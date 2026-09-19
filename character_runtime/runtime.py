"""Host-independent orchestration; an authenticated owner is fixed at construction."""

from typing import Any

from .characters import Characters
from .growth import grow
from .memory import Memories
from .models import Candidate, GrowthProposal, Session, TaskMode, now
from .rules import BASE_RULES, MODE_RULES, TASK_RULES
from .storage import Storage


class Runtime:
    def __init__(self, storage: Storage, owner: str) -> None:
        if not owner.strip() or len(owner) > 200:
            raise ValueError("A valid authenticated owner is required")
        self.storage, self.owner = storage, owner
        self.characters = Characters(storage, owner)
        self.memory = Memories(storage, owner, self.characters)

    def set_default(self, character_id: str | None) -> None:
        if character_id is not None:
            self.characters.get(character_id)
        self.storage.put(self.owner, "settings", "default", {"character_id": character_id})

    def bind_project(self, project: str, character_id: str | None) -> None:
        if character_id is not None:
            self.characters.get(character_id)
        if not project.strip() or len(project) > 200:
            raise ValueError("Invalid project key")
        self.storage.put(self.owner, "route", project, {"character_id": character_id})

    def open_session(
        self, session_id: str, *, character_id: str | None = None, project: str | None = None
    ) -> Session:
        with self.storage.transaction():
            existing = self.storage.get(self.owner, "session", session_id)
            if existing is not None:
                return Session.model_validate(existing)
            if character_id is None:
                route = self.storage.get(self.owner, "route", project) if project else None
                if route is None:
                    route = self.storage.get(self.owner, "settings", "default")
                character_id = route.get("character_id") if route else None
            if character_id is not None:
                self.characters.get(character_id)
            session = Session(id=session_id, character_id=character_id, project=project)
            self._save_session(session)
            return session

    def _save_session(self, session: Session) -> None:
        self.storage.put(self.owner, "session", session.id, session.model_dump(mode="json"))

    def session(self, session_id: str) -> Session:
        value = self.storage.get(self.owner, "session", session_id)
        if value is None:
            raise KeyError("Session not found; open it first")
        return Session.model_validate(value)

    def session_control(
        self,
        session_id: str,
        action: str,
        *,
        character_id: str | None = None,
        mode: TaskMode | None = None,
    ) -> Session:
        with self.storage.transaction():
            session = self.session(session_id)
            if action == "activate":
                if character_id is None:
                    raise ValueError("Choose a character to activate")
                self.characters.get(character_id)
                session.character_id = character_id
                session.ooc, session.mode_override, session.task_mode = False, None, None
            elif action == "deactivate":
                session.character_id = None
                session.ooc, session.mode_override, session.task_mode = False, None, None
            elif action in ("enter_ooc", "exit_ooc"):
                session.ooc = action == "enter_ooc"
            elif action == "set_mode":
                session.mode_override = mode
            elif action == "start_task":
                if mode is None:
                    raise ValueError("Task mode is required")
                session.task_mode = mode
            elif action == "end_task":
                session.task_mode = None
            else:
                raise ValueError("Unknown session action")
            self._save_session(session)
            return session

    def context(self, session_id: str, query: str = "") -> dict[str, Any]:
        with self.storage.transaction():
            session = self.session(session_id)
            result: dict[str, Any] = {
                "session_id": session.id,
                "ooc": session.ooc,
                "definition": None,
                "state": None,
                "memories": [],
                "effective_mode": "task_neutral",
                "rules": list(BASE_RULES),
            }
            if session.character_id is None:
                return result
            definition = self.characters.get(session.character_id)
            mode = session.task_mode or session.mode_override or definition.default_task_mode
            result.update(
                definition=definition.model_dump(mode="json"),
                state=self.characters.state(definition.id).model_dump(mode="json"),
                memories=[
                    m.model_dump(mode="json")
                    for m in self.memory.recall(definition.id, query, session_id=session.id)
                ],
                effective_mode=mode,
            )
            result["rules"] += [MODE_RULES[definition.mode], TASK_RULES[mode]]
            if session.ooc:
                result["rules"].append(
                    "User explicitly entered OOC; discuss configuration plainly."
                )
            return result

    def commit_turn(
        self,
        session_id: str,
        turn_id: str,
        candidates: list[Candidate],
        growth: GrowthProposal | None = None,
    ) -> dict[str, Any]:
        if not turn_id.strip() or len(turn_id) > 100 or len(candidates) > 20:
            raise ValueError("A short unique turn ID and at most 20 candidates are required")
        with self.storage.transaction():
            session = self.session(session_id)
            if session.character_id is None or session.ooc:
                raise ValueError("Roleplay turn commits require an active character outside OOC")
            # Length-prefixed session component avoids ambiguous concatenation collisions.
            receipt_id = f"{len(session_id)}:{session_id}:{turn_id}"
            previous = self.storage.get(self.owner, "turn", receipt_id)
            if previous is not None:
                if previous["character_id"] != session.character_id:
                    raise ValueError("Turn ID belongs to another character; use a fresh ID")
                return previous
            for candidate in candidates:
                if candidate.kind == "real_user":
                    raise ValueError("Automatic memory cannot create real-user facts")
            definition = self.characters.get(session.character_id)
            state = self.characters.state(session.character_id)
            if growth:
                evidence_turns: set[str] = set()
                for memory_id in growth.evidence_ids:
                    evidence = self.memory.owned(definition.id, memory_id)
                    if evidence.status != "active" or (
                        evidence.expires_at and evidence.expires_at <= now()
                    ):
                        raise ValueError("Growth evidence must be active")
                    if evidence.kind not in (
                        "character_long_term",
                        "relationship",
                        "shared_roleplay",
                    ):
                        raise ValueError("Growth evidence must be persistent character memory")
                    if evidence.turn_id:
                        receipt = self.storage.get(self.owner, "turn", evidence.turn_id)
                        if (
                            receipt
                            and receipt.get("character_id") == definition.id
                            and evidence.id in receipt.get("memory_ids", [])
                            and receipt.get("turn_count", 0)
                            > state.last_growth_turn.get("relationship", 0)
                        ):
                            evidence_turns.add(evidence.turn_id)
                relationship_changes = any(
                    target is not None and target != getattr(state.relationship, field)
                    for field, target in (
                        ("stage", growth.stage),
                        ("trust", growth.trust),
                        ("familiarity", growth.familiarity),
                    )
                )
                if relationship_changes and len(evidence_turns) < 3:
                    raise ValueError("Relationship growth needs evidence from three distinct turns")
            state.turn_count += 1
            state = grow(definition, state, growth)
            memories = [
                self.memory.store(definition.id, c, session.id, turn_id=receipt_id)
                for c in candidates
                if c.importance >= 0.3 and c.confidence >= 0.5
            ]
            state.revision += 1
            self.characters.save_state(state)
            result = {
                "character_id": definition.id,
                "memory_ids": [m.id for m in memories],
                "turn_count": state.turn_count,
                "state_revision": state.revision,
            }
            self.storage.put(self.owner, "turn", receipt_id, result)
            return result
