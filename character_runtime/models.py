"""Portable contracts; no platform, transport, or storage dependencies."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, Self
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1, max_length=4000)]
Identifier = Annotated[str, Field(min_length=1, max_length=200)]
Score = Annotated[float, Field(ge=0, le=1)]
Mode = Literal["canon", "au", "inspired"]
TaskMode = Literal["full_roleplay", "soft_roleplay", "task_neutral"]
Mutability = Literal["low", "medium", "high"]
Source = Literal["user_explicit", "user_material", "official", "wiki", "model", "inferred"]
MemoryKind = Literal["session", "short_term", "character_long_term", "relationship", "real_user"]
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


class VoiceProfile(Model):
    verbosity_default: Literal["brief", "balanced", "detailed"] = "balanced"
    sentence_length: Literal["short", "varied", "long"] = "varied"
    directness: Literal["gentle", "direct", "blunt"] = "direct"
    addressing_style: str = Field(default="natural", max_length=300)
    self_reference_style: str = Field(default="natural", max_length=300)
    humor_style: str = Field(default="character-appropriate", max_length=300)
    emotional_expressiveness: Literal["reserved", "balanced", "expressive"] = "balanced"
    catchphrases: list[Text] = Field(default_factory=list, max_length=8)
    stage_direction_policy: Literal["none", "occasional", "expressive"] = "occasional"
    repetition_tolerance: Literal["low", "normal"] = "low"
    dialogue_examples: list[Text] = Field(default_factory=list, max_length=10)


class EmbodimentProfile(Model):
    enabled: bool = False
    sleep_enabled: bool = False
    hunger_enabled: bool = False
    physical_discomfort_enabled: bool = False
    weather_sensitivity: Score = 0
    social_capacity_enabled: bool = False
    custom_axes: dict[Identifier, Score] = Field(default_factory=dict, max_length=10)


class CharacterDefinition(Model):
    schema_version: Literal[1] = 1
    id: Identifier = Field(default_factory=new_id)
    name: Annotated[str, Field(min_length=1, max_length=100)]
    origin: Literal["original", "ip"] = "original"
    mode: Mode = "au"
    facts: dict[Identifier, Fact] = Field(default_factory=dict, max_length=100)
    default_task_mode: TaskMode = "soft_roleplay"
    growth: GrowthPolicy = Field(default_factory=GrowthPolicy)
    voice: VoiceProfile = Field(default_factory=VoiceProfile)
    embodiment: EmbodimentProfile = Field(default_factory=EmbodimentProfile)
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
    turn_count: int = Field(default=0, ge=0)
    last_growth_turn: dict[str, int] = Field(default_factory=dict)
    revision: int = Field(default=1, ge=1)

    @model_validator(mode="before")
    @classmethod
    def remove_legacy_social_fields(cls, value: Any) -> Any:
        if isinstance(value, dict):
            value = {
                k: v for k, v in value.items() if k not in {"known_characters", "shared_world_id"}
            }
        return value


class Session(Model):
    id: Identifier
    character_id: Identifier | None = None
    project: Identifier | None = None
    ooc: bool = False
    mode_override: TaskMode | None = None
    task_mode: TaskMode | None = None
    identity_verified: bool = True
    identity_binding: Identifier | None = None


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
    kind: MemoryKind | Literal["shared_roleplay"] = "character_long_term"
    session_id: Identifier | None = None
    turn_id: str | None = Field(default=None, min_length=1, max_length=305)
    content: str = Field(max_length=4000)
    semantic_key: Identifier | None = None
    durability: Literal["temporary", "persistent", "explicit"] = "persistent"
    activation: Score = 0
    reinforcement: int = Field(default=0, ge=0)
    last_injected_at: AwareDatetime | None = None
    useful_count: int = Field(default=0, ge=0)
    event_at: AwareDatetime | None = None
    superseded_by: Identifier | None = None
    importance: Score = 0.5
    confidence: Score = 0.8
    source: str = Field(default="conversation", max_length=2000)
    evidence_refs: list[Identifier] = Field(default_factory=list, max_length=20)
    authority: Authority = "INFERRED"
    sensitivity: Literal["public", "private", "sensitive"] = "private"
    legacy_unverified: bool = False
    created_at: AwareDatetime = Field(default_factory=now)
    last_access: AwareDatetime | None = None
    expires_at: AwareDatetime | None = None
    status: Literal["active", "archived", "expired", "forgotten"] = "active"
    occurrences: int = Field(default=1, ge=1)
    last_observed_at: AwareDatetime | None = None
    observation_turn_ids: list[str] = Field(default_factory=list, max_length=20)
    consolidated_at: AwareDatetime | None = None
    promoted_from: Identifier | None = None
    confirmation: str = Field(default="", max_length=2000)

    @model_validator(mode="before")
    @classmethod
    def legacy_memory(cls, value: Any) -> Any:
        if isinstance(value, dict):
            value = dict(value)
            # Known legacy grants are discarded, never interpreted as authorization.
            value.pop("scope", None)
            value.pop("shared_with", None)
            value.setdefault("legacy_unverified", True)
            if value.get("kind") == "shared_roleplay":
                value["legacy_unverified"] = True
        return value

    @model_validator(mode="after")
    def valid_memory(self) -> Self:
        if self.source == "simulated_life" and self.kind not in (
            "short_term",
            "character_long_term",
        ):
            raise ValueError("Simulated life is never real-user or shared-event memory")
        if self.kind == "session" and self.session_id is None:
            raise ValueError("Session memory requires a session ID")
        if self.status != "forgotten" and not self.content.strip():
            raise ValueError("Memory content cannot be blank")
        if self.status != "forgotten" and self.kind in ("session", "short_term"):
            maximum = timedelta(days=1 if self.kind == "session" else 30)
            if self.expires_at is None or self.expires_at > now() + maximum:
                raise ValueError("Temporary memory requires a bounded expiration")
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
