# Runtime 连接与恢复

先发现本次工具 Schema。打开当前会话独有 session；平台消息用稳定 host/platform/actor_id，未知身份不能冒用本地 owner。runtime_context 给出 stable_prefix + temporary；切换人物时清除旧投影与旧临时对话，不删除持久人物。

可见输入先 event_ingest：稳定 source_id/source_event_id 和 operation_id，明确 USER_DIRECT/QUOTED/FORWARDED/MEDIA_DERIVED/PLANNED/SIMULATED。不上传隐藏推理和凭据。只有值得长期保留的信息才提交 turn_commit.proposal，并引用返回的 RawEvent IDs。Narrative 和助手历史不是新事实证据。不要把尚未送出的输出记为已送达。

使用当前宿主模型生成自然回复；不调用第二个必需模型。GenerationRequest 给出实际任务意图、用户格式/长度要求；这些优先于人物口癖。读取 context 中的声音和表达策略，不能让长历史训练人物永久变长。

失败只使用当前可见资料，不虚报持久化。超时重试原 operation_id 和完全相同请求；不要换 ID 重复提交。旧 candidates/turn_id 写入明确不兼容，按新 Schema 迁移。
