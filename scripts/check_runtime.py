"""Native synthetic Runtime acceptance: evidence, identity, growth and delivery recovery."""

import asyncio
import json
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from character_runtime.companion_models import CompanionUpdate, SettingsUpdate, TopicUpdate
from character_runtime.health import call, protocol_check, reject
from character_runtime.models import CharacterDefinition
from character_runtime.runtime import Runtime
from character_runtime.safety import check_content
from character_runtime.storage import SQLiteStorage


def safety_boundaries() -> None:
    """Random hexadecimal IDs are not personal numbers; standalone numbers remain gated.

    随机十六进制标识符不是个人号码；独立号码仍必须通过敏感信息授权。
    """
    check_content('{"id":"abcdef123456789012345678abcdef12"}')
    for content in ("123456789012345678", "号码12345678901234567X。", "123-45-6789"):
        try:
            check_content(content)
        except ValueError:
            pass
        else:
            raise AssertionError("Sensitive standalone number was accepted")


async def advanced(client: Client) -> None:
    cid = (
        await call(
            client,
            "character_write",
            request={
                "action": "create",
                "operation_id": "advanced-create",
                "definition": {"name": "synthetic-persistence"},
            },
        )
    )["id"]
    await call(
        client,
        "session_control",
        request={"action": "open", "session_id": "advanced", "character_id": cid},
    )
    await call(
        client,
        "session_control",
        request={
            "action": "open",
            "session_id": "unbound",
            "character_id": cid,
            "host": "synthetic",
            "platform": "test",
            "actor_id": "stable-id",
        },
    )
    await reject(client, "memory_recall", session_id="unbound")
    await call(
        client,
        "identity_control",
        host="synthetic",
        platform="test",
        actor_id="stable-id",
        operation_id="bind",
        confirmation="Explicit synthetic owner approval",
    )
    await call(
        client,
        "session_control",
        request={
            "action": "open",
            "session_id": "bound",
            "character_id": cid,
            "host": "synthetic",
            "platform": "test",
            "actor_id": "stable-id",
        },
    )
    instant = datetime.now(UTC)
    events = [
        {
            "source_id": "advanced",
            "source_event_id": str(i),
            "source_kind": "USER_DIRECT",
            "content": "我希望你表达更简洁。我喜欢苹果。",
            "timestamp": (instant - timedelta(days=i)).isoformat(),
        }
        for i in range(3)
    ]
    raw = await call(
        client,
        "event_ingest",
        request={"operation_id": "evidence", "session_id": "advanced", "events": events},
    )
    duplicate = await call(
        client,
        "event_ingest",
        request={"operation_id": "evidence-other-op", "session_id": "advanced", "events": events},
    )
    assert raw["event_ids"] == duplicate["event_ids"]
    await reject(
        client,
        "event_ingest",
        request={
            "operation_id": "changed-source",
            "session_id": "advanced",
            "events": [{**events[0], "content": "changed"}],
        },
    )
    await call(
        client,
        "event_ingest",
        request={
            "operation_id": "tool-metadata",
            "session_id": "advanced",
            "events": [
                {
                    **events[0],
                    "source_event_id": "tool",
                    "source_kind": "TOOL_RESULT",
                    "host": "synthetic-tool",
                    "content": "visible tool result",
                }
            ],
        },
    )
    await reject(
        client,
        "event_ingest",
        request={
            "operation_id": "unknown-platform-user",
            "session_id": "advanced",
            "events": [
                {
                    **events[0],
                    "source_event_id": "unknown-user",
                    "host": "synthetic-tool",
                    "content": "unverified direct speaker",
                }
            ],
        },
    )
    initial = await call(client, "runtime_context", session_id="advanced")
    proposal = {
        "operation_id": "low-growth",
        "growth_proposals": [
            {
                "changes": [{"domain": "voice", "key": "verbosity_default", "value": "brief"}],
                "evidence_refs": raw["event_ids"],
                "reason": "repeated explicit feedback",
            }
        ],
    }
    approved = await call(client, "turn_commit", session_id="advanced", proposal=proposal)
    assert approved == await call(client, "turn_commit", session_id="advanced", proposal=proposal)
    assert approved["growth_results"][0]["status"] == "approved"
    context = await call(client, "runtime_context", session_id="advanced")
    assert context["stable_prefix"] != initial["stable_prefix"]
    assert (await call(client, "character_read", character_id=cid))["definition"]["voice"][
        "verbosity_default"
    ] == "balanced"
    await reject(
        client,
        "turn_commit",
        session_id="advanced",
        proposal={
            "operation_id": "one-feedback",
            "growth_proposals": [
                {
                    "changes": [
                        {"domain": "voice", "key": "verbosity_default", "value": "detailed"}
                    ],
                    "evidence_refs": raw["event_ids"][:1],
                    "reason": "one",
                }
            ],
        },
    )
    high = await call(
        client,
        "turn_commit",
        session_id="advanced",
        proposal={
            "operation_id": "high-growth",
            "growth_proposals": [
                {
                    "changes": [{"domain": "personality", "key": "principle", "value": "patience"}],
                    "evidence_refs": raw["event_ids"],
                    "reason": "explicit proposal",
                }
            ],
        },
    )
    assert high["growth_results"][0]["status"] == "pending"
    await call(client, "session_control", request={"action": "enter_ooc", "session_id": "advanced"})
    history = await call(client, "growth_control", session_id="advanced", action="history")
    await call(
        client,
        "growth_control",
        session_id="advanced",
        action="approve",
        operation_id="approve-high",
        target_id=high["growth_results"][0]["candidate_id"],
        allowlist_id=history["allowlists"]["candidate"]["id"],
    )
    history = await call(client, "growth_control", session_id="advanced", action="history")
    await call(
        client,
        "growth_control",
        session_id="advanced",
        action="rollback",
        operation_id="rollback",
        target_id=approved["growth_results"][0]["version"],
        allowlist_id=history["allowlists"]["version"]["id"],
    )
    await reject(
        client,
        "turn_commit",
        session_id="advanced",
        proposal={**proposal, "operation_id": "cooldown"},
    )
    fact = await call(
        client,
        "turn_commit",
        session_id="advanced",
        proposal={
            "operation_id": "fact",
            "fact_proposals": [
                {
                    "semantic_key": "profile:fruit",
                    "subject": "owner",
                    "value": "喜欢苹果",
                    "evidence_refs": raw["event_ids"][:1],
                    "explicit_confirmation": "truth and storage",
                }
            ],
        },
    )
    correction = await call(
        client,
        "event_ingest",
        request={
            "operation_id": "correction-event",
            "session_id": "advanced",
            "events": [
                {**events[0], "source_event_id": "correction", "content": "我现在已经不喜欢苹果了"}
            ],
        },
    )
    recall = await call(client, "memory_recall", session_id="advanced", real=True)
    await call(
        client,
        "turn_commit",
        session_id="advanced",
        proposal={
            "operation_id": "correct-fact",
            "fact_proposals": [
                {
                    "semantic_key": "profile:fruit",
                    "subject": "owner",
                    "value": "不喜欢苹果",
                    "evidence_refs": correction["event_ids"],
                    "explicit_confirmation": "truth and storage",
                    "operation": "SUPERSEDE",
                    "target_id": fact["fact_ids"][0],
                    "allowlist_id": recall["allowlists"]["fact"]["id"],
                }
            ],
        },
    )
    facts = (await call(client, "memory_recall", session_id="advanced", real=True))["facts"]
    assert len(facts) == 1 and facts[0]["value"] == "不喜欢苹果"
    media = await call(
        client,
        "event_ingest",
        request={
            "operation_id": "media-event",
            "session_id": "advanced",
            "events": [
                {
                    **events[0],
                    "source_event_id": "media",
                    "source_kind": "MEDIA_DERIVED",
                    "content": "海边的角色插画",
                }
            ],
        },
    )
    await reject(
        client,
        "turn_commit",
        session_id="advanced",
        proposal={
            "operation_id": "media-fact",
            "fact_proposals": [
                {
                    "semantic_key": "event:beach",
                    "subject": "character",
                    "value": "海边",
                    "evidence_refs": media["event_ids"],
                }
            ],
        },
    )
    prototype = await call(
        client,
        "perception_observe",
        session_id="advanced",
        action="propose",
        operation_id="prototype",
        prototype={
            "character_id": cid,
            "source_ref": "asset:synthetic",
            "evidence_refs": media["event_ids"],
        },
    )
    observation = {
        "character_id": cid,
        "description": "媒体中的形象",
        "evidence_refs": media["event_ids"],
        "recognized": "SELF",
        "prototype_id": prototype["prototype_id"],
        "confidence": 0.99,
        "expires_at": (instant + timedelta(hours=1)).isoformat(),
    }
    untrusted = await call(
        client,
        "perception_observe",
        session_id="advanced",
        action="observe",
        operation_id="untrusted-media",
        observation=observation,
    )
    assert untrusted["recognized"] == "UNKNOWN"
    read = await call(client, "perception_observe", session_id="advanced", action="read")
    await call(
        client,
        "perception_observe",
        session_id="advanced",
        action="confirm",
        operation_id="confirm-prototype",
        target_id=prototype["prototype_id"],
        allowlist_id=read["allowlist"]["id"],
        confirmation_evidence=raw["event_ids"][:1],
    )
    trusted = await call(
        client,
        "perception_observe",
        session_id="advanced",
        action="observe",
        operation_id="trusted-media",
        observation=observation,
    )
    assert trusted["recognized"] == "SELF"
    result = await call(
        client, "runtime_doctor", session_id="advanced", maintenance_operation_id="maintain"
    )
    assert result["invalid_evidence_records"] == 0
    memory_proposals = [
        {"content": f"合成回忆{i}", "importance": 0.9, "evidence_refs": [raw["event_ids"][i]]}
        for i in range(3)
    ]
    await call(
        client,
        "turn_commit",
        session_id="advanced",
        proposal={
            "operation_id": "dated-memory",
            "memory_proposals": memory_proposals,
            "affect_effects": [{"valence": 0.2, "evidence_refs": correction["event_ids"]}],
        },
    )
    yesterday = await call(
        client,
        "memory_recall",
        session_id="advanced",
        request={"intent": "TIME_WINDOW", "relative_window": "yesterday", "timezone": "UTC"},
    )
    assert [m["content"] for m in yesterday["memories"]] == ["合成回忆1"]
    strict = await call(
        client,
        "runtime_context",
        session_id="advanced",
        generation={"intent": "CODING", "explicit_format": "json", "payload_only": True},
    )
    expression = next(
        f["payload"]["expression_policy"]
        for f in strict["temporary"]["state"]
        if "expression_policy" in f["payload"]
    )
    assert expression["catchphrase_density"] == "none" and expression["format"] == "json"
    default_package = await call(client, "character_export", character_id=cid)
    assert not default_package["raw_events"] and default_package["runtime_snapshot"] is None
    package = await call(
        client,
        "character_export",
        character_id=cid,
        include_memories=True,
        include_companion=True,
        include_private_knowledge=True,
    )
    imported = await call(
        client, "character_import", package=package, operation_id="advanced-import"
    )
    assert imported == await call(
        client, "character_import", package=package, operation_id="advanced-import"
    )
    await call(
        client,
        "session_control",
        request={"action": "open", "session_id": "imported", "character_id": imported["id"]},
    )
    imported_context = await call(client, "runtime_context", session_id="imported")
    prefix = json.loads(imported_context["stable_prefix"])
    assert prefix["growth_overlay"]["voice"]["verbosity_default"] == "brief"
    assert (await call(client, "memory_recall", session_id="imported"))["memories"] == []
    imported_memories = (
        await call(
            client, "memory_recall", session_id="imported", request={"intent": "AUTOBIOGRAPHICAL"}
        )
    )["memories"]
    assert all(m["use_decision"]["policy"] == "UNCERTAIN" for m in imported_memories)
    assert len(imported_memories) == 3 and all(m["legacy_unverified"] for m in imported_memories)
    await call(
        client,
        "turn_commit",
        session_id="advanced",
        proposal={
            "operation_id": "derived-goal",
            "companion_update": {
                "goal": {
                    "id": "derived-goal",
                    "description": "记忆派生的合成目标",
                    "evidence_ids": raw["event_ids"][:1],
                }
            },
        },
    )
    before_forget = await call(client, "memory_recall", session_id="advanced")
    selected = next(m for m in before_forget["memories"] if m["content"] == "合成回忆0")
    await call(
        client,
        "memory_write",
        request={
            "action": "forget",
            "operation_id": "forget-derived",
            "session_id": "advanced",
            "character_id": cid,
            "memory_id": selected["id"],
            "allowlist_id": before_forget["allowlists"]["memory"]["id"],
        },
    )
    after_forget = await call(client, "runtime_context", session_id="advanced")
    assert json.loads(after_forget["stable_prefix"])["growth_overlay"] == {}
    assert "记忆派生的合成目标" not in str(after_forget)
    assert all(
        p["payload"]["recognized"] != "SELF"
        for p in after_forget["temporary"].get("perception", [])
    )
    print("PASS erasure: goals, growth descendants, compiled cache, prototype recognition")
    print(
        "PASS persistence: temporal event dates, strict-format policy, private snapshot roundtrip"
    )
    print(
        "PASS protocol: identity fail-closed, source dedup, growth gate/rollback, "
        "correction, media provenance, maintenance"
    )


def recovery(root: Path) -> None:
    instant = datetime.now(UTC)
    stores = [SQLiteStorage(root / "recovery.sqlite3") for _ in range(2)]
    try:
        runtimes = [Runtime(s, "synthetic", clock=lambda: instant) for s in stores]
        rt = runtimes[0]
        cid = rt.characters.create(CharacterDefinition(name="synthetic-delivery")).id
        rt.companion.update(
            cid,
            CompanionUpdate(
                settings=SettingsUpdate(proactive_contact=True, quiet_start=0, quiet_end=0),
                topic=TopicUpdate(id="topic", description="合成跟进", priority=1, relevance=1),
            ),
        )
        decision = rt.companion.decide(cid)
        assert decision.should_contact
        assert decision.context["motive"] == "pending_followup"
        assert decision.context["opportunity"] == "idle_window"
        assert decision.context["basis"] == "configured intent, not a completed event"
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(
                pool.map(lambda runtime: runtime.companion.prepare(cid, decision.id), runtimes)
            )
        assert sum(c.should_contact for c in claims) == 1
        first = next(c for c in claims if c.should_contact)
        assert first.claim_id
        assert not runtimes[1].companion.prepare(cid, decision.id).should_contact
        with ThreadPoolExecutor(max_workers=2) as pool:
            deliveries = list(
                pool.map(
                    lambda runtime: runtime.companion.delivery(
                        cid, decision.id, first.claim_id or ""
                    ),
                    runtimes,
                )
            )
        assert sum(d.should_contact for d in deliveries) == 1
        assert not runtimes[1].companion.delivery(cid, decision.id, first.claim_id).should_contact
        rt.companion.ack(cid, decision.id, None, first.claim_id)
        assert not runtimes[1].companion.decide(cid, decision.id).should_contact
        state = rt.companion.get(cid)
        assert state.pending_decision and state.pending_decision.status == "unknown"
        # A separate character tests invalidation without confusing unknown delivery recovery.
        cid2 = rt.characters.create(CharacterDefinition(name="synthetic-invalidation")).id
        rt.companion.update(
            cid2,
            CompanionUpdate(
                settings=SettingsUpdate(proactive_contact=True, quiet_start=0, quiet_end=0),
                topic=TopicUpdate(id="topic", description="合成跟进", priority=1, relevance=1),
            ),
        )
        decision = rt.companion.decide(cid2)
        first = rt.companion.prepare(cid2, decision.id)
        rt.companion.record_activity(cid2)
        assert not rt.companion.delivery(cid2, decision.id, first.claim_id or "").should_contact
        # Equal relevant topics prefer the less recently mentioned one, after hard gates.
        # 同等相关话题在通过硬门之后优先较久未提及者，不绕过冷却或安静时段。
        from character_runtime.companion_models import Topic

        cid3 = rt.characters.create(CharacterDefinition(name="synthetic-recency")).id
        state = rt.companion.get(cid3)
        state.settings.proactive_contact = True
        state.settings.quiet_start = state.settings.quiet_end = 0
        state.topics = [
            Topic(
                id="old",
                description="older",
                priority=0.5,
                relevance=1,
                cooldown_seconds=86400,
                last_mentioned_at=instant - timedelta(days=3),
            ),
            Topic(
                id="recent",
                description="recent",
                priority=0.5,
                relevance=1,
                cooldown_seconds=86400,
                last_mentioned_at=instant - timedelta(days=1),
            ),
        ]
        rt.companion._save(state)
        assert rt.companion.decide(cid3).topic_id == "topic:old"
        print(
            "PASS recovery: single generation/send grant, unknown delivery quarantine, "
            "activity invalidation"
        )
    finally:
        for store in stores:
            store.close()


async def main() -> None:
    safety_boundaries()
    with tempfile.TemporaryDirectory(prefix="agentcosplay-acceptance-") as directory:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "character_runtime", "serve"],
            env={**os.environ, "CHARACTER_DATA_DIR": directory, "CHARACTER_OWNER": "synthetic"},
        )
        async with Client(params) as client:
            print("PASS core:", ", ".join(await protocol_check(client)))
            await advanced(client)
        recovery(Path(directory))
        print(json.dumps({"ok": True, "scope": "synthetic local Runtime acceptance"}))


if __name__ == "__main__":
    asyncio.run(main())
