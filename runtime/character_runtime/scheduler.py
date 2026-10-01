"""Runtime scheduler emits reserved intents; host scheduler uses the same engine over MCP.

Runtime 调度只预留意图；宿主通过 MCP 使用同一引擎。
"""

from typing import Any

from .runtime import Runtime


def tick(runtime: Runtime, character_ids: list[str]) -> list[dict[str, Any]]:
    """Advance due local work and reserve intents without sending platform messages.

    推进到期本地工作并预留意图，不发送平台消息。
    """

    results = []
    for character_id in character_ids:
        with runtime.storage.transaction():
            runtime.advance(character_id)
            decision = runtime.companion.decide(character_id)
            results.append({"character_id": character_id, **decision.model_dump(mode="json")})
    return results
