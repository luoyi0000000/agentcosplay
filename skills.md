# agentcosplay — Agent 安装入口

版本 1.1.0。用户只需提供完整仓库 URL 并说“安装这个项目”。本页是可读安装指引，不是 SKILL.md，也不是另造的宿主插件协议。

来源：https://github.com/luoyi0000000/agentcosplay

## 执行流程

1. 确认这是用户提出的安装任务。识别实际 Runtime 宿主、操作系统、Python 3.11+、Git、写入权限和当前 Agent/profile。不要在一次性的聊天沙盒安装后宣称用户机器已可用。
2. 读取仓库 [INSTALL.md](https://raw.githubusercontent.com/luoyi0000000/agentcosplay/main/INSTALL.md) 和安装器。clone 整个仓库；人工与 Agent 均执行同一个 `install.py`，使用相同 Runtime、版本和数据格式。
3. 根据宿主选 `--host codex`、`--host hermes` 或 `--host astrbot --host-dir <已核实的数据目录>`。AstrBot 容器内运行的进程必须看得到 Python、安装路径和持久卷。多宿主时使用用户当前请求的宿主；无法判断才询问。
4. 默认数据目录、依赖、单用户 owner 由安装器生成，不问无必要的问题。已有模型/API Key 沿用宿主设置，本项目不索取新的模型密钥。自定义目录须在源码、Git 和程序目录之外；保留现有安装记录里的目录与身份。
5. 执行完整安装，检查返回 `ok:true`，执行 `doctor`。安装器写本平台原生配置，保留其他 MCP 服务；冲突时先检查并备份用户改动，不能强制覆盖或绕过授权。YAML 重写可能改变注释，但私密原文件有备份。
6. 按宿主机制重新加载 MCP/Skills（AstrBot 配置仅在进程停止且已获管理权限时离线编辑）。实际发现 `character_write`、`session_control`、`runtime_context`、`turn_commit`、`memory_recall`；创建合成角色、打开专用测试 session、提交一个合成记忆、重新连接后召回，并用 character_write 的 delete 操作清理角色。先查看真实工具 Schema，不能猜参数。
7. 加载 `plugins/agentcosplay/skills/agentcosplay/SKILL.md` 与 `references/runtime.md`，按用户已指定人物开始自然对话。只有文件就绪但宿主未加载时，明确报告等待重载，不报完整成功。

手动入口示例：`python3 install.py --host hermes`。Windows 用 `py -3`。主程序和依赖放在用户目录，无需全局 pip 安装。升级、回滚、移除、恢复均由同一安装器管理，具体参数见 INSTALL。

## 多设备与多入口

优先让一个 Hermes/AstrBot Gateway 承接多个聊天渠道，共用本机持久数据。多个 Gateway 在同一主机运行时，使用 INSTALL 中的 `connect --transport http` 配置它们连接同一 Runtime 进程。不要给不同入口安装互相独立的数据库，不通过模型名称判断是否同一人物；共用同一 Runtime、owner 和 character ID，session ID 按渠道/会话隔离。群聊须限制为同一授权用户，不能向其他用户暴露共享身份。

分离主机或 Docker 网络不共用 localhost。遵循高级适配文档使用用户自有 HTTPS/OAuth 服务及容器网络；本安装器不猜网络拓扑，不开放无认证公网端口，不代购云资源。

## 只有插件页或聊天权限

marketplace 清单位于 `.agents/plugins/marketplace.json`，源 `./plugins/agentcosplay`。有管理权限的工作区可导入仓库安装对话规则；这不等于安装持久化 Runtime，也不等于公开上架。

AstrBot Skill ZIP：https://raw.githubusercontent.com/luoyi0000000/agentcosplay/main/downloads/agentcosplay-skill.zip 。可在插件 → 技能 → 上传技能导入；它是可选对话规则，不能作为 Python 插件上传。仅 Skill 的 macOS/Linux 备用安装器是 `install-skill.sh`。这些路线只有当前会话角色能力；若用户要求完整安装，说明缺少的宿主执行/管理权限，不能悄悄降级。

当前全部 Skills 只有 `agentcosplay`，包含角色工作流和自然表达。不把 README 或示例角色复制成其他 Skills；不修改宿主全局人格，不将角色经历写入平台全局 Memory，不打印/上传 token、API Key、数据库或安装备份。

官方机制：[Codex MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)、[Hermes MCP](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp/)、[AstrBot MCP](https://docs.astrbot.app/use/mcp.html)。入口形式参考用户提供的 [千问 skills.md](https://platform.qianwenai.com/skills.md)，不安装千问技能。
