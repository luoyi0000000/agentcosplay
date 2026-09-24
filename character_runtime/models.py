"""Portable contracts; no platform, transport, or storage dependencies.

可迁移数据契约，不依赖平台、传输或存储。
"""

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
    """Return an aware UTC timestamp for default record creation.

    为默认记录创建时间提供带时区的 UTC 时刻。
    """

    return datetime.now(UTC)


def new_id() -> str:
    """Create an opaque record identifier; it conveys no permission.

    生成不透明记录 ID；ID 本身不授予权限。
    """

    return str(uuid4())


class Model(BaseModel):
    """Reject unknown fields by default and validate assignments at contract boundaries.

    默认拒绝未知字段，并在契约边界验证赋值。
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True, allow_inf_nan=False)


class Fact(Model):
    """Describe a sourced character-definition claim, separate from runtime FactRecord.

    描述有来源的角色定义声明，与 Runtime FactRecord 分离。
    """

    value: Text
    source_type: Source = "inferred"
    reference: str = Field(default="", max_length=2000)
    confidence: Score = 0.5
    canon_status: Literal["canon", "user_defined", "unverified", "inferred"] = "inferred"

    @model_validator(mode="after")
    def source_integrity(self) -> Self:
        """Require references for sourced claims and restrict claims of canon.

        要求有来源声明携带引用，并限制正史声明资格。
        """

        if self.source_type in ("official", "wiki", "user_material") and not self.reference.strip():
            raise ValueError("A document reference is required for sourced facts")
        if self.canon_status == "canon" and self.source_type not in ("official", "wiki"):
            raise ValueError("Only sourced official/wiki facts may claim canon")
        return self


class GrowthPolicy(Model):
    """Bound permitted changes by character domain rather than grant write authority.

    按角色领域限制允许变化，不授予写权限。
    """

    personality_mutability: Mutability = "low"
    relationship_mutability: Mutability = "medium"
    world_state_mutability: Mutability = "low"


class DialogueExample(Model):
    """A curated meaning-to-expression example; assistant history is never baseline authority.

    精选的语义到人物表达示范；助手历史输出绝不自动成为基线权威。
    """

    meaning: Annotated[str, Field(min_length=1, max_length=500)]
    character: Annotated[str, Field(min_length=1, max_length=1000)]


class CatchphraseRule(Model):
    """Optional suitability and repetition limits, never mandatory text insertion.

    可选适用场景与重复限制，绝不代表必须插入某个口头禅。
    """

    phrase: Annotated[str, Field(min_length=1, max_length=80)]
    usage: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        default_factory=list, max_length=6
    )
    intensity: Literal["light", "normal", "emphatic"] = "light"
    cooldown_seconds: int = Field(default=120, ge=0, le=86400)
    avoid_contexts: list[Annotated[str, Field(min_length=1, max_length=40)]] = Field(
        default_factory=lambda: [
            "CODE",
            "JSON",
            "VERBATIM",
            "COMMAND",
            "FORMAL_QUOTE",
            "SERIOUS_SAFETY",
        ],
        max_length=12,
    )


class VoiceProfile(Model):
    """One portable voice model for conversation and professional tasks alike.

    闲聊与专业任务共用同一可迁移表达模型，不建立第二套任务人格。
    """

    preferred_vocabulary: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        default_factory=list, max_length=8
    )
    avoided_vocabulary: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        default_factory=list, max_length=8
    )
    sentence_rhythm: str = Field(default="natural varied rhythm", max_length=300)
    explanation_style: str = Field(
        default="character-appropriate, clear causal reasoning", max_length=300
    )
    analogy_style: str = Field(default="only when useful", max_length=300)
    evaluation_style: str = Field(default="direct with factual conditions intact", max_length=300)
    disagreement_style: str = Field(default="state the reason respectfully", max_length=300)
    question_style: str = Field(default="ask only useful follow-up questions", max_length=300)
    verbosity_default: Literal["brief", "balanced", "detailed"] = "balanced"
    sentence_length: Literal["short", "varied", "long"] = "varied"
    directness: Literal["gentle", "direct", "blunt"] = "direct"
    addressing_style: str = Field(default="natural", max_length=300)
    self_reference_style: str = Field(default="natural", max_length=300)
    humor_style: str = Field(default="character-appropriate", max_length=300)
    emotional_expressiveness: Literal["reserved", "balanced", "expressive"] = "balanced"
    catchphrase_rules: list[CatchphraseRule] = Field(default_factory=list, max_length=8)
    catchphrases: list[Text] = Field(default_factory=list, max_length=8)
    stage_direction_policy: Literal["none", "occasional", "expressive"] = "occasional"
    repetition_tolerance: Literal["low", "normal"] = "low"
    preferred_patterns: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        default_factory=list, max_length=8
    )
    avoided_patterns: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        default_factory=list, max_length=8
    )
    dialogue_examples: list[Text | DialogueExample] = Field(default_factory=list, max_length=10)


class EmbodimentProfile(Model):
    """Opt into simulated bodily axes; human physiology is never assumed by default.

    显式开启模拟身体维度，不默认假定人类生理需求。
    """

    enabled: bool = False
    sleep_enabled: bool = False
    hunger_enabled: bool = False
    physical_discomfort_enabled: bool = False
    weather_sensitivity: Score = 0
    social_capacity_enabled: bool = False
    custom_axes: dict[Identifier, Score] = Field(default_factory=dict, max_length=10)


class CharacterDefinition(Model):
    """Portable stable profile with explicit source facts and revision, not live session state.

    包含显式来源事实及版本的稳定可迁移档案，不存放实时会话状态。
    """

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
    """Bound relationship dimensions and explicit interaction boundaries.

    约束关系维度及显式互动边界。
    """

    stage: Stage = "stranger"
    trust: Level = "low"
    familiarity: Level = "low"
    preferred_address: str = Field(default="", max_length=100)
    interaction_style: str = Field(default="", max_length=500)
    boundaries: list[Text] = Field(default_factory=list, max_length=20)


class Evolution(Model):
    """Preserve legacy evolution evidence references separately from approved Growth versions.

    保存旧演化的证据引用，与已批准的 Growth 版本分离。
    """

    axis: Literal["personality", "world"]
    key: Identifier
    value: Text
    portable_summary: Text | None = None
    evidence_ids: list[Identifier] = Field(default_factory=list, max_length=10)
    at_turn: int = Field(ge=1)


class CharacterState(Model):
    """Retain baseline compatibility state; domain engines own their canonical projections.

    保留基线兼容状态；各领域引擎管理对应规范投影。
    """

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
        """Ignore unsupported legacy social fields in the active model; migrations retain originals.

        当前模型忽略不支持的旧社交字段；迁移保留原始记录。
        """

        if isinstance(value, dict):
            value = {
                k: v for k, v in value.items() if k not in {"known_characters", "shared_world_id"}
            }
        return value


class Session(Model):
    """Keep one active character and temporary conversation modes; actor identity is per turn.

    保存一个激活角色及临时会话模式；发言人身份按回合确定。
    """

    id: Identifier
    character_id: Identifier | None = None
    project: Identifier | None = None
    ooc: bool = False
    mode_override: TaskMode | None = None
    task_mode: TaskMode | None = None
    identity_verified: bool = True
    identity_binding: Identifier | None = None


class Candidate(Model):
    """Bound a proposed memory summary; confidence does not establish factual authority.

    约束记忆摘要候选；置信度不建立事实权威。
    """

    content: Text
    kind: MemoryKind = "character_long_term"
    importance: Score = 0.5
    confidence: Score = 0.8
    source: str = Field(default="conversation", max_length=2000)
    ttl_seconds: int | None = Field(default=None, ge=1, le=31536000)


class MemoryScope(Model):
    """Explicit memory audience, independent of confidence and retrieval scores.

    显式记忆受众；置信度、召回分数和同群关系均不授予访问权。
    """

    kind: Literal["PARTICIPANT_CHARACTER", "ENDPOINT_CHARACTER"]
    participant_id: Identifier | None = None
    endpoint_id: Identifier | None = None

    @model_validator(mode="after")
    def audience(self) -> Self:
        """Require exactly the declared audience. / 必须且只能指定声明的受众。"""
        if self.kind == "PARTICIPANT_CHARACTER":
            if not self.participant_id or self.endpoint_id is not None:
                raise ValueError("Private memory requires only a participant")
        elif not self.endpoint_id or self.participant_id is not None:
            raise ValueError("Public endpoint memory requires only an endpoint")
        return self


class Memory(Model):
    """Store a scoped canonical summary with provenance and validity, never an exact quote.

    保存带作用域、来源及有效性的规范摘要，不冒充原话。
    """

    id: Identifier = Field(default_factory=new_id)
    owner: Identifier
    character_id: Identifier
    # Missing metadata is legacy owner-private, never shared by default.
    # 缺失元数据只代表旧 Owner 私有记录，绝不能默认为共享。
    record_scope: MemoryScope | None = None
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
        """Remove old access grants from the active model and default legacy evidence to unverified.

        从当前模型撤销旧访问授权，旧证据默认未验证。
        """

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
        """Enforce audience privacy, simulation separation and bounded temporary lifetimes.

        强制受众隐私、模拟隔离及临时记忆寿命上限。
        """

        if self.record_scope and self.record_scope.kind == "ENDPOINT_CHARACTER":
            if self.sensitivity != "public" or self.kind in ("real_user", "relationship"):
                raise ValueError("Endpoint memory must be public, not personal state")
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
    """Represent the legacy bounded growth proposal, not approval or canonical state.

    表示旧有界成长提案，不代表批准或规范状态。
    """

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
    """Read the legacy portable package with explicit opt-in for memories.

    读取旧可迁移包；携带记忆必须显式开启。
    """

    schema_version: Literal[1] = 1
    definition: CharacterDefinition
    state: CharacterState | None = None
    memories: list[Memory] = Field(default_factory=list, max_length=10000)
    includes_memories: bool = False

    @model_validator(mode="after")
    def coherent(self) -> Self:
        """Reject foreign/private records and inconsistent memory opt-in flags.

        拒绝外部或私人记录，以及不一致的记忆携带开关。
        """

        if self.memories and not self.includes_memories:
            raise ValueError("Package contains memories without opt-in flag")
        if self.state and self.state.character_id != self.definition.id:
            raise ValueError("State belongs to a different character")
        if any(
            m.character_id != self.definition.id or m.kind == "real_user" for m in self.memories
        ):
            raise ValueError("Character packages cannot contain foreign or real-user memories")
        return self
