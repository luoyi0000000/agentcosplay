"""Official AstrBot lifecycle bridge; no local database, model or delivery assumptions.

AstrBot 官方生命周期桥接；不持有数据库、模型，也不猜测投递成功。
"""

import hashlib
import json
from collections import OrderedDict
from copy import copy
from pathlib import Path
from types import MethodType
from typing import Any

from mcp.types import CallToolResult, TextContent

from .host_client import HostBridge


def _key(*parts: str) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=True).encode()).hexdigest()


class AstrBotAdapter:
    """Map exact platform-instance routes and per-event capabilities to one remote Runtime.

    将精确的平台实例路由与单事件能力令牌映射到同一个 Runtime，不维护角色状态副本。
    """

    def __init__(self, url: str, token_file: Path, host: str, routes: list[dict[str, str]]) -> None:
        self.bridge = HostBridge(url, token_file)
        if not host or len(host) > 100:
            raise ValueError("Stable Host ID required")
        self.host = host
        self.routes: dict[tuple[str, str, str], dict[str, str]] = {}
        for route in routes:
            key = (route["platform_id"], route["session_id"], route["kind"])
            if (
                key in self.routes
                or key[2] not in {"dm", "group"}
                or not all(isinstance(v, str) and 0 < len(v) <= 200 for v in route.values())
                or not route["runtime_platform"]
                or not route["endpoint_id"]
            ):
                raise ValueError("Explicit unique AstrBot routes required")
            self.routes[key] = dict(route)
        self.turns: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def event_key(self, event: Any) -> str:
        """Bind callback identity to actor, endpoint and source message, never a nickname.

        回调身份绑定 Actor、Endpoint 和源消息，不使用昵称猜测身份。
        """
        return _key(
            event.get_platform_id(),
            event.get_session_id(),
            event.get_sender_id(),
            str(event.message_obj.message_id),
        )

    async def prepare(self, event: Any, request: Any, *, plain: bool) -> None:
        """Inject stable then dynamic system context; leave prompt and durable history untouched.

        稳定前缀后附加动态系统上下文；不改任务正文或持久聊天历史。
        AstrBot excludes its initial system message from persisted conversation history.
        AstrBot 保存会话历史时排除首条系统消息；因此动态状态不会积累到历史。
        """
        kind = {"GroupMessage": "group", "FriendMessage": "dm"}.get(event.message_obj.type.value)
        route = self.routes.get((event.get_platform_id(), event.get_session_id(), kind or ""))
        if route is None:
            return
        if not event.get_sender_id() or not event.message_obj.message_id:
            raise ValueError("Verified sender and message ID required")
        key = self.event_key(event)
        old = self.turns.get(key)
        text = request.prompt or event.get_message_str()
        prepared = await self.bridge.call(
            "host_prepare_turn",
            {
                "envelope": {
                    "host_id": self.host,
                    "platform": route["runtime_platform"],
                    "actor_id": event.get_sender_id(),
                    "endpoint_id": route["endpoint_id"],
                    "chat_type": kind,
                    "session_id": _key(event.get_platform_id(), event.get_session_id()),
                    "turn_id": key,
                    "message_id": str(event.message_obj.message_id),
                    "text": text,
                    "input_is_verbatim": plain and text == event.get_message_str(),
                    # AstrBotMessage.timestamp defaults to receipt time, not attested source time.
                    # AstrBotMessage.timestamp 默认为接收时钟，不能冒充已证实的源时间。
                    "timestamp": None,
                },
                "capabilities": {
                    "pre_generation": True,
                    "post_generation": True,
                    "participant_identity": True,
                    "group_identity": True,
                    "reliable_delivery_ack": False,
                },
            },
        )
        projection = prepared["context"]
        suffix = (
            "\n"
            + projection["stable_prefix"]
            + "\nRuntime session_id: "
            + prepared["turn_id"]
            + "\nTurn-local context:\n"
            + json.dumps(projection["temporary"], ensure_ascii=False)
        )
        base = request.system_prompt or ""
        if old and base.endswith(old["suffix"]):
            base = base[: -len(old["suffix"])]
        request.system_prompt = base + suffix
        self.turns[key] = {
            "capability": prepared["capability"],
            "turn_id": prepared["turn_id"],
            "suffix": suffix,
        }
        while len(self.turns) > 128:
            self.turns.popitem(last=False)
        if request.func_tool is not None:
            # Clone the request's tool list; never mutate globally shared MCP tools or credentials.
            # 复制本请求工具列表，不修改全局共享 MCP 工具或凭据。
            request.func_tool = copy(request.func_tool)
            request.func_tool.tools = [
                self.scoped_tool(tool, key) for tool in request.func_tool.tools
            ]

    def scoped_tool(self, tool: Any, key: str) -> Any:
        """Wrap existing MCP tools with the current capability; never duplicate tool schemas.

        以当前能力令牌包装已有 MCP 工具，不另建工具 Schema，也不回退管理凭据。
        """
        if getattr(tool, "mcp_server_name", None) != "agentcosplay":
            return tool
        wrapped = copy(tool)
        name = tool.mcp_tool.name

        async def call(_self: Any, context: Any, **kwargs: Any) -> CallToolResult:
            try:
                turn = self.turns[key]
                result = await self.bridge.model_call(
                    turn["capability"], turn["turn_id"], name, kwargs
                )
                envelope = {"ok": True, "result": result}
            except Exception:
                envelope = {"ok": False, "error": "Verified Runtime turn required"}
            # AstrBot dispatches MCPTool results by SDK type, not JSON string content.
            # AstrBot 按宿主 SDK 类型分派 MCPTool 结果，不能返回普通 JSON 字符串。
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(envelope, ensure_ascii=False))]
            )

        wrapped.call = MethodType(call, wrapped)
        return wrapped

    async def observe(self, event: Any, response: Any) -> None:
        """Observe completion_text only; no reasoning, final decoration or delivery claim.

        只观察 completion_text；不保存推理，不冒充最终装饰内容或投递回执。
        """
        turn = self.turns.get(self.event_key(event))
        if not turn:
            return
        await self.bridge.call(
            "host_observe_generation",
            {
                "turn_id": turn["turn_id"],
                "operation_id": _key(turn["turn_id"], "generation"),
                "text": response.completion_text,
            },
        )
        await self.bridge.call(
            "host_finalize_turn",
            {
                "turn_id": turn["turn_id"],
                "operation_id": _key(turn["turn_id"], "finalize"),
            },
        )
