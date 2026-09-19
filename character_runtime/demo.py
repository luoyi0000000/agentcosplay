"""Deterministic MCP/state demonstration using synthetic data; no LLM API calls."""

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from mcp import Client
from mcp.client.stdio import StdioServerParameters


async def call(client: Client, tool: str, **arguments: Any) -> dict[str, Any]:
    result = await client.call_tool(tool, arguments)
    data = result.structured_content
    if result.is_error or not isinstance(data, dict) or not data.get("ok"):
        raise RuntimeError(f"Demo operation failed: {tool}")
    value: dict[str, Any] = data["result"]
    return value


async def run(folder: Path) -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "character_runtime", "serve", "--transport", "stdio"],
        env={**os.environ, "CHARACTER_DATA_DIR": str(folder), "CHARACTER_OWNER": "demo-only"},
    )
    async with Client(params) as client:
        a = await call(
            client,
            "character_write",
            request={
                "action": "create",
                "definition": {
                    "name": "林舟",
                    "facts": {
                        "identity": {"value": "守灯塔的年轻旅人", "source_type": "user_explicit"},
                        "speech_style": {
                            "value": "安静、直接，习惯用海边的意象",
                            "source_type": "user_explicit",
                        },
                    },
                },
            },
        )
        b = await call(
            client,
            "character_write",
            request={
                "action": "create",
                "definition": {"name": "岚"},
            },
        )
        await call(
            client,
            "session_control",
            request={
                "action": "open",
                "session_id": "first",
                "character_id": a["id"],
            },
        )
        await call(
            client,
            "turn_commit",
            session_id="first",
            turn_id="1",
            candidates=[
                {
                    "content": "角色世界：用户希望被称作旅人，约好下次一起看灯塔。",
                    "importance": 0.9,
                },
                {"content": "仅本会话的合成线索", "kind": "session", "importance": 0.6},
                {"content": "随口一句", "importance": 0.1},
            ],
        )
        print("PASS 真实 MCP 创建/激活/提交：低重要性候选丢弃，长期与会话记忆分开。")
    # Closing Client terminates the first server; the next Client starts a new process.
    async with Client(params) as client:
        await call(
            client,
            "session_control",
            request={
                "action": "open",
                "session_id": "second",
                "character_id": a["id"],
            },
        )
        context = await call(client, "runtime_context", session_id="second", query="灯塔")
        assert len(context["memories"]) == 1
        memory = context["memories"][0]
        print("PASS 服务进程重启 + 新会话召回：", memory["content"])
        await call(
            client,
            "session_control",
            request={
                "action": "open",
                "session_id": "other",
                "character_id": b["id"],
            },
        )
        assert not (await call(client, "runtime_context", session_id="other"))["memories"]
        print("PASS 角色 B 看不到 A 的记忆。")
        for action in ("enter_ooc", "exit_ooc"):
            await call(
                client, "session_control", request={"action": action, "session_id": "second"}
            )
            assert (await call(client, "runtime_context", session_id="second"))["ooc"] == (
                action == "enter_ooc"
            )
        await call(
            client,
            "session_control",
            request={
                "action": "start_task",
                "session_id": "second",
                "mode": "task_neutral",
            },
        )
        assert (await call(client, "runtime_context", session_id="second"))[
            "effective_mode"
        ] == "task_neutral"
        await call(
            client, "session_control", request={"action": "end_task", "session_id": "second"}
        )
        assert (await call(client, "runtime_context", session_id="second"))[
            "effective_mode"
        ] == "soft_roleplay"
        print("PASS OOC 与临时任务模式均可恢复。")
        package = await call(client, "character_export", character_id=a["id"])
        assert not package["memories"]
        full = await call(client, "character_export", character_id=a["id"], include_memories=True)
        clone = await call(client, "character_import", package=full)
        assert clone["id"] != a["id"]
        print("PASS 默认无记忆导出；显式含记忆导出后可导入为独立新角色。")
        assert not (await call(client, "memory_recall", session_id="second", real=True))["memories"]
        real = await call(
            client,
            "memory_promote",
            session_id="second",
            memory_id=memory["id"],
            confirmation="仅测试：合成用户明确确认此事真实且同意保存",
        )
        assert real["kind"] == "real_user"
        assert not (await call(client, "memory_recall", session_id="second"))["memories"]
        assert not (
            await call(client, "character_export", character_id=a["id"], include_memories=True)
        )["memories"]
        await call(
            client, "session_control", request={"action": "enter_ooc", "session_id": "second"}
        )
        await call(
            client,
            "memory_write",
            request={
                "action": "forget",
                "session_id": "second",
                "character_id": a["id"],
                "memory_id": real["id"],
            },
        )
        assert not (await call(client, "memory_recall", session_id="second", real=True))["memories"]
        print("PASS 显式现实记忆提升、角色包排除、遗忘后不可召回。")
    print("演示完成：全部为合成数据，临时数据库随后删除；未调用模型、未连接远程。")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print("agentcosplay：确定性协议/状态演示（台词与候选不是模型生成）")
    with tempfile.TemporaryDirectory(prefix="character-runtime-demo-") as folder:
        asyncio.run(run(Path(folder) / "角色 data"))


if __name__ == "__main__":
    main()
