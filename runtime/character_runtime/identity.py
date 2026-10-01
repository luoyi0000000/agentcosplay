"""Resolve explicit platform identities inside an authenticated owner's namespace.

在已认证 Runtime Owner 的命名空间内解析显式绑定；Participant 不等于 Owner。
"""

from typing import Any

from .models import now
from .operations import fingerprint
from .storage import Storage


def binding_key(host: str, platform: str, actor_id: str) -> str:
    """Hash stable provider IDs, never display names. / 只使用稳定标识，不推测昵称。"""
    if any(not v.strip() or len(v) > 200 for v in (host, platform, actor_id)):
        raise ValueError("Stable host/platform/actor IDs are required, never display names")
    return fingerprint([host, platform, actor_id])


def resolve(storage: Storage, owner: str, host: str, platform: str, actor_id: str) -> str | None:
    """Resolve active bindings only. / 仅解析当前有效的绑定。"""
    key = binding_key(host, platform, actor_id)
    record = storage.get(owner, "identity_binding", key)
    if not record or not record.get("active") or record.get("owner_id") != owner:
        return None
    if (record.get("host"), record.get("platform"), record.get("actor_id")) != (
        host,
        platform,
        actor_id,
    ):
        return None
    participant = record.get("participant_id", owner)
    person = storage.get(owner, "participant", participant)
    if (person is None and participant != owner) or (
        person is not None and (not person.get("active") or person.get("owner_id") != owner)
    ):
        return None
    return key


def bind(
    storage: Storage,
    owner: str,
    host: str,
    platform: str,
    actor_id: str,
    operation_id: str,
    confirmation: str,
    *,
    participant_id: str | None = None,
) -> dict[str, Any]:
    """Bind after owner verification; never silently move an actor between people.

    仅在 Owner 验证后绑定；旧调用默认 Participant=Owner，禁止静默合并真人。
    This is an administrative API, not proof supplied by a conversational model.
    这是管理接口，聊天模型提供的确认字符串本身不是身份认证凭据。
    """
    if not confirmation.strip():
        raise ValueError("Explicit owner approval of the stable platform identity is required")
    participant = owner if participant_id is None else participant_id
    if any(not v.strip() or len(v) > 200 for v in (owner, participant, operation_id)):
        raise ValueError("Valid owner, participant and operation identifiers are required")
    key = binding_key(host, platform, actor_id)
    # Preserve existing single-user receipt fingerprints without granting a new identity.
    # 保留单用户旧回执摘要；多用户绑定把 Participant 纳入去重，避免重放改绑。
    payload = fingerprint(
        [host, platform, actor_id] + ([] if participant == owner else [participant])
    )
    with storage.transaction():
        existing = storage.get(owner, "identity_binding", key)
        if existing and existing.get("participant_id", owner) != participant:
            raise ValueError(
                "Identity already belongs to another participant; explicit migration required"
            )
        receipt = storage.get(owner, "identity_receipt", operation_id)
        if receipt and receipt["fingerprint"] != payload:
            raise ValueError("Identity operation ID conflict")
        if receipt:
            return {"binding_id": receipt["binding_id"]}
        participant_record = storage.get(owner, "participant", participant)
        if participant_record and (
            not participant_record.get("active") or participant_record.get("owner_id") != owner
        ):
            raise ValueError("Participant is inactive; explicit reactivation is required")
        if participant_record is None:
            storage.put(
                owner,
                "participant",
                participant,
                {
                    "id": participant,
                    "owner_id": owner,
                    "active": True,
                    "created_at": now().isoformat(),
                },
            )
        storage.put(
            owner,
            "identity_binding",
            key,
            {
                **(existing or {}),
                "id": key,
                "owner_id": owner,
                "participant_id": participant,
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
