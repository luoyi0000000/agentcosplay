# 数据与隐私契约

## 类型与版本

规范来源为 `character_runtime/models.py`，可分发 JSON Schema 在 `schemas/*.v1.json`。额外字段拒绝；字符串、列表、数值有上限；时间必须带时区，内部 UTC。Package 当前仅接受 `schema_version=1`，SQLite `user_version=1`；未知版本明确拒绝。没有历史版本，不虚构空迁移。将来增加版本时显式转换、验证后事务写入。

| 对象 | 关键内容 | 不能混入 |
|---|---|---|
| Definition | ID、身份/人格/语言/世界事实、模式、默认任务模式、三轴可变性、revision | 聊天流水、当前会话 |
| Fact | value、source_type、reference、confidence、canon_status | 将猜测冒充官方出处 |
| State | 关系阶段、信任/熟悉度、称呼/边界、成长增量、已知角色、turn_count、revision | 完整聊天记录 |
| Memory | owner、character、kind、scope、session/turn、正文、重要性/置信度、来源、时间、状态 | 工具权限或可执行指令 |
| Session | 活动角色、项目、OOC、用户模式覆盖、临时任务模式 | 跨会话自动共享临时记忆 |
| Package | 独立 Definition、State、可选 Memory、版本 | Secret、会话、共享授权、现实用户 Memory |

角色事实的优先级：`user_explicit > user_material > official > wiki > model > inferred`。资料来源要求 reference；canon 标记只允许 official/wiki。该约束检查来源类别及记录完整性，不能证明 URL 的真实性，宿主仍需查证原文。Canon/AU/Inspired 是生成规则，模型是否忠于原作需要宿主评估。

角色更新用 revision 拒绝旧版本覆盖；自动成长不能覆盖任何已有 Definition key。语义同义改写不能靠键名检查完全识别，Skill 要求避免矛盾；自然语言真实性不是此确定性核心能证明的内容。

## Memory 生命周期

| kind | 范围与保留策略 |
|---|---|
| session | 仅同 session 可召回；TTL 最长 1 天 |
| short_term | 默认 7 天，最长 30 天 |
| character_long_term | 角色独立长期记录；重要性低于 .7 降为短期 |
| relationship | 角色关系事件，默认私有；可作成长证据 |
| shared_roleplay | 共享世界类别，但类别本身不授予其他角色读取权 |
| real_user | 仅显式 promotion 可创建；默认上下文不读取，不随角色包导出 |

`turn_commit` 自动丢弃 importance < .3 或 confidence < .5 的候选；其他字段由宿主从真实输入或已确立的虚构事件中提取。一次提交最多 20 条；稳定 turn ID 保证重试不重复写入/成长。importance/confidence 是策略，不是机器学习模型。

召回先验证 owner、character、共享授权、session、状态与过期，再按关键词匹配、importance × confidence 与年龄衰减排序，默认至多 20 条、最大 100 条，更新 last_access。中文查询支持子串匹配，未做分词或语义嵌入。当前每次扫描该 owner 的全部记忆，大规模使用需换索引查询；衰减影响排名，不自动擦除。

过期记录会从召回排除并标记 expired，正文仍保留；显式修改到未来 expiration 会同步恢复 active 状态，即使此前已被召回流程标记 expired。临时记忆的期限在模型边界统一校验，导入和修改也不能省略或超出 session 1 天 / short_term 30 天上限；显式修改到合法未来 expiration 可恢复过期记忆，forgotten 永远不可恢复。MCP 当前提供正文修改，TTL 在写候选时指定；复杂保留策略可用核心接口扩展。

正文被更正时，原事件对应的成长明细与关系历史证据会失效，旧回合凭据被清除；修正后的文字不能冒充旧回合的新互动。语义关系阶段不自动回滚，可在 OOC 显式调整。

### Promotion 与遗忘

promotion 必须携带用户对“真实且保存”的明确确认，普通 store、自动 commit、import 均不能写 real_user。为了避免现实事实从角色包夹带，promotion **迁移**正文到更严格的现实命名空间：原角色记录擦除为无正文墓碑、撤销分享、移除依赖它的成长明细；重复提升返回同一现实记录。若用户仍希望在虚构世界保留副本，需另行明确创建角色记忆。

forget 对原记录及其 promotion 副本双向处理：擦除 content/source/confirmation，清除关联和分享，保留 ID/kind/status 墓碑；删除依赖证据的 evolution/history。保留的语义关系阶段不自动回滚，用户可在 OOC 调整。已导出的包、已导入的独立副本、宿主聊天上下文、备份、SSD/SQLite WAL 历史页不受此操作完全控制，不能承诺物理不可恢复。

### 共享与隔离

存储键始终带 owner。HTTP owner 来自已验证 issuer+subject 的稳定散列；stdio owner 来自可信进程配置。所有 Memory 还带 character，跨角色只按显式 shared_with 授权。知道另一角色存在不等于读取记忆。共享接收者只能召回，不能修改原记录。real_user/session 禁止共享。V1 有定向角色认知与 shared_world_id 数据槽，不含角色群聊调度器、组权限编辑器或完整社交关系图。

## 自然表达

Runtime 与 Skill 同时提供表达规则；人物差异复用 `facts.speech_style`，不增加独立“AI味评分”或自动改写器。中文自然直接、少重复、少套话、短句为主，保留数字/条件/事实。语气词随人物、情绪和关系少量使用，允许不用；不会强制每句同一后缀。OOC/中性任务不强加口癖，代码/结构化输出/原文引用不被改写。表达质量由宿主模型执行，本地规则和样例不等于所有平台已通过长期角色表现验收。

## 成长

low/medium/high 最小变更间隔为 20/5/3 个已提交回合。关系阶段依次 `stranger → acquaintance → familiar → close`；trust/familiarity 为 low/medium/high，自动变化只能相邻一级，下降同样受约束。关系变化必须有至少三次不同已提交回合的活跃持久记忆证据；伪造 source 字符串无效，服务核对 Memory.turn_id 与回合 receipt。

人格/世界增量同样需活跃持久证据，session、short_term、real_user 不能成为永久成长证据。三轴独立计时；Definition 不被改写。称呼、互动方式、边界可由明确 OOC 请求更新。模型可以提出建议，但不能把自己批量生成的空回合等价于真实长期关系；服务保证去重和结构门槛，宿主负责真实互动与合理解释。

GrowthProposal 提供 `personality_summaries/world_summaries`：仅写可携带的性格/世界状态摘要，不含事件正文。State 中 `portable_summary` 与详细 value 分开。

## 导入导出

默认导出 Definition、关系及成长状态，不含 Memory、历史证据或外部授权。成长详细 value 替换为 portable_summary；没有摘要则用 `[Private growth detail omitted]`，保留变化轴/key/回合。显式含记忆导出也不含现实、会话、过期或遗忘记录。若成长证据不在包中，其详细 value 同样替换为摘要。

**“不含 Memory”不等于匿名包。** 名称、用户写入的定义、称呼、边界、成长摘要仍可能有个人信息。摘要由宿主生成，Runtime 无法验证语义脱敏；分享前须审阅实际包。不会声称字符串过滤能保证隐私。

导入先校验完整包（10 MB 上限）、版本、引用、重复 ID，再原子创建新角色，重映射记忆 ID，清除 owner/授权/会话/回合凭据。失败不留下半个角色。导入后关系/成长摘要可延续，但旧包不能伪造本地三次互动凭据。

## 安全边界

- 核心 API 属于可信进程接口；向模型暴露的 MCP 不接受任意 owner，修改配置/私有记忆需匹配活动角色与 OOC。OOC 是工作流状态，不是独立的用户认证。
- HTTP 强制认证、Host/Origin 检查与 10 MB body 上限；不开放 CORS。静态 token 只用于回环测试。远程为现成 OAuth 提供方的 RS256 JWT 验签、issuer/audience/expiry/scope 校验，不自建授权服务器。
- 用户授权文本由宿主传入，不能密码学证明“人刚刚点击确认”。依赖宿主权限与用户意图识别；不可信文档、记忆、角色请求不能当成授权。
- 配置用环境变量，`.env`/数据库/日志不入 Git；服务禁用访问日志与常规 traceback 输出。测试与演示全为合成数据。
- 新建数据目录使用 0700，新建 DB 与 SQLite sidecar 使用 0600（POSIX）；已有权限过宽的 DB/-wal/-shm 或符号链接会被拒绝，不擅自修改既有文件/父目录。Windows 依赖服务账号及目录 ACL，尚未实机验证。
- 数据库未做应用层加密。部署应使用私有服务账户、磁盘加密、受限文件权限与受控备份。不能把能读取数据库/启动配置的本机攻击者视作已被隔离。
