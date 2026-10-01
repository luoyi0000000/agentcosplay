"""Portable P0 evidence and proposal contracts; records never confer permissions.

可迁移 P0 证据与提案契约；记录本身不能授予权限。
"""

from typing import Any, Literal

from pydantic import (
    AwareDatetime,
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
)

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
    """Carry source identity and timestamp basis; observed time is not fabricated source time.

    携带源身份及时间依据；观察时间不能冒充源时间。
    """

    source_event_id: Identifier
    source_id: Identifier
    source_kind: SourceKind
    content: str = Field(min_length=1, max_length=64000)
    timestamp: AwareDatetime
    timestamp_basis: Literal["source", "observed"] | None = None
    host: str = Field(default="", max_length=100)
    platform: str = Field(default="", max_length=100)
    conversation_id: str = Field(default="", max_length=200)
    actor_id: str = Field(default="", max_length=200)
    source_ref: str = Field(default="", max_length=1000)
    sensitivity: Literal["public", "private", "sensitive"] = "private"

    @model_serializer(mode="wrap")
    def serialize_time_basis(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Preserve legacy receipt hashes when no explicit timestamp basis was supplied.

        未声明时间来源的旧请求保持原序列化形状，避免破坏幂等收据摘要。
        """
        data: dict[str, Any] = handler(self)
        if data.get("timestamp_basis") is None:
            data.pop("timestamp_basis", None)
        return data


class RawEvent(EventInput):
    """Keep source evidence separate from summaries, narratives and generation drafts.

    保存摄入的源证据，与摘要、叙事及生成草稿分离。
    """

    visible_kind: Literal["SEND_TEXT", "REPLY", "REACTION", "STICKER", "FOLLOW_UP"] | None = None
    logical_response_id: Identifier | None = None
    segment_index: int | None = Field(default=None, ge=0, le=20)
    id: Identifier = Field(default_factory=new_id)
    owner_id: Identifier
    character_id: Identifier
    session_id: Identifier
    received_at: AwareDatetime = Field(default_factory=now)
    validity: Literal["active", "forgotten"] = "active"
    legacy_unverified: bool = False
    content: str = Field(max_length=64000)


class EventBatch(Model):
    """Group bounded source inputs under one idempotent ingestion operation.

    将有界源输入归入一个幂等摄入操作。
    """

    operation_id: Identifier
    session_id: Identifier
    events: list[EventInput] = Field(min_length=1, max_length=50)
    mode: Literal["realtime", "backfill", "import"] = "realtime"
    sensitive_confirmation: str = Field(default="", max_length=1000)
    checkpoint_revision: int | None = Field(default=None, ge=0)


class MemoryProposal(Candidate):
    """Propose a summary backed by RawEvent references; persistence still requires validation.

    提出附带 RawEvent 引用的摘要；持久化仍须验证。
    """

    semantic_key: Identifier | None = None
    explicit_remember: bool = False
    evidence_refs: list[Identifier] = Field(min_length=1, max_length=20)
    domain: Literal["character", "project"] = "character"
    sensitive_confirmation: str = Field(default="", max_length=1000)

    @field_validator("semantic_key")
    @classmethod
    def normalize_key(cls, value: str | None) -> str | None:
        """Use the same canonical semantic-key rules as fact proposals.

        复用事实提案的规范语义键规则。
        """

        return FactProposal.normalized_key(value) if value else None


class FactProposal(Model):
    """Request creation or supersession using evidence and explicit target authorization.

    使用证据与显式目标授权请求创建或替代事实。
    """

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
        """Normalize namespace segments and reject ambiguous semantic keys.

        规范命名空间片段，拒绝含糊语义键。
        """

        import re
        import unicodedata

        value = unicodedata.normalize("NFKC", value).casefold().strip()
        if not re.fullmatch(r"[a-z0-9_]+(?::[a-z0-9_-]+){1,5}", value):
            raise ValueError("semantic_key requires normalized namespace:slot segments")
        return value


class FactRecord(Model):
    """Record validity and provenance for a scoped fact, independent of retrieval score.

    记录作用域事实的有效性及来源，不依赖检索分数。
    """

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
    """Derive a narrative from evidence; the narrative cannot become evidence itself.

    从证据派生叙事；叙事不能反向成为证据。
    """

    content: Text
    evidence_refs: list[Identifier] = Field(min_length=1, max_length=20)


class ParticipantAdaptation(Model):
    """Low-impact enumerated preferences, never a Character Core mutation.

    枚举化的低影响互动偏好；只影响当前 Participant，不修改 Character Core。
    """

    dimension: Literal["verbosity_default", "directness", "emoji_use", "technical_detail"]
    value: str = Field(min_length=1, max_length=30)
    evidence_refs: list[Identifier] = Field(min_length=1, max_length=20)


class TurnProposal(Model):
    """Bundle candidate effects for one atomic evidence-gated commit.

    组合候选变化，交给一次有证据门的原子提交。
    """

    participant_adaptations: list[ParticipantAdaptation] = Field(default_factory=list, max_length=4)
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
    """Require an operation and explicit target grant for canonical memory edits.

    规范记忆编辑须携带操作及显式目标授权。
    """

    operation_id: Identifier
    action: Literal["MODIFY", "FORGET", "ARCHIVE", "PROMOTE"]
    session_id: Identifier
    memory_id: Identifier
    allowlist_id: Identifier
    content: Text | None = None
    evidence_refs: list[Identifier] = Field(default_factory=list, max_length=20)
    confirmation: str = Field(default="", max_length=1000)
