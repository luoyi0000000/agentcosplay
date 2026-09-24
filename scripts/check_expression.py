"""Verify character continuity and content contracts with synthetic local characters.

用临时合成人物验证任务中的角色连续性和内容约束；不调用第二个模型。
"""

import json
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import get_args

from character_runtime.cognition import expression, expression_frequency, validate_response
from character_runtime.knowledge_models import EventBatch, EventInput
from character_runtime.models import CharacterDefinition, VoiceProfile, now
from character_runtime.persistence_models import (
    GenerationIntent,
    GenerationRequest,
    GrowthCandidate,
    GrowthChange,
)
from character_runtime.runtime import Runtime
from character_runtime.storage import SQLiteStorage


def main() -> None:
    with TemporaryDirectory(prefix="agentcosplay-expression-") as directory:
        with_store = SQLiteStorage(Path(directory) / "runtime.sqlite3")
        try:
            rt = Runtime(with_store, "owner")
            voice = VoiceProfile.model_validate(
                {
                    "catchphrases": ["owo"],
                    "catchphrase_rules": [
                        {"phrase": "owo", "usage": ["playful surprise"], "cooldown_seconds": 120}
                    ],
                    "preferred_vocabulary": ["先拆开看"],
                    "avoided_vocabulary": ["综上所述"],
                    "sentence_rhythm": "短句与停顿交替",
                    "explanation_style": "先结论，再拆因果",
                    "analogy_style": "用日常物件解释",
                    "evaluation_style": "直白但保留条件",
                    "disagreement_style": "先说明分歧依据",
                    "question_style": "只追问关键缺口",
                    "dialogue_examples": [
                        {
                            "meaning": "configuration mismatch",
                            "character": "这里配歪啦，先看这一项。",
                        }
                    ],
                }
            )
            cid = rt.characters.create(CharacterDefinition(name="岚", voice=voice)).id
            rt.open_session("chat", character_id=cid)
            first = rt.context("chat")["stable_prefix"]
            for intent in get_args(GenerationIntent):
                context = rt.context("chat", generation=GenerationRequest(intent=intent))
                assert context["stable_prefix"] == first
                assert json.loads(first)["character"]["id"] == cid
                assert context["effective_mode"] == "soft_roleplay"
            policy = expression(
                GenerationRequest(intent="CODING", explicit_format="code"),
                VoiceProfile(),
                {},
                "soft_roleplay",
            )
            assert policy["catchphrase_density"] != "none"
            assert "precedence" not in policy
            assert policy["character_expression"]["enabled"]
            raw = expression(
                GenerationRequest(intent="CODING", explicit_format="json", payload_only=True),
                VoiceProfile(),
                {},
                "soft_roleplay",
            )
            assert (
                raw["catchphrase_density"] == "none" and not raw["character_expression"]["enabled"]
            )
            neutral = expression(
                GenerationRequest(intent="ANALYSIS"), VoiceProfile(), {}, "task_neutral"
            )
            assert neutral["directness"] is None and neutral["warmth"] is None
            policy = next(
                f["payload"]["expression_policy"]
                for f in rt.context("chat")["temporary"]["state"]
                if "expression_policy" in f["payload"]
            )
            assert policy["catchphrase_options"] == ["owo"]
            rt.knowledge.ingest(
                EventBatch(
                    session_id="chat",
                    operation_id="delivered",
                    events=[
                        EventInput(
                            source_id="host",
                            source_event_id="delivered-one",
                            source_kind="ASSISTANT_VISIBLE",
                            content="这下明白了 owo",
                            timestamp=now(),
                        )
                    ],
                )
            )
            policy = next(
                f["payload"]["expression_policy"]
                for f in rt.context("chat")["temporary"]["state"]
                if "expression_policy" in f["payload"]
            )
            assert policy["catchphrase_options"] == []
            usage = [
                {"source_kind": "GENERATED_OBSERVATION", "content": "值得注意的是，条件仍成立。"}
            ] * 2
            frequency = expression_frequency(voice, usage)
            assert frequency["avoid_overuse"] == ["值得注意的是"]
            assert frequency["generated_observations"] == 2
            assert usage[0]["content"] == "值得注意的是，条件仍成立。"
            rt.session_control("chat", "enter_ooc")
            context = rt.context("chat")
            policy = next(
                f["payload"]["expression_policy"]
                for f in context["temporary"]["state"]
                if "expression_policy" in f["payload"]
            )
            assert policy["catchphrase_density"] == "none"
            rt.session_control("chat", "exit_ooc")
            assert rt.context("chat")["stable_prefix"] == first
            protected = GenerationRequest.model_validate(
                {
                    "intent": "CODING",
                    "explicit_format": "code",
                    "protected_payloads": [{"kind": "CODE", "content": 'print("owo")'}],
                }
            )
            validate_response('看这里：\n```python\nprint("owo")\n```\n这样就好啦。', protected)
            try:
                validate_response('print("uwu")', protected)
            except ValueError:
                pass
            else:
                raise AssertionError("Protected code was rewritten")
            json_only = GenerationRequest(explicit_format="json", payload_only=True)
            validate_response('{"ok":true}', json_only)
            for bad in (
                '```json\n{"ok":true}\n```',
                '{"ok":true} owo',
                '{"value":NaN}',
                '{"ok":true,"ok":false}',
            ):
                try:
                    validate_response(bad, json_only)
                except ValueError:
                    pass
                else:
                    raise AssertionError("Invalid raw JSON accepted")
            evidence = rt.knowledge.ingest(
                EventBatch(
                    session_id="chat",
                    operation_id="growth-evidence",
                    events=[
                        EventInput(
                            source_id="growth",
                            source_event_id=str(day),
                            source_kind="USER_DIRECT",
                            content="humor preference",
                            timestamp=now() - timedelta(days=day),
                        )
                        for day in range(3)
                    ],
                )
            )
            humor = rt.knowledge.growth.propose(
                GrowthCandidate(
                    character_id=cid,
                    changes=[GrowthChange(domain="voice", key="humor_style", value="dry irony")],
                    evidence_refs=evidence["event_ids"],
                    reason="synthetic review",
                )
            )
            assert humor["status"] == "pending" and humor["impact"] == "high"
            assert rt.knowledge.growth.current(cid)[0] == "baseline"
            rt.session_control("chat", "start_task", mode="task_neutral")
            assert rt.context("chat")["effective_mode"] == "task_neutral"
            rt.session_control("chat", "end_task")
            assert rt.context("chat")["effective_mode"] == "soft_roleplay"
        finally:
            with_store.close()
    print("PASS expression: all task identities, explicit OOC/neutral, role restoration")


if __name__ == "__main__":
    main()
