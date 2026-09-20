"""The single decision engine used by host and runtime schedulers. Never sends messages."""

from typing import TYPE_CHECKING, Any, Literal
from zoneinfo import ZoneInfo

from .companion_models import Decision

if TYPE_CHECKING:
    from .companion import Companion


def decide(
    companion: "Companion", character_id: str, reservation_id: str | None = None
) -> Decision:
    with companion.storage.transaction():
        state = companion.advance(character_id)
        settings, instant = state.settings, companion.clock()
        local = instant.astimezone(ZoneInfo(settings.timezone))

        def silent(reason: str, cooldown: int = 0) -> Decision:
            return Decision(silence_reason=reason, cooldown=max(0, cooldown), created_at=instant)

        if not settings.proactive_contact:
            return silent("disabled")
        pending = state.pending_decision
        if reservation_id is not None and (pending is None or pending.id != reservation_id):
            return silent("unknown_reservation")
        if pending and reservation_id is None:
            # No automatic lease expiry: after a crash delivery is uncertain. Require an ack.
            return silent("delivery_unconfirmed")
        if pending and (instant - pending.created_at).total_seconds() > 300:
            return silent("reservation_stale")
        start, end = settings.quiet_start, settings.quiet_end
        if (start < end and start <= local.hour < end) or (
            start > end and (local.hour >= start or local.hour < end)
        ):
            return silent("quiet_hours")
        environment = companion.environment(state)
        availability = environment.get("schedule", {}).get("availability", "unknown")
        if settings.availability in ("busy", "unavailable") or availability in (
            "busy",
            "unavailable",
        ):
            return silent("unavailable")
        if state.last_user_activity:
            remaining = (
                settings.recent_activity_seconds
                - (instant - state.last_user_activity).total_seconds()
            )
            if remaining > 0:
                return silent("recent_activity", int(remaining) + 1)
        if state.last_contact_at:
            remaining = (
                settings.cooldown_seconds - (instant - state.last_contact_at).total_seconds()
            )
            if remaining > 0:
                return silent("cooldown", int(remaining) + 1)
        today = local.date().isoformat()
        if today > state.contact_day:
            state.contact_day, state.contacts_today = today, 0
        if state.contacts_today >= settings.max_contacts_per_day:
            return silent("daily_limit")
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
                        topic.priority * topic.relevance,
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
                key == pending.topic_id and text[:240] == pending.topic
                for _, key, text, _ in candidates
            ):
                return silent("topic_no_longer_relevant")
            return pending
        _, key, topic_text, urgency = max(candidates)
        decision = Decision(
            should_contact=True,
            reason="Relevant opted-in follow-up",
            topic=topic_text[:240],
            topic_id=key,
            urgency=urgency,
            context={
                "character_id": character_id,
                "instruction": "宿主按当前角色自然措辞；不把模拟生活当成共同经历",
            },
            cooldown=settings.cooldown_seconds,
            created_at=instant,
        )
        state.pending_decision = decision
        companion._save(state)
        return decision


def ack(
    companion: "Companion", character_id: str, decision_id: str, delivered: bool
) -> dict[str, Any]:
    with companion.storage.transaction():
        state = companion.get(character_id)
        if decision_id in state.acknowledgements:
            if state.acknowledgements[decision_id] != delivered:
                raise ValueError("Delivery acknowledgement conflicts with previous acknowledgement")
            return {"decision_id": decision_id, "delivered": delivered, "duplicate": True}
        pending = state.pending_decision
        if pending is None or pending.id != decision_id:
            raise ValueError("Unknown pending decision")
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
        return {"decision_id": decision_id, "delivered": delivered, "duplicate": False}
