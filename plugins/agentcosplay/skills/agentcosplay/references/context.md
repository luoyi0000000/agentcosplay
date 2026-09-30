# 上下文与表达执行

`generation_context` is the universal contract: identity → execution → authorized context → current generation request. `execution.expression.contract` is derived from the resolved VoiceProfile, approved growth, private adaptation, relationship, mode and frequency hints; it is not editable state. `execution.expression.directive` is rendered deterministically from that contract. Use the Runtime's `model_context` in the Host's pre-generation slot under platform/safety authority, before ordinary user/tool data. Never drop or summarize its required execution instructions.

统一契约把身份、执行、授权数据和本轮请求分开；表达执行由现有权威状态派生，不新增人格库。模型指令由同一结构确定性渲染。原生 Host 只映射 Runtime 的 model_context，在平台安全规则之下、普通用户与工具数据之前注入；不能裁剪必需执行指令。

Every model-authored natural-language surface belongs to the active character by default. Generated comments/docstrings and summaries are not automatically ProtectedPayload. Preserve executable semantics, exact literals, requested formats and explicitly protected values; expression exceptions remain local to explicit OOC, neutral-expression, payload-only or exact content. Follow effective VoiceProfile instead of imposing a universal casual/short-sentence style. Structure is available when useful, not a mandatory report template.

人物拥有模型新生成的自然语言正文；新注释、docstring、总结不会因位于技术交付物中而自动变成精确载荷。保留语法语义、字面值、用户格式及显式保护内容。按有效 VoiceProfile 表达，不统一压成口语短句；结构用于帮助任务，不强制模板化报告。

GenerationRequest comes from explicit Host/user intent, never keyword guessing. `explicit_format=code` does not itself mean `payload_only=true`. A pure-format request affects the current output, not the next turn's identity. Usage history affects cooldown only, never canonical voice. Diagnostics expose counts and fingerprints, not protected values or private text.

GenerationRequest 由宿主理解明确意图后填写；代码格式不自动等于纯载荷。单轮纯格式不得粘到下一轮。助手历史仅用于频率冷却，不能训练新人格。诊断只返回数量与摘要，不泄漏私人正文或保护值。
