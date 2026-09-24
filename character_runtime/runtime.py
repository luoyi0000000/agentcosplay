"""Host-independent orchestration; an authenticated owner is fixed at construction.

宿主无关的编排；认证 Owner 在构造时固定。
"""

from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any

from .characters import Characters
from .cognition import (
    catchphrase_options,
    expression,
    expression_frequency,
    expression_observations,
)
from .companion import Companion
from .compiler import compile
from .context import project_context
from .conversation import turn_windows
from .identity import resolve
from .knowledge import Knowledge
from .knowledge_models import TurnProposal
from .lifelike import interaction
from .lifelike_models import InteractionRequest
from .memory import Memories
from .models import CharacterState, Memory, Session, TaskMode, VoiceProfile, now
from .persistence_models import GenerationRequest
from .providers import Provider, SystemTimeProvider
from .rules import BASE_RULES, MODE_RULES, TASK_RULES
from .scope import ScopeResolver
from .scoped_storage import ScopedStorage
from .storage import Storage


class Runtime:
    """Compose existing engines over one owner or authorized turn storage view.

    在一个 Owner 或已授权回合视图上组合现有引擎，不另建状态权威。
    """

    def __init__(
        self,
        storage: Storage,
        owner: str,
        *,
        clock: Callable[[], datetime] = now,
        providers: Iterable[Provider] = (),
    ) -> None:
        if not owner.strip() or len(owner) > 200 or "\0" in owner:
            raise ValueError("A valid authenticated owner is required")
        self.storage, self.owner = storage, owner
        self.characters = Characters(storage, owner)
        self.clock = clock
        self.actor = storage.actor if isinstance(storage, ScopedStorage) else None
        self.memory = Memories(
            storage,
            owner,
            self.characters,
            clock,
            scope=storage.memory_scope if isinstance(storage, ScopedStorage) else None,
        )
        self.knowledge = Knowledge(storage, owner, self.characters, self.memory, clock)
        self.companion = Companion(storage, owner, self.characters, clock)
        self.providers = (SystemTimeProvider(clock), *providers)

    def for_turn(self, turn_id: str) -> "Runtime":
        """Reuse this engine with a verified actor and authorized storage view.

        使用经验证 Actor 与授权存储视图复用同一引擎；不创建第二套角色数据库。
        """
        if isinstance(self.storage, ScopedStorage):
            raise ValueError("A scoped turn cannot open another participant's turn")
        resolver = ScopeResolver(self.storage, self.owner, self.clock)
        actor = resolver.load_turn(turn_id)
        return Runtime(ScopedStorage(self.storage, resolver, actor), self.owner, clock=self.clock)

    def advance(self, character_id: str) -> None:
        """Refresh optional perception and advance companion state in one transaction.

        在同一事务中刷新可选感知并推进陪伴状态。
        """

        with self.storage.transaction():
            self.companion.refresh(character_id, self.providers)
            self.companion.advance(character_id)

    def set_default(self, character_id: str | None) -> None:
        """Set the owner default only after checking character ownership.

        先验证角色归属，再设置 Owner 默认角色。
        """

        if character_id is not None:
            self.characters.get(character_id)
        self.storage.put(self.owner, "settings", "default", {"character_id": character_id})

    def bind_project(self, project: str, character_id: str | None) -> None:
        """Persist an explicit project route without switching an existing session.

        保存显式项目路由，不自动切换已有会话。
        """

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
        """Open a conversation with one active character and verified host identity when supplied.

        打开只激活一个角色的会话；传入宿主身份时必须验证绑定。
        """

        with self.storage.transaction():
            binding = (
                resolve(self.storage, self.owner, host, platform, actor_id)
                if any((host, platform, actor_id))
                else None
            )
            verified = not any((host, platform, actor_id)) or binding is not None
            if binding:
                identity = self.storage.get(self.owner, "identity_binding", binding) or {}
                # Legacy session tools represent the owner, never another participant.
                # 旧 Session 工具只代表 Owner；多人入口必须使用逐轮权限解析。
                if identity.get("participant_id", self.owner) != self.owner:
                    raise ValueError("Participant interaction requires the scoped turn API")
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
        """Read the owned session; a session ID is not proof of actor identity.

        读取所属会话；会话 ID 不能作为 Actor 身份证明。
        """

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
        """Apply explicit session mode and character changes, preserving long-term state.

        执行显式会话模式及角色切换，不重置长期状态。
        """

        with self.storage.transaction():
            session = self.session(session_id)
            if not session.identity_verified:
                raise ValueError("Unresolved identity cannot activate a private character")
            if action == "activate":
                if character_id is None:
                    raise ValueError("Choose a character to activate")
                if isinstance(self.storage, ScopedStorage):
                    self.storage.resolver.switch_character(self.storage.actor.id, character_id)
                    session.character_id = character_id
                    session.ooc, session.mode_override, session.task_mode = False, None, None
                    return session
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
        """Assemble authorized state and bounded recall through the single compiler pipeline.

        通过唯一编译与组装流程投影授权状态及有界召回。
        """

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
            result.update(turn_windows(self, definition.id, session_id))
            mode = session.task_mode or session.mode_override or definition.default_task_mode
            result.update(
                definition=definition.model_dump(mode="json"),
                state=(
                    CharacterState(character_id=definition.id)
                    if self.actor and not self.actor.private_context_allowed
                    else self.characters.state(definition.id)
                ).model_dump(mode="json"),
                memories=[
                    m.model_dump(mode="json")
                    for m in self.memory.recall(
                        definition.id, query, session_id=session.id, limit=8
                    )
                ],
                effective_mode=mode,
            )
            projected_memories, decisions = self.memory.project(
                definition.id,
                [Memory.model_validate(m) for m in result["memories"]],
                query=query,
                generation=generation,
            )
            result["memories"], result["memory_use_decisions"] = projected_memories, decisions
            if self.actor is None or self.actor.private_context_allowed:
                result["state"]["relationship"] = self.knowledge.relationship.projection(
                    definition.id
                )
            growth_version, overlay = self.knowledge.growth.current(definition.id)
            effective_voice = VoiceProfile.model_validate(
                definition.voice.model_dump() | overlay.get("voice", {})
            )
            if self.actor is None or self.actor.private_context_allowed:
                adaptation = self.knowledge.adaptation(definition.id)
                effective_voice = VoiceProfile.model_validate(
                    effective_voice.model_dump()
                    | {
                        key: value
                        for key, value in adaptation.items()
                        if key in ("verbosity_default", "directness")
                    }
                )
                result["participant_adaptation"] = adaptation
            result["expression_policy"] = expression(
                generation or GenerationRequest(),
                effective_voice,
                result["state"]["relationship"],
                "task_neutral" if session.ooc else mode,
            )
            # ponytail: audience scan; index delivered timestamps when histories grow.
            # 只扫描已授权受众；历史量增大时再为已发送时间建立索引。
            usage = expression_observations(
                self.knowledge.records("raw_event", definition.id),
                self.knowledge.records("turn_lifecycle", definition.id),
                self.clock(),
            )
            result["expression_policy"]["frequency"] = expression_frequency(effective_voice, usage)
            result["expression_policy"]["catchphrase_options"] = (
                catchphrase_options(
                    effective_voice,
                    usage,
                    self.clock(),
                    generation or GenerationRequest(),
                )
                if result["expression_policy"]["character_expression"]["enabled"]
                else []
            )
            result["rules"] += [MODE_RULES[definition.mode], TASK_RULES[mode]]
            if session.ooc:
                result["rules"].append(
                    "User explicitly entered OOC; discuss configuration plainly."
                )
            if include_companion:
                result["companion"] = self.companion.context(definition.id, query)
            if self.actor is None or self.actor.private_context_allowed:
                result.setdefault("companion", {}).update(
                    self.knowledge.lifelike.projection(definition.id)
                )
            if isinstance(self.storage, ScopedStorage):
                # Public life never falls back to the owner's legacy private companion.
                # 公共生活绝不回退到 Owner 的旧私人 Companion 数据。
                public = Runtime(
                    ScopedStorage(
                        self.storage.base,
                        self.storage.resolver,
                        self.storage.actor,
                        public_state=True,
                    ),
                    self.owner,
                    clock=self.clock,
                )
                public.advance(definition.id)
                public_life = public.companion.context(definition.id, query)
                body = public.knowledge.lifelike.advance(definition.id)
                companion = result.setdefault("companion", {})
                companion["life"] = public_life["life"]
                companion["character_affect"] = {
                    "valence": body.affect.valence,
                    "arousal": body.affect.arousal,
                    "tags": body.affect.tags,
                }
                if "affect" in companion:
                    companion["relational_affect"] = companion.pop("affect")
                for key in ("goals", "habits"):
                    companion[key] = [*public_life.get(key, []), *companion.get(key, [])]
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
        """Delegate proposals to the evidence-gated transactional knowledge engine.

        把回合提案交给有证据门的知识事务引擎。
        """

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
