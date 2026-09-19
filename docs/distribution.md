# agentcosplay 分发与验收

版本 1.1.0，2026-09-19。完整产品采用本地 / self-hosted 存储，不依赖作者托管服务。

- 人工和 Agent：同一仓库 `install.py`，完整 Runtime、适配配置和 Skill；默认程序与人物数据分离。
- `install.sh`：下载仓库并执行完整安装器；不再只下载 Skill。
- `skills.md` / `AGENTS.md`：整仓库安装的发现入口；原生配置使用 Codex TOML、Hermes YAML、AstrBot JSON。
- `.agents/plugins/marketplace.json`：官方 marketplace 清单，源 `./plugins/agentcosplay`。
- `plugins/agentcosplay/plugin.json` 与 `.codex-plugin/plugin.json`：同名同版本分发清单；插件目录自包含。
- `downloads/agentcosplay-skill.zip` / `install-skill.sh`：可选的单独对话规则，不能代替完整安装。

普通用户无需作者 API Key；完整本地 Runtime 需要 Python 3.11+，依赖由安装器在独立目录自动准备。内部 Python module 仍叫 `character_runtime`，保留旧 CLI 别名以免破坏现有接入；产品名和版本统一为 agentcosplay / 1.1.0。

ChatGPT 工作区可按权限从 GitHub 导入 marketplace 后供成员安装；仓库上传不等于公开目录上架。无后端时只有当前会话角色对话，ChatGPT 云端不能直接连接用户 localhost。移动端连续互动可以通过用户已有 Hermes/AstrBot Gateway 使用同一 Runtime；不是作者云同步。

[安装与恢复](../INSTALL.md) · [本次验收与局限](installation-audit.md)

修改 Skill 后运行 `python -m scripts.build_distribution` 生成确定性 ZIP，更新 **install-skill.sh** 校验值；完整安装器从源码和 uv.lock 构建。ZIP 是正式下载资产，其余临时构建和缓存不提交。

官方格式依据：[OpenAI marketplace](https://learn.chatgpt.com/docs/enterprise/plugin-management)、[Plugin 格式](https://developers.openai.com/plugins/build/plugins)、[Hermes MCP](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp/)、[AstrBot MCP](https://docs.astrbot.app/use/mcp.html)。AstrBot 原生 mcp_server.json 的 mcpServers / active 与 HTTP transport 字段另对照其 [配置加载源码](https://github.com/AstrBotDevs/AstrBot/blob/master/astrbot/core/provider/func_tool_manager.py) 和 [客户端源码](https://github.com/AstrBotDevs/AstrBot/blob/master/astrbot/core/agent/mcp_client.py)。
