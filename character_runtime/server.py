"""Thin MCP adapter over the same runtime used by every platform.

复用相同 Runtime 的轻量 MCP 适配层。
"""

from collections.abc import Callable
from functools import wraps
from typing import Any, Literal, ParamSpec
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl, Field, ValidationError
from starlette.applications import Starlette

from . import __version__
from .auth import JWTVerifier, LocalTokenVerifier, TurnTokenVerifier
from .companion_models import CompanionUpdate, LegacyMoodWriteUnsupported
from .conversation import ConversationDelivery, TurnIntakeBuffer
from .conversation_models import EndpointCapabilities, SemanticResponse
from .diagnostics import diagnose
from .identity import bind
from .knowledge_models import EventBatch, EventInput, MemoryMutation, MemoryProposal, TurnProposal
from .lifecycle import HostCapabilities, TurnEnvelope, TurnLifecycle
from .lifelike_models import InteractionRequest, PerceptionObservation, VisualPrototype
from .models import (
    Candidate,
    CharacterDefinition,
    EmbodimentProfile,
    Fact,
    GrowthPolicy,
    Identifier,
    Mode,
    Model,
    Package,
    Relationship,
    TaskMode,
    VoiceProfile,
)
from .operations import fingerprint
from .packages import PackageV2, PackageV3, export_character, import_character
from .persistence_models import GenerationRequest, RecallRequest
from .providers import Observation, Provider
from .runtime import Runtime
from .safety import check_content
from .scope import ScopeResolver
from .storage import Storage

P = ParamSpec("P")


def safe(fn: Callable[P, Any]) -> Callable[P, dict[str, Any]]:
    """Redact failures while retaining stable compatibility error codes.

    对失败脱敏，同时保留稳定兼容错误码。
    """

    @wraps(fn)
    def call(*args: P.args, **kwargs: P.kwargs) -> dict[str, Any]:
        try:
            access = get_access_token()
            if access and "character:discovery" in access.scopes:
                raise ValueError(
                    "Discovery credentials cannot execute tools; a verified turn is required"
                )
            if access and any(s.startswith("character:turn:") for s in access.scopes):
                # A scoped model tool token cannot administer identities or attest delivery.
                # 模型的单轮工具令牌不能管理身份、伪造原始证据或确认平台投递。
                if fn.__name__ not in {
                    "runtime_context",
                    "memory_recall",
                    "memory_write",
                    "memory_promote",
                    "turn_commit",
                    "session_control",
                    "context_explain",
                    "character_read",
                    "companion_control",
                    "runtime_doctor",
                    "perception_observe",
                }:
                    raise ValueError("This operation requires the trusted owner/host bridge")
            result = fn(*args, **kwargs)
            if isinstance(result, Model):
                result = result.model_dump(mode="json")
            return {"ok": True, "result": result}
        except LegacyMoodWriteUnsupported as exc:
            return {
                "ok": False,
                "error": exc.code,
                "read_only": exc.read_only,
                "replacement": exc.replacement,
                "message": str(exc),
            }
        except ValidationError:
            return {
                "ok": False,
                "error": "invalid_input",
                "message": "2.x contract required: ingest RawEvents; submit operation_id "
                "and obtain allowlists before edits. Read the current tool schema.",
            }
        except KeyError:
            return {"ok": False, "error": "not_found", "message": "Object not found in this scope"}
        except ValueError as exc:
            return {"ok": False, "error": "invalid_operation", "message": str(exc)}

    return call


class DefinitionPatch(Model):
    """Bound explicit character edits without exposing storage ownership fields.

    约束显式角色编辑，不暴露存储归属字段。
    """

    name: str | None = Field(default=None, min_length=1, max_length=100)
    origin: Literal["original", "ip"] | None = None
    mode: Mode | None = None
    default_task_mode: TaskMode | None = None
    growth: GrowthPolicy | None = None
    voice: VoiceProfile | None = None
    embodiment: EmbodimentProfile | None = None
    facts: dict[Identifier, Fact] | None = Field(default=None, max_length=100)


class CharacterWrite(Model):
    """Validate the public character mutation envelope; authority is resolved separately.

    验证公开角色修改请求；权限另行解析。
    """

    operation_id: Identifier | None = None
    allowlist_id: Identifier | None = None
    action: Literal["create", "update", "relationship"]
    definition: CharacterDefinition | None = None
    character_id: Identifier | None = None
    session_id: Identifier | None = None
    patch: DefinitionPatch | None = None
    expected_revision: int | None = Field(default=None, ge=1)
    relationship: Relationship | None = None


class SessionControl(Model):
    """Describe explicit session actions, never infer a participant from message text.

    描述显式会话动作，不从正文猜测参与者身份。
    """

    host: str = Field(default="", max_length=200)
    platform: str = Field(default="", max_length=200)
    actor_id: str = Field(default="", max_length=200)
    action: Literal[
        "open",
        "activate",
        "deactivate",
        "enter_ooc",
        "exit_ooc",
        "set_mode",
        "start_task",
        "end_task",
        "set_default",
        "bind_project",
    ]
    session_id: Identifier
    character_id: Identifier | None = None
    project: Identifier | None = None
    mode: TaskMode | None = None


class MemoryWrite(Model):
    """Require current evidence and operation contracts for public memory writes.

    公开记忆写入必须满足当前证据及操作契约。
    """

    action: Literal["store", "modify", "forget", "archive"]
    character_id: Identifier
    session_id: Identifier
    operation_id: Identifier | None = None
    allowlist_id: Identifier | None = None
    memory_id: Identifier | None = None
    proposal: MemoryProposal | None = None
    content: str | None = Field(default=None, min_length=1, max_length=4000)
    evidence_refs: list[Identifier] = Field(default_factory=list, max_length=20)
    confirmation: str = Field(default="", max_length=1000)


def require_operation(operation_id: str | None) -> str:
    """Reject legacy writes lacking an idempotency key with migration guidance.

    拒绝缺少幂等键的旧写入，并提供迁移提示。
    """

    if not operation_id:
        raise ValueError(
            "compatibility_error: 2.x requires operation_id, RawEvent-backed proposals "
            "and issued allowlists for edits; read the current tool schema"
        )
    return operation_id


def build_server(
    storage: Storage,
    *,
    local_owner: str = "local-user",
    token: str | None = None,
    issuer: str | None = None,
    audience: str | None = None,
    jwks_url: str | None = None,
    resource: str = "http://127.0.0.1:8765/mcp",
    providers: tuple[Provider, ...] = (),
) -> MCPServer[Any]:
    """Expose one Runtime through authenticated owner or restricted turn tools.

    通过认证 Owner 或受限回合工具暴露同一个 Runtime。
    """

    verifier: JWTVerifier | LocalTokenVerifier | TurnTokenVerifier | None = None
    auth = None
    if issuer or audience or jwks_url:
        if providers:
            raise ValueError("Shared local provider files are limited to a single-owner Runtime")
        if not all((issuer, audience, jwks_url)):
            raise ValueError("OAuth issuer, audience and JWKS URL must all be configured")
        verifier = JWTVerifier(issuer or "", audience or "", jwks_url or "", resource)
    elif token:
        verifier = LocalTokenVerifier(token, local_owner, resource)
    if verifier is not None and not isinstance(verifier, TurnTokenVerifier):
        verifier = TurnTokenVerifier(verifier, resource)
        auth = AuthSettings(
            issuer_url=AnyHttpUrl(issuer or "http://127.0.0.1:8765"),
            resource_server_url=AnyHttpUrl(resource),
            required_scopes=["character:access"],
            validate_token_resource=True,
        )
    server: MCPServer[Any] = MCPServer(
        "agentcosplay",
        version=__version__,
        token_verifier=verifier,
        auth=auth,
        log_level="CRITICAL",
        instructions="Open a session and load runtime_context before roleplay. "
        "No active character means ask who the user wants to portray, not an error. "
        "If tools fail, continue current-session roleplay and never claim persistence. "
        "Commit important memories after each turn. User facts need explicit promotion.",
    )

    def runtime(turn_id: str | None = None) -> Runtime:
        if verifier:
            access = get_access_token()
            if access is None or not access.subject:
                raise ValueError("Authenticated user identity is required")
            if "character:discovery" in access.scopes:
                raise ValueError("Discovery credentials cannot access Runtime state")
            rt = Runtime(storage, access.subject, providers=providers)
            turns = [
                s.removeprefix("character:turn:")
                for s in access.scopes
                if s.startswith("character:turn:")
            ]
            if turns:
                if len(turns) != 1 or (turn_id is not None and turn_id != turns[0]):
                    raise ValueError("Turn capability does not authorize this interaction")
                scoped_runtime = rt.for_turn(turns[0])
                if (
                    not scoped_runtime.actor
                    or access.client_id != "turn:" + scoped_runtime.actor.host
                ):
                    raise ValueError("Host capability mismatch")
                return scoped_runtime
        else:
            rt = Runtime(storage, local_owner, providers=providers)
        return rt.for_turn(turn_id) if turn_id else rt

    def scoped(rt: Runtime, session_id: str, character_id: str, *, ooc: bool = False) -> None:
        s = rt.session(session_id)
        if s.character_id != character_id:
            raise ValueError("Session is not active for this character")
        if ooc and not s.ooc:
            raise ValueError("Enter OOC before editing configuration or private memories")

    read = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
    write = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=False)

    @server.tool(annotations=write)
    @safe
    def host_prepare_turn(envelope: TurnEnvelope, capabilities: HostCapabilities) -> dict[str, Any]:
        """Automatic trusted-host lifecycle; the model does not have to call this tool.

        可信宿主自动生命周期入口；模型不需要主动调用，核心实现独立于 MCP 传输。
        """
        rt = runtime()
        result = TurnLifecycle(rt).prepare(envelope, capabilities)
        if isinstance(verifier, TurnTokenVerifier):
            actor = ScopeResolver(storage, rt.owner, rt.clock).load_turn(result["turn_id"])
            result["capability"] = verifier.issue(
                rt.owner, actor.id, actor.host, int(actor.expires_at.timestamp())
            )
        return result

    @server.tool(annotations=write)
    @safe
    def host_observe_ambient(
        envelope: TurnEnvelope, capabilities: HostCapabilities
    ) -> dict[str, Any]:
        """Observe verified public activity without generation.

        观察经验证的公开活动，不发起生成。
        """
        return TurnLifecycle(runtime()).observe_ambient(envelope, capabilities)

    @server.tool(annotations=write)
    @safe
    def host_observe_generation(
        turn_id: Identifier, operation_id: Identifier, text: str
    ) -> dict[str, Any]:
        """Observe generated output without asserting delivery. / 观察生成输出，不声明已送达。"""
        return TurnLifecycle(runtime()).observe_generation(turn_id, operation_id, text)

    @server.tool(annotations=write)
    @safe
    def host_finalize_turn(
        turn_id: Identifier, operation_id: Identifier, proposal: TurnProposal | None = None
    ) -> dict[str, Any]:
        """Finish a generation through existing evidence gates. / 经既有证据门结束本轮生成。"""
        return TurnLifecycle(runtime()).finalize(turn_id, operation_id, proposal)

    @server.tool(annotations=write)
    @safe
    def host_turn_open(
        host: Identifier,
        platform: Identifier,
        actor_id: Identifier,
        endpoint_id: Identifier,
        session_id: Identifier,
        request_id: Identifier,
        event: EventInput | None = None,
        buffer_intake: bool = False,
        expected_endpoint_kind: Literal["dm", "group"] | None = None,
    ) -> dict[str, Any]:
        """Trusted host ingress: resolve an actor and issue model tools a limited capability.

        可信宿主入口：解析 Actor 并签发受限模型工具令牌，管理凭据不得进入模型。
        """
        rt = runtime()
        with storage.transaction():
            # Host-observed audience must agree with the authoritative binding.
            # 宿主观察到的受众类型必须与规范绑定一致，防止群入口映射到私人上下文。
            if expected_endpoint_kind is not None:
                endpoint = storage.get(rt.owner, "platform_binding", endpoint_id)
                if not endpoint or endpoint.get("kind") != expected_endpoint_kind:
                    raise ValueError("Host audience does not match the endpoint binding")
            turn = ScopeResolver(storage, rt.owner).begin_turn(
                host=host,
                platform=platform,
                actor_id=actor_id,
                endpoint_id=endpoint_id,
                session_id=session_id,
                request_id=request_id,
            )
            result: dict[str, Any] = {"turn_id": turn.id, "character_id": turn.character_id}
            if event is not None:
                if event.source_kind != "USER_DIRECT":
                    raise ValueError("Ingress requires a visible direct user event")
                result["ingestion"] = rt.for_turn(turn.id).knowledge.ingest(
                    EventBatch(
                        session_id=turn.id,
                        operation_id=fingerprint([event.source_id, event.source_event_id]),
                        events=[event],
                    )
                )
            if isinstance(verifier, TurnTokenVerifier):
                result["capability"] = verifier.issue(
                    rt.owner, turn.id, host, int(turn.expires_at.timestamp())
                )
            if buffer_intake:
                if event is None:
                    raise ValueError("Buffered intake requires a direct source event")
                result["intake"] = TurnIntakeBuffer(rt).push(
                    turn.id, result["ingestion"]["event_ids"][0]
                )
            return result

    @server.tool(annotations=write)
    @safe
    def host_intake_claim(buffer_id: Identifier) -> dict[str, Any]:
        """Claim one debounced batch for the current host model.

        为宿主当前模型领取一次合并批次；管理凭据不可暴露给模型。
        """
        return {"batch": TurnIntakeBuffer(runtime()).claim(buffer_id)}

    @server.tool(annotations=write)
    @safe
    def host_response_plan(
        turn_id: Identifier,
        operation_id: Identifier,
        response: SemanticResponse,
        request: GenerationRequest,
        capabilities: EndpointCapabilities,
    ) -> dict[str, Any]:
        """Persist one semantic response; capabilities are attested by trusted adapter code.

        保存一份语义回复；平台能力必须由可信 Adapter 声明，模型不能授予发送权。
        """
        return ConversationDelivery(runtime()).create(
            turn_id, operation_id, response, request, capabilities
        )

    @server.tool(annotations=write)
    @safe
    def host_response_claim(plan_id: Identifier, segment_index: int) -> dict[str, Any]:
        """Claim a due visible segment once. / 只领取一次到期可见片段。"""
        return {"segment": ConversationDelivery(runtime()).claim(plan_id, segment_index)}

    @server.tool(annotations=write)
    @safe
    def host_response_ack(
        plan_id: Identifier,
        segment_index: int,
        claim_id: Identifier,
        delivered: bool | None,
        visible_content: str = "",
        delivery_reference: str = "",
    ) -> dict[str, Any]:
        """Attest actual final delivery; uncertainty never permits another send.

        确认平台实际最终投递；未知结果绝不授予重发权。
        """
        return ConversationDelivery(runtime()).acknowledge(
            plan_id,
            segment_index,
            claim_id,
            delivered,
            visible_content=visible_content,
            delivery_reference=delivery_reference,
        )

    @server.tool(annotations=write)
    @safe
    def host_response_cancel(plan_id: Identifier) -> dict[str, Any]:
        """Cancel unsent segments only. / 只取消尚未发送的片段。"""
        return ConversationDelivery(runtime()).cancel(plan_id)

    @server.tool(annotations=read)
    @safe
    def character_read(
        character_id: Identifier | None = None, session_id: Identifier | None = None
    ) -> dict[str, Any]:
        """Read owned configuration; OOC session requests receive short-lived mutation targets.

        读取所属配置；OOC 会话请求取得短期修改目标授权。
        """
        rt = runtime()
        if character_id is None:
            return {
                "characters": [
                    {"id": c.id, "name": c.name, "mode": c.mode} for c in rt.characters.list()
                ]
            }
        result: dict[str, Any] = {
            "definition": rt.characters.get(character_id).model_dump(mode="json"),
        }
        if rt.actor is None or rt.actor.private_context_allowed:
            result["state"] = rt.characters.state(character_id).model_dump(mode="json")
        if rt.actor:
            # Stable definition is public; participant state must never appear in a group.
            # 稳定角色定义可以共享；Participant 私有状态绝不进入群聊工具结果。
            return result
        if session_id:
            scoped(rt, session_id, character_id, ooc=True)
            ops = rt.knowledge.operations(character_id)
            result["allowlists"] = {
                domain: ops.issue_allowlist(
                    domain, [character_id], ["UPDATE"], session_id=session_id
                )
                for domain in ("definition", "state")
            }
        return result

    @server.tool(annotations=write)
    @safe
    def character_write(request: CharacterWrite) -> dict[str, Any]:
        """Create idempotently; OOC edits require a current character_read target grant.

        幂等创建；OOC 编辑须携带当前 character_read 签发的目标授权。
        """
        operation = require_operation(request.operation_id)
        rt = runtime()
        with rt.storage.transaction():
            if request.action == "create":
                if request.definition is None:
                    raise ValueError("A definition is required")
                definition = request.definition
                if "id" not in definition.model_fields_set:
                    definition = definition.model_copy(
                        update={"id": str(uuid5(NAMESPACE_URL, fingerprint([rt.owner, operation])))}
                    )
                check_content(definition.model_dump_json())
                payload = {"action": "create", "definition": definition.model_dump(mode="json")}
                existing = rt.storage.get(rt.owner, "definition", definition.id)
                if existing is None:
                    rt.characters.create(definition)
                ops = rt.knowledge.operations(definition.id)
                if existing is not None and ops._get("operation", operation) is None:
                    raise ValueError("Character ID already exists")
                return ops.execute(
                    operation,
                    payload,
                    lambda: {"id": definition.id},
                    domain="character",
                    operation="CREATE",
                    authority="USER_MANUAL",
                )
            if not request.character_id or not request.session_id or not request.allowlist_id:
                raise ValueError("Character, OOC session and target allowlist are required")
            cid = request.character_id
            scoped(rt, request.session_id, cid, ooc=True)
            ops = rt.knowledge.operations(cid)

            def apply() -> dict[str, Any]:
                domain = "definition" if request.action == "update" else "state"
                ops.consume_allowlist(
                    request.allowlist_id or "",
                    "UPDATE",
                    [cid],
                    session_id=request.session_id,
                    collection=domain,
                )
                if request.expected_revision is None:
                    raise ValueError("expected_revision is required")
                if request.action == "update":
                    if request.patch is None:
                        raise ValueError("A patch is required")
                    check_content(request.patch.model_dump_json())
                    changes = request.patch.model_dump(exclude_none=True)
                    changes.pop("facts", None)
                    updated = rt.characters.update(
                        cid,
                        facts=request.patch.facts,
                        expected_revision=request.expected_revision,
                        **changes,
                    )
                    return {"id": cid, "revision": updated.revision}
                if request.relationship is None:
                    raise ValueError("Relationship is required")
                state = rt.knowledge.relationship.configure(
                    cid, request.relationship, request.expected_revision
                )
                return {"id": cid, "revision": state.revision}

            return ops.execute(
                operation,
                request.model_dump(mode="json"),
                apply,
                domain="character",
                operation="UPDATE",
                target_ids=[cid],
                authority="USER_MANUAL",
            )

    @server.tool(annotations=write)
    @safe
    def session_control(request: SessionControl) -> dict[str, Any]:
        """Route sessions, switch characters, control OOC and temporary task mode.

        显式路由会话、切换角色，并控制 OOC 与临时任务模式。
        """
        rt = runtime()
        if request.action == "open":
            return rt.open_session(
                request.session_id,
                character_id=request.character_id,
                project=request.project,
                host=request.host,
                platform=request.platform,
                actor_id=request.actor_id,
            ).model_dump(mode="json")
        if request.action == "set_default":
            rt.set_default(request.character_id)
            return {"default_character": request.character_id}
        if request.action == "bind_project":
            if request.project is None:
                raise ValueError("Project key is required")
            rt.bind_project(request.project, request.character_id)
            return {"project": request.project, "character_id": request.character_id}
        return rt.session_control(
            request.session_id, request.action, character_id=request.character_id, mode=request.mode
        ).model_dump(mode="json")

    @server.tool(annotations=read)
    @safe
    def runtime_context(
        session_id: Identifier,
        query: str = "",
        include_companion: bool = True,
        include_self_model: bool = True,
        generation: GenerationRequest | None = None,
        interaction_request: InteractionRequest | None = None,
    ) -> dict[str, Any]:
        """Load definition, state, relevant roleplay memories and runtime rules.

        载入所属定义、状态、相关记忆及 Runtime 规则。
        """
        return runtime().context(
            session_id,
            query,
            include_companion=include_companion,
            include_self_model=include_self_model,
            generation=generation,
            interaction_request=interaction_request,
        )

    @server.tool(annotations=write)
    @safe
    def companion_control(
        session_id: Identifier,
        update: CompanionUpdate | None = None,
        operation_id: Identifier | None = None,
        allowlist_id: Identifier | None = None,
    ) -> dict[str, Any]:
        """OOC read issues an edit grant; updates require that grant and an operation ID.

        OOC 读取签发编辑授权；更新须携带授权及操作 ID。
        """
        rt = runtime()
        if update is not None and update.mood is not None:
            raise LegacyMoodWriteUnsupported()
        with rt.storage.transaction():
            session = rt.knowledge.scope(session_id, ooc=True)
            assert session.character_id is not None
            cid = session.character_id
            state = rt.companion.get(cid)
            if rt.storage.get(rt.owner, "companion", cid) is None:
                rt.companion._save(state)
            ops = rt.knowledge.operations(cid)
            if update is None:
                return {
                    "legacy_mood_read_only": True,
                    "state": state.model_dump(
                        mode="json", exclude={"pending_decision": {"claim_id"}}
                    ),
                    "allowlist": ops.issue_allowlist(
                        "companion", [cid], ["UPDATE"], session_id=session_id
                    ),
                }
            operation = require_operation(operation_id)
            if not allowlist_id:
                raise ValueError("Read companion_control first to obtain a target grant")
            check_content(update.model_dump_json())

            def apply() -> dict[str, Any]:
                ops.consume_allowlist(
                    allowlist_id, "UPDATE", [cid], collection="companion", session_id=session_id
                )
                rt.companion.update(cid, update)
                return {"updated": cid}

            return ops.execute(
                operation,
                {
                    "session_id": session_id,
                    "allowlist_id": allowlist_id,
                    "update": update.model_dump(mode="json"),
                },
                apply,
                domain="companion",
                operation="UPDATE",
                target_ids=[cid],
                authority="USER_MANUAL",
            )

    @server.tool(annotations=write)
    @safe
    def host_companion_configure(
        turn_id: Identifier,
        update: CompanionUpdate,
        operation_id: Identifier,
        confirmation: str,
    ) -> dict[str, Any]:
        """Owner-only endpoint configuration; model turn tokens cannot call this tool.

        Owner 专用受众配置；模型的单轮令牌不能调用此入口。
        """
        if not confirmation.strip():
            raise ValueError("Explicit owner confirmation is required")
        rt = runtime(turn_id)
        assert rt.actor
        cid = rt.actor.character_id
        return rt.knowledge.operations(cid).execute(
            operation_id,
            {"update": update.model_dump(mode="json"), "confirmation": confirmation},
            lambda: {"revision": rt.companion.update(cid, update, endpoint_admin=True).revision},
            domain="companion",
            operation="UPDATE",
            authority="USER_MANUAL",
        )

    @server.tool(annotations=write)
    @safe
    def provider_observe(
        session_id: Identifier, observation: Observation, operation_id: Identifier | None = None
    ) -> dict[str, Any]:
        """Supply sourced, expiring host observations, never credentials or user profile truth.

        提交有来源和有效期的宿主观察，不提交凭据或冒充用户真实档案。
        """
        operation = require_operation(operation_id)
        rt = runtime()
        with rt.storage.transaction():
            session = rt.knowledge.scope(session_id)
            assert session.character_id is not None
            check_content(observation.model_dump_json())

            def apply() -> dict[str, Any]:
                rt.companion.observe(session.character_id or "", observation)
                return {"observed": observation.kind}

            return rt.knowledge.operations(session.character_id).execute(
                operation,
                {"session_id": session_id, "observation": observation.model_dump(mode="json")},
                apply,
                domain="observation",
                operation="CREATE",
            )

    @server.tool(annotations=write)
    @safe
    def proactive_decide(
        character_id: Identifier,
        reservation_id: Identifier | None = None,
        turn_id: Identifier | None = None,
    ) -> dict[str, Any]:
        """Scheduler decision and atomic reservation; does not generate or send a message.

        调度决策及原子预留，不生成或发送消息。
        """
        rt = runtime(turn_id)
        with rt.storage.transaction():
            rt.advance(character_id)
            return rt.companion.decide(character_id, reservation_id).model_dump(mode="json")

    @server.tool(annotations=write)
    @safe
    def proactive_prepare(
        session_id: Identifier, decision_id: Identifier, turn_id: Identifier | None = None
    ) -> dict[str, Any]:
        """Claim one generation attempt with assembled context; never sends a message.

        使用已组装上下文领取一次生成尝试，不发送消息。
        """
        rt = runtime(turn_id)
        with rt.storage.transaction():
            session = rt.knowledge.scope(session_id)
            assert session.character_id is not None
            decision = rt.companion.prepare(session.character_id, decision_id)
            result = {"decision": decision.model_dump(mode="json")}
            if decision.should_contact:
                result["context"] = rt.context(session_id, decision.topic)
            return result

    @server.tool(annotations=write)
    @safe
    def proactive_delivery(
        character_id: Identifier,
        decision_id: Identifier,
        claim_id: Identifier,
        turn_id: Identifier | None = None,
        binding_revision: int | None = None,
    ) -> dict[str, Any]:
        """Claim existing proactive delivery and endpoint authority atomically.

        在同一事务中取得既有主动投递权与 Endpoint 发送权，不创建第二套主动引擎。
        """
        rt = runtime(turn_id)
        with rt.storage.transaction():
            receipt = None
            if rt.actor:
                if binding_revision is None:
                    raise ValueError("Scoped delivery requires the current binding revision")
                receipt = ScopeResolver(storage, rt.owner).claim_delivery(
                    rt.actor.platform_binding,
                    decision_id,
                    rt.actor.host,
                    binding_revision,
                )
                if receipt is None:
                    raise ValueError("Delivery was already claimed; do not resend")
            decision = rt.companion.delivery(character_id, decision_id, claim_id)
            if rt.actor and not decision.should_contact:
                assert receipt is not None
                ScopeResolver(storage, rt.owner).ack_delivery(
                    rt.actor.platform_binding,
                    decision_id,
                    rt.actor.host,
                    receipt["claim_id"],
                    False,
                )
            result = decision.model_dump(mode="json")
            if receipt:
                result["endpoint_claim_id"] = receipt["claim_id"]
            return result

    @server.tool(annotations=write)
    @safe
    def proactive_ack(
        character_id: Identifier,
        decision_id: Identifier,
        delivered: bool | None,
        claim_id: Identifier | None = None,
        turn_id: Identifier | None = None,
        endpoint_claim_id: Identifier | None = None,
    ) -> dict[str, Any]:
        """Acknowledge both ledgers together; unknown never grants another Host a resend.

        原子确认主动状态与 Endpoint 投递记录；未知结果不能让其他 Host 重发。
        """
        rt = runtime(turn_id)
        with rt.storage.transaction():
            if rt.actor:
                if endpoint_claim_id is None:
                    raise ValueError("Scoped delivery acknowledgement requires endpoint claim")
                ScopeResolver(storage, rt.owner).ack_delivery(
                    rt.actor.platform_binding,
                    decision_id,
                    rt.actor.host,
                    endpoint_claim_id,
                    delivered,
                )
            return rt.companion.ack(character_id, decision_id, delivered, claim_id)

    @server.tool(annotations=read)
    @safe
    def memory_recall(
        session_id: Identifier,
        query: str = "",
        real: bool = False,
        request: RecallRequest | None = None,
    ) -> dict[str, Any]:
        """Scoped recall; OOC returns current mutation allowlists. Retrieval never reinforces.

        按作用域召回；OOC 返回当前修改授权；召回本身不强化证据。
        """
        rt = runtime()
        with rt.storage.transaction():
            session = rt.knowledge.scope(session_id)
            assert session.character_id is not None
            cid = session.character_id
            memories = rt.memory.recall(
                cid, query, session_id=session.id, real=real, request=request
            )
            facts = [
                f
                for f in rt.knowledge.records("fact", cid)
                if f.get("validity") == "active" and (real or f.get("subject") != "owner")
            ]
            projected, decisions = rt.memory.project(cid, memories, query=query, recall=request)
            result: dict[str, Any] = {
                # OOC maintenance can inspect authorized originals; ordinary generation cannot.
                # OOC 维护可审阅已授权规范记录；普通生成只接收使用策略允许的投影。
                "memories": [m.model_dump(mode="json") for m in memories]
                if session.ooc
                else projected,
                "memory_use_decisions": decisions,
                "facts": facts,
            }
            result["use_policy"] = {
                "legacy": "unverified history, not new evidence",
                "simulation": "label explicitly; never user experience",
                "facts": "only active facts are current; preserve provenance",
                "quotes": "quote only exact original RawEvent content",
            }
            if request and request.intent in {"EXACT_QUOTE", "EXACT_RECALL"}:
                result["raw_events"] = rt.knowledge.recall_events(cid, request, query)
                result["quotes"] = result["raw_events"]
            if request and request.intent in ("CURRENT_STATE", "GOAL", "OPEN_LOOP"):
                companion = rt.companion.get(cid)
                result["current_state"] = {
                    "goals": [
                        g.model_dump(mode="json") for g in companion.goals if g.status == "active"
                    ],
                    "open_loops": [
                        t.model_dump(mode="json") for t in companion.topics if t.status == "open"
                    ],
                    "relationship": rt.knowledge.relationship.projection(cid)
                    if rt.actor is None or rt.actor.private_context_allowed
                    else {},
                }
            if session.ooc:
                ops = rt.knowledge.operations(cid)
                result["allowlists"] = {}
                if memories:
                    result["allowlists"]["memory"] = ops.issue_allowlist(
                        "memory",
                        [m.id for m in memories],
                        ["CORRECT", "FORGET", "ARCHIVE", "UPDATE"],
                        session_id=session.id,
                    )
                if facts:
                    result["allowlists"]["fact"] = ops.issue_allowlist(
                        "fact", [f["id"] for f in facts][:100], ["SUPERSEDE"], session_id=session.id
                    )
            return result

    @server.tool(annotations=write)
    @safe
    def memory_write(request: MemoryWrite) -> dict[str, Any]:
        """2.x evidence-backed creation; edits require OOC plus a memory_recall allowlist.

        2.x 创建必须有证据；编辑须处于 OOC 并携带 memory_recall 授权。
        """
        operation = require_operation(request.operation_id)
        rt = runtime()
        with rt.storage.transaction():
            scoped(rt, request.session_id, request.character_id, ooc=request.action != "store")
            if request.action == "store":
                if request.proposal is None:
                    raise ValueError(
                        "compatibility_error: ingest events then supply a MemoryProposal"
                    )
                return rt.commit_turn(
                    request.session_id,
                    TurnProposal(operation_id=operation, memory_proposals=[request.proposal]),
                )
            if not request.memory_id or not request.allowlist_id:
                raise ValueError("memory_id and allowlist_id are required")
            return rt.knowledge.mutate(
                MemoryMutation.model_validate(
                    {
                        "operation_id": operation,
                        "session_id": request.session_id,
                        "memory_id": request.memory_id,
                        "allowlist_id": request.allowlist_id,
                        "action": request.action.upper(),
                        "content": request.content,
                        "evidence_refs": request.evidence_refs,
                        "confirmation": request.confirmation,
                    }
                )
            )

    @server.tool(annotations=write)
    @safe
    def memory_promote(
        session_id: Identifier,
        memory_id: Identifier,
        confirmation: str,
        operation_id: Identifier | None = None,
        allowlist_id: Identifier | None = None,
    ) -> dict[str, Any]:
        """Explicit OOC promotion with direct user evidence and a fresh target grant.

        显式 OOC 提升，要求直接用户证据及新鲜目标授权。
        """
        operation = require_operation(operation_id)
        if not allowlist_id:
            raise ValueError("A fresh memory_recall allowlist is required")
        return runtime().knowledge.mutate(
            MemoryMutation(
                operation_id=operation,
                session_id=session_id,
                memory_id=memory_id,
                allowlist_id=allowlist_id,
                action="PROMOTE",
                confirmation=confirmation,
            )
        )

    @server.tool(annotations=write)
    @safe
    def turn_commit(
        session_id: Identifier,
        proposal: TurnProposal | None = None,
        turn_id: Identifier | None = None,
        candidates: list[Candidate] | None = None,
    ) -> dict[str, Any]:
        """Commit a 2.x TurnProposal atomically; old writes return compatibility errors.

        原子提交 2.x 回合提案；旧写入返回兼容错误。
        """
        if proposal is None or turn_id is not None or candidates is not None:
            raise ValueError(
                "compatibility_error: call event_ingest then turn_commit(session_id, "
                "proposal={operation_id,memory_proposals,fact_proposals,narrative_proposals})"
            )
        return runtime().commit_turn(session_id, proposal)

    @server.tool(annotations=write)
    @safe
    def event_ingest(request: EventBatch) -> dict[str, Any]:
        """Persist visible events once by stable source identity; never hidden reasoning.

        按稳定源身份只保存一次可见事件，不保存隐藏推理。
        """
        return runtime().knowledge.ingest(request)

    @server.tool(annotations=write)
    @safe
    def identity_control(
        host: Identifier,
        platform: Identifier,
        actor_id: Identifier,
        operation_id: Identifier,
        confirmation: str,
        participant_id: Identifier | None = None,
    ) -> dict[str, Any]:
        """Bind stable platform actors to participants under authenticated owner authority.

        由认证 Owner 将稳定平台 Actor 显式绑定到 Participant，不使用昵称猜测。
        """
        rt = runtime()
        return bind(
            storage,
            rt.owner,
            host,
            platform,
            actor_id,
            operation_id,
            confirmation,
            participant_id=participant_id,
        )

    @server.tool(annotations=write)
    @safe
    def endpoint_bind(
        platform: Identifier,
        endpoint: Identifier,
        kind: Literal["dm", "group"],
        default_character_id: Identifier,
        operation_id: Identifier,
        confirmation: str,
        participant_id: Identifier | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        """Owner configures an endpoint explicitly; a DM has exactly one recipient.

        Owner 显式配置 Endpoint；私聊必须指定唯一 Participant，群聊不能绑定私人受众。
        """
        rt = runtime()
        return ScopeResolver(storage, rt.owner).bind_endpoint(
            platform,
            endpoint,
            kind,
            default_character_id,
            participant_id=participant_id,
            operation_id=operation_id,
            confirmation=confirmation,
            expected_revision=expected_revision,
        )

    @server.tool(annotations=write)
    @safe
    def character_route_bind(
        endpoint_id: Identifier,
        character_id: Identifier,
        operation_id: Identifier,
        confirmation: str,
        participant_id: Identifier | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        """Authorize a route without changing the endpoint default or active session.

        授权可用角色路由；不会修改 Endpoint 默认角色或当前 Session。
        """
        rt = runtime()
        return ScopeResolver(storage, rt.owner).bind_route(
            endpoint_id,
            participant_id,
            character_id,
            operation_id=operation_id,
            confirmation=confirmation,
            expected_revision=expected_revision,
        )

    @server.tool(annotations=write)
    @safe
    def delivery_bind(
        endpoint_id: Identifier,
        host: Identifier,
        adapter: Identifier,
        operation_id: Identifier,
        confirmation: str,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        """Configure the sole sender; unknown sends block authority handover.

        配置唯一发送者；存在未知投递结果时禁止交接发送权限。
        """
        rt = runtime()
        return ScopeResolver(storage, rt.owner).bind_delivery(
            endpoint_id,
            host,
            adapter,
            operation_id=operation_id,
            confirmation=confirmation,
            expected_revision=expected_revision,
        )

    @server.tool(annotations=write)
    @safe
    def growth_control(
        session_id: Identifier,
        action: Literal["history", "preview", "approve", "reject", "rollback"],
        target_id: Identifier | None = None,
        operation_id: Identifier | None = None,
        allowlist_id: Identifier | None = None,
    ) -> dict[str, Any]:
        """OOC growth review, approval and rollback; baseline remains unchanged.

        OOC 成长审查、批准及回滚，角色基线保持不变。
        """
        rt = runtime()
        with rt.storage.transaction():
            session = rt.knowledge.scope(session_id, ooc=True)
            assert session.character_id is not None
            cid = session.character_id
            ops, growth = rt.knowledge.operations(cid), rt.knowledge.growth
            if action in ("history", "preview"):
                candidates = rt.knowledge.records("growth_candidate", cid)
                versions = rt.knowledge.records("growth_version", cid)
                result: dict[str, Any] = {
                    "candidates": candidates,
                    "versions": versions,
                    "current_version": growth.current(cid)[0],
                    "allowlists": {},
                }
                pending = [c["id"] for c in candidates if c["status"] == "pending"]
                if pending:
                    result["allowlists"]["candidate"] = ops.issue_allowlist(
                        "growth_candidate", pending[:100], ["UPDATE"], session_id=session_id
                    )
                if versions:
                    result["allowlists"]["version"] = ops.issue_allowlist(
                        "growth_version",
                        [v["id"] for v in versions][-100:],
                        ["ROLLBACK"],
                        session_id=session_id,
                    )
                return result
            operation = require_operation(operation_id)
            if not target_id or not allowlist_id:
                raise ValueError("Target ID and growth_control allowlist are required")

            def apply() -> dict[str, Any]:
                collection = "growth_version" if action == "rollback" else "growth_candidate"
                ops.consume_allowlist(
                    allowlist_id,
                    "ROLLBACK" if action == "rollback" else "UPDATE",
                    [target_id],
                    collection=collection,
                    session_id=session_id,
                )
                if action == "approve":
                    return growth.approve(cid, target_id, explicit=True)
                if action == "rollback":
                    return growth.rollback(cid, target_id)
                candidate = rt.storage.get(rt.owner, "growth_candidate", target_id)
                if not candidate or candidate["status"] != "pending":
                    raise ValueError("Pending candidate required")
                candidate["status"] = "rejected"
                rt.storage.put(rt.owner, "growth_candidate", target_id, candidate)
                return {"candidate_id": target_id, "status": "rejected"}

            return ops.execute(
                operation,
                {"action": action, "target_id": target_id, "allowlist_id": allowlist_id},
                apply,
                domain="growth",
                operation="UPDATE",
                target_ids=[target_id],
                authority="USER_EXPLICIT",
            )

    @server.tool(annotations=write)
    @safe
    def perception_observe(
        session_id: Identifier,
        action: Literal["read", "observe", "propose", "confirm", "reject"],
        operation_id: Identifier | None = None,
        observation: PerceptionObservation | None = None,
        prototype: VisualPrototype | None = None,
        target_id: Identifier | None = None,
        allowlist_id: Identifier | None = None,
        confirmation_evidence: list[Identifier] | None = None,
    ) -> dict[str, Any]:
        """Media perception and visual candidates; only explicit OOC confirmation grants trust.

        媒体感知及视觉候选；只有显式 OOC 确认能授予相应信任。
        """
        rt = runtime()
        with rt.storage.transaction():
            session = rt.knowledge.scope(session_id, ooc=action in ("confirm", "reject"))
            assert session.character_id is not None
            cid, ops = session.character_id, rt.knowledge.operations(session.character_id)
            if action == "read":
                records = rt.knowledge.records("visual_prototype", cid)
                result: dict[str, Any] = {"prototypes": records}
                if records and session.ooc:
                    result["allowlist"] = ops.issue_allowlist(
                        "visual_prototype",
                        [p["id"] for p in records],
                        ["UPDATE"],
                        session_id=session_id,
                    )
                return result
            operation = require_operation(operation_id)
            payload = {
                "action": action,
                "session_id": session_id,
                "observation": observation.model_dump(mode="json", exclude_unset=True)
                if observation
                else None,
                "prototype": prototype.model_dump(mode="json", exclude_unset=True)
                if prototype
                else None,
                "target_id": target_id,
                "allowlist_id": allowlist_id,
                "confirmation_evidence": confirmation_evidence,
            }

            def apply() -> dict[str, Any]:
                if action == "observe":
                    if not observation or observation.character_id != cid:
                        raise ValueError("An observation matching the active character is required")
                    observation.id = fingerprint([cid, operation, "perception"])
                    return rt.knowledge.lifelike.observe(observation)
                if action == "propose":
                    if not prototype:
                        raise ValueError("Prototype proposal is required")
                    prototype.id = fingerprint([cid, operation, "prototype"])
                    return rt.knowledge.lifelike.prototype(cid, prototype, explicit=False)
                if not target_id or not allowlist_id:
                    raise ValueError("Read perception_observe for a fresh target allowlist")
                ops.consume_allowlist(
                    allowlist_id,
                    "UPDATE",
                    [target_id],
                    collection="visual_prototype",
                    session_id=session_id,
                )
                record = rt.storage.get(rt.owner, "visual_prototype", target_id)
                assert record is not None
                if action == "confirm":
                    evidence = rt.knowledge.evidence(cid, confirmation_evidence or [])
                    if any(e.source_kind != "USER_DIRECT" for e in evidence):
                        raise ValueError(
                            "Visual confirmation requires explicit direct user evidence"
                        )
                    record.update(
                        status="trusted",
                        authority="USER_EXPLICIT",
                        evidence_refs=list(
                            dict.fromkeys(record["evidence_refs"] + (confirmation_evidence or []))
                        ),
                    )
                else:
                    record["status"] = "rejected"
                rt.storage.put(rt.owner, "visual_prototype", target_id, record)
                return {"prototype_id": target_id, "status": record["status"]}

            return ops.execute(
                operation,
                payload,
                apply,
                domain="perception",
                operation="CREATE" if action in ("observe", "propose") else "UPDATE",
            )

    @server.tool(annotations=write)
    @safe
    def runtime_doctor(
        session_id: Identifier, maintenance_operation_id: Identifier | None = None
    ) -> dict[str, Any]:
        """Inspect scoped integrity statistics without exposing private record bodies.

        检查作用域完整性统计，不暴露私人记录正文。
        """
        rt = runtime()
        session = rt.knowledge.scope(session_id)
        assert session.character_id is not None
        if maintenance_operation_id:
            from .maintenance import run

            if not session.ooc:
                raise ValueError("Explicit maintenance requires OOC")
            run(rt, session.character_id, maintenance_operation_id)
        return diagnose(rt.knowledge, session.character_id)

    @server.tool(annotations=read)
    @safe
    def context_explain(session_id: Identifier, query: str = "") -> dict[str, Any]:
        """Authenticated context budget/fingerprint statistics, without private content.

        认证后的上下文预算及指纹统计，不包含私人正文。
        """
        return dict(
            runtime().context(session_id, query).get("context_diagnostics", {"active": False})
        )

    @server.tool(annotations=read)
    @safe
    def character_export(
        character_id: Identifier,
        include_memories: bool = False,
        include_companion: bool = False,
        include_private_knowledge: bool = False,
    ) -> dict[str, Any]:
        """Export portable JSON. Include private character memory ONLY on explicit user opt-in.

        导出可迁移 JSON；携带私人角色记忆必须获得用户显式选择。
        """
        return export_character(
            runtime(),
            character_id,
            include_memories=include_memories,
            include_companion=include_companion,
            include_private_knowledge=include_private_knowledge,
        ).model_dump(mode="json")

    @server.tool(annotations=write)
    @safe
    def character_import(
        package: Package | PackageV2 | PackageV3,
        operation_id: Identifier | None = None,
        sensitive_confirmation: str = "",
    ) -> dict[str, Any]:
        """Import conservatively once; evidence and grants never acquire trust through packages.

        保守幂等导入；包不能让证据或授权自动提高信任。
        """
        operation = require_operation(operation_id)
        rt = runtime()
        payload = package.model_dump(mode="json")
        digest = fingerprint({"package": payload, "consent": sensitive_confirmation})
        with rt.storage.transaction():
            receipt = rt.storage.get(rt.owner, "import_receipt", operation)
            if receipt:
                if receipt["fingerprint"] != digest:
                    raise ValueError("Import operation ID was reused for different data")
                return {"id": receipt["character_id"]}
            definition = import_character(
                rt, payload, sensitive_confirmation=sensitive_confirmation
            )
            rt.storage.put(
                rt.owner,
                "import_receipt",
                operation,
                {"character_id": definition.id, "fingerprint": digest},
            )
            return rt.knowledge.operations(definition.id).execute(
                operation,
                {"package_digest": digest},
                lambda: {"id": definition.id},
                domain="package",
                operation="CREATE",
                authority="USER_MANUAL",
            )

    return server


def http_app(server: MCPServer[Any], host: str = "127.0.0.1", port: int = 8765) -> Starlette:
    """Build the authenticated HTTP resource server without publishing it.

    构建带认证的 HTTP 资源服务，不执行公开部署。
    """

    if server.settings.auth is None:
        raise ValueError("HTTP transport requires authentication")
    resource = urlsplit(str(server.settings.auth.resource_server_url))
    return server.streamable_http_app(
        json_response=True,
        stateless_http=True,
        max_request_body_size=10_000_000,
        host=host,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[f"{host}:{port}", f"localhost:{port}", resource.netloc],
            allowed_origins=[
                f"http://{host}:{port}",
                f"http://localhost:{port}",
                f"{resource.scheme}://{resource.netloc}",
            ],
        ),
    )
