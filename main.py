"""AstrBot native plugin entry using only official lifecycle hooks.

AstrBot 原生插件入口；仅使用官方生命周期钩子，角色状态由共享 Runtime 管理。
"""

import hashlib
import hmac
import json
from pathlib import Path

from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Plain
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star

from .character_runtime.astrbot_adapter import AstrBotAdapter


class AgentCosplay(Star):
    """Map Host callbacks without creating another Runtime or model.

    映射宿主回调，不创建第二个 Runtime 或模型。
    """

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        token_file = Path(config["token_file"])
        self.adapter = AstrBotAdapter(
            config["runtime_url"], token_file, config["host_id"], json.loads(config["routes_json"])
        )
        with token_file.open(encoding="ascii") as source:
            credential = source.read(4097).strip()
        if not 32 <= len(credential) <= 4096:
            raise ValueError("Invalid Runtime credential file")
        discovery = hmac.new(
            credential.encode(), b"agentcosplay:model-discovery:v1", hashlib.sha256
        ).hexdigest()
        path = Path(context.get_llm_tool_manager().mcp_config_path)
        servers = (
            json.loads(path.read_text(encoding="utf-8")).get("mcpServers", {})
            if path.exists()
            else {}
        )
        server = servers.get("agentcosplay")
        if server and (
            server.get("url") != config["runtime_url"]
            or server.get("command")
            or server.get("headers", {}).get("Authorization") != "Bearer " + discovery
        ):
            raise ValueError("Connect AstrBot with --native-astrbot before enabling this plugin")

    @filter.on_llm_request()
    async def prepare(self, event: AstrMessageEvent, request: ProviderRequest):
        """Project one authorized turn or stop the routed request safely.

        投影已授权单轮；失败时停止该请求，不输出私人异常正文。
        """
        try:
            await self.adapter.prepare(
                event, request, plain=all(isinstance(c, Plain) for c in event.message_obj.message)
            )
        except Exception:
            self.logger.error("agentcosplay context unavailable; inspect local Runtime diagnostics")
            event.stop_event()

    @filter.on_llm_response()
    async def observe(self, event: AstrMessageEvent, response: LLMResponse):
        """Record generation without asserting a send. / 记录生成，不声明发送成功。"""
        try:
            await self.adapter.observe(event, response)
        except Exception:
            self.logger.error(
                "agentcosplay generation observation failed; delivery remains unknown"
            )

    async def terminate(self):
        """Discard transient capabilities only. / 仅清除临时能力令牌。"""
        self.adapter.turns.clear()
