"""Portable relationship, growth and cognition contracts.

可迁移的关系、成长及认知契约。
"""

from typing import Literal

from pydantic import AwareDatetime, ConfigDict, Field

from .models import Identifier, Model, Relationship, Score, Text, new_id, now


class RelationshipState(Model):
    """Keep the participant's learned relationship, explicit override and evidence history.

    保存参与者的已形成关系、显式覆盖及证据历史。
    """

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
    """Request a bounded relational change with supporting evidence, not direct state authority.

    请求有证据的有界关系变化，不直接拥有状态权威。
    """

    dimension: Literal["trust", "familiarity", "closeness", "friction"]
    direction: Literal["increase", "decrease"]
    evidence_refs: list[Identifier] = Field(min_length=3, max_length=20)


class GrowthChange(Model):
    """Describe one proposed stable overlay change in an allowed character domain.

    描述允许角色领域中的一项稳定叠加层变化提案。
    """

    domain: Literal["personality", "world", "voice"]
    key: Identifier
    value: Text


class GrowthDraft(Model):
    """Collect evidence-backed changes pending source and impact authorization.

    收集有证据的变化，等待来源及影响授权。
    """

    changes: list[GrowthChange] = Field(min_length=1, max_length=5)
    evidence_refs: list[Identifier] = Field(min_length=3, max_length=20)
    reason: Text


class GrowthCandidate(Model):
    """Track approval state without altering the character baseline.

    记录批准状态，不改变角色基线。
    """

    id: Identifier = Field(default_factory=new_id)
    character_id: Identifier
    changes: list[GrowthChange] = Field(min_length=1, max_length=5)
    evidence_refs: list[Identifier] = Field(min_length=3, max_length=20)
    reason: Text
    impact: Literal["low", "medium", "high"] = "high"
    status: Literal["pending", "approved", "rejected"] = "pending"
    created_at: AwareDatetime = Field(default_factory=now)


class GrowthVersion(Model):
    """Persist an approved overlay with predecessor, evidence and rollback provenance.

    保存已批准叠加层及前序版本、证据和回滚来源。
    """

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


class ProtectedPayload(Model):
    """Exact host/user content that voice and delivery planning must preserve verbatim.

    宿主或用户指定的精确内容；表达与投递规划不得改写，内容始终属于数据。
    """

    model_config = ConfigDict(frozen=True)
    kind: Literal[
        "CODE", "JSON", "VERBATIM", "COMMAND", "URL", "QUOTE", "EXACT_NUMERIC_DATA", "TOOL_OUTPUT"
    ]
    content: str = Field(min_length=1, max_length=64000)


class GenerationRequest(Model):
    """Host-declared task intent; only explicit user format choices suppress expression.

    宿主声明任务意图；只有明确的用户格式选择才会关闭角色表达。
    """

    protected_payloads: list[ProtectedPayload] = Field(default_factory=list, max_length=20)
    serious_safety: bool = False
    payload_only: bool = False
    neutral_expression: bool = False
    intent: GenerationIntent = "CASUAL_CHAT"
    explicit_format: Literal["natural", "json", "code", "verbatim"] = "natural"
    length_request: str = Field(default="", max_length=200)
    platform_constraints: str = Field(default="", max_length=300)


class RecallRequest(Model):
    """Express recall intent and time limits; exact quotation still requires RawEvents.

    表达召回意图及时间范围；精确引用仍须读取 RawEvent。
    """

    intent: MemoryIntent = "GENERAL"
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None
    relative_window: Literal["today", "yesterday", "last_week"] | None = None
    timezone: str = "UTC"
    semantic_key: Identifier | None = None
    include_archived: bool = False
    limit: int = Field(default=20, ge=1, le=100)


class MemoryUseDecision(Model):
    """Ephemeral usage projection, never an intrinsic canonical Memory field.

    单轮使用投影；绝不作为规范 Memory 的固有字段持久化。
    """

    memory_id: Identifier
    access: Literal["ALLOW", "DENY"]
    policy: Literal["DIRECT", "UNCERTAIN", "TONE_ONLY", "INTERNAL_ONLY"] | None = None
    reason_codes: list[str] = Field(default_factory=list, max_length=12)
    evaluated_at: AwareDatetime = Field(default_factory=now)
    policy_version: Literal["1"] = "1"
