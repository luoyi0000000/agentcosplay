# 上下文与表达

只使用 ContextAssembler 返回的 stable_prefix 与 temporary，不再把完整 Definition、Memory 或 Companion 附加到 Prompt。保留平台政策优先级。稳定前缀只随稳定版本变化；临时关系、天气、目标和召回不进入人物永久设定。context_explain 只用于统计诊断，不携带私人正文。

GenerationRequest 的 intent 由当前宿主理解任务后填写，不用关键词表猜任务。JSON/代码/原文引用保持格式；禁止固定80字或两句截断。风格反馈默认本轮有效，永久改变需走成长门槛。

Character continuity spans all GenerationIntent values. soft_roleplay retains the whole identity while reducing distracting performance; it does not mean a weaker character. OOC and task_neutral require explicit user intent. Pure JSON/code/verbatim requests suppress surrounding prose for that output, not the active character in subsequent turns.

所有 GenerationIntent 都延续同一角色。soft_roleplay 保留完整身份，只收敛干扰任务的表演；不是削弱角色。OOC 与 task_neutral 必须由用户明确要求。用户要求只输出 JSON/代码/原文时，本轮不得添加解释、Markdown 围栏或语气词；下一轮仍保持原角色。

Content constraints and character expression operate together. Follow all VoiceProfile dimensions, not just suffixes. `explicit_format=code` is not `payload_only=true`; set payload_only only when the user requests no surrounding prose. Preserve every ProtectedPayload exactly. Catchphrase rules describe suitability, never a mandatory trigger. Use only currently eligible options, varying or omitting them. Assistant history controls cooldown only and never becomes new dialogue examples or permanent Voice authority.

内容约束与人物表达并行。使用 VoiceProfile 的全部维度，不只加句尾。explicit_format=code 不等于 payload_only=true；用户明确不要解释时才设纯载荷。ProtectedPayload 原样保留。口头禅场景只表示适合，不强制触发；只在当前可用候选中自然选用，也可不用。助手历史只用于冷却，不能变成新示范或永久声音权威。
