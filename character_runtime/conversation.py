"""Plan semantic conversation behavior; adapters execute platform operations.

规划语义聊天行为；平台动作由 Adapter 执行，Core 不调用第二个模型。
"""

from datetime import datetime, timedelta
from random import Random
from typing import TYPE_CHECKING, Any, Literal

from .cognition import validate_response
from .conversation_models import (
    EndpointCapabilities,
    InteractionAction,
    InteractionPlan,
    SemanticResponse,
)
from .persistence_models import GenerationRequest
from .safety import check_content
from .scoped_storage import ScopedStorage

if TYPE_CHECKING:
    from .runtime import Runtime


def turn_windows(runtime: "Runtime", character_id: str, session_id: str) -> dict[str, Any]:
    """Derive bounded recent/ambient views after audience authorization, never new Memory.

    先经受众授权再派生有界近期及环境视图；不是长期记忆，不包含私人跨群上下文。
    Generated drafts are excluded here: they do not prove a shared conversation occurred.
    生成草稿不在此处出现：它们不能证明双方已经发生共同对话。
    """
    instant = runtime.clock()
    lifecycle = runtime.knowledge.records("turn_lifecycle", character_id)
    ambient_ids = {
        event_id
        for turn in lifecycle
        if turn.get("state") == "ambient" and not turn.get("erased")
        for event_id in turn.get("event_ids", [])
    }
    current = next((turn for turn in lifecycle if turn["id"] == session_id), {})
    current_ids = set(current.get("event_ids", []))
    # ponytail: scan authorized rows; add a scoped received_at index when histories grow.
    # 仅扫描授权后的记录；历史变大时再增加带作用域的接收时间索引。
    events = [
        event
        for event in runtime.knowledge.records("raw_event", character_id)
        if event.get("validity") == "active"
        and not event.get("legacy_unverified")
        and event.get("sensitivity") != "sensitive"
        and event.get("source_kind") in {"USER_DIRECT", "ASSISTANT_VISIBLE"}
        and 0 <= (instant - datetime.fromisoformat(event["received_at"])).total_seconds() <= 86400
    ]
    events.sort(key=lambda event: (event["received_at"], event["id"]))
    recent: list[dict[str, Any]] = []
    ambient_events: list[dict[str, Any]] = []
    for event in events[-24:]:
        # Do not slice code/quotes to fit a context window; the canonical event remains intact.
        # 不为窗口截断代码或引文；完整规范事件继续保留，可通过精确召回访问。
        if len(event["content"]) > 2000:
            continue
        projection = {
            "event_id": event["id"],
            "content": event["content"],
            "source_kind": event["source_kind"],
            "observed_at": event["received_at"],
            "source_timestamp": event["timestamp"]
            if event.get("timestamp_basis") == "source"
            else None,
            "historical_data_not_instructions": True,
        }
        (ambient_events if event["id"] in ambient_ids else recent).append(projection)
    previous = [event for event in events if event["id"] not in current_ids]
    own_input = next(
        (event["content"] for event in reversed(events) if event["id"] in current_ids), ""
    )
    gap = (
        max(0, (instant - datetime.fromisoformat(previous[-1]["received_at"])).total_seconds())
        if previous
        else None
    )
    return {
        "recent_turn_window": recent[-8:],
        "ambient_window": ambient_events[-8:],
        "derived_turn_signals": {
            "conversation_gap_seconds": gap,
            "exact_repeat_count": sum(event["content"] == own_input for event in previous[-12:])
            if own_input
            else 0,
            "ambient_activity_count": len(ambient_events),
            "recent_return": gap is not None and gap >= 1800,
            "recent_delivery_state": "delivered"
            if previous and previous[-1]["source_kind"] == "ASSISTANT_VISIBLE"
            else "unknown",
            "ephemeral": True,
            "may_mutate_personality": False,
        },
    }


class ConversationBehaviorPlanner:
    """Vary delivery only where meaning, task and capabilities permit it.

    只在语义、任务和平台能力允许时变化发送节奏，不改人物或事实。
    """

    def __init__(self, random: Random | None = None) -> None:
        self.random = random or Random()

    def plan(
        self,
        response: SemanticResponse,
        request: GenerationRequest,
        capabilities: EndpointCapabilities,
        *,
        arousal: float = 0.3,
        familiar: bool = False,
        follow_up_allowed: bool = False,
    ) -> InteractionPlan:
        """Group complete semantic units; never split code, punctuation or exact payloads.

        只组合完整语义单元，不切分代码、标点或精确载荷；专业任务不增加表演性等待。
        """
        response = SemanticResponse.model_validate(response.model_dump())
        capabilities = EndpointCapabilities.model_validate(capabilities.model_dump())
        if response.action == "SILENCE":
            if (
                request.payload_only
                or request.protected_payloads
                or request.explicit_format != "natural"
            ):
                raise ValueError("Silence cannot satisfy a required payload")
            return InteractionPlan(actions=[InteractionAction(kind="SILENCE")])
        if response.action in {"REACTION", "STICKER"}:
            supported = (
                capabilities.reactions
                if response.action == "REACTION"
                else response.content in capabilities.stickers
            )
            if (
                supported
                and request.explicit_format == "natural"
                and not request.payload_only
                and not request.protected_payloads
            ):
                return InteractionPlan(
                    actions=[
                        InteractionAction(
                            kind=response.action,
                            content=response.content,
                            segment_index=0,
                            reply_target=response.reply_target,
                        )
                    ]
                )
            parts = [response.fallback_text]
        else:
            parts = response.parts
        text = "\n\n".join(parts)
        validate_response(text, request)
        social = request.intent in {"CASUAL_CHAT", "SOCIAL", "EMOTIONAL_SUPPORT"}
        relaxed = social and not request.payload_only and not request.serious_safety
        atomic = (
            request.payload_only
            or request.explicit_format in {"json", "verbatim"}
            or any(part.count("```") % 2 or part.count("~~~") % 2 for part in parts)
            or any(not any(p.content in part for part in parts) for p in request.protected_payloads)
        )
        count = 1
        if not atomic and relaxed and capabilities.multiple_messages and len(parts) > 1:
            chance = self.random.random()
            count = min(
                len(parts),
                3 if chance < 0.04 else 2 if chance < (0.22 if familiar else 0.15) else 1,
            )
        # Semantic boundaries are supplied by the current host model, not guessed by Core.
        # 语义边界由当前宿主模型提供，Core 不猜句子边界。
        chunks = [
            "\n\n".join(parts[i * len(parts) // count : (i + 1) * len(parts) // count])
            for i in range(count)
        ]
        if any(len(chunk) > capabilities.max_text_chars for chunk in chunks):
            # Retry partitioning at semantic boundaries only; never cut an atomic unit.
            # 只能重新采用现有语义边界，不能切开不可分的载荷。
            if (
                not capabilities.multiple_messages
                or atomic
                or any(len(p) > capabilities.max_text_chars for p in parts)
            ):
                raise ValueError("Endpoint cannot fit an intact semantic unit")
            chunks = parts
        if "\n\n".join(chunks) != text:
            raise ValueError("Semantic segmentation changed response content")
        actions = []
        for index, chunk in enumerate(chunks):
            if relaxed and capabilities.typing:
                actions.append(InteractionAction(kind="TYPING"))
                delay = int(
                    min(1600, 40 + len(chunk) * self.random.uniform(8, 20))
                    * (1 - min(1, max(0, arousal)) * 0.4)
                )
                actions.append(InteractionAction(kind="WAIT", delay_ms=delay))
            kind: Literal["REPLY", "SEND_TEXT"] = (
                "REPLY"
                if response.action == "REPLY" and capabilities.replies and response.reply_target
                else "SEND_TEXT"
            )
            actions.append(
                InteractionAction(
                    kind=kind,
                    content=chunk,
                    segment_index=index,
                    reply_target=response.reply_target if kind == "REPLY" else None,
                )
            )
        if relaxed and follow_up_allowed and response.follow_up and self.random.random() < 0.05:
            if len(response.follow_up) <= capabilities.max_text_chars:
                actions.append(
                    InteractionAction(kind="WAIT", delay_ms=self.random.randint(15000, 30000))
                )
                actions.append(
                    InteractionAction(
                        kind="FOLLOW_UP", content=response.follow_up, segment_index=len(chunks)
                    )
                )
        return InteractionPlan(actions=actions)


class ConversationDelivery:
    """Persist reactive segment delivery in the same Runtime and authority ledger.

    在同一 Runtime 与发送权限账本中持久化回复片段；不实现第二套主动决策引擎。
    """

    def __init__(self, runtime: "Runtime") -> None:
        if runtime.actor:
            raise ValueError("Delivery requires a trusted host bridge")
        self.rt = runtime

    def create(
        self,
        turn_id: str,
        operation_id: str,
        response: SemanticResponse,
        request: GenerationRequest,
        capabilities: EndpointCapabilities,
    ) -> dict[str, Any]:
        """Persist random choices once; retry cannot regenerate or change a response.

        随机选择只持久化一次；重试不能重新生成或篡改同一回复。
        """
        from .operations import fingerprint
        from .proactive import contact_limit
        from .scope import ScopeResolver

        check_content(response.model_dump_json())
        check_content(request.model_dump_json())
        ScopeResolver._ids(operation_id)
        with self.rt.storage.transaction():
            scoped = self.rt.for_turn(turn_id)
            actor = scoped.actor
            assert actor
            resolver = ScopeResolver(self.rt.storage, self.rt.owner, self.rt.clock)
            binding = resolver._record("delivery_binding", actor.platform_binding)
            if binding["host"] != actor.host:
                raise ValueError("Host is not the active endpoint sender")
            key = fingerprint([turn_id, operation_id])
            digest = fingerprint(
                [
                    response.model_dump(mode="json"),
                    request.model_dump(mode="json"),
                    capabilities.model_dump(mode="json"),
                ]
            )
            old = self.rt.storage.get(self.rt.owner, "response_plan", key)
            if old:
                if old["fingerprint"] != digest:
                    raise ValueError("Response operation reused with different content")
                return old
            if self.rt.storage.get(self.rt.owner, "turn_response", turn_id):
                raise ValueError("This turn already has a logical response")
            activity = self.rt.storage.get(
                self.rt.owner, "endpoint_activity", actor.platform_binding
            ) or {"revision": 0}
            # An old generation cannot borrow a newer turn's activity revision.
            # 旧轮次生成结果不得借用新消息版本绕过中断。
            if not actor.activity_revision or activity["revision"] != actor.activity_revision:
                raise ValueError("Response predates newer endpoint input")
            if self.rt.storage.get(self.rt.owner, "response_invalidated", turn_id):
                raise ValueError("Response context was invalidated by erasure")
            arousal, familiar = 0.3, False
            if actor.private_context_allowed:
                arousal = scoped.knowledge.lifelike.get(actor.character_id).affect.arousal
                familiar = (
                    scoped.knowledge.relationship.get(actor.character_id).learned.stage
                    != "stranger"
                )
            companion = scoped.companion
            state = companion.get(actor.character_id)
            plan = ConversationBehaviorPlanner().plan(
                response,
                request,
                capabilities,
                arousal=arousal,
                familiar=familiar,
                follow_up_allowed=not state.pending_decision
                and contact_limit(companion, state) is None,
            )
            identity = resolver._record("identity_binding", actor.identity_binding)
            instant, elapsed = self.rt.clock(), 0
            segments = []
            for action in plan.actions:
                elapsed += action.delay_ms
                if action.segment_index is not None:
                    segments.append(
                        {
                            **action.model_dump(mode="json"),
                            "status": "ready",
                            "due_at": (instant + timedelta(milliseconds=elapsed)).isoformat(),
                        }
                    )
            assert isinstance(scoped.storage, ScopedStorage)
            record = {
                "id": key,
                "character_id": actor.character_id,
                "turn_id": turn_id,
                "endpoint_id": actor.platform_binding,
                "host": actor.host,
                "binding_revision": binding["revision"],
                "activity_revision": activity["revision"],
                "audience": scoped.storage.audience_namespace,
                "platform": identity["platform"],
                "actor_id": identity["actor_id"],
                "fingerprint": digest,
                "actions": plan.model_dump(mode="json")["actions"],
                "segments": segments,
                "cancelled": False,
                "protected_payloads": [
                    p.model_dump(mode="json") for p in request.protected_payloads
                ],
                "explicit_format": request.explicit_format,
                "payload_only": request.payload_only,
            }
            self.rt.storage.put(self.rt.owner, "response_plan", key, record)
            self.rt.storage.put(self.rt.owner, "turn_response", turn_id, {"plan_id": key})
            return record

    def _plan(self, plan_id: str) -> dict[str, Any]:
        record = self.rt.storage.get(self.rt.owner, "response_plan", plan_id)
        if not record:
            raise ValueError("Unknown response plan")
        return record

    def cancel(self, plan_id: str) -> dict[str, Any]:
        """Cancel unsent segments only; claimed or unknown sends retain their uncertainty.

        只取消未发送片段；已领取或未知投递保留原状态，不能假定未送达。
        """
        with self.rt.storage.transaction():
            plan = self._plan(plan_id)
            plan["cancelled"] = True
            for segment in plan["segments"]:
                if segment["status"] == "ready":
                    segment["status"] = "cancelled"
            self.rt.storage.put(self.rt.owner, "response_plan", plan_id, plan)
            return plan

    def claim(self, plan_id: str, segment_index: int) -> dict[str, Any] | None:
        """Claim one due segment against current identity, activity and delivery authority.

        依据当前身份、消息版本和发送权限领取到期片段；中断或租约过期不授予重发。
        """
        from .operations import fingerprint
        from .scope import ScopeResolver

        with self.rt.storage.transaction():
            plan = self._plan(plan_id)
            activity = self.rt.storage.get(
                self.rt.owner, "endpoint_activity", plan["endpoint_id"]
            ) or {"revision": 0}
            if plan["cancelled"] or activity["revision"] != plan["activity_revision"]:
                self.cancel(plan_id)
                return None
            if segment_index < 0 or segment_index >= len(plan["segments"]):
                raise ValueError("Unknown response segment")
            segment = plan["segments"][segment_index]
            if segment["status"] != "ready" or any(
                s["status"] != "delivered" for s in plan["segments"][:segment_index]
            ):
                return None
            if datetime.fromisoformat(segment["due_at"]) > self.rt.clock():
                return None
            scoped = self.rt.for_turn(plan["turn_id"])
            followup_state = None
            if segment["kind"] == "FOLLOW_UP":
                from zoneinfo import ZoneInfo

                from .proactive import contact_limit

                state = scoped.companion.get(plan["character_id"])
                if state.pending_decision or contact_limit(scoped.companion, state):
                    self.cancel(plan_id)
                    return None
                # Reserve the shared rate budget before sending, including uncertain outcomes.
                # 发送前占用共用频率预算，未知结果同样占用，防止跨计划重复补发。
                instant = self.rt.clock()
                today = instant.astimezone(ZoneInfo(state.settings.timezone)).date().isoformat()
                if today > state.contact_day:
                    state.contact_day, state.contacts_today = today, 0
                state.contacts_today += 1
                state.last_contact_at = instant
                followup_state = state
            decision_id = fingerprint([plan_id, segment_index])
            claim = ScopeResolver(self.rt.storage, self.rt.owner, self.rt.clock).claim_delivery(
                plan["endpoint_id"],
                decision_id,
                plan["host"],
                plan["binding_revision"],
            )
            if claim is None:
                return None
            if followup_state is not None:
                scoped.companion._save(followup_state)
            segment.update(status="pending", claim_id=claim["claim_id"], decision_id=decision_id)
            self.rt.storage.put(self.rt.owner, "response_plan", plan_id, plan)
            return {**segment, "logical_response_id": plan_id}

    def acknowledge(
        self,
        plan_id: str,
        segment_index: int,
        claim_id: str,
        delivered: bool | None,
        *,
        visible_content: str = "",
        delivery_reference: str = "",
    ) -> dict[str, Any]:
        """Record actual visible content atomically with ACK, even after a turn expires.

        实际可见内容与 ACK 原子提交；Turn 过期也不能丢失已经发生的投递事实。
        The sealed claim's audience is used; no new read/send authority is granted.
        使用领取时封存的受众，不授予新的读取或发送权限。
        """
        from .knowledge_models import RawEvent
        from .operations import fingerprint
        from .scope import ScopeResolver

        with self.rt.storage.transaction():
            plan = self._plan(plan_id)
            if segment_index < 0 or segment_index >= len(plan["segments"]):
                raise ValueError("Unknown response segment")
            segment = plan["segments"][segment_index]
            if segment.get("claim_id") != claim_id:
                raise ValueError("Segment delivery claim mismatch")
            digest = fingerprint([delivered, visible_content, delivery_reference])
            if "ack_fingerprint" in segment:
                if segment["ack_fingerprint"] != digest:
                    raise ValueError("Conflicting segment acknowledgement")
                return {"status": segment["status"], "event_id": segment.get("event_id")}
            if delivered is True:
                if not visible_content:
                    raise ValueError("Successful delivery requires the final visible content")
                from .persistence_models import ProtectedPayload

                relevant = [
                    ProtectedPayload.model_validate(p)
                    for p in plan["protected_payloads"]
                    if p["content"] in segment["content"]
                ]
                # A transport may already have delivered a damaged payload. Keep the real
                # receipt and diagnose the violation instead of inventing a failed send.
                # 平台可能已发送受损内容；记录真实回执和契约违例，不能伪装发送失败。
                try:
                    validate_response(
                        visible_content,
                        GenerationRequest(
                            protected_payloads=relevant,
                            explicit_format=plan["explicit_format"],
                            payload_only=plan["payload_only"],
                        ),
                    )
                except ValueError:
                    segment["contract_violation"] = True
            result = ScopeResolver(self.rt.storage, self.rt.owner, self.rt.clock).ack_delivery(
                plan["endpoint_id"],
                segment["decision_id"],
                plan["host"],
                claim_id,
                delivered,
            )
            if delivered is True:
                redacted = (
                    plan.get("erased", False)
                    or len(visible_content) > 64000
                    or len(delivery_reference) > 1000
                )
                try:
                    check_content(visible_content)
                    check_content(delivery_reference)
                except ValueError:
                    redacted = True
                event_id = fingerprint([plan_id, segment_index, "visible"])
                event = RawEvent(
                    id=event_id,
                    owner_id=plan["audience"],
                    character_id=plan["character_id"],
                    session_id=plan["turn_id"],
                    source_id="delivery:" + plan_id,
                    source_event_id=str(segment_index),
                    source_kind="ASSISTANT_VISIBLE",
                    content="" if redacted else visible_content,
                    validity="forgotten" if redacted else "active",
                    timestamp=self.rt.clock(),
                    host=plan["host"],
                    platform=plan["platform"],
                    source_ref="" if redacted else delivery_reference,
                    logical_response_id=plan_id,
                    segment_index=segment_index,
                    visible_kind=segment["kind"],
                )
                # The receipt prevents a repeated ACK from resurrecting erased event content.
                # 回执阻止重复 ACK 复活已被遗忘的事件正文。
                self.rt.storage.put(
                    plan["audience"], "raw_event", event_id, event.model_dump(mode="json")
                )
                segment["event_id"] = event_id
            segment.update(status=result["status"], ack_fingerprint=digest)
            self.rt.storage.put(self.rt.owner, "response_plan", plan_id, plan)
            return {"status": segment["status"], "event_id": segment.get("event_id")}


class TurnIntakeBuffer:
    """Debounce verified source events without duplicating their canonical bodies.

    对已验证的原始事件做短时合并，不复制规范正文；不同角色或会话不混合。
    """

    def __init__(self, runtime: "Runtime") -> None:
        if runtime.actor:
            raise ValueError("Intake requires a trusted host bridge")
        self.rt = runtime

    def push(self, turn_id: str, event_id: str) -> dict[str, Any]:
        """Reset a short receive-time debounce, bounded to three seconds and 20 events.

        按接收时间重置短暂等待，最多三秒、20 个事件；来源时间不能操纵调度。
        """
        from .models import new_id
        from .operations import fingerprint

        with self.rt.storage.transaction():
            scoped = self.rt.for_turn(turn_id)
            actor = scoped.actor
            assert actor
            from .scope import ScopeResolver

            binding = ScopeResolver(self.rt.storage, self.rt.owner, self.rt.clock)._record(
                "delivery_binding", actor.platform_binding
            )
            if binding["host"] != actor.host:
                raise ValueError("Only the active sender can schedule intake")
            event = scoped.storage.get(self.rt.owner, "raw_event", event_id)
            if not event or event["source_kind"] != "USER_DIRECT" or event["validity"] != "active":
                raise ValueError("Intake requires an active direct event in this audience")
            if event["session_id"] != turn_id:
                raise ValueError("Intake event belongs to another ingress turn")
            receipt_id = fingerprint([turn_id, event_id])
            receipt = self.rt.storage.get(self.rt.owner, "intake_receipt", receipt_id)
            if receipt:
                return self._buffer(receipt["buffer_id"])
            key = fingerprint([actor.host, actor.session_id, actor.character_id])
            head = self.rt.storage.get(self.rt.owner, "intake_head", key)
            buffer = self._buffer(head["buffer_id"]) if head else None
            instant = self.rt.clock()
            if buffer is None or buffer["status"] != "waiting":
                buffer = {
                    "id": new_id(),
                    "character_id": actor.character_id,
                    "started_at": instant.isoformat(),
                    "event_ids": [],
                    "status": "waiting",
                }
            if len(buffer["event_ids"]) >= 20:
                raise ValueError("Intake is full; claim the ready batch before accepting more")
            buffer["event_ids"].append(event_id)
            buffer["turn_id"] = turn_id
            delay = 450 if len(event["content"]) <= 200 and len(buffer["event_ids"]) < 20 else 0
            buffer["due_at"] = min(
                instant + timedelta(milliseconds=delay),
                datetime.fromisoformat(buffer["started_at"]) + timedelta(seconds=3),
            ).isoformat()
            self.rt.storage.put(self.rt.owner, "intake_buffer", buffer["id"], buffer)
            self.rt.storage.put(self.rt.owner, "intake_head", key, {"buffer_id": buffer["id"]})
            self.rt.storage.put(
                self.rt.owner, "intake_receipt", receipt_id, {"buffer_id": buffer["id"]}
            )
            return buffer

    def _buffer(self, buffer_id: str) -> dict[str, Any]:
        value = self.rt.storage.get(self.rt.owner, "intake_buffer", buffer_id)
        if not value:
            raise ValueError("Unknown intake buffer")
        return value

    def claim(self, buffer_id: str) -> dict[str, Any] | None:
        """Grant generation once; restarts never replay an already claimed batch.

        只授予一次生成权；重启不能重放已领取的批次，群聊保留每条事件的 Actor。
        """
        with self.rt.storage.transaction():
            buffer = self._buffer(buffer_id)
            if buffer["status"] != "waiting" or self.rt.clock() < datetime.fromisoformat(
                buffer["due_at"]
            ):
                return None
            scoped = self.rt.for_turn(buffer["turn_id"])
            actor = scoped.actor
            assert actor
            activity = self.rt.storage.get(
                self.rt.owner, "endpoint_activity", actor.platform_binding
            )
            if (
                not activity
                or activity["revision"] != actor.activity_revision
                or self.rt.storage.get(self.rt.owner, "response_invalidated", actor.id)
            ):
                buffer["status"] = "cancelled"
                self.rt.storage.put(self.rt.owner, "intake_buffer", buffer_id, buffer)
                return None
            events = []
            for event_id in buffer["event_ids"]:
                event = scoped.storage.get(self.rt.owner, "raw_event", event_id)
                if not event or event["validity"] != "active":
                    raise ValueError("Intake source was erased or is no longer authorized")
                events.append(event)
            buffer["status"] = "claimed"
            self.rt.storage.put(self.rt.owner, "intake_buffer", buffer_id, buffer)
            return {"turn_id": actor.id, "events": events}


def erase_response_context(storage: Any, owner: str, character_id: str) -> None:
    """Invalidate generation snapshots and erase transport copies in this audience.

    遗忘时撤销当前受众的生成快照并清除发送副本；回执与未知投递状态仍保留。
    Without complete model attribution, every response in this audience may derive
    from forgotten evidence; other audiences and canonical records remain intact.
    无法完整追踪模型引用，因此保守清理同受众回复；其他受众及规范记录不变。
    """
    from .operations import fingerprint

    scoped = isinstance(storage, ScopedStorage)
    base = storage.base if scoped else storage
    audience = storage.audience_namespace if scoped else owner
    with storage.transaction():
        for record in base.list(audience, "turn_lifecycle"):
            if record["character_id"] == character_id:
                record.update(erased=True, generated_text="", generation_request={})
                base.put(audience, "turn_lifecycle", record["id"], record)
        # ponytail: linear administrative erasure; index by audience if history grows large.
        # 遗忘管理扫描为线性复杂度；历史增大后按受众建立索引。
        for turn in base.list(owner, "turn_actor"):
            private = turn["private_context_allowed"]
            namespace = (
                owner
                if private and turn["participant_id"] == owner
                else "\0agentcosplay:"
                + fingerprint(
                    [
                        owner,
                        "participant" if private else "endpoint",
                        turn["participant_id"] if private else turn["platform_binding"],
                    ]
                )
            )
            if turn["character_id"] == character_id and namespace == audience:
                base.put(owner, "response_invalidated", turn["id"], {"erased": True})
        for plan in base.list(owner, "response_plan"):
            if plan["character_id"] != character_id or plan["audience"] != audience:
                continue
            plan.update(cancelled=True, erased=True, actions=[], protected_payloads=[])
            for segment in plan["segments"]:
                segment["content"] = ""
                event_id = segment.get("event_id")
                event = base.get(audience, "raw_event", event_id) if event_id else None
                if event:
                    event.update(content="", validity="forgotten", source_ref="")
                    base.put(audience, "raw_event", event_id, event)
                if segment["status"] == "ready":
                    segment["status"] = "cancelled"
            base.put(owner, "response_plan", plan["id"], plan)
