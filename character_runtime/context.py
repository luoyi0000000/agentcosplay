"""Bounded projections. Original records remain the only source of truth."""

from typing import Any


def clip(value: str, limit: int = 800) -> str:
    return value if len(value) <= limit else value[:limit] + "…[truncated; request full record]"


def project_context(result: dict[str, Any], query: str) -> dict[str, Any]:
    definition, state = result["definition"], result["state"]
    facts = definition["facts"]
    core = {"identity", "personality", "self_beliefs", "world", "speech_style", "boundaries"}
    tokens = query.casefold().split()
    keys = sorted(
        facts,
        key=lambda k: (k in core, sum(t in (k + facts[k]["value"]).casefold() for t in tokens)),
        reverse=True,
    )[:12]
    definition["facts"] = {
        k: {
            **facts[k],
            "value": clip(facts[k]["value"]),
            "reference": clip(facts[k]["reference"], 200),
        }
        for k in keys
    }
    result["context_limits"] = {
        "facts": 12,
        "memories": 8,
        "text_chars": 800,
        "partial": len(keys) < len(facts),
        "full_records": "character_read / memory_recall",
    }
    state["evolution"] = state["evolution"][-3:]
    for event in state["evolution"]:
        event["value"] = clip(event["value"])
        if event["portable_summary"]:
            event["portable_summary"] = clip(event["portable_summary"])
    state["relationship_history"] = [
        {clip(k, 80): clip(str(v), 240) for k, v in list(event.items())[:8]}
        for event in state["relationship_history"][-3:]
    ]
    state["known_characters"] = state["known_characters"][:10]
    state["last_growth_turn"] = dict(list(state["last_growth_turn"].items())[-10:])
    relation = state["relationship"]
    relation["boundaries"] = [clip(v, 300) for v in relation["boundaries"][:6]]
    result["memories"] = [
        {
            **m,
            "content": clip(m["content"]),
            "source": clip(m["source"], 200),
            "shared_with": [],
            "confirmation": "",
        }
        for m in result["memories"][:8]
    ]
    # JSON pointers expose an explicit Self Model without copying persistent records or prompts.
    result["self_model"] = {
        "identity": "/definition",
        "self_beliefs": "/definition/facts/self_beliefs",
        "personality": "/definition/facts/personality",
        "relationship": "/state/relationship",
        "autobiographical_memory": "/memories",
        "growth_history": "/state/evolution",
    }
    return result
