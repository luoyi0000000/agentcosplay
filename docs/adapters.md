# 宿主接入契约

安装步骤集中在 [INSTALL](../INSTALL.md)。全部入口使用同一 Runtime、owner、character ID，session ID 按渠道和会话隔离。模型由宿主提供，后端不调用 LLM。

## 工具

MCP 发现提供真实输入 Schema。工具返回 ok/result，业务失败 ok=false；还须检查协议 is_error。

| 工具 | 用途 |
|---|---|
| character_read / character_write | 角色摘要、定义、OOC 修改；没有 delete 操作 |
| session_control | 选角、OOC、临时模式、默认/项目路由 |
| runtime_context | 有界、按查询选择的角色/记忆/Companion/Self Model |
| turn_commit | RawEvent 证据提案、operation_id、事务与目标 allowlist |
| memory_recall / memory_write / memory_promote | 角色隔离、遗忘及真实用户确认 |
| character_export / character_import | 默认无私人经历的 V1，显式 Companion V2 |
| companion_control | OOC 配置功能、情绪、目标、习惯、未完成话题 |
| provider_observe | 宿主提交有来源和有效期的环境观测 |
| proactive_decide / proactive_ack | 联系意图保留、发送前复核、实际送达回执 |

同一 Skill 由宿主加载，参考文件只按需读取。普通角色对话不需要文件或 shell 权限。

## 原生适配

install.py 生成 Codex TOML、Hermes YAML、AstrBot JSON 配置并保留其他服务，不再提供可能漂移的静态示例配置。AstrBot 需核实其实际持久目录，容器内的路径必须对运行进程可见；停止宿主后编辑再重载。

同机共享使用 INSTALL 中 connect --transport http / run。不同主机、Docker 网络、ChatGPT 云端不能把各自的 localhost 当成同一个服务。

高级自托管沿用用户现有 HTTPS/OAuth 服务。配置 CHARACTER_OAUTH_ISSUER、CHARACTER_OAUTH_AUDIENCE、CHARACTER_OAUTH_JWKS_URL 和 CHARACTER_RESOURCE_URL，使用 RS256 JWT、有效 iss/sub/aud/iat/exp 和 character:access scope。Runtime 验证签名、受众、过期、scope、Host/Origin；不是 OAuth 授权服务器。非回环监听必须有 OAuth，静态 token 只用于同一用户的回环入口。

默认 local-user 仅代表单个真实用户。多人 bot 必须先做额外身份映射/OAuth；不能让陌生人共享此身份。多个角色群聊 orchestration 和社交图不在本轮实现范围。

## Plugin 与品牌字段

以 [OpenAI 当前 Plugin 文档](https://developers.openai.com/plugins/build/plugins) 为依据（2026-09-20核对）：根 plugin.json 的 extensions.com.openai 是权威 OpenAI 元数据源，存在时整体替代 .codex-plugin/plugin.json overlay，不合并。两份 interface 保持相同以兼容旧宿主。

logo 为 ./assets/logo.png，composerIcon 为 ./assets/composer-icon.png，brandColor 为 #A64965。Logo 保留用户 P1 原文件；composer icon 只从其中心正方形裁切并等比例缩放。维护检查验证两份 interface 相同、资源路径及完整 PNG 数据。

当前没有作者托管服务或移动端本机 Runtime。支持 Marketplace 导入的环境可安装规则，未连接后端仍能当前会话聊天。

官方适配资料：[Codex MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)、[Hermes MCP](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp/)、[AstrBot MCP](https://docs.astrbot.app/use/mcp.html)。

## 2.x 调用迁移

旧写入保留工具名但拒绝无证据请求。先 event_ingest，再 turn_commit(proposal)。编辑前在 OOC 读取相应对象获得 allowlist。读取工具实时 Schema，不复用旧 candidates/turn_id 参数。平台转发必须提供稳定身份绑定；未知身份只可有限无状态回应。上下文消费 stable_prefix + temporary，替换旧人物投影，不能累积多个角色前缀。增长、媒体、诊断及完整投递流程见 docs/reference.md、docs/companion.md。
