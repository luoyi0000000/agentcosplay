"""Runtime scheduler emits reserved intents; host scheduler uses the same engine over MCP."""

from typing import Any

from .runtime import Runtime


def tick(runtime: Runtime, character_ids: list[str]) -> list[dict[str, Any]]:
    results = []
    for character_id in character_ids:
        with runtime.storage.transaction():
            runtime.advance(character_id)
            decision = runtime.companion.decide(character_id)
            results.append({"character_id": character_id, **decision.model_dump(mode="json")})
    return results
