"""Real local protocol health check; synthetic writes never enter the user store.

真实本地协议健康检查；合成写入不进入用户库。
"""

import os
import sqlite3
import stat
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from . import __version__
from .storage import SQLiteStorage


async def call(client: Client, tool: str, **arguments: Any) -> dict[str, Any]:
    """Check protocol and business status without leaking returned private values.

    验证协议及业务状态，不泄漏返回的私人值。
    """
    result = await client.call_tool(tool, arguments)
    data = result.structured_content
    if result.is_error or not isinstance(data, dict) or not data.get("ok"):
        raise RuntimeError(f"Runtime operation failed: {tool}")
    value: dict[str, Any] = data["result"]
    return value


async def reject(client: Client, tool: str, **arguments: Any) -> None:
    """Require a synthetic unsafe operation to fail instead of silently succeeding.

    要求合成不安全操作明确失败，不能静默成功。
    """

    result = await client.call_tool(tool, arguments)
    assert result.is_error or (
        result.structured_content and not result.structured_content.get("ok")
    )


async def remember(client: Client, session: str, operation: str, content: str) -> dict[str, Any]:
    """Exercise evidence-backed persistence using only synthetic test input.

    仅用合成输入验证有证据的持久化流程。
    """

    raw = await call(
        client,
        "event_ingest",
        request={
            "operation_id": "event-" + operation,
            "session_id": session,
            "events": [
                {
                    "source_event_id": operation,
                    "source_id": "health",
                    "source_kind": "USER_DIRECT",
                    "content": content,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            ],
        },
    )
    return await call(
        client,
        "turn_commit",
        session_id=session,
        proposal={
            "operation_id": operation,
            "memory_proposals": [
                {"content": content, "importance": 0.9, "evidence_refs": raw["event_ids"]}
            ],
        },
    )


async def protocol_check(client: Client) -> list[str]:
    """Verify discovery and lifecycle over a real client-server transport.

    通过真实客户端服务端传输验证发现及生命周期。
    """

    names = {tool.name for tool in (await client.list_tools()).tools}
    assert {"event_ingest", "context_explain", "turn_commit", "proactive_prepare"} <= names
    a = (
        await call(
            client,
            "character_write",
            request={
                "action": "create",
                "operation_id": "create-a",
                "definition": {"name": "synthetic-a"},
            },
        )
    )["id"]
    repeated = await call(
        client,
        "character_write",
        request={
            "action": "create",
            "operation_id": "create-a",
            "definition": {"name": "synthetic-a"},
        },
    )
    assert a == repeated["id"]
    b = (
        await call(
            client,
            "character_write",
            request={
                "action": "create",
                "operation_id": "create-b",
                "definition": {"name": "synthetic-b"},
            },
        )
    )["id"]
    for session, cid in (("a", a), ("reset-a", a), ("b", b)):
        await call(
            client,
            "session_control",
            request={"action": "open", "session_id": session, "character_id": cid},
        )
    write = await remember(client, "a", "turn-a", "合成记忆：我喜欢苹果")
    assert len(write["memory_ids"]) == 1
    for session, expected in (("reset-a", True), ("b", False)):
        memories = (await call(client, "memory_recall", session_id=session))["memories"]
        assert bool(memories) == expected
    context = await call(client, "runtime_context", session_id="a")
    other = await call(client, "runtime_context", session_id="reset-a")
    assert context["stable_prefix"] == other["stable_prefix"]
    assert "合成记忆" in str(context["temporary"])
    explain = await call(client, "context_explain", session_id="a")
    assert "合成记忆" not in str(explain)
    assert explain["total_chars"] <= context["context_limits"]["total_chars"]
    await reject(client, "turn_commit", session_id="a", turn_id="legacy", candidates=[])
    await reject(
        client,
        "turn_commit",
        session_id="b",
        proposal={
            "operation_id": "foreign",
            "memory_proposals": [{"content": "fake", "evidence_refs": write["memory_ids"]}],
        },
    )
    await reject(
        client,
        "event_ingest",
        request={
            "operation_id": "secret",
            "session_id": "a",
            "events": [
                {
                    "source_id": "health",
                    "source_event_id": "secret",
                    "source_kind": "USER_DIRECT",
                    "content": "password: synthetic-secret",
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            ],
        },
    )
    raw = await call(
        client,
        "event_ingest",
        request={
            "operation_id": "forward",
            "session_id": "a",
            "events": [
                {
                    "source_id": "health",
                    "source_event_id": "forward",
                    "source_kind": "FORWARDED",
                    "content": "我喜欢猫",
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            ],
        },
    )
    await reject(
        client,
        "turn_commit",
        session_id="a",
        proposal={
            "operation_id": "false-fact",
            "fact_proposals": [
                {
                    "semantic_key": "profile:preference",
                    "subject": "owner",
                    "value": "猫",
                    "evidence_refs": raw["event_ids"],
                }
            ],
        },
    )
    await call(client, "session_control", request={"action": "enter_ooc", "session_id": "a"})
    recalled = await call(client, "memory_recall", session_id="a")
    grant = recalled["allowlists"]["memory"]["id"]
    args = {
        "action": "forget",
        "operation_id": "forget-a",
        "session_id": "a",
        "character_id": a,
        "memory_id": write["memory_ids"][0],
        "allowlist_id": grant,
    }
    first = await call(client, "memory_write", request=args)
    assert first == await call(client, "memory_write", request=args)
    assert not (await call(client, "memory_recall", session_id="reset-a"))["memories"]
    await reject(client, "memory_write", request={**args, "operation_id": "reuse-grant"})
    return [
        "discovery",
        "idempotent-create",
        "cross-session-memory",
        "character-isolation",
        "stable-compiler",
        "context-budget",
        "private-diagnostics",
        "legacy-write-rejected",
        "foreign-evidence-rejected",
        "secret-rejected",
        "forwarded-not-user-fact",
        "grant-single-use",
        "atomic-forget-retry",
    ]


async def check(data: Path) -> dict[str, Any]:
    # Installer preflight must never migrate the live database before activation.
    """Run isolated protocol checks without modifying the user's character store.

    运行隔离协议检查，不修改用户人物库。
    """

    database = data / "runtime.sqlite3"
    with tempfile.TemporaryDirectory(prefix="agentcosplay-schema-check-") as scratch:
        snapshot = Path(scratch) / "runtime.sqlite3"
        if database.exists() or database.is_symlink():
            for suffix in ("", "-wal", "-shm"):
                candidate = Path(str(database) + suffix)
                if candidate.exists() or candidate.is_symlink():
                    mode = candidate.lstat().st_mode
                    if stat.S_ISLNK(mode) or (os.name == "posix" and mode & 0o077):
                        raise PermissionError("Database files must be private and non-symlink")
            source = sqlite3.connect(
                "file:" + quote(str(database.resolve())) + "?mode=ro", uri=True
            )
            descriptor = os.open(snapshot, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
            target = sqlite3.connect(snapshot)
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
        store = SQLiteStorage(snapshot)
        store.close()
    with tempfile.TemporaryDirectory(prefix="agentcosplay-health-") as directory:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "character_runtime", "serve"],
            env={**os.environ, "CHARACTER_DATA_DIR": directory, "CHARACTER_OWNER": "healthcheck"},
        )
        async with Client(params) as client:
            checks = await protocol_check(client)
    return {"ok": True, "version": __version__, "data_dir": str(data), "checks": checks}
