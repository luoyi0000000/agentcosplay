"""Thin MCP adapter over the same runtime used by every platform."""

from collections.abc import Callable
from functools import wraps
from typing import Any, Literal, ParamSpec
from urllib.parse import urlsplit

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
from .models import (
    Candidate,
    CharacterDefinition,
    Fact,
    GrowthPolicy,
    GrowthProposal,
    Identifier,
    Mode,
    Model,
    Package,
    Relationship,
    TaskMode,
)
from .packages import PackageV2, export_character, import_character
from .providers import Observation, Provider
from .runtime import Runtime
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
                "message": "Input failed schema validation",
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
    facts: dict[Identifier, Fact] | None = Field(default=None, max_length=100)


class CharacterWrite(Model):
    action: Literal["create", "update", "relationship", "known_characters"]
    definition: CharacterDefinition | None = None
    character_id: Identifier | None = None
    session_id: Identifier | None = None
    patch: DefinitionPatch | None = None
    expected_revision: int | None = Field(default=None, ge=1)
    relationship: Relationship | None = None
    known_characters: list[Identifier] = Field(default_factory=list, max_length=100)


class SessionControl(Model):
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
    action: Literal["store", "modify", "forget", "share"]
    character_id: Identifier
    session_id: Identifier
    memory_id: Identifier | None = None
    candidate: Candidate | None = None
    content: str | None = Field(default=None, min_length=1, max_length=4000)
    recipients: list[Identifier] = Field(default_factory=list, max_length=100)


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
    def character_read(character_id: Identifier | None = None) -> dict[str, Any]:
        """List owned character summaries, or read one definition and relationship state."""
        rt = runtime()
        if character_id is None:
            return {
                "characters": [
                    {"id": c.id, "name": c.name, "mode": c.mode} for c in rt.characters.list()
                ]
            }
        return {
            "definition": rt.characters.get(character_id).model_dump(mode="json"),
            "state": rt.characters.state(character_id).model_dump(mode="json"),
        }

    @server.tool(annotations=write)
    @safe
    def character_write(request: CharacterWrite) -> dict[str, Any]:
        """Create characters or edit in OOC, preserving source priority and revisions."""
        rt = runtime()
        if request.action == "create":
            if request.definition is None:
                raise ValueError("A definition is required")
            return rt.characters.create(request.definition).model_dump(mode="json")
        if request.character_id is None or request.session_id is None:
            raise ValueError("Character and session IDs are required for editing")
        scoped(rt, request.session_id, request.character_id, ooc=True)
        if request.action == "update":
            if request.patch is None or request.expected_revision is None:
                raise ValueError("A patch and expected_revision are required")
            changes = request.patch.model_dump(exclude_none=True)
            facts = request.patch.facts
            changes.pop("facts", None)
            return rt.characters.update(
                request.character_id,
                facts=facts,
                expected_revision=request.expected_revision,
                **changes,
            ).model_dump(mode="json")
        if request.action == "relationship":
            if request.relationship is None or request.expected_revision is None:
                raise ValueError("Relationship and state revision are required")
            return rt.characters.configure_relationship(
                request.character_id, request.relationship, request.expected_revision
            ).model_dump(mode="json")
        return rt.characters.set_known_characters(
            request.character_id, request.known_characters
        ).model_dump(mode="json")

    @server.tool(annotations=write)
    @safe
    def session_control(request: SessionControl) -> dict[str, Any]:
        """Route sessions, switch characters, control OOC and temporary task mode."""
        rt = runtime()
        if request.action == "open":
            return rt.open_session(
                request.session_id, character_id=request.character_id, project=request.project
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
    ) -> dict[str, Any]:
        """Load definition, state, relevant roleplay memories and runtime rules."""
        return runtime().context(
            session_id,
            query,
            include_companion=include_companion,
            include_self_model=include_self_model,
        )

    @server.tool(annotations=write)
    @safe
    def companion_control(session_id: Identifier, update: CompanionUpdate) -> dict[str, Any]:
        """Explicit OOC companion configuration. Automatic mood/topics use turn_commit."""
        rt = runtime()
        session = rt.session(session_id)
        if session.character_id is None:
            raise ValueError("Choose a character first")
        scoped(rt, session_id, session.character_id, ooc=True)
        return rt.companion.update(session.character_id, update).model_dump(mode="json")

    @server.tool(annotations=write)
    @safe
    def provider_observe(session_id: Identifier, observation: Observation) -> dict[str, Any]:
        """Supply sourced, expiring host context; never provider credentials."""
        rt = runtime()
        session = rt.session(session_id)
        if session.character_id is None:
            raise ValueError("Choose a character first")
        rt.companion.observe(session.character_id, observation)
        return {"observed": observation.kind}

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
    def proactive_ack(
        character_id: Identifier, decision_id: Identifier, delivered: bool
    ) -> dict[str, Any]:
        """Acknowledge actual delivery; unknown delivery must not be retried automatically."""
        return runtime().companion.ack(character_id, decision_id, delivered)

    @server.tool(annotations=read)
    @safe
    def memory_recall(
        session_id: Identifier, query: str = "", real: bool = False
    ) -> dict[str, Any]:
        """Recall only the session character's authorized memories. Real facts are opt-in."""
        rt = runtime()
        session = rt.session(session_id)
        if session.character_id is None:
            raise ValueError("No active character")
        return {
            "memories": [
                m.model_dump(mode="json")
                for m in rt.memory.recall(
                    session.character_id, query, session_id=session.id, real=real
                )
            ]
        }

    @server.tool(annotations=write)
    @safe
    def memory_write(request: MemoryWrite) -> dict[str, Any]:
        """Store character memory. Edit/forget/share require OOC; never writes real facts."""
        rt = runtime()
        scoped(rt, request.session_id, request.character_id, ooc=request.action != "store")
        if request.action == "store":
            if request.candidate is None:
                raise ValueError("A candidate is required")
            return rt.memory.store(
                request.character_id, request.candidate, request.session_id
            ).model_dump(mode="json")
        if request.memory_id is None:
            raise ValueError("Memory ID is required")
        if request.action == "forget":
            rt.memory.forget(request.character_id, request.memory_id)
            return {"forgotten": request.memory_id}
        if request.action == "modify":
            if request.content is None:
                raise ValueError("Replacement content is required")
            return rt.memory.modify(
                request.character_id, request.memory_id, content=request.content
            ).model_dump(mode="json")
        return rt.memory.share(
            request.character_id, request.memory_id, request.recipients
        ).model_dump(mode="json")

    @server.tool(annotations=write)
    @safe
    def memory_promote(
        session_id: Identifier, memory_id: Identifier, confirmation: str
    ) -> dict[str, Any]:
        """Move to real-user memory after explicit confirmation of truth AND storage."""
        rt = runtime()
        session = rt.session(session_id)
        if session.character_id is None:
            raise ValueError("No active character")
        return rt.memory.promote(
            session.character_id, memory_id, confirmation=confirmation
        ).model_dump(mode="json")

    @server.tool(annotations=write)
    @safe
    def turn_commit(
        session_id: Identifier,
        turn_id: Identifier,
        candidates: list[Candidate],
        growth: GrowthProposal | None = None,
        companion: CompanionUpdate | None = None,
    ) -> dict[str, Any]:
        """Commit important memories and gradual growth once per turn ID."""
        return runtime().commit_turn(session_id, turn_id, candidates, growth, companion)

    @server.tool(annotations=read)
    @safe
    def character_export(
        character_id: Identifier, include_memories: bool = False, include_companion: bool = False
    ) -> dict[str, Any]:
        """Export portable JSON. Include private character memory ONLY on explicit user opt-in."""
        return export_character(
            runtime(),
            character_id,
            include_memories=include_memories,
            include_companion=include_companion,
        ).model_dump(mode="json")

    @server.tool(annotations=write)
    @safe
    def character_import(package: Package | PackageV2) -> dict[str, Any]:
        """Import V1/V2 data atomically, with fresh IDs and no external or proactive grants."""
        return import_character(runtime(), package.model_dump(mode="json")).model_dump(mode="json")

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
