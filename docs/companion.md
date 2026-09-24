# 陪伴与主动联系

功能按人物存储；主动联系、天气/日程感知和生活模拟默认关闭。用户授权后，在 OOC 调用 companion_control 读取 state/allowlist，再以 operation_id、allowlist_id 和 update 更新。对普通回合的目标、习惯或话题提案使用 turn_commit.proposal.companion_update；自动修改已有条目需要当前 companion allowlist，情绪变化走 affect_effects，设置不能由聊天提案修改。

Current emotion comes only from scoped `AffectState`. `AffectEffect` is an evidence-gated mutation input applied by the existing reducer, not another state source. Legacy `CompanionState.mood` is opaque read-only history: no decay, current context projection, decisions or label-to-vector conversion. Compatibility reads mark it read-only; writes return `LEGACY_MOOD_WRITE_UNSUPPORTED`, `read_only=true`, `replacement=AffectEffect`.

当前情绪仅来自相应作用域的 `AffectState`。`AffectEffect` 只是经证据验证后交给既有 reducer 的变化输入，不是另一份状态。旧 Mood 完整保留为只读档案，不衰减、不进入当前上下文或决策、不转换数值；写入返回稳定兼容错误。私有导入导出保留档案和未知字段，导入不激活旧 Mood。Schema 5 升级先备份并保留原始 JSON，失败事务回滚。用户显式遗忘仍会清除相关受众的历史正文，这是隐私清除而非情绪更新；私有恢复备份应由用户自行保管和清理。

Affect 根据有来源的事件接受有界变化并随时间回归。Attention 分开表达 care、focus、capacity。Embodiment 在人物定义中单独启用，不假定人物必须是人；未启用时不会制造饥饿、睡眠需求。Life 只模拟低风险日常，以 started_at/expected_end/next_decision_after 保存滚动状态；没有第二个模型，也不会伪造用户共同经历。

宿主的定时器可在 OOC 管理 session 调用 runtime_doctor(maintenance_operation_id=稳定ID) 运行一次持久维护，再调用 proactive_decide。维护处理过期、相同证据的重复归档、派生 daily reflection 和状态推进。由宿主安排周期，不会启动新的必需服务或自行发送消息。

主动发送流程：

1. proactive_decide(character_id) 返回 reservation；should_contact=false 时保持安静。
2. proactive_prepare(session_id, decision_id) 原子领取一次生成机会，返回当前人物的统一 context 和 claim_id。
3. 宿主当前模型生成回复。
4. 发送前立即 proactive_delivery(character_id, decision_id, claim_id)。只有 should_contact=true 才能执行一次实际发送。
5. proactive_ack 使用同一 decision_id/claim_id，delivered=true 为确认成功，false 为确定未发送，null 为结果未知。

重复 scheduler、重连和重启不能获得第二次生成或发送许可。结果未知会保留隔离状态，宿主查证结果后再确认，不自动重发。平台支持时同时使用 decision_id 作为平台投递幂等键。关闭开关、安静时段、用户刚发消息、目标/话题变化和过期均在发送前重查。Core 无法撤回已经交给网络的消息。

InteractionRequest 表达 TEXT/REPLY/REACTION/STICKER/IMAGE_OR_MEME/POKE_OR_LIGHT_PING/TYPING/READ_RECEIPT/SILENCE 与用途；平台不支持时退回 TEXT 或 SILENCE。它不提供平台端点、不授予发送权限。Perception 和视觉原型见数据契约；角色图像只描述媒体，不建立现实经历。

Proactive decisions expose `motive`, `opportunity` and `basis` from existing opted-in goals/topics and current availability. Topic ranking uses a bounded recency preference after the existing cooldown gates. These are explanations of configured intent, not evidence that an event happened; no second motivation store or model is involved.

主动决策根据已开启的目标／话题和当前可用状态返回动机、机会及依据。话题先通过既有冷却门，再使用有界近期使用权重排序。这些字段解释已配置的意图，不证明事件发生，不新增动机数据库或模型。普通记忆更正只使派生状态失效，不清空旧 Mood 档案；显式遗忘的隐私清除规则保持不变。
