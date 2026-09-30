"""Verify persistent conversations separately from scoped turns, using real local storage.
使用真实本地存储验证持久会话与单轮权限分离。
"""

import asyncio
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from character_runtime.conversation import turn_windows
from character_runtime.hermes_adapter import HermesAdapter
from character_runtime.host_client import HostBridge
from character_runtime.host_protocol import ScopedToolRouter
from character_runtime.host_session import HostSessionIdentity, SessionRegistry
from character_runtime.identity import bind
from character_runtime.lifecycle import HostCapabilities, TurnEnvelope, TurnLifecycle
from character_runtime.models import CharacterDefinition
from character_runtime.operations import fingerprint
from character_runtime.persistence_models import GenerationRequest
from character_runtime.runtime import Runtime
from character_runtime.scope import ScopeResolver
from character_runtime.storage import SQLiteStorage


def legacy_recovery():
    """Replay a legacy receipt without renewing its authorization or skipping registration.
    重放旧收据不得延长权限，也不得跳过会话注册。
    """
    with TemporaryDirectory() as tmp, closing(SQLiteStorage(Path(tmp) / "legacy.db")) as db:
        rt = Runtime(db, "owner")
        cid = rt.characters.create(CharacterDefinition(name="legacy")).id
        bind(db, "owner", "host", "app", "actor", "bind", "verified")
        endpoint = ScopeResolver(db, "owner").bind_endpoint(
            "app",
            "dm",
            "dm",
            cid,
            operation_id="endpoint",
            confirmation="verified",
            participant_id="owner",
        )
        env = TurnEnvelope(
            host_id="host",
            platform="app",
            actor_id="actor",
            endpoint_id=endpoint["id"],
            chat_type="dm",
            session_id="native",
            turn_id="turn",
            message_id="message",
            text="hello",
        )
        caps = HostCapabilities(pre_generation=True)
        before = TurnLifecycle(rt).prepare(env, caps)
        sid = before["session_id"]
        session = db.get("owner", "conversation_session", sid)
        mapping_id = session.pop("mapping_id")
        session.pop("host_identity")
        session["legacy_unknown"] = {"keep": True}
        db.put("owner", "conversation_session", sid, session)
        db.delete("owner", "host_session", mapping_id)
        request = fingerprint([env.session_id, env.turn_id])
        current_key = fingerprint(
            [env.host_id, env.platform, env.endpoint_id, env.session_id, request]
        )
        receipt = db.get("owner", "turn_receipt", current_key)
        db.delete("owner", "turn_receipt", current_key)
        db.put("owner", "turn_receipt", fingerprint([env.host_id, request]), receipt)
        expires = ScopeResolver(db, "owner").load_turn(before["turn_id"]).expires_at
        after = TurnLifecycle(rt).prepare(env, caps)
        assert after["turn_id"] == before["turn_id"] and after["session_id"] == sid
        assert ScopeResolver(db, "owner").load_turn(after["turn_id"]).expires_at == expires
        assert db.get("owner", "conversation_session", sid)["legacy_unknown"] == {"keep": True}
        SessionRegistry(db, "owner").transition(sid, "rotate", "reset")


def main():
    legacy_recovery()

    async def propagated():
        async def capture(self, tool, arguments, **kwargs):
            return arguments

        with TemporaryDirectory() as directory, patch.object(HostBridge, "call", capture):
            # Mocked transport needs an OS-native absolute path, not a credential file.
            # 模拟传输仅需要本机绝对路径，不需要创建凭据文件。
            bridge = HostBridge("http://127.0.0.1:8765/mcp", Path(directory).resolve() / "token")
            result = await bridge.model_call("cap", "turn", "runtime_context", {})
            assert result.get("session_id") == "turn", "Current scope was not injected"
            result = await bridge.model_call(
                "cap",
                "turn",
                "session_control",
                {"request": {"action": "enter_ooc"}},
                session_id="canonical",
            )
            assert result["request"]["session_id"] == "canonical"
            for arguments in (
                {"request": {"action": "open"}},
                {"request": {"action": "enter_ooc", "session_id": "native:v4"}},
            ):
                try:
                    await bridge.model_call(
                        "cap", "turn", "session_control", arguments, session_id="canonical"
                    )
                except ValueError:
                    pass
                else:
                    raise AssertionError("Model created or selected a session")
            schema = {
                "$defs": {
                    "Request": {
                        "properties": {"session_id": {"type": "string"}},
                        "required": ["session_id", "action"],
                    }
                }
            }
            hidden = ScopedToolRouter.schema("session_control", schema)
            assert hidden["$defs"]["Request"]["required"] == ["action"]
            assert "session_id" in schema["$defs"]["Request"]["properties"]

    asyncio.run(propagated())
    with TemporaryDirectory() as tmp, closing(SQLiteStorage(Path(tmp) / "runtime.sqlite3")) as db:
        rt = Runtime(db, "owner")
        cid = rt.characters.create(CharacterDefinition(name="synthetic")).id
        bind(db, "owner", "harness", "app", "actor", "bind", "verified")
        endpoint = ScopeResolver(db, "owner").bind_endpoint(
            "app",
            "dm",
            "dm",
            cid,
            operation_id="endpoint",
            confirmation="verified",
            participant_id="owner",
        )
        envelope = TurnEnvelope(
            host_id="harness",
            platform="app",
            actor_id="actor",
            endpoint_id=endpoint["id"],
            chat_type="dm",
            session_id="external-conversation",
            turn_id="one",
            message_id="one",
            text="hello",
        )
        caps = HostCapabilities(pre_generation=True, post_generation=True)
        bind(db, "owner", "hermes", "app", "actor", "cli-bind", "verified")

        class LocalBridge(HostBridge):
            async def call(self, tool, arguments, **kwargs):
                if tool == "host_prepare_turn":
                    value = TurnLifecycle(rt).prepare(
                        TurnEnvelope.model_validate(arguments["envelope"]),
                        HostCapabilities.model_validate(arguments["capabilities"]),
                    )
                    return {**value, "capability": value["turn_id"]}
                if tool == "host_session_control":
                    return SessionRegistry(db, "owner").transition(**arguments)
                scoped = rt.for_turn(kwargs["capability"])
                if tool == "runtime_context":
                    return scoped.context(**arguments)
                raise AssertionError("Unexpected test transport operation")

        async def cli():
            adapter = HermesAdapter(
                "http://127.0.0.1:8765/mcp",
                Path(tmp).resolve() / "token",
                "hermes",
                [],
                cli_binding={
                    "actor_id": "actor",
                    "runtime_platform": "app",
                    "endpoint_id": endpoint["id"],
                },
            )
            adapter.bridge = LocalBridge(adapter.bridge.url, adapter.bridge.token_file)
            for turn in ("cli-one", "cli-two"):
                context = await adapter.context(
                    {}, platform="cli", session_id="terminal", turn_id=turn, user_message="hello"
                )
                assert "Runtime session_id:" in context, "CLI did not register its Runtime session"
                response = await adapter.execute_tool(("terminal", turn), "runtime_context", {})
                assert response["ok"] and response["result"]["character_id"] == cid
            assert (
                adapter.turns.get(("terminal", "cli-one")).runtime_session_id
                == adapter.turns.get(("terminal", "cli-two")).runtime_session_id
            )
            adapter.clear(session_id="terminal")
            await adapter.context(
                {}, platform="cli", session_id="terminal", turn_id="cli-three", user_message="hello"
            )
            assert adapter.turns.get(("terminal", "cli-three")) is not None
            old = adapter.turns.get(("terminal", "cli-three"))
            await adapter.context(
                {},
                platform="cli",
                session_id="other-terminal",
                turn_id="other",
                user_message="hello",
            )
            ticket = adapter.turns.reserve(("terminal", "late"))
            await adapter.session_boundary(("terminal", "cli-three"), "rotate", "cli-reset")
            assert adapter.turns.get(("other-terminal", "other")) is not None
            assert not adapter.turns.complete(("terminal", "late"), ticket, old)
            await adapter.context(
                {}, platform="cli", session_id="terminal", turn_id="cli-four", user_message="hello"
            )
            assert (
                adapter.turns.get(("terminal", "cli-four")).runtime_session_id
                != old.runtime_session_id
            )

        asyncio.run(cli())
        locked = TurnLifecycle(rt).prepare(
            envelope.model_copy(
                update={
                    "turn_id": "locked",
                    "message_id": "locked",
                    "generation": GenerationRequest(neutral_expression=True),
                }
            ),
            caps,
        )
        locked_rt = rt.for_turn(locked["turn_id"])
        assert locked_rt.context(locked["session_id"])["context_diagnostics"]["generation"][
            "neutral_expression"
        ], "Canonical session tools lost the prepared turn contract"
        try:
            locked_rt.context(locked["session_id"], generation=GenerationRequest())
        except ValueError:
            pass
        else:
            raise AssertionError("Canonical session bypassed immutable generation contract")
        first = TurnLifecycle(rt).prepare(envelope, caps)
        assert first.get("session_id"), "Bridge failed to propagate canonical conversation ID"
        sid = first["session_id"]
        assert sid not in {envelope.session_id, first["turn_id"]}
        scoped = rt.for_turn(first["turn_id"])
        assert scoped.context(sid)["character_id"] == cid
        scoped.session_control(sid, "enter_ooc")
        second = TurnLifecycle(Runtime(db, "owner")).prepare(
            envelope.model_copy(update={"turn_id": "two", "message_id": "two"}),
            caps,
        )
        assert second["session_id"] == sid and second["turn_id"] != first["turn_id"]
        assert rt.for_turn(second["turn_id"]).context(sid)["ooc"]
        scoped_second = rt.for_turn(second["turn_id"])
        canonical_signals = turn_windows(scoped_second, cid, sid)["derived_turn_signals"]
        alias_signals = turn_windows(scoped_second, cid, second["turn_id"])["derived_turn_signals"]
        assert canonical_signals["exact_repeat_count"] == alias_signals["exact_repeat_count"] > 0
        other_endpoint = ScopeResolver(db, "owner").bind_endpoint(
            "app",
            "other-dm",
            "dm",
            cid,
            operation_id="other-endpoint",
            confirmation="verified",
            participant_id="owner",
        )
        isolated = TurnLifecycle(rt).prepare(
            envelope.model_copy(update={"endpoint_id": other_endpoint["id"]}),
            caps,
        )
        assert isolated["session_id"] != sid, "Native IDs collided across endpoints"
        try:
            rt.for_turn(second["turn_id"]).context("external-conversation:v4")
        except KeyError:
            pass
        else:
            raise AssertionError("Unregistered model session accepted")
        # A separate storage connection exercises durable recovery, not a process dictionary.
        # 独立存储连接验证持久恢复，而不是复用进程内字典。
        with closing(SQLiteStorage(Path(tmp) / "runtime.sqlite3")) as reopened:
            resumed = TurnLifecycle(Runtime(reopened, "owner")).prepare(
                envelope.model_copy(update={"turn_id": "resume", "message_id": "resume"}), caps
            )
            assert resumed["session_id"] == sid
            assert Runtime(reopened, "owner").for_turn(resumed["turn_id"]).context(sid)["ooc"]
        process = subprocess.run(
            [
                sys.executable,
                "-c",
                """
import sys
from contextlib import closing
from character_runtime.storage import SQLiteStorage
from character_runtime.runtime import Runtime
from character_runtime.lifecycle import TurnLifecycle, TurnEnvelope, HostCapabilities
with closing(SQLiteStorage(sys.argv[1])) as db:
    result = TurnLifecycle(Runtime(db, 'owner')).prepare(
        TurnEnvelope.model_validate_json(sys.argv[2]),
        HostCapabilities(pre_generation=True, post_generation=True))
    print(result['session_id'])
""",
                str(Path(tmp) / "runtime.sqlite3"),
                envelope.model_copy(
                    update={"turn_id": "process", "message_id": "process"}
                ).model_dump_json(),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        assert process.stdout.strip() == sid, "New process lost persistent mapping"
        registry = SessionRegistry(db, "owner")
        legacy_identity = HostSessionIdentity(
            host="harness",
            platform="app",
            endpoint_id=endpoint["id"],
            native_session_id="legacy",
            audience="dm",
            participant_id="owner",
        )
        legacy = dict(
            id=legacy_identity.key(),
            owner_id="owner",
            platform_binding=endpoint["id"],
            character_id=cid,
            revision=7,
            unknown={"preserve": True},
        )
        db.put("owner", "conversation_session", legacy["id"], legacy)
        adopted = registry.resolve(legacy_identity, "not-used")
        assert all(adopted[k] == v for k, v in legacy.items())
        group = ScopeResolver(db, "owner").bind_endpoint(
            "app", "group", "group", cid, operation_id="group", confirmation="verified"
        )
        bind(db, "owner", "harness", "app", "other", "other", "verified", participant_id="other")
        group_a = TurnLifecycle(rt).prepare(
            envelope.model_copy(
                update={
                    "endpoint_id": group["id"],
                    "chat_type": "group",
                    "turn_id": "a",
                    "message_id": "a",
                }
            ),
            caps,
        )
        group_b = TurnLifecycle(rt).prepare(
            envelope.model_copy(
                update={
                    "endpoint_id": group["id"],
                    "chat_type": "group",
                    "actor_id": "other",
                    "turn_id": "b",
                    "message_id": "b",
                }
            ),
            caps,
        )
        assert group_a["session_id"] == group_b["session_id"] != sid
        assert rt.for_turn(group_b["turn_id"]).storage.actor.participant_id == "other"
        assert rt.for_turn(group_a["turn_id"]).storage.actor.participant_id == "owner"
        cross_host = TurnLifecycle(rt).prepare(
            envelope.model_copy(update={"host_id": "hermes"}), caps
        )
        assert cross_host["session_id"] != sid
        next_character = rt.characters.create(CharacterDefinition(name="second")).id
        ScopeResolver(db, "owner").bind_route(
            endpoint["id"], "owner", next_character, operation_id="route", confirmation="verified"
        )
        rt.for_turn(resumed["turn_id"]).session_control(
            sid, "activate", character_id=next_character
        )
        switched = TurnLifecycle(rt).prepare(
            envelope.model_copy(update={"turn_id": "switch", "message_id": "switch"}), caps
        )
        assert (
            switched["session_id"] == sid and switched["context"]["character_id"] == next_character
        )
        replacement = registry.transition(sid, "rotate", "reset")
        assert replacement["session_id"] != sid
        assert registry.transition(sid, "rotate", "reset") == replacement
        third = TurnLifecycle(rt).prepare(
            envelope.model_copy(update={"turn_id": "three", "message_id": "three"}),
            caps,
        )
        assert third["session_id"] == replacement["session_id"]
        assert not rt.for_turn(third["turn_id"]).context(third["session_id"])["ooc"]
        try:
            rt.for_turn(second["turn_id"])
        except ValueError:
            pass
        else:
            raise AssertionError("Old session capability survived explicit rotation")
        registry.transition(third["session_id"], "invalidate", "end")
        try:
            TurnLifecycle(rt).prepare(
                envelope.model_copy(update={"turn_id": "four", "message_id": "four"}),
                caps,
            )
        except ValueError:
            pass
        else:
            raise AssertionError("Invalidated mapping silently resurrected")
    print("PASS persistent canonical session, new turns, scoped tools and mode continuity")


if __name__ == "__main__":
    main()
