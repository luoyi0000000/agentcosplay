"""Evidence-gated knowledge commits. Host proposals are never database authority."""

from collections.abc import Callable
from datetime import datetime
from typing import Any

from .characters import Characters
from .cognition import classify_conflict
from .growth import Growth
from .knowledge_models import (
    EventBatch,
    FactRecord,
    MemoryMutation,
    RawEvent,
    TurnProposal,
)
from .lifelike import Lifelike
from .memory import Memories
from .models import Candidate, Memory, Session, new_id, now
from .operations import Operations, fingerprint
from .persistence_models import GrowthCandidate
from .relationship import Relationships
from .safety import SENSITIVE, check_content
from .storage import Storage


class Knowledge:
    def __init__(
        self,
        storage: Storage,
        owner: str,
        characters: Characters,
        memory: Memories,
        clock: Callable[[], datetime] = now,
    ) -> None:
        self.storage, self.owner = storage, owner
        self.characters, self.memory, self.clock = characters, memory, clock
        self.relationship = Relationships(self)
        self.growth = Growth(self)
        self.lifelike = Lifelike(self)

    def operations(self, character_id: str) -> Operations:
        return Operations(self.storage, self.owner, character_id, self.clock)

    def scope(self, session_id: str, *, ooc: bool = False) -> Session:
        value = self.storage.get(self.owner, "session", session_id)
        if value is None:
            raise KeyError("Session not found")
        session = Session.model_validate(value)
        if (
            not session.identity_verified
            or session.character_id is None
            or (ooc and not session.ooc)
        ):
            raise ValueError("An active character and explicit OOC for edits are required")
        if session.identity_binding:
            binding = self.storage.get(self.owner, "identity_binding", session.identity_binding)
            if not binding or not binding.get("active"):
                raise ValueError("Identity binding is revoked")
        self.characters.get(session.character_id)
        return session

    def records(self, collection: str, character_id: str) -> list[dict[str, Any]]:
        self.characters.get(character_id)
        # ponytail: owner-local scan for new domains; add SQL indexes when volume warrants it.
        return [
            r
            for r in self.storage.list(self.owner, collection)
            if r.get("character_id") == character_id
        ]

    def evidence(self, character_id: str, references: list[str]) -> list[RawEvent]:
        if not references or len(references) != len(set(references)):
            raise ValueError("Distinct RawEvent evidence references are required")
        events = []
        for reference in references:
            value = self.storage.get(self.owner, "raw_event", reference)
            if value is None:
                raise ValueError("Evidence must reference an existing RawEvent, never a narrative")
            event = RawEvent.model_validate(value)
            if (
                event.owner_id != self.owner
                or event.character_id != character_id
                or event.validity != "active"
                or event.legacy_unverified
            ):
                raise ValueError("Evidence is forgotten or outside the character namespace")
            events.append(event)
        return events

    def ingest(self, batch: EventBatch) -> dict[str, Any]:
        with self.storage.transaction():
            session = self.scope(batch.session_id)
            assert session.character_id is not None
            character_id = session.character_id
            ops = self.operations(character_id)

            def apply() -> dict[str, Any]:
                ids = []
                for incoming in batch.events:
                    if incoming.source_kind == "USER_DIRECT" and (
                        incoming.actor_id or incoming.platform or incoming.host
                    ):
                        from .identity import resolve

                        binding = resolve(
                            self.storage,
                            self.owner,
                            incoming.host,
                            incoming.platform,
                            incoming.actor_id,
                        )
                        if binding is None or binding != session.identity_binding:
                            raise ValueError(
                                "Direct platform evidence requires a matching "
                                "verified identity binding"
                            )
                    check_content(
                        incoming.model_dump_json(),
                        sensitive=incoming.sensitivity == "sensitive",
                        confirmed=session.ooc and bool(batch.sensitive_confirmation.strip()),
                    )
                    key = fingerprint([character_id, incoming.source_id, incoming.source_event_id])
                    old = self.storage.get(self.owner, "raw_event", key)
                    digest = fingerprint(incoming.model_dump(mode="json"))
                    if old is not None:
                        # Tombstone digests prevent retries from resurrecting content.
                        original = self.storage.get(self.owner, "event_digest", key)
                        if not original or original["fingerprint"] != digest:
                            raise ValueError("Source event ID reused with different content")
                    else:
                        event = RawEvent(
                            **(
                                incoming.model_dump()
                                | {
                                    "sensitivity": "sensitive"
                                    if SENSITIVE.search(incoming.content)
                                    else incoming.sensitivity
                                }
                            ),
                            id=key,
                            owner_id=self.owner,
                            character_id=character_id,
                            session_id=session.id,
                            received_at=self.clock(),
                        )
                        self.storage.put(
                            self.owner, "raw_event", key, event.model_dump(mode="json")
                        )
                        self.storage.put(
                            self.owner,
                            "event_digest",
                            key,
                            {"character_id": character_id, "fingerprint": digest},
                        )
                    ids.append(key)
                checkpoint = None
                if batch.checkpoint_revision is not None:
                    if len({e.source_id for e in batch.events}) != 1:
                        raise ValueError("A checkpoint batch must contain exactly one source")
                    last = batch.events[-1]
                    checkpoint = ops.checkpoint(
                        last.source_id,
                        last.source_event_id,
                        last.timestamp,
                        expected_revision=batch.checkpoint_revision,
                    )
                return {"event_ids": ids, "retention": "RAW_ONLY", "checkpoint": checkpoint}

            return ops.execute(
                batch.operation_id,
                batch.model_dump(mode="json"),
                apply,
                domain="ingestion",
                operation="CREATE",
            )

    def commit(self, session_id: str, proposal: TurnProposal) -> dict[str, Any]:
        with self.storage.transaction():
            session = self.scope(session_id)
            assert session.character_id is not None
            cid = session.character_id
            ops = self.operations(cid)

            def apply() -> dict[str, Any]:
                memory_ids, fact_ids, narrative_ids, retention = [], [], [], []
                for p in proposal.memory_proposals:
                    events = self.evidence(cid, p.evidence_refs)
                    sensitive = any(e.sensitivity == "sensitive" for e in events)
                    confirmed = session.ooc and bool(p.sensitive_confirmation.strip())
                    check_content(p.content, sensitive=sensitive, confirmed=confirmed)
                    if p.kind == "real_user":
                        raise ValueError(
                            "Use OOC FactProposal or explicit memory promotion for owner facts"
                        )
                    if not p.explicit_remember and (p.importance < 0.3 or p.confidence < 0.5):
                        retention.append("RAW_ONLY")
                        continue
                    kinds = {e.source_kind for e in events}
                    source = (
                        "simulated_life"
                        if kinds & {"SIMULATED", "PLANNED"}
                        else "reference:" + ",".join(sorted(kinds))
                        if kinds - {"USER_DIRECT", "ASSISTANT_VISIBLE"}
                        else "conversation"
                    )
                    if source == "simulated_life" and p.kind == "relationship":
                        raise ValueError("Simulation and plans cannot establish user relationships")
                    if p.domain == "project":
                        mid = new_id()
                        self.storage.put(
                            self.owner,
                            "project_memory",
                            mid,
                            {
                                "id": mid,
                                "character_id": cid,
                                "owner_id": self.owner,
                                "content": p.content,
                                "evidence_refs": p.evidence_refs,
                                "authority": "MODEL_DERIVED",
                                "source": source,
                                "validity": "active",
                                "sensitivity": "sensitive" if sensitive else "private",
                            },
                        )
                        memory_ids.append(mid)
                        retention.append("PROJECT_KNOWLEDGE")
                        continue
                    # Only cosmetic normalization with the same evidence is duplicate.
                    effective_kind = (
                        "character_long_term"
                        if p.explicit_remember
                        else "short_term"
                        if p.kind == "character_long_term" and p.importance < 0.7
                        else p.kind
                    )
                    duplicate = next(
                        (
                            m
                            for m in self.records("memory", cid)
                            if m.get("status") == "active"
                            and classify_conflict(m.get("content", ""), p.content)
                            in ("EXACT_DUPLICATE", "NEAR_DUPLICATE")
                            and m.get("kind") == effective_kind
                            and (not p.explicit_remember or m.get("durability") == "explicit")
                            and set(m.get("evidence_refs", [])) == set(p.evidence_refs)
                        ),
                        None,
                    )
                    if duplicate:
                        memory_ids.append(duplicate["id"])
                        retention.append(classify_conflict(duplicate["content"], p.content))
                        continue
                    candidate = Candidate(
                        **p.model_dump(include=set(Candidate.model_fields)) | {"source": source}
                    )
                    memory = self.memory.store(
                        cid,
                        candidate,
                        session.id,
                        turn_id=proposal.operation_id,
                        confirmed=confirmed,
                    )
                    memory.evidence_refs = p.evidence_refs
                    memory.event_at = max(e.timestamp for e in events)
                    memory.semantic_key = p.semantic_key
                    memory.durability = (
                        "explicit"
                        if p.explicit_remember
                        else (
                            "temporary"
                            if memory.kind in ("session", "short_term")
                            else "persistent"
                        )
                    )
                    if p.explicit_remember:
                        if not any(e.source_kind == "USER_DIRECT" for e in events):
                            raise ValueError("Explicit remember requires direct user evidence")
                        memory.kind, memory.expires_at, memory.session_id = (
                            "character_long_term",
                            None,
                            None,
                        )
                        memory.authority = "USER_EXPLICIT"
                    memory.authority = (
                        "SIMULATED" if source == "simulated_life" else "MODEL_DERIVED"
                    )
                    memory.sensitivity = "sensitive" if sensitive else "private"
                    if p.explicit_remember:
                        memory.authority = "USER_EXPLICIT"
                    self.memory._save(memory)
                    memory_ids.append(memory.id)
                    retention.append("MEMORY_CANDIDATE")
                for fp in proposal.fact_proposals:
                    events = self.evidence(cid, fp.evidence_refs)
                    if any(e.source_kind not in {"USER_DIRECT", "TOOL_RESULT"} for e in events):
                        raise ValueError(
                            "References, media, plans and simulations cannot establish Facts"
                        )
                    confirmed = session.ooc and bool(fp.explicit_confirmation.strip())
                    if fp.subject == "owner" and (
                        not confirmed or any(e.source_kind != "USER_DIRECT" for e in events)
                    ):
                        raise ValueError(
                            "Owner facts require direct user evidence and OOC storage confirmation"
                        )
                    sensitive = any(e.sensitivity == "sensitive" for e in events)
                    check_content(fp.value, sensitive=sensitive, confirmed=confirmed)
                    if not any(fp.value in e.content for e in events):
                        raise ValueError("P0 facts must preserve an exact evidence excerpt")
                    active = [
                        f
                        for f in self.records("fact", cid)
                        if f["validity"] == "active"
                        and f["subject"] == fp.subject
                        and f["semantic_key"] == fp.semantic_key
                    ]
                    old = None
                    if fp.operation == "SUPERSEDE":
                        if not session.ooc or not fp.allowlist_id or not fp.target_id:
                            raise ValueError(
                                "Supersession requires OOC and an issued target allowlist"
                            )
                        ops.consume_allowlist(
                            fp.allowlist_id,
                            "SUPERSEDE",
                            [fp.target_id],
                            session_id=session.id,
                            collection="fact",
                        )
                        old = next((f for f in active if f["id"] == fp.target_id), None)
                        if old is None:
                            raise ValueError("Supersession must target the active semantic slot")
                    elif active:
                        raise ValueError(
                            "Fact slot already exists; use SUPERSEDE with a fresh allowlist"
                        )
                    elif fp.target_id or fp.allowlist_id:
                        raise ValueError("CREATE cannot carry a mutation target")
                    fact = FactRecord(
                        owner_id=self.owner,
                        character_id=cid,
                        semantic_key=fp.semantic_key,
                        subject=fp.subject,
                        value=fp.value,
                        evidence_refs=fp.evidence_refs,
                        confidence=fp.confidence,
                        authority="USER_EXPLICIT" if confirmed else "HOST_OBSERVED",
                        sensitivity="sensitive" if sensitive else "private",
                        valid_from=self.clock(),
                        created_at=self.clock(),
                        updated_at=self.clock(),
                    )
                    if old:
                        old.update(
                            validity="superseded",
                            valid_to=self.clock().isoformat(),
                            superseded_by=fact.id,
                            updated_at=self.clock().isoformat(),
                        )
                        self.storage.put(self.owner, "fact", old["id"], old)
                    self.storage.put(self.owner, "fact", fact.id, fact.model_dump(mode="json"))
                    fact_ids.append(fact.id)
                for np in proposal.narrative_proposals:
                    events = self.evidence(cid, np.evidence_refs)
                    check_content(
                        np.content, sensitive=any(e.sensitivity == "sensitive" for e in events)
                    )
                    nid = new_id()
                    self.storage.put(
                        self.owner,
                        "narrative",
                        nid,
                        {
                            "id": nid,
                            "owner_id": self.owner,
                            "character_id": cid,
                            "content": np.content,
                            "source": "derived",
                            "authority": "MODEL_DERIVED",
                            "evidence_refs": np.evidence_refs,
                            "validity": "active",
                        },
                    )
                    narrative_ids.append(nid)
                for affect_effect in proposal.affect_effects:
                    self.lifelike.affect(cid, affect_effect)
                if proposal.companion_update:
                    from .companion import Companion

                    change = proposal.companion_update
                    if change.settings or change.mood:
                        raise ValueError(
                            "Settings require OOC; use affect_effects for automatic emotion"
                        )
                    companion = Companion(self.storage, self.owner, self.characters, self.clock)
                    previous = companion.get(cid)
                    for item in (change.goal, change.habit, change.topic):
                        if item and not item.evidence_ids:
                            raise ValueError(
                                "Automatic goals, habits and topics require "
                                "direct RawEvent evidence"
                            )
                    modifying = any(
                        item is not None and any(old.id == item.id for old in records)
                        for item, records in (
                            (change.goal, previous.goals),
                            (change.habit, previous.habits),
                            (change.topic, previous.topics),
                        )
                    )
                    if modifying:
                        if not proposal.companion_allowlist_id:
                            raise ValueError(
                                "Updating companion records requires an issued allowlist"
                            )
                        ops.consume_allowlist(
                            proposal.companion_allowlist_id,
                            "UPDATE",
                            [cid],
                            collection="companion",
                            session_id=session_id,
                        )
                    check_content(change.model_dump_json())
                    companion.update(cid, change)
                for effect in proposal.relationship_effects:
                    self.relationship.effect(cid, effect)
                growth_results = []
                for index, draft in enumerate(proposal.growth_proposals):
                    growth_candidate = GrowthCandidate(
                        **draft.model_dump(),
                        character_id=cid,
                        id=fingerprint([cid, proposal.operation_id, index]),
                    )
                    growth_results.append(self.growth.propose(growth_candidate))
                relationship = self.relationship.get(cid)
                relationship.last_interaction = self.clock()
                self.relationship.save(relationship)
                state = self.characters.state(cid)
                state.turn_count += 1
                state.revision += 1
                self.characters.save_state(state)
                return {
                    "character_id": cid,
                    "memory_ids": memory_ids,
                    "fact_ids": fact_ids,
                    "narrative_ids": narrative_ids,
                    "growth_results": growth_results,
                    "retention": retention,
                    "turn_count": state.turn_count,
                    "state_revision": state.revision,
                }

            return ops.execute(
                proposal.operation_id,
                {"session_id": session_id, **proposal.model_dump(mode="json")},
                apply,
                domain="knowledge",
                operation="CREATE",
                target_ids=[p.target_id for p in proposal.fact_proposals if p.target_id],
                evidence_refs=sorted(
                    {
                        ref
                        for group in (
                            proposal.memory_proposals,
                            proposal.fact_proposals,
                            proposal.narrative_proposals,
                        )
                        for item in group
                        for ref in item.evidence_refs
                    }
                ),
            )

    def mutate(self, request: MemoryMutation) -> dict[str, Any]:
        with self.storage.transaction():
            session = self.scope(request.session_id, ooc=True)
            assert session.character_id is not None
            cid = session.character_id
            ops = self.operations(cid)

            def apply() -> dict[str, Any]:
                action = {"MODIFY": "CORRECT", "PROMOTE": "UPDATE"}.get(
                    request.action, request.action
                )
                ops.consume_allowlist(
                    request.allowlist_id,
                    action,
                    [request.memory_id],
                    session_id=session.id,
                    collection="memory",
                )
                memory = self.memory.owned(cid, request.memory_id)
                conflict = "UNRELATED"
                if request.action == "FORGET":
                    self.forget(cid, memory)
                    return {"forgotten": memory.id}
                if request.action == "ARCHIVE":
                    memory.status = "archived"
                    self.memory._save(memory)
                elif request.action == "MODIFY":
                    if not request.content:
                        raise ValueError("Correction requires content and RawEvent evidence")
                    conflict = classify_conflict(
                        memory.content, request.content, proposed="CORRECTION"
                    )
                    events = self.evidence(cid, request.evidence_refs)
                    check_content(
                        request.content,
                        sensitive=any(e.sensitivity == "sensitive" for e in events),
                        confirmed=bool(request.confirmation.strip()),
                    )
                    memory = self.memory.modify(
                        cid,
                        memory.id,
                        content=request.content,
                        confirmed=bool(request.confirmation.strip()),
                    )
                    memory.evidence_refs = request.evidence_refs
                    memory.legacy_unverified = False
                    memory.authority = "USER_MANUAL"
                    self.memory._save(memory)
                elif request.action == "PROMOTE":
                    if memory.legacy_unverified:
                        raise ValueError(
                            "Legacy memory needs new direct RawEvent evidence before promotion"
                        )
                    events = self.evidence(cid, memory.evidence_refs)
                    if any(e.source_kind != "USER_DIRECT" for e in events):
                        raise ValueError("Only direct user evidence may be promoted")
                    check_content(
                        memory.content,
                        sensitive=memory.sensitivity == "sensitive",
                        confirmed=bool(request.confirmation.strip()),
                    )
                    memory = self.memory.promote(cid, memory.id, confirmation=request.confirmation)
                return {"memory_id": memory.id, "status": memory.status, "conflict": conflict}

            return ops.execute(
                request.operation_id,
                request.model_dump(mode="json"),
                apply,
                domain="memory",
                operation=request.action,
                target_ids=[request.memory_id],
                authority="USER_MANUAL",
                evidence_refs=request.evidence_refs,
            )

    def forget(self, character_id: str, memory: Memory) -> None:
        """Erase evidence-linked bodies together; preserve digest-only receipts and tombstones."""
        refs = set(memory.evidence_refs)
        self.storage.delete(self.owner, "imported_snapshot", character_id)
        self.memory.forget(character_id, memory.id)
        for ref in refs:
            value = self.storage.get(self.owner, "raw_event", ref)
            if value and value.get("character_id") == character_id:
                value.update(content="", validity="forgotten", actor_id="", source_ref="")
                self.storage.put(self.owner, "raw_event", ref, value)
        self.storage.delete(self.owner, "migration_original", "memory:" + memory.id)
        invalid_growth = set()
        invalid_prototypes = set()
        for collection in ("growth_candidate", "growth_version", "perception", "visual_prototype"):
            for record in self.records(collection, character_id):
                if refs.intersection(record.get("evidence_refs", [])):
                    if collection == "growth_version":
                        invalid_growth.add(record["id"])
                    if collection == "visual_prototype":
                        invalid_prototypes.add(record["id"])
                    self.storage.delete(self.owner, collection, record["id"])
        for perception in self.records("perception", character_id):
            if perception.get("prototype_id") in invalid_prototypes:
                perception.update(recognized="UNKNOWN", prototype_id=None)
                self.storage.put(self.owner, "perception", perception["id"], perception)
        changed = True
        while changed:
            changed = False
            for version in self.records("growth_version", character_id):
                if version.get("previous_version") in invalid_growth:
                    invalid_growth.add(version["id"])
                    self.storage.delete(self.owner, "growth_version", version["id"])
                    changed = True
        from .companion import Companion
        from .companion_models import Mood

        companion = Companion(self.storage, self.owner, self.characters, self.clock)
        companion_state = companion.get(character_id)
        removed_topics = {
            "topic:" + t.id for t in companion_state.topics if refs.intersection(t.evidence_ids)
        }
        removed_goals = {
            "goal:" + g.id for g in companion_state.goals if refs.intersection(g.evidence_ids)
        }
        companion_state.goals = [
            g for g in companion_state.goals if not refs.intersection(g.evidence_ids)
        ]
        companion_state.habits = [
            h for h in companion_state.habits if not refs.intersection(h.evidence_ids)
        ]
        companion_state.topics = [
            t for t in companion_state.topics if not refs.intersection(t.evidence_ids)
        ]
        if refs.intersection(companion_state.mood.evidence_ids):
            companion_state.mood = Mood(updated_at=self.clock())
        pending = companion_state.pending_decision
        if pending and pending.topic_id in removed_goals | removed_topics:
            pending.topic, pending.reason, pending.context = "", "Evidence forgotten", {}
            companion._invalidate_pending(companion_state, "evidence_forgotten")
        companion._save(companion_state)
        head = self.storage.get(self.owner, "growth_head", character_id)
        if head and head.get("version") in invalid_growth:
            self.storage.delete(self.owner, "growth_head", character_id)
            self.storage.delete(self.owner, "compiled_lkg", character_id)
        for compiled in self.records("compiled_context", character_id):
            if compiled.get("growth_version") in invalid_growth:
                from .context_models import canonical
                from .context_models import fingerprint as context_fingerprint

                key = context_fingerprint(
                    canonical(
                        [
                            character_id,
                            compiled["character_version"],
                            compiled["growth_version"],
                            compiled["compiler_version"],
                        ]
                    )
                )
                self.storage.delete(self.owner, "compiled_context", key)
        relationship = self.relationship.get(character_id)
        if refs.intersection(relationship.evidence_refs):
            relationship.learned = relationship.anchor.model_copy(deep=True)
            relationship.closeness = relationship.friction = 0
            relationship.evidence_refs = []
            self.relationship.save(relationship)
        lifelike = self.lifelike.get(character_id)
        if refs.intersection(lifelike.affect.evidence_refs):
            from .lifelike_models import AffectState

            lifelike.affect = AffectState(updated_at=self.clock())
            self.lifelike.save(lifelike)
        for collection in ("memory", "fact", "narrative", "project_memory"):
            for record in self.records(collection, character_id):
                if not refs.intersection(record.get("evidence_refs", [])):
                    continue
                if collection == "memory":
                    self.memory.forget(character_id, record["id"])
                else:
                    record.update(validity="forgotten")
                    record["value" if collection == "fact" else "content"] = ""
                    self.storage.put(self.owner, collection, record["id"], record)
