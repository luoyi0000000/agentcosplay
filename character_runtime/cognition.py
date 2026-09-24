"""Structured host intent routing, expression policy and explicit temporal recall.

结构化宿主意图路由、表达策略及显式时间召回。
"""

import json
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .models import CatchphraseRule, VoiceProfile
from .persistence_models import GenerationRequest, RecallRequest


def expression(
    request: GenerationRequest, voice: VoiceProfile, relationship: dict[str, Any], mode: str
) -> dict[str, Any]:
    """Apply content constraints beside character expression, never above its existence.

    内容约束与角色表达并行；专业任务改变完成标准，不改变“谁在说话”。
    """
    suppressed = request.payload_only or request.neutral_expression or mode == "task_neutral"
    analytical = request.intent in {"ANALYSIS", "EXPLANATION", "CODING", "FACTUAL_QA", "TOOL_TASK"}
    return {
        "intent": request.intent,
        "format": request.explicit_format,
        "payload_only": request.payload_only,
        "user_length_request": request.length_request,
        "platform_constraints": request.platform_constraints,
        "content_constraints": [
            "safety",
            "factual_correctness",
            "tool_truth",
            "requested_format",
            "exact_data",
            "citation_integrity",
            "protected_payload_integrity",
        ],
        "character_expression": {
            "enabled": not suppressed,
            "identity": "same active character",
            "voice_source": None
            if suppressed
            else "stable voice + approved overlay + private turn adaptation",
            "restraint": "task-appropriate" if mode == "soft_roleplay" else "full",
            "rule": "Facts are not roleplayed; expression is character-owned.",
        },
        "verbosity": "task-required"
        if suppressed or analytical or request.length_request
        else voice.verbosity_default,
        "directness": None if suppressed else voice.directness,
        "sentence_target": None if suppressed else voice.sentence_length,
        "warmth": None
        if suppressed
        else "respectful"
        if relationship.get("stage") == "stranger"
        else "familiar",
        "explanation_depth": "complete when required by the task"
        if analytical
        else "conversational",
        "catchphrase_density": "none"
        if suppressed or request.serious_safety
        else "optional, sparse, never mandatory",
        "stage_direction_policy": "none" if suppressed else voice.stage_direction_policy,
        "protected_payloads": (
            "Never stylize code, JSON, commands, URLs, quotes, numbers or tool output; "
            "surrounding prose retains character voice."
        ),
        "history_is_voice_training": False,
        "hard_output_truncation": False,
    }


def catchphrase_options(
    voice: VoiceProfile,
    events: list[dict[str, Any]],
    instant: datetime,
    request: GenerationRequest,
) -> list[str]:
    """Use visible and generated observations for cooldown, never new voice authority.

    已发送及生成观察只计算冷却，不学习新的声音权威；建议不代表强制使用。
    """
    if request.payload_only or request.neutral_expression or request.serious_safety:
        return []
    rules = {r.phrase: r for r in voice.catchphrase_rules}
    for phrase in voice.catchphrases:
        # Legacy long examples remain baseline data, not generated suffix templates.
        # 旧长句保留在基线里，但不当作自动追加的句尾模板。
        if len(phrase) <= 80:
            rules.setdefault(phrase, CatchphraseRule(phrase=phrase))
    available = []
    for phrase, rule in rules.items():
        if request.intent in rule.avoid_contexts:
            continue
        recent = any(
            e.get("source_kind") in {"ASSISTANT_VISIBLE", "GENERATED_OBSERVATION"}
            and e.get("validity") == "active"
            and not e.get("legacy_unverified")
            and phrase in e.get("content", "")
            and 0
            <= (instant - datetime.fromisoformat(e["timestamp"])).total_seconds()
            < rule.cooldown_seconds
            for e in events
        )
        if not recent:
            available.append(phrase)
    return available


def expression_observations(
    events: list[dict[str, Any]], turns: list[dict[str, Any]], instant: datetime
) -> list[dict[str, Any]]:
    """Build an ephemeral scoped usage window; generated text is never delivery evidence.

    构建临时且已授权的表达使用窗口；生成正文绝不变成发送证据或声音训练数据。
    """
    visible = [
        e
        for e in events
        if e.get("source_kind") == "ASSISTANT_VISIBLE"
        and e.get("validity") == "active"
        and not e.get("legacy_unverified")
    ]
    delivered_turns = {e["session_id"] for e in visible}
    generated = [
        {
            "source_kind": "GENERATED_OBSERVATION",
            "validity": "active",
            "timestamp": t["generated_at"],
            "content": t["generated_text"],
        }
        for t in turns
        if t.get("state") in {"generated", "finalized"}
        and not t.get("erased")
        and t.get("generated_text")
        and t["id"] not in delivered_turns
    ]
    observations = [
        e
        for e in [*visible, *generated]
        if 0 <= (instant - datetime.fromisoformat(e["timestamp"])).total_seconds() < 86400
    ]
    return sorted(observations, key=lambda e: e["timestamp"])[-12:]


def expression_frequency(voice: VoiceProfile, observations: list[dict[str, Any]]) -> dict[str, Any]:
    """Advise against repeated rhetoric without rewriting payloads or banning useful words.

    根据近期频率建议减少重复修辞，不改写载荷，也不将有用词语列为硬禁词。
    """
    markers = dict.fromkeys(
        [
            *voice.avoided_patterns,
            *voice.avoided_vocabulary,
            *voice.preferred_patterns,
            "值得注意的是",
            "总而言之",
            "综上所述",
            "换句话说",
            "本质上",
        ]
    )
    counts = {
        phrase: sum(phrase.casefold() in e["content"].casefold() for e in observations)
        for phrase in markers
    }
    threshold = 2 if voice.repetition_tolerance == "low" else 3
    return {
        "window_size": len(observations),
        "generated_observations": sum(
            e["source_kind"] == "GENERATED_OBSERVATION" for e in observations
        ),
        "avoid_overuse": [phrase for phrase, count in counts.items() if count >= threshold][:6],
        "novelty_pressure": "vary phrasing"
        if any(c >= threshold for c in counts.values())
        else "normal",
        "rule": (
            "Usage hints only; preserve facts, necessary terminology and protected payloads. "
            "Generated observations do not prove delivery."
        ),
    }


def validate_response(text: str, request: GenerationRequest) -> None:
    """Reject corrupted exact content without rewriting it or calling another model.

    拒绝损坏的精确内容，不自动改写，也不调用第二个模型修复。
    This validates declared payload integrity, not the truth or correctness of new model output.
    此检查验证已声明载荷的完整性，不声称验证模型新生成内容的真实性或正确性。
    """
    if not text or len(text) > 64000:
        raise ValueError("Response must contain 1..64000 characters")
    for payload in request.protected_payloads:
        if payload.content not in text:
            raise ValueError("Protected payload changed or missing")
    if not request.payload_only:
        return
    if request.explicit_format in {"json", "code", "verbatim"} and text.lstrip().startswith("```"):
        raise ValueError("Payload-only output cannot have Markdown fences")
    if request.explicit_format == "json":

        def constant(value: str) -> Any:
            raise ValueError("Raw JSON cannot contain non-finite numbers")

        def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Raw JSON cannot contain duplicate keys")
                result[key] = value
            return result

        json.loads(text, parse_constant=constant, object_pairs_hook=object_pairs)
    if len(request.protected_payloads) == 1 and request.explicit_format in {"code", "verbatim"}:
        if text != request.protected_payloads[0].content:
            raise ValueError("Exact payload-only output cannot have wrappers")


def window(request: RecallRequest, instant: datetime) -> tuple[datetime | None, datetime | None]:
    """Resolve explicit temporal recall bounds without promoting recollection to truth.

    解析显式时间召回边界，不把回忆提升为事实。
    """

    if request.start and request.end and request.start >= request.end:
        raise ValueError("Recall start must precede end")
    if request.relative_window:
        if request.start or request.end:
            raise ValueError("Choose an explicit or relative time window, not both")
        local = instant.astimezone(ZoneInfo(request.timezone))
        today = datetime.combine(local.date(), time.min, tzinfo=local.tzinfo)
        if request.relative_window == "today":
            return today, today + timedelta(days=1)
        if request.relative_window == "yesterday":
            return today - timedelta(days=1), today
        monday = today - timedelta(days=today.weekday())
        return monday - timedelta(days=7), monday
    if request.intent == "TIME_WINDOW" and not (request.start or request.end):
        raise ValueError(
            "TIME_WINDOW requires dates or a relative window; ask the host to resolve them"
        )
    return request.start, request.end


def classify_conflict(
    old: str, new: str, *, same_slot: bool = False, proposed: str = "UNRELATED"
) -> str:
    """Classify contradictions for review rather than silently overwrite evidence.

    分类矛盾供审查，不静默覆盖证据。
    """

    from .retrieval import normalize

    if old == new:
        return "EXACT_DUPLICATE"
    if normalize(old) == normalize(new):
        return "NEAR_DUPLICATE"
    if proposed in {"CORRECTION", "CONTRADICTION", "SUPERSEDING_UPDATE", "SUPPLEMENT"}:
        return proposed
    return "CONTRADICTION" if same_slot else "UNRELATED"
