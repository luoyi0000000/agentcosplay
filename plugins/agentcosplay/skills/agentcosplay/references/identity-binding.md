# 平台身份与端点

Runtime Owner is the authenticated local administrator; Participant is the verified speaker. Platform messages follow `identity_control → endpoint_bind → real Host message → host_prepare_turn / host_turn_open → scoped context/tools`. Never route an unknown actor through the local Owner session path. Nicknames and avatars cannot establish identity.

Owner 是已认证本地管理员，Participant 是本轮经过验证的说话人。平台消息先显式绑定身份与 Endpoint，再由真实 Host 消息开启受限回合；不能先走旧 `open_session` 再补身份。旧未认证 Session 始终拒绝私人数据。不得为方便把未知 Actor 当成 Owner。

`endpoint_bind.endpoint` is the external Host string, such as `cli:default:user`. Its returned `id` is the Runtime `endpoint_id` used by Host routes and lifecycle calls. They are not interchangeable. Stable errors are `endpoint_binding_not_found`, `endpoint_kind_mismatch`, and `endpoint_inactive`.

`endpoint_bind.endpoint` 是外部端点字符串，返回的 `id` 才是后续使用的 Runtime `endpoint_id`。不要混用。群聊必须同时保留 Actor 与 Endpoint，且不读取任何参与者私人记忆。

The verified Owner may call `endpoint_control(action="deactivate", endpoint_id=..., expected_revision=..., operation_id=..., confirmation=...)`. This increments the revision, preserves history/unknown fields/audit receipts, and rejects new turns and old capabilities. Retry the exact operation ID and arguments. Rebinding requires explicit Owner action using the current revision; deactivation never resets delivery history or authorizes resend.

仅经过认证的 Owner 可停用 Endpoint。停用增加 revision、保留历史与审计，并撤销旧回合权限；聊天模型的确认文字不构成管理授权。重试复用原 operation_id 和参数。重新绑定须显式管理操作及当前 revision，不重置投递历史，也不允许未知结果自动重发。
