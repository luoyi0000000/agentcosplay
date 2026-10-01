#!/usr/bin/env python3
"""Complete local-first installation using only Python's standard library.

仅使用 Python 标准库完成本地优先安装，不覆盖用户数据与未托管配置。
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import tomllib
import uuid
from pathlib import Path
from typing import Any

from runtime.character_runtime.paths import default_base, validate_data_path

SOURCE = Path(__file__).resolve().parent
UNSET = object()
LAUNCHER = """import json, os, pathlib, sys
root = pathlib.Path(__file__).resolve().parent
state = json.loads((root / "installed.json").read_text(encoding="utf-8"))
if state.get("uninstalled"):
    raise SystemExit("agentcosplay is uninstalled; character data is preserved")
release = (root / "releases" / state["active"]).resolve()
if release.parent != (root / "releases").resolve():
    raise SystemExit("Invalid installed release")
python = release / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
os.environ["CHARACTER_DATA_DIR"] = state["data_dir"]
os.environ["CHARACTER_OWNER"] = state["owner"]
for key in ("PYTHONPATH", "PYTHONHOME"):
    os.environ.pop(key, None)
if "http" in sys.argv[1:] and state.get("http_port"):
    os.environ["CHARACTER_TOKEN"] = (root / "http-token").read_text().strip()
    os.environ["CHARACTER_HOST"] = "127.0.0.1"
    os.environ["CHARACTER_PORT"] = str(state["http_port"])
    os.environ["CHARACTER_RESOURCE_URL"] = f"http://127.0.0.1:{state['http_port']}/mcp"
os.execv(str(python), [str(python), "-I", "-m", "character_runtime", *sys.argv[1:]])
"""


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read(path: Path) -> bytes | None:
    if path.is_symlink():
        raise ValueError(f"Refusing symlink file: {path}")
    return path.read_bytes() if path.exists() else None


def atomic_write(path: Path, value: bytes | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError(f"Refusing symlink file: {path}")
    if value is None:
        path.unlink(missing_ok=True)
        return
    fd, name = tempfile.mkstemp(prefix=".agentcosplay-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(value)
            file.flush()
            os.fsync(file.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def encode(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def state_of(root: Path) -> dict[str, Any]:
    value = read(root / "installed.json")
    return json.loads(value) if value else {}


@contextlib.contextmanager
def lock(root: Path):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / "install.lock"
    if path.is_symlink():
        raise ValueError("Installation lock must not be a symlink")
    # Kernel-owned lock is released even after SIGKILL. Keep its inode stable.
    fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "r+b") as file:
        try:
            if os.name == "nt":
                import msvcrt

                if path.stat().st_size == 0:
                    file.write(b"0")
                    file.flush()
                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError("Another installation is running; wait for it to finish") from None
        try:
            file.seek(0)
            file.write(str(os.getpid()).encode())
            file.truncate()
            file.flush()
            yield
        finally:
            if os.name == "nt":
                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(file.fileno(), fcntl.LOCK_UN)


class Transaction:
    """Journal writes; recover interrupted changes without clobbering edits."""

    def __init__(self, root: Path):
        self.root = root
        self.path = root / "pending.json"
        if self.path.exists():
            raise ValueError("Interrupted installation found; run recover before continuing")
        self.entries: list[dict[str, Any]] = []

    def write(self, path: Path, value: bytes | None, *, expected: Any = UNSET) -> None:
        old = read(path)
        if expected is not UNSET and old != expected:
            raise ValueError("File changed during installation; reload configuration and retry")
        if old == value:
            return
        self.entries.append(
            {
                "path": str(path),
                "before": None if old is None else base64.b64encode(old).decode(),
                "after": None if value is None else digest(value),
            }
        )
        atomic_write(self.path, encode(self.entries))
        atomic_write(path, value)

    def commit(self) -> None:
        if self.path.exists():
            backups = self.root / "backups"
            backups.mkdir(mode=0o700, exist_ok=True)
            os.replace(self.path, backups / f"{uuid.uuid4().hex}.json")

    def rollback(self) -> None:
        recover(self.root)


def recover(root: Path) -> None:
    path = root / "pending.json"
    if not path.exists():
        return
    entries = json.loads(path.read_bytes())
    # Validate every preimage before any restoration. No partial rollback across external edits.
    for entry in reversed(entries):
        file = Path(entry["path"])
        before = None if entry["before"] is None else base64.b64decode(entry["before"])
        current = read(file)
        if current != before and (None if current is None else digest(current)) != entry["after"]:
            raise ValueError(
                f"File changed after interruption; preserve and reconcile manually: {file}"
            )
    for entry in reversed(entries):
        atomic_write(
            Path(entry["path"]),
            None if entry["before"] is None else base64.b64decode(entry["before"]),
        )
    path.unlink()


def python_at(release: Path) -> Path:
    return release / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def release_at(root: Path, name: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9.-]+", name):
        raise ValueError("Invalid release name")
    path = (root / "releases" / name).resolve()
    if path.parent != (root / "releases").resolve():
        raise ValueError("Release escapes installation")
    return path


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    input: str | None = None,
    stage: str = "subprocess",
) -> str:
    """Capture subprocess bytes; expose only a fixed stage, category and exit code.

    捕获子进程原始字节，仅暴露固定阶段、错误类别和退出码，不输出私密内容。
    """
    if stage not in {
        "subprocess",
        "bootstrap",
        "dependencies",
        "health",
        "host-config",
        "native-preflight",
        "native-plugin-install",
        "native-plugin-enable",
        "native-plugin-disable",
        "native-plugin-doctor",
        "native-bind",
        "native-settings",
        "native-probe",
    }:
        raise ValueError("Unknown installation stage")
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        input=None if input is None else input.encode("utf-8"),
        capture_output=True,
        timeout=600,
    )
    if result.returncode:
        # Never decode/echo stderr: even decoding errors can expose private bytes.
        # 不解码或回显 stderr；解码异常本身也可能暴露私密字节。
        if stage == "health" and len(result.stdout) <= 1024:
            from runtime.character_runtime.health_diagnostics import ERROR_TYPES, STAGES

            try:
                diagnostic = json.loads(result.stdout)
            except (ValueError, UnicodeDecodeError):
                diagnostic = None
            if (
                isinstance(diagnostic, dict)
                and diagnostic.get("ok") is False
                and isinstance(diagnostic.get("stage"), str)
                and diagnostic["stage"] in STAGES
                and isinstance(diagnostic.get("exception_type"), str)
                and diagnostic["exception_type"] in ERROR_TYPES
            ):
                raise RuntimeError(
                    f"Step failed ({diagnostic['stage']}, "
                    f"{diagnostic['exception_type']}, exit {result.returncode})"
                )
        category = "subprocess-failure"
        for signature, label in (
            (b"UnicodeEncodeError", "encoding"),
            (b"UnicodeDecodeError", "encoding"),
            (b"ModuleNotFoundError", "missing-module"),
            (b"PermissionError", "permission"),
        ):
            if signature in result.stderr:
                category = label
                break
        raise RuntimeError(
            f"Step failed ({stage}, {category}, exit {result.returncode}); "
            "check dependencies, permissions and host config"
        )
    try:
        return result.stdout.decode("utf-8")
    except UnicodeDecodeError:
        raise RuntimeError(f"Step failed ({stage}, invalid-output-encoding)") from None


def build_release(root: Path, source: Path) -> Path:
    release = root / "releases" / uuid.uuid4().hex
    release.mkdir(parents=True, mode=0o700)
    try:
        for name in (
            "runtime/character_runtime",
            "runtime/pyproject.toml",
            "runtime/uv.lock",
            "runtime/LICENSE",
            "agentcosplay_host",
            "pyproject.toml",
            "build-constraints.txt",
            "LICENSE",
            "plugins/agentcosplay/skills",
        ):
            item = source / name
            if item.is_symlink():
                raise ValueError("Source package must not contain symlinks")
            if item.is_dir():
                shutil.copytree(
                    item,
                    release / name,
                    symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".venv", "dist"),
                )
                if any(p.is_symlink() for p in (release / name).rglob("*")):
                    raise ValueError("Source package must not contain symlinks")
            else:
                shutil.copy2(item, release / name)
        uv = shutil.which("uv")
        if not uv:
            bootstrap = root / "bootstrap"
            if not python_at(bootstrap).exists():
                run([sys.executable, "-m", "venv", str(bootstrap / ".venv")], stage="bootstrap")
            if not (python_at(bootstrap).parent / ("uv.exe" if os.name == "nt" else "uv")).exists():
                run(
                    [str(python_at(bootstrap)), "-m", "pip", "install", "uv==0.11.7"],
                    stage="bootstrap",
                )
            uv = str(python_at(bootstrap).parent / ("uv.exe" if os.name == "nt" else "uv"))
        clean_env = {
            k: v
            for k, v in os.environ.items()
            if k not in {"VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "UV_PROJECT_ENVIRONMENT"}
        }
        clean_env["UV_CACHE_DIR"] = str(root / "cache")
        # The release keeps its own environment; Host dependency resolution never runs here.
        # 发布目录拥有独立环境；此处绝不操作宿主的依赖解析。
        clean_env["UV_PROJECT_ENVIRONMENT"] = str(release / ".venv")
        run(
            [
                uv,
                "sync",
                "--project",
                "runtime",
                "--locked",
                "--no-dev",
                "--no-editable",
                "--python",
                sys.executable,
            ],
            cwd=release,
            env=clean_env,
            stage="dependencies",
        )
        return release
    except BaseException:
        shutil.rmtree(release)
        raise


def health(release: Path, data: Path, owner: str) -> dict[str, Any]:
    env = {**os.environ, "CHARACTER_DATA_DIR": str(data), "CHARACTER_OWNER": owner}
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    value = json.loads(
        run(
            [str(python_at(release)), "-I", "-m", "character_runtime", "doctor"],
            cwd=release,
            env=env,
            stage="health",
        )
    )
    if not value.get("ok"):
        raise RuntimeError("Runtime health check failed")
    return value


def host_paths(host: str, host_dir: Path | None) -> tuple[Path, Path]:
    if host_dir is None:
        if host == "codex":
            host_dir = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
        elif host == "hermes":
            host_dir = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
        else:
            raise ValueError(
                "AstrBot requires --host-dir pointing to its actual persistent data directory"
            )
    host_dir = host_dir.expanduser().resolve()
    if any((p / ".git").exists() for p in (host_dir, *host_dir.parents)):
        raise ValueError("Host configuration may contain credentials; keep it outside Git")
    return host_dir / {
        "codex": "config.toml",
        "hermes": "config.yaml",
        "astrbot": "mcp_server.json",
    }[host], host_dir / "skills/agentcosplay"


def config_text(
    release: Path, host: str, text: str, server: dict[str, Any], remove: bool = False
) -> str:
    value = run(
        [str(python_at(release)), "-I", "-m", "character_runtime.host_config"],
        cwd=release,
        input=json.dumps({"host": host, "text": text, "server": server, "remove": remove}),
        stage="host-config",
    )
    return json.loads(value)["text"]


def attach(
    root: Path,
    release: Path,
    host: str,
    host_dir: Path | None,
    previous: dict[str, Any],
    tx: Transaction,
    desired: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config, skill = host_paths(host, host_dir)
    server: dict[str, Any] = {
        "command": getattr(sys, "_base_executable", sys.executable),
        "args": [str(root / "launch.py"), "serve"],
    }
    if host == "astrbot":
        server["active"] = True
    old = next((x for x in previous.get("integrations", []) if x["config"] == str(config)), None)
    if old:
        server = old["server"]  # launcher remains stable even when bootstrap Python changes
    current = read(config)
    text = (current or b"").decode()
    if desired is not None:
        if old:
            text = config_text(release, host, text, server, True)
        server = desired
    new_text = config_text(release, host, text, server)
    files: dict[str, str] = {}
    before_files: dict[str, bytes | None] = {}
    source_skill = release / "plugins/agentcosplay/skills/agentcosplay"
    for source in source_skill.rglob("*"):
        if source.is_file():
            name = source.relative_to(source_skill).as_posix()
            existing = read(skill / name)
            before_files[name] = existing
            content = source.read_bytes()
            expected = (old or {}).get("files", {}).get(name)
            if existing is not None and existing != content and digest(existing) != expected:
                raise ValueError(
                    f"Skill file has unowned edits; back it up before installation: {skill / name}"
                )
            files[name] = digest(content)
    tx.write(config, new_text.encode(), expected=current)
    for name in files:
        tx.write(skill / name, (source_skill / name).read_bytes(), expected=before_files[name])
    for name, expected in (old or {}).get("files", {}).items():
        if name not in files:
            existing = read(skill / name)
            if existing is not None and digest(existing) != expected:
                raise ValueError("Obsolete Skill file has user edits")
            tx.write(skill / name, None, expected=existing)
    return {
        **(old or {}),
        "host": host,
        "config": str(config),
        "skill": str(skill),
        "server": server,
        "files": files,
    }


def validate_layout(root: Path, data: Path, source: Path) -> Path:
    data = validate_data_path(data, [root, source])
    if root.is_relative_to(data) or root.is_relative_to(source) or source.is_relative_to(root):
        raise ValueError("Source, installation and character-data directories must not overlap")
    if any((p / ".git").exists() for p in (root, *root.parents)):
        raise ValueError("Install program outside Git repositories")
    return data


def install(
    root: Path, source: Path, data: Path, owner: str, host: str, host_dir: Path | None = None
) -> dict[str, Any]:
    data = validate_layout(root, data, source)
    old = state_of(root)
    if old and (old["data_dir"] != str(data) or old["owner"] != owner):
        raise ValueError(
            "Update cannot change data directory or identity; use explicit export/import"
        )
    tx = Transaction(root)
    release = build_release(root, source)
    try:
        result = health(release, data, owner)
        launcher = root / "launch.py"
        existing_launcher = read(launcher)
        if existing_launcher not in (None, LAUNCHER.encode()):
            raise ValueError("Installed launcher has user edits; refusing overwrite")
        tx.write(launcher, LAUNCHER.encode())
        integrations = list(old.get("integrations", []))
        targets = [(x["host"], Path(x["config"]).parent) for x in integrations]
        if host != "generic" and (host, host_paths(host, host_dir)[0].parent) not in targets:
            targets.append((host, host_paths(host, host_dir)[0].parent))
        for name, directory in targets:
            entry = attach(root, release, name, directory, old, tx)
            integrations = [x for x in integrations if x["config"] != entry["config"]] + [entry]
        state = {
            **old,
            "active": release.name,
            "previous": old.get("active"),
            "data_dir": str(data),
            "owner": owner,
            "version": result["version"],
            "integrations": integrations,
            "uninstalled": False,
        }
        # Commit point: configs point at the stable launcher; selected release changes last.
        tx.write(root / "installed.json", encode(state))
        tx.commit()
        return {
            "ok": True,
            "version": result["version"],
            "install_root": str(root),
            "data_dir": str(data),
            "hosts": [x["host"] for x in integrations],
            "host_reload_required": True,
        }
    except BaseException:
        tx.rollback()
        shutil.rmtree(release)
        raise


def rollback(root: Path) -> dict[str, Any]:
    old = state_of(root)
    if not old.get("previous") or old.get("uninstalled"):
        raise ValueError("No previous installed release")
    release = release_at(root, old["previous"])
    result = health(release, validate_data_path(Path(old["data_dir"]), [root]), old["owner"])
    tx = Transaction(root)
    try:
        entries = [
            attach(root, release, x["host"], Path(x["config"]).parent, old, tx)
            for x in old["integrations"]
        ]
        state = {
            **old,
            "active": old["previous"],
            "previous": old["active"],
            "version": result["version"],
            "integrations": entries,
        }
        tx.write(root / "installed.json", encode(state))
        tx.commit()
        return {"ok": True, "version": state["version"], "data_preserved": True}
    except BaseException:
        tx.rollback()
        raise


def uninstall(root: Path) -> dict[str, Any]:
    old = state_of(root)
    if not old:
        return {"ok": True, "already_uninstalled": True}
    validate_data_path(Path(old["data_dir"]), [root])
    if old.get("uninstalled"):
        # A locked release or process interruption may have stopped post-commit cleanup.
        for name in ("releases", "cache", "bootstrap"):
            if (root / name).exists():
                shutil.rmtree(root / name)
        return {"ok": True, "already_uninstalled": True, "data_preserved": True}
    release = release_at(root, old["active"])
    tx = Transaction(root)
    try:
        for entry in old["integrations"]:
            if entry.get("native_hermes"):
                detach_native(release, entry, tx)
            config = Path(entry["config"])
            original = read(config)
            content = config_text(
                release, entry["host"], (original or b"").decode(), entry["server"], True
            )
            tx.write(config, content.encode(), expected=original)
            for name, expected in entry["files"].items():
                path = Path(entry["skill"]) / name
                current = read(path)
                if current is not None:
                    if digest(current) != expected:
                        raise ValueError(
                            f"Skill changed since installation; preserve before uninstall: {path}"
                        )
                    tx.write(path, None, expected=current)
        tx.write(
            root / "installed.json",
            encode(
                {**old, "uninstalled": True, "active": None, "previous": None, "integrations": []}
            ),
        )
        tx.commit()
    except BaseException:
        tx.rollback()
        raise
    for name in ("releases", "cache", "bootstrap"):
        if (root / name).exists():
            shutil.rmtree(root / name)
    return {"ok": True, "data_preserved": True, "data_dir": old["data_dir"]}


def connect(
    root: Path,
    host: str,
    host_dir: Path | None,
    transport: str,
    port: int,
    native_hermes: bool = False,
    native_astrbot: bool = False,
) -> dict[str, Any]:
    if native_hermes and (host != "hermes" or transport != "http"):
        raise ValueError("Native Hermes requires --host hermes --transport http")
    if native_astrbot and (host != "astrbot" or transport != "http"):
        raise ValueError("Native AstrBot requires --host astrbot --transport http")
    old = state_of(root)
    if not old or old.get("uninstalled") or host in {"auto", "generic"}:
        raise ValueError("Connect requires an installed Runtime and explicit supported --host")
    release = release_at(root, old["active"])
    tx = Transaction(root)
    try:
        if not native_hermes:
            config_path = str(host_paths(host, host_dir)[0])
            for entry in old["integrations"]:
                if entry["config"] == config_path and entry.get("native_hermes"):
                    detach_native(release, entry, tx)
                    del entry["native_hermes"]
        server: dict[str, Any] = {
            "command": getattr(sys, "_base_executable", sys.executable),
            "args": [str(root / "launch.py"), "serve"],
        }
        state = dict(old)
        if transport == "http":
            if not 1024 <= port <= 65535 or old.get("http_port", port) != port:
                raise ValueError("Choose one stable unprivileged port for the shared Runtime")
            value = read(root / "http-token")
            if value is None:
                value = secrets.token_urlsafe(48).encode()
                tx.write(root / "http-token", value)
            server = {
                "url": f"http://127.0.0.1:{port}/mcp",
                "http_headers" if host == "codex" else "headers": {
                    "Authorization": "Bearer " + value.decode().strip()
                },
            }
            if native_hermes or native_astrbot:
                # Middleware failure or plugin disable must not expose owner-level MCP tools.
                # 中间件失败或插件停用时，MCP 发现凭据仍不能执行 Owner 工具。
                credential = hmac.new(
                    value.decode().strip().encode(),
                    b"agentcosplay:model-discovery:v1",
                    hashlib.sha256,
                ).hexdigest()
                server["headers"]["Authorization"] = "Bearer " + credential
            state["http_port"] = port
        if host == "astrbot":
            server["active"] = True
            if transport == "http":
                server["transport"] = "streamable_http"
        entry = attach(root, release, host, host_dir, old, tx, desired=server)
        state["integrations"] = [
            x for x in old["integrations"] if x["config"] != entry["config"]
        ] + [entry]
        tx.write(root / "installed.json", encode(state))
        tx.commit()
        return {
            "ok": True,
            "host": host,
            "transport": transport,
            "host_reload_required": True,
            "start_shared_runtime": transport == "http",
        }
    except BaseException:
        tx.rollback()
        raise


def hermes_command(python: Path) -> list[str]:
    """Run Hermes' official entry point in the exact interpreter being inspected.
    在依赖快照对应的同一解释器中执行官方 Hermes 入口，不通过 PATH 另选环境。
    """
    return [str(python), "-I", "-c", "from hermes_cli.main import main; main()"]


def native_worker(release: Path, action: str, **arguments: Any) -> Any:
    """Keep YAML and protocol dependencies inside the installed Runtime.
    YAML 与协议依赖只在已安装 Runtime 中执行。
    """
    result = json.loads(
        run(
            [str(python_at(release)), "-I", "-m", "character_runtime.native_install"],
            cwd=release,
            input=json.dumps({"action": action, **arguments}),
            stage="native-" + (action if action in {"bind", "settings", "probe"} else "preflight"),
        )
    )
    if result.get("ok") is not True:
        raise RuntimeError("Native Hermes validation failed")
    return result["result"]


def detach_native(release: Path, entry: dict[str, Any], tx: Transaction) -> None:
    """Disable our native integration before removing its MCP authority.
    撤销 MCP 权限前先禁用本安装管理的原生插件；用户配置有冲突则保留并拒绝。
    """
    native = entry["native_hermes"]
    config = Path(entry["config"])
    native_worker(
        release, "remove", text=(read(config) or b"").decode(), settings=native["settings"]
    )
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
    env["HERMES_HOME"] = str(config.parent)
    run(
        [*hermes_command(Path(native["python"])), "plugins", "disable", "agentcosplay"],
        env=env,
        input="",
        stage="native-plugin-disable",
    )
    current = read(config)
    text = native_worker(
        release, "remove", text=(current or b"").decode(), settings=native["settings"]
    )
    tx.write(config, text.encode(), expected=current)


def native_hermes(
    root: Path,
    host_dir: Path,
    routes_file: Path,
    hermes_python: Path,
    port: int,
    *,
    data: Path | None = None,
    owner: str | None = None,
) -> dict[str, Any]:
    """Orchestrate official plugin admission; never merge Runtime and Host environments.

    编排官方插件准入；不合并 Runtime 与宿主环境。失败保留可重放绑定和已完成安装，
    配置写入使用现有事务；不回滚身份数据，也不自动重启 Gateway。
    """
    cli = hermes_command(hermes_python)
    if not hermes_python.is_file():
        raise ValueError("Native Hermes requires its CLI and explicit --hermes-python")
    config_path, _ = host_paths("hermes", host_dir)
    if not config_path.is_file():
        raise ValueError("Select an existing Hermes profile with --host-dir")
    raw = read(routes_file)
    if raw is None or len(raw) > 200000:
        raise ValueError("Provide a bounded owner-verified --routes-file")
    try:
        setup = json.loads(raw)
    except (ValueError, UnicodeError):
        raise ValueError("Invalid route JSON") from None
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"}
    }
    env["HERMES_HOME"] = str(config_path.parent)
    run([*cli, "--version"], env=env, input="", stage="native-preflight")

    def versions() -> str:
        # Snapshot all distributions in the explicitly selected Host interpreter.
        # 快照明确指定宿主解释器的全部发行包；不把名称或版本输出到日志。
        return run(
            [
                str(hermes_python),
                "-I",
                "-c",
                "import hermes_cli,importlib.metadata as m,json; "
                "print(json.dumps(sorted((d.metadata['Name'],d.version) "
                "for d in m.distributions())))",
            ],
            env=env,
            stage="native-preflight",
        )

    before = versions()
    checkpoint = root / ("native-" + digest(str(config_path).encode()) + ".json")
    previous = json.loads(read(checkpoint) or b"{}")
    baseline = {"python": str(hermes_python), "versions": before}
    if previous.get("complete") is False and previous.get("baseline") != baseline:
        raise ValueError(
            "Host dependency baseline changed since interrupted native setup; review before retry"
        )
    atomic_write(checkpoint, encode({"complete": False, "baseline": baseline}))
    old = state_of(root)
    selected_owner = owner or old.get("owner", "local-user")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,200}", selected_owner):
        raise ValueError("Invalid Runtime owner identifier")
    install(
        root,
        SOURCE,
        data or Path(old.get("data_dir", default_base() / "characters")),
        selected_owner,
        "generic",
    )
    state = state_of(root)
    release = release_at(root, state["active"])

    def worker(action: str, **arguments: Any) -> Any:
        return native_worker(release, action, **arguments)

    worker("validate", setup=setup)
    connect(root, "hermes", config_path.parent, "http", port, native_hermes=True)
    address = {"url": f"http://127.0.0.1:{port}/mcp", "token_file": str(root / "http-token")}
    child = None
    complete = False
    try:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                pass
        except ConnectionRefusedError:
            # Only an explicit native installation starts loopback HTTP; never restart a Host.
            # 仅显式原生安装启动本机 HTTP；绝不重启宿主。
            child = subprocess.Popen(
                [
                    str(python_at(release)),
                    "-I",
                    str(root / "launch.py"),
                    "serve",
                    "--transport",
                    "http",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=os.name != "nt",
                env=env,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    raise RuntimeError("Native Runtime startup failed")
                try:
                    worker("probe", **address)
                    break
                except RuntimeError:
                    time.sleep(0.2)
            else:
                raise RuntimeError("Native Runtime readiness timed out")
        worker("probe", **address)  # Authenticate existing listeners before any binding.
        target = config_path.parent / "plugins" / "agentcosplay"
        if not target.exists():
            run(
                [*cli, "plugins", "install", "luoyi0000000/agentcosplay", "--no-enable"],
                env=env,
                input="",
                stage="native-plugin-install",
            )
        metadata = tomllib.loads((target / "pyproject.toml").read_text(encoding="utf-8"))
        if (
            metadata.get("project", {}).get("dependencies") != []
            or not (target / "agentcosplay_host").is_dir()
        ):
            raise ValueError(
                "Installed plugin lacks the isolated Host package; update it before enabling"
            )
        settings = worker("bind", setup=setup, **address)
        current = read(config_path)
        text = worker("settings", text=(current or b"").decode("utf-8"), settings=settings)
        tx = Transaction(root)
        try:
            tx.write(config_path, text.encode("utf-8"), expected=current)
            state = state_of(root)
            for entry in state["integrations"]:
                if entry["config"] == str(config_path):
                    entry["native_hermes"] = {"python": str(hermes_python), "settings": settings}
            # Record ownership before activation, so an interrupted enable can be undone.
            # 激活前记录归属，让启用过程被中断时仍能安全撤销。
            tx.write(root / "installed.json", encode(state))
            tx.commit()
        except BaseException:
            tx.rollback()
            raise
        # Doctor must pass in its own empty profile before granting plugin activation.
        # Doctor 必须先在其空配置中通过，再允许官方激活流程。
        run(
            [*cli, "plugins", "doctor", str(target), "--ci"],
            env=env,
            input="",
            stage="native-plugin-doctor",
        )
        run(
            [*cli, "plugins", "enable", "agentcosplay"],
            env=env,
            input="",
            stage="native-plugin-enable",
        )
        if versions() != before:
            raise RuntimeError(
                "Host dependencies changed during plugin admission; review Hermes environment"
            )
        atomic_write(checkpoint, encode({"complete": True, "baseline": baseline}))
        complete = True
        return {
            "ok": True,
            "gateway_restart_required": True,
            "runtime_started": child is not None,
            "runtime_restart_required": child is None,
            "host_dependencies_unchanged": True,
            "real_platform_verified": False,
        }
    finally:
        if child is not None and not complete:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=10)


def main() -> None:
    parser = argparse.ArgumentParser(description="Install the complete local agentcosplay Runtime")
    parser.add_argument(
        "action",
        choices=[
            "install",
            "update",
            "connect",
            "doctor",
            "rollback",
            "uninstall",
            "recover",
            "run",
            "native-hermes",
        ],
        nargs="?",
        default="install",
    )
    parser.add_argument("--install-root", type=Path, default=default_base() / "runtime")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--owner")
    parser.add_argument(
        "--host", choices=["auto", "generic", "codex", "hermes", "astrbot"], default="auto"
    )
    parser.add_argument("--host-dir", type=Path)
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--native-hermes", action="store_true")
    parser.add_argument("--native-astrbot", action="store_true")
    parser.add_argument("--routes-file", type=Path)
    parser.add_argument("--hermes-python", type=Path)
    args = parser.parse_args()
    root = args.install_root.expanduser().resolve()
    try:
        if args.action == "run":
            os.execv(
                sys.executable,
                [sys.executable, str(root / "launch.py"), "serve", "--transport", args.transport],
            )
        with lock(root):
            old = state_of(root)
            if args.action == "recover":
                recover(root)
                result = {"ok": True, "recovered": True}
            elif (root / "pending.json").exists():
                raise ValueError("Interrupted transaction exists; use recover first")
            elif args.action == "native-hermes":
                if args.host_dir is None or args.routes_file is None or args.hermes_python is None:
                    raise ValueError(
                        "Native Hermes requires --host-dir, --routes-file and --hermes-python"
                    )
                result = native_hermes(
                    root,
                    args.host_dir.expanduser().resolve(),
                    args.routes_file.expanduser().resolve(),
                    args.hermes_python.expanduser().absolute(),
                    args.port,
                    data=args.data_dir,
                    owner=args.owner,
                )
            elif args.action in {"install", "update"}:
                host = args.host
                if host == "auto":
                    hosts = [
                        h for h in ("codex", "hermes") if host_paths(h, None)[0].parent.exists()
                    ]
                    if len(hosts) > 1:
                        raise ValueError("Multiple hosts detected; use --host for the active Agent")
                    host = hosts[0] if hosts else "generic"
                data = args.data_dir or Path(old.get("data_dir", default_base() / "characters"))
                owner = args.owner or old.get("owner", "local-user")
                if not re.fullmatch(r"[A-Za-z0-9_.-]{1,200}", owner):
                    raise ValueError(
                        "Owner must be 1-200 ASCII letters, digits, dot, underscore or hyphen"
                    )
                result = install(root, SOURCE, data, owner, host, args.host_dir)
            elif args.action == "connect":
                result = connect(
                    root,
                    args.host,
                    args.host_dir,
                    args.transport,
                    args.port,
                    args.native_hermes,
                    args.native_astrbot,
                )
            elif args.action == "rollback":
                result = rollback(root)
            elif args.action == "uninstall":
                result = uninstall(root)
            else:
                if not old or old.get("uninstalled"):
                    raise ValueError("Runtime not installed")
                release = release_at(root, old["active"])
                for entry in old["integrations"]:
                    original = (read(Path(entry["config"])) or b"").decode()
                    if (
                        config_text(release, entry["host"], original, entry["server"], True)
                        == original
                    ):
                        raise ValueError("Installed host entry is missing")
                    for name, expected in entry["files"].items():
                        if digest(read(Path(entry["skill"]) / name) or b"") != expected:
                            raise ValueError("Installed Skill missing or changed")
                result = health(
                    release, validate_data_path(Path(old["data_dir"]), [root]), old["owner"]
                )
        # Machine-readable output must survive non-UTF-8 redirected consoles.
        # 机器可读输出必须兼容非 UTF-8 的重定向控制台，中文由 JSON 转义保留。
        print(json.dumps(result))
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        # Exception details can contain host configuration or secrets; keep CLI output bounded.
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": str(error)
                    if isinstance(error, (ValueError, RuntimeError))
                    else "Installation failed; check permissions, paths and dependencies.",
                }
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
