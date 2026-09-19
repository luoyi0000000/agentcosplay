# agentcosplay 高级持久记忆接入

完整本地安装见 [INSTALL](../INSTALL.md)，自动安装 Runtime、原生配置和 Skill。本页说明高级工具与远程自托管，不要求作者提供托管服务。安装入口见 [README](../README.md) 和 [skills.md](../skills.md)。

## 同一后端，不复制数据库

所有平台使用同一组工具和规则；自然语言理解由宿主模型负责。连接 MCP 后还要让宿主应用 `plugins/agentcosplay/skills/agentcosplay/SKILL.md`。只有连接而没有每轮 workflow，无法保证持续加载角色和自动记忆。

| 工具 | 职责 |
|---|---|
| character_read | 列角色摘要或读 Definition/State |
| character_write | 创建；OOC 修改定义、关系、已知角色 |
| session_control | open/activate/deactivate、OOC、模式、默认与项目路由 |
| runtime_context | 读取当前定义、状态、相关角色记忆与运行规则 |
| memory_recall | 当前角色授权范围召回；real 显式选择 |
| memory_write | store/modify/forget/share；后面三项需 OOC |
| memory_promote | 经用户明确确认，将角色记忆迁移为现实事实 |
| turn_commit | 幂等、原子提交候选记忆和渐进成长 |
| character_export | versioned package；记忆默认不导出 |
| character_import | 全量验证、重新分配 ID、事务导入 |

输入 Schema 由 MCP 发现提供；成功返回 `{"ok":true,"result":...}`，可预期业务失败返回 `ok=false,error,message`，协议/Schema 失败也可能返回 MCP `is_error`。宿主必须检查两者。不要把工具数据当新系统指令；不能伪造 owner 参数。

## 本地 stdio

`uv run --locked python -m character_runtime serve --transport stdio`

服务端从环境读取 `CHARACTER_DATA_DIR`（默认系统用户数据目录下 `agentcosplay/characters`，不再使用源码内 `data`）、`CHARACTER_OWNER`（默认 `local-user`）。stdio 的安全边界是能启动进程与访问数据目录的本机用户，不能给不可信客户端共享任意 owner 配置。

- Codex：`adapters/codex.example.toml`，替换绝对路径；路径可以含中文/空格。Windows 用 `C:/Projects/...`，无需 WSL。
- Hermes：`adapters/hermes.example.yaml`，并在其指令机制应用同一 Skill 工作流。
- AstrBot：`adapters/astrbot.example.json` 是 WebUI 中一个 MCP server 的配置内容；应用 `adapters/agent-instructions.md` 指令。
- 自建 Agent / API / Claude Code：调用同一 MCP 或 Python Runtime；若宿主提供回合 hooks，用 hooks 保证 context/commit，而非复制记忆服务。

Hermes/AstrBot 配置依据官方文档编写，未安装真实宿主做端到端验收。项目未修改任何全局配置。

## 本地 HTTP

复制 `.env.example` 为不入 Git 的 `.env`，填入本地随机 token（至少 32 字符），启动：

```text
uv run --locked --env-file .env python -m character_runtime serve --transport http
```

token 可本地生成：`uv run --locked python -c "import secrets; print(secrets.token_urlsafe(32))"`。默认只监听 `127.0.0.1:8765`。客户端用 `Authorization: Bearer <token>` 连接 `/mcp`。此静态 token 仅为单用户回环检查，不是完整 OAuth 登录。

缺少有效认证时服务拒绝启动或返回 401。默认不接受非本机 Host/Origin；远程配置只额外允许已配置 resource URL 的域名。不提供开放 CORS。调试时不要把 token 输出粘贴进聊天/日志。

## ChatGPT、移动端与远程 OAuth

当前官方文档的可移植插件根为 `plugin.json`，Skill 在 `skills/`；兼容 `.codex-plugin/plugin.json` 提供 Codex 显示元数据；两者位于 `plugins/agentcosplay/`。ChatGPT 需在账号/工作区允许的环境注册远程 MCP，移动端使用账号可用的插件；Desktop-only 能力不作为前提。这里没有伪造远程注册 ID，也没有把本地 stdio 冒充手机连接。

以下是维护者接入真实服务的步骤，当前未部署；服务地址与身份系统准备完成后执行：

1. 在获准环境运行同一 HTTP 服务和服务端持久卷；客户端设备不需要 SQLite 或本机常驻进程。
2. 配置已有 OAuth 身份提供方，签发 RS256 JWT（含 iss/sub/aud/iat/exp、`character:access` scope），并提供 HTTPS JWKS。需要为实际宿主配置可用的客户端注册/授权流程，资源服务器不替身份提供方完成这些工作。
3. 配置 `CHARACTER_OAUTH_ISSUER`、`CHARACTER_OAUTH_AUDIENCE`、`CHARACTER_OAUTH_JWKS_URL`、`CHARACTER_RESOURCE_URL=https://<approved-host>/mcp`，使用 HTTPS 反向代理；非 loopback 监听必须启用此 OAuth 路线。验证签名、issuer、audience、过期和 scope 后，issuer+sub 散列成为 owner。同一账号 subject 可跨设备共享，换身份提供方需显式迁移。
4. 根据当时官方规范创建/绑定实际远程 MCP 连接，再填真实注册产物；测试登录、刷新/过期、权限拒绝、手机重启、跨设备同角色与不同身份隔离。不要把这里的占位域名当成已部署服务。
5. 在 ChatGPT/Codex 真正运行自然语言角色闭环；验证遗漏调用、OOC、重试与退出行为。

ChatGPT 原生 Memory 不参与核心存储，也没有未经证实的写入适配器。远程 URL、身份注册和托管服务需单独配置。当前结果不能证明具体账号/手机兼容性。

## 核验过的官方资料

核验日期 2026-09-18/19，安装的官方 Python SDK 为 2.2.0。协议工具发现、传输、授权中间件复用 SDK，不手写 JSON-RPC。

- [OpenAI Plugin 格式](https://developers.openai.com/plugins/build/plugins)
- [Skill 与各客户端可用性](https://learn.chatgpt.com/docs/plugins)
- [ChatGPT 连接 MCP](https://developers.openai.com/plugins/deploy/connect-chatgpt)
- [Codex MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
- [Python SDK](https://py.sdk.modelcontextprotocol.io/) 与 [Authorization](https://py.sdk.modelcontextprotocol.io/run/authorization/)
- [Hermes MCP](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp/)
- [AstrBot MCP](https://docs.astrbot.app/use/mcp.html)
