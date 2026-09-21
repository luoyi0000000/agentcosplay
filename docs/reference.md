# Runtime 数据契约

规范来自 `character_runtime` 的 Pydantic 模型和 `schemas/`；额外字段、非有限数字及越界输入被拒绝。SQLite schema 为 2，角色包为 V3，接受旧 V1/V2 包。数据的长期命名空间为认证 owner + character，session/host/platform 只是绑定与传输。一个 session 同时只有一个活动人物。

## 权威与证据

RawEvent 保存可见输入、最终可见输出或必要观察；不接收隐藏推理。宿主提供稳定 source_id/source_event_id，数据库 UNIQUE 防重；checkpoint 只是游标。重复源 ID 的不同正文被拒绝。批次和提交都有 operation_id，相同请求返回原收据，不同请求复用 ID 报错。

Memory、Fact、State、Narrative 独立存储。提案只接受同 owner/character 的有效 RawEvent 证据；Narrative、旧 Memory 和导入证据不能充当新可信证据。媒体、引用、转发、计划与模拟不能直接建立 Fact。Fact 保留有效期，冲突槽需要 OOC、SUPERSEDE 和当前 allowlist；旧 Fact 留存 superseded 链。真实用户 Fact 还要求直接用户证据和保存确认。确定性核心要求 Fact value 是证据原文片段，不冒充自然语言蕴含判断器。

安全门拒绝可识别密码、密钥、Token、Cookie 与私钥。敏感内容需要明确存储授权；凭据不能靠授权绕过。模式检测不是完整的敏感信息识别器，宿主仍须正确标记 sensitivity，不应传入凭据。授权由可信宿主根据用户意图传递，OOC 和确认文本并不是独立的身份认证。

## 写入与恢复

先读取候选，再使用 Runtime 发出的短时 allowlist 修改。grant 绑定 owner、character、collection、session、目标快照、操作与过期时间，成功后单次消费。事务失败不消耗授权；成功后的原 operation_id 重试返回收据。MutationLog 保存操作元数据和前后摘要，不复制私人正文。

Durable Job 使用 pending/running/retry/failed/quarantined/committed。租约过期的安全本地任务可有限重试，结果未知的外部操作隔离。SQLite 使用 WAL、busy_timeout、嵌套事务、外键和私有文件权限；网络发送不能放进数据库事务冒充原子提交。

## 记忆与上下文

importance、confidence、durability、activation 分开。普通低价值提案留在 RAW_ONLY；显式记住需直接用户证据，长期保留。短期 TTL、过期、归档和忘记各有含义；自动维护不会因长期未召回而删除显式记忆。检索不增加 confidence/durability。中文有本地 bigram 与词项索引，FTS5 缺失时使用本地索引；不要求向量服务。

时间召回由宿主发送 RecallRequest 的 intent、起止时间或 today/yesterday/last_week 与时区，按原事件时间过滤。关键词不承担主要意图识别。EXACT_QUOTE 只返回原始证据正文；推断、旧记忆和模拟必须保留标签。项目知识独立于人物 Memory，不进入人格编译。

ContextAssembler 是唯一投影与预算权威。稳定前缀由人物 revision、growth version、compiler version 决定，不含当前时间、天气、关系、召回结果或用户名。同版本内容字节稳定；编译失败保留同角色 Last Known Good。临时状态按 slot 预算收纳完整片段，超限省略并报告，不机械截断用户答复。context_explain 只返回统计、版本与摘要。

## 关系、成长与表达

Relationship Engine 保存 anchor、learned、override、closeness、friction 和互动时间。缺席只改变临时 warmth，不降低 trust。自动关系变化需要跨三天的独立用户证据、相邻级别变化和冷却，显式 override 阻止自动覆盖。

成长保存 candidate/version/overlay；从不覆写基线。低影响声音变化需要至少三天直接证据；其他变化先进入待审。高影响变化必须 OOC 批准。growth_control 提供 history/preview/approve/reject/rollback，回滚产生新版本并冷却七天，保留原证据。一次“说短一点”和助手历史不能永久训练人物声音。

VoiceProfile 是结构化人物表达权威。宿主通过 GenerationRequest 指定任务类型、格式和长度要求；ExpressionPolicy 优先满足正确性、用户要求、任务和平台约束，再应用声音与关系。自然中文、少套话和按性格偶尔使用语气词是生成指导，不是硬字数截断器。

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
