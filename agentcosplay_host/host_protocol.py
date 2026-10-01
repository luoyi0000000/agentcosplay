"""Shared Host lifecycle and projection mapping; SDK bindings carry no policy.
共享宿主生命周期和投影映射；SDK 绑定不持有人格、记忆或投递权威。
"""

import hashlib
import json
import re
import threading
import time
from collections import OrderedDict
from copy import deepcopy
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import AliasChoices, AwareDatetime, Field

from .base import Identifier, Model
from .context_models import UniversalGenerationContext
from .endpoints import EndpointCapabilities
from .host_client import HostBridge


class InputEvidence(StrEnum):
    """Source fidelity, not a claim about truth. / 源正文保真度，不是真实性声明。"""

    VERIFIED_VERBATIM = "verified_verbatim"
    TRANSFORMED = "transformed"
    UNKNOWN = "unknown"


class GenerationSurface(StrEnum):
    """Native fields share one logical authority position. / 原生字段共用一处逻辑权限位置。"""

    INSTRUCTIONS = "instructions"
    SYSTEM_TEXT = "system_text"
    SYSTEM_BLOCKS = "system_blocks"
    SYSTEM_MESSAGE = "system_message"


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
    generation_surfaces: tuple[GenerationSurface, ...] = ()
    tool_interception: bool = False


class HostIngress(Model):
    """Typed trusted ingress; Runtime resolves the participant.

    可信类型化入口，Runtime 解析真人身份。
    """

    host_id: Identifier
    platform: Identifier
    actor_id: Identifier
    endpoint_id: Identifier
    chat_type: Literal["dm", "group"]
    native_session_id: Identifier = Field(
        validation_alias=AliasChoices("native_session_id", "session_id")
    )
    turn_id: Identifier
    message_id: Identifier
    text: str = Field(min_length=1, max_length=64000)
    input_evidence: InputEvidence = InputEvidence.UNKNOWN
    source_timestamp: AwareDatetime | None = None

    def envelope(self) -> dict[str, Any]:
        """Serialize the existing wire contract without changing persisted request IDs.
        保持已有传输契约和持久化请求 ID；旧 bool 仅在边界进行明确转换。
        """
        result = self.model_dump(mode="json", exclude={"input_evidence", "source_timestamp"})
        result["session_id"] = result.pop("native_session_id")
        result.update(
            input_is_verbatim=self.input_evidence == InputEvidence.VERIFIED_VERBATIM,
            timestamp=self.source_timestamp.isoformat() if self.source_timestamp else None,
        )
        return result


class ActiveHostTurn(Model):
    """Ephemeral capability with validated projection, never a second state store.
    临时能力与已验证投影，不是第二份状态数据库。
    """

    runtime_turn_id: Identifier
    runtime_session_id: Identifier
    capability: str = Field(min_length=1, max_length=4096, repr=False)
    generation_context: UniversalGenerationContext
    created_monotonic: float


class TurnRegistry:
    """Bound lifetime and capacity; missing/expired entries grant nothing.
    限制生命周期与容量；不存在或已过期的条目不授予任何权限。
    """

    def __init__(self, capacity: int = 128, ttl: float = 300) -> None:
        if capacity < 1 or ttl <= 0:
            raise ValueError("Positive turn capacity and TTL required")
        self.capacity, self.ttl = capacity, ttl
        self._items: OrderedDict[tuple[str, str], ActiveHostTurn] = OrderedDict()
        self._lock = threading.RLock()
        self._pending: OrderedDict[tuple[str, str], tuple[object, float]] = OrderedDict()

    def reserve(self, key: tuple[str, str]) -> object:
        """Invalidate older in-flight prepares before asynchronous I/O.

        异步 I/O 前使同一键的旧 prepare 失效，迟到回调不得恢复旧能力。
        """
        with self._lock:
            self._items.pop(key, None)
            self._pending.pop(key, None)
            ticket = object()
            self._pending[key] = (ticket, time.monotonic())
            while len(self._pending) > self.capacity:
                self._pending.popitem(last=False)
            return ticket

    def complete(self, key: tuple[str, str], ticket: object, value: ActiveHostTurn) -> bool:
        """Accept only the newest live reservation. / 只接受最新且未过期的预留。"""
        with self._lock:
            pending = self._pending.get(key)
            if pending is None or pending[0] is not ticket:
                return False
            self._pending.pop(key)
            if time.monotonic() - pending[1] >= self.ttl:
                return False
            self.put(key, value)
            return True

    def get(self, key: tuple[str, str]) -> ActiveHostTurn | None:
        """Expire before returning a capability. / 返回能力前先检查过期。"""
        with self._lock:
            value = self._items.get(key)
            if value is not None and time.monotonic() - value.created_monotonic >= self.ttl:
                self._items.pop(key)
                return None
            return value.model_copy(deep=True) if value else None

    def put(self, key: tuple[str, str], value: ActiveHostTurn) -> None:
        """Copy validated state and evict oldest entries. / 复制已验证状态并淘汰最早条目。"""
        with self._lock:
            self._items.pop(key, None)
            self._items[key] = ActiveHostTurn.model_validate(value.model_dump())
            while len(self._items) > self.capacity:
                self._items.popitem(last=False)

    def discard(self, key: tuple[str, str]) -> None:
        """Revoke a local capability before another prepare. / 新 prepare 前撤销本地旧能力。"""
        with self._lock:
            self._items.pop(key, None)
            self._pending.pop(key, None)

    def clear(self, session_id: str | None = None) -> None:
        """Clear transient entries only; canonical memory is untouched.
        只清理临时条目，不修改规范记忆。
        """
        with self._lock:
            for key in list(self._pending):
                if session_id is None or key[0] == session_id:
                    self._pending.pop(key)
            for key in list(self._items):
                if session_id is None or key[0] == session_id:
                    self._items.pop(key)


def stable_host_key(*parts: str) -> str:
    """Preserve v1 hash bytes so retries and existing sessions remain addressable.
    保留 v1 哈希字节，防止重试收据和旧会话因重构失联。
    """
    return hashlib.sha256(json.dumps(parts, ensure_ascii=True).encode()).hexdigest()


UNAVAILABLE = "agentcosplay unavailable: no verified Runtime context; do not invent memories."
_PROJECTION_START = "\n<agentcosplay-generation-context>\n"
_PROJECTION_END = "\n</agentcosplay-generation-context>\n"


def _without_projection(text: str) -> str:
    """Remove complete owned blocks; ambiguous Host edits must not retain private data.

    移除完整自有块；宿主改坏边界时拒绝处理，避免保留旧私人数据。
    """
    cleaned = re.sub(
        r"\n?"
        + re.escape(_PROJECTION_START.strip())
        + r".*?"
        + re.escape(_PROJECTION_END.strip())
        + r"\n?",
        "",
        text,
        flags=re.DOTALL,
    )
    if (
        "<agentcosplay-generation-context>" in cleaned
        or "</agentcosplay-generation-context>" in cleaned
    ):
        raise ValueError("Host changed the Runtime projection; use a fresh request")
    return cleaned


def _clean_native_content(content: Any) -> Any:
    """Clean both native string and text-block representations without touching user data.

    同时清理原生字符串与文本块表示；仅由系统槽调用，不改用户数据。
    """
    if isinstance(content, str):
        return _without_projection(content)
    if isinstance(content, list):
        kept = []
        for item in content:
            if item.get("type") in {"text", "input_text"}:
                item["text"] = _without_projection(item["text"])
                if not item["text"]:
                    continue
            kept.append(item)
        return kept
    raise ValueError("Unsupported native system content")


class GenerationBinding(Model):
    """The SDK selects a supported field, never a different expression policy.

    SDK 只选择已支持字段，不选择另一套表达策略。
    """

    surface: GenerationSurface


class ProjectionMapper:
    """Serialize the same typed context beneath Host policy in each native surface.
    在各原生槽中将同一类型化契约放在宿主策略之后；不改变上下文语义。
    """

    @staticmethod
    def apply(
        request: dict[str, Any],
        context: UniversalGenerationContext | None,
        binding: GenerationBinding | None = None,
    ) -> dict[str, Any]:
        """Copy request, remove old owned projection, then render current context.
        复制请求、移除旧自有投影，再渲染本轮上下文。
        """
        surface = (
            GenerationSurface.INSTRUCTIONS
            if "instructions" in request
            else GenerationSurface.SYSTEM_TEXT
            if isinstance(request.get("system"), str)
            else GenerationSurface.SYSTEM_BLOCKS
            if isinstance(request.get("system"), list)
            else GenerationSurface.SYSTEM_MESSAGE
        )
        if binding is not None and binding.surface != surface:
            raise ValueError("Generation surface does not match its binding")
        text = context.render() if context else UNAVAILABLE
        text = _PROJECTION_START + text + _PROJECTION_END
        mapped = deepcopy(request)
        if "instructions" in mapped:
            if not isinstance(mapped["instructions"], str):
                raise ValueError("Unsupported native instructions format")
            mapped["instructions"] = _without_projection(mapped["instructions"]) + text
        elif "system" in mapped:
            system = mapped["system"]
            if isinstance(system, str):
                mapped["system"] = _without_projection(system) + text
            elif isinstance(system, list):
                block = {"type": "text", "text": text}
                mapped["system"] = [*_clean_native_content(system), block]
            else:
                raise ValueError("Unsupported native system format")
        elif isinstance(mapped.get("messages"), list):
            messages = mapped["messages"]
            retained = []
            for item in messages:
                if item.get("role") in {"system", "developer"}:
                    item["content"] = _clean_native_content(item.get("content"))
                    if not item["content"]:
                        continue
                retained.append(item)
            messages = mapped["messages"] = retained
            message = {"role": "system", "content": text}
            if message not in messages:
                index = 0
                while index < len(messages) and messages[index].get("role") in {
                    "system",
                    "developer",
                }:
                    index += 1
                messages.insert(index, message)
        else:
            raise ValueError("Unsupported native generation request")
        return mapped


class ScopedToolRouter:
    """Bind model tools to Host-issued sessions; never infer IDs from model text.

    把模型工具绑定到 Host 签发的会话；不从模型正文猜测或修复 ID。
    """

    session_tools = frozenset(
        {
            "runtime_context",
            "memory_recall",
            "memory_promote",
            "turn_commit",
            "companion_control",
            "perception_observe",
            "runtime_doctor",
            "context_explain",
        }
    )
    request_tools = frozenset({"session_control", "memory_write"})

    @classmethod
    def arguments(
        cls, tool: str, arguments: dict[str, Any], session_id: str, turn_id: str
    ) -> dict[str, Any]:
        """Fill absent scope; reject conflicting native/fabricated IDs without mutating input.

        补齐缺失作用域，拒绝冲突的原生/虚构 ID，不修改宿主原请求。
        """
        result = deepcopy(arguments)
        target = result
        if tool in cls.request_tools:
            target = result.setdefault("request", {})
            if not isinstance(target, dict):
                raise ValueError("Structured scoped request required")
            if tool == "session_control" and target.get("action") in {
                "open",
                "set_default",
                "bind_project",
            }:
                raise ValueError("Session registration requires trusted Host lifecycle")
        if tool in cls.session_tools | cls.request_tools:
            if target.get("session_id") not in {None, session_id, turn_id}:
                raise ValueError("Model tool session does not match this interaction")
            target["session_id"] = session_id
        return result

    @classmethod
    def schema(cls, tool: str, schema: dict[str, Any]) -> dict[str, Any]:
        """Hide Host-bound session fields in model-facing copies of existing tool schemas.

        在已有工具 Schema 的模型侧副本中移除 Host 绑定字段，不注册第二套工具。
        """
        result = deepcopy(schema)
        if tool not in cls.session_tools | cls.request_tools:
            return result

        def strip(value: Any) -> None:
            if isinstance(value, dict):
                if isinstance(value.get("properties"), dict):
                    value["properties"].pop("session_id", None)
                if isinstance(value.get("required"), list):
                    value["required"] = [key for key in value["required"] if key != "session_id"]
                for child in value.values():
                    strip(child)
            elif isinstance(value, list):
                for child in value:
                    strip(child)

        strip(result)
        return result


class UniversalHostBridge:
    """One prepare/tools/observe/finalize contract over the existing bridge.
    复用既有传输桥接，唯一实现 prepare、工具、观察和结束契约。
    """

    def __init__(self, url: str, token_file: Path, host: str) -> None:
        if not host or len(host) > 100:
            raise ValueError("Stable Host ID required")
        self.host = host
        self.bridge = HostBridge(url, token_file)
        self.turns = TurnRegistry()
        self.capabilities = HostCapabilities(
            pre_generation=True,
            post_generation=True,
            participant_identity=True,
            group_identity=True,
            tool_interception=True,
            generation_surfaces=tuple(GenerationSurface),
        )

    async def prepare_turn(self, key: tuple[str, str], ingress: HostIngress) -> ActiveHostTurn:
        """Invalidate old capability before I/O; reject untyped/missing Runtime projections.
        网络请求前撤销旧能力；拒绝缺失或无类型的 Runtime 投影。
        """
        ticket = self.turns.reserve(key)
        if not self.capabilities.pre_generation:
            raise ValueError("Host cannot prepare generation")
        if ingress.host_id != self.host:
            raise ValueError("Host ingress mismatch")
        opened = await self.bridge.call(
            "host_prepare_turn",
            {
                "envelope": ingress.envelope(),
                "capabilities": self.capabilities.model_dump(mode="json"),
            },
        )
        turn = ActiveHostTurn(
            runtime_turn_id=opened["turn_id"],
            runtime_session_id=opened["session_id"],
            capability=opened["capability"],
            generation_context=UniversalGenerationContext.model_validate(
                opened["context"]["generation_context"]
            ),
            created_monotonic=time.monotonic(),
        )
        if not self.turns.complete(key, ticket, turn):
            raise ValueError("Host prepare was superseded or expired")
        return turn

    async def execute_tool(
        self, key: tuple[str, str], tool: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Use current turn only; failures return redacted errors, never owner fallback.
        只用当前回合；失败返回脱敏错误，绝不回退管理权限。
        """
        try:
            turn = self.turns.get(key)
            if turn is None or not self.capabilities.tool_interception:
                raise ValueError("Missing turn/tool capability")
            value = await self.bridge.model_call(
                turn.capability,
                turn.runtime_turn_id,
                tool,
                arguments,
                session_id=turn.runtime_session_id,
            )
            return {"ok": True, "result": value}
        except Exception:
            return {"ok": False, "error": "Verified Runtime turn required"}

    async def observe_turn(self, key: tuple[str, str], text: str) -> None:
        """Observe official text then finalize; generation never acknowledges delivery.
        观察官方正文后结束回合；生成不能确认送达。失败不泄漏正文且不伪造成功。
        """
        turn = self.turns.get(key)
        if turn is None or not self.capabilities.post_generation:
            return
        await self.bridge.call(
            "host_observe_generation",
            {
                "turn_id": turn.runtime_turn_id,
                "operation_id": stable_host_key(turn.runtime_turn_id, "generation"),
                "text": text,
            },
        )
        await self.bridge.call(
            "host_finalize_turn",
            {
                "turn_id": turn.runtime_turn_id,
                "operation_id": stable_host_key(turn.runtime_turn_id, "finalize"),
            },
        )

    async def session_boundary(
        self, key: tuple[str, str], action: Literal["invalidate", "rotate"], operation_id: str
    ) -> dict[str, Any]:
        """Apply an explicit Host lifetime boundary, never a model-tool request.

        应用 Host 明确的会话生命周期边界，不作为模型工具请求执行。
        """
        turn = self.turns.get(key)
        if turn is None:
            raise ValueError("Live trusted session handle required")
        # Cancel this native callback bucket, including late prepares, not other endpoints.
        # 撤销当前原生回调桶及迟到 prepare，不清除其他 Endpoint 的活动会话。
        self.turns.clear(key[0])
        return await self.bridge.call(
            "host_session_control",
            {
                "session_id": turn.runtime_session_id,
                "action": action,
                "operation_id": operation_id,
            },
        )


# Keep existing embedding imports during the naming transition; there is one implementation.
# 名称迁移期间保持旧嵌入导入兼容；没有第二份实现。
UniversalHostAdapter = UniversalHostBridge
