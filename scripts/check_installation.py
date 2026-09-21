"""Opt-in, network-using acceptance of the actual installer in disposable directories.

Run: uv run --locked python -m scripts.check_installation
No existing host configuration is touched. All character content is synthetic.
"""

import asyncio
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import AsyncExitStack
from pathlib import Path

import httpx2
import yaml
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp.client.streamable_http import streamable_http_client

from character_runtime.health import call, remember

SOURCE = Path(__file__).resolve().parents[1]


async def stdio(root: Path, character: str | None = None) -> str:
    import tomllib

    config = tomllib.loads((root / "codex/config.toml").read_text())["mcp_servers"]["agentcosplay"]
    async with Client(StdioServerParameters(**config)) as client:
        if character is None:
            character = (
                await call(
                    client,
                    "character_write",
                    request={
                        "action": "create",
                        "operation_id": "create-install",
                        "definition": {"name": "安装验收合成人物"},
                    },
                )
            )["id"]
            await call(
                client,
                "session_control",
                request={"action": "open", "session_id": "install-test", "character_id": character},
            )
            await remember(client, "install-test", "install-1", "保留下来的合成记忆")
        else:
            context = await call(client, "runtime_context", session_id="install-test")
            assert json.loads(context["stable_prefix"])["character"]["id"] == character
            assert "保留下来的合成记忆" in str(context["temporary"])
        return character


async def shared(root: Path, character: str) -> None:
    configs = [
        yaml.safe_load((root / "hermes/config.yaml").read_text())["mcp_servers"]["agentcosplay"],
        json.loads((root / "astrbot/mcp_server.json").read_text())["mcpServers"]["agentcosplay"],
    ]
    assert configs[0]["url"] == configs[1]["url"]
    assert configs[1]["transport"] == "streamable_http"
    async with AsyncExitStack() as stack:
        clients = []
        for config in configs:
            http = await stack.enter_async_context(httpx2.AsyncClient(headers=config["headers"]))
            clients.append(
                await stack.enter_async_context(
                    Client(streamable_http_client(config["url"], http_client=http))
                )
            )
        for client, session in zip(clients, ("gateway-a", "gateway-b"), strict=True):
            await call(
                client,
                "session_control",
                request={"action": "open", "session_id": session, "character_id": character},
            )
        for writer, reader, session, other, content in [
            (clients[0], clients[1], "gateway-a", "gateway-b", "A入口写入"),
            (clients[1], clients[0], "gateway-b", "gateway-a", "B入口写入"),
        ]:
            await remember(writer, session, "gateway-" + session, content)
            context = await call(reader, "runtime_context", session_id=other)
            assert content in str(context["temporary"])


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentcosplay 中文 acceptance ") as directory:
        root = Path(directory).resolve()
        checkout = root / "checkout"
        checkout.mkdir()
        for name in (
            "install.py",
            "character_runtime",
            "plugins",
            "pyproject.toml",
            "uv.lock",
            "build-constraints.txt",
            "LICENSE",
        ):
            source = SOURCE / name
            if source.is_dir():
                shutil.copytree(
                    source, checkout / name, ignore=shutil.ignore_patterns("__pycache__")
                )
            else:
                shutil.copy2(source, checkout / name)
        app, data = root / "runtime", root / "characters"

        def command(*args: str) -> dict:
            result = subprocess.run(
                [sys.executable, str(checkout / "install.py"), *args, "--install-root", str(app)],
                capture_output=True,
                text=True,
                timeout=600,
            )
            if result.returncode:
                raise RuntimeError("Isolated installer failed: " + result.stderr)
            parsed = json.loads(result.stdout)
            assert parsed["ok"]
            print("PASS", args[0], flush=True)
            return parsed

        command(
            "install", "--data-dir", str(data), "--host", "codex", "--host-dir", str(root / "codex")
        )
        command("doctor")
        character = asyncio.run(stdio(root))
        # Source relocation must not affect the separately installed package.
        moved = root / "relocated-checkout"
        checkout.rename(moved)
        checkout = moved
        asyncio.run(stdio(root, character))
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        for host in ("hermes", "astrbot"):
            command(
                "connect",
                "--host",
                host,
                "--host-dir",
                str(root / host),
                "--transport",
                "http",
                "--port",
                str(port),
            )
        process = subprocess.Popen(
            [sys.executable, str(app / "launch.py"), "serve", "--transport", "http"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("Shared Runtime exited")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                        break
                except OSError:
                    time.sleep(0.1)
            asyncio.run(shared(root, character))
        finally:
            process.terminate()
            process.wait(timeout=10)
        first = json.loads((app / "installed.json").read_text())["active"]
        command("update", "--host", "generic")
        assert json.loads((app / "installed.json").read_text())["active"] != first
        command("doctor")
        asyncio.run(stdio(root, character))
        command("rollback")
        assert json.loads((app / "installed.json").read_text())["active"] == first
        asyncio.run(stdio(root, character))
        before = (data / "runtime.sqlite3").read_bytes()
        command("uninstall")
        assert (data / "runtime.sqlite3").read_bytes() == before
        assert not (app / "releases").exists()
        command("install", "--host", "codex", "--host-dir", str(root / "codex"))
        command("doctor")
        asyncio.run(stdio(root, character))
        command("uninstall")
        print(
            json.dumps(
                {
                    "ok": True,
                    "checks": [
                        "fresh-install",
                        "real-stdio-reconnect",
                        "source-relocation",
                        "native-configs",
                        "one-live-http-runtime-two-clients-bidirectional",
                        "update",
                        "rollback",
                        "uninstall-preserves-database",
                        "reinstall-preserves-memory",
                    ],
                }
            )
        )


if __name__ == "__main__":
    main()
