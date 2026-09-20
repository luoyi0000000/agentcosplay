# Companion Runtime

所有状态按 owner + character ID 保存在 SQLite 的 companion collection，schema_version=1。时钟可注入，UTC 存储；IANA 时区用于免打扰和每日上限。Windows 安装锁定的 tzdata 数据包。

| 领域 | 实现与约束 |
|---|---|
| Mood | 持续 label/intensity/reason/evidence/时间；每分钟至多一次、上升不超过 .25；6 小时半衰期，回归 neutral，不改 Definition |
| Goals | ID、描述、来源、重要性、状态、创建/截止、进度和证据；最多30，active/paused/completed/cancelled |
| Habits | 同一行为按不同本地日期累积；至少3天才 established，强度按10天渐进，最多20条 |
| Life State | idle/reading/resting/working/walking 白名单；仅 life_simulation 开启时推进 |
| Unfinished Topics | relevance×priority、status、cooldown、last_mentioned；最多30条，每次context最多3条 |
| Providers | time/weather/schedule/location，元数据和有效期；同种只存最新一条，不积累天气历史 |
| Self Model | context.py 的引用视图，组合已有身份、信念、人格、关系、记忆、成长和陪伴字段 |
| Proactive | proactive.py 唯一决策引擎，事务保留+幂等回执；只产生意图，不生成/发送消息 |

## 配置与回合

OOC 下 companion_control(session_id, update) 修改配置与明确设置的状态。普通回合的 mood/goal/habit/topic 更新可放 turn_commit.companion，与该轮 Memory/Growth 同一事务、同一 turn_id 去重；功能开关不得放入普通 commit。开关是 proactive_contact、schedule_awareness、weather_awareness、life_simulation、relationship_growth，前四项默认关闭，自动关系成长默认保留。

每次 runtime_context 按查询选择最多12项设定、8项记忆、3项目标/习惯/话题；文本有上限，截断的核心记录可按需另读。include_companion=false / include_self_model=false 可减少视图。记忆仍是每 owner 线性扫描，小规模单用户使用；大规模需存储层索引。

## Provider

统一 Provider.read() -> Observation | None；SystemTimeProvider 与 JSONFileProvider 是实际实现。宿主通过 provider_observe 提交观测；本地自托管采集器可更新用户指定 JSON 文件，CLI 用 --provider-file weather=/绝对路径/weather.json（schedule/location/time 同理）。不从模型参数接受任意路径/URL，不在核心绑定天气厂商，不索取厂商凭据。

Observation 带 source、observed_at、fetched_at、expires_at、summary；天气/位置须 location_scope。时间戳需顺序正确，拒绝未来/过期/倒退观测；最大 freshness：time/location 1小时、weather 12小时、schedule 24小时。读取再次检查过期；缺失、格式错误或不可访问时降级无数据，不阻断聊天。网络采集由宿主或其自托管采集器负责。

CLI 示例（维护者）：

```bash
uv run --locked python -m character_runtime serve --provider-file weather=/private/weather.json
uv run --locked python -m character_runtime scheduler --character CHARACTER_ID --once
```

已安装程序可用安装根下 launch.py 传同样 scheduler 参数，以确保使用安装记录中的 owner 和数据目录。省略 --once 按 --interval 周期运行（默认300秒，最短60秒），由既有进程管理器启动/停止。观测文件仅支持单 owner 服务；OAuth 多 owner 需通过各自认证的 provider_observe 提交，不能共享全局私人日程文件。

## 主动联系与中断

Host Scheduler 调 MCP proactive_decide；Runtime Scheduler 调 scheduler.tick，二者最终都调用同一个 Companion.decide/proactive.decide。周期唤醒不等于周期发消息。

默认关闭；开启后的默认保护：22点至次日8点安静、6小时联系冷却、近1小时有用户活动则静默、每日最多2次。用户可明确配置；quiet_start=quiet_end 表示不设安静时段。busy/unavailable、日程忙碌、用户 opt-out、话题冷却与去重均会静默，高 urgency 不绕过它们。候选来自相关未完成话题或临近截止的重要目标，情绪变化本身不触发联系。

should_contact=true 带唯一 decision.id，事务内保留；其他 Scheduler 看到 delivery_unconfirmed。发送前再次 proactive_decide(character_id, reservation_id=id) 检查开关、活动、时段与话题是否仍有效。保留超过5分钟视为 stale，但不会自动重发，避免进程在“已发但未回执”处崩溃后重复骚扰。

宿主当前模型加载角色生成文本，Gateway 以 decision.id 作幂等键发送；实际成功才 proactive_ack(delivered=true)，明确没有发送才 false。不确定送达则保持 pending，由宿主/用户核对。重复同结果 ack 幂等，矛盾回执拒绝。Runtime 不保证外部网络恰好一次投递；需要 Gateway 幂等支持，不具备时只保证保守抑制自动重发。关闭后不能再发送此前保留的意图。

Scheduler stdout 是交给授权宿主的 JSON 意图，可能含私人话题；不要重定向到公开日志。没有生成/发送能力时不能宣称已启用自动聊天。

## 离线推进

根据时间、fresh日程/天气、用户选择的低风险目标活动与已有习惯选择当前活动。雨雪/风暴下 walking 改为室内 reading；夜间 resting。默认不追补功能关闭期间的时间。

长时间离线单次最多推进72小时估计量，目标进度单次最多 .1，自动最多 .95，不模拟完成重大事件。只有明确标记 simulate 的日常目标才推进；固定描述不复制可能涉及真实人的目标正文。累计48小时且确有进度变化才产生 simulated_life 候选，普通生活不存 Memory。候选 importance=.5，按既有策略降为短期；必须经事务内 advance→drain→memory.store，失败一起回滚。

这是保守、粗粒度的角色日常估计，不是现实活动证明。不能模拟事故、疾病、婚姻、用户共同经历或现实重大事实。模型表达需保留其虚构来源。
