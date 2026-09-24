"""Opt-in, network-using acceptance of the actual installer in disposable directories.

Run: uv run --locked python -m scripts.check_installation
No existing host configuration is touched. All character content is synthetic.
"""

import asyncio
import json
import os
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


def check_pipe_encoding() -> None:
    """Exercise real JSON entry points through a Windows-style legacy pipe.

    用 Windows 旧编码管道执行真实 JSON 入口，检查中文路径和配置不会丢失。
    """
    with tempfile.TemporaryDirectory(prefix="agentcosplay 中文 encoding ") as directory:
        env = {
            **os.environ,
            "PYTHONIOENCODING": "cp1252",
            "PYTHONUTF8": "0",
            "CHARACTER_DATA_DIR": directory,
            "CHARACTER_OWNER": "encoding-check",
        }
        result = subprocess.run(
            [sys.executable, "-m", "character_runtime", "doctor"],
            cwd=SOURCE,
            env=env,
            capture_output=True,
            timeout=60,
        )
        assert result.returncode == 0, "Doctor cannot emit Unicode paths through a legacy pipe"
        report = json.loads(result.stdout.decode("ascii"))
        assert report["ok"] and report["data_dir"] == str(Path(directory).resolve())
        for host in ("codex", "hermes", "astrbot"):
            request = {
                "host": host,
                "text": "",
                "server": {"command": sys.executable, "args": [directory, "中文配置"]},
            }
            result = subprocess.run(
                [sys.executable, "-m", "character_runtime.host_config"],
                cwd=SOURCE,
                env=env,
                input=json.dumps(request).encode("ascii"),
                capture_output=True,
                timeout=30,
            )
            assert result.returncode == 0, f"{host} config cannot use a legacy pipe"
            text = json.loads(result.stdout.decode("ascii"))["text"]
            if host == "codex":
                import tomllib

                config = tomllib.loads(text)
            elif host == "hermes":
                config = yaml.safe_load(text)
            else:
                config = json.loads(text)
            key = "mcpServers" if host == "astrbot" else "mcp_servers"
            assert config[key]["agentcosplay"] == request["server"]
    print("PASS legacy-pipe-unicode", flush=True)


def check_failure_privacy() -> None:
    """Keep raw dependency stderr private even when its encoding is invalid.

    依赖错误输出即使含非法编码，也不得泄露到安装器的错误信息中。
    """
    import install

    try:
        install.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.stderr.buffer.write("
                "b'UnicodeEncodeError: https://user:synthetic-secret@example.invalid/\\xff'); "
                "sys.exit(7)",
            ]
        )
    except RuntimeError as error:
        message = str(error)
        assert "exit 7" in message
        assert "synthetic-secret" not in message and "example.invalid" not in message
    else:
        raise AssertionError("Failed subprocess reported success")
    print("PASS failure-privacy", flush=True)


def check_interrupted_install() -> None:
    """Recover a killed config transaction, but never overwrite a later user edit.

    恢复被强制中断的配置事务，同时拒绝覆盖中断后用户自行修改的文件。
    """
    import install

    with tempfile.TemporaryDirectory(prefix="agentcosplay interruption ") as directory:
        root = Path(directory)
        config = root / "配置.json"
        original = '{"label":"保留中文"}'.encode()
        config.write_bytes(original)
        probe = (
            "import os,sys; from pathlib import Path; import install; "
            "root=Path(sys.argv[1]); "
            "tx=install.Transaction(root); "
            "tx.write(root / '配置.json', b'partial'); os._exit(9)"
        )
        for user_edit in (False, True):
            result = subprocess.run([sys.executable, "-c", probe, str(root)], cwd=SOURCE)
            assert result.returncode == 9 and (root / "pending.json").exists()
            if user_edit:
                config.write_bytes(b"user-edit")
                try:
                    install.recover(root)
                except ValueError:
                    assert config.read_bytes() == b"user-edit"
                    assert (root / "pending.json").exists()
                else:
                    raise AssertionError("Recovery overwrote an unrelated user edit")
            else:
                install.recover(root)
                assert config.read_bytes() == original
                assert not (root / "pending.json").exists()
    print("PASS interrupted-install-recovery", flush=True)


async def stdio(root: Path, character: str | None = None) -> str:
    import tomllib

    config = tomllib.loads((root / "codex/config.toml").read_text(encoding="utf-8"))["mcp_servers"][
        "agentcosplay"
    ]
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
        yaml.safe_load((root / "hermes/config.yaml").read_text(encoding="utf-8"))["mcp_servers"][
            "agentcosplay"
        ],
        json.loads((root / "astrbot/mcp_server.json").read_text(encoding="utf-8"))["mcpServers"][
            "agentcosplay"
        ],
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
    check_pipe_encoding()
    check_failure_privacy()
    check_interrupted_install()
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
                encoding="ascii",
                env={**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"},
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
        command(
            "connect",
            "--host",
            "hermes",
            "--host-dir",
            str(root / "hermes"),
            "--transport",
            "http",
            "--port",
            str(port),
            "--native-hermes",
        )
        from character_runtime.auth import LocalTokenVerifier

        config = yaml.safe_load((root / "hermes/config.yaml").read_text(encoding="utf-8"))
        expected_discovery = LocalTokenVerifier(
            (app / "http-token").read_text().strip(), "synthetic", "http://localhost/mcp"
        ).discovery_token
        assert config["mcp_servers"]["agentcosplay"]["headers"]["Authorization"] == (
            "Bearer " + expected_discovery
        )
        print("PASS native Hermes discovery-only configuration", flush=True)
        command(
            "connect",
            "--host",
            "astrbot",
            "--host-dir",
            str(root / "astrbot"),
            "--transport",
            "http",
            "--port",
            str(port),
            "--native-astrbot",
        )
        native_astrbot = json.loads((root / "astrbot/mcp_server.json").read_text(encoding="utf-8"))
        assert native_astrbot["mcpServers"]["agentcosplay"]["headers"]["Authorization"] == (
            "Bearer " + expected_discovery
        )
        print("PASS native AstrBot discovery-only configuration", flush=True)
        first = json.loads((app / "installed.json").read_text(encoding="utf-8"))["active"]
        command("update", "--host", "generic")
        assert json.loads((app / "installed.json").read_text(encoding="utf-8"))["active"] != first
        command("doctor")
        asyncio.run(stdio(root, character))
        command("rollback")
        assert json.loads((app / "installed.json").read_text(encoding="utf-8"))["active"] == first
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
