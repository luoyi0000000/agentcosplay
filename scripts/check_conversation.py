"""Exercise semantic delivery plans and interruption with disposable runtime state.

在临时 Runtime 中验证语义发送计划、逐段确认与中断恢复。
"""

from datetime import timedelta
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
from unittest.mock import patch

from character_runtime.conversation import (
    ConversationBehaviorPlanner,
    ConversationDelivery,
    TurnIntakeBuffer,
    erase_response_context,
)
from character_runtime.conversation_models import EndpointCapabilities, SemanticResponse
from character_runtime.identity import bind
from character_runtime.knowledge_models import EventBatch, EventInput
from character_runtime.models import CharacterDefinition, now
from character_runtime.persistence_models import GenerationRequest
from character_runtime.runtime import Runtime
from character_runtime.scope import ScopeResolver
from character_runtime.storage import SQLiteStorage


def main() -> None:
    response = SemanticResponse(parts=["？？", "你真买了？", "给我看看"])
    caps = EndpointCapabilities(multiple_messages=True, typing=True)
    counts = set()
    for seed in range(150):
        plan = ConversationBehaviorPlanner(Random(seed)).plan(response, GenerationRequest(), caps)
        sent = [a.content for a in plan.actions if a.kind == "SEND_TEXT"]
        counts.add(len(sent))
        assert "\n\n".join(sent) == "\n\n".join(response.parts)
    assert counts == {1, 2, 3}
    code = SemanticResponse(parts=["说明。代码里也有句号。", '```python\nprint("a.b")\n```'])
    plan = ConversationBehaviorPlanner().plan(code, GenerationRequest(intent="CODING"), caps)
    assert len(plan.actions) == 1 and plan.actions[0].kind == "SEND_TEXT"
    assert 'print("a.b")' in plan.actions[0].content
    fallback = ConversationBehaviorPlanner().plan(
        response, GenerationRequest(), EndpointCapabilities()
    )
    assert len(fallback.actions) == 1
    for kind in ("REACTION", "STICKER"):
        answer = SemanticResponse(action=kind, content="ack", fallback_text="嗯")
        plan = ConversationBehaviorPlanner().plan(
            answer, GenerationRequest(), EndpointCapabilities()
        )
        assert plan.actions[-1].kind == "SEND_TEXT" and plan.actions[-1].content == "嗯"
    silence = ConversationBehaviorPlanner().plan(
        SemanticResponse(action="SILENCE"), GenerationRequest(), caps
    )
    assert [a.kind for a in silence.actions] == ["SILENCE"]
    with TemporaryDirectory(prefix="agentcosplay-segments-") as directory:
        path = Path(directory) / "runtime.sqlite3"
        store = SQLiteStorage(path)
        instant = [now()]
        try:
            rt = Runtime(store, "owner", clock=lambda: instant[0])
            cid = rt.characters.create(CharacterDefinition(name="delivery")).id
            bind(store, "owner", "hermes", "test", "actor", "bind", "Verified")
            resolver = ScopeResolver(store, "owner", lambda: instant[0])
            endpoint = resolver.bind_endpoint(
                "test",
                "dm",
                "dm",
                cid,
                participant_id="owner",
                operation_id="endpoint",
                confirmation="Explicit",
            )
            resolver.bind_delivery(
                endpoint["id"], "hermes", "test", operation_id="sender", confirmation="Explicit"
            )
            args = dict(
                host="hermes",
                platform="test",
                actor_id="actor",
                endpoint_id=endpoint["id"],
                session_id="chat",
            )
            turn = resolver.begin_turn(**args)
            delivery = ConversationDelivery(rt)
            answer = SemanticResponse(parts=["segment0", "segment1", "segment2"])
            request = GenerationRequest(intent="ANALYSIS")
            capability = EndpointCapabilities(multiple_messages=True, max_text_chars=8)
            plan = delivery.create(turn.id, "reply", answer, request, capability)
            assert delivery.create(turn.id, "reply", answer, request, capability) == plan
            assert len(plan["segments"]) == 3
            assert delivery.claim(plan["id"], 1) is None
            claim = delivery.claim(plan["id"], 0)
            assert claim and delivery.claim(plan["id"], 0) is None
            ack = delivery.acknowledge(
                plan["id"], 0, claim["claim_id"], True, visible_content="segment0"
            )
            assert ack == delivery.acknowledge(
                plan["id"], 0, claim["claim_id"], True, visible_content="segment0"
            )
            event = rt.for_turn(turn.id).knowledge.records("raw_event", cid)[0]
            assert (
                event["content"] == "segment0"
                and event["segment_index"] == 0
                and event["logical_response_id"] == plan["id"]
            )
            pending = delivery.claim(plan["id"], 1)
            assert pending
            delivery.acknowledge(plan["id"], 1, pending["claim_id"], None)
            assert delivery.claim(plan["id"], 1) is None and delivery.claim(plan["id"], 2) is None
            following = resolver.begin_turn(**args)
            assert delivery.claim(plan["id"], 2) is None
            assert delivery._plan(plan["id"])["segments"][0]["status"] == "delivered"
            try:
                delivery.create(turn.id, "stale-generation", answer, request, capability)
            except ValueError:
                pass
            else:
                raise AssertionError("A generation predating new input was scheduled")
            fresh = delivery.create(
                following.id, "fresh", SemanticResponse(parts=["fresh"]), request, capability
            )
            claim = delivery.claim(fresh["id"], 0)
            assert claim
            instant[0] += timedelta(hours=2)
            assert (
                delivery.acknowledge(
                    fresh["id"], 0, claim["claim_id"], True, visible_content="fresh"
                )["status"]
                == "delivered"
            )
            store.close()
            store = SQLiteStorage(path)
            recovered = ConversationDelivery(Runtime(store, "owner", clock=lambda: instant[0]))
            assert recovered.claim(plan["id"], 1) is None
            rt = recovered.rt
            resolver = ScopeResolver(store, "owner", lambda: instant[0])
            turn = resolver.begin_turn(**args)
            json_plan = recovered.create(
                turn.id,
                "json",
                SemanticResponse(parts=['{"value":1}']),
                GenerationRequest(explicit_format="json", payload_only=True),
                EndpointCapabilities(),
            )
            claim = recovered.claim(json_plan["id"], 0)
            assert claim
            result = recovered.acknowledge(
                json_plan["id"],
                0,
                claim["claim_id"],
                True,
                visible_content='```json\n{"value":1}\n```',
            )
            assert result["status"] == "delivered"
            assert recovered._plan(json_plan["id"])["segments"][0]["contract_violation"]
            erase_response_context(rt.for_turn(turn.id).storage, "owner", cid)
            erased = recovered._plan(json_plan["id"])
            assert erased["erased"] and not erased["segments"][0]["content"]
            assert not store.get("owner", "raw_event", result["event_id"])["content"]
            try:
                recovered.create(turn.id, "after-erasure", answer, request, capability)
            except ValueError:
                pass
            else:
                raise AssertionError("A forgotten generation context was reused")
            next_turn = resolver.begin_turn(**args)
            pending_plan = recovered.create(
                next_turn.id,
                "pending-erasure",
                SemanticResponse(parts=["private"]),
                request,
                capability,
            )
            claim = recovered.claim(pending_plan["id"], 0)
            assert claim
            erase_response_context(rt.for_turn(next_turn.id).storage, "owner", cid)
            result = recovered.acknowledge(
                pending_plan["id"],
                0,
                claim["claim_id"],
                True,
                visible_content="private",
            )
            event = store.get("owner", "raw_event", result["event_id"])
            assert result["status"] == "delivered" and event["validity"] == "forgotten"
            assert event["content"] == ""
            intake = TurnIntakeBuffer(rt)
            first_buffer = None
            for index, content in enumerate(["我刚刚", "去找他了", "他不在"]):
                turn = resolver.begin_turn(**args)
                scoped = rt.for_turn(turn.id)
                ingested = scoped.knowledge.ingest(
                    EventBatch(
                        operation_id="intake-" + str(index),
                        session_id=turn.id,
                        events=[
                            EventInput(
                                source_id="intake",
                                source_event_id=str(index),
                                source_kind="USER_DIRECT",
                                content=content,
                                timestamp=instant[0],
                            )
                        ],
                    )
                )
                event_id = ingested["event_ids"][0]
                buffered = intake.push(turn.id, event_id)
                assert intake.push(turn.id, event_id) == buffered
                assert intake.claim(buffered["id"]) is None
                if first_buffer:
                    assert first_buffer["id"] == buffered["id"]
                first_buffer = buffered
                instant[0] += timedelta(milliseconds=100)
            instant[0] += timedelta(milliseconds=500)
            batch = intake.claim(buffered["id"])
            assert batch and [e["content"] for e in batch["events"]] == [
                "我刚刚",
                "去找他了",
                "他不在",
            ]
            assert intake.claim(buffered["id"]) is None
            bind(store, "owner", "astrbot", "test", "observer", "observer-bind", "Verified")
            observer = resolver.begin_turn(**(args | {"host": "astrbot", "actor_id": "observer"}))
            assert observer.activity_revision == 0
            main_plan = recovered.create(
                turn.id, "observed", SemanticResponse(parts=["ok"]), request, capability
            )
            assert recovered.claim(main_plan["id"], 0)
            turn = resolver.begin_turn(**args)
            scoped = rt.for_turn(turn.id)
            state = scoped.companion.get(cid)
            state.settings.quiet_start = state.settings.quiet_end = 0
            scoped.companion._save(state)
            # A fixed random source exercises a rare afterthought, never production frequency.
            # 固定随机源只用于覆盖低概率补充消息，不改变正式运行概率。
            planner = ConversationBehaviorPlanner(Random(31))
            with patch(
                "character_runtime.conversation.ConversationBehaviorPlanner", return_value=planner
            ):
                afterthought = recovered.create(
                    turn.id,
                    "afterthought",
                    SemanticResponse(parts=["ok"], follow_up="after"),
                    GenerationRequest(),
                    capability,
                )
            assert afterthought["segments"][-1]["kind"] == "FOLLOW_UP"
            claim = recovered.claim(afterthought["id"], 0)
            assert claim
            recovered.acknowledge(
                afterthought["id"], 0, claim["claim_id"], True, visible_content="ok"
            )
            assert recovered.claim(afterthought["id"], 1) is None
            instant[0] += timedelta(seconds=31)
            claim = recovered.claim(afterthought["id"], 1)
            assert claim
            recovered.acknowledge(afterthought["id"], 1, claim["claim_id"], None)
            assert recovered.claim(afterthought["id"], 1) is None
            following = resolver.begin_turn(**args)
            with patch(
                "character_runtime.conversation.ConversationBehaviorPlanner",
                return_value=ConversationBehaviorPlanner(Random(31)),
            ):
                cooled = recovered.create(
                    following.id,
                    "cooldown",
                    SemanticResponse(parts=["ok"], follow_up="after"),
                    GenerationRequest(),
                    capability,
                )
            assert all(s["kind"] != "FOLLOW_UP" for s in cooled["segments"])
        finally:
            store.close()
    print("PASS segments: ordered claims, per-segment RawEvent, unknown, restart, interruption")
    print("PASS conversation: variable semantic burst, intact code, capability fallback, silence")


if __name__ == "__main__":
    main()
