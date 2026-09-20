"""Versioned, bounded companion state; never a second character definition."""

from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, Field, model_validator

from .models import Candidate, Identifier, Model, Score, new_id, now
from .providers import Activity, Observation


class Settings(Model):
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
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("Unknown timezone; install IANA timezone data or use UTC") from error
        return self


class SettingsUpdate(Model):
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
    label: str = Field(min_length=1, max_length=80)
    intensity: Score
    reason: str = Field(min_length=1, max_length=500)
    evidence_ids: list[Identifier] = Field(default_factory=list, max_length=5)


class Mood(Model):
    label: str = Field(default="neutral", max_length=80)
    intensity: Score = 0
    reason: str = Field(default="", max_length=500)
    evidence_ids: list[Identifier] = Field(default_factory=list, max_length=5)
    updated_at: AwareDatetime = Field(default_factory=now)
    influenced_at: AwareDatetime | None = None


class Goal(Model):
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
    id: Identifier
    description: str = Field(min_length=1, max_length=500)
    activity: Activity = "reading"
    evidence_ids: list[Identifier] = Field(default_factory=list, max_length=5)


class Habit(HabitUpdate):
    observed_days: list[str] = Field(default_factory=list, max_length=30)
    established: bool = False
    strength: Score = 0
    source: Literal["user_explicit", "simulated_life"] = "user_explicit"
    last_observed_at: AwareDatetime | None = None


class Topic(Model):
    id: Identifier
    description: str = Field(min_length=1, max_length=500)
    relevance: Score = 0.5
    priority: Score = 0.5
    cooldown_seconds: int = Field(default=604800, ge=86400, le=31536000)
    status: Literal["open", "resolved", "dismissed"] = "open"
    last_mentioned_at: AwareDatetime | None = None


class TopicUpdate(Model):
    id: Identifier
    description: str = Field(min_length=1, max_length=500)
    relevance: Score = 0.5
    priority: Score = 0.5
    cooldown_seconds: int = Field(default=604800, ge=86400, le=31536000)
    status: Literal["open", "resolved", "dismissed"] = "open"
    mentioned: bool = False


class LifeState(Model):
    activity: Activity = "idle"
    source: Literal["simulated_life"] = "simulated_life"
    updated_at: AwareDatetime = Field(default_factory=now)
    reason: str = Field(default="", max_length=240)


class Decision(Model):
    id: Identifier = Field(default_factory=new_id)
    should_contact: bool = False
    reason: str = Field(default="", max_length=240)
    topic: str = Field(default="", max_length=240)
    topic_id: str = Field(default="", max_length=220)
    urgency: Literal["low", "normal", "high"] = "low"
    context: dict[str, str] = Field(default_factory=dict, max_length=5)
    silence_reason: str = Field(default="", max_length=100)
    cooldown: int = Field(default=0, ge=0)
    created_at: AwareDatetime = Field(default_factory=now)


class CompanionUpdate(Model):
    settings: SettingsUpdate | None = None
    mood: MoodUpdate | None = None
    goal: GoalUpdate | None = None
    habit: HabitUpdate | None = None
    topic: TopicUpdate | None = None


class CompanionState(Model):
    schema_version: Literal[1] = 1
    character_id: Identifier
    revision: int = Field(default=1, ge=1)
    settings: Settings = Field(default_factory=Settings)
    mood: Mood = Field(default_factory=Mood)
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
