"""Check the official Hermes bridge contract with synthetic host callbacks.

用合成宿主回调验证 Hermes 官方桥接契约，不冒充真实宿主端到端验收。
"""

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from character_runtime.auth import LocalTokenVerifier
from character_runtime.hermes_adapter import HermesAdapter, register
from character_runtime.identity import bind
from character_runtime.lifecycle import HostCapabilities, TurnEnvelope, TurnLifecycle
from character_runtime.models import CharacterDefinition
from character_runtime.runtime import Runtime
from character_runtime.scope import ScopeResolver
from character_runtime.storage import SQLiteStorage


def long_input_checks(directory, adapter, env):
    """Full Host tasks survive a bounded retrieval projection.

    完整宿主任务不能因检索投影的长度限制而失去角色上下文。
    """
    storage = SQLiteStorage(Path(directory) / "long-input.sqlite3")
    try:
        runtime = Runtime(storage, "synthetic")
        cid = runtime.characters.create(CharacterDefinition(name="continuous")).id
        bind(storage, "synthetic", "hermes", "telegram-app", "actor-A", "a", "verified")
        endpoint = ScopeResolver(storage, "synthetic", runtime.clock).bind_endpoint(
            "telegram-app", "group", "group", cid, operation_id="g", confirmation="verified"
        )
        lifecycle = TurnLifecycle(runtime)

        class LocalBridge:
            async def call(self, tool, arguments):
                assert tool == "host_prepare_turn"
                arguments["envelope"]["endpoint_id"] = endpoint["id"]
                result = lifecycle.prepare(
                    TurnEnvelope.model_validate(arguments["envelope"]),
                    HostCapabilities.model_validate(arguments["capabilities"]),
                )
                return {**result, "capability": "synthetic"}

        original = adapter.bridge
        adapter.bridge = LocalBridge()
        try:
            for size in (4000, 4001, 64000):
                task = "精确任务 " + "x" * (size - 12) + " END 42"
                before = task
                result = asyncio.run(
                    adapter.context(
                        env,
                        session_id="long",
                        turn_id=str(size),
                        sender_id="actor-A",
                        user_message=task,
                    )
                )
                assert "Runtime session_id:" in result, f"Character lost for length {size}"
                assert task == before
        finally:
            adapter.bridge = original
    finally:
        storage.close()


def registration_checks(token, settings, env):
    """Check hook registration and middleware failure without a live Host.

    验证注册及中间件失败边界，不依赖或冒充真实 Host。
    """
    hooks, middleware, skills = {}, {}, {}
    config = {
        "mcp_servers": {
            "agentcosplay": {
                "url": settings["runtime_url"],
                "headers": {
                    "Authorization": "Bearer "
                    + LocalTokenVerifier(
                        token.read_text(), "owner", settings["runtime_url"]
                    ).discovery_token
                },
            }
        }
    }
    ctx = SimpleNamespace(
        get_config=lambda key, default=None: settings.get(key, default),
        register_hook=lambda key, callback: hooks.update({key: callback}),
        register_middleware=lambda key, callback: middleware.update({key: callback}),
        register_skill=lambda key, path: skills.update({key: path}),
    )
    with patch.dict(
        sys.modules,
        {
            "gateway.session_context": SimpleNamespace(
                get_session_env=lambda key: env.get(key, "")
            ),
            "hermes_cli.config": SimpleNamespace(load_config_readonly=lambda: config),
            "hermes_cli.plugins": SimpleNamespace(resolve_plugin_command_result=asyncio.run),
        },
    ):
        register(ctx, Path(__file__).resolve().parents[1])
        assert "post_llm_call" in hooks
        assert skills["agentcosplay"].is_file()
        handler = middleware["tool_execution"]

        def downstream(args):
            raise AssertionError("Protected MCP call reached owner fallback")

        assert not json.loads(
            handler(tool_name="mcp__agentcosplay__runtime_context", args={}, next_call=downstream)
        )["ok"]
        assert handler(tool_name="other", args={"value": 1}, next_call=lambda args: args) == {
            "value": 1
        }
        config["mcp_servers"]["agentcosplay"]["headers"]["Authorization"] = (
            "Bearer " + token.read_text()
        )
        try:
            register(ctx, Path(__file__).resolve().parents[1])
        except ValueError:
            pass
        else:
            raise AssertionError("Native entry accepted an owner MCP credential")


class Bridge:
    def __init__(self):
        self.calls = []

    async def call(self, tool, arguments, **kwargs):
        self.calls.append((tool, arguments, kwargs))
        if tool == "host_prepare_turn":
            return {
                "turn_id": "runtime-turn",
                "capability": "turn-cap",
                "context": {"stable_prefix": "character", "temporary": {"memory": "allowed"}},
            }
        assert tool in {"host_observe_generation", "host_finalize_turn"}
        return {"state": "finalized", "delivery_state": "unknown"}

    async def model_call(self, capability, turn_id, tool, arguments):
        assert (capability, turn_id) == ("turn-cap", "runtime-turn")
        self.calls.append((tool, arguments, {}))
        return {"stable_prefix": "character", "temporary": {"memory": "allowed"}}


def main():
    with TemporaryDirectory() as directory:
        token = Path(directory) / "token"
        token.write_text("x" * 48, encoding="ascii")
        adapter = HermesAdapter(
            "http://127.0.0.1:8765/mcp",
            token,
            "hermes",
            [
                {
                    "platform": "telegram",
                    "chat_id": "group",
                    "thread_id": "",
                    "chat_type": "group",
                    "runtime_platform": "telegram-app",
                    "endpoint_id": "bound-group",
                    "kind": "group",
                }
            ],
        )
        bridge = Bridge()
        adapter.bridge = bridge
        env = {
            "HERMES_SESSION_PLATFORM": "telegram",
            "HERMES_SESSION_CHAT_ID": "group",
            "HERMES_SESSION_CHAT_TYPE": "group",
            "HERMES_SESSION_THREAD_ID": "",
            "HERMES_SESSION_USER_ID": "actor-A",
            "HERMES_SESSION_MESSAGE_ID": "m1",
        }
        registration_checks(
            token,
            {
                "runtime_url": "http://127.0.0.1:8765/mcp",
                "token_file": str(token),
                "routes": list(adapter.routes.values()),
            },
            env,
        )
        event = SimpleNamespace(
            source=SimpleNamespace(
                platform=SimpleNamespace(value="telegram"),
                chat_id="group",
                chat_type="group",
                thread_id="",
                user_id="actor-A",
            ),
            user_id="actor-A",
            message_id="m1",
            text="hello",
            internal=False,
            media_urls=[],
            media_types=[],
            timestamp=datetime.now(UTC),
        )
        # Capture before Host authorization must not perform Runtime writes.
        # 宿主鉴权前捕获事件不得写入 Runtime。
        adapter.capture(event=event)
        assert not bridge.calls
        context = asyncio.run(
            adapter.context(
                env, session_id="s1", turn_id="t1", user_message="hello", sender_id="actor-A"
            )
        )
        assert "character" in context and "allowed" in context
        ingress = bridge.calls[0][1]["envelope"]
        assert ingress["chat_type"] == "group"
        assert ingress["text"] == "hello" and ingress["input_is_verbatim"]
        assert ingress["actor_id"] == "actor-A"
        asyncio.run(
            adapter.observe(
                session_id="s1",
                turn_id="t1",
                assistant_response="reply",
                conversation_history=[{"reasoning": "must-not-persist"}],
            )
        )
        assert [tool for tool, _, _ in bridge.calls[-2:]] == [
            "host_observe_generation",
            "host_finalize_turn",
        ]
        assert "must-not-persist" not in str(bridge.calls)
        long_input_checks(directory, adapter, env)
        event.timestamp = None
        event.message_id = "missing-time"
        adapter.capture(event=event)
        capture = list(adapter.inputs.values())[-1][1]
        assert capture["timestamp"] is None, "Missing source timestamp was fabricated"
        assert capture["observed_at"]
        asyncio.run(
            adapter.context(
                {**env, "HERMES_SESSION_MESSAGE_ID": "missing-time"},
                session_id="missing",
                turn_id="missing-time",
                sender_id="actor-A",
                user_message="hello",
            )
        )
        assert bridge.calls[-1][1]["envelope"]["timestamp"] is None
        assert bridge.calls[-1][1]["envelope"]["input_is_verbatim"]
        # Official Hermes may omit sender_id; task-local verified actor metadata remains mandatory.
        # 官方 Hermes 可不提供 sender_id，但仍必须有可信的逐轮 Actor 元数据。
        assert "Runtime session_id:" in asyncio.run(
            adapter.context(
                env,
                session_id="optional-sender",
                turn_id="optional-sender",
                user_message="decorated",
            )
        )
        assert not bridge.calls[-1][1]["envelope"]["input_is_verbatim"]
        result = asyncio.run(
            adapter.tool("s1", "t1", "runtime_context", {"session_id": "runtime-turn"})
        )
        assert json.loads(result)["ok"]
        for changes in ({"sender_id": "actor-B"}, {"parent_session_id": "subagent"}):
            args = dict(session_id="s2", turn_id="t2", user_message="hello", sender_id="actor-A")
            args.update(changes)
            assert "unavailable" in asyncio.run(adapter.context(env, **args))
        # Changing a group to a DM in untrusted metadata cannot match the route.
        # 群事件篡改为私聊不得匹配私有数据路由。
        assert "unavailable" in asyncio.run(
            adapter.context(
                {**env, "HERMES_SESSION_CHAT_TYPE": "private"}, session_id="s2", turn_id="t2"
            )
        )
        missing = asyncio.run(adapter.tool("s2", "t2", "runtime_context", {}))
        assert not json.loads(missing)["ok"]
        adapter.clear(session_id="s1")
        assert not json.loads(asyncio.run(adapter.tool("s1", "t1", "runtime_context", {})))["ok"]
        before = len(bridge.calls)
        asyncio.run(adapter.observe(session_id="s1", turn_id="t1", assistant_response="late"))
        assert len(bridge.calls) == before
        assert not any("ack" in tool or "response" in tool for tool, _, _ in bridge.calls)
    print("PASS Hermes official-hook contract, actor/endpoint isolation, capability fail-closed")


if __name__ == "__main__":
    main()
