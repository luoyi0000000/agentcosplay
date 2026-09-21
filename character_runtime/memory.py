"""Memory lifecycle and authorization. All paths scope before returning content."""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from .characters import Characters
from .cognition import window
from .models import Candidate, Memory, new_id, now
from .persistence_models import RecallRequest
from .retrieval import score
from .safety import check_content
from .storage import Storage


class Memories:
    def __init__(
        self,
        storage: Storage,
        owner: str,
        characters: Characters,
        clock: Callable[[], datetime] = now,
    ) -> None:
        self.storage, self.owner, self.characters = storage, owner, characters
        self.clock = clock

    def _save(self, memory: Memory) -> Memory:
        checked = Memory.model_validate(memory.model_dump())
        if checked.owner != self.owner:
            raise ValueError("Memory owner mismatch")
        self.storage.put(self.owner, "memory", checked.id, checked.model_dump(mode="json"))
        return checked

    def owned(self, character_id: str, memory_id: str) -> Memory:
        self.characters.get(character_id)
        data = self.storage.get(self.owner, "memory", memory_id)
        if data is None or data["character_id"] != character_id:
            raise KeyError("Memory not found in this character")
        return Memory.model_validate(data)

    def store(
        self,
        character_id: str,
        candidate: Candidate,
        session_id: str | None = None,
        *,
        turn_id: str | None = None,
        confirmed: bool = False,
    ) -> Memory:
        self.characters.get(character_id)
        check_content(candidate.content, confirmed=confirmed)
        candidate = Candidate.model_validate(candidate.model_dump())
        if candidate.kind == "real_user":
            raise ValueError("Use explicit promotion to store real-user facts")
        if candidate.source == "simulated_life" and candidate.kind not in (
            "short_term",
            "character_long_term",
        ):
            raise ValueError("Simulated life cannot represent shared or real-user experiences")
        kind = candidate.kind
        if kind == "character_long_term" and candidate.importance < 0.7:
            kind = "short_term"
        ttl = candidate.ttl_seconds
        if kind == "session":
            ttl = min(ttl or 86400, 86400)
        elif kind == "short_term":
            ttl = min(ttl or 7 * 86400, 30 * 86400)
        return self._save(
            Memory(
                owner=self.owner,
                character_id=character_id,
                kind=kind,
                session_id=session_id if kind == "session" else None,
                turn_id=turn_id,
                created_at=self.clock(),
                legacy_unverified=False,
                content=candidate.content,
                importance=candidate.importance,
                confidence=candidate.confidence,
                source=candidate.source,
                expires_at=self.clock() + timedelta(seconds=ttl) if ttl else None,
            )
        )

    def recall(
        self,
        character_id: str,
        query: str = "",
        *,
        session_id: str | None = None,
        real: bool = False,
        limit: int = 20,
        relationship: str = "",
        current_topic: str = "",
        unfinished_topics: list[str] | None = None,
        active_goals: list[str] | None = None,
        include_archived: bool = False,
        request: RecallRequest | None = None,
    ) -> list[Memory]:
        self.characters.get(character_id)
        if not 1 <= limit <= 100 or len(query) > 4000:
            raise ValueError("Recall limit must be 1..100 and query at most 4000 characters")
        topics = tuple((unfinished_topics or [])[:8])
        goals = tuple((active_goals or [])[:8])
        if any(len(text) > 4000 for text in (relationship, current_topic, *topics, *goals)):
            raise ValueError("Recall hints must be at most 4000 characters each")
        clock = self.clock()
        retrieval_query = " ".join(
            (
                query,
                current_topic[:800],
                relationship[:400],
                *[text[:160] for text in topics],
                *[text[:160] for text in goals],
            )
        )[:8000]
        with self.storage.transaction():
            candidates = self.storage.memory_candidates(
                self.owner,
                character_id,
                retrieval_query,
                session_id=session_id,
                real=real,
                at=clock,
                include_archived=include_archived,
            )
            if request is not None:
                start, end = window(request, clock)
                kind = {
                    "RELATIONSHIP": "relationship",
                    "USER_FACT": "real_user",
                    "USER_PREFERENCE": "real_user",
                }.get(request.intent)
                if kind == "real_user" and not real:
                    raise ValueError("Owner profile recall requires real=True")
                if start or end or request.semantic_key or kind or request.intent == "RECENT":
                    candidates = [
                        (r, 0.0)
                        for r in self.storage.memory_window(
                            self.owner,
                            character_id,
                            start=start,
                            end=end,
                            session_id=session_id,
                            real=real,
                            include_archived=request.include_archived,
                            semantic_key=request.semantic_key,
                            kind=kind,
                            limit=request.limit,
                        )
                    ]
                if request.intent == "SIMULATED_LIFE":
                    candidates = [
                        (r, rank) for r, rank in candidates if r.get("source") == "simulated_life"
                    ]
                limit = request.limit
            ranked: list[tuple[float, Memory]] = []
            for data, fts in candidates:
                memory = Memory.model_validate(data)
                if memory.owner != self.owner or memory.character_id != character_id:
                    continue
                parts = score(
                    memory,
                    query,
                    clock,
                    fts=fts,
                    relationship=relationship,
                    current_topic=current_topic,
                    unfinished_topics=topics,
                    active_goals=goals,
                )
                ranked.append((sum(parts.values()), memory))
            ranked.sort(key=lambda item: (item[0], item[1].created_at, item[1].id), reverse=True)
            # Retrieval is read-only: it is neither injection nor useful independent evidence.
            return [memory for _, memory in ranked[:limit]]

    def modify(
        self,
        character_id: str,
        memory_id: str,
        *,
        content: str | None = None,
        expires_at: datetime | None = None,
        confirmed: bool = False,
    ) -> Memory:
        with self.storage.transaction():
            m = self.owned(character_id, memory_id)
            if m.status == "forgotten":
                raise ValueError("Forgotten memories cannot be restored")
            if m.kind == "real_user" and content is not None:
                raise ValueError("Store a new corrected character memory and explicitly promote it")
            if content is not None:
                check_content(content, confirmed=confirmed)
            changes: dict[str, Any] = {"content": content} if content is not None else {}
            if expires_at is not None:
                changes["expires_at"] = expires_at
            updated = Memory.model_validate(m.model_dump() | changes)
            if expires_at is not None:
                updated.status = "expired" if expires_at <= self.clock() else "active"
            if content is not None and content != m.content:
                updated.turn_id = None
                self._invalidate_evidence(character_id, {memory_id})
            return self._save(updated)

    def promote(self, character_id: str, memory_id: str, *, confirmation: str) -> Memory:
        if not confirmation.strip() or len(confirmation) > 2000:
            raise ValueError("Explicit user confirmation of truth and storage is required")
        with self.storage.transaction():
            m = self.owned(character_id, memory_id)
            if m.legacy_unverified or not m.evidence_refs:
                raise ValueError("Promotion requires new verified RawEvent evidence")
            if m.source == "simulated_life":
                raise ValueError("Simulated life cannot be promoted to real-user facts")
            for data in self.storage.memory_related(self.owner, character_id, m.id):
                if data.get("promoted_from") == m.id and data.get("status") == "active":
                    return Memory.model_validate(data)
            if m.status != "active" or (m.expires_at and m.expires_at <= self.clock()):
                raise ValueError("Only active memories may be promoted")
            if m.kind == "real_user":
                raise ValueError("Memory is already real-user memory")
            data = m.model_dump() | {
                "id": new_id(),
                "kind": "real_user",
                "session_id": None,
                "promoted_from": m.id,
                "confirmation": "User confirmed truth and storage in OOC",
                "created_at": self.clock(),
                "expires_at": None,
                "last_access": None,
            }
            # Move into the stricter namespace; no duplicate body can leak via character export.
            self.forget(character_id, memory_id)
            return self._save(Memory.model_validate(data))

    def forget(self, character_id: str, memory_id: str) -> None:
        with self.storage.transaction():
            selected = self.owned(character_id, memory_id)
            affected = {memory_id}
            if selected.promoted_from:
                affected.add(selected.promoted_from)
            records = self.storage.memory_related(
                self.owner, character_id, selected.promoted_from or memory_id
            )
            if not any(d["id"] == selected.id for d in records):
                records.append(selected.model_dump())
            for d in records:
                if d.get("promoted_from") in affected:
                    affected.add(d["id"])
            for d in records:
                if d["id"] in affected:
                    d.update(
                        status="forgotten",
                        content="",
                        source="",
                        confirmation="",
                        promoted_from=None,
                        observation_turn_ids=[],
                    )
                    self._save(Memory.model_validate(d))
            self._invalidate_evidence(character_id, affected)

    def _invalidate_evidence(self, character_id: str, affected: set[str]) -> None:
        state = self.characters.state(character_id)
        state.evolution = [e for e in state.evolution if not affected.intersection(e.evidence_ids)]
        state.relationship_history = [
            h
            for h in state.relationship_history
            if not affected.intersection(str(h.get("evidence_ids", "")).split(","))
        ]
        state.revision += 1
        self.characters.save_state(state)
        # Erase derived companion bodies as well, so forget/promotion cannot leak through context.
        from .companion import Companion
        from .companion_models import Mood

        companion = Companion(self.storage, self.owner, self.characters)
        if self.storage.get(self.owner, "companion", character_id) is not None:
            record = companion.get(character_id)
            if affected.intersection(record.mood.evidence_ids):
                record.mood = Mood()
            removed_goals = {g.id for g in record.goals if affected.intersection(g.evidence_ids)}
            pending = record.pending_decision
            if pending and pending.topic_id in {"goal:" + key for key in removed_goals}:
                # Keep the reservation as a tombstone: delivery may already have happened.
                pending.topic, pending.reason, pending.context = "", "Evidence removed", {}
                pending.should_contact = False
            record.goals = [g for g in record.goals if not affected.intersection(g.evidence_ids)]
            record.habits = [h for h in record.habits if not affected.intersection(h.evidence_ids)]
            companion._save(record)
