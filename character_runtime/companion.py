"""Transactional companion state, conservative offline simulation, and bounded views.

事务化陪伴状态、保守离线模拟与有界视图。
"""

from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any
from zoneinfo import ZoneInfo

from .characters import Characters
from .companion_models import (
    CompanionState,
    CompanionUpdate,
    Decision,
    Goal,
    Habit,
    LegacyMoodWriteUnsupported,
    LifeState,
    Settings,
    Topic,
)
from .models import Candidate, now
from .providers import Observation, Provider
from .safety import check_content
from .storage import Storage


class Companion:
    """Maintain scoped life and proactive state; legacy Mood is only a read-only archive.

    维护作用域内生活与主动状态；旧 Mood 仅为只读档案。
    """

    def __init__(
        self,
        storage: Storage,
        owner: str,
        characters: Characters,
        clock: Callable[[], datetime] = now,
    ) -> None:
        if owner != characters.owner:
            raise ValueError("Companion owner must match Characters owner")
        self.storage, self.owner, self.characters, self.clock = storage, owner, characters, clock

    def get(self, character_id: str) -> CompanionState:
        """Read companion state preserving opaque legacy fields and safe defaults.

        读取陪伴状态，保留不透明旧字段及安全默认值。
        """

        self.characters.get(character_id)
        raw = self.storage.get(self.owner, "companion", character_id)
        if raw is not None:
            result = CompanionState.model_validate(raw)
            if result.character_id != character_id:
                raise ValueError("Companion character mismatch")
            return result
        instant = self.clock()
        return CompanionState(
            character_id=character_id,
            last_advanced_at=instant,
            life=LifeState(updated_at=instant),
        )

    def _save(self, state: CompanionState) -> None:
        state.revision += 1
        validated = CompanionState.model_validate(state.model_dump())
        self.storage.put(
            self.owner, "companion", state.character_id, validated.model_dump(mode="json")
        )

    @staticmethod
    def _invalidate_pending(state: CompanionState, reason: str) -> None:
        pending = state.pending_decision
        if pending and pending.status in ("reserved", "generation_requested"):
            pending.should_contact = False
            pending.silence_reason = reason

    def _evidence(self, character_id: str, evidence_ids: list[str]) -> None:
        for key in evidence_ids:
            record = self.storage.get(self.owner, "raw_event", key)
            if (
                not record
                or record.get("character_id") != character_id
                or record.get("owner_id") != self.owner
                or record.get("legacy_unverified")
                or record.get("validity") != "active"
                or record.get("source_kind") != "USER_DIRECT"
            ):
                raise ValueError("Companion evidence requires direct owned RawEvents")

    def update(
        self, character_id: str, update: CompanionUpdate, *, endpoint_admin: bool = False
    ) -> CompanionState:
        """Update audience state; endpoint policy changes require the trusted admin bridge.

        更新当前受众状态；Endpoint 策略配置仅由可信管理入口授权。
        """
        update = CompanionUpdate.model_validate(update.model_dump())
        if update.mood is not None:
            raise LegacyMoodWriteUnsupported()
        with self.storage.transaction():
            actor = getattr(self.storage, "actor", None)
            if (
                actor
                and not actor.private_context_allowed
                and not endpoint_admin
                and update.settings
            ):
                # An ordinary group participant cannot control endpoint policy.
                # 普通群成员不能通过个人 OOC 操作管理 Endpoint 设置。
                raise ValueError("Endpoint settings require owner administration")
            state = self.advance(character_id)
            instant = self.clock()
            if update.settings:
                settings = state.settings.model_dump()
                settings.update(update.settings.model_dump(exclude_none=True))
                state.settings = Settings.model_validate(settings)
                if not state.settings.proactive_contact:
                    self._invalidate_pending(state, "disabled")
                if not state.settings.life_simulation:
                    state.life = LifeState(updated_at=instant)
                # Turning simulation on starts here; disabled time must never be caught up.
                state.last_advanced_at = max(state.last_advanced_at, instant)
            if update.goal:
                self._evidence(character_id, update.goal.evidence_ids)
                old = next((g for g in state.goals if g.id == update.goal.id), None)
                if old is None and len(state.goals) >= 30:
                    raise ValueError("Goal limit reached; reuse a completed goal ID")
                data = update.goal.model_dump()
                data.update(
                    created_at=old.created_at if old else instant,
                    simulated_hours=old.simulated_hours if old else 0,
                    simulation_milestone=old.simulation_milestone if old else 0,
                )
                goal = Goal.model_validate(data)
                if goal.status == "completed":
                    goal.progress = 1
                state.goals = [g for g in state.goals if g.id != goal.id] + [goal]
                pending = state.pending_decision
                if (
                    pending
                    and pending.topic_id == "goal:" + goal.id
                    and (
                        goal.status != "active"
                        or sha256(goal.description.encode()).hexdigest()
                        != pending.topic_fingerprint
                    )
                ):
                    self._invalidate_pending(state, "topic_no_longer_relevant")
            if update.habit:
                change = update.habit
                self._evidence(character_id, change.evidence_ids)
                habit = next((h for h in state.habits if h.id == change.id), None)
                if habit is None:
                    if len(state.habits) >= 20:
                        raise ValueError("Habit limit reached")
                    habit = Habit(**change.model_dump())
                    state.habits.append(habit)
                elif habit.description != change.description or habit.activity != change.activity:
                    raise ValueError("Use a new habit ID for a different behavior")
                day = instant.astimezone(ZoneInfo(state.settings.timezone)).date().isoformat()
                if day not in habit.observed_days:
                    habit.observed_days = (habit.observed_days + [day])[-30:]
                    habit.strength = min(1, len(habit.observed_days) / 10)
                    habit.established = len(habit.observed_days) >= 3
                habit.evidence_ids = list(dict.fromkeys(habit.evidence_ids + change.evidence_ids))[
                    -5:
                ]
                habit.last_observed_at = instant
            if update.topic:
                self._evidence(character_id, update.topic.evidence_ids)
                old_topic = next((t for t in state.topics if t.id == update.topic.id), None)
                if old_topic is None and len(state.topics) >= 30:
                    raise ValueError("Topic limit reached; reuse a resolved topic ID")
                data = update.topic.model_dump(exclude={"mentioned"})
                data["last_mentioned_at"] = (
                    instant
                    if update.topic.mentioned
                    else (old_topic.last_mentioned_at if old_topic else None)
                )
                topic = Topic.model_validate(data)
                state.topics = [t for t in state.topics if t.id != topic.id] + [topic]
                pending = state.pending_decision
                if (
                    pending
                    and pending.topic_id == "topic:" + topic.id
                    and (
                        topic.status != "open"
                        or sha256(topic.description.encode()).hexdigest()
                        != pending.topic_fingerprint
                        or update.topic.mentioned
                    )
                ):
                    self._invalidate_pending(state, "topic_no_longer_relevant")
            self._save(state)
            return state

    def observe(self, character_id: str, observation: Observation) -> None:
        """Accept validated provider observations under enabled perception settings.

        只在对应感知设置开启时接受有效来源观察。
        """

        observation = Observation.model_validate(observation.model_dump())
        check_content(observation.model_dump_json())
        with self.storage.transaction():
            state = self.get(character_id)
            if not observation.fresh(self.clock()):
                raise ValueError("Observation is stale or from the future")
            old = state.observations.get(observation.kind)
            if old and old.observed_at > observation.observed_at:
                raise ValueError("Older observation cannot replace a newer observation")
            state.observations[observation.kind] = observation
            self._save(state)

    def refresh(self, character_id: str, providers: Iterable[Provider]) -> dict[str, str]:
        """A missing/failed optional collector must not stop role conversation.

        缺失或失败的可选采集器不能阻止角色对话。
        """
        outcomes = {}
        for index, provider in enumerate(providers):
            try:
                observation = provider.read()
                if observation is None:
                    outcomes[str(index)] = "unavailable"
                else:
                    self.observe(character_id, observation)
                    outcomes[str(index)] = "updated"
            except (OSError, ValueError):
                # Do not surface credentials or paths contained in provider error messages.
                outcomes[str(index)] = "unavailable"
        return outcomes

    def environment(self, state: CompanionState) -> dict[str, dict[str, Any]]:
        """Project fresh enabled observations without treating stale input as current reality.

        只投影新鲜且已启用的观察，不把过期输入当作当前现实。
        """

        instant = self.clock()
        result = {}
        for kind, observation in state.observations.items():
            if not observation.fresh(instant):
                continue
            if kind == "weather" and not state.settings.weather_awareness:
                continue
            if kind == "schedule" and not state.settings.schedule_awareness:
                continue
            value = observation.model_dump(mode="json")
            value["summary"] = observation.summary
            result[kind] = value
        return result

    def advance(self, character_id: str) -> CompanionState:
        """Advance opted-in life simulation without updating the legacy Mood archive.

        推进已开启的生活模拟，不更新旧 Mood 档案。
        """

        with self.storage.transaction():
            state = self.get(character_id)
            instant = self.clock()
            seconds = max(0, (instant - state.last_advanced_at).total_seconds())
            # Legacy Mood is an archive: no decay, adaptation or current-state projection.
            # 旧 Mood 是档案：不衰减、不适应，也不进入当前状态投影。
            if state.settings.life_simulation:
                hour = instant.astimezone(ZoneInfo(state.settings.timezone)).hour
                environment = self.environment(state)
                schedule = environment.get("schedule", {})
                weather = environment.get("weather", {})
                active = [g for g in state.goals if g.status == "active" and g.simulate]
                goal = max(active, key=lambda g: g.importance, default=None)
                habit = next((h for h in state.habits if h.established), None)
                activity = (
                    "resting"
                    if hour < 7 or hour >= 23
                    else (
                        "eating"
                        if hour in (8, 12, 19)
                        else schedule.get("activity")
                        or (goal.activity if goal else (habit.activity if habit else "reading"))
                    )
                )
                if activity == "walking" and weather.get("condition") in ("rain", "snow", "storm"):
                    activity = "reading"
                if (
                    state.life.next_decision_after is None
                    or state.life.next_decision_after <= instant
                    or state.life.activity != activity
                ):
                    state.life = LifeState(
                        activity=activity,
                        updated_at=instant,
                        current_phase=activity,
                        started_at=state.life.started_at
                        if state.life.activity == activity
                        else instant,
                        expected_end=instant + timedelta(hours=1),
                        next_decision_after=instant + timedelta(minutes=30),
                        reason="受约束的日常模拟；不代表现实或共同经历",
                    )
                if goal and seconds > 0:
                    # ponytail: bounded coarse offline progress, not an hour-by-hour simulator.
                    hours = min(seconds / 3600, 72)
                    goal.simulated_hours = min(100000, goal.simulated_hours + hours)
                    before = goal.progress
                    goal.progress = min(0.95, before + min(hours * 0.002, 0.1))
                    milestone = int(goal.simulated_hours // 48)
                    if milestone > goal.simulation_milestone and goal.progress > before:
                        goal.simulation_milestone = milestone
                        event = Candidate(
                            content=f"模拟生活：持续进行{goal.activity}，一个日常目标有小幅进展。",
                            source="simulated_life",
                            importance=0.5,
                            confidence=1,
                        )
                        state.simulated_memories = (state.simulated_memories + [event])[-30:]
            state.last_advanced_at = max(instant, state.last_advanced_at)
            self._save(state)
            return state

    def drain_simulated_memories(self, character_id: str) -> list[Candidate]:
        """Call with memory.store in one outer transaction to make the transfer atomic.

        与 memory.store 放在同一个外层事务，保证转移原子性。
        """
        with self.storage.transaction():
            state = self.get(character_id)
            events = state.simulated_memories
            state.simulated_memories = []
            self._save(state)
            return events

    def context(self, character_id: str, query: str = "") -> dict[str, Any]:
        """Project current companion context with the legacy Mood archive excluded.

        投影当前陪伴上下文，排除旧 Mood 历史档案。
        """

        state = self.advance(character_id)
        words = query.casefold().split()[:20]

        def relevance(item: Goal | Topic | Habit) -> tuple[float, float]:
            matches = sum(word in item.description.casefold() for word in words)
            weight = (
                item.importance
                if isinstance(item, Goal)
                else (item.priority * item.relevance if isinstance(item, Topic) else item.strength)
            )
            return matches, weight

        def select(items: Iterable[Goal | Topic | Habit]) -> list[dict[str, Any]]:
            result = []
            for item in sorted(items, key=relevance, reverse=True):
                if words and not relevance(item)[0] and relevance(item)[1] < 0.8:
                    continue
                fields = {
                    "id",
                    "description",
                    "status",
                    "progress",
                    "deadline",
                    "source",
                    "activity",
                    "strength",
                    "established",
                }
                data = item.model_dump(mode="json", include=fields)
                result.append(data)
            return result

        return {
            "goals": select(g for g in state.goals if g.status == "active"),
            "habits": select(h for h in state.habits if h.established),
            "unfinished_topics": select(t for t in state.topics if t.status == "open"),
            "life": state.life.model_dump(mode="json") if state.settings.life_simulation else None,
            "environment": self.environment(state),
            "settings": state.settings.model_dump(),
        }

    def record_activity(self, character_id: str) -> None:
        """Record current user activity for proactive cooldown decisions.

        记录用户当前活动，用于主动联系冷却判断。
        """

        with self.storage.transaction():
            state = self.get(character_id)
            instant = self.clock()
            state.last_user_activity = max(instant, state.last_user_activity or instant)
            self._invalidate_pending(state, "recent_activity")
            self._save(state)

    def decide(self, character_id: str, reservation_id: str | None = None) -> Decision:
        """Delegate proactive reservations to the single decision engine.

        将主动意图预留交给唯一决策引擎。
        """

        from .proactive import decide

        return decide(self, character_id, reservation_id)

    def prepare(self, character_id: str, decision_id: str) -> Decision:
        """Claim a reserved generation once before asking the Host model.

        请求宿主模型前，只领取一次预留生成机会。
        """

        from .proactive import prepare

        return prepare(self, character_id, decision_id)

    def delivery(self, character_id: str, decision_id: str, claim_id: str) -> Decision:
        """Recheck send gates and claim a single delivery attempt.

        重查发送门，并领取一次投递尝试。
        """

        from .proactive import delivery

        return delivery(self, character_id, decision_id, claim_id)

    def ack(
        self,
        character_id: str,
        decision_id: str,
        delivered: bool | None,
        claim_id: str | None = None,
    ) -> dict[str, Any]:
        """Record delivered, failed or unknown outcomes without blind retries.

        记录已送达、明确失败或未知结果，不盲目重试。
        """

        from .proactive import ack

        return ack(self, character_id, decision_id, delivered, claim_id)
