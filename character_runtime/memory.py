"""Memory lifecycle and authorization. All paths scope before returning content."""

from datetime import datetime, timedelta
from typing import Any

from .characters import Characters
from .models import Candidate, Memory, new_id, now
from .storage import Storage


class Memories:
    def __init__(self, storage: Storage, owner: str, characters: Characters) -> None:
        self.storage, self.owner, self.characters = storage, owner, characters

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
    ) -> Memory:
        self.characters.get(character_id)
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
                content=candidate.content,
                importance=candidate.importance,
                confidence=candidate.confidence,
                source=candidate.source,
                expires_at=now() + timedelta(seconds=ttl) if ttl else None,
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
    ) -> list[Memory]:
        self.characters.get(character_id)
        if not 1 <= limit <= 100 or len(query) > 4000:
            raise ValueError("Recall limit must be 1..100 and query at most 4000 characters")
        with self.storage.transaction():
            found: list[Memory] = []
            clock = now()
            # ponytail: O(n) per-owner scan; add storage-side indexed retrieval at larger scale.
            for data in self.storage.list(self.owner, "memory"):
                m = Memory.model_validate(data)
                if m.owner != self.owner:
                    continue
                if m.character_id != character_id and not (
                    m.scope == "shared" and character_id in m.shared_with
                ):
                    continue
                if (m.kind == "real_user") != real or m.status != "active":
                    continue
                if m.kind == "session" and m.session_id != session_id:
                    continue
                if m.expires_at and m.expires_at <= clock:
                    m.status = "expired"
                    self._save(m)
                    continue
                found.append(m)
            tokens = query.casefold().split()

            def rank(m: Memory) -> tuple[float, datetime]:
                matches = sum(t in m.content.casefold() for t in tokens)
                age_days = max(0, (clock - m.created_at).total_seconds() / 86400)
                relevance = matches + m.importance * m.confidence / (1 + age_days / 180)
                return relevance, m.last_access or m.created_at

            found.sort(key=rank, reverse=True)
            found = found[:limit]
            for m in found:
                m.last_access = clock
                self._save(m)
            return found

    def modify(
        self,
        character_id: str,
        memory_id: str,
        *,
        content: str | None = None,
        expires_at: datetime | None = None,
    ) -> Memory:
        with self.storage.transaction():
            m = self.owned(character_id, memory_id)
            if m.status == "forgotten":
                raise ValueError("Forgotten memories cannot be restored")
            if m.kind == "real_user" and content is not None:
                raise ValueError("Store a new corrected character memory and explicitly promote it")
            changes: dict[str, Any] = {"content": content} if content is not None else {}
            if expires_at is not None:
                changes["expires_at"] = expires_at
            updated = Memory.model_validate(m.model_dump() | changes)
            if expires_at is not None:
                updated.status = "expired" if expires_at <= now() else "active"
            if content is not None and content != m.content:
                updated.turn_id = None
                self._invalidate_evidence(character_id, {memory_id})
            return self._save(updated)

    def share(self, character_id: str, memory_id: str, recipients: list[str]) -> Memory:
        with self.storage.transaction():
            m = self.owned(character_id, memory_id)
            if m.status != "active" or m.kind in ("session", "real_user"):
                raise ValueError("Only active character memories can be shared")
            for other in recipients:
                self.characters.get(other)
            data = m.model_dump() | {
                "shared_with": list(dict.fromkeys(recipients)),
                "scope": "shared" if recipients else "private",
            }
            return self._save(Memory.model_validate(data))

    def promote(self, character_id: str, memory_id: str, *, confirmation: str) -> Memory:
        if not confirmation.strip() or len(confirmation) > 2000:
            raise ValueError("Explicit user confirmation of truth and storage is required")
        with self.storage.transaction():
            m = self.owned(character_id, memory_id)
            if m.source == "simulated_life":
                raise ValueError("Simulated life cannot be promoted to real-user facts")
            for data in self.storage.list(self.owner, "memory"):
                if data.get("promoted_from") == m.id and data.get("status") == "active":
                    return Memory.model_validate(data)
            if m.status != "active" or (m.expires_at and m.expires_at <= now()):
                raise ValueError("Only active memories may be promoted")
            if m.kind == "real_user":
                raise ValueError("Memory is already real-user memory")
            data = m.model_dump() | {
                "id": new_id(),
                "kind": "real_user",
                "scope": "private",
                "session_id": None,
                "shared_with": [],
                "promoted_from": m.id,
                "confirmation": confirmation,
                "created_at": now(),
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
            records = self.storage.list(self.owner, "memory")
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
                        shared_with=[],
                        scope="private",
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
