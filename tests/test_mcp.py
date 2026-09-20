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
                        self.assertTrue(
                            {"runtime_context", "memory_promote"} <= {t.name for t in listed.tools}
                        )
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


class SharedRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_gateway_clients_share_one_runtime_bidirectionally(self):
        from contextlib import AsyncExitStack

        from character_runtime.health import call

        with tempfile.TemporaryDirectory() as folder:
            store = SQLiteStorage(Path(folder) / "one-runtime.sqlite3")
            try:
                server = build_server(store, local_owner="same-user", token="s" * 40)
                app = http_app(server)
                async with app.router.lifespan_context(app), AsyncExitStack() as stack:
                    clients = []
                    # Independent HTTP connections and conversation IDs; one app/store, no sync.
                    for gateway in ("hermes-entry", "astrbot-entry"):
                        http = await stack.enter_async_context(
                            httpx2.AsyncClient(
                                transport=httpx2.ASGITransport(app=app),
                                headers={"Authorization": "Bearer " + "s" * 40},
                            )
                        )
                        clients.append(
                            await stack.enter_async_context(
                                Client(
                                    streamable_http_client(
                                        "http://127.0.0.1:8765/mcp", http_client=http
                                    )
                                )
                            )
                        )
                    a, b = clients
                    character = await call(
                        a,
                        "character_write",
                        request={"action": "create", "definition": {"name": "共享合成角色"}},
                    )
                    for client, session in zip(
                        clients, ("hermes-entry", "astrbot-entry"), strict=True
                    ):
                        await call(
                            client,
                            "session_control",
                            request={
                                "action": "open",
                                "session_id": session,
                                "character_id": character["id"],
                            },
                        )
                    for writer, session, reader, other, content in (
                        (a, "hermes-entry", b, "astrbot-entry", "来自入口 A 的合成记忆"),
                        (b, "astrbot-entry", a, "hermes-entry", "来自入口 B 的合成记忆"),
                    ):
                        await call(
                            writer,
                            "turn_commit",
                            session_id=session,
                            turn_id="1",
                            candidates=[{"content": content, "importance": 0.9}],
                        )
                        context = await call(reader, "runtime_context", session_id=other)
                        self.assertIn(content, [m["content"] for m in context["memories"]])
                    self.assertEqual(len(store.list("same-user", "definition")), 1)
                    await call(
                        b,
                        "session_control",
                        request={"action": "enter_ooc", "session_id": "astrbot-entry"},
                    )
                    state = (await call(b, "character_read", character_id=character["id"]))["state"]
                    relation = {**state["relationship"], "preferred_address": "旅人"}
                    await call(
                        b,
                        "character_write",
                        request={
                            "action": "relationship",
                            "session_id": "astrbot-entry",
                            "character_id": character["id"],
                            "relationship": relation,
                            "expected_revision": state["revision"],
                        },
                    )
                    await call(
                        b,
                        "companion_control",
                        session_id="astrbot-entry",
                        update={"goal": {"id": "read", "description": "共同选择的读书目标"}},
                    )
                    context = await call(a, "runtime_context", session_id="hermes-entry")
                    self.assertEqual(context["state"]["relationship"]["preferred_address"], "旅人")
                    self.assertEqual(
                        context["companion"]["goals"][0]["description"], "共同选择的读书目标"
                    )
                    denied = await a.call_tool(
                        "companion_control",
                        {
                            "session_id": "hermes-entry",
                            "update": {"settings": {"proactive_contact": True}},
                        },
                    )
                    self.assertFalse(denied.structured_content["ok"])
                    self.assertFalse(
                        (await call(a, "proactive_decide", character_id=character["id"]))[
                            "should_contact"
                        ]
                    )
            finally:
                store.close()
