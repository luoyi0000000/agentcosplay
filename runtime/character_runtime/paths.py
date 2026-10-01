"""Local-first path policy, usable by the installer without third-party dependencies.

本地优先路径策略；安装器使用时不依赖第三方包。
"""

import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path


def default_base(
    platform: str = sys.platform,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Choose the current user's platform data directory, not the source tree.

    选择当前用户的平台数据目录，不放入源码树。
    """

    env = os.environ if env is None else env
    home = Path.home() if home is None else home
    if platform == "win32":
        base = Path(env.get("LOCALAPPDATA") or home / "AppData/Local")
    elif platform == "darwin":
        base = home / "Library/Application Support"
    else:
        base = Path(env.get("XDG_DATA_HOME") or home / ".local/share")
    if not base.is_absolute():
        raise ValueError("Platform data directory must be absolute")
    return base / "agentcosplay"


def validate_data_path(path: Path, program_roots: Sequence[Path] = ()) -> Path:
    """Reject unsafe data locations before persistent files are opened.

    打开持久文件前拒绝不安全的数据位置。
    """

    path = path.expanduser()
    if not path.is_absolute():
        raise ValueError("Character data directory must be an absolute path")
    path = path.resolve()
    roots = [Path(__file__).resolve().parents[1], *program_roots]
    if any(path.is_relative_to(root.resolve()) for root in roots):
        raise ValueError("Character data must be outside source and installation directories")
    if any((parent / ".git").exists() for parent in (path, *path.parents)):
        raise ValueError("Character data must not be inside a Git repository")
    return path


def runtime_data_dir() -> Path:
    """Resolve the configured local persistence directory through the path policy.

    按路径策略解析配置的本地持久化目录。
    """

    configured = os.environ.get("CHARACTER_DATA_DIR")
    return validate_data_path(Path(configured) if configured else default_base() / "characters")
