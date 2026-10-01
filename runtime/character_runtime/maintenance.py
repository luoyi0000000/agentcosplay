"""One durable local maintenance cycle, callable by any host scheduler.

任何宿主调度器均可调用的唯一持久本地维护周期。
"""

from typing import TYPE_CHECKING, Any

from .models import Memory, new_id
from .operations import fingerprint
from .retrieval import normalize

if TYPE_CHECKING:
    from .runtime import Runtime


def run(runtime: "Runtime", character_id: str, operation_id: str) -> dict[str, Any]:
    """Execute a durable maintenance operation using existing idempotent receipts.

    使用现有幂等回执执行持久维护操作。
    """

    k = runtime.knowledge
    ops = k.operations(character_id)
    job_id = fingerprint(["maintenance", operation_id])
    ops.enqueue(job_id, "maintenance", {"character_id": character_id}, retry_safe=True)
    with runtime.storage.transaction():
        job = ops.claim(job_id)
        if job is None:
            previous = ops._get("operation", operation_id)
            return dict(previous["result"]) if previous else {"status": "pending-or-quarantined"}

        def apply() -> dict[str, Any]:
            runtime.advance(character_id)
            k.lifelike.advance(character_id)
            expired = archived = 0
            seen: dict[tuple[str, str, str], str] = {}
            for data in k.records("memory", character_id):
                memory = Memory.model_validate(data)
                if memory.status != "active":
                    continue
                if memory.expires_at and memory.expires_at <= k.clock():
                    memory.status = "expired"
                    k.memory._save(memory)
                    expired += 1
                    continue
                if memory.authority in ("USER_EXPLICIT", "USER_MANUAL", "ADMIN_CONFIG"):
                    continue
                key = (
                    normalize(memory.content),
                    memory.kind,
                    fingerprint([memory.source, sorted(memory.evidence_refs)]),
                )
                if key in seen:
                    memory.status = "archived"
                    memory.superseded_by = seen[key]
                    memory.consolidated_at = k.clock()
                    k.memory._save(memory)
                    archived += 1
                else:
                    seen[key] = memory.id
            # Reflection summarizes observed evidence, never acts as evidence itself.
            day = k.clock().date().isoformat()
            reflection_key = fingerprint([character_id, day, "reflection"])
            if runtime.storage.get(runtime.owner, "reflection_receipt", reflection_key) is None:
                events = [
                    e
                    for e in k.records("raw_event", character_id)
                    if e.get("validity") == "active"
                    and not e.get("legacy_unverified")
                    and e.get("source_kind") == "USER_DIRECT"
                    and e["timestamp"].startswith(day)
                ]
                if events:
                    narrative_id = new_id()
                    runtime.storage.put(
                        runtime.owner,
                        "narrative",
                        narrative_id,
                        {
                            "id": narrative_id,
                            "character_id": character_id,
                            "owner_id": runtime.owner,
                            "content": f"Daily reflection for {day}: "
                            f"{len(events)} direct observations retained.",
                            "source": "derived",
                            "authority": "MODEL_DERIVED",
                            "validity": "active",
                            "evidence_refs": [e["id"] for e in events[:20]],
                        },
                    )
                    runtime.storage.put(
                        runtime.owner,
                        "reflection_receipt",
                        reflection_key,
                        {"character_id": character_id, "narrative_id": narrative_id},
                    )
            return {"status": "committed", "expired": expired, "archived_duplicates": archived}

        result = ops.execute(
            operation_id, {"kind": "maintenance"}, apply, domain="maintenance", operation="UPDATE"
        )
        ops.finish(job_id, job["claim_id"], result)
        return result
