"""One authority for stable prefixes and whole, bounded runtime fragments."""

from collections.abc import Iterable
from typing import Any, get_args

from .compiler import compile_definition
from .context_models import (
    CompiledContext,
    ContextBudget,
    ContextFragment,
    ContextSlot,
    canonical,
    fingerprint,
)
from .rules import BASE_RULES, MODE_RULES

SLOTS: tuple[ContextSlot, ...] = get_args(ContextSlot)


class ContextAssembler:
    def __init__(self, budget: ContextBudget | None = None) -> None:
        self.budget = ContextBudget.model_validate((budget or ContextBudget()).model_dump())

    def assemble(
        self, compiled: CompiledContext, fragments: Iterable[ContextFragment]
    ) -> dict[str, Any]:
        # Revalidate mutable producer objects, including costs and fingerprints.
        compiled = CompiledContext.model_validate(compiled.model_dump(mode="json"))
        candidates = [ContextFragment.model_validate(f.model_dump(mode="json")) for f in fragments]
        if any(f.domain == "stable_character" for f in candidates):
            raise ValueError("Only the character compiler may supply the stable prefix")
        stable_chars = len(compiled.content)
        if (
            stable_chars > self.budget.stable_character
            or stable_chars + 2 > self.budget.total_chars
        ):
            raise ValueError("Context budget cannot hold the complete stable character prefix")
        temporary: dict[str, list[dict[str, Any]]] = {}
        stats: dict[str, dict[str, Any]] = {
            slot: {"included": 0, "excluded": 0, "chars": 0, "reasons": {}}
            for slot in SLOTS
            if slot != "stable_character"
        }
        candidates.sort(
            key=lambda f: (
                -f.priority,
                SLOTS.index(f.domain),
                fingerprint(canonical(f.model_dump(mode="json"))),
            )
        )
        for fragment in candidates:
            slot = fragment.domain
            record = fragment.model_dump(mode="json")
            proposed = [*temporary.get(slot, []), record]
            slot_chars = len(canonical(proposed))
            reason = None
            if slot_chars > getattr(self.budget, slot):
                reason = "slot_budget"
            elif (
                stable_chars + len(canonical({**temporary, slot: proposed}))
                > self.budget.total_chars
            ):
                reason = "total_budget"
            if reason:
                stats[slot]["excluded"] += 1
                reasons = stats[slot]["reasons"]
                reasons[reason] = reasons.get(reason, 0) + 1
            else:
                temporary[slot] = proposed
                stats[slot]["included"] += 1
                stats[slot]["chars"] = slot_chars
        temporary = {slot: temporary[slot] for slot in SLOTS if slot in temporary}
        temporary_text = canonical(temporary)
        total = stable_chars + len(temporary_text)
        return {
            "stable_prefix": compiled.content,
            "temporary": temporary,
            "context_limits": {
                **self.budget.model_dump(),
                "unit": "characters",
                "measurement": "stable prefix text plus canonical JSON temporary context",
                "partial": any(s["excluded"] for s in stats.values()),
                "full_records": "character_read / memory_recall / companion_control",
            },
            "context_diagnostics": {
                "slots": {
                    "stable_character": {"included": 1, "excluded": 0, "chars": stable_chars},
                    **stats,
                },
                "total_chars": total,
                "estimated_tokens": (total + 3) // 4,
                "stable_prefix_fingerprint": compiled.fingerprint,
                "character_version": compiled.character_version,
                "growth_version": compiled.growth_version,
                "compiler_version": compiled.compiler_version,
                "cache_key": fingerprint(
                    canonical(
                        [
                            compiled.character_id,
                            compiled.character_version,
                            compiled.growth_version,
                            compiled.compiler_version,
                        ]
                    )
                ),
                "memory_projection_fingerprint": fingerprint(
                    canonical(temporary.get("memory", []))
                ),
                "runtime_context_fingerprint": fingerprint(temporary_text),
            },
        }


def project_context(
    result: dict[str, Any],
    query: str,
    compiled: CompiledContext | None = None,
    budget: ContextBudget | None = None,
) -> dict[str, Any]:
    """Adapt legacy runtime records to fragments; never return their unbounded mirrors."""
    definition = result["definition"]
    compiled = compiled or compile_definition(definition)
    if compiled.character_id != definition["id"]:
        raise ValueError("Compiled prefix belongs to another character")
    state = result.get("state") or {}
    if state.get("character_id", compiled.character_id) != compiled.character_id:
        raise ValueError("Context state belongs to another character")
    fragments: list[ContextFragment] = []
    version = str(state.get("revision", 1))

    def add(
        slot: ContextSlot,
        payload: Any,
        priority: int = 50,
        authority: str = "TOOL_VERIFIED",
        source_version: str = version,
    ) -> None:
        fragments.append(
            ContextFragment.model_validate(
                {
                    "domain": slot,
                    "authority": authority,
                    "stability": "DYNAMIC",
                    "priority": priority,
                    "payload": payload,
                    "source_version": source_version,
                }
            )
        )

    stable_rules = {*BASE_RULES, *MODE_RULES.values()}
    rules = [rule for rule in result.get("rules", []) if rule not in stable_rules]
    if rules:
        add("state", {"rules": rules}, 100, "ADMIN_CONFIG")
    if state.get("relationship"):
        add("relationship", {"relationship": state["relationship"]}, 90)
    for event in state.get("relationship_history", []):
        add("relationship", {"history": event}, 35)
    for event in state.get("evolution", []):
        add("state", {"legacy_evolution": event, "unverified_evidence": True}, 40, "INFERRED")
    words = query.casefold().split()
    for memory in result.get("memories", []):
        if memory.get("character_id", compiled.character_id) != compiled.character_id:
            raise ValueError("Context memory belongs to another character")
        fields = (
            "id",
            "kind",
            "content",
            "source",
            "confidence",
            "importance",
            "created_at",
            "evidence_refs",
            "legacy_unverified",
        )
        projected = {key: memory[key] for key in fields if key in memory}
        relevance = sum(word in str(memory.get("content", "")).casefold() for word in words)
        add(
            "memory",
            projected,
            min(85, 60 + relevance),
            memory.get("authority", "INFERRED"),
            str(memory.get("id", "legacy")),
        )
    for fact in result.get("facts", []):
        if fact.get("character_id") != compiled.character_id:
            raise ValueError("Fact context scope mismatch")
        add(
            "memory",
            {"fact": {key: fact[key] for key in ("id", "semantic_key", "value", "confidence")}},
            80,
            fact.get("authority", "INFERRED"),
        )
    if result.get("expression_policy"):
        add("state", {"expression_policy": result["expression_policy"]}, 95, "ADMIN_CONFIG")
    for observation in result.get("perception", []):
        add("perception", observation, 65, "HOST_OBSERVED")
    if result.get("interaction"):
        add("state", {"interaction": result["interaction"]}, 60, "ADMIN_CONFIG")
    companion = result.get("companion") or {}
    if companion.get("character_id", compiled.character_id) != compiled.character_id:
        raise ValueError("Companion context belongs to another character")
    for key in ("affect", "embodiment", "settings", "attention", "expression_policy"):
        if key in companion:
            add("state", {key: companion[key]}, 75 if key == "mood" else 55)
    companion_slots: tuple[tuple[str, ContextSlot], ...] = (
        ("goals", "goals"),
        ("unfinished_topics", "open_loops"),
        ("habits", "life"),
    )
    for key, slot in companion_slots:
        for item in companion.get(key, []):
            add(slot, {key: item}, 55)
    if companion.get("life"):
        add("life", {"life": companion["life"]}, 50, "SIMULATED")
    for key, observation in companion.get("environment", {}).items():
        add("external_context", {key: observation}, 45)
    assembled = ContextAssembler(budget).assemble(compiled, fragments)
    for key in ("session_id", "ooc", "effective_mode"):
        if key in result:
            assembled[key] = result[key]
    return assembled
