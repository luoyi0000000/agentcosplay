"""Versioned, bounded companion state; never a second character definition.

版本化、有界陪伴状态；不构成第二份角色定义。
"""

from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, ConfigDict, Field, JsonValue, model_validator

from .models import Candidate, Identifier, Model, Score, new_id, now
from .providers import Activity, Observation


class Settings(Model):
    """Keep explicit opt-in controls and proactive quiet/rate limits.

    保存显式启用开关，以及主动联系的安静时段和频率限制。
    """

    proactive_contact: bool = False
    schedule_awareness: bool = False
    weather_awareness: bool = False
    life_simulation: bool = False
    relationship_growth: bool = True
    timezone: str = Field(default="UTC", max_length=100)
    quiet_start: int = Field(default=22, ge=0, le=23)
    quiet_end: int = Field(default=8, ge=0, le=23)
    cooldown_seconds: int = Field(default=21600, ge=3600, le=604800)
    recent_activity_seconds: int = Field(default=3600, ge=300, le=86400)
    max_contacts_per_day: int = Field(default=2, ge=1, le=10)
    availability: Literal["unknown", "available", "busy", "unavailable"] = "unknown"

    @model_validator(mode="after")
    def valid_timezone(self) -> Self:
        """Reject unavailable timezone rules instead of silently using a different zone.

        拒绝不可用的时区规则，不静默换用其他时区。
        """

        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("Unknown timezone; install IANA timezone data or use UTC") from error
        return self


class SettingsUpdate(Model):
    """Patch only supplied owner settings, preserving unspecified values.

    只修改提供的 Owner 设置，保留未指定值。
    """

    proactive_contact: bool | None = None
    schedule_awareness: bool | None = None
    weather_awareness: bool | None = None
    life_simulation: bool | None = None
    relationship_growth: bool | None = None
    timezone: str | None = None
    quiet_start: int | None = None
    quiet_end: int | None = None
    cooldown_seconds: int | None = None
    recent_activity_seconds: int | None = None
    max_contacts_per_day: int | None = None
    availability: Literal["unknown", "available", "busy", "unavailable"] | None = None


class MoodUpdate(Model):
    """Legacy request shape, retained only to return an explicit compatibility error.

    旧请求形状仅用于明确返回兼容错误，不再参与情绪写入。
    """

    label: str = Field(min_length=1, max_length=80)
    intensity: Score
    reason: str = Field(min_length=1, max_length=500)
    evidence_ids: list[Identifier] = Field(default_factory=list, max_length=5)


class Mood(Model):
    """Legacy reader shape, never the current emotional authority.

    旧版读取结构，不再作为当前情绪权威。
    """

    label: str = Field(default="neutral", max_length=80)
    intensity: Score = 0
    reason: str = Field(default="", max_length=500)
    evidence_ids: list[Identifier] = Field(default_factory=list, max_length=5)
    updated_at: AwareDatetime = Field(default_factory=now)
    influenced_at: AwareDatetime | None = None


class Goal(Model):
    """Track configured intent and progress; a plan is not evidence of a completed event.

    记录配置意图及进度；计划不是已完成事件的证据。
    """

    id: Identifier = Field(default_factory=new_id)
    description: str = Field(min_length=1, max_length=500)
    source: Literal["user_explicit", "definition", "schedule", "growth", "simulated_life"] = (
        "user_explicit"
    )
    importance: Score = 0.5
    status: Literal["active", "paused", "completed", "cancelled"] = "active"
    created_at: AwareDatetime = Field(default_factory=now)
    deadline: AwareDatetime | None = None
    progress: Score = 0
    evidence_ids: list[Identifier] = Field(default_factory=list, max_length=5)
    activity: Activity = "reading"
    simulate: bool = False
    simulated_hours: float = Field(default=0, ge=0, le=100000)
    simulation_milestone: int = Field(default=0, ge=0, le=10000)


class GoalUpdate(Model):
    """Bound goal changes and their evidence references before applying them.

    应用前约束目标变化及证据引用。
    """

    id: Identifier
    description: str = Field(min_length=1, max_length=500)
    source: Literal["user_explicit", "definition", "schedule", "growth"] = "user_explicit"
    importance: Score = 0.5
    status: Literal["active", "paused", "completed", "cancelled"] = "active"
    deadline: AwareDatetime | None = None
    progress: Score = 0
    evidence_ids: list[Identifier] = Field(default_factory=list, max_length=5)
    activity: Activity = "reading"
    simulate: bool = False


class HabitUpdate(Model):
    """Propose a habit with evidence, never an assumed repeated real-world event.

    提出有证据的习惯，不假定现实事件已经反复发生。
    """

    id: Identifier
    description: str = Field(min_length=1, max_length=500)
    activity: Activity = "reading"
    evidence_ids: list[Identifier] = Field(default_factory=list, max_length=5)


class Habit(HabitUpdate):
    """Track gradual habit support separately from immutable character identity.

    记录渐进习惯支持，与不可变角色身份分离。
    """

    observed_days: list[str] = Field(default_factory=list, max_length=30)
    established: bool = False
    strength: Score = 0
    source: Literal["user_explicit", "simulated_life"] = "user_explicit"
    last_observed_at: AwareDatetime | None = None


class Topic(Model):
    """Keep opted-in follow-up relevance and cooldown state.

    保存已允许跟进的话题相关性及冷却状态。
    """

    evidence_ids: list[Identifier] = Field(default_factory=list, max_length=10)
    id: Identifier
    description: str = Field(min_length=1, max_length=500)
    relevance: Score = 0.5
    priority: Score = 0.5
    cooldown_seconds: int = Field(default=604800, ge=86400, le=31536000)
    status: Literal["open", "resolved", "dismissed"] = "open"
    last_mentioned_at: AwareDatetime | None = None


class TopicUpdate(Model):
    """Bound explicit topic edits and mention observations.

    约束显式话题编辑及提及观察。
    """

    evidence_ids: list[Identifier] = Field(default_factory=list, max_length=10)
    id: Identifier
    description: str = Field(min_length=1, max_length=500)
    relevance: Score = 0.5
    priority: Score = 0.5
    cooldown_seconds: int = Field(default=604800, ge=86400, le=31536000)
    status: Literal["open", "resolved", "dismissed"] = "open"
    mentioned: bool = False


class LifeState(Model):
    """Track simulated activity timing; simulation must not become shared experience.

    记录模拟活动时序；模拟不能变成用户共同经历。
    """

    activity: Activity = "idle"
    current_process: str = Field(default="daily_routine", max_length=100)
    current_phase: str = Field(default="idle", max_length=100)
    started_at: AwareDatetime = Field(default_factory=now)
    expected_end: AwareDatetime | None = None
    next_decision_after: AwareDatetime | None = None
    confidence: Score = 0.5
    source: Literal["simulated_life"] = "simulated_life"
    updated_at: AwareDatetime = Field(default_factory=now)
    reason: str = Field(default="", max_length=240)


class Decision(Model):
    """Persist a reserved intent and delivery state, not evidence that a message was sent.

    保存预留意图及投递状态，不证明消息已经发送。
    """

    id: Identifier = Field(default_factory=new_id)
    should_contact: bool = False
    # Old pending records have no phase: they may already have reached a gateway.
    status: Literal[
        "reserved", "generation_requested", "delivery_pending", "delivered", "failed", "unknown"
    ] = "unknown"
    claim_id: Identifier | None = None
    topic_fingerprint: str = Field(default="", max_length=64)
    reason: str = Field(default="", max_length=240)
    topic: str = Field(default="", max_length=500)
    topic_id: str = Field(default="", max_length=220)
    urgency: Literal["low", "normal", "high"] = "low"
    context: dict[str, str] = Field(default_factory=dict, max_length=5)
    silence_reason: str = Field(default="", max_length=100)
    cooldown: int = Field(default=0, ge=0)
    created_at: AwareDatetime = Field(default_factory=now)


class CompanionUpdate(Model):
    """Describe bounded companion mutations; legacy Mood writes are rejected by the API.

    描述有界陪伴变化；旧 Mood 写入由 API 明确拒绝。
    """

    settings: SettingsUpdate | None = None
    mood: MoodUpdate | dict[str, JsonValue] | None = None
    goal: GoalUpdate | None = None
    habit: HabitUpdate | None = None
    topic: TopicUpdate | None = None


class CompanionState(Model):
    """Current life state plus an opaque historical Mood archive.

    当前生活状态附带不透明的历史 Mood 档案；未知字段往返保留，不参与当前决策。
    """

    model_config = ConfigDict(extra="allow")
    schema_version: Literal[1] = 1
    character_id: Identifier
    revision: int = Field(default=1, ge=1)
    settings: Settings = Field(default_factory=Settings)
    mood: dict[str, JsonValue] = Field(default_factory=dict, description="Read-only legacy archive")
    goals: list[Goal] = Field(default_factory=list, max_length=30)
    habits: list[Habit] = Field(default_factory=list, max_length=20)
    topics: list[Topic] = Field(default_factory=list, max_length=30)
    life: LifeState = Field(default_factory=LifeState)
    observations: dict[str, Observation] = Field(default_factory=dict, max_length=4)
    last_advanced_at: AwareDatetime = Field(default_factory=now)
    last_user_activity: AwareDatetime | None = None
    last_contact_at: AwareDatetime | None = None
    contact_day: str = ""
    contacts_today: int = Field(default=0, ge=0)
    pending_decision: Decision | None = None
    acknowledgements: dict[str, bool] = Field(default_factory=dict, max_length=32)
    contacted_topics: dict[str, AwareDatetime] = Field(default_factory=dict, max_length=60)
    simulated_memories: list[Candidate] = Field(default_factory=list, max_length=30)


class LegacyMoodWriteUnsupported(ValueError):
    """Stable public compatibility failure; legacy data remains read-only.

    稳定的公开兼容错误；旧数据只读，不能静默转换为新的情绪变化。
    """

    code = "LEGACY_MOOD_WRITE_UNSUPPORTED"
    read_only = True
    replacement = "AffectEffect"

    def __init__(self) -> None:
        super().__init__(
            "Legacy Mood is a read-only archive; "
            "submit AffectEffect via TurnProposal.affect_effects"
        )
