"""Check native AstrBot mapping and shared lifecycle without impersonating a live Host.

验证 AstrBot 原生映射与共享生命周期，不冒充真实宿主端到端验收。
"""

import argparse
import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from mcp.types import CallToolResult

from character_runtime.astrbot_adapter import AstrBotAdapter
from character_runtime.identity import bind
from character_runtime.lifecycle import HostCapabilities, TurnEnvelope, TurnLifecycle
from character_runtime.models import CharacterDefinition
from character_runtime.runtime import Runtime
from character_runtime.scope import ScopeResolver
from character_runtime.storage import SQLiteStorage


async def run(directory):
    store = SQLiteStorage(Path(directory) / "joint.sqlite3")
    try:
        rt = Runtime(store, "owner")
        cid = rt.characters.create(CharacterDefinition(name="shared")).id
        for host in ("hermes", "astrbot"):
            bind(store, "owner", host, "qq", "alice", host, "verified", participant_id="alice")
        scope = ScopeResolver(store, "owner")
        endpoint = scope.bind_endpoint(
            "qq", "group", "group", cid, operation_id="g", confirmation="verified"
        )
        lifecycle = TurnLifecycle(rt)
        token = Path(directory) / "token"
        token.write_text("x" * 48)
        adapter = AstrBotAdapter(
            "http://127.0.0.1:8765/mcp",
            token,
            "astrbot",
            [
                {
                    "platform_id": "qq-bot",
                    "session_id": "group",
                    "kind": "group",
                    "runtime_platform": "qq",
                    "endpoint_id": endpoint["id"],
                }
            ],
        )

        class Bridge:
            async def model_call(self, capability, turn_id, tool, arguments):
                assert capability == "turn-cap" and turn_id and tool == "character_read"
                return {"name": "shared"}

            async def call(self, tool, arguments):
                if tool == "host_prepare_turn":
                    return {
                        **lifecycle.prepare(
                            TurnEnvelope.model_validate(arguments["envelope"]),
                            HostCapabilities.model_validate(arguments["capabilities"]),
                        ),
                        "capability": "turn-cap",
                    }
                if tool == "host_observe_generation":
                    return lifecycle.observe_generation(**arguments)
                if tool == "host_finalize_turn":
                    return lifecycle.finalize(**arguments)
                raise AssertionError(tool)

        adapter.bridge = Bridge()
        event = SimpleNamespace(
            get_platform_id=lambda: "qq-bot",
            get_session_id=lambda: "group",
            get_sender_id=lambda: "alice",
            get_message_str=lambda: "AstrBot public input",
            message_obj=SimpleNamespace(type=SimpleNamespace(value="GroupMessage"), message_id="m"),
        )
        request = SimpleNamespace(
            prompt="AstrBot public input", system_prompt="Host rules", func_tool=None
        )
        before = request.prompt
        await adapter.prepare(event, request, plain=True)
        first = request.system_prompt
        await adapter.prepare(event, request, plain=True)
        assert (
            first.split("Turn-local context:")[0]
            == request.system_prompt.split("Turn-local context:")[0]
        )
        assert request.system_prompt.count("Runtime session_id:") == 1 and request.prompt == before
        await adapter.observe(
            event,
            SimpleNamespace(completion_text="generated only", reasoning_content="hidden sentinel"),
        )
        other = lifecycle.prepare(
            TurnEnvelope(
                host_id="hermes",
                platform="qq",
                actor_id="alice",
                endpoint_id=endpoint["id"],
                chat_type="group",
                session_id="hermes",
                turn_id="h",
                message_id="h",
                text="Hermes next turn",
            ),
            HostCapabilities(pre_generation=True, post_generation=True),
        )
        assert "AstrBot public input" in str(other["context"])
        records = rt.for_turn(other["turn_id"]).knowledge.records("turn_lifecycle", cid)
        assert "hidden sentinel" not in str(records)
        assert any(
            t.get("state") == "finalized" and t["delivery_state"] == "unknown" for t in records
        )
        assert not any(
            e["source_kind"] == "ASSISTANT_VISIBLE"
            for e in rt.for_turn(other["turn_id"]).knowledge.records("raw_event", cid)
        )
        # Per-request wrappers must neither mutate global tools nor fall back after eviction.
        # 单请求包装不能修改全局工具，也不能在令牌清除后回退管理权限。
        original = SimpleNamespace(
            mcp_server_name="agentcosplay",
            mcp_tool=SimpleNamespace(name="character_read"),
            call=None,
        )
        wrapped = adapter.scoped_tool(original, adapter.event_key(event))
        assert wrapped is not original and original.call is None
        result = await wrapped.call(None)
        assert isinstance(result, CallToolResult), "AstrBot MCP executor rejects string results"
        assert '"ok": true' in result.content[0].text
        adapter.turns.clear()
        result = await wrapped.call(None)
        assert isinstance(result, CallToolResult)
        assert '"ok": false' in result.content[0].text
        event.get_sender_id = lambda: "unknown"
        try:
            await adapter.prepare(event, request, plain=True)
        except (ValueError, RuntimeError):
            pass
        else:
            raise AssertionError("Unknown actor gained Runtime context")
    finally:
        store.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sdk-python", help="Optional isolated Host SDK Python executable")
    args = parser.parse_args()
    with TemporaryDirectory() as directory:
        asyncio.run(run(directory))
        if args.sdk_python:
            # Exercise the real HTTP server with the Host's SDK, without importing Core there.
            # 使用宿主 SDK 连接真实 HTTP 服务；客户端环境不导入 Core，也不替换宿主依赖。
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            token = Path(directory) / "sdk-token"
            token.write_text("synthetic-sdk-credential-12345678901234567890")
            environment = dict(
                os.environ,
                CHARACTER_DATA_DIR=directory,
                CHARACTER_OWNER="synthetic",
                CHARACTER_PORT=str(port),
                CHARACTER_TOKEN=token.read_text(),
            )
            process = subprocess.Popen(
                [sys.executable, "-m", "character_runtime.cli", "serve", "--transport", "http"],
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError("Synthetic Runtime exited")
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                            break
                    except OSError:
                        time.sleep(0.1)
                code = """import asyncio,sys
from pathlib import Path
from character_runtime.host_client import HostBridge
async def check():
    bridge = HostBridge(sys.argv[1], Path(sys.argv[2]))
    character = await bridge.call("character_write", {"request": {
        "action": "create", "operation_id": "sdk-create", "definition": {"name": "sdk-check"}}})
    await bridge.call("session_control", {"request": {
        "action": "open", "session_id": "sdk-session", "character_id": character["id"]}})
    result = await bridge.call("runtime_doctor", {"session_id": "sdk-session"})
    assert result
    from types import SimpleNamespace
    from mcp.types import CallToolResult
    from character_runtime.astrbot_adapter import AstrBotAdapter
    adapter = AstrBotAdapter(sys.argv[1], Path(sys.argv[2]), "sdk", [])
    wrapped = adapter.scoped_tool(SimpleNamespace(
        mcp_server_name="agentcosplay", mcp_tool=SimpleNamespace(name="character_read")), "gone")
    rejected = await wrapped.call(None)
    assert isinstance(rejected, CallToolResult) and '"ok": false' in rejected.content[0].text
asyncio.run(check())
"""
                completed = subprocess.run(
                    [args.sdk_python, "-c", code, f"http://127.0.0.1:{port}/mcp", str(token)],
                    capture_output=True,
                    timeout=30,
                )
                assert completed.returncode == 0, "Host SDK HTTP compatibility check failed"
            finally:
                process.terminate()
                process.wait(timeout=10)
            print("PASS isolated Host SDK against real Runtime HTTP transport")
    print("PASS AstrBot mapping, shared Runtime continuity, temporary context, no false ACK")


if __name__ == "__main__":
    main()
