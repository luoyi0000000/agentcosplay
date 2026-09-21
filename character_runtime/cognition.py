"""Structured host intent routing, expression policy and explicit temporal recall."""

from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .models import VoiceProfile
from .persistence_models import GenerationRequest, RecallRequest


def expression(
    request: GenerationRequest, voice: VoiceProfile, relationship: dict[str, Any], mode: str
) -> dict[str, Any]:
    strict = request.explicit_format != "natural" or mode == "task_neutral"
    analytical = request.intent in {"ANALYSIS", "EXPLANATION", "CODING", "FACTUAL_QA", "TOOL_TASK"}
    return {
        "intent": request.intent,
        "format": request.explicit_format,
        "user_length_request": request.length_request,
        "platform_constraints": request.platform_constraints,
        "verbosity": "task-required"
        if analytical or request.length_request
        else voice.verbosity_default,
        "directness": voice.directness,
        "sentence_target": voice.sentence_length,
        "warmth": "respectful" if relationship.get("stage") == "stranger" else "familiar",
        "explanation_depth": "complete when required by the task"
        if analytical
        else "conversational",
        "catchphrase_density": "none" if strict else "optional, sparse, never mandatory",
        "stage_direction_policy": "none" if strict else voice.stage_direction_policy,
        "precedence": [
            "safety/correctness",
            "user format/length",
            "task",
            "platform",
            "voice",
            "affect",
        ],
        "history_is_voice_training": False,
        "hard_output_truncation": False,
    }


def window(request: RecallRequest, instant: datetime) -> tuple[datetime | None, datetime | None]:
    if request.start and request.end and request.start >= request.end:
        raise ValueError("Recall start must precede end")
    if request.relative_window:
        if request.start or request.end:
            raise ValueError("Choose an explicit or relative time window, not both")
        local = instant.astimezone(ZoneInfo(request.timezone))
        today = datetime.combine(local.date(), time.min, tzinfo=local.tzinfo)
        if request.relative_window == "today":
            return today, today + timedelta(days=1)
        if request.relative_window == "yesterday":
            return today - timedelta(days=1), today
        monday = today - timedelta(days=today.weekday())
        return monday - timedelta(days=7), monday
    if request.intent == "TIME_WINDOW" and not (request.start or request.end):
        raise ValueError(
            "TIME_WINDOW requires dates or a relative window; ask the host to resolve them"
        )
    return request.start, request.end


def classify_conflict(
    old: str, new: str, *, same_slot: bool = False, proposed: str = "UNRELATED"
) -> str:
    from .retrieval import normalize

    if old == new:
        return "EXACT_DUPLICATE"
    if normalize(old) == normalize(new):
        return "NEAR_DUPLICATE"
    if proposed in {"CORRECTION", "CONTRADICTION", "SUPERSEDING_UPDATE", "SUPPLEMENT"}:
        return proposed
    return "CONTRADICTION" if same_slot else "UNRELATED"
