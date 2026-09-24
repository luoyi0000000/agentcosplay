"""Hermes native plugin entry; Core remains platform neutral.

Hermes 原生插件入口；Core 继续保持平台中立。
"""

from pathlib import Path
from typing import Any

from .character_runtime.hermes_adapter import register as register_adapter


def register(ctx: Any) -> None:
    """Use official hooks and the canonical Skill. / 使用官方钩子与唯一 Skill。"""
    register_adapter(ctx, Path(__file__).resolve().parent)
