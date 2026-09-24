"""Verify one platform-neutral lifecycle against the real scoped Runtime.

使用真实作用域 Runtime 验证平台中立生命周期；输入均为隔离合成数据。
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from character_runtime.identity import bind
from character_runtime.lifecycle import HostCapabilities, TurnEnvelope, TurnLifecycle
from character_runtime.models import CharacterDefinition, VoiceProfile
from character_runtime.operations import fingerprint
from character_runtime.runtime import Runtime
from character_runtime.scope import ScopeResolver
from character_runtime.storage import SQLiteStorage


def reject(action):
    try:
        action()
    except ValueError:
        return
    raise AssertionError("Unsafe lifecycle operation succeeded")


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
