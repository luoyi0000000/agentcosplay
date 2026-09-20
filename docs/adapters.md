# 宿主接入与真实验收

安装步骤集中在 [INSTALL](../INSTALL.md)。全部入口使用同一 Runtime、owner、character ID，session ID 按渠道和会话隔离。模型由宿主提供，后端不调用 LLM。

## 工具

MCP 发现提供真实输入 Schema。工具返回 ok/result，业务失败 ok=false；还须检查协议 is_error。

| 工具 | 用途 |
|---|---|
| character_read / character_write | 角色摘要、定义、OOC 修改；没有 delete 操作 |
| session_control | 选角、OOC、临时模式、默认/项目路由 |
| runtime_context | 有界、按查询选择的角色/记忆/Companion/Self Model |
| turn_commit | 同一 turn_id 原子去重保存记忆、成长和 Companion 更新 |
| memory_recall / memory_write / memory_promote | 隔离、遗忘、共享及真实用户确认 |
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

## 可重复的真实宿主验收（尚待实机）

1. 在获准测试 profile 中安装并重载 Codex/Hermes/AstrBot；发现 Skill 和上述真实工具。
2. 使用同一授权身份及同一 HTTP 服务。在 Hermes 创建角色并提交合成记忆。
3. 在 AstrBot 选相同 character ID、不同 session ID，召回该记忆。
4. 在 AstrBot OOC 改称呼和目标，Hermes 下一轮 context 应看到同样状态。
5. 重启 Runtime 后重复读取；其他 owner/角色不能读取私人内容。
6. 分别检查无 Runtime 首用、空角色首用、工具故障继续聊天且不声称保存。
7. 主动联系只在获准测试渠道启用；两个 Scheduler 竞争同一决策，只一个保留成功。发送前用 reservation_id 复核，发送确认后 ack；不确定就保持 pending，不重发。

SDK 测试已模拟两个独立网关客户端，不能据此宣称三款真实应用的插件加载、QQ 路由或自然语言表现均验收通过。

## Plugin 与品牌字段

以 [OpenAI 当前 Plugin 文档](https://developers.openai.com/plugins/build/plugins) 为依据（2026-09-20核对）：根 plugin.json 的 extensions.com.openai 是权威 OpenAI 元数据源，存在时整体替代 .codex-plugin/plugin.json overlay，不合并。两份 interface 保持相同以兼容旧宿主。

logo 和 composerIcon 均为 ./assets/logo.png，brandColor 为 #A64965。图片为用户 P1 原文件，未裁切、未生成新身份。仅验证路径、文件、manifest 与包内容；真实 ChatGPT Plugin UI 和小尺寸可读性需人工验收。

当前没有作者托管服务或移动端本机 Runtime。支持 Marketplace 导入的环境可安装规则，未连接后端仍能当前会话聊天。

官方适配资料：[Codex MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)、[Hermes MCP](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp/)、[AstrBot MCP](https://docs.astrbot.app/use/mcp.html)。
