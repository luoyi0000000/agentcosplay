# 宿主接入契约

安装步骤集中在 [INSTALL](../INSTALL.md)。全部入口使用同一 Runtime、owner、character ID，session ID 按渠道和会话隔离。模型由宿主提供，后端不调用 LLM。

## Shared Host protocol / 共享宿主协议

`host_protocol.py` owns `HostIngress`, typed input evidence, `HostCapabilities`, the bounded/expiring `TurnRegistry`, stable Host keys, `ProjectionMapper` and `UniversalHostBridge`. Hermes/AstrBot retain only native event extraction, SDK hook registration and per-request wrapping. Both use the same prepare → tool → observe → finalize path, typed `UniversalGenerationContext`, and capability-scoped tools. SDK representation differs; character policy does not.

`host_protocol.py` 统一承载 `HostIngress`、类型化输入证据、`HostCapabilities`、有界过期 `TurnRegistry`、稳定 Host Key、`ProjectionMapper` 与 `UniversalHostBridge`。Hermes/AstrBot 只保留原生事件提取、SDK 钩子注册及请求级包装，复用相同 prepare → tool → observe → finalize、`UniversalGenerationContext` 和单轮工具权限；只改变 SDK 表示，不分叉角色策略。

The registry keeps at most 128 turns for 300 seconds, returns defensive copies and rejects superseded prepare completions. A prepare for the same key invalidates the old capability before awaiting Runtime. Session cleanup clears pending and active turns. Existing key bytes and legacy `TurnEnvelope` serialization are preserved; `HostCapabilities` remains importable from `lifecycle` for compatibility. Projection replacement is request-local and preserves other plugins' content. Missing/expired capabilities fail closed. The Runtime CLI remains process/transport startup; the Hermes CLI binding supplies its official native conversation ID.

注册表最多保留 128 个回合、有效期 300 秒，返回防修改副本并拒绝被新请求取代的旧 prepare 回调。同一键的新 prepare 在等待 Runtime 前使旧权限失效；清理会话同时清除待完成和活动回合。既有 Key 字节与旧 `TurnEnvelope` 序列化保持不变，`HostCapabilities` 仍可从 `lifecycle` 兼容导入。投影替换仅作用于当前请求，并保留其他插件内容；缺失/过期权限拒绝调用。Runtime CLI 仍只承担进程/传输入口；Hermes CLI 绑定另行提供官方原生会话 ID。

## Persistent sessions / 持久会话

`HostIngress.native_session_id` is a trusted Harness conversation identifier, not a Runtime session or a per-message ID. The old `session_id` ingress alias and `TurnEnvelope` wire field remain compatible. `ScopeResolver` verifies identity/endpoint first, then `SessionRegistry` maps Host + canonical endpoint + native conversation to a persistent canonical session. Full platform/audience provenance is checked on every lookup. A group shares its conversation/character across actors; each turn separately authorizes its actor, without private-memory access in group context. A DM mapping also records its verified participant.

`HostIngress.native_session_id` 来自可信宿主会话，不是 Runtime session 或消息 ID。旧入口别名和传输字段保持兼容。先验证身份及端点，再映射持久规范会话，并核对完整平台/受众来源。群聊共用会话与角色，每轮独立授权 Actor，群上下文不读取私人记忆；私聊额外记录已验证 Participant。

`host_prepare_turn` / `host_turn_open` return **session_id** and **turn_id** separately. The first continues across messages/restarts; the second authorizes only the current interaction. `ScopedToolRouter` removes session fields from request-local model schemas and injects the registered session into top-level or nested tool arguments. A conflicting ID is rejected; `open`, `set_default`, and `bind_project` require trusted administration. The legacy turn-ID alias remains accepted under the same capability, never as an independent credential. Switching character revokes that turn's old scope; the next trusted prepare resolves the new route.

两个入口分别返回持久 session ID 和单轮 turn ID。Bridge 在模型工具 Schema 副本中隐藏会话字段，执行时自动补齐顶层或 request 内参数；冲突 ID 明确拒绝。模型不能注册会话、设置默认或项目路由。旧 turn-ID 别名仍可使用，但必须携带当前权限。切换角色会使旧单轮作用域失效，下次可信 prepare 解析新角色。

Mappings live in the same SQLite (`host_session`, `conversation_session`, idempotent `host_session_operation` receipts). Legacy rows are enriched transactionally without changing their IDs, routes, mode or unknown fields. No physical schema rewrite or trust elevation occurs. The trusted `host_session_control` API can invalidate or rotate a canonical session; rotation archives the old row and resets session-only mode/route to the endpoint default. Private memory and bindings remain intact. Invalidated mappings never silently resurrect. `UniversalHostBridge.session_boundary` uses an active native callback handle, cancels pending callbacks in that bucket, and calls this same API. These collections are not portable Character Package contents.

映射和幂等操作收据使用同一 SQLite。旧记录在事务内补充来源，不修改原 ID、路由、模式或未知字段，不重写物理 Schema，也不提升信任。可信生命周期 API 可注销或轮换会话；轮换保留旧记录，临时模式/角色恢复端点默认，私人记忆与绑定不变。注销映射不能隐式复活。Bridge 通过活动原生回调句柄执行边界操作并清除该桶内待完成回调；这些 Host 数据不进入角色导出包。

### Native conversation sources / 原生会话来源

- **Hermes Gateway:** official hook `session_id`; Gateway endpoint and actor remain distinct. The same path handles QQ, Telegram and other supported Hermes transports.
- **Hermes CLI:** official hook `platform=cli`, stable `session_id` and per-run `turn_id`; configure plugin `cli_binding` with `actor_id`, `runtime_platform`, `endpoint_id` that already have trusted Runtime bindings. There is no nickname/Owner fallback. A missing native ID is rejected. A future Harness without IDs must create its native conversation handle once at conversation start, outside the model.
- **AstrBot:** `ProviderRequest.conversation.cid`, falling back only to explicitly supplied `ProviderRequest.session_id`; the route's endpoint ID alone cannot stand in for the conversation. Missing conversation identity rejects prepare. A reset to a new CID creates a fresh Runtime session.

Hermes Gateway 使用官方会话 ID，QQ/TG 不各写一套策略。CLI 使用官方稳定 session_id 和单轮 turn_id，插件 cli_binding 必须显式配置已绑定的 Actor、平台与端点，不猜测 Owner。AstrBot 优先使用 conversation.cid，仅允许明确 session_id 作为回退，不能以 Endpoint 冒充会话。缺少原生 ID 拒绝 prepare。未来无会话 ID 的宿主须在对话开始时生成一次原生句柄，不能由模型逐轮拼造。

Hermes `on_session_end` ends a run, not necessarily a conversation; shutdown/finalize may be resumable. These hooks clear transient capabilities only. Reset with a new native ID creates a new mapping; explicit `old_session_id` also clears old callbacks. Durable invalidation/rotation requires an explicit trusted conversation boundary. CLI pre-LLM text without matching raw capture is marked transformed: context/control work, but this hook alone does not attest exact user evidence. Both native bindings still report no reliable delivery ACK; generation is not delivery.

Hermes 的 on_session_end 是一轮运行结束，shutdown/finalize 也可能恢复，因此只清理临时权限；新原生 ID 产生新映射，reset 明确提供旧 ID 时同时清除旧回调。持久注销/轮换必须有明确可信会话边界。CLI pre-LLM 正文没有对应原始捕获时标记为 transformed，能加载上下文/控制会话，但不能据此认证用户原话。两个绑定仍无可靠投递 ACK，生成不冒充送达。

Sources checked for this contract: [Hermes lifecycle hooks](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/hooks.md), [Hermes middleware](https://github.com/NousResearch/hermes-agent/blob/main/hermes_cli/middleware.py), [AstrBot request fields](https://github.com/AstrBotDevs/AstrBot/blob/master/astrbot/core/provider/entities.py), [AstrBot tool schemas](https://github.com/AstrBotDevs/AstrBot/blob/master/astrbot/core/agent/tool.py). These are source-contract checks, not a claim that a locally installed Host or real QQ/TG transport was exercised.

上述为本轮核对的官方源码契约，不代表已运行真实宿主或 QQ/TG 平台验收。

### Future bindings / 后续绑定

MaiBot is a binding contract, not an installed SDK integration. A binding supplies authoritative `HostIngress`, reports actual `HostCapabilities`, invokes shared prepare/tool/observe/finalize, maps `UniversalGenerationContext` into a temporary native request, and reports only real send acknowledgements. It must propagate the same canonical session and per-turn capability, route tools through `ScopedToolRouter`, and call the trusted session boundary only when its native lifecycle confirms an end/reset. It owns no session policy, state DB, character logic or second model.

MaiBot 当前仅定义绑定契约，没有宣称 SDK 已实现。绑定提供可信入口、真实能力和生命周期事件，映射临时生成请求，使用统一作用域工具路由；只有原生生命周期确认结束/重置才应用持久会话边界。禁止独立会话策略、角色数据库、角色规则或第二模型。

## 工具

MCP 发现提供真实输入 Schema。工具返回 ok/result，业务失败 ok=false；还须检查协议 is_error。

| 工具 | 用途 |
|---|---|
| character_read / character_write | 角色摘要、定义、OOC 修改；没有 delete 操作 |
| session_control | 选角、OOC、临时模式、默认/项目路由；受限模式由 Bridge 自动注入规范 session ID，并携带 turn capability |
| endpoint_bind / endpoint_control | Owner 绑定外部端点；按 revision 软停用并保留审计 |
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

Hermes uses official lifecycle hooks plus `llm_request` middleware. `pre_llm_call` prepares the Runtime turn but returns no injected text; the full `model_context` is mapped into each copied provider request. This avoids official hook spill, which reduces context beyond 10,000 characters to a preview. Chat Completions system messages, Responses instructions and Anthropic system blocks serialize the same contract after Host policy and before user/tool data. Unsupported native formats are not certified. This source/API check is not installed-Host behavioral acceptance.

Hermes 使用官方生命周期钩子和 llm_request 中间件。pre_llm_call 只准备回合，不返回会被预览截断的长文字；每次模型请求复制后映射完整 model_context。三种原生参数格式共用同一语义，平台规则在前，角色契约先于用户/工具数据。未识别请求格式不在已验证支持范围；源码核对不等于真实宿主验收。

Request mapping was checked against Hermes source commit `26472756f1d8f65e714d6228f76b6816df87ea13`: [request metadata](https://github.com/NousResearch/hermes-agent/blob/26472756f1d8f65e714d6228f76b6816df87ea13/agent/turn_api_request.py), [hook spill](https://github.com/NousResearch/hermes-agent/blob/26472756f1d8f65e714d6228f76b6816df87ea13/tools/hook_output_spill.py). Mapping failure returns an empty replacement request: official middleware otherwise catches exceptions and reuses the original request, which could retain private context. The empty replacement makes generation fail without transmitting that stale payload. This source check does not certify an installed Hermes version or live model.

请求映射按上述固定提交核对。映射失败时返回空替代请求：官方中间件会捕获抛出的异常并继续使用原请求，可能带出旧私人上下文；空替代使生成失败，避免传出该旧载荷。本项源码核对不代表已验证本机 Hermes 版本或真实模型行为。

The native entry (`plugin.yaml`, `__init__.py`) registers one canonical Skill, passive pre-dispatch capture, turn preparation, request-local generation projection, post-LLM generation observation, session cleanup and existing-MCP tool middleware. Official hooks call the shared prepare/observe/finalize lifecycle automatically. It has no database, model or duplicate tool registry. Explicit actor/endpoint routes resolve through Runtime bindings; unknown actors, subagents and mismatched audience types fail closed. Only matching raw text is ingested after authorized Host dispatch; transformed text loads context without fabricating evidence. Missing source time remains unknown with a separate observation clock. The optional sender hook field is checked when present; task-local actor identity remains mandatory.

原生入口注册唯一 Skill、调度前被动捕获、单轮上下文、生成观察、会话清理与现有 MCP 工具中间件。官方钩子自动调用共享 prepare/observe/finalize 生命周期。身份依赖 Runtime 显式绑定；未知身份、子 Agent、受众类型不匹配时拒绝访问。调度前捕获不写库，仅在宿主正式进入模型阶段且原文匹配时提交用户事件；转录或改写正文不冒充原话。源时间缺失时保持未知并单独记录观察时间。可选 sender 字段存在时必须一致，逐轮 Actor 元数据始终必需。生成回调不读取隐藏推理或整段宿主历史，结束生成仍保持投递未知。会话重置不删除长期状态。

**Final delivery confirmation is unsupported.** This adapter does not orchestrate native bursts, typing, debounce generation, proactive sends or final receipts. Runtime delivery APIs retain authority/claim/unknown guarantees, but independent Hermes automatic sends are outside that state machine. Do not enable two automatic host responders for the same endpoint. Disabling the plugin leaves discovery-only MCP unable to execute tools; the owner may explicitly reconnect single-user MCP mode. Live dual-host acceptance remains pending.

**此 Adapter 不支持最终投递确认。** 不自动接管 Hermes 分段、输入状态、合并生成、主动发送或发送回执；Runtime 的完整发送协议继续保留，但 Hermes 自身自动回复尚未接入该状态机。同一 Endpoint 不可同时启用两个宿主自动回复。停用插件后发现凭据无法执行工具；Owner 可显式重新连接原有单用户 MCP 模式。真实双 Host 验收仍待完成。

AstrBot native entry uses official `on_llm_request` and `on_llm_response`, explicit platform-instance/endpoint routes and the same Runtime lifecycle. The same universal execution/identity/context/request serialization enters the request system message; AstrBot excludes that initial system message from saved history. It wraps existing MCP tools per request with a turn capability, without modifying global tool instances. `completion_text` is observed; hidden reasoning is ignored. SDK 1.x and 2.x share the same thin transport, with no dependency-major replacement, proxy inheritance or redirects.

AstrBot 原生入口使用官方请求/响应钩子、显式平台实例/Endpoint 路由及同一 Runtime 生命周期。请求系统消息消费相同的统一执行/身份/上下文/请求序列；AstrBot 不将该首条系统消息写入历史。已有 MCP 工具按请求包装单轮令牌，不修改全局工具实例。只观察 `completion_text`，忽略隐藏推理。轻量传输兼容宿主 SDK 1.x 和 2.x，不替换依赖主版本、不继承代理、不跟随重定向。

Reused AstrBot requests remove their own previous projection and unwrap old turn tools before routing, even when the next event is unrouted or rejected. Other plugins' appended text is preserved. If a Host has edited the injected block so it cannot be removed exactly, the request fails closed and must be rebuilt. No conversation history is deleted. Hermes uses official request middleware and replaces complete owned projection blocks on request reuse; neither bridge creates a second expression policy.

AstrBot 请求对象复用时，在路由前移除自身旧投影及旧工具包装，下一事件无路由或被拒绝也一样。其他插件追加的文字会保留。宿主若改写注入块导致无法精确移除，则拒绝该请求，须重新创建请求对象；不删除会话历史。Hermes 使用官方请求中间件，复用请求时替换自身完整投影块；两个 Bridge 都不创建第二套表达策略。

Native hooks supply raw task text, not parsed semantic format constraints. Both bridges therefore start with fresh default generation metadata; the current user's explicit instructions still govern output. Clients that declare GenerationRequest obtain runtime format/payload validation. Native text-only requests are not falsely reported as parsed JSON/code contracts. Synthetic checks verify lifecycle and projection integrity; live Host/model tests must separately verify actual voice and history-bias recovery. Official hook contracts rechecked on 2026-09-27: [Hermes turn hooks](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/hooks.md), [AstrBot AI integration](https://docs.astrbot.app/dev/star/guides/ai.html).

原生钩子提供任务原文，不提供解析后的语义格式约束，因此两个 Bridge 每轮从独立默认生成元数据开始；用户当前明确指令仍决定输出。主动声明 GenerationRequest 的客户端可获得 Runtime 格式和载荷校验。原生纯文本请求不会被谎称已解析成 JSON/代码契约。合成检查验证生命周期及投影完整性，实际语气和历史格式偏置恢复需另做真实 Host/模型验收。

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

旧写入保留工具名但拒绝无证据请求。先 event_ingest，再 turn_commit(proposal)。编辑前在 OOC 读取相应对象获得 allowlist。读取工具实时 Schema，不复用旧 candidates/turn_id 参数。平台转发必须提供稳定身份绑定；未知身份只可有限无状态回应。模型消费完整 model_context（generation_context 的确定性序列化），替换旧人物投影，不能累积多个角色前缀；stable_prefix + temporary 仅作兼容读取，不代替必需执行契约。增长、媒体、诊断及完整投递流程见 docs/reference.md、docs/companion.md。
