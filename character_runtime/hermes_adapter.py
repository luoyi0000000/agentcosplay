"""Official Hermes hooks: ephemeral context and scoped MCP, never delivery receipts.

Hermes 官方钩子：临时上下文与受限 MCP 调用，绝不把生成冒充投递回执。
"""

import hashlib
import hmac
import json
import threading
import time
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .host_client import HostBridge

UNAVAILABLE = "agentcosplay unavailable: no verified Runtime context; do not invent memories."


def _key(*parts: str) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=True).encode()).hexdigest()


class HermesAdapter:
    """Bind explicit platform routes; cache only transient input and turn capabilities.

    仅匹配显式平台路由；缓存只含瞬时输入和单轮令牌，不维护第二份长期状态。
    """

    def __init__(self, url: str, token_file: Path, host: str, routes: list[dict[str, str]]) -> None:
        self.bridge = HostBridge(url, token_file)
        self.host = host
        self.routes: dict[tuple[str, ...], dict[str, str]] = {}
        for route in routes:
            fields = ("platform", "chat_id", "thread_id", "chat_type")
            key = tuple(route[field] for field in fields)
            if (
                key in self.routes
                or route["kind"] not in {"dm", "group"}
                or route["chat_type"] not in {"dm", "group", "channel", "thread"}
                or route["kind"] != ("dm" if route["chat_type"] == "dm" else "group")
                or not all(isinstance(v, str) and len(v) <= 200 for v in route.values())
                or not all(
                    route[k] for k in (*fields[:2], "chat_type", "runtime_platform", "endpoint_id")
                )
            ):
                raise ValueError("Explicit unique Hermes routes are required")
            self.routes[key] = dict(route)
        if not host or len(host) > 200:
            raise ValueError("A stable Host ID is required")
        self.lock = threading.Lock()
        self.inputs: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
        self.turns: OrderedDict[tuple[str, str], tuple[str, str]] = OrderedDict()

    def capture(self, *, event: Any, **kwargs: Any) -> None:
        """Observe raw input without granting authority before gateway authentication.

        Gateway 鉴权前只暂存原始输入，不授权、不建立身份、不写入 Runtime。
        """
        try:
            source = event.source
            route = (
                source.platform.value,
                source.chat_id,
                source.thread_id or "",
                source.chat_type,
            )
            actor = event.user_id or source.user_id
            if (
                route not in self.routes
                or event.internal
                or event.media_urls
                or event.media_types
                or not actor
                or not event.message_id
                or not event.text
                or len(event.text) > 64000
            ):
                return
            timestamp = event.timestamp
            # An absent/offset-free source time is unknown, not the receipt clock.
            # 缺失或没有时区偏移的源时间保持未知，不能冒充接收时钟。
            source_time = (
                timestamp.astimezone(UTC).isoformat()
                if isinstance(timestamp, datetime) and timestamp.utcoffset() is not None
                else None
            )
            item = {
                "source_id": _key(self.host, *route),
                "source_event_id": _key(event.message_id),
                "source_kind": "USER_DIRECT",
                "content": event.text,
                "timestamp": source_time,
                "observed_at": datetime.now(UTC).isoformat(),
                "host": self.host,
                "actor_id": actor,
            }
            with self.lock:
                self.inputs[_key(*route, actor, event.message_id)] = (time.monotonic(), item)
                # ponytail: bounded transient captures; durable intake stays in Runtime.
                # 有界临时捕获；持久化输入缓冲仍由 Runtime 管理。
                while len(self.inputs) > 128:
                    self.inputs.popitem(last=False)
        except (AttributeError, TypeError, ValueError):
            return

    async def context(
        self,
        env: dict[str, str],
        *,
        session_id: str = "",
        turn_id: str = "",
        user_message: str = "",
        sender_id: str = "",
        parent_session_id: str = "",
        **kwargs: Any,
    ) -> str:
        """Project context only after Host dispatch; reject unknown actors and child agents.

        宿主正式调度后才投影上下文；拒绝未知 Actor 和未授权的子 Agent 继承身份。
        """
        cache_key = (session_id, turn_id)
        with self.lock:
            self.turns.pop(cache_key, None)
        try:
            route_key = tuple(
                env.get("HERMES_SESSION_" + k, "")
                for k in ("PLATFORM", "CHAT_ID", "THREAD_ID", "CHAT_TYPE")
            )
            route = self.routes[route_key]
            actor = env.get("HERMES_SESSION_USER_ID", "")
            if (
                not session_id
                or not turn_id
                or not actor
                or parent_session_id
                or (sender_id and sender_id != actor)
            ):
                return UNAVAILABLE
            request: dict[str, Any] = {
                "host_id": self.host,
                "platform": route["runtime_platform"],
                "actor_id": actor,
                "endpoint_id": route["endpoint_id"],
                "chat_type": route["kind"],
                "session_id": _key(session_id),
                "turn_id": _key(session_id, turn_id),
                "message_id": _key(env.get("HERMES_SESSION_MESSAGE_ID") or turn_id),
                "text": user_message,
                "input_is_verbatim": False,
            }
            with self.lock:
                captured = self.inputs.get(
                    _key(*route_key, actor, env.get("HERMES_SESSION_MESSAGE_ID", ""))
                )
            # Host-added prefixes, transcripts and forwarded text are not exact user evidence.
            # 宿主拼接前缀、转录、转发正文不冒充用户原话；不匹配时只加载上下文。
            if captured and time.monotonic() - captured[0] < 300:
                if captured[1]["content"] == user_message:
                    request.update(input_is_verbatim=True, timestamp=captured[1]["timestamp"])
            opened = await self.bridge.call(
                "host_prepare_turn",
                {
                    "envelope": request,
                    "capabilities": {
                        "pre_generation": True,
                        "post_generation": True,
                        "participant_identity": True,
                        "group_identity": True,
                        "reliable_delivery_ack": False,
                    },
                },
            )
            capability, runtime_turn = opened["capability"], opened["turn_id"]
            result = opened["context"]
            with self.lock:
                self.turns[cache_key] = (capability, runtime_turn)
                while len(self.turns) > 128:
                    self.turns.popitem(last=False)
            return (
                str(result["stable_prefix"])
                + "\nRuntime session_id: "
                + str(runtime_turn)
                + "\nTurn-local context:\n"
                + json.dumps(result["temporary"], ensure_ascii=False)
            )
        except Exception:
            return UNAVAILABLE

    async def observe(
        self,
        *,
        session_id: str = "",
        turn_id: str = "",
        assistant_response: str = "",
        **kwargs: Any,
    ) -> None:
        """Observe the official final generation; ignore history and never acknowledge delivery.

        只观察官方最终生成正文；忽略历史及隐藏推理，不产生投递确认。
        """
        try:
            with self.lock:
                _, runtime_turn = self.turns[(session_id, turn_id)]
            await self.bridge.call(
                "host_observe_generation",
                {
                    "turn_id": runtime_turn,
                    "operation_id": _key(runtime_turn, "generation"),
                    "text": assistant_response,
                },
            )
            await self.bridge.call(
                "host_finalize_turn",
                {"turn_id": runtime_turn, "operation_id": _key(runtime_turn, "finalize")},
            )
        except Exception:
            # Host hooks must not leak private text or tokens through exception logs.
            # 宿主钩子失败不得通过异常日志泄漏私人正文或令牌。
            return

    async def tool(
        self, session_id: str, turn_id: str, tool: str, arguments: dict[str, Any]
    ) -> str:
        """Intercept existing MCP tools without falling back to owner credentials.

        截获现有 MCP 工具，不注册重复 API，也不回退 Owner 凭据。
        """
        try:
            with self.lock:
                capability, runtime_turn = self.turns[(session_id, turn_id)]
            result = await self.bridge.model_call(capability, runtime_turn, tool, arguments)
            return json.dumps({"ok": True, "result": result}, ensure_ascii=False)
        except Exception:
            return json.dumps({"ok": False, "error": "Verified Runtime turn required"})

    def clear(self, *, session_id: str = "", **kwargs: Any) -> None:
        """Drop session capabilities without resetting canonical memory or bindings.

        仅清除会话能力令牌，不重置长期记忆和身份绑定。
        """
        with self.lock:
            for key in list(self.turns):
                if key[0] == session_id:
                    del self.turns[key]


def register(ctx: Any, root: Path) -> None:
    """Register public hooks and one canonical Skill; no tools or delivery ACK hooks.

    注册官方钩子和唯一 Skill；不注册重复工具或伪造投递回执钩子。
    """
    # These imports belong to the host; Core never depends on Hermes.
    # 这些导入属于宿主层，Core 不依赖 Hermes。
    from gateway.session_context import get_session_env  # type: ignore[import-not-found]
    from hermes_cli.config import load_config_readonly  # type: ignore[import-not-found]
    from hermes_cli.plugins import resolve_plugin_command_result  # type: ignore[import-not-found]

    adapter = HermesAdapter(
        ctx.get_config("runtime_url"),
        Path(ctx.get_config("token_file")),
        ctx.get_config("host_id", "hermes"),
        ctx.get_config("routes", []),
    )
    with adapter.bridge.token_file.open(encoding="ascii") as source:
        owner_token = source.read(4097).strip()
    if not 32 <= len(owner_token) <= 4096:
        raise ValueError("Invalid Runtime credential file")
    discovery = hmac.new(
        owner_token.encode(), b"agentcosplay:model-discovery:v1", hashlib.sha256
    ).hexdigest()
    server = (load_config_readonly() or {}).get("mcp_servers", {}).get("agentcosplay", {})
    if (
        server.get("url") != adapter.bridge.url
        or server.get("command")
        or server.get("headers", {}).get("Authorization") != "Bearer " + discovery
    ):
        raise ValueError("Connect Hermes with --native-hermes before enabling the plugin")

    async def pre_llm_call(**kwargs: Any) -> str:
        env = {
            "HERMES_SESSION_" + k: get_session_env("HERMES_SESSION_" + k)
            for k in ("PLATFORM", "CHAT_ID", "CHAT_TYPE", "THREAD_ID", "USER_ID", "MESSAGE_ID")
        }
        return await adapter.context(env, **kwargs)

    def tool_execution(
        tool_name: str,
        args: dict[str, Any],
        next_call: Any,
        session_id: str = "",
        turn_id: str = "",
        **kwargs: Any,
    ) -> Any:
        prefix = "mcp__agentcosplay__"
        if not tool_name.startswith(prefix):
            return next_call(args)
        # Hermes execution middleware fails open on exceptions; always return an error envelope.
        # Hermes 执行中间件异常时会继续下游，因此必须返回错误信封；发现令牌另行兜底拒绝。
        try:
            return resolve_plugin_command_result(
                adapter.tool(session_id, turn_id, tool_name[len(prefix) :], args)
            )
        except Exception:
            return json.dumps({"ok": False, "error": "Verified Runtime turn required"})

    ctx.register_hook("pre_gateway_dispatch", adapter.capture)
    ctx.register_hook("pre_llm_call", pre_llm_call)
    ctx.register_hook("post_llm_call", adapter.observe)
    for name in ("on_session_end", "on_session_reset", "on_session_finalize"):
        ctx.register_hook(name, adapter.clear)
    ctx.register_middleware("tool_execution", tool_execution)
    ctx.register_skill("agentcosplay", root / "plugins/agentcosplay/skills/agentcosplay/SKILL.md")
