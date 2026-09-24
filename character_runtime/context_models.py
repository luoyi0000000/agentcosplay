"""Portable contracts for bounded Host context and deterministic compilation.

有界宿主上下文与确定性编译的可迁移契约。
"""

import hashlib
import json
from typing import Any, Literal, Self

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from .models import Identifier, Model, now

ContextSlot = Literal[
    "stable_character",
    "relationship",
    "state",
    "memory",
    "goals",
    "open_loops",
    "life",
    "perception",
    "external_context",
    "recent_turn_window",
    "ambient_window",
]


def canonical(value: Any) -> str:
    """Serialize deterministic JSON and reject non-finite numbers.

    序列化确定性 JSON，拒绝非有限数值。
    """

    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def fingerprint(value: str) -> str:
    """Hash exact UTF-8 prefix bytes for cache identity, not authorization.

    对前缀 UTF-8 字节求摘要，用于缓存标识，不用于授权。
    """

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class ContextFragment(Model):
    """Carry authority, sensitivity and budget metadata for one whole context fragment.

    携带一个完整上下文片段的权威、敏感性与预算元数据。
    """

    domain: ContextSlot
    authority: Literal[
        "USER_EXPLICIT",
        "USER_MANUAL",
        "ADMIN_CONFIG",
        "TOOL_VERIFIED",
        "HOST_OBSERVED",
        "MODEL_DERIVED",
        "INFERRED",
        "SIMULATED",
    ]
    stability: Literal["STATIC", "SEMI_STABLE", "DYNAMIC", "EPHEMERAL"]
    priority: int = Field(default=50, ge=0, le=100)
    payload: JsonValue
    budget_cost: int = Field(default=0, ge=0)
    sensitivity: Literal["public", "private"] = "private"
    source_version: Identifier

    @model_validator(mode="after")
    def measured(self) -> Self:
        # Costs are recomputed from validated JSON, never trusted from a producer.
        """Recompute cost from validated payload and exclude dynamic stable-prefix content.

        从已验证载荷重算成本，禁止动态内容进入稳定前缀槽。
        """

        object.__setattr__(self, "budget_cost", len(canonical(self.payload)))
        if self.domain == "stable_character" and self.stability not in ("STATIC", "SEMI_STABLE"):
            raise ValueError("Dynamic state cannot enter the stable character slot")
        return self


class ContextBudget(Model):
    """Character caps are authoritative; token counts are diagnostic estimates only.

    字符预算是硬限制；Token 数仅作诊断估计。
    """

    stable_character: int = Field(default=16000, ge=0, le=65536)
    relationship: int = Field(default=1800, ge=0, le=65536)
    state: int = Field(default=4000, ge=0, le=65536)
    memory: int = Field(default=7200, ge=0, le=65536)
    goals: int = Field(default=2200, ge=0, le=65536)
    open_loops: int = Field(default=2200, ge=0, le=65536)
    life: int = Field(default=2200, ge=0, le=65536)
    perception: int = Field(default=1600, ge=0, le=65536)
    external_context: int = Field(default=2400, ge=0, le=65536)
    recent_turn_window: int = Field(default=4800, ge=0, le=65536)
    ambient_window: int = Field(default=2400, ge=0, le=65536)
    total_chars: int = Field(default=36000, ge=0, le=131072)


class CompiledContext(Model):
    """Bind a stable prefix to its character, versions and content digest.

    将稳定前缀绑定到角色、版本及正文摘要。
    """

    character_id: Identifier
    character_version: int = Field(ge=1)
    growth_version: Identifier
    compiler_version: Identifier
    content: str = Field(min_length=1, max_length=1000000)
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: AwareDatetime = Field(default_factory=now)

    @model_validator(mode="after")
    def intact(self) -> Self:
        """Reject corrupt or noncanonical prefixes before they can replace a valid compile.

        拒绝损坏或非规范前缀，避免替换有效编译结果。
        """

        if fingerprint(self.content) != self.fingerprint:
            raise ValueError("Compiled character fingerprint mismatch")
        payload = json.loads(self.content)
        if not isinstance(payload, dict) or not isinstance(payload.get("character"), dict):
            raise ValueError("Compiled character must contain a character object")
        if canonical(payload) != self.content or (
            payload["character"].get("id") != self.character_id
            or payload.get("character_version") != self.character_version
            or payload.get("growth_version") != self.growth_version
            or payload.get("compiler_version") != self.compiler_version
            or "created_at" in payload
        ):
            raise ValueError("Compiled character metadata mismatch")
        return self
