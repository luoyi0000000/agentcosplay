# Runtime 连接与恢复

Discover current tool schemas first. In native Host sessions, the Bridge registers/reuses the canonical session and injects session arguments plus the current turn capability. Request context or OOC without inventing IDs. If a direct trusted tool schema still requires an ID, use only the canonical `session_id` explicitly supplied by that Host; the old turn-ID alias is compatibility only. Never use an external conversation ID or invent suffixes. Missing mapping requires trusted Host repair, not model-created `session_control(action="open")`.

先发现当前工具 Schema。原生宿主由 Bridge 注册/复用规范会话，自动补齐 session 参数和单轮权限。请求上下文或 OOC 时不要编造 ID；直接可信工具若仍要求 ID，只能使用 Host 明确提供的规范 session_id，旧 turn-ID 只是兼容别名。不能填外部会话 ID 或拼接后缀。映射缺失交由可信宿主修复，模型不得自行 open 会话。

For scoped OOC, request `session_control` with `enter_ooc` or `exit_ooc`; the Bridge supplies the scope. Mode persists across turns of the same canonical conversation. Do not reopen an Owner session to bypass a participant's scope. Local Owner registration remains an administrative compatibility API, not a model session-repair strategy.

受限 OOC 只请求 enter_ooc / exit_ooc，作用域由 Bridge 注入；模式在同一规范会话中跨轮保留。不得另开 Owner Session 绕过 Participant 作用域。本地 Owner 注册仅保留管理兼容接口，不作为模型修复会话的路径。

Consume `generation_context` / its deterministic `model_context` once. `stable_prefix` and `temporary` remain compatibility views; do not inject them again beside model_context. Runtime dynamic data never becomes permanent Character state.

使用统一契约及其确定性 model_context 一次；旧 stable_prefix/temporary 只作兼容视图，不再重复注入。动态上下文不能累积为人物永久设定。

可见输入先 event_ingest：稳定 source_id/source_event_id 和 operation_id，明确 USER_DIRECT/QUOTED/FORWARDED/MEDIA_DERIVED/PLANNED/SIMULATED。不上传隐藏推理和凭据。只有值得长期保留的信息才提交 turn_commit.proposal，并引用返回的 RawEvent IDs。Narrative 和助手历史不是新事实证据。不要把尚未送出的输出记为已送达。

使用当前宿主模型生成自然回复；不调用第二个必需模型。GenerationRequest 给出实际任务意图、用户格式/长度要求；这些优先于人物口癖。读取 context 中的声音和表达策略，不能让长历史训练人物永久变长。

失败只使用当前可见资料，不虚报持久化。超时重试原 operation_id 和完全相同请求；不要换 ID 重复提交。旧 candidates/turn_id 写入明确不兼容，按新 Schema 迁移。
