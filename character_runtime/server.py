"""Thin MCP adapter over the same runtime used by every platform."""

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
from .auth import JWTVerifier, LocalTokenVerifier
from .companion_models import CompanionUpdate
from .diagnostics import diagnose
from .identity import bind
from .knowledge_models import EventBatch, MemoryMutation, MemoryProposal, TurnProposal
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
from .storage import Storage

P = ParamSpec("P")


def safe(fn: Callable[P, Any]) -> Callable[P, dict[str, Any]]:
    @wraps(fn)
    def call(*args: P.args, **kwargs: P.kwargs) -> dict[str, Any]:
        try:
            result = fn(*args, **kwargs)
            if isinstance(result, Model):
                result = result.model_dump(mode="json")
            return {"ok": True, "result": result}
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
    name: str | None = Field(default=None, min_length=1, max_length=100)
    origin: Literal["original", "ip"] | None = None
    mode: Mode | None = None
    default_task_mode: TaskMode | None = None
    growth: GrowthPolicy | None = None
    voice: VoiceProfile | None = None
    embodiment: EmbodimentProfile | None = None
    facts: dict[Identifier, Fact] | None = Field(default=None, max_length=100)


class CharacterWrite(Model):
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
    verifier: JWTVerifier | LocalTokenVerifier | None = None
    auth = None
    if issuer or audience or jwks_url:
        if providers:
            raise ValueError("Shared local provider files are limited to a single-owner Runtime")
        if not all((issuer, audience, jwks_url)):
            raise ValueError("OAuth issuer, audience and JWKS URL must all be configured")
        verifier = JWTVerifier(issuer or "", audience or "", jwks_url or "", resource)
    elif token:
        verifier = LocalTokenVerifier(token, local_owner, resource)
    if verifier:
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

    def runtime() -> Runtime:
        if verifier:
            access = get_access_token()
            if access is None or not access.subject:
                raise ValueError("Authenticated user identity is required")
            return Runtime(storage, access.subject, providers=providers)
        return Runtime(storage, local_owner, providers=providers)

    def scoped(rt: Runtime, session_id: str, character_id: str, *, ooc: bool = False) -> None:
        s = rt.session(session_id)
        if s.character_id != character_id:
            raise ValueError("Session is not active for this character")
        if ooc and not s.ooc:
            raise ValueError("Enter OOC before editing configuration or private memories")

    read = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
    write = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=False)

    @server.tool(annotations=read)
    @safe
    def character_read(
        character_id: Identifier | None = None, session_id: Identifier | None = None
    ) -> dict[str, Any]:
        """Read owned configuration; OOC session requests receive short-lived mutation targets."""
        rt = runtime()
        if character_id is None:
            return {
                "characters": [
                    {"id": c.id, "name": c.name, "mode": c.mode} for c in rt.characters.list()
                ]
            }
        result: dict[str, Any] = {
            "definition": rt.characters.get(character_id).model_dump(mode="json"),
            "state": rt.characters.state(character_id).model_dump(mode="json"),
        }
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
        """Create idempotently; OOC edits require a current character_read target grant."""
        operation = require_operation(request.operation_id)
        rt = runtime()
        with storage.transaction():
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
                existing = storage.get(rt.owner, "definition", definition.id)
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
        """Route sessions, switch characters, control OOC and temporary task mode."""
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
        """Load definition, state, relevant roleplay memories and runtime rules."""
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
        """OOC read issues an edit grant; updates require that grant and an operation ID."""
        rt = runtime()
        with storage.transaction():
            session = rt.knowledge.scope(session_id, ooc=True)
            assert session.character_id is not None
            cid = session.character_id
            state = rt.companion.get(cid)
            if storage.get(rt.owner, "companion", cid) is None:
                rt.companion._save(state)
            ops = rt.knowledge.operations(cid)
            if update is None:
                return {
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
    def provider_observe(
        session_id: Identifier, observation: Observation, operation_id: Identifier | None = None
    ) -> dict[str, Any]:
        """Supply sourced, expiring host observations, never credentials or user profile truth."""
        operation = require_operation(operation_id)
        rt = runtime()
        with storage.transaction():
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
        character_id: Identifier, reservation_id: Identifier | None = None
    ) -> dict[str, Any]:
        """Scheduler decision and atomic reservation; does not generate or send a message."""
        rt = runtime()
        with storage.transaction():
            rt.advance(character_id)
            return rt.companion.decide(character_id, reservation_id).model_dump(mode="json")

    @server.tool(annotations=write)
    @safe
    def proactive_prepare(session_id: Identifier, decision_id: Identifier) -> dict[str, Any]:
        """Claim one generation attempt with assembled context; never sends a message."""
        rt = runtime()
        with storage.transaction():
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
        character_id: Identifier, decision_id: Identifier, claim_id: Identifier
    ) -> dict[str, Any]:
        """Immediately before send, recheck eligibility and claim one delivery attempt."""
        return (
            runtime()
            .companion.delivery(character_id, decision_id, claim_id)
            .model_dump(mode="json")
        )

    @server.tool(annotations=write)
    @safe
    def proactive_ack(
        character_id: Identifier,
        decision_id: Identifier,
        delivered: bool | None,
        claim_id: Identifier | None = None,
    ) -> dict[str, Any]:
        """Acknowledge actual delivery; unknown delivery must not be retried automatically."""
        return runtime().companion.ack(character_id, decision_id, delivered, claim_id)

    @server.tool(annotations=read)
    @safe
    def memory_recall(
        session_id: Identifier,
        query: str = "",
        real: bool = False,
        request: RecallRequest | None = None,
    ) -> dict[str, Any]:
        """Scoped recall; OOC returns current mutation allowlists. Retrieval never reinforces."""
        rt = runtime()
        with storage.transaction():
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
            result: dict[str, Any] = {
                "memories": [m.model_dump(mode="json") for m in memories],
                "facts": facts,
            }
            result["use_policy"] = {
                "legacy": "unverified history, not new evidence",
                "simulation": "label explicitly; never user experience",
                "facts": "only active facts are current; preserve provenance",
                "quotes": "quote only exact original RawEvent content",
            }
            if request and request.intent == "EXACT_QUOTE":
                refs = list(dict.fromkeys(ref for m in memories for ref in m.evidence_refs))
                result["quotes"] = (
                    [
                        {"event_id": e.id, "content": e.content, "source_kind": e.source_kind}
                        for e in rt.knowledge.evidence(cid, refs[:20])
                    ]
                    if refs
                    else []
                )
            if request and request.intent in ("CURRENT_STATE", "GOAL", "OPEN_LOOP"):
                companion = rt.companion.get(cid)
                result["current_state"] = {
                    "goals": [
                        g.model_dump(mode="json") for g in companion.goals if g.status == "active"
                    ],
                    "open_loops": [
                        t.model_dump(mode="json") for t in companion.topics if t.status == "open"
                    ],
                    "relationship": rt.knowledge.relationship.projection(cid),
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
        """2.x evidence-backed creation; edits require OOC plus a memory_recall allowlist."""
        operation = require_operation(request.operation_id)
        rt = runtime()
        with storage.transaction():
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
        """Explicit OOC promotion with direct user evidence and a fresh target grant."""
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
        """Commit a 2.x TurnProposal atomically; old writes return compatibility errors."""
        if proposal is None or turn_id is not None or candidates is not None:
            raise ValueError(
                "compatibility_error: call event_ingest then turn_commit(session_id, "
                "proposal={operation_id,memory_proposals,fact_proposals,narrative_proposals})"
            )
        return runtime().commit_turn(session_id, proposal)

    @server.tool(annotations=write)
    @safe
    def event_ingest(request: EventBatch) -> dict[str, Any]:
        """Persist visible events once by stable source identity; never hidden reasoning."""
        return runtime().knowledge.ingest(request)

    @server.tool(annotations=write)
    @safe
    def identity_control(
        host: Identifier,
        platform: Identifier,
        actor_id: Identifier,
        operation_id: Identifier,
        confirmation: str,
    ) -> dict[str, Any]:
        """Bind a stable platform actor to the authenticated owner; never use nicknames."""
        rt = runtime()
        return bind(storage, rt.owner, host, platform, actor_id, operation_id, confirmation)

    @server.tool(annotations=write)
    @safe
    def growth_control(
        session_id: Identifier,
        action: Literal["history", "preview", "approve", "reject", "rollback"],
        target_id: Identifier | None = None,
        operation_id: Identifier | None = None,
        allowlist_id: Identifier | None = None,
    ) -> dict[str, Any]:
        """OOC growth review, approval and rollback; baseline remains unchanged."""
        rt = runtime()
        with storage.transaction():
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
                candidate = storage.get(rt.owner, "growth_candidate", target_id)
                if not candidate or candidate["status"] != "pending":
                    raise ValueError("Pending candidate required")
                candidate["status"] = "rejected"
                storage.put(rt.owner, "growth_candidate", target_id, candidate)
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
        """Media perception and visual candidates; only explicit OOC confirmation grants trust."""
        rt = runtime()
        with storage.transaction():
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
                record = storage.get(rt.owner, "visual_prototype", target_id)
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
                storage.put(rt.owner, "visual_prototype", target_id, record)
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
        """Inspect scoped integrity statistics without exposing private record bodies."""
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
        """Authenticated context budget/fingerprint statistics, without private content."""
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
        """Export portable JSON. Include private character memory ONLY on explicit user opt-in."""
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
        """Import conservatively once; evidence and grants never acquire trust through packages."""
        operation = require_operation(operation_id)
        rt = runtime()
        payload = package.model_dump(mode="json")
        digest = fingerprint({"package": payload, "consent": sensitive_confirmation})
        with storage.transaction():
            receipt = storage.get(rt.owner, "import_receipt", operation)
            if receipt:
                if receipt["fingerprint"] != digest:
                    raise ValueError("Import operation ID was reused for different data")
                return {"id": receipt["character_id"]}
            definition = import_character(
                rt, payload, sensitive_confirmation=sensitive_confirmation
            )
            storage.put(
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
