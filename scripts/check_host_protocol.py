"""Check shared Host contracts without SDKs or a model.
无需宿主 SDK 或模型即可检查共享宿主契约。
"""

import json
import time
from unittest.mock import patch

from character_runtime.host_protocol import (
    ActiveHostTurn,
    HostIngress,
    InputEvidence,
    TurnRegistry,
    stable_host_key,
)
from scripts.check_hermes import sample_projection


def main():
    assert (
        stable_host_key("a", "b")
        == __import__("hashlib")
        .sha256(json.dumps(("a", "b"), ensure_ascii=True).encode())
        .hexdigest()
    )
    ingress = HostIngress(
        host_id="host",
        platform="platform",
        actor_id="actor",
        endpoint_id="endpoint",
        chat_type="dm",
        session_id="s",
        turn_id="t",
        message_id="m",
        text="hello",
        input_evidence=InputEvidence.TRANSFORMED,
    )
    assert ingress.envelope()["input_is_verbatim"] is False
    assert ingress.envelope()["timestamp"] is None
    registry = TurnRegistry(capacity=2, ttl=1)
    assert registry.get(("missing", "turn")) is None
    turn = ActiveHostTurn(
        runtime_turn_id="rt",
        runtime_session_id="rs",
        capability="synthetic",
        generation_context=sample_projection(),
        created_monotonic=time.monotonic(),
    )
    registry.put(("session", "old"), turn)
    copied = registry.get(("session", "old"))
    copied.capability = "changed"
    assert registry.get(("session", "old")).capability == "synthetic"
    with patch(
        "character_runtime.host_protocol.time.monotonic", return_value=turn.created_monotonic + 2
    ):
        assert registry.get(("session", "old")) is None
    first = registry.reserve(("s", "t"))
    second = registry.reserve(("s", "t"))
    assert not registry.complete(("s", "t"), first, turn)
    assert registry.complete(("s", "t"), second, turn)
    registry.clear("s")
    assert registry.get(("s", "t")) is None
    print("PASS shared Host models, evidence, TTL, defensive copies, superseded callbacks, cleanup")


if __name__ == "__main__":
    main()
