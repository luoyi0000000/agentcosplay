"""Portable contracts; no platform, transport, or storage dependencies."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, Self
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1, max_length=4000)]
Identifier = Annotated[str, Field(min_length=1, max_length=200)]
Score = Annotated[float, Field(ge=0, le=1)]
Mode = Literal["canon", "au", "inspired"]
TaskMode = Literal["full_roleplay", "soft_roleplay", "task_neutral"]
Mutability = Literal["low", "medium", "high"]
Source = Literal["user_explicit", "user_material", "official", "wiki", "model", "inferred"]
MemoryKind = Literal[
    "session", "short_term", "character_long_term", "relationship", "shared_roleplay", "real_user"
]
Stage = Literal["stranger", "acquaintance", "familiar", "close"]
Level = Literal["low", "medium", "high"]


def now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid4())


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, allow_inf_nan=False)


class Fact(Model):
    value: Text
    source_type: Source = "inferred"
    reference: str = Field(default="", max_length=2000)
    confidence: Score = 0.5
    canon_status: Literal["canon", "user_defined", "unverified", "inferred"] = "inferred"

    @model_validator(mode="after")
    def source_integrity(self) -> Self:
        if self.source_type in ("official", "wiki", "user_material") and not self.reference.strip():
            raise ValueError("A document reference is required for sourced facts")
        if self.canon_status == "canon" and self.source_type not in ("official", "wiki"):
            raise ValueError("Only sourced official/wiki facts may claim canon")
        return self


class GrowthPolicy(Model):
    personality_mutability: Mutability = "low"
    relationship_mutability: Mutability = "medium"
    world_state_mutability: Mutability = "low"


class CharacterDefinition(Model):
    schema_version: Literal[1] = 1
    id: Identifier = Field(default_factory=new_id)
    name: Annotated[str, Field(min_length=1, max_length=100)]
    origin: Literal["original", "ip"] = "original"
    mode: Mode = "au"
    facts: dict[Identifier, Fact] = Field(default_factory=dict, max_length=100)
    default_task_mode: TaskMode = "soft_roleplay"
    growth: GrowthPolicy = Field(default_factory=GrowthPolicy)
    revision: int = Field(default=1, ge=1)


class Relationship(Model):
    stage: Stage = "stranger"
    trust: Level = "low"
    familiarity: Level = "low"
    preferred_address: str = Field(default="", max_length=100)
    interaction_style: str = Field(default="", max_length=500)
    boundaries: list[Text] = Field(default_factory=list, max_length=20)


class Evolution(Model):
    axis: Literal["personality", "world"]
    key: Identifier
    value: Text
    portable_summary: Text | None = None
    evidence_ids: list[Identifier] = Field(default_factory=list, max_length=10)
    at_turn: int = Field(ge=1)


class CharacterState(Model):
    character_id: Identifier
    relationship: Relationship = Field(default_factory=Relationship)
    evolution: list[Evolution] = Field(default_factory=list, max_length=100)
    # History stores references and semantic transitions, never transcript bodies.
    relationship_history: list[dict[str, str | int]] = Field(default_factory=list, max_length=100)
    known_characters: list[Identifier] = Field(default_factory=list, max_length=100)
    shared_world_id: Identifier | None = None
    turn_count: int = Field(default=0, ge=0)
    last_growth_turn: dict[str, int] = Field(default_factory=dict)
    revision: int = Field(default=1, ge=1)


class Session(Model):
    id: Identifier
    character_id: Identifier | None = None
    project: Identifier | None = None
    ooc: bool = False
    mode_override: TaskMode | None = None
    task_mode: TaskMode | None = None


class Candidate(Model):
    content: Text
    kind: MemoryKind = "character_long_term"
    importance: Score = 0.5
    confidence: Score = 0.8
    source: str = Field(default="conversation", max_length=2000)
    ttl_seconds: int | None = Field(default=None, ge=1, le=31536000)


class Memory(Model):
    id: Identifier = Field(default_factory=new_id)
    owner: Identifier
    character_id: Identifier
    kind: MemoryKind = "character_long_term"
    scope: Literal["private", "shared"] = "private"
    session_id: Identifier | None = None
    turn_id: str | None = Field(default=None, min_length=1, max_length=305)
    content: str = Field(max_length=4000)
    importance: Score = 0.5
    confidence: Score = 0.8
    source: str = Field(default="conversation", max_length=2000)
    created_at: AwareDatetime = Field(default_factory=now)
    last_access: AwareDatetime | None = None
    expires_at: AwareDatetime | None = None
    status: Literal["active", "expired", "forgotten"] = "active"
    shared_with: list[Identifier] = Field(default_factory=list, max_length=100)
    promoted_from: Identifier | None = None
    confirmation: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def valid_scope(self) -> Self:
        if self.kind == "session" and self.session_id is None:
            raise ValueError("Session memory requires a session ID")
        if self.status != "forgotten" and not self.content.strip():
            raise ValueError("Memory content cannot be blank")
        if self.status != "forgotten" and self.kind in ("session", "short_term"):
            maximum = timedelta(days=1 if self.kind == "session" else 30)
            if self.expires_at is None or self.expires_at > now() + maximum:
                raise ValueError("Temporary memory requires a bounded expiration")
        if self.scope == "private" and self.shared_with:
            raise ValueError("Private memory cannot have sharing grants")
        if (
            self.kind == "real_user"
            and self.status != "forgotten"
            and not self.confirmation.strip()
        ):
            raise ValueError("Real memory requires explicit user confirmation")
        return self


class GrowthProposal(Model):
    stage: Stage | None = None
    trust: Level | None = None
    familiarity: Level | None = None
    personality: dict[Identifier, Text] = Field(default_factory=dict, max_length=3)
    world: dict[Identifier, Text] = Field(default_factory=dict, max_length=3)
    evidence_ids: list[Identifier] = Field(default_factory=list, max_length=10)
    personality_summaries: dict[Identifier, Text] = Field(default_factory=dict, max_length=3)
    world_summaries: dict[Identifier, Text] = Field(default_factory=dict, max_length=3)
    reason: Text


class Package(Model):
    schema_version: Literal[1] = 1
    definition: CharacterDefinition
    state: CharacterState | None = None
    memories: list[Memory] = Field(default_factory=list, max_length=10000)
    includes_memories: bool = False

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.memories and not self.includes_memories:
            raise ValueError("Package contains memories without opt-in flag")
        if self.state and self.state.character_id != self.definition.id:
            raise ValueError("State belongs to a different character")
        if any(
            m.character_id != self.definition.id or m.kind == "real_user" for m in self.memories
        ):
            raise ValueError("Character packages cannot contain foreign or real-user memories")
        return self
