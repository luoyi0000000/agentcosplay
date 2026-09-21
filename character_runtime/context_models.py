"""Portable contracts for bounded Host context and deterministic compilation."""

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
]


def canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class ContextFragment(Model):
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
        object.__setattr__(self, "budget_cost", len(canonical(self.payload)))
        if self.domain == "stable_character" and self.stability not in ("STATIC", "SEMI_STABLE"):
            raise ValueError("Dynamic state cannot enter the stable character slot")
        return self


class ContextBudget(Model):
    """Character caps are authoritative; token counts are diagnostic estimates only."""

    stable_character: int = Field(default=16000, ge=0, le=65536)
    relationship: int = Field(default=1800, ge=0, le=65536)
    state: int = Field(default=2200, ge=0, le=65536)
    memory: int = Field(default=7200, ge=0, le=65536)
    goals: int = Field(default=2200, ge=0, le=65536)
    open_loops: int = Field(default=2200, ge=0, le=65536)
    life: int = Field(default=2200, ge=0, le=65536)
    perception: int = Field(default=1600, ge=0, le=65536)
    external_context: int = Field(default=2400, ge=0, le=65536)
    total_chars: int = Field(default=36000, ge=0, le=131072)


class CompiledContext(Model):
    character_id: Identifier
    character_version: int = Field(ge=1)
    growth_version: Identifier
    compiler_version: Identifier
    content: str = Field(min_length=1, max_length=1000000)
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: AwareDatetime = Field(default_factory=now)

    @model_validator(mode="after")
    def intact(self) -> Self:
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
