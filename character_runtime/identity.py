"""Explicit stable platform IDs, scoped to the authenticated Runtime owner."""

from typing import Any

from .models import now
from .operations import fingerprint
from .storage import Storage


def binding_key(host: str, platform: str, actor_id: str) -> str:
    if any(not v.strip() or len(v) > 200 for v in (host, platform, actor_id)):
        raise ValueError("Stable host/platform/actor IDs are required, never display names")
    return fingerprint([host, platform, actor_id])


def resolve(storage: Storage, owner: str, host: str, platform: str, actor_id: str) -> str | None:
    key = binding_key(host, platform, actor_id)
    record = storage.get(owner, "identity_binding", key)
    return key if record and record.get("active") and record.get("owner_id") == owner else None


def bind(
    storage: Storage,
    owner: str,
    host: str,
    platform: str,
    actor_id: str,
    operation_id: str,
    confirmation: str,
) -> dict[str, Any]:
    if not confirmation.strip():
        raise ValueError("Explicit owner approval of the stable platform identity is required")
    key = binding_key(host, platform, actor_id)
    payload = fingerprint([host, platform, actor_id])
    with storage.transaction():
        receipt = storage.get(owner, "identity_receipt", operation_id)
        if receipt and receipt["fingerprint"] != payload:
            raise ValueError("Identity operation ID conflict")
        if receipt:
            return {"binding_id": receipt["binding_id"]}
        storage.put(
            owner,
            "identity_binding",
            key,
            {
                "id": key,
                "owner_id": owner,
                "host": host,
                "platform": platform,
                "actor_id": actor_id,
                "active": True,
                "authority": "USER_EXPLICIT",
                "created_at": now().isoformat(),
            },
        )
        storage.put(
            owner, "identity_receipt", operation_id, {"binding_id": key, "fingerprint": payload}
        )
        return {"binding_id": key}
