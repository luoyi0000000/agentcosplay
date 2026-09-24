"""Private-safe integrity statistics for an authenticated owner's character.

认证 Owner 的角色完整性统计，不泄漏私人正文。
"""

from datetime import datetime
from typing import Any

from .compiler import read_compiled
from .context_models import ContextBudget
from .knowledge import Knowledge
from .models import now
from .providers import Observation


def diagnose(knowledge: Knowledge, character_id: str) -> dict[str, Any]:
    """Report integrity diagnostics without returning private record bodies.

    返回完整性诊断，不返回私人记录正文。
    """

    knowledge.characters.get(character_id)
    counts: dict[str, int] = {}
    invalid_evidence = stale_jobs = invalid_records = orphan_records = legacy_records = 0
    known = {d["id"] for d in knowledge.storage.list(knowledge.owner, "definition")}
    for collection in ("raw_event", "fact", "memory", "narrative", "project_memory", "job"):
        try:
            all_records = knowledge.storage.list(knowledge.owner, collection)
            orphan_records += sum(r.get("character_id") not in known for r in all_records)
            records = [r for r in all_records if r.get("character_id") == character_id]
        except (ValueError, TypeError):
            invalid_records += 1
            continue
        counts[collection] = len(records)
        for record in records:
            refs = record.get("evidence_refs", [])
            legacy_records += bool(record.get("legacy_unverified"))
            if (
                refs
                and not record.get("legacy_unverified")
                and record.get("validity", record.get("status", "active")) == "active"
            ):
                try:
                    knowledge.evidence(character_id, refs)
                except (ValueError, KeyError):
                    invalid_evidence += 1
            if collection == "job" and record.get("status") == "running":
                try:
                    stale_jobs += datetime.fromisoformat(record["lease_until"]) <= now()
                except (KeyError, ValueError, TypeError):
                    invalid_records += 1
    compiled = read_compiled(knowledge.storage, knowledge.owner, character_id)
    pending = knowledge.storage.get(knowledge.owner, "companion", character_id) or {}
    fresh_providers = invalid_providers = 0
    for value in pending.get("observations", {}).values():
        try:
            fresh_providers += Observation.model_validate(value).fresh(knowledge.clock())
        except ValueError:
            invalid_providers += 1
    return {
        "schema_version": getattr(knowledge.storage, "SCHEMA_VERSION", None),
        "record_counts": counts,
        "invalid_evidence_records": invalid_evidence,
        "invalid_record_collections": invalid_records,
        "stale_jobs": stale_jobs,
        "orphan_records": orphan_records,
        "legacy_unverified_records": legacy_records,
        "fresh_providers": fresh_providers,
        "invalid_providers": invalid_providers,
        "context_budget": ContextBudget().model_dump(),
        "compiled_fingerprint": compiled.fingerprint if compiled else None,
        "pending_proactive": bool(pending.get("pending_decision")),
        # Owner-wide warnings may identify private records; scoped diagnostics omit them.
        # Owner 级迁移告警可能识别私人记录，单轮诊断不得读取。
        "migration_warnings": (
            None
            if getattr(knowledge.storage, "actor", None)
            else len(knowledge.storage.list(knowledge.owner, "migration_warning"))
        ),
    }
