"""One automatic Host lifecycle over existing Runtime engines, independent of MCP.

复用现有 Runtime 引擎的统一自动宿主生命周期；不依赖模型主动调用 MCP。
"""

from datetime import timedelta
from typing import Any, Literal

from pydantic import AwareDatetime, Field

from .cognition import validate_response
from .conversation_models import EndpointCapabilities
from .knowledge_models import EventBatch, EventInput, TurnProposal
from .models import Identifier, Model
from .operations import fingerprint
from .persistence_models import GenerationRequest
from .runtime import Runtime
from .safety import check_content
from .scope import ScopeResolver


class HostCapabilities(EndpointCapabilities):
    """Declared capability is not authority; absent support stays false.

    能力声明不授予权限；未声明的能力默认不可用。
    """

    pre_generation: bool = False
    post_generation: bool = False
    conversation_history: bool = False
    participant_identity: bool = False
    group_identity: bool = False
    reply_topology: bool = False
    mentions: bool = False
    ambient_messages: bool = False
    tool_events: bool = False
    voice_output: bool = False
    message_edit: bool = False
    reliable_delivery_ack: bool = False


class TurnEnvelope(Model):
    """Trusted Host metadata; Participant is resolved by Runtime, never self-declared.

    可信宿主元数据；Participant 必须由 Runtime 解析，不能由正文或请求自行声明。
    """

    host_id: Identifier
    platform: Identifier
    actor_id: Identifier
    endpoint_id: Identifier
    chat_type: Literal["dm", "group"]
    session_id: Identifier
    turn_id: Identifier
    message_id: Identifier
    text: str = Field(min_length=1, max_length=64000)
    input_is_verbatim: bool = True
    timestamp: AwareDatetime | None = None
    generation: GenerationRequest = Field(default_factory=GenerationRequest)


class TurnLifecycle:
    """Keep generated observations out of evidence and commit proposals through Knowledge.

    生成观察不是证据；提案只通过既有 Knowledge 验证、作用域和事务提交。
    """

    def __init__(self, runtime: Runtime) -> None:
        if runtime.actor:
            raise ValueError("Lifecycle requires trusted Host authority")
        self.rt = runtime

    def observe_ambient(
        self, envelope: TurnEnvelope, capabilities: HostCapabilities
    ) -> dict[str, Any]:
        """Record verified public activity without requesting a generation or delivery.

        记录经验证的公开环境活动，不发起生成或投递；仍使用相同身份与证据边界。
        """
        return self.prepare(envelope, capabilities, ambient=True)

    def prepare(
        self, envelope: TurnEnvelope, capabilities: HostCapabilities, *, ambient: bool = False
    ) -> dict[str, Any]:
        """Authorize, ingest and project once, preserving complete input and source-time truth.

        授权、原始输入提交和投影在同一事务内完成；不截断任务，不伪造源时间。
        """
        envelope = TurnEnvelope.model_validate(envelope.model_dump())
        capabilities = HostCapabilities.model_validate(capabilities.model_dump())
        if ambient and (envelope.chat_type != "group" or not capabilities.ambient_messages):
            raise ValueError("Ambient observation requires a public endpoint and Host capability")
        if not ambient and not capabilities.pre_generation:
            raise ValueError("Host has no pre-generation lifecycle capability")
        digest_input = [envelope.model_dump(mode="json"), capabilities.model_dump()]
        if ambient:
            digest_input.append({"ambient": True})
        digest = fingerprint(digest_input)
        accepted_digests = {digest}
        if envelope.input_is_verbatim and not ambient:
            # Earlier prepared turns always ingested verbatim input. Accept only that exact
            # historical fingerprint; transformed text and ambient turns cannot inherit it.
            # 旧回合固定提交原文；只兼容完全相同的旧指纹，装饰文本及环境回合不得继承。
            accepted_digests.add(
                fingerprint(
                    [
                        envelope.model_dump(mode="json", exclude={"input_is_verbatim"}),
                        capabilities.model_dump(),
                    ]
                )
            )
        with self.rt.storage.transaction():
            resolver = ScopeResolver(self.rt.storage, self.rt.owner, self.rt.clock)
            endpoint = resolver._record("platform_binding", envelope.endpoint_id)
            if endpoint["kind"] != envelope.chat_type:
                raise ValueError("Host audience does not match the endpoint binding")
            turn = resolver.begin_turn(
                host=envelope.host_id,
                platform=envelope.platform,
                actor_id=envelope.actor_id,
                endpoint_id=envelope.endpoint_id,
                session_id=envelope.session_id,
                request_id=fingerprint([envelope.session_id, envelope.turn_id]),
            )
            scoped = self.rt.for_turn(turn.id)
            old = scoped.storage.get(self.rt.owner, "turn_lifecycle", turn.id)
            if old and old["fingerprint"] not in accepted_digests:
                raise ValueError("Prepared turn cannot change its input or capabilities")
            if self.rt.storage.get(self.rt.owner, "response_invalidated", turn.id):
                raise ValueError("Turn context was erased")
            if old is None:
                observed = self.rt.clock()
                if envelope.timestamp and envelope.timestamp > observed + timedelta(minutes=5):
                    raise ValueError("Source timestamp is implausibly in the future")
                # Unverified Host decoration may guide this turn, never become user evidence.
                # 未验证的宿主装饰正文只用于本轮投影，不能成为用户原话证据。
                ingestion = (
                    scoped.knowledge.ingest(
                        EventBatch(
                            session_id=turn.id,
                            operation_id=fingerprint([turn.id, "intake"]),
                            events=[
                                EventInput(
                                    source_id=fingerprint(
                                        [envelope.host_id, envelope.platform, envelope.endpoint_id]
                                    ),
                                    source_event_id=envelope.message_id,
                                    source_kind="USER_DIRECT",
                                    content=envelope.text,
                                    timestamp=envelope.timestamp or observed,
                                    timestamp_basis="source" if envelope.timestamp else "observed",
                                    host=envelope.host_id,
                                    platform=envelope.platform,
                                    actor_id=envelope.actor_id,
                                    conversation_id=envelope.endpoint_id,
                                    sensitivity="public"
                                    if envelope.chat_type == "group"
                                    else "private",
                                )
                            ],
                        )
                    )
                    if envelope.input_is_verbatim
                    else {"event_ids": []}
                )
                old = {
                    "id": turn.id,
                    "character_id": turn.character_id,
                    "owner_id": self.rt.owner,
                    "fingerprint": digest,
                    "state": "ambient" if ambient else "prepared",
                    "delivery_state": "unknown",
                    "observed_at": observed.isoformat(),
                    "source_timestamp": envelope.timestamp.isoformat()
                    if envelope.timestamp
                    else None,
                    "event_ids": ingestion["event_ids"],
                    "capabilities": capabilities.model_dump(),
                    "generation_request": envelope.generation.model_dump(mode="json"),
                    "generated_text": "",
                    "erased": False,
                }
                scoped.storage.put(self.rt.owner, "turn_lifecycle", turn.id, old)
            query = envelope.text
            if len(query) > 4000:
                query = query[:2000] + query[-2000:]
            context = (
                {} if ambient else scoped.context(turn.id, query, generation=envelope.generation)
            )
            return {
                "turn_id": turn.id,
                "character_id": turn.character_id,
                "context": context,
                "capabilities": old["capabilities"],
                "state": old["state"],
            }

    def _load(self, turn_id: str) -> tuple[Runtime, dict[str, Any]]:
        scoped = self.rt.for_turn(turn_id)
        record = scoped.storage.get(self.rt.owner, "turn_lifecycle", turn_id)
        if (
            not record
            or record["erased"]
            or self.rt.storage.get(self.rt.owner, "response_invalidated", turn_id)
        ):
            raise ValueError("Prepared turn is absent or erased")
        return scoped, record

    def observe_generation(self, turn_id: str, operation_id: str, text: str) -> dict[str, Any]:
        """Persist an observable generation, never hidden reasoning or delivery evidence.

        只保存可观察的生成结果，不索取隐藏推理，也不将生成当作投递证据。
        """
        ScopeResolver._ids(operation_id)
        if not text or len(text) > 64000:
            raise ValueError("Generation must contain 1-64000 characters")
        check_content(text)
        digest = fingerprint([operation_id, text])
        with self.rt.storage.transaction():
            scoped, record = self._load(turn_id)
            if not record["capabilities"]["post_generation"]:
                raise ValueError("Host has no generation-observation capability")
            if record.get("generation_digest"):
                if record["generation_digest"] != digest:
                    raise ValueError("Generation observation conflicts with the existing result")
                return {k: record[k] for k in ("state", "delivery_state", "contract_valid")}
            if record["state"] != "prepared":
                raise ValueError("Generation is not pending")
            try:
                validate_response(
                    text, GenerationRequest.model_validate(record["generation_request"])
                )
                valid = True
            except ValueError:
                valid = False
            record.update(
                state="generated",
                generated_text=text,
                generation_digest=digest,
                generated_at=self.rt.clock().isoformat(),
                contract_valid=valid,
            )
            scoped.storage.put(self.rt.owner, "turn_lifecycle", turn_id, record)
            return {k: record[k] for k in ("state", "delivery_state", "contract_valid")}

    def finalize(
        self, turn_id: str, operation_id: str, proposal: TurnProposal | None = None
    ) -> dict[str, Any]:
        """Finalize generation once; optional effects reuse evidence-gated canonical reducers.

        一次性结束生成；可选变化复用证据门与规范 reducer，结束不代表送达。
        """
        ScopeResolver._ids(operation_id)
        digest = fingerprint([operation_id, proposal.model_dump(mode="json") if proposal else None])
        with self.rt.storage.transaction():
            scoped, record = self._load(turn_id)
            if record.get("finalize_digest"):
                if record["finalize_digest"] != digest:
                    raise ValueError("Finalization conflicts with the existing result")
                return {"state": "finalized", "delivery_state": record["delivery_state"]}
            if record["state"] != "generated":
                raise ValueError("Observe generation before finalization")
            if proposal:
                if not record["contract_valid"]:
                    raise ValueError("Invalid generation cannot commit state proposals")
                scoped.commit_turn(turn_id, proposal)
            record.update(
                state="finalized", finalize_digest=digest, finalized_at=self.rt.clock().isoformat()
            )
            scoped.storage.put(self.rt.owner, "turn_lifecycle", turn_id, record)
            return {"state": "finalized", "delivery_state": record["delivery_state"]}
