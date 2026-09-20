"""Real local protocol health check; synthetic writes never enter the user store."""

import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from . import __version__
from .storage import SQLiteStorage


async def call(client: Client, tool: str, **arguments: Any) -> dict[str, Any]:
    """Check protocol and business status without leaking returned private values."""
    result = await client.call_tool(tool, arguments)
    data = result.structured_content
    if result.is_error or not isinstance(data, dict) or not data.get("ok"):
        raise RuntimeError(f"Runtime operation failed: {tool}")
    value: dict[str, Any] = data["result"]
    return value


async def check(data: Path) -> dict[str, Any]:
    store = SQLiteStorage(data / "runtime.sqlite3")
    try:
        # Check opening/schema/permissions without writing into any user's namespace.
        store.get("healthcheck", "healthcheck", "absent")
    finally:
        store.close()
    with tempfile.TemporaryDirectory(prefix="agentcosplay-health-") as directory:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "character_runtime", "serve"],
            env={**os.environ, "CHARACTER_DATA_DIR": directory, "CHARACTER_OWNER": "healthcheck"},
        )
        async with Client(params) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            if not {"runtime_context", "character_write", "turn_commit"} <= names:
                raise RuntimeError("Required Runtime tools missing")
            await call(
                client,
                "character_write",
                request={"action": "create", "definition": {"name": "synthetic-healthcheck"}},
            )
    return {"ok": True, "version": __version__, "data_dir": str(data), "tools": len(names)}
