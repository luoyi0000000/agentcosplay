"""Check native setup isolation, validation and resumable authoritative bindings.
验证原生安装隔离、校验与可续接的权威绑定。
"""

import asyncio
import copy
import json
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import yaml

import install
from character_runtime.identity import bind
from character_runtime.models import CharacterDefinition
from character_runtime.native_install import NativeSetup, bind_routes, merge_settings
from character_runtime.runtime import Runtime
from character_runtime.scope import ScopeResolver
from character_runtime.storage import SQLiteStorage


def main():
    assert install.hermes_command(Path("/host/venv/bin/python"))[:3] == [
        "/host/venv/bin/python",
        "-I",
        "-c",
    ]
    with TemporaryDirectory() as directory:
        root = Path(directory)
        storage = SQLiteStorage(root / "runtime.sqlite3")
        try:
            rt = Runtime(storage, "owner")
            character = rt.characters.create(CharacterDefinition(name="synthetic"))
            raw = {
                "owner_verified": True,
                "host_id": "hermes",
                "routes": [
                    {
                        "platform": "qq",
                        "chat_id": "chat",
                        "chat_type": "dm",
                        "runtime_platform": "qq-app",
                        "endpoint": "external-chat",
                        "kind": "dm",
                        "character_id": character.id,
                        "actors": [{"actor_id": "actor", "participant_id": "participant"}],
                    }
                ],
            }

            class Bridge:
                url = "http://127.0.0.1:8765/mcp"
                token_file = root / "token"

                async def call(self, tool, args):
                    if tool == "identity_control":
                        return bind(storage, "owner", **args)
                    assert tool == "endpoint_bind"
                    return ScopeResolver(storage, "owner").bind_endpoint(**args)

            setup = NativeSetup.model_validate(raw)
            first = asyncio.run(bind_routes(setup, Bridge()))
            assert asyncio.run(bind_routes(setup, Bridge())) == first
            assert first["routes"][0]["endpoint_id"] != "external-chat"
            text = merge_settings("unrelated: retained\n", first)
            assert "unrelated: retained" in text and merge_settings(text, first) == text
            try:
                merge_settings(text, {**first, "host_id": "other"})
            except ValueError:
                pass
            else:
                raise AssertionError("Conflicting configuration overwritten")
            for mutate in (
                lambda x: x.update(owner_verified=False),
                lambda x: x["routes"][0].update(endpoint_id="fabricated"),
                lambda x: x["routes"][0].update(kind="group"),
                lambda x: x["routes"][0].update(actors=[]),
                lambda x: x["routes"].append(copy.deepcopy(x["routes"][0])),
            ):
                invalid = copy.deepcopy(raw)
                mutate(invalid)
                try:
                    NativeSetup.model_validate(invalid)
                except ValueError:
                    pass
                else:
                    raise AssertionError("Unsafe route accepted")
            # CLI preflight must fail before creating a Runtime or touching a Host.
            # 缺少真实宿主时，在创建 Runtime 或修改宿主前失败。
            with (
                patch("install.shutil.which", return_value=None),
                patch("install.install") as build,
            ):
                try:
                    install.native_hermes(
                        root / "install", root / "host", root / "routes", root / "python", 8765
                    )
                except ValueError:
                    pass
                else:
                    raise AssertionError("Missing Host CLI accepted")
                build.assert_not_called()
        finally:
            storage.close()
    print(
        "PASS native route validation, authoritative IDs, interrupted replay and config protection"
    )
    orchestration()


def orchestration():
    """Use a real installed HTTP Runtime with a synthetic official CLI boundary.
    使用真实安装的 HTTP Runtime 和合成官方 CLI 边界；不冒充真实 Hermes 验收。
    """
    with TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        host, data, app = root / "host", root / "data", root / "app"
        host.mkdir()
        (host / "config.yaml").write_text("unrelated: preserved\n")
        data.mkdir()
        storage = SQLiteStorage(data / "runtime.sqlite3")
        try:
            character = Runtime(storage, "owner").characters.create(
                CharacterDefinition(name="synthetic")
            )
        finally:
            storage.close()
        routes = root / "routes.json"
        routes.write_text(
            json.dumps(
                {
                    "owner_verified": True,
                    "host_id": "hermes",
                    "routes": [
                        {
                            "platform": "qq",
                            "chat_id": "chat",
                            "chat_type": "dm",
                            "kind": "dm",
                            "runtime_platform": "qq-app",
                            "endpoint": "external",
                            "character_id": character.id,
                            "actors": [{"actor_id": "actor", "participant_id": "owner"}],
                        }
                    ],
                }
            )
        )
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        original_run, original_which, original_popen = install.run, shutil.which, subprocess.Popen
        children, calls = [], []
        fail_doctor = True
        host_version = "Host-owned-version"

        def run(command, **kwargs):
            if len(command) > 3 and command[3] == "from hermes_cli.main import main; main()":
                assert command[:3] == [sys.executable, "-I", "-c"]
                command = ["synthetic-hermes", *command[4:]]
                calls.append(command[1:])
                assert kwargs["env"]["HERMES_HOME"] == str(host)
                assert "--force" not in command and "--no-deps" not in command
                if command[1:3] == ["plugins", "install"]:
                    target = host / "plugins/agentcosplay"
                    (target / "agentcosplay_host").mkdir(parents=True)
                    shutil.copy2(install.SOURCE / "pyproject.toml", target / "pyproject.toml")
                if command[1:3] == ["plugins", "doctor"] and fail_doctor:
                    raise RuntimeError("Synthetic Doctor refusal")
                if command[1:3] == ["plugins", "enable"]:
                    config = yaml.safe_load((host / "config.yaml").read_text())
                    config["plugins"]["enabled"] = ["agentcosplay"]
                    (host / "config.yaml").write_text(yaml.safe_dump(config))
                if command[1:3] == ["plugins", "disable"]:
                    config = yaml.safe_load((host / "config.yaml").read_text())
                    config["plugins"]["enabled"] = []
                    (host / "config.yaml").write_text(yaml.safe_dump(config))
                return "ok"
            if len(command) > 3 and "import hermes_cli,importlib.metadata" in command[3]:
                return json.dumps([["mcp", host_version]])
            return original_run(command, **kwargs)

        def spawn(*args, **kwargs):
            child = original_popen(*args, **kwargs)
            if "launch.py" in " ".join(args[0]):
                children.append(child)
            return child

        try:
            with (
                patch("install.run", run),
                patch(
                    "install.shutil.which",
                    lambda name: "synthetic-hermes" if name == "hermes" else original_which(name),
                ),
                patch("install.subprocess.Popen", spawn),
            ):
                try:
                    install.native_hermes(
                        app, host, routes, Path(sys.executable), port, data=data, owner="owner"
                    )
                except RuntimeError as error:
                    assert str(error) == "Synthetic Doctor refusal"
                else:
                    raise AssertionError("Doctor failure reported success")
                assert children and all(child.poll() is not None for child in children)
                assert ["plugins", "enable", "agentcosplay"] not in calls
                host_version = "changed-after-interruption"
                with patch("install.install") as build:
                    try:
                        install.native_hermes(
                            app, host, routes, Path(sys.executable), port, data=data, owner="owner"
                        )
                    except ValueError as error:
                        assert "baseline changed" in str(error)
                    else:
                        raise AssertionError("Interrupted dependency baseline was forgotten")
                    build.assert_not_called()
                host_version = "Host-owned-version"
                fail_doctor = False
                result = install.native_hermes(
                    app, host, routes, Path(sys.executable), port, data=data, owner="owner"
                )
                assert result["ok"] and result["gateway_restart_required"]
                assert result["runtime_started"] and not result["real_platform_verified"]
                config = yaml.safe_load((host / "config.yaml").read_text())
                assert config["unrelated"] == "preserved"
                assert (
                    config["plugins"]["entries"]["agentcosplay"]["settings"]["routes"][0][
                        "endpoint_id"
                    ]
                    != "external"
                )
                assert sum(call[:2] == ["plugins", "install"] for call in calls) == 1
                install.connect(app, "hermes", host, "stdio", port)
                config = yaml.safe_load((host / "config.yaml").read_text())
                assert "agentcosplay" not in config["plugins"]["enabled"], (
                    "Native plugin left enabled after stdio fallback"
                )
                assert "settings" not in config["plugins"]["entries"]["agentcosplay"]
                # Exercise uninstall from native again without rebuilding the Runtime.
                # 复用已安装 Runtime 验证从原生模式卸载，不额外重建环境。
                with patch("install.install"):
                    result = install.native_hermes(
                        app, host, routes, Path(sys.executable), port, data=data, owner="owner"
                    )
                    assert result["ok"]
                for child in children:
                    if child.poll() is None:
                        child.terminate()
                        child.wait(timeout=20)
                install.uninstall(app)
                config = yaml.safe_load((host / "config.yaml").read_text())
                assert "agentcosplay" not in config["plugins"]["enabled"]
                assert "settings" not in config["plugins"]["entries"]["agentcosplay"]
                assert (data / "runtime.sqlite3").exists()
        finally:
            for child in children:
                if child.poll() is None:
                    child.terminate()
                    child.wait(timeout=20)
        print("PASS real isolated native Runtime, synthetic CLI refusal, cleanup and retry")


if __name__ == "__main__":
    main()
