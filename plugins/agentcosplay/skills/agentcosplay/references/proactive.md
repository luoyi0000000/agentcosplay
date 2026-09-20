# 主动联系

默认关闭。用户明确开启后配置时区、免打扰、冷却、每日上限和渠道；用户退出/不想被打扰时立即关闭。Host Scheduler 与 Runtime Scheduler 都调用 proactive_decide；不能另写一套判断或绕过 silence_reason。

should_contact=false 就保持安静。true 是已保留的联系意图，不是已发送消息。宿主当前角色模型依据 topic/context 生成内容，Gateway 负责真实发送。发送前再次 proactive_decide(character_id, reservation_id=decision.id) 确认授权和保留仍有效；成功后用 proactive_ack(delivered=true)，明确未发送才 false。发送结果不确定时不要重发；超时默认保守抑制重复。实际送达采用 decision_id 幂等键。

不会只因情绪变化主动骚扰用户。遵守冷却、安静时段、最近活动、忙碌状态、话题去重和 opt-out。未完成话题只是候选，不代表每次都要翻旧账。调度输出可能含私人话题，只交给授权宿主，不记到公开日志。
