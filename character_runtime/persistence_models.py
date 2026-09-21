"""Portable relationship, growth and cognition contracts."""

from typing import Literal

from pydantic import AwareDatetime, Field

from .models import Identifier, Model, Relationship, Score, Text, new_id, now


class RelationshipState(Model):
    character_id: Identifier
    anchor: Relationship = Field(default_factory=Relationship)
    learned: Relationship = Field(default_factory=Relationship)
    override: Relationship | None = None
    closeness: Score = 0
    friction: Score = 0
    last_interaction: AwareDatetime | None = None
    last_meaningful_interaction: AwareDatetime | None = None
    last_transition: AwareDatetime | None = None
    evidence_refs: list[Identifier] = Field(default_factory=list, max_length=100)
    revision: int = 1


class RelationshipEffect(Model):
    dimension: Literal["trust", "familiarity", "closeness", "friction"]
    direction: Literal["increase", "decrease"]
    evidence_refs: list[Identifier] = Field(min_length=3, max_length=20)


class GrowthChange(Model):
    domain: Literal["personality", "world", "voice"]
    key: Identifier
    value: Text


class GrowthDraft(Model):
    changes: list[GrowthChange] = Field(min_length=1, max_length=5)
    evidence_refs: list[Identifier] = Field(min_length=3, max_length=20)
    reason: Text


class GrowthCandidate(Model):
    id: Identifier = Field(default_factory=new_id)
    character_id: Identifier
    changes: list[GrowthChange] = Field(min_length=1, max_length=5)
    evidence_refs: list[Identifier] = Field(min_length=3, max_length=20)
    reason: Text
    impact: Literal["low", "medium", "high"] = "high"
    status: Literal["pending", "approved", "rejected"] = "pending"
    created_at: AwareDatetime = Field(default_factory=now)


class GrowthVersion(Model):
    id: Identifier = Field(default_factory=new_id)
    character_id: Identifier
    previous_version: Identifier | None = None
    overlay: dict[str, dict[str, str]] = Field(default_factory=dict)
    diff: list[GrowthChange] = Field(default_factory=list)
    evidence_refs: list[Identifier] = Field(default_factory=list)
    impact: Literal["low", "medium", "high"] = "high"
    reason: Text
    approved_by: Literal["USER_EXPLICIT", "EVIDENCE_GATE"]
    created_at: AwareDatetime = Field(default_factory=now)


GenerationIntent = Literal[
    "CASUAL_CHAT",
    "SOCIAL",
    "EMOTIONAL_SUPPORT",
    "FACTUAL_QA",
    "EXPLANATION",
    "ANALYSIS",
    "CODING",
    "WRITING",
    "TRANSLATION",
    "TOOL_TASK",
    "CREATIVE",
]
MemoryIntent = Literal[
    "CURRENT_STATE",
    "RECENT",
    "TIME_WINDOW",
    "AUTOBIOGRAPHICAL",
    "SHARED_EXPERIENCE",
    "RELATIONSHIP",
    "USER_FACT",
    "USER_PREFERENCE",
    "OPEN_LOOP",
    "GOAL",
    "SIMULATED_LIFE",
    "EXACT_RECALL",
    "EXACT_QUOTE",
    "GENERAL",
]


class GenerationRequest(Model):
    intent: GenerationIntent = "CASUAL_CHAT"
    explicit_format: Literal["natural", "json", "code", "verbatim"] = "natural"
    length_request: str = Field(default="", max_length=200)
    platform_constraints: str = Field(default="", max_length=300)


class RecallRequest(Model):
    intent: MemoryIntent = "GENERAL"
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None
    relative_window: Literal["today", "yesterday", "last_week"] | None = None
    timezone: str = "UTC"
    semantic_key: Identifier | None = None
    include_archived: bool = False
    limit: int = Field(default=20, ge=1, le=100)
