# Runtime 数据契约

规范来自 `character_runtime` 的 Pydantic 模型和 `schemas/`；额外字段、非有限数字及越界输入被拒绝。SQLite schema 为 5，角色包为 V3，接受旧 V1/V2 包。长期状态按 RuntimeOwner、CharacterInstance、Participant 或 Endpoint 分隔；Session 的角色路由与逐轮 Actor 分离。一个 session 同时只有一个活动人物。

## 权威与证据

RawEvent 保存可见输入、最终可见输出或必要观察；不接收隐藏推理。宿主提供稳定 source_id/source_event_id，数据库 UNIQUE 防重；checkpoint 只是游标。重复源 ID 的不同正文被拒绝。批次和提交都有 operation_id，相同请求返回原收据，不同请求复用 ID 报错。

Memory、Fact、State、Narrative 独立存储。提案只接受同 owner/character 的有效 RawEvent 证据；Narrative、旧 Memory 和导入证据不能充当新可信证据。媒体、引用、转发、计划与模拟不能直接建立 Fact。Fact 保留有效期，冲突槽需要 OOC、SUPERSEDE 和当前 allowlist；旧 Fact 留存 superseded 链。真实用户 Fact 还要求直接用户证据和保存确认。确定性核心要求 Fact value 是证据原文片段，不冒充自然语言蕴含判断器。

安全门拒绝可识别密码、密钥、Token、Cookie 与私钥。敏感内容需要明确存储授权；凭据不能靠授权绕过。模式检测不是完整的敏感信息识别器，宿主仍须正确标记 sensitivity，不应传入凭据。授权由可信宿主根据用户意图传递，OOC 和确认文本并不是独立的身份认证。

## Typed decisions / 类型化决策

`ExpressionPolicy.resolve` decides OOC, neutral/payload-only suppression and prose ownership in code. `ExpressionExecution` carries the resolved policy and validated effective voice. Legacy rendering hints cannot contradict its enabled/ownership fields; generated prose inside a technical deliverable remains character-owned unless explicitly suppressed. `rules.py` holds typed decisions and a minimal protocol; rendered text does not authorize lifecycle or persistence operations. Compiler version 6 invalidates old derived prefixes without changing canonical character data.

`ExpressionPolicy.resolve` 在代码中决定 OOC、中立/纯载荷抑制与表达归属。`ExpressionExecution` 携带解析后的策略与已验证声音；旧渲染提示不能与启用/归属字段矛盾。技术产物中的自拟自然语言默认仍归角色表达，除非显式抑制。`rules.py` 提供类型化决策及最小协议，渲染文本不授予生命周期或持久化权限。Compiler 版本 6 使旧派生前缀失效，不改变角色规范数据。

Retrieval authorizes owner, character, audience, validity and session in SQL before ranking. Lexical FTS/token ranks and optional `SemanticIndex` ranks use reciprocal rank fusion (RRF), without mixing raw scores. `RetrievalDecision` separates relevance, character utility (topic/goal/relationship/recency/importance), and confidence/provenance. `context_explain` exposes diagnostics without granting access. Explicit temporal/kind recall bounds also constrain topic/goal candidates. Similarity alone never merges negations or changed numbers.

检索先在 SQL 中检查 Owner、角色、受众、有效性与会话，再排序。FTS/词项及可选 `SemanticIndex` 的名次通过 RRF 融合，不直接混合原始分数。`RetrievalDecision` 分开记录相关性、角色效用（话题/目标/关系/近期性/重要度）与置信度/来源。`context_explain` 提供诊断但不授予权限；显式时间/类型范围同样约束话题/目标候选。语义相似本身不能合并否定或数字变化。

A trusted embedding host may inject `semantic_index` into `Runtime` or `build_server`; no vendor, vector service or second LLM is bundled or enabled by default. The provider must filter `namespace` and `allowed_ids` **before** ranking, avoid retaining query logs, and support erasure. SQL rechecks returned IDs. `memory.rebuild_semantic(character_id)` refreshes committed authorized data outside an existing transaction and holds the database lock during provider calls; use bounded local providers. Refresh explicitly after committed writes/imports: this version has no background index worker. A stale or absent index does not change canonical memory; lexical retrieval remains available.

可信嵌入宿主可向 `Runtime` 或 `build_server` 注入 `semantic_index`；默认不安装或启用任何向量服务、供应商或第二模型。后端必须在排序**之前**应用 `namespace` 与 `allowed_ids`、避免保留查询日志，并支持遗忘；返回 ID 仍由 SQL 复核。`memory.rebuild_semantic(character_id)` 在已有事务之外刷新已提交的授权数据，后端调用期间持有数据库锁，适合有界本地后端。写入/导入提交后须显式刷新，本版没有后台索引任务。索引缺失或过旧不改变规范记忆，词项检索仍可用。

`SafetyContext` (trusted purpose/provenance), optional `SensitivityClassifier`, and structural evidence produce `SensitivityAssessment` and `SafetyDecision`. Format/checksum evidence is not a claim that a value is genuine. Unknown-format private data can be assessed through context or the trusted classifier; without either, detection remains conservative and incomplete. Configure `safety_classifier` on `Runtime`/`build_server`; it applies to ingestion, corrections, proposals, generated observations, delivery and package validation. Classifier failures deny persistence with a redacted error. No model is called by the default implementation.

`SafetyContext`（可信用途/来源）、可选 `SensitivityClassifier` 与结构证据共同生成 `SensitivityAssessment` 和 `SafetyDecision`。格式/校验和证据不声称数值真实。未知格式的私人信息可由上下文或可信分类器识别；两者都缺失时，检测仍是保守且不完整的。通过 `Runtime`/`build_server` 配置 `safety_classifier`，覆盖摄入、更正、提案、生成观察、投递和角色包验证。分类器失败时使用脱敏错误拒绝持久化；默认实现不调用模型。

`StorageAuthorization` binds explicit approval to an operation and exact content hash; span approval cannot authorize surrounding text. Internal `check_content(..., confirmed=True)` callers must migrate to `authorization=StorageAuthorization.for_content(...)` **after** verifying user authority. Existing MCP confirmation fields remain inputs to the authenticated operation boundary, not reusable grants. Approval never overrides high authentication risk. Corrections preserve or raise sensitivity; an endpoint-public memory cannot be changed into sensitive private text. Failed writes roll back without consuming their target grant.

`StorageAuthorization` 将显式批准绑定到操作和精确正文摘要；局部片段批准不能授权周围正文。内部旧 `check_content(..., confirmed=True)` 调用须在验证用户权限**之后**改用 `authorization=StorageAuthorization.for_content(...)`。现有 MCP 确认字段继续在认证操作边界使用，不是可复用授权。批准不能覆盖高凭据风险。更正保留或提高敏感标签；Endpoint 公开记忆不能被更正为敏感私文。失败写入回滚，不消耗目标授权。

## 写入与恢复

先读取候选，再使用 Runtime 发出的短时 allowlist 修改。grant 绑定 owner、character、collection、session、目标快照、操作与过期时间，成功后单次消费。事务失败不消耗授权；成功后的原 operation_id 重试返回收据。MutationLog 保存操作元数据和前后摘要，不复制私人正文。

Durable Job 使用 pending/running/retry/failed/quarantined/committed。租约过期的安全本地任务可有限重试，结果未知的外部操作隔离。SQLite 使用 WAL、busy_timeout、嵌套事务、外键和私有文件权限；网络发送不能放进数据库事务冒充原子提交。

## 记忆与上下文

importance、confidence、durability、activation 分开。普通低价值提案留在 RAW_ONLY；显式记住需直接用户证据，长期保留。短期 TTL、过期、归档和忘记各有含义；自动维护不会因长期未召回而删除显式记忆。检索不增加 confidence/durability。中文有本地 bigram 与词项索引，FTS5 缺失时使用本地索引；不要求向量服务。

时间召回由宿主发送 RecallRequest 的 intent、起止时间或 today/yesterday/last_week 与时区，按原事件时间过滤。关键词不承担主要意图识别。EXACT_QUOTE / EXACT_RECALL 直接读取可见 RawEvent 原文（包含尚未提炼为 Memory 的记录）；推断、旧记忆和模拟必须保留标签。项目知识独立于人物 Memory，不进入人格编译。

ContextAssembler 是唯一投影与预算权威。稳定前缀由人物 revision、growth version、compiler version 决定，不含当前时间、天气、关系、召回结果或用户名。同版本内容字节稳定；编译失败保留同角色 Last Known Good。临时状态按 slot 预算收纳完整片段，超限省略并报告，不机械截断用户答复。context_explain 只返回统计、版本与摘要。

The platform-neutral `UniversalGenerationContext` separates identity, required expression execution, authorized fragments, and the current GenerationRequest. `ExpressionExecution` is derived per turn; it has no storage collection or write API. Its effective voice includes approved growth and authorized participant adaptation. The deterministic directive owns all model-authored natural language and discourse organization while respecting local exactness exceptions. Required execution is reserved before optional fragments; budget failure is explicit. Legacy `stable_prefix`/`temporary` are compatibility views and must not be injected beside `model_context`.

UniversalGenerationContext 分离身份、必需执行契约、授权片段与本轮任务。ExpressionExecution 仅为单轮派生，不新增存储域或写接口；有效声音包含已批准成长及经过作用域检查的私人适应。结构与短指令由同一契约产生，涵盖自然语言正文和组织方式，精确性只局部优先。必需执行先占预算，超限明确失败；旧字段不能和 model_context 重复注入。

Endpoint lifecycle is Owner-only: deactivate compares the expected revision, writes an idempotent receipt with the previous record, marks inactive and preserves audit/delivery history. New ingress and old turn capabilities fail closed. OOC belongs to the Runtime conversation across Host turns; external Host session strings and Runtime turn IDs are different identifiers.

Endpoint 停用仅限 Owner，检查预期 revision、保存幂等回执与原记录、标记 inactive；历史及投递状态不删除。新入口和旧回合均拒绝。OOC 在同一 Runtime 会话跨轮保持；外部 Host session 字符串和 Runtime turn_id 不可互换。

## 关系、成长与表达

Relationship Engine 保存 anchor、learned、override、closeness、friction 和互动时间。缺席只改变临时 warmth，不降低 trust。自动关系变化需要跨三天的独立用户证据、相邻级别变化和冷却，显式 override 阻止自动覆盖。

成长保存 candidate/version/overlay；从不覆写基线。低影响声音变化需要至少三天直接证据；其他变化先进入待审。高影响变化必须 OOC 批准。growth_control 提供 history/preview/approve/reject/rollback，回滚产生新版本并冷却七天，保留原证据。一次“说短一点”和助手历史不能永久训练人物声音。

VoiceProfile 是结构化人物表达权威。宿主通过 GenerationRequest 指定任务类型、格式和长度要求；ExpressionPolicy 将内容约束与角色表达并行处理；专业任务不会自动中性化，人物表达不得损坏事实与精确载荷。自然中文、少套话和按性格偶尔使用语气词是生成指导，不是硬字数截断器。

## 身份、陪伴与媒体

可信本地 owner 由进程配置确定；HTTP owner 来自验证后的认证主体。平台消息必须以稳定 host/platform/actor ID 显式绑定；未绑定 session 无私人记忆读写权。不能按昵称合并身份。宿主必须将陌生平台消息放入带平台身份的 session，不能冒用可信本地 owner 路径。

Affect、Attention、可选 Embodiment 与日常 Life 分开。生活模拟仅白名单日常，禁造现实经历和重大人生事件。Provider 观察含来源、时间、过期和置信度，不保存 provider 凭据。视觉自动匹配是 candidate；SELF 识别必须指向已明确确认的 prototype，媒体始终是 MEDIA，不建立现实到访事实。确认图像不会访问其他角色私人状态。

主动联系默认关闭。decide → prepare → delivery → ack，每个阶段只发放一次生成/发送许可；发送前重新检查关闭、安静时段、最近活动、失效话题、过期。结果未知用 delivered=null，不能盲目重发。Core 只给 interaction intent，由授权宿主负责实际平台发送。统一 maintenance 由宿主调度调用，不要求后台第二模型。

## 迁移、导出与遗忘

V1 数据库首次升级前生成 0600 的 SQLite 完整备份；迁移事务失败回滚。原始 Memory/State 保存在私有 migration_original，无法映射的字段记录告警；畸形旧行原样保留但不进入检索。shared_world_id、known_characters、shared_with、recipients 的跨角色权限被撤销。旧记忆仅原角色可读，明确 legacy_unverified，不自动成为 Fact 或成长证据。

V3 默认包不含 Memory、原始事件、真实用户资料、provider 位置、身份绑定、投递记录或授权。include_memories、include_companion 与 include_private_knowledge 分别控制私人范围；完整迁移需审阅实际包。定义及关系自身也可能含私人文字，“不含 Memory”不等于匿名。

导入事务创建新人物并重映射记录 ID；原包保持不变。旧包及导入证据不获得本地信任；导入 Fact/Narrative/Project Memory 归档。显式导入的当前成长作为手动人物配置保存，历史证据只归档，不能用于自动成长。视觉 prototype 重新成为待确认候选，主动联系等授权清空。

忘记会清除活跃库中的正文和依赖证据的派生内容，并使关联成长投影失效。已导出的文件、私有迁移备份、宿主历史和介质历史页需分别管理；不能声称物理不可恢复。数据库不做应用层加密，部署应使用私有账户、磁盘权限和受控备份。

P3 的向量/embedding、外部 Memory backend、视觉向量库和管理 UI 都是可选扩展，未作为当前依赖。

## Scoped host ingress / 宿主权限入口

RuntimeOwner manages the namespace; Participant identifies a verified human. IdentityBinding maps an actor, PlatformBinding selects the endpoint, CharacterRoute authorizes the instance, and DeliveryBinding grants one host permission to send. Shared instances share definition and approved Growth, never personal context. Private instances use distinct character IDs in the same Runtime engine and SQLite.

RuntimeOwner 管理命名空间；Participant 标识显式验证过的真人。IdentityBinding 确定“谁”，PlatformBinding 确定“哪里”，CharacterRoute 确定角色实例，DeliveryBinding 确定唯一发送者。共享实例只共享定义与已批准成长；私人实例使用不同角色 ID，仍共用同一引擎与 SQLite。

A trusted owner/host bridge configures `identity_control`, `endpoint_bind`, `character_route_bind` and `delivery_bind`. It opens an interaction with `host_turn_open` and a stable `request_id`. Retry reuses the turn and rechecks revocation. Authenticated HTTP ingress returns a short-lived capability for the model's existing MCP tools. The owner credential must remain in trusted host code. A scoped capability cannot ingest evidence, manage bindings, authorize global Growth, or acknowledge delivery; it expires after one hour and after server restart.

可信管理/宿主入口配置身份、地点、路由与投递绑定，再用稳定 request_id 打开 Turn；重试复用原 Turn 并复查撤销。HTTP 入口为模型现有 MCP 工具签发短期能力令牌，Owner 凭据必须留在可信宿主代码中。单轮令牌不能伪造证据、管理绑定、授权全局成长或确认发送，一小时后或服务重启后失效。

Group storage denies every Participant-private collection before reading, including the current actor's state, Relationship, Adaptation and Relational Affect. Operation audit snapshots respect the same boundary. Only endpoint public context and character public life can enter group generation. Personal preferences change the temporary projection, never the stable prefix or global Growth. Conversation task/OOC modes survive subsequent turns without pinning the conversation to a human.

群聊在存储读取前拒绝所有 Participant 私有数据，包括当前 Actor 的状态、关系、适应和关系情绪；操作审计快照也遵守该边界。群聊生成只使用 Endpoint 公开上下文与角色公共生活。个人偏好只改变临时投影，不改变稳定前缀或全局成长；会话任务/OOC 模式跨轮次保留，但不把会话绑定到某个人。

Schema 3 migration privately backs up the database, preserves legacy mixed state and unknown fields byte-for-byte, and initializes separate public life with safe defaults. A failure rolls back all migration writes. There is no automatic private-to-public promotion. `host_companion_configure` is owner-only; group OOC cannot enable endpoint proactive policy. Scoped proactive send and ACK update the existing proactive engine and the endpoint delivery ledger in one transaction. Unknown results block authority handover and resend.

Schema 3 迁移先生成私有备份，原样保留旧混合状态及未知字段，再以安全默认值初始化公共生活；失败完整回滚，不自动把私人内容公开。host_companion_configure 仅供 Owner 使用，群聊 OOC 不授予 Endpoint 主动联系配置权。带 Turn 的主动发送与 ACK 在同一事务中更新既有主动引擎和 Endpoint 投递账本；未知结果禁止切换 Host 或重发。

## MemoryUsePolicy / 逐条记忆使用决策

Scope authorization precedes every candidate lane and ranking. Each allowed Memory then receives an ephemeral `MemoryUseDecision` with ALLOW/DENY, policy, reasons, evaluation time and policy version. DENY is not INTERNAL_ONLY. Diagnostics expose decisions for authorized candidates, never another participant's private bodies or record inventory.

Scope 授权先于每个候选通道及排序。每条已授权记忆再得到临时 MemoryUseDecision，包含访问结果、使用策略、原因、时间与版本。DENY 不等于 INTERNAL_ONLY；诊断不枚举其他 Participant 的私人记录。

DIRECT permits evidence-backed background use, not absolute truth or verbatim quotation. Inferred/model-derived content is UNCERTAIN. Relationship cues and simulations may produce TONE_ONLY social guidance without event bodies. Expired, forgotten, superseded and normally recalled legacy records remain INTERNAL_ONLY. Explicit historical recall may expose authorized legacy records as UNCERTAIN. Unrelated sensitive memory is excluded. OOC maintenance can inspect authorized originals without turning them into generation evidence.

DIRECT 允许使用有证据的背景，但不等于绝对真实或原话；推断与模型派生内容标为 UNCERTAIN。关系线索与模拟可生成 TONE_ONLY 社交约束，不输出事件正文。过期、遗忘、被替代及普通召回中的旧未验证记录为 INTERNAL_ONLY；显式历史回忆可将已授权旧记录标为 UNCERTAIN。无关敏感记忆不进入生成；OOC 维护可审阅已授权原始记录，但不把它们升级成生成证据。

The decision is not written back to Memory. Exact recall reads RawEvent independently of summaries and preserves source/legacy labels. A DIRECT paraphrase cannot become a claimed user quote.

决策不写回 Memory；精确回忆独立读取 RawEvent 并保留来源与旧记录标签。即使摘要为 DIRECT，也不能冒充用户原话。

## Character continuity / 任务人格连续性

`soft_roleplay` retains full character identity with task-appropriate restraint. All task intents use the same VoiceProfile; vocabulary, rhythm, explanations, analogies, evaluation, questions and disagreement styles are compiled into the stable prefix. Curated dialogue examples accept both legacy strings and meaning/character pairs. They are never learned from assistant history automatically. Core humor changes now require explicit Growth approval.

soft_roleplay 保留完整角色身份，按任务收敛表演；所有任务共用 VoiceProfile。词汇、节奏、解释、比喻、评价、追问和分歧风格进入稳定前缀。示范兼容旧字符串及 meaning/character 对照，但不会自动从助手历史学习；核心幽默风格变化须显式批准成长。

GenerationRequest separates `explicit_format` from `payload_only`. Code/JSON inside an answer permits character prose around it. Only an explicit payload-only request suppresses wrappers; `neutral_expression` and session OOC/task_neutral suppress voice without deleting the character. Catchphrase rules are optional suggestions with usage/intensity/avoid-contexts and a cooldown measured from authorized visible/generated observations; generation is never delivery evidence.

GenerationRequest 将格式与 payload_only 分开；回答包含代码/JSON 时仍可有人物解释，明确要求纯载荷才禁止包装文字。neutral_expression 和 OOC/task_neutral 关闭表达，不删除角色。口头禅有场景、强度、避用条件与冷却，根据已授权受众中的可见或生成观察计算，绝不强制使用；生成观察不是投递证据。

ProtectedPayload marks exact code, JSON, commands, URLs, quotes, numeric data and tool output. The local validator rejects changes to declared payloads and invalid raw JSON without a repair LLM. It does not prove newly generated code or factual claims correct. Compiler version 5 keeps the full-prose continuity contract separate from old cached prefixes. Context assembly includes declared literal values and fails explicitly if it cannot retain the required expression contract.

ProtectedPayload 标记精确代码、JSON、命令、URL、引用、数字和工具输出。本地校验拒绝已声明载荷被改写及无效纯 JSON，不调用润色模型；它不保证新生成代码或事实结论正确。编译器版本 5 为全文角色表达建立新的缓存版本；上下文包含声明的精确值，必要表达约束装不进预算时明确失败，不静默丢弃。

Character voice owns the entire free-language answer: technical explanations, assessments, recommendations, transitions, tool commentary and failure reactions. Exact spans are local exceptions. Protect facts, not the way facts are spoken. Numbers are protected as facts, not as sentences. Tool execution does not suspend identity; raw tool results stay raw. Anti-template guidance varies phrasing without flattening the character or forcing catchphrases.

角色表达覆盖完整自然语言正文：技术解释、判断、建议、转场、工具解读及失败反应。精确片段只是局部例外，数字作为事实受到保护，不意味着整句必须中性化。工具执行不会暂停角色身份，原始结果仍保持原样。去模板化要求变化表达方式，不抹平人格，也不强加口头禅。

A prepared lifecycle turn retains its GenerationRequest across context/tool/diagnostic reads and restarts; conflicting replacements are rejected. A different turn starts with a fresh request. Temporary neutral/OOC-style output uses `neutral_expression`; an explicitly entered persistent session OOC/task mode still requires its existing exit/end action. No text-style heuristic activates a character. `context_explain` reports resolved activation, character ID, definition/state presence, effective mode, expression enabled and generation flags. Protected values appear only in authorized generation context; diagnostics show their types and lengths, not their bodies.

已准备回合的 GenerationRequest 在重读上下文、工具调用、诊断及重启后保持一致，冲突替换会被拒绝；不同回合重新建立请求。临时 neutral/OOC 式输出使用 neutral_expression；显式进入的持久会话 OOC/task 模式仍按原有 exit/end 操作结束。不能根据文本风格激活角色。context_explain 报告解析后的激活状态、角色 ID、定义/状态是否存在、有效模式、表达开关及生成标记。精确值仅进入授权生成上下文，诊断只报告类型和长度。
