"""Host-independent orchestration; an authenticated owner is fixed at construction."""

from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any

from .characters import Characters
from .cognition import expression
from .companion import Companion
from .compiler import compile
from .context import project_context
from .identity import resolve
from .knowledge import Knowledge
from .knowledge_models import TurnProposal
from .lifelike import interaction
from .lifelike_models import InteractionRequest
from .memory import Memories
from .models import Session, TaskMode, VoiceProfile, now
from .persistence_models import GenerationRequest
from .providers import Provider, SystemTimeProvider
from .rules import BASE_RULES, MODE_RULES, TASK_RULES
from .storage import Storage


class Runtime:
    def __init__(
        self,
        storage: Storage,
        owner: str,
        *,
        clock: Callable[[], datetime] = now,
        providers: Iterable[Provider] = (),
    ) -> None:
        if not owner.strip() or len(owner) > 200:
            raise ValueError("A valid authenticated owner is required")
        self.storage, self.owner = storage, owner
        self.characters = Characters(storage, owner)
        self.memory = Memories(storage, owner, self.characters, clock)
        self.knowledge = Knowledge(storage, owner, self.characters, self.memory, clock)
        self.companion = Companion(storage, owner, self.characters, clock)
        self.providers = (SystemTimeProvider(clock), *providers)

    def advance(self, character_id: str) -> None:
        with self.storage.transaction():
            self.companion.refresh(character_id, self.providers)
            self.companion.advance(character_id)

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
        self,
        session_id: str,
        *,
        character_id: str | None = None,
        project: str | None = None,
        host: str = "",
        platform: str = "",
        actor_id: str = "",
    ) -> Session:
        with self.storage.transaction():
            binding = (
                resolve(self.storage, self.owner, host, platform, actor_id)
                if any((host, platform, actor_id))
                else None
            )
            verified = not any((host, platform, actor_id)) or binding is not None
            existing = self.storage.get(self.owner, "session", session_id)
            if existing is not None:
                active = Session.model_validate(existing)
                if active.identity_binding != binding or active.identity_verified != verified:
                    raise ValueError("Session identity changed; create a new session after binding")
                return active
            if character_id is None:
                route = self.storage.get(self.owner, "route", project) if project else None
                if route is None:
                    route = self.storage.get(self.owner, "settings", "default")
                character_id = route.get("character_id") if route else None
            if character_id is not None:
                self.characters.get(character_id)
            session = Session(
                id=session_id,
                character_id=character_id if verified else None,
                project=project,
                identity_verified=verified,
                identity_binding=binding,
            )
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
            if not session.identity_verified:
                raise ValueError("Unresolved identity cannot activate a private character")
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

    def context(
        self,
        session_id: str,
        query: str = "",
        *,
        include_companion: bool = True,
        include_self_model: bool = True,
        generation: GenerationRequest | None = None,
        interaction_request: InteractionRequest | None = None,
    ) -> dict[str, Any]:
        if len(query) > 4000:
            raise ValueError("Context query must be at most 4000 characters")
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
                result["onboarding"] = {
                    "status": "choose_character",
                    "prompt": "你想让我扮演谁？也可以创建一个新角色，或导入已有角色。",
                    "persistence_available": True,
                }
                return result
            self.knowledge.scope(session_id)
            definition = self.characters.get(session.character_id)
            self.advance(definition.id)
            mode = session.task_mode or session.mode_override or definition.default_task_mode
            result.update(
                definition=definition.model_dump(mode="json"),
                state=self.characters.state(definition.id).model_dump(mode="json"),
                memories=[
                    m.model_dump(mode="json")
                    for m in self.memory.recall(
                        definition.id, query, session_id=session.id, limit=8
                    )
                ],
                effective_mode=mode,
            )
            result["state"]["relationship"] = self.knowledge.relationship.projection(definition.id)
            growth_version, overlay = self.knowledge.growth.current(definition.id)
            effective_voice = VoiceProfile.model_validate(
                definition.voice.model_dump() | overlay.get("voice", {})
            )
            result["expression_policy"] = expression(
                generation or GenerationRequest(),
                effective_voice,
                result["state"]["relationship"],
                mode,
            )
            result["rules"] += [MODE_RULES[definition.mode], TASK_RULES[mode]]
            if session.ooc:
                result["rules"].append(
                    "User explicitly entered OOC; discuss configuration plainly."
                )
            if include_companion:
                result["companion"] = self.companion.context(definition.id, query)
            result.setdefault("companion", {}).update(
                self.knowledge.lifelike.projection(definition.id)
            )
            result["interaction"] = interaction(interaction_request or InteractionRequest())
            result["perception"] = [
                p
                for p in self.knowledge.records("perception", definition.id)
                if p.get("expires_at", "") > self.companion.clock().isoformat()
            ]
            result["facts"] = [
                f
                for f in self.knowledge.records("fact", definition.id)
                if f.get("validity") == "active" and f.get("subject") == "character"
            ]
            return project_context(
                result,
                query,
                compiled=compile(self.storage, self.owner, definition, growth_version, overlay),
            )

    def commit_turn(self, session_id: str, proposal: TurnProposal) -> dict[str, Any]:
        with self.storage.transaction():
            result = self.knowledge.commit(session_id, proposal)
            # Activity refresh is idempotent per operation too.
            marker = f"{result['character_id']}:{proposal.operation_id}"
            if self.storage.get(self.owner, "activity_receipt", marker) is None:
                self.companion.record_activity(result["character_id"])
                self.storage.put(
                    self.owner, "activity_receipt", marker, {"character_id": result["character_id"]}
                )
            return result
