"""Portable P0 evidence and proposal contracts; records never confer permissions."""

from typing import Literal

from pydantic import AwareDatetime, Field, field_validator

from .companion_models import CompanionUpdate
from .lifelike_models import AffectEffect
from .models import Candidate, Identifier, Model, Score, Text, new_id, now
from .persistence_models import GrowthDraft, RelationshipEffect

SourceKind = Literal[
    "USER_DIRECT",
    "ASSISTANT_VISIBLE",
    "QUOTED",
    "FORWARDED",
    "MEDIA_DERIVED",
    "TOOL_RESULT",
    "WEB_CONTENT",
    "SIMULATED",
    "PLANNED",
]
Authority = Literal[
    "USER_EXPLICIT",
    "USER_MANUAL",
    "ADMIN_CONFIG",
    "TOOL_VERIFIED",
    "HOST_OBSERVED",
    "MODEL_DERIVED",
    "INFERRED",
    "SIMULATED",
]


class EventInput(Model):
    source_event_id: Identifier
    source_id: Identifier
    source_kind: SourceKind
    content: Text
    timestamp: AwareDatetime
    host: str = Field(default="", max_length=100)
    platform: str = Field(default="", max_length=100)
    conversation_id: str = Field(default="", max_length=200)
    actor_id: str = Field(default="", max_length=200)
    source_ref: str = Field(default="", max_length=1000)
    sensitivity: Literal["public", "private", "sensitive"] = "private"


class RawEvent(EventInput):
    id: Identifier = Field(default_factory=new_id)
    owner_id: Identifier
    character_id: Identifier
    session_id: Identifier
    received_at: AwareDatetime = Field(default_factory=now)
    validity: Literal["active", "forgotten"] = "active"
    legacy_unverified: bool = False
    content: str = Field(max_length=4000)


class EventBatch(Model):
    operation_id: Identifier
    session_id: Identifier
    events: list[EventInput] = Field(min_length=1, max_length=50)
    mode: Literal["realtime", "backfill", "import"] = "realtime"
    sensitive_confirmation: str = Field(default="", max_length=1000)
    checkpoint_revision: int | None = Field(default=None, ge=0)


class MemoryProposal(Candidate):
    semantic_key: Identifier | None = None
    explicit_remember: bool = False
    evidence_refs: list[Identifier] = Field(min_length=1, max_length=20)
    domain: Literal["character", "project"] = "character"
    sensitive_confirmation: str = Field(default="", max_length=1000)

    @field_validator("semantic_key")
    @classmethod
    def normalize_key(cls, value: str | None) -> str | None:
        return FactProposal.normalized_key(value) if value else None


class FactProposal(Model):
    semantic_key: Identifier
    subject: Literal["owner", "character", "project"] = "character"
    value: Text
    confidence: Score = 0.8
    evidence_refs: list[Identifier] = Field(min_length=1, max_length=20)
    operation: Literal["CREATE", "SUPERSEDE"] = "CREATE"
    target_id: Identifier | None = None
    allowlist_id: Identifier | None = None
    explicit_confirmation: str = Field(default="", max_length=1000)

    @field_validator("semantic_key")
    @classmethod
    def normalized_key(cls, value: str) -> str:
        import re
        import unicodedata

        value = unicodedata.normalize("NFKC", value).casefold().strip()
        if not re.fullmatch(r"[a-z0-9_]+(?::[a-z0-9_-]+){1,5}", value):
            raise ValueError("semantic_key requires normalized namespace:slot segments")
        return value


class FactRecord(Model):
    id: Identifier = Field(default_factory=new_id)
    owner_id: Identifier
    character_id: Identifier
    semantic_key: Identifier
    subject: Literal["owner", "character", "project"]
    value: Text
    evidence_refs: list[Identifier] = Field(min_length=1, max_length=20)
    confidence: Score
    authority: Authority
    sensitivity: Literal["public", "private", "sensitive"] = "private"
    validity: Literal["active", "archived", "superseded", "expired", "forgotten"] = "active"
    legacy_unverified: bool = False
    valid_from: AwareDatetime
    valid_to: AwareDatetime | None = None
    superseded_by: Identifier | None = None
    created_at: AwareDatetime = Field(default_factory=now)
    updated_at: AwareDatetime = Field(default_factory=now)


class NarrativeProposal(Model):
    content: Text
    evidence_refs: list[Identifier] = Field(min_length=1, max_length=20)


class TurnProposal(Model):
    affect_effects: list[AffectEffect] = Field(default_factory=list, max_length=1)
    companion_update: CompanionUpdate | None = None
    companion_allowlist_id: Identifier | None = None
    operation_id: Identifier
    relationship_effects: list[RelationshipEffect] = Field(default_factory=list, max_length=3)
    growth_proposals: list[GrowthDraft] = Field(default_factory=list, max_length=3)
    memory_proposals: list[MemoryProposal] = Field(default_factory=list, max_length=20)
    fact_proposals: list[FactProposal] = Field(default_factory=list, max_length=20)
    narrative_proposals: list[NarrativeProposal] = Field(default_factory=list, max_length=5)


class MemoryMutation(Model):
    operation_id: Identifier
    action: Literal["MODIFY", "FORGET", "ARCHIVE", "PROMOTE"]
    session_id: Identifier
    memory_id: Identifier
    allowlist_id: Identifier
    content: Text | None = None
    evidence_refs: list[Identifier] = Field(default_factory=list, max_length=20)
    confirmation: str = Field(default="", max_length=1000)
