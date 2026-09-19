import os
import sys
import tempfile
import unittest
from pathlib import Path

import httpx2
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp.client.streamable_http import streamable_http_client

from character_runtime.server import build_server, http_app
from character_runtime.storage import SQLiteStorage


class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_stdio_character_memory_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "character_runtime", "serve", "--transport", "stdio"],
                env={**os.environ, "CHARACTER_DATA_DIR": folder, "CHARACTER_OWNER": "synthetic"},
            )
            async with Client(params) as client:
                names = {t.name for t in (await client.list_tools()).tools}
                self.assertIn("runtime_context", names)
                created = await client.call_tool(
                    "character_write",
                    {"request": {"action": "create", "definition": {"name": "合成旅人"}}},
                )
                self.assertFalse(created.is_error)
                cid = created.structured_content["result"]["id"]
                opened = await client.call_tool(
                    "session_control",
                    {"request": {"action": "open", "session_id": "test", "character_id": cid}},
                )
                self.assertFalse(opened.is_error)
                saved = await client.call_tool(
                    "turn_commit",
                    {
                        "session_id": "test",
                        "turn_id": "1",
                        "candidates": [{"content": "喜欢星空", "importance": 0.9}],
                    },
                )
                self.assertFalse(saved.is_error)
                context = await client.call_tool("runtime_context", {"session_id": "test"})
                self.assertEqual(
                    context.structured_content["result"]["memories"][0]["content"], "喜欢星空"
                )
                denied = await client.call_tool(
                    "memory_write",
                    {
                        "request": {
                            "action": "store",
                            "session_id": "test",
                            "character_id": cid,
                            "candidate": {"content": "虚构现实", "kind": "real_user"},
                        }
                    },
                )
                self.assertFalse(denied.structured_content["ok"])

    async def test_http_auth_and_owner_not_controlled_by_arguments(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteStorage(Path(folder) / "db")
            server = build_server(
                store,
                local_owner="synthetic",
                token="x" * 40,
                resource="https://memory.example/mcp",
            )
            app = http_app(server)
            async with app.router.lifespan_context(app):
                async with httpx2.AsyncClient(
                    transport=httpx2.ASGITransport(app=app), base_url="http://127.0.0.1:8765"
                ) as client:
                    result = await client.post(
                        "/mcp",
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                    )
                    self.assertEqual(result.status_code, 401)
                    result = await client.get("/.well-known/oauth-protected-resource/mcp")
                    self.assertEqual(result.status_code, 200)
                    client.headers["Authorization"] = "Bearer " + "x" * 40
                    async with Client(
                        streamable_http_client("http://127.0.0.1:8765/mcp", http_client=client)
                    ) as mcp:
                        listed = await mcp.list_tools()
                        self.assertEqual(len(listed.tools), 10)
                        created = await mcp.call_tool(
                            "character_write",
                            {
                                "request": {
                                    "action": "create",
                                    "definition": {"name": "HTTP 合成角色"},
                                }
                            },
                        )
                        self.assertTrue(created.structured_content["ok"])
                        injected = await mcp.call_tool(
                            "character_write",
                            {
                                "request": {
                                    "action": "create",
                                    "definition": {"name": "拒绝伪造"},
                                    "owner": "another-user",
                                }
                            },
                        )
                        self.assertTrue(injected.is_error)
                        self.assertEqual(len(store.list("synthetic", "definition")), 1)
                        self.assertEqual(store.list("another-user", "definition"), [])
                    public_host = await client.post(
                        "/mcp",
                        headers={"Host": "memory.example", "Origin": "https://memory.example"},
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    )
                    self.assertNotIn(public_host.status_code, (400, 401, 421))
                    client.headers["Authorization"] = "Bearer incorrect"
                    denied = await client.post(
                        "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
                    )
                    self.assertEqual(denied.status_code, 401)
                    malformed = await client.post(
                        "/mcp",
                        headers={"Authorization": b"Bearer \xff"},
                        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                    )
                    self.assertEqual(malformed.status_code, 401)
                    client.headers["Authorization"] = "Bearer " + "x" * 40
                    rebinding = await client.post(
                        "/mcp",
                        headers={"Host": "evil.example"},
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    )
                    self.assertIn(rebinding.status_code, (400, 421))
            store.close()


if __name__ == "__main__":
    unittest.main()
