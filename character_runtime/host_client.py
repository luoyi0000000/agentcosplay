"""Thin MCP client for trusted hosts; no SQLite, state engine or model lives here.

可信宿主的轻量 MCP 客户端；不持有数据库、状态引擎或第二个模型。
"""

import importlib
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

# Use the Host's installed SDK, never replace its dependency major version.
# 使用宿主已安装的 SDK，不替换宿主依赖的主版本。
mcp = importlib.import_module("mcp")
httpx2 = importlib.import_module("httpx2" if hasattr(mcp, "Client") else "httpx")
http_transport = importlib.import_module("mcp.client.streamable_http")


@dataclass(frozen=True)
class HostBridge:
    """Keep owner credentials in host code and use turn credentials for model tools.

    管理凭据留在宿主代码；模型工具只使用本轮凭据，失败不回退管理权限。
    """

    url: str
    token_file: Path

    def __post_init__(self) -> None:
        address = urlsplit(self.url)
        if (
            address.scheme not in {"http", "https"}
            or not address.hostname
            or address.username is not None
            or address.password is not None
            or address.fragment
            or address.query
            or (
                address.scheme == "http"
                and address.hostname not in {"localhost", "127.0.0.1", "::1"}
            )
            or not self.token_file.is_absolute()
        ):
            raise ValueError(
                "Host bridge requires HTTPS or loopback HTTP and an absolute token path"
            )

    async def call(
        self,
        tool: str,
        arguments: dict[str, Any],
        *,
        capability: str | None = None,
    ) -> dict[str, Any]:
        """Execute one MCP call with bounded, redacted failure and no transport retries.

        执行一次 MCP 调用；错误脱敏，不自动重试有副作用的传输。
        """
        try:
            if capability is None:
                with self.token_file.open("r", encoding="ascii") as source:
                    credential = source.read(4097).strip()
            else:
                credential = capability
            if not credential or len(credential) > 4096 or not credential.isascii():
                raise ValueError("Invalid host credential")

            async def reject_redirect(response: Any) -> None:
                if 300 <= response.status_code < 400:
                    raise ValueError("Runtime redirects are not authorized")

            def create_http(**kwargs: Any) -> Any:
                return httpx2.AsyncClient(
                    headers={"Authorization": "Bearer " + credential},
                    timeout=5,
                    trust_env=False,
                    follow_redirects=False,
                    event_hooks={"response": [reject_redirect]},
                )

            async with AsyncExitStack() as stack:
                if hasattr(mcp, "Client"):
                    http = await stack.enter_async_context(create_http())
                    client = await stack.enter_async_context(
                        mcp.Client(
                            http_transport.streamable_http_client(self.url, http_client=http),
                            read_timeout_seconds=5,
                        )
                    )
                else:
                    # SDK 1.x exposes transport streams and an explicit initialized session.
                    # SDK 1.x 使用传输流及显式初始化的会话；仍保持禁代理和禁重定向。
                    streams = await stack.enter_async_context(
                        http_transport.streamablehttp_client(
                            self.url,
                            headers={"Authorization": "Bearer " + credential},
                            timeout=5,
                            sse_read_timeout=5,
                            httpx_client_factory=create_http,
                        )
                    )
                    client = await stack.enter_async_context(
                        mcp.ClientSession(
                            streams[0], streams[1], read_timeout_seconds=timedelta(seconds=5)
                        )
                    )
                    await client.initialize()
                result = await client.call_tool(tool, arguments)
                envelope = getattr(result, "structured_content", None) or getattr(
                    result, "structuredContent", None
                )
                failed = getattr(result, "is_error", False) or getattr(result, "isError", False)
                if failed or not isinstance(envelope, dict) or not envelope.get("ok"):
                    raise ValueError("Runtime rejected the host request")
                value = envelope.get("result")
                if not isinstance(value, dict):
                    raise ValueError("Unexpected Runtime response")
                return value
        except Exception:
            # Exceptions may contain HTTP headers or private response bodies.
            # 底层异常可能包含请求头或私人正文，禁止把异常内容带入宿主日志。
            raise RuntimeError(
                "agentcosplay host request failed; check local diagnostics"
            ) from None

    async def model_call(
        self,
        capability: str,
        turn_id: str,
        tool: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Never substitute an owner token when a turn capability is absent.

        缺少本轮能力令牌时直接拒绝，绝不替换成 Owner 令牌。
        """
        if not capability or not turn_id:
            raise ValueError("A verified turn capability is required")
        arguments = dict(arguments)
        if "session_id" in arguments and arguments["session_id"] != turn_id:
            raise ValueError("Model tool session does not match this interaction")
        return await self.call(tool, arguments, capability=capability)
