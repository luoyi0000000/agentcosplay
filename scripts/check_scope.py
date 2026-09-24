"""Exercise trusted identity, conversation routing and delivery authority locally.

本地验证可信身份、会话路由与投递权限；所有数据均为临时合成数据。
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from character_runtime.identity import bind
from character_runtime.knowledge_models import EventBatch, EventInput, MemoryProposal, TurnProposal
from character_runtime.memory import Memories
from character_runtime.models import Candidate, CharacterDefinition, MemoryScope, now
from character_runtime.packages import export_character, import_character
from character_runtime.persistence_models import RecallRequest
from character_runtime.runtime import Runtime
from character_runtime.scope import ScopeResolver
from character_runtime.storage import SQLiteStorage


def denied(action) -> None:
    """Require a closed authorization failure. / 必须明确拒绝未授权操作。"""
    try:
        action()
    except (ValueError, KeyError):
        return
    raise AssertionError("Unauthorized operation succeeded")


def memory_policy_checks(path: Path) -> None:
    """Policy is ephemeral and cannot weaken audience authorization.

    使用策略只在单轮投影中存在，不能降低受众权限或修改规范记忆。
    """
    from character_runtime.persistence_models import GenerationRequest

    store = SQLiteStorage(path)
    try:
        rt = Runtime(store, "owner")
        cid = rt.characters.create(CharacterDefinition(name="policy")).id
        rt.open_session("policy", character_id=cid)
        memory = rt.memory.store(cid, Candidate(content="legacy-secret", importance=1))
        memory.legacy_unverified = True
        rt.memory._save(memory)
        before = store.get("owner", "memory", memory.id)
        assert "legacy-secret" not in str(rt.context("policy"))
        decision = rt.memory.use_decision(cid, memory)
        assert decision.access == "ALLOW" and decision.policy == "INTERNAL_ONLY"
        assert (
            rt.memory.use_decision(
                cid, memory, recall=RecallRequest(intent="AUTOBIOGRAPHICAL")
            ).policy
            == "UNCERTAIN"
        )
        assert before == store.get("owner", "memory", memory.id)
        raw = rt.knowledge.ingest(
            EventBatch(
                session_id="policy",
                operation_id="original",
                events=[
                    EventInput(
                        source_id="original",
                        source_event_id="one",
                        source_kind="USER_DIRECT",
                        content="exact payload 4.32 GHz",
                        timestamp=now(),
                    )
                ],
            )
        )
        for intent in ("EXACT_QUOTE", "EXACT_RECALL"):
            events = rt.knowledge.recall_events(cid, RecallRequest(intent=intent), "payload")
            assert [e["content"] for e in events] == ["exact payload 4.32 GHz"]
        direct = rt.memory.store(cid, Candidate(content="paraphrase", importance=1))
        direct.authority, direct.evidence_refs = "USER_EXPLICIT", raw["event_ids"]
        rt.memory._save(direct)
        assert rt.memory.use_decision(cid, direct).policy == "DIRECT"
        assert (
            rt.knowledge.recall_events(cid, RecallRequest(intent="EXACT_QUOTE"), "paraphrase") == []
        )
        foreign = memory.model_copy(
            update={
                "record_scope": MemoryScope(kind="PARTICIPANT_CHARACTER", participant_id="other")
            }
        )
        denied_decision = rt.memory.use_decision(cid, foreign)
        assert denied_decision.access == "DENY" and denied_decision.policy is None
        simulation = rt.memory.store(
            cid,
            Candidate(content="fictional-event-sentinel", source="simulated_life", importance=1),
        )
        assert rt.memory.use_decision(cid, simulation).policy == "TONE_ONLY"
        assert (
            rt.memory.use_decision(
                cid, simulation, generation=GenerationRequest(intent="ANALYSIS")
            ).policy
            == "INTERNAL_ONLY"
        )
        assert "fictional-event-sentinel" not in str(rt.context("policy"))
        inferred = rt.memory.store(cid, Candidate(content="inferred-sentinel", importance=1))
        assert rt.memory.use_decision(cid, inferred).policy == "UNCERTAIN"
        inferred.sensitivity = "sensitive"
        assert rt.memory.use_decision(cid, inferred, query="unrelated").policy == "INTERNAL_ONLY"
        inferred.status = "expired"
        assert (
            rt.memory.use_decision(cid, inferred, query="inferred-sentinel").policy
            == "INTERNAL_ONLY"
        )
    finally:
        store.close()
    print("PASS memory use: authorization first, ephemeral policy, legacy and tone isolation")


async def http_capabilities(path: Path) -> None:
    """Exercise real ASGI/MCP authentication and tool dispatch without external networking.

    经真实 ASGI/MCP 认证中间件与工具分发验证权限；无需外部网络或真实用户配置。
    """
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client

    from character_runtime.health import call, reject
    from character_runtime.server import build_server, http_app

    storage = SQLiteStorage(path)
    resource = "http://127.0.0.1:8765/mcp"
    owner_token = "synthetic-owner-token-for-local-check-only"
    server = build_server(storage, local_owner="owner", token=owner_token, resource=resource)
    app = http_app(server)

    def client(token):
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            headers={"Authorization": "Bearer " + token},
        )

    try:
        async with app.router.lifespan_context(app):
            async with (
                client(owner_token) as http,
                Client(streamable_http_client(resource, http_client=http)) as admin,
            ):
                cid = (
                    await call(
                        admin,
                        "character_write",
                        request={
                            "action": "create",
                            "operation_id": "create",
                            "definition": {"name": "shared"},
                        },
                    )
                )["id"]
                await call(
                    admin,
                    "identity_control",
                    host="hermes",
                    platform="qq",
                    actor_id="alice",
                    participant_id="alice",
                    operation_id="identity",
                    confirmation="Verified",
                )
                endpoint = await call(
                    admin,
                    "endpoint_bind",
                    platform="qq",
                    endpoint="group",
                    kind="group",
                    default_character_id=cid,
                    operation_id="endpoint",
                    confirmation="Explicit",
                )
                request = dict(
                    host="hermes",
                    platform="qq",
                    actor_id="alice",
                    endpoint_id=endpoint["id"],
                    session_id="conversation",
                    request_id="message-one",
                    event={
                        "source_kind": "USER_DIRECT",
                        "source_id": "platform",
                        "source_event_id": "one",
                        "content": "public-evidence",
                        "timestamp": now().isoformat(),
                    },
                )
                opened = await call(admin, "host_turn_open", **request)
                await reject(admin, "host_turn_open", **request, expected_endpoint_kind="dm")
                repeated = await call(admin, "host_turn_open", **request)
                assert repeated["turn_id"] == opened["turn_id"]
                assert repeated["ingestion"] == opened["ingestion"]
                tid = opened["turn_id"]
                compatibility = await admin.call_tool(
                    "companion_control",
                    {
                        "session_id": tid,
                        "update": {"mood": {"label": "happy", "intensity": 1, "reason": "legacy"}},
                    },
                )
                assert compatibility.structured_content["error"] == "LEGACY_MOOD_WRITE_UNSUPPORTED"
                assert compatibility.structured_content["read_only"] is True
                assert compatibility.structured_content["replacement"] == "AffectEffect"
                from unittest.mock import patch

                from character_runtime.host_client import HostBridge

                credential_file = path.parent / "synthetic-host-token"
                credential_file.write_text(owner_token, encoding="ascii")
                credential_file.chmod(0o600)
                bridge = HostBridge(resource, credential_file)
                original_client = httpx2.AsyncClient
                with patch(
                    "character_runtime.host_client.httpx2.AsyncClient",
                    side_effect=lambda **kwargs: original_client(
                        transport=httpx2.ASGITransport(app=app), **kwargs
                    ),
                ):
                    from character_runtime.hermes_adapter import HermesAdapter

                    native = HermesAdapter(
                        resource,
                        credential_file,
                        "hermes",
                        [
                            {
                                "platform": "qq",
                                "chat_id": "group",
                                "thread_id": "",
                                "chat_type": "group",
                                "runtime_platform": "qq",
                                "endpoint_id": endpoint["id"],
                                "kind": "group",
                            }
                        ],
                    )
                    native_context = await native.context(
                        {
                            "HERMES_SESSION_PLATFORM": "qq",
                            "HERMES_SESSION_CHAT_ID": "group",
                            "HERMES_SESSION_CHAT_TYPE": "group",
                            "HERMES_SESSION_USER_ID": "alice",
                        },
                        session_id="native",
                        turn_id="native-one",
                        sender_id="alice",
                        user_message="synthetic native task",
                    )
                    assert "Runtime session_id:" in native_context
                    await native.observe(
                        session_id="native",
                        turn_id="native-one",
                        assistant_response="synthetic result",
                    )
                    native_tid = native.turns[("native", "native-one")][1]
                    native_record = (
                        Runtime(storage, "owner")
                        .for_turn(native_tid)
                        .storage.get("owner", "turn_lifecycle", native_tid)
                    )
                    assert native_record["state"] == "finalized"
                    assert native_record["delivery_state"] == "unknown"
                    assert '"ok": true' in await native.tool(
                        "native", "native-one", "character_read", {"character_id": cid}
                    )
                    assert '"ok": false' in await native.tool(
                        "native", "native-one", "host_turn_open", request
                    )
                    projection = await bridge.model_call(
                        opened["capability"], tid, "runtime_context", {"session_id": tid}
                    )
                    assert projection["stable_prefix"]
                    for capability in ("", "invalid-capability"):
                        try:
                            await bridge.model_call(capability, tid, "character_read", {})
                        except (ValueError, RuntimeError) as error:
                            assert owner_token not in str(error)
                        else:
                            raise AssertionError("Host bridge fell back to owner authentication")
                from character_runtime.auth import LocalTokenVerifier

                discovery_token = LocalTokenVerifier(owner_token, "owner", resource).discovery_token
                assert discovery_token != owner_token
                async with (
                    client(discovery_token) as discovery_http,
                    Client(
                        streamable_http_client(resource, http_client=discovery_http)
                    ) as discovery,
                ):
                    assert (await discovery.list_tools()).tools
                    await reject(discovery, "runtime_context", session_id=tid)
                    await reject(discovery, "host_turn_open", **request)
                    await reject(discovery, "character_read")
                await call(
                    admin,
                    "host_companion_configure",
                    turn_id=tid,
                    operation_id="enable-proactive",
                    confirmation="Owner authorizes endpoint",
                    update={
                        "settings": {"proactive_contact": True, "quiet_start": 0, "quiet_end": 0},
                        "topic": {
                            "id": "followup",
                            "description": "synthetic followup",
                            "priority": 1,
                            "relevance": 1,
                        },
                    },
                )
                delivery = await call(
                    admin,
                    "delivery_bind",
                    endpoint_id=endpoint["id"],
                    host="hermes",
                    adapter="synthetic",
                    operation_id="sender",
                    confirmation="Explicit",
                )
                decision = await call(admin, "proactive_decide", character_id=cid, turn_id=tid)
                assert decision["should_contact"]
                prepared = await call(
                    admin,
                    "proactive_prepare",
                    session_id=tid,
                    decision_id=decision["id"],
                    turn_id=tid,
                )
                proactive_claim = prepared["decision"]["claim_id"]
                await reject(
                    admin,
                    "proactive_delivery",
                    character_id=cid,
                    decision_id=decision["id"],
                    claim_id=proactive_claim,
                    turn_id=tid,
                    binding_revision=delivery["revision"] + 1,
                )
                sending = await call(
                    admin,
                    "proactive_delivery",
                    character_id=cid,
                    decision_id=decision["id"],
                    claim_id=proactive_claim,
                    turn_id=tid,
                    binding_revision=delivery["revision"],
                )
                assert sending["should_contact"]
                await call(
                    admin,
                    "proactive_ack",
                    character_id=cid,
                    decision_id=decision["id"],
                    claim_id=proactive_claim,
                    turn_id=tid,
                    endpoint_claim_id=sending["endpoint_claim_id"],
                    delivered=None,
                )
                await reject(
                    admin,
                    "delivery_bind",
                    endpoint_id=endpoint["id"],
                    host="astrbot",
                    adapter="synthetic",
                    operation_id="other-sender",
                    confirmation="switch",
                    expected_revision=delivery["revision"],
                )
                await reject(
                    admin,
                    "proactive_delivery",
                    character_id=cid,
                    decision_id=decision["id"],
                    claim_id=proactive_claim,
                    turn_id=tid,
                    binding_revision=delivery["revision"],
                )
                async with (
                    client(opened["capability"]) as turn_http,
                    Client(streamable_http_client(resource, http_client=turn_http)) as model,
                ):
                    await call(model, "runtime_context", session_id=tid)
                    assert "state" not in await call(model, "character_read", character_id=cid)
                    await reject(model, "runtime_context", session_id="other-session")
                    await reject(model, "host_turn_open", **request)
                    await reject(
                        model,
                        "host_response_plan",
                        turn_id=tid,
                        operation_id="model-forged-send",
                        response={"parts": ["forged"]},
                        request={},
                        capabilities={},
                    )
                    await reject(
                        model,
                        "identity_control",
                        host="hermes",
                        platform="qq",
                        actor_id="bob",
                        participant_id="alice",
                        operation_id="forged",
                        confirmation="pretend",
                    )
                    await reject(
                        model,
                        "event_ingest",
                        request={
                            "session_id": tid,
                            "operation_id": "forged-event",
                            "events": [request["event"]],
                        },
                    )
                    await call(
                        model,
                        "turn_commit",
                        session_id=tid,
                        proposal={
                            "operation_id": "remember",
                            "memory_proposals": [
                                {
                                    "content": "public-evidence",
                                    "evidence_refs": opened["ingestion"]["event_ids"],
                                    "explicit_remember": True,
                                }
                            ],
                        },
                    )
                    await call(model, "runtime_doctor", session_id=tid)
                    actor = storage.get("owner", "participant", "alice")
                    actor["active"] = False
                    storage.put("owner", "participant", "alice", actor)
                    await reject(model, "runtime_context", session_id=tid)
                    await reject(admin, "host_turn_open", **request)
                pieces = opened["capability"].split(".")
                pieces[1] = pieces[1][::-1]
                async with client(".".join(pieces)) as tampered:
                    response = await tampered.post(
                        resource, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
                    )
                    assert response.status_code == 401
    finally:
        storage.close()
    print("PASS HTTP capabilities: ingress retry, model limits, actor revocation, tamper rejection")


def main() -> None:
    """Check independent actors on a shared conversation and persistent send claims.

    验证共享会话中的独立说话人，以及重启后仍有效的发送去重。
    """
    with TemporaryDirectory(prefix="agentcosplay-scope-") as directory:
        memory_policy_checks(Path(directory) / "policy.sqlite3")
        asyncio.run(http_capabilities(Path(directory) / "http.sqlite3"))
        path = Path(directory) / "scope.sqlite3"
        stores = [SQLiteStorage(path), SQLiteStorage(path)]
        try:
            runtime = Runtime(stores[0], "owner")
            cid = runtime.characters.create(CharacterDefinition(name="shared")).id
            other = runtime.characters.create(CharacterDefinition(name="temporary")).id
            resolvers = [ScopeResolver(store, "owner") for store in stores]
            resolver = resolvers[0]
            for host in ("hermes", "astrbot"):
                for participant in ("alice", "bob"):
                    bind(
                        stores[0],
                        "owner",
                        host,
                        "qq",
                        participant,
                        host + participant,
                        "Verified synthetic identity",
                        participant_id=participant,
                    )
            denied(
                lambda: bind(
                    stores[0],
                    "owner",
                    "hermes",
                    "qq",
                    "alice",
                    "rebind",
                    "Cannot silently merge",
                    participant_id="bob",
                )
            )
            endpoint = resolver.bind_endpoint(
                "qq", "group", "group", cid, operation_id="endpoint", confirmation="Explicit"
            )
            kwargs = dict(
                host="hermes", platform="qq", endpoint_id=endpoint["id"], session_id="conversation"
            )
            denied(lambda: resolver.begin_turn(**kwargs, actor_id="unknown"))
            denied(
                lambda: runtime.open_session(
                    "legacy", character_id=cid, host="hermes", platform="qq", actor_id="alice"
                )
            )
            retried = resolver.begin_turn(**kwargs, actor_id="alice", request_id="stable-message")
            assert (
                resolver.begin_turn(**kwargs, actor_id="alice", request_id="stable-message")
                == retried
            )
            denied(
                lambda: resolver.begin_turn(**kwargs, actor_id="bob", request_id="stable-message")
            )
            alice = resolver.begin_turn(**kwargs, actor_id="alice")
            bob = resolver.begin_turn(**kwargs, actor_id="bob")
            assert alice.participant_id == "alice" and bob.participant_id == "bob"
            assert alice.session_id == bob.session_id and alice.character_id == cid
            assert alice.id != bob.id and not alice.private_context_allowed
            assert resolver.load_turn(alice.id).participant_id == "alice"
            denied(lambda: resolver.switch_character(alice.id, other))
            resolver.bind_route(
                endpoint["id"],
                None,
                other,
                operation_id="route",
                confirmation="Explicit shared session route",
            )
            resolver.switch_character(alice.id, other)
            denied(lambda: resolver.load_turn(bob.id))
            following = resolver.begin_turn(**kwargs, actor_id="bob")
            assert following.character_id == other
            assert (
                stores[0].get("owner", "platform_binding", endpoint["id"])["default_character_id"]
                == cid
            )
            delivery = resolver.bind_delivery(
                endpoint["id"],
                "hermes",
                "qq-adapter",
                operation_id="delivery",
                confirmation="Explicit",
            )
            with ThreadPoolExecutor(max_workers=2) as pool:
                claims = list(
                    pool.map(
                        lambda r: r.claim_delivery(
                            endpoint["id"], "decision", "hermes", delivery["revision"]
                        ),
                        resolvers,
                    )
                )
            assert sum(c is not None for c in claims) == 1
            claim = next(c for c in claims if c is not None)
            denied(
                lambda: resolver.ack_delivery(
                    endpoint["id"], "decision", "astrbot", claim["claim_id"], True
                )
            )
            resolver.ack_delivery(endpoint["id"], "decision", "hermes", claim["claim_id"], None)
            # Configuration retry is observational even after a send; it cannot grant a resend.
            # 发送后的配置重试只返回旧回执，不能获得新的重发权限。
            assert (
                resolver.bind_delivery(
                    endpoint["id"],
                    "hermes",
                    "qq-adapter",
                    operation_id="delivery",
                    confirmation="Explicit",
                )
                == delivery
            )
            denied(
                lambda: resolver.bind_delivery(
                    endpoint["id"],
                    "astrbot",
                    "qq-adapter",
                    operation_id="switch",
                    confirmation="Explicit",
                    expected_revision=delivery["revision"],
                )
            )
            assert (
                resolver.claim_delivery(endpoint["id"], "decision", "hermes", delivery["revision"])
                is None
            )
            stores[1].close()
            stores[1] = SQLiteStorage(path)
            assert (
                ScopeResolver(stores[1], "owner").claim_delivery(
                    endpoint["id"], "decision", "hermes", delivery["revision"]
                )
                is None
            )
            audiences = [
                None,
                MemoryScope(kind="PARTICIPANT_CHARACTER", participant_id="alice"),
                MemoryScope(kind="PARTICIPANT_CHARACTER", participant_id="bob"),
                MemoryScope(kind="ENDPOINT_CHARACTER", endpoint_id=endpoint["id"]),
            ]
            engines = [Memories(stores[0], "owner", runtime.characters, scope=s) for s in audiences]
            memories = [
                engine.store(cid, Candidate(content="scope sentinel " + str(i), importance=1))
                for i, engine in enumerate(engines)
            ]
            denied(lambda: engines[0]._save(memories[0].model_copy(update={"character_id": other})))
            supported_fts = stores[0].fts_available
            for i, engine in enumerate(engines):
                for fts in (supported_fts, False):
                    stores[0].fts_available = fts
                    assert [m.id for m in engine.recall(cid, "scope sentinel")] == [memories[i].id]
                    assert [
                        m.id for m in engine.recall(cid, request=RecallRequest(intent="RECENT"))
                    ] == [memories[i].id]
                    assert [
                        m[0]["id"]
                        for m in stores[0].memory_candidates(
                            "owner",
                            cid,
                            "scope sentinel",
                            session_id=None,
                            real=False,
                            at=now(),
                            scope=audiences[i],
                        )
                    ] == [memories[i].id]
                for j, memory in enumerate(memories):
                    if i != j:
                        denied(lambda m=memory: engine.owned(cid, m.id))
                        denied(lambda m=memory: engine._save(m))
                        forged = memories[i].model_copy(update={"id": memory.id})
                        denied(lambda m=forged: engine._save(m))
            stores[0].fts_available = supported_fts
            # Inaccessible matches must not consume any candidate lane's bounded capacity.
            # 无权访问的命中不能占用有限候选槽，避免先召回后过滤造成隔离或可用性缺陷。
            for i in range(80):
                engines[2].store(
                    cid, Candidate(content="scope sentinel crowd " + str(i), importance=1)
                )
            assert [
                r[0]["id"]
                for r in stores[0].memory_candidates(
                    "owner",
                    cid,
                    "scope sentinel",
                    session_id=None,
                    real=False,
                    at=now(),
                    scope=audiences[1],
                    limit=4,
                )
            ] == [memories[1].id]
            package = export_character(runtime, cid, include_memories=True)
            assert len(package.memories) == 1 and package.memories[0].record_scope is None
            imported = import_character(runtime, package.model_dump(mode="json"))
            assert runtime.memory.recall(imported.id)[0].record_scope is None
            bind(stores[0], "owner", "local", "test", "owner-actor", "owner-binding", "Verified")
            runtime.open_session(
                "revocation",
                character_id=cid,
                host="local",
                platform="test",
                actor_id="owner-actor",
            )
            person = stores[0].get("owner", "participant", "owner")
            assert person
            person["active"] = False
            stores[0].put("owner", "participant", "owner", person)
            denied(lambda: runtime.knowledge.scope("revocation"))
            # Exercise the same engine through two hosts and a public audience.
            # 两个 Host 与群聊均经过同一 Runtime；私有信息不能进入群聊 Context。
            dm = resolver.bind_endpoint(
                "qq",
                "alice-dm",
                "dm",
                cid,
                participant_id="alice",
                operation_id="dm",
                confirmation="Explicit",
            )
            turn = resolver.begin_turn(
                host="hermes",
                platform="qq",
                actor_id="alice",
                endpoint_id=dm["id"],
                session_id="private",
            )
            private_rt = runtime.for_turn(turn.id)
            private_rt.session_control(turn.id, "start_task", mode="task_neutral")
            continued = resolver.begin_turn(
                host="hermes",
                platform="qq",
                actor_id="alice",
                endpoint_id=dm["id"],
                session_id="private",
            )
            assert runtime.for_turn(continued.id).session(continued.id).task_mode == "task_neutral"
            private_rt.session_control(turn.id, "end_task")
            assert runtime.for_turn(continued.id).session(continued.id).task_mode is None
            raw = private_rt.knowledge.ingest(
                EventBatch(
                    session_id=turn.id,
                    operation_id="private-event",
                    events=[
                        EventInput(
                            source_id="private",
                            source_event_id="one",
                            source_kind="USER_DIRECT",
                            content="participant-private-sentinel",
                            timestamp=now(),
                        )
                    ],
                )
            )
            private_rt.commit_turn(
                turn.id,
                TurnProposal(
                    operation_id="private-memory",
                    memory_proposals=[
                        MemoryProposal(
                            content="participant-private-sentinel",
                            evidence_refs=raw["event_ids"],
                            explicit_remember=True,
                            importance=1,
                        )
                    ],
                ),
            )
            second = resolver.begin_turn(
                host="astrbot",
                platform="qq",
                actor_id="alice",
                endpoint_id=dm["id"],
                session_id="other-host",
            )
            assert "participant-private-sentinel" in str(
                runtime.for_turn(second.id).context(second.id)
            )
            private_rt.commit_turn(
                turn.id,
                TurnProposal.model_validate(
                    {
                        "operation_id": "adaptation",
                        "participant_adaptations": [
                            {
                                "dimension": "verbosity_default",
                                "value": "brief",
                                "evidence_refs": raw["event_ids"],
                            }
                        ],
                    }
                ),
            )
            assert (
                runtime.for_turn(second.id).knowledge.adaptation(cid)["verbosity_default"]
                == "brief"
            )
            assert runtime.knowledge.growth.current(cid)[0] == "baseline"
            group_turn = resolver.begin_turn(**kwargs, actor_id="alice")
            resolver.switch_character(group_turn.id, cid)
            group_turn = resolver.begin_turn(**kwargs, actor_id="alice")
            assert group_turn.character_id == second.character_id
            group_rt = runtime.for_turn(group_turn.id)
            assert "participant-private-sentinel" not in str(group_rt.context(group_turn.id))
            assert "private-calendar" not in str(group_rt.context(group_turn.id))
            denied(lambda: group_rt.characters.update(cid, name="poison"))
            # Denial must happen before reading, even for the current group actor.
            # 群聊即使知道当前 Actor，也必须在读取任何私人持久状态前拒绝。
            for bucket in ("state", "relationship", "lifelike", "participant_adaptation"):
                denied(lambda b=bucket: group_rt.storage.get("owner", b, cid))
                denied(lambda b=bucket: group_rt.storage.list("owner", b))
            public_raw = group_rt.knowledge.ingest(
                EventBatch(
                    session_id=group_turn.id,
                    operation_id="public-event",
                    events=[
                        EventInput(
                            source_id="group",
                            source_event_id="one",
                            source_kind="USER_DIRECT",
                            content="endpoint-public-sentinel",
                            timestamp=now(),
                        )
                    ],
                )
            )
            group_rt.commit_turn(
                group_turn.id,
                TurnProposal(
                    operation_id="public-memory",
                    memory_proposals=[
                        MemoryProposal(
                            content="endpoint-public-sentinel",
                            evidence_refs=public_raw["event_ids"],
                            explicit_remember=True,
                            importance=1,
                        )
                    ],
                ),
            )
            group_bob = resolver.begin_turn(
                host="astrbot",
                platform="qq",
                actor_id="bob",
                endpoint_id=endpoint["id"],
                session_id="cross-host-group",
            )
            bob_runtime = runtime.for_turn(group_bob.id)
            bob_context = bob_runtime.context(group_bob.id)
            assert "endpoint-public-sentinel" in str(bob_context)
            assert "participant-private-sentinel" not in str(bob_context)
            denied(lambda: bob_runtime.knowledge.personal_evidence(cid, public_raw["event_ids"]))
            denied(
                lambda: bob_runtime.commit_turn(
                    group_bob.id,
                    TurnProposal.model_validate(
                        {
                            "operation_id": "foreign-adaptation",
                            "participant_adaptations": [
                                {
                                    "dimension": "verbosity_default",
                                    "value": "brief",
                                    "evidence_refs": public_raw["event_ids"],
                                }
                            ],
                        }
                    ),
                )
            )
            denied(lambda: bob_runtime.knowledge.adaptation(cid))
            assert (
                bob_context["context_diagnostics"]["stable_prefix_fingerprint"]
                == private_rt.context(turn.id)["context_diagnostics"]["stable_prefix_fingerprint"]
            )
            private_rt.knowledge.forget(cid, private_rt.memory.recall(cid)[0])
            assert "participant-private-sentinel" not in str(
                runtime.for_turn(second.id).context(second.id)
            )
            assert runtime.for_turn(second.id).knowledge.adaptation(cid) == {}
            print(
                "PASS scope: identity, turn actor, session switch, authority, restart, "
                "pre-retrieval audience, portable privacy"
            )
        finally:
            for store in stores:
                store.close()


if __name__ == "__main__":
    main()
