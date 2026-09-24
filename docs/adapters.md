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
| character_export / character_import | 默认 V3 无私人经历；接受 V1/V2 兼容导入 |
| companion_control | OOC 配置功能、目标、习惯、话题；情绪变化用 AffectEffect |
| provider_observe | 宿主提交有来源和有效期的环境观测 |
| proactive_decide / proactive_ack | 联系意图保留、发送前复核、实际送达回执 |

同一 Skill 由宿主加载，参考文件只按需读取。普通角色对话不需要文件或 shell 权限。

## 原生适配

install.py 生成 Codex TOML、Hermes YAML、AstrBot JSON 配置并保留其他服务，不再提供可能漂移的静态示例配置。AstrBot 需核实其实际持久目录，容器内的路径必须对运行进程可见；停止宿主后编辑再重载。

同机共享使用 INSTALL 中 connect --transport http / run。不同主机、Docker 网络、ChatGPT 云端不能把各自的 localhost 当成同一个服务。

Native bridge authentication separates discovery, turn execution and owner administration. The local discovery credential can list schemas but cannot execute a Runtime tool. `HostBridge.model_call` requires a nonempty verified turn capability; errors never fall back to the owner token. The bridge uses the existing MCP SDK, disables credential-bearing redirects/environment proxies, redacts failures and owns no state database.

原生桥接将工具发现、单轮执行与 Owner 管理凭据分开。本地发现凭据只能读取工具 Schema，不能执行 Runtime 操作；模型调用必须提供已验证的单轮令牌，失败不能回退到管理凭据。桥接复用现有 MCP SDK，不携带凭据跟随重定向或环境代理，错误脱敏，也不持有状态数据库。Hermes 原生接入须通过 `connect --native-hermes` 使用发现凭据；既有单用户 MCP 入口继续保留。

Hermes integration research is pinned to official source `439eb0395eed5025139ee917526f31e2d161699e` (declared version 0.21.4), not an installed-host validation. Its `pre_llm_call` supports ephemeral context; `post_llm_call` observes generation, not delivery. The generic plugin hook registry has no final-send receipt. The internal post-delivery callback is invoked from cleanup and does not attest success or final content. The chosen integration uses official hooks only, without version-bound Gateway extensions or synthetic delivery ACKs.

Hermes 接口核对依据官方源码 0.21.4，不代表已在真实宿主验证。pre_llm_call 可注入临时上下文，post_llm_call 只观察生成；通用插件钩子没有最终发送回执。用户已选择仅用官方钩子，不增加版本限定 Gateway 扩展，也不伪造成功 ACK。

The native entry (`plugin.yaml`, `__init__.py`) registers one canonical Skill, passive pre-dispatch capture, turn-local pre-LLM context, post-LLM generation observation, session cleanup and existing-MCP tool middleware. Official hooks call the shared prepare/observe/finalize lifecycle automatically. It has no database, model or duplicate tool registry. Explicit actor/endpoint routes resolve through Runtime bindings; unknown actors, subagents and mismatched audience types fail closed. Only matching raw text is ingested after authorized Host dispatch; transformed text loads context without fabricating evidence. Missing source time remains unknown with a separate observation clock. The optional sender hook field is checked when present; task-local actor identity remains mandatory.

原生入口注册唯一 Skill、调度前被动捕获、单轮上下文、生成观察、会话清理与现有 MCP 工具中间件。官方钩子自动调用共享 prepare/observe/finalize 生命周期。身份依赖 Runtime 显式绑定；未知身份、子 Agent、受众类型不匹配时拒绝访问。调度前捕获不写库，仅在宿主正式进入模型阶段且原文匹配时提交用户事件；转录或改写正文不冒充原话。源时间缺失时保持未知并单独记录观察时间。可选 sender 字段存在时必须一致，逐轮 Actor 元数据始终必需。生成回调不读取隐藏推理或整段宿主历史，结束生成仍保持投递未知。会话重置不删除长期状态。

**Final delivery confirmation is unsupported.** This adapter does not orchestrate native bursts, typing, debounce generation, proactive sends or final receipts. Runtime delivery APIs retain authority/claim/unknown guarantees, but independent Hermes automatic sends are outside that state machine. Do not enable two automatic host responders for the same endpoint. Disabling the plugin leaves discovery-only MCP unable to execute tools; the owner may explicitly reconnect single-user MCP mode. Live dual-host acceptance remains pending.

**此 Adapter 不支持最终投递确认。** 不自动接管 Hermes 分段、输入状态、合并生成、主动发送或发送回执；Runtime 的完整发送协议继续保留，但 Hermes 自身自动回复尚未接入该状态机。同一 Endpoint 不可同时启用两个宿主自动回复。停用插件后发现凭据无法执行工具；Owner 可显式重新连接原有单用户 MCP 模式。真实双 Host 验收仍待完成。

AstrBot native entry uses official `on_llm_request` and `on_llm_response`, explicit platform-instance/endpoint routes and the same Runtime lifecycle. Stable prefix precedes dynamic context in the request system message; AstrBot excludes that initial system message from saved history. It wraps existing MCP tools per request with a turn capability, without modifying global tool instances. `completion_text` is observed; hidden reasoning is ignored. SDK 1.x and 2.x share the same thin transport, with no dependency-major replacement, proxy inheritance or redirects.

AstrBot 原生入口使用官方请求/响应钩子、显式平台实例/Endpoint 路由及同一 Runtime 生命周期。请求系统消息中先放稳定前缀再放动态上下文；AstrBot 不将该首条系统消息写入历史。已有 MCP 工具按请求包装单轮令牌，不修改全局工具实例。只观察 `completion_text`，忽略隐藏推理。轻量传输兼容宿主 SDK 1.x 和 2.x，不替换依赖主版本、不继承代理、不跟随重定向。

Official source inspected: AstrBot 4.28.1, `95e98b8aed75d56713666eff39e31bafffd95426`. Its respond stage catches send exceptions before invoking `after_message_sent`; this callback is not a reliable receipt. Both native bridges therefore declare `reliable_delivery_ack=false`; generated/finalized remains separate from delivered. This is a source-contract and synthetic integration result, not a live-platform certification. Sources: [plugin guide](https://docs.astrbot.app/dev/star/plugin-new.html), [respond stage](https://github.com/AstrBotDevs/AstrBot/blob/95e98b8aed75d56713666eff39e31bafffd95426/astrbot/core/pipeline/respond/stage.py), [history persistence](https://github.com/AstrBotDevs/AstrBot/blob/95e98b8aed75d56713666eff39e31bafffd95426/astrbot/core/pipeline/process_stage/method/agent_sub_stages/internal.py).

所核对官方源码版本为 AstrBot 4.28.1。发送阶段捕获异常后仍触发 `after_message_sent`，因此两个原生 Bridge 均明确声明无可靠 ACK，生成/结束与送达分离。这是源码契约及合成接入验证，不是真实平台认证。

Sources / 依据：[Hermes plugin contract](https://hermes-agent.nousresearch.com/docs/zh-Hans/developer-guide/plugins), [hook registry](https://github.com/NousResearch/hermes-agent/blob/439eb0395eed5025139ee917526f31e2d161699e/hermes_cli/plugins.py), [gateway delivery lifecycle](https://github.com/NousResearch/hermes-agent/blob/439eb0395eed5025139ee917526f31e2d161699e/gateway/platforms/base.py).

高级自托管沿用用户现有 HTTPS/OAuth 服务。配置 CHARACTER_OAUTH_ISSUER、CHARACTER_OAUTH_AUDIENCE、CHARACTER_OAUTH_JWKS_URL 和 CHARACTER_RESOURCE_URL，使用 RS256 JWT、有效 iss/sub/aud/iat/exp 和 character:access scope。Runtime 验证签名、受众、过期、scope、Host/Origin；不是 OAuth 授权服务器。非回环监听必须有 OAuth，静态 token 只用于同一用户的回环入口。

默认 local-user 标识 Runtime 管理命名空间；单用户 Participant 默认等于 Owner。多人 Bot 必须显式验证每个 Actor 的 Participant 绑定，群聊只读取 Endpoint 公开上下文；不能把陌生人映射到 Owner。多个角色群聊 orchestration 和社交图不在本轮实现范围。

## Plugin 与品牌字段

以 [OpenAI 当前 Plugin 文档](https://developers.openai.com/plugins/build/plugins) 为依据（2026-09-20核对）：根 plugin.json 的 extensions.com.openai 是权威 OpenAI 元数据源，存在时整体替代 .codex-plugin/plugin.json overlay，不合并。两份 interface 保持相同以兼容旧宿主。

logo 为 ./assets/logo.png（560×560），composerIcon 为 ./assets/composer-icon.png（256×256），brandColor 为 #A64965。当前资源已经接受，保留用户 P1 的视觉设计、构图和主要内容；为适配 Marketplace/API/Host，可以合理缩放或压缩，不要求历史 PNG 的二进制或 SHA256 不变。维护检查验证两份 interface 相同、资源路径及当前发布 PNG 的完整性。

PresentationProfile is an optional host presentation capability, not a missing Core contract. Bot avatars, sender names and webhook personas must not become identity evidence, VisualPrototype, Fact or LifeState.

PresentationProfile 是未来宿主可选的展示能力，不是当前 Core 缺项。Bot 头像、发送名称与 webhook 展示人格不得自动成为身份依据、VisualPrototype、Fact 或 LifeState。

当前没有作者托管服务或移动端本机 Runtime。支持 Marketplace 导入的环境可安装规则，未连接后端仍能当前会话聊天。

官方适配资料：[Codex MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)、[Hermes MCP](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp/)、[AstrBot MCP](https://docs.astrbot.app/use/mcp.html)。

## Conversation transport / 对话发送

`TurnLifecycle` is the automatic platform-neutral entry, independent of MCP. `prepare` resolves trusted identity and audience, preserves the complete input, bounds only retrieval and assembles context. `observe_generation` stores generated output in an audience-scoped lifecycle record; `finalize` applies optional proposals only through existing Knowledge evidence gates. Neither action creates delivery evidence. Hosts declare `HostCapabilities`; absent delivery ACK support remains false. Existing MCP functions expose the same methods as a transport for trusted bridge code, not as a requirement for the model to remember tool calls.

RecentTurnWindow and AmbientWindow are bounded views of authorized active RawEvents, not new Memory stores. Trusted hosts can submit public activity through `host_observe_ambient`; it never requests generation. Context excludes sensitive and legacy-unverified events, keeps whole payloads, and applies separate window budgets. DerivedTurnSignals report observed gaps, exact repetition and delivery uncertainty; they never change personality. Hosts without ambient observation simply have an empty ambient view.

近期对话及环境窗口是已授权有效 RawEvent 的有界视图，不新建长期记忆存储。可信宿主通过 `host_observe_ambient` 记录公开活动，不发起生成。上下文排除敏感及未经验证的旧记录，保留完整载荷并分别应用窗口预算。当前轮信号只报告观察到的间隔、精确重复及投递不确定性，不改变人格。宿主不支持环境观察时，该视图为空。

Expression cooldown uses at most twelve authorized visible/generated observations from the last day. Generated observations are labeled separately and never enter shared-experience windows or factual evidence. Repeated rhetorical markers yield soft variety hints, not output rewriting or a hard blacklist. VoiceProfile preferred/avoided patterns remain character configuration; observations never train or mutate them. Existing semantic behavior planning falls back to intact text where a Host lacks multi-message/reaction/reply capabilities.

表达冷却使用最近一天最多十二条已授权的发送或生成观察。生成观察单独标注，不能进入共同经历窗口或事实证据。重复修辞只产生柔性的表达变化建议，不自动改写输出、不建立硬禁词表。VoiceProfile 的偏好及避免句式仍由人物配置定义，不从观察中训练或修改。宿主缺少多消息、反应或引用能力时，既有语义行为规划保守降级为完整文本。

统一生命周期自动解析可信身份与受众、保留完整输入、限制检索投影并组装上下文。生成记录按受众隔离，结束阶段的可选提案复用既有 Knowledge 证据门；两者都不产生投递证据。源时间可为空，独立记录实际 observed_at；RawEvent 的 timestamp_basis 区分源时间与观察时间，旧记录不猜测来源。遗忘同时清理生成副本，防止迟到回调恢复正文。新增生命周期 collection 使用同一 SQLite；schema 4 升级先备份，旧记录不改写。

Trusted adapters use `host_turn_open(buffer_intake=true)` and `host_intake_claim` for one-shot generation from verified source events. Short inputs debounce for 450 ms, bounded to three seconds and 20 events; long inputs are ready immediately. Buffers store event references, preserving each actor.

可信 Adapter 使用合并入口领取一次生成权：短消息等待 450 毫秒，连续输入最多等待三秒、20 条，长输入立即就绪。缓冲区只保存原始事件引用，不丢失每条消息的 Actor。

`host_response_plan` groups host-model semantic units without splitting punctuation or calling another model. `host_response_claim` grants each due segment once and in order. `host_response_ack` records actual final delivery as per-segment ASSISTANT_VISIBLE events. Unknown or unacknowledged claims never grant retries after restart. Cancellation affects unsent segments only. New input invalidates older generations, including ones not yet planned; observing hosts cannot interrupt the active sender.

发送计划只组合宿主模型的语义单元，不切句号或调用第二模型。片段按顺序领取一次，实际送达后逐段记录可见事件。未知及未确认投递重启后也不能重发；只取消尚未发送片段。新输入使旧生成失效，旁观 Host 不得中断当前发送者。

Afterthoughts share Companion quiet hours, availability, cooldown and daily budget, reserved before sending even for unknown results. Erasure clears same-audience response copies and invalidates old generation; late ACK cannot restore bodies. Already-delivered payload corruption is recorded as a contract violation, not non-delivery. Unsafe persisted content becomes a bodyless tombstone. Export omits transport IDs.

补充消息复用 Companion 的安静时段、可用状态、冷却及每日预算，发送前占用，未知结果也占用。遗忘清理同受众发送副本并撤销旧生成，迟到回执不能恢复正文。已送达的载荷受损会记录契约违例，不能冒充未送达；不安全正文仅保存墓碑。导出不包含发送标识。

## 2.x 调用迁移

旧写入保留工具名但拒绝无证据请求。先 event_ingest，再 turn_commit(proposal)。编辑前在 OOC 读取相应对象获得 allowlist。读取工具实时 Schema，不复用旧 candidates/turn_id 参数。平台转发必须提供稳定身份绑定；未知身份只可有限无状态回应。上下文消费 stable_prefix + temporary，替换旧人物投影，不能累积多个角色前缀。增长、媒体、诊断及完整投递流程见 docs/reference.md、docs/companion.md。
