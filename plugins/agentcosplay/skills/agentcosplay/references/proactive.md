# 主动联系

默认关闭，只有用户明确授权才启用时区、安静时段和渠道。decide 返回联系意图，不是发送结果。

流程为 proactive_decide → proactive_prepare(session_id,decision_id) → 宿主当前模型生成 → proactive_delivery(character_id,decision_id,claim_id) → 平台发送 → proactive_ack。prepare 和 delivery 只许可一次；发送前应立即领取 delivery 且 should_contact=true。禁止用重复 decide 代替发送许可。

ack 的 true/false/null 分别是确认成功/确定未发送/结果未知；未知时隔离，不能重发。查证后再确认。平台支持时用 decision_id 防重。所有 topic 和 context 只交给授权宿主，不进入公开日志。交互意图和平台能力不会单独授予发送权限。
