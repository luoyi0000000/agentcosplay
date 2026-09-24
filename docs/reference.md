# Runtime 数据契约

规范来自 `character_runtime` 的 Pydantic 模型和 `schemas/`；额外字段、非有限数字及越界输入被拒绝。SQLite schema 为 3，角色包为 V3，接受旧 V1/V2 包。长期状态按 RuntimeOwner、CharacterInstance、Participant 或 Endpoint 分隔；Session 的角色路由与逐轮 Actor 分离。一个 session 同时只有一个活动人物。

## 权威与证据

RawEvent 保存可见输入、最终可见输出或必要观察；不接收隐藏推理。宿主提供稳定 source_id/source_event_id，数据库 UNIQUE 防重；checkpoint 只是游标。重复源 ID 的不同正文被拒绝。批次和提交都有 operation_id，相同请求返回原收据，不同请求复用 ID 报错。

Memory、Fact、State、Narrative 独立存储。提案只接受同 owner/character 的有效 RawEvent 证据；Narrative、旧 Memory 和导入证据不能充当新可信证据。媒体、引用、转发、计划与模拟不能直接建立 Fact。Fact 保留有效期，冲突槽需要 OOC、SUPERSEDE 和当前 allowlist；旧 Fact 留存 superseded 链。真实用户 Fact 还要求直接用户证据和保存确认。确定性核心要求 Fact value 是证据原文片段，不冒充自然语言蕴含判断器。

安全门拒绝可识别密码、密钥、Token、Cookie 与私钥。敏感内容需要明确存储授权；凭据不能靠授权绕过。模式检测不是完整的敏感信息识别器，宿主仍须正确标记 sensitivity，不应传入凭据。授权由可信宿主根据用户意图传递，OOC 和确认文本并不是独立的身份认证。

## 写入与恢复

先读取候选，再使用 Runtime 发出的短时 allowlist 修改。grant 绑定 owner、character、collection、session、目标快照、操作与过期时间，成功后单次消费。事务失败不消耗授权；成功后的原 operation_id 重试返回收据。MutationLog 保存操作元数据和前后摘要，不复制私人正文。

Durable Job 使用 pending/running/retry/failed/quarantined/committed。租约过期的安全本地任务可有限重试，结果未知的外部操作隔离。SQLite 使用 WAL、busy_timeout、嵌套事务、外键和私有文件权限；网络发送不能放进数据库事务冒充原子提交。

## 记忆与上下文

importance、confidence、durability、activation 分开。普通低价值提案留在 RAW_ONLY；显式记住需直接用户证据，长期保留。短期 TTL、过期、归档和忘记各有含义；自动维护不会因长期未召回而删除显式记忆。检索不增加 confidence/durability。中文有本地 bigram 与词项索引，FTS5 缺失时使用本地索引；不要求向量服务。

时间召回由宿主发送 RecallRequest 的 intent、起止时间或 today/yesterday/last_week 与时区，按原事件时间过滤。关键词不承担主要意图识别。EXACT_QUOTE / EXACT_RECALL 直接读取可见 RawEvent 原文（包含尚未提炼为 Memory 的记录）；推断、旧记忆和模拟必须保留标签。项目知识独立于人物 Memory，不进入人格编译。

ContextAssembler 是唯一投影与预算权威。稳定前缀由人物 revision、growth version、compiler version 决定，不含当前时间、天气、关系、召回结果或用户名。同版本内容字节稳定；编译失败保留同角色 Last Known Good。临时状态按 slot 预算收纳完整片段，超限省略并报告，不机械截断用户答复。context_explain 只返回统计、版本与摘要。

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

GenerationRequest separates `explicit_format` from `payload_only`. Code/JSON inside an answer permits character prose around it. Only an explicit payload-only request suppresses wrappers; `neutral_expression` and session OOC/task_neutral suppress voice without deleting the character. Catchphrase rules are optional suggestions with usage/intensity/avoid-contexts and a cooldown measured from delivered ASSISTANT_VISIBLE history in the authorized audience.

GenerationRequest 将格式与 payload_only 分开；回答包含代码/JSON 时仍可有人物解释，明确要求纯载荷才禁止包装文字。neutral_expression 和 OOC/task_neutral 关闭表达，不删除角色。口头禅有场景、强度、避用条件与冷却，冷却仅根据已授权受众中实际可见的助手历史计算，绝不强制使用。

ProtectedPayload marks exact code, JSON, commands, URLs, quotes, numeric data and tool output. The local validator rejects changes to declared payloads and invalid raw JSON without a repair LLM. It does not prove newly generated code or factual claims correct. Compiler version 4 keeps the new semantics separate from old cached prefixes. Context assembly fails explicitly if it cannot retain the required expression contract.

ProtectedPayload 标记精确代码、JSON、命令、URL、引用、数字和工具输出。本地校验拒绝已声明载荷被改写及无效纯 JSON，不调用润色模型；它不保证新生成代码或事实结论正确。编译器版本 4 避免复用旧语义缓存；必要表达约束装不进预算时明确失败，不静默丢弃。
