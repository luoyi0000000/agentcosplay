# 上下文与表达

只使用 ContextAssembler 返回的 stable_prefix 与 temporary，不再把完整 Definition、Memory 或 Companion 附加到 Prompt。保留平台政策优先级。稳定前缀只随稳定版本变化；临时关系、天气、目标和召回不进入人物永久设定。context_explain 只用于统计诊断，不携带私人正文。

GenerationRequest 的 intent 由当前宿主理解任务后填写，不用关键词表猜任务。JSON/代码/原文引用保持格式；禁止固定80字或两句截断。风格反馈默认本轮有效，永久改变需走成长门槛。
