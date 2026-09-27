"""Verify one platform-neutral lifecycle against the real scoped Runtime.

使用真实作用域 Runtime 验证平台中立生命周期；输入均为隔离合成数据。
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from character_runtime.identity import bind
from character_runtime.lifecycle import HostCapabilities, TurnEnvelope, TurnLifecycle
from character_runtime.models import CharacterDefinition, VoiceProfile
from character_runtime.operations import fingerprint
from character_runtime.persistence_models import GenerationRequest
from character_runtime.runtime import Runtime
from character_runtime.scope import ScopeResolver
from character_runtime.storage import SQLiteStorage


def reject(action):
    try:
        action()
    except ValueError:
        return
    raise AssertionError("Unsafe lifecycle operation succeeded")


def continuity_checks(rt, envelope, capabilities, path):
    """Replay task contracts without a reminder; synthetic responses are not an LLM test.

    连续回放任务契约，不提醒恢复角色；合成回复不冒充真实模型行为验收。
    """
    cases = [
        ("普通闲聊", {}, "聊聊吧。", True),
        ("技术解释", {"intent": "EXPLANATION"}, "先看输入与输出的关系。", True),
        (
            "数据分析",
            {
                "intent": "ANALYSIS",
                "protected_payloads": [
                    {"kind": "EXACT_NUMERIC_DATA", "content": "25.3%"},
                    {"kind": "EXACT_NUMERIC_DATA", "content": "659Mi/1.9Gi"},
                    {"kind": "EXACT_NUMERIC_DATA", "content": "67%"},
                ],
            },
            "CPU 25.3%，内存 659Mi/1.9Gi，磁盘 67%。先看增长速度。",
            True,
        ),
        ("Docker 成功结果解读", {"intent": "TOOL_TASK"}, "根据这份结果，容器在运行。", True),
        ("工具失败", {"intent": "TOOL_TASK"}, "工具没连上，这次没查到。", True),
        (
            "写 Python",
            {"intent": "CODING", "explicit_format": "code"},
            "先跑这句：\n```python\nprint(42)\n```",
            True,
        ),
        (
            "only Python code",
            {
                "intent": "CODING",
                "explicit_format": "code",
                "payload_only": True,
                "protected_payloads": [{"kind": "CODE", "content": "print(42)"}],
            },
            "print(42)",
            False,
        ),
        ("解释刚才代码", {"intent": "EXPLANATION"}, "这句会输出 42。", True),
        ("only JSON", {"explicit_format": "json", "payload_only": True}, '{"ok":true}', False),
        ("普通自然语言", {}, "接着聊吧。", True),
        ("情绪聊天", {"intent": "EMOTIONAL_SUPPORT"}, "嗯，我听着。", True),
        ("再次技术任务", {"intent": "TOOL_TASK"}, "先确认配置项的含义。", True),
        ("本轮中性回答", {"neutral_expression": True}, "已记录本轮要求。", False),
        ("下一轮自然回答", {}, "说到哪儿了？", True),
    ]
    lifecycle = TurnLifecycle(rt)
    character = rt.characters.get(
        lifecycle.prepare(envelope, capabilities)["character_id"]
    ).model_dump()
    trace = []
    for index, (text, spec, response, enabled) in enumerate(cases):
        request = GenerationRequest.model_validate(spec)
        current = envelope.model_copy(
            update={
                "turn_id": f"sequence-{index}",
                "message_id": f"sequence-{index}",
                "text": text,
                "generation": request,
            }
        )
        prepared = lifecycle.prepare(current, capabilities)
        context = prepared["context"]
        diagnostic = context["context_diagnostics"]
        assert (
            diagnostic["active"]
            and diagnostic["definition_present"]
            and diagnostic["state_present"]
        )
        assert diagnostic["character_id"] == character["id"]
        assert diagnostic["character_expression_enabled"] is enabled
        assert diagnostic["effective_mode"] == "soft_roleplay"
        generation = diagnostic["generation"]
        assert generation["explicit_format"] == spec.get("explicit_format", "natural")
        assert generation["payload_only"] is spec.get("payload_only", False)
        assert generation["neutral_expression"] is spec.get("neutral_expression", False)
        assert len(generation["protected_payloads"]) == len(spec.get("protected_payloads", []))
        tid = prepared["turn_id"]
        # A new storage/Runtime instance must recover exactly this turn's contract.
        # 新存储连接及 Runtime 实例须恢复本轮契约，不能靠内存缓存维持。
        reopened = SQLiteStorage(path)
        try:
            restored = Runtime(reopened, "owner", clock=rt.clock).for_turn(tid).context(tid)
            assert restored["context_diagnostics"]["generation"] == generation
        finally:
            reopened.close()
        observed = lifecycle.observe_generation(tid, "sequence-observation", response)
        assert observed["contract_valid"] and observed["delivery_state"] == "unknown"
        lifecycle.finalize(tid, "sequence-finalize")
        assert not any(
            e["source_kind"] == "ASSISTANT_VISIBLE"
            for e in rt.for_turn(tid).knowledge.records("raw_event", character["id"])
        )
        trace.append(
            {
                "step": index + 1,
                "character_id": character["id"],
                "turn_id": tid,
                "session_id": context["session_id"],
                "enabled": enabled,
                **generation,
            }
        )
    assert rt.characters.get(character["id"]).model_dump() == character
    print("PASS synthetic continuity sequence: " + json.dumps(trace, ensure_ascii=False))


def main():
    with TemporaryDirectory() as directory:
        path = Path(directory) / "runtime.sqlite3"
        store = SQLiteStorage(path)
        instant = datetime(2026, 9, 23, tzinfo=UTC)
        rt = Runtime(store, "owner", clock=lambda: instant)
        cid = rt.characters.create(
            CharacterDefinition(name="continuous", voice=VoiceProfile(catchphrases=["owo"]))
        ).id
        resolver = ScopeResolver(store, "owner", rt.clock)
        for who in ("alice", "bob"):
            bind(store, "owner", "host", "app", who, who, "verified", participant_id=who)
        dm = resolver.bind_endpoint(
            "app",
            "dm",
            "dm",
            cid,
            operation_id="dm",
            confirmation="verified",
            participant_id="alice",
        )
        group = resolver.bind_endpoint(
            "app", "group", "group", cid, operation_id="group", confirmation="verified"
        )
        lifecycle = TurnLifecycle(rt)
        envelope = TurnEnvelope(
            host_id="host",
            platform="app",
            actor_id="alice",
            endpoint_id=dm["id"],
            chat_type="dm",
            session_id="s",
            turn_id="t",
            message_id="m",
            text="private input " + "x" * 5000,
        )
        capabilities = HostCapabilities(pre_generation=True, post_generation=True)
        prepared = lifecycle.prepare(envelope, capabilities)
        tid = prepared["turn_id"]
        scoped = rt.for_turn(tid)
        assert prepared["context"]["stable_prefix"]
        assert lifecycle.prepare(envelope, capabilities)["turn_id"] == tid
        events = scoped.knowledge.records("raw_event", cid)
        assert len(events) == 1 and events[0]["content"] == envelope.text
        assert events[0]["timestamp_basis"] == "observed"
        record = scoped.storage.get("owner", "turn_lifecycle", tid)
        assert record["source_timestamp"] is None and record["observed_at"] == instant.isoformat()
        # Simulate a prepared turn saved before input_is_verbatim was introduced.
        # 模拟增加 input_is_verbatim 字段前保存的中断回合，不得重复摄入或放宽输入。
        record["fingerprint"] = fingerprint(
            [
                envelope.model_dump(mode="json", exclude={"input_is_verbatim"}),
                capabilities.model_dump(),
            ]
        )
        scoped.storage.put("owner", "turn_lifecycle", tid, record)
        assert lifecycle.prepare(envelope, capabilities)["turn_id"] == tid
        reject(
            lambda: lifecycle.prepare(
                envelope.model_copy(update={"input_is_verbatim": False}), capabilities
            )
        )
        assert len(scoped.knowledge.records("raw_event", cid)) == 1
        assert "derived_turn_signals" in str(prepared["context"]["temporary"])
        reject(lambda: lifecycle.finalize(tid, "finish"))
        result = lifecycle.observe_generation(tid, "response", "private generated text owo")
        assert result["state"] == "generated" and result["delivery_state"] == "unknown"
        assert lifecycle.observe_generation(tid, "response", "private generated text owo") == result
        reject(lambda: lifecycle.observe_generation(tid, "response", "changed text"))
        assert lifecycle.finalize(tid, "finish")["state"] == "finalized"
        policy = next(
            f["payload"]["expression_policy"]
            for f in scoped.context(tid)["temporary"]["state"]
            if "expression_policy" in f["payload"]
        )
        assert policy["catchphrase_options"] == [], "No-ACK generation failed to cool repetition"
        assert policy["frequency"]["generated_observations"] == 1
        assert lifecycle.finalize(tid, "finish")["state"] == "finalized"
        assert not any(
            e["source_kind"] == "ASSISTANT_VISIBLE"
            for e in scoped.knowledge.records("raw_event", cid)
        )
        unverified = envelope.model_copy(
            update={"turn_id": "decorated", "text": "host-added text", "input_is_verbatim": False}
        )
        fallback = lifecycle.prepare(unverified, capabilities)
        assert fallback["context"]["stable_prefix"]
        assert len(scoped.knowledge.records("raw_event", cid)) == 1
        public = lifecycle.prepare(
            envelope.model_copy(
                update={
                    "endpoint_id": group["id"],
                    "chat_type": "group",
                    "turn_id": "g",
                    "text": "public input",
                    "actor_id": "bob",
                }
            ),
            capabilities,
        )
        public_rt = rt.for_turn(public["turn_id"])
        assert not public_rt.storage.get("owner", "turn_lifecycle", tid)
        assert "private generated text" not in str(public["context"])
        ambient = lifecycle.observe_ambient(
            envelope.model_copy(
                update={
                    "endpoint_id": group["id"],
                    "chat_type": "group",
                    "actor_id": "bob",
                    "turn_id": "ambient",
                    "message_id": "ambient",
                    "text": "ambient-public-sentinel",
                }
            ),
            HostCapabilities(ambient_messages=True),
        )
        reject(lambda: lifecycle.observe_generation(ambient["turn_id"], "no", "not requested"))
        public_context = public_rt.context(public["turn_id"])
        assert "ambient-public-sentinel" in str(public_context["temporary"].get("ambient_window"))
        assert "public input" in str(public_context["temporary"].get("recent_turn_window"))
        assert "ambient-public-sentinel" not in str(scoped.context(tid))
        assert "private input" not in str(public_context)
        # Re-reading the same prepared turn must keep its output contract, but a new
        # turn must not inherit JSON, neutral style or protected literal values.
        # 重读已准备回合须保留输出契约；新回合不能继承 JSON、中性表达或精确载荷。
        json_turn = lifecycle.prepare(
            envelope.model_copy(
                update={
                    "turn_id": "json",
                    "message_id": "json",
                    "text": "only JSON",
                    "generation": GenerationRequest(explicit_format="json", payload_only=True),
                }
            ),
            capabilities,
        )
        json_rt = rt.for_turn(json_turn["turn_id"])
        again = json_rt.context(json_turn["turn_id"])
        again_policy = next(
            f["payload"]["expression_policy"]
            for f in again["temporary"]["state"]
            if "expression_policy" in f["payload"]
        )
        assert again_policy["payload_only"], "Same-turn context lost prepared output contract"
        assert not again_policy["character_expression"]["enabled"]
        reject(lambda: json_rt.context(json_turn["turn_id"], generation=GenerationRequest()))
        natural_turn = lifecycle.prepare(
            envelope.model_copy(
                update={
                    "turn_id": "natural",
                    "message_id": "natural",
                    "text": "继续聊聊",
                }
            ),
            capabilities,
        )
        natural = natural_turn["context"]
        assert natural["character_id"] == cid
        assert natural["context_diagnostics"]["generation"]["payload_only"] is False
        assert natural["context_diagnostics"]["character_expression_enabled"] is True
        continuity_checks(rt, envelope, capabilities, path)
        reject(
            lambda: lifecycle.prepare(
                envelope.model_copy(update={"chat_type": "group"}), capabilities
            )
        )
        reject(
            lambda: lifecycle.prepare(
                envelope.model_copy(update={"actor_id": "unknown"}), capabilities
            )
        )
        reject(
            lambda: lifecycle.prepare(
                envelope.model_copy(
                    update={"turn_id": "future", "timestamp": instant + timedelta(days=1)}
                ),
                capabilities,
            )
        )
        from character_runtime.conversation import erase_response_context

        erase_response_context(scoped.storage, "owner", cid)
        assert scoped.storage.get("owner", "turn_lifecycle", tid)["generated_text"] == ""
        reject(lambda: lifecycle.observe_generation(tid, "late", "resurrected"))
        store.close()
        store = SQLiteStorage(path)
        try:
            restored = TurnLifecycle(Runtime(store, "owner", clock=lambda: instant))
            reject(lambda: restored.observe_generation(tid, "late", "resurrected"))
        finally:
            store.close()
    print(
        "PASS lifecycle: scoped ingress, source time, long task, "
        "generation != delivery, erasure/restart"
    )


if __name__ == "__main__":
    main()
