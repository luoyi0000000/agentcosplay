"""The single decision engine used by Host and Runtime schedulers; never sends messages.

宿主与 Runtime 调度共用唯一决策引擎；这里只保留意图，不发送消息或制造事实。
"""

from hashlib import sha256
from typing import TYPE_CHECKING, Any, Literal
from zoneinfo import ZoneInfo

from .companion_models import CompanionState, Decision
from .models import new_id

if TYPE_CHECKING:
    from .companion import Companion


def contact_limit(companion: "Companion", state: CompanionState) -> str | None:
    """Shared quiet/availability/rate gate for proactive contact and afterthoughts.

    主动联系与当前对话补充消息共用安静时段、可用状态及频率限制。
    """
    settings, instant = state.settings, companion.clock()
    local = instant.astimezone(ZoneInfo(settings.timezone))
    start, end = settings.quiet_start, settings.quiet_end
    if (start < end and start <= local.hour < end) or (
        start > end and (local.hour >= start or local.hour < end)
    ):
        return "quiet_hours"
    availability = companion.environment(state).get("schedule", {}).get("availability", "unknown")
    if settings.availability in ("busy", "unavailable") or availability in ("busy", "unavailable"):
        return "unavailable"
    if (
        state.last_contact_at
        and (instant - state.last_contact_at).total_seconds() < settings.cooldown_seconds
    ):
        return "cooldown"
    if (
        local.date().isoformat() <= state.contact_day
        and state.contacts_today >= settings.max_contacts_per_day
    ):
        return "daily_limit"
    return None


def _evaluate(
    companion: "Companion", state: CompanionState, reservation_id: str | None = None
) -> Decision:
    """Evaluate opted-in motives; callers hold the write transaction and claim each phase once.

    评估用户已开启的动机与机会；调用方持有事务，每个生成或发送阶段只领取一次。
    """
    character_id = state.character_id
    settings, instant = state.settings, companion.clock()
    local = instant.astimezone(ZoneInfo(settings.timezone))

    pending = state.pending_decision

    def silent(reason: str, cooldown: int = 0) -> Decision:
        if pending and reservation_id == pending.id:
            companion._invalidate_pending(state, reason)
            companion._save(state)
        return Decision(silence_reason=reason, cooldown=max(0, cooldown), created_at=instant)

    if not settings.proactive_contact:
        return silent("disabled")
    if reservation_id is not None and (pending is None or pending.id != reservation_id):
        return silent("unknown_reservation")
    if pending and not pending.should_contact:
        return silent(pending.silence_reason or "reservation_invalidated")
    if pending and instant < pending.created_at:
        return silent("clock_rewind")
    if pending and (instant - pending.created_at).total_seconds() > 300:
        return silent("reservation_stale")
    limit = contact_limit(companion, state)
    if limit:
        remaining = (
            settings.cooldown_seconds - (instant - state.last_contact_at).total_seconds()
            if limit == "cooldown" and state.last_contact_at
            else 0
        )
        return silent(limit, int(remaining) + 1 if remaining else 0)
    if state.last_user_activity:
        remaining = (
            settings.recent_activity_seconds - (instant - state.last_user_activity).total_seconds()
        )
        if remaining > 0:
            return silent("recent_activity", int(remaining) + 1)
    today = local.date().isoformat()
    if today > state.contact_day:
        state.contact_day, state.contacts_today = today, 0
    candidates: list[tuple[float, str, str, Literal["low", "normal", "high"]]] = []
    for topic in state.topics:
        last = max(
            (
                value
                for value in (
                    state.contacted_topics.get("topic:" + topic.id),
                    topic.last_mentioned_at,
                )
                if value is not None
            ),
            default=None,
        )
        if (
            topic.status == "open"
            and topic.priority * topic.relevance >= 0.2
            and (last is None or (instant - last).total_seconds() >= topic.cooldown_seconds)
        ):
            candidates.append(
                (
                    # A soft recency preference breaks repetition without inventing new motives.
                    # 柔性的近期使用倾向减少重复，不凭空生成新的动机或共同经历。
                    topic.priority
                    * topic.relevance
                    * (
                        1
                        if last is None
                        else 1
                        + 0.25
                        * min(
                            2, max(0, (instant - last).total_seconds() / topic.cooldown_seconds - 1)
                        )
                    ),
                    "topic:" + topic.id,
                    topic.description,
                    "normal",
                )
            )
    for goal in state.goals:
        last = state.contacted_topics.get("goal:" + goal.id)
        if (
            goal.status == "active"
            and goal.importance >= 0.7
            and goal.deadline
            and 0 <= (goal.deadline - instant).total_seconds() <= 86400
            and (last is None or (instant - last).total_seconds() >= 604800)
        ):
            candidates.append((goal.importance, "goal:" + goal.id, goal.description, "high"))
    if not candidates:
        return silent("no_relevant_topic")
    if pending:
        if not any(
            key == pending.topic_id
            and sha256(text.encode()).hexdigest() == pending.topic_fingerprint
            for _, key, text, _ in candidates
        ):
            return silent("topic_no_longer_relevant")
        return pending
    _, key, topic_text, urgency = max(candidates)
    decision = Decision(
        should_contact=True,
        status="reserved",
        topic_fingerprint=sha256(topic_text.encode()).hexdigest(),
        reason="Relevant opted-in follow-up",
        topic=topic_text,
        topic_id=key,
        urgency=urgency,
        context={
            "character_id": character_id,
            "instruction": "宿主按当前角色自然措辞；不把模拟生活当成共同经历",
            "motive": "time_bound_goal" if key.startswith("goal:") else "pending_followup",
            "opportunity": "schedule_available"
            if companion.environment(state).get("schedule", {}).get("availability") == "available"
            else "idle_window",
            "basis": "configured intent, not a completed event",
        },
        cooldown=settings.cooldown_seconds,
        created_at=instant,
    )
    state.pending_decision = decision
    companion._save(state)
    return decision


def _blocked(pending: Decision, reason: str) -> Decision:
    return pending.model_copy(
        update={"should_contact": False, "silence_reason": reason, "claim_id": None}
    )


def decide(
    companion: "Companion", character_id: str, reservation_id: str | None = None
) -> Decision:
    """Reserve one relevant initiative, preserving unknown delivery quarantine.

    保留一个相关主动意图；未知投递继续隔离，不因再次调度而重新发送。
    """
    with companion.storage.transaction():
        state = companion.advance(character_id)
        pending = state.pending_decision
        if pending:
            # A scheduler retry is observational, never another generation/delivery grant.
            reason = "delivery_unconfirmed"
            if reservation_id and pending.id != reservation_id:
                reason = "unknown_reservation"
            return _blocked(pending, reason)
        return _evaluate(companion, state, reservation_id)


def prepare(companion: "Companion", character_id: str, decision_id: str) -> Decision:
    """Claim generation once; the Host's current model uses its bounded context.

    仅领取一次生成权限；由宿主当前模型根据有界上下文生成。
    """
    with companion.storage.transaction():
        state = companion.advance(character_id)
        pending = state.pending_decision
        if pending is None or pending.id != decision_id:
            raise ValueError("Unknown pending decision")
        if pending.status != "reserved":
            return _blocked(pending, "generation_already_claimed")
        result = _evaluate(companion, state, decision_id)
        if not result.should_contact:
            return _blocked(pending, result.silence_reason)
        pending.status, pending.claim_id = "generation_requested", new_id()
        companion._save(state)
        return pending


def delivery(
    companion: "Companion", character_id: str, decision_id: str, claim_id: str
) -> Decision:
    """Claim one gateway attempt immediately before sending, with decision_id as its key.

    The host must not retry a send after timeout or a lost response. A gateway may
    only retry internally if it durably deduplicates that key. Runtime sends no text.

    发送前只领取一次 Gateway 尝试权限；超时或丢失回执不得盲目重发。
    Gateway 只有持久去重时才可内部重试，Runtime 本身不发送正文。
    """
    with companion.storage.transaction():
        state = companion.advance(character_id)
        pending = state.pending_decision
        if pending is None or pending.id != decision_id:
            raise ValueError("Unknown pending decision")
        if not pending.claim_id or pending.claim_id != claim_id:
            raise ValueError("Generation claim does not match")
        if pending.status != "generation_requested":
            return _blocked(pending, "delivery_unconfirmed")
        result = _evaluate(companion, state, decision_id)
        if not result.should_contact:
            return _blocked(pending, result.silence_reason)
        pending.status = "delivery_pending"
        companion._save(state)
        return pending


def ack(
    companion: "Companion",
    character_id: str,
    decision_id: str,
    delivered: bool | None,
    claim_id: str | None = None,
) -> dict[str, Any]:
    """True confirms delivery, False definite non-delivery, None an unresolved outcome.

    True 表示确认送达，False 表示确定未送达，None 表示结果未知且不可盲目重试。
    """
    with companion.storage.transaction():
        state = companion.get(character_id)
        if decision_id in state.acknowledgements:
            if state.acknowledgements[decision_id] != delivered:
                raise ValueError("Delivery acknowledgement conflicts with previous acknowledgement")
            return {
                "decision_id": decision_id,
                "delivered": delivered,
                "status": "delivered" if delivered else "failed",
                "duplicate": True,
            }
        pending = state.pending_decision
        if pending is None or pending.id != decision_id:
            raise ValueError("Unknown pending decision")
        if pending.claim_id is not None and claim_id != pending.claim_id:
            raise ValueError("Generation claim does not match")
        if delivered is not False and pending.status not in ("delivery_pending", "unknown"):
            raise ValueError("Delivery has not been claimed")
        if delivered is None:
            duplicate = pending.status == "unknown"
            pending.status = "unknown"
            companion._save(state)
            return {
                "decision_id": decision_id,
                "delivered": None,
                "status": "unknown",
                "duplicate": duplicate,
            }
        if delivered:
            instant = companion.clock()
            today = instant.astimezone(ZoneInfo(state.settings.timezone)).date().isoformat()
            if today > state.contact_day:
                state.contact_day, state.contacts_today = today, 0
            state.contacts_today += 1
            state.last_contact_at = max(instant, state.last_contact_at or instant)
            state.contacted_topics[pending.topic_id] = instant
            state.contacted_topics = dict(list(state.contacted_topics.items())[-60:])
            if pending.topic_id.startswith("topic:"):
                for topic in state.topics:
                    if topic.id == pending.topic_id[6:]:
                        topic.last_mentioned_at = instant
        state.acknowledgements[decision_id] = delivered
        state.acknowledgements = dict(list(state.acknowledgements.items())[-32:])
        state.pending_decision = None
        companion._save(state)
        return {
            "decision_id": decision_id,
            "delivered": delivered,
            "status": "delivered" if delivered else "failed",
            "duplicate": False,
        }
