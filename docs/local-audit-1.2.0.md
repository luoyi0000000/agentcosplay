# agentcosplay 1.2.0 本地审计报告

日期：2026-09-20  
项目：/Users/zeonjyuwai/Documents/Codex/agentcosplay  
范围：本地增量实现与验收。没有上传、发布、部署或修改真实宿主配置。

## 1. 修改摘要

新增：Companion 持续状态、Provider、统一主动联系决策、Runtime Scheduler、有界 Self Model 视图、Companion 可选导出包、三系统 CI、回归测试。版本更新为 1.2.0。

修改：runtime_context / turn_commit / MCP 接入；记忆来源与遗忘边界；可恢复卸载；单一 Skill 及按需 references；README 两种入口；两个 manifest 的 P1 品牌资源。

删除：19个旧演示/分发/重复文档文件，逐项见第2节。保留已工作的安装器、核心契约、Memory/Growth、安全与平台接入，不调用第二个 LLM。

重点检查中断后发现并修复的问题：

| 问题 | 实际影响 | 修复位置与证据 |
|---|---|---|
| 原 context 全量输出设定和记忆 | 构造输入输出278,930字符，会随资料增长膨胀 | context.py / runtime.py；有界投影、查询选取、原始资料不变，test_context |
| 首用说明存在冲突 | 没后端时混入安装术语；空角色可能当故障；文档要求不存在的删除工具 | 主 Skill、runtime reference、INSTALL、skills.md；三种首用场景复查通过 |
| 模拟生活来源未有提升边界 | 模拟记录能进入 real_user 或共同事件类型 | models.py / memory.py / runtime.py；来源限制贯穿存储、提升、导入、成长 |
| 新增 Companion 派生状态未随遗忘失效 | Memory删除后，mood/goal/habit仍可能回显正文 | memory.py 的统一证据失效入口清理派生内容 |
| 遗忘后待发送意图残留正文 | pending_decision.topic 仍能通过工具返回 | 清除意图正文但保留 decision ID 和未确认状态；独立审查复现、回归测试修复 |
| 话题冷却忽略较新的提及 | 旧发送时间覆盖最近讨论时间，可能过早再次提起 | proactive.py 使用发送/提及中较新时间；回归先失败后通过 |
| 卸载清理被文件占用中断后不能重试 | 已标记卸载，下次调用跳过残留 releases | install.py 让重复卸载继续清理；文件占用与数据保留回归通过 |

以上是已复现问题及修复，不表示已经证明不存在其他漏洞。

## 2. 删除文件

删除前搜索了 tests、scripts、安装器、manifest、docs 和构建配置中的引用；运行必要依赖迁移后的单测、构建与真实隔离安装。

| 删除文件 | 原依赖、原因及确认方式 |
|---|---|
| examples/original-character.json | 仅Schema测试加载的合成卡；测试改为7份实际契约对照，角色创建另有真实MCP测试 |
| character_runtime/demo.py | health/MCP/安装验收使用其中call；将检查协议与业务状态的helper迁到health.py并更新所有调用，独立演示流程由现有E2E覆盖 |
| downloads/agentcosplay-skill.zip | 原Bash单Skill入口和分发测试使用；完整install.py与Marketplace不读取，撤销此额外路线后删除 |
| install-skill.sh | 只安装Skill的旧入口；统一完整安装器与Marketplace，清理文档及旧脚本测试 |
| install.sh | Bash下载包装器；不被install.py依赖，README不再提供第三路线 |
| scripts/build_distribution.py | 只构建被移除的Skill ZIP；manifest直接读取源目录，删除AGENTS旧构建指令 |
| adapters/codex.example.toml | 静态示例与安装器生成的原生配置重复；原生配置合并、真实stdio验收通过 |
| adapters/hermes.example.yaml | 同上；保留host_config.py生成与共享HTTP配置验收 |
| adapters/astrbot.example.json | 同上；实际安装器生成JSON并由双客户端验收读取 |
| adapters/agent-instructions.md | 与唯一主Skill重复；高级接入统一指向该Skill |
| docs/audit.md | 旧版本历史验收；由本报告取代，历史仍在Git |
| docs/demo.md | 已删除演示的旧输出；当前真实测试结果进入本报告 |
| docs/design.md | 旧架构阶段说明；持续契约集中到reference/companion |
| docs/distribution.md | 包含旧Bash/ZIP路线；现行分发说明集中到development |
| docs/implementation-plan.md | 已结束的历史实施计划；当前计划与实际代码分别保留 |
| docs/installation-audit.md | 旧1.1.0安装审计；当前完整生命周期重新验收 |
| docs/interruption-review.md | 历史修复记录；旧回归测试保留，本次新增问题列于第1节 |
| docs/plans/local-installation.md | 已完成旧安装计划；installer和回归保留 |
| docs/progress.md | 陈旧1.0.x进度，与当前能力不一致 |

保留兼容manifest和character-runtime CLI别名，已有宿主可能依赖。没有盲删源码、锁文件、必要测试或用户数据库。

## 3. Companion Runtime

| 领域 | 实现 |
|---|---|
| Mood | companion_models.py + companion.py：持久强度、更新时间、reason/evidence；单次升幅最多.25、每分钟一次；6小时半衰期，回归neutral |
| Goals | companion.py：创建/暂停/完成/取消、来源、期限、进度和证据；最多30 |
| Habits | companion.py：不同本地日期累积，至少3天建立；强度渐进，最多20 |
| Life State | companion.py：固定低风险activity集合，持久化，关闭模拟时不推进 |
| Unfinished Topics | priority/relevance/status/cooldown/last_mentioned；新提及延长冷却 |
| Providers | providers.py：统一Protocol、系统时钟、本地JSON文件；宿主通过provider_observe提交；来源、时间、有效期、地点范围齐备 |
| Proactive | proactive.py：默认关闭、安静时段、每日上限、联系与话题冷却、最近用户活动、可用性、退出开关、紧急度 |
| Scheduler | scheduler.py + cli.py：--once或周期；Host Scheduler通过MCP调用同一决策引擎 |
| Offline Simulation | advance→drain→Memory.store同一事务；当前活动通常仅State，明确可模拟目标累计48小时且进度变化才生成simulated_life短期记忆 |
| Self Model | context.py：JSON Pointer指向现有Definition/State/Memory/Companion；没有重复持久化人格 |

新增工具：companion_control、provider_observe、proactive_decide、proactive_ack。普通回合的状态更新与turn_commit同事务去重，设置开关须OOC操作。环境缺失/过期不会阻断角色聊天。

主动联系的true仅代表保留意图；宿主当前模型写内容，获授权Gateway负责送达。发送前带reservation_id再次复核；不确定送达保留pending，不自动重发。实际渠道恰好一次投递仍需要Gateway支持幂等键。

详尽字段、默认值和维护命令见项目 docs/companion.md。

## 4. 首次使用

| 状态 | 当前行为及验收性质 |
|---|---|
| Marketplace-only | 无工具也先问“你想让我扮演谁？”；用户选角后直接当前会话聊天，诚实说明只在本对话记住；Skill代理场景复查通过，真实ChatGPT UI未验证 |
| Runtime connected | 打开独有session→context返回choose_character→选角/创建→activate→持久化；自动回归和真实MCP工具链通过 |
| Runtime error | 说明暂时无法保存，继续当前可见角色；context失败不盲写，commit结果未知复用原ID；Skill场景复查通过，不冒充真实应用网络故障E2E |

压力复核另外涵盖：仓促开启每小时联系、导入卡伪造promote授权、旧天气上下文，共6个只读代理情景。它们不是ChatGPT/宿主UI实测，也不是自动化长期语言质量评分。

## 5. README

只剩两条安装路线：

1. ChatGPT Marketplace导入整个仓库URL。
2. 把仓库URL发给具备执行权限的Agent自动安装。

README不再给git clone、python install.py、curl或Skill ZIP路线。技术细节仍在INSTALL/docs，完整安装始终使用同一install.py。

明确本地主机存储、Gateway共享同一Runtime、没有作者云服务；Marketplace不会在手机/电脑自动部署Python后端。

## 6. Logo

使用本次提供的P1：codex-clipboard-90279743-c2bb-4a81-869c-e58fe714aef9.png，原样复制，未裁切、重绘或变形。

资源：plugins/agentcosplay/assets/logo.png  
SHA-256：6705d3ecc42b9cebaaa4881faf0b57429275d8cc560845af438d20a3568a9ae1

根plugin.json的extensions.com.openai.interface与兼容.codex-plugin/plugin.json.interface都设置logo、composerIcon为./assets/logo.png，brandColor=#A64965。

按[当前官方文档](https://developers.openai.com/plugins/build/plugins)，inline com.openai存在时整体替代兼容overlay，不进行合并。本仓库权威源为根manifest，两份interface一致。官方portable JSON Schema校验、Plugin Creator兼容校验、资源路径/摘要检查、源码包资源检查均通过。

未打开真实ChatGPT Plugin UI；插件页显示与小尺寸composer icon清晰度仍需人工验收。没有声称UI已通过。

## 7. 数据 Schema

SQLite仍为user_version=1，旧Definition/State/Memory/Package V1结构保留。新增独立CompanionState V1与Observation V1，不重写原核心记录。

默认角色导出仍是V1且无Memory/Companion；显式include_memories=true + include_companion=true时使用V2。V2仍排除real_user，剔除provider/位置观测、投递记录及主动联系授权。

V1→V2导入转换使用深拷贝，原始输入/文件不改写，保留原包作为备份；导入创建新人物，不覆盖旧人物。未知版本拒绝，失败不留下半个角色。本轮没有SQLite schema升级，因此无需数据库改写迁移，也未删除数据库。

实测旧代码互操作：从HEAD df3a2fb的1.1.0代码写库→1.2.0增加Companion→1.1.0读取核心→1.2.0再次读取Companion，均保留。安装回滚也通过；回滚不把数据恢复到旧快照。旧1.1.0不认识V2角色包，可使用默认V1导出。

需要完整备份时先停止全部连接，复制整个私有数据库目录；不只复制活跃SQLite主文件。原始包/数据库备份由用户保管，不自动上传。

## 8. 测试

执行位置为项目根目录，macOS本机Python 3.11。以下数量有交集，不可相加当作独立总数。

| 命令/检查 | 通过 | 失败 |
|---|---:|---:|
| 修改前 .venv/bin/python -m unittest discover -s tests -q | 68 | 0 |
| 最终 .venv/bin/python -m unittest discover -s tests -q | 97 | 0 |
| .venv/bin/python -m unittest tests.test_mcp -q | 3 | 0 |
| .venv/bin/python -m unittest tests.test_mcp.SharedRuntimeTests -q（包含于上项） | 1 | 0 |
| .venv/bin/python -m unittest tests.test_companion tests.test_companion_integration tests.test_proactive tests.test_providers tests.test_companion_packages tests.test_context -q | 27 | 0 |
| .venv/bin/python -m unittest tests.test_installation -q | 11 | 0 |
| .venv/bin/ruff check . | 静态检查通过 | 0 |
| .venv/bin/ruff format --check . | 全部格式通过 | 0 |
| .venv/bin/mypy character_runtime | 22个源码文件 | 0 |
| uv sync --locked | 40个锁定包解析通过 | 0 |
| uv build --build-constraints build-constraints.txt | wheel + sdist | 0 |
| .venv/bin/python -m scripts.check_installation | 1个完整脚本，9项验收点 | 0 |
| git diff --check | 通过 | 0 |
| Plugin Creator validate_plugin.py plugins/agentcosplay | 1 | 0 |
| 官方plugin.schema.json + jsonschema.validate | 1 | 0 |
| 文档相对链接、私密文件路径、三系统workflow解析、构建资产检查 | 通过 | 0 |
| 旧1.1.0/新1.2.0 SQLite互操作 | 1个四阶段检查 | 0 |

安装脚本覆盖：fresh-install、真实stdio重连、源码移动、原生配置、同一真实回环HTTP进程双客户端双向记忆、update、rollback、uninstall保留数据库、reinstall保留记忆；均为临时中文/空格路径。另有SDK测试双向关系及Companion目标连续。

新测试先暴露失败，再修复；曾出现的格式/类型检查问题已处理。最终没有测试失败。JWT测试偶尔有asyncio慢任务诊断信息，不是失败。

macOS本机通过。Windows/Linux实机：未验证。三系统CI仅本地创建，未上传、未执行，不声称CI已绿。Windows时区、路径、文件占用恢复有代码/测试覆盖，真实ACL及系统占用行为仍待平台运行。

## 9. 实际宿主

| 宿主 | 本轮实际验证 | 尚未验证 |
|---|---|---|
| Codex | 隔离原生配置、SDK stdio真实进程发现/重连、安装生命周期；本任务在Codex中开发 | 将新版安装到用户真实profile后触发角色插件的完整UI E2E |
| Hermes | 原生YAML生成、同一HTTP Runtime的独立SDK客户端读写 | 真实Hermes应用、定时唤醒、模型生成与实际渠道发送 |
| AstrBot | 原生JSON生成、同一HTTP Runtime的独立SDK客户端读写 | 真实AstrBot应用、容器部署、QQ等消息渠道、实际主动发送 |

未动用户真实宿主配置、没有向他人发消息。可重复的实机验收步骤在docs/adapters.md。

## 10. 已知剩余问题

- 真实ChatGPT插件页面、各宿主自然语言表现和Windows/Linux实机仍需审计；不能用SDK检查代替。
- Runtime产生意图；接入实际定时任务、当前模型和发送渠道由宿主/Gateway负责。若投递状态不确定，需人工或Gateway核对后ack，不自动重发。
- Provider只有系统时钟、宿主提交和本地JSON采集入口，没有默认天气/日历厂商、隐式定位或作者云服务。凭据由宿主管理。
- 离线模拟是受限粗粒度估计，不是连续真实人生模拟；运行时不能自动证明任意自然语言描述真实性。
- 当前按owner扫描记忆；数据很大时需要索引检索。没有完整群聊编排、社交图或SaaS多租户产品。
- 记忆遗忘清理当前记录及已登记派生证据，不承诺擦除备份、平台历史或已交给宿主的旧内容。
- V2包隐私默认更保守；分享前仍应审阅用户自行写入的角色定义/关系。
- 当前仍未选择 License，需要项目所有者决定。

## 11. Git 状态

本地分支：companion-runtime。存在本轮未提交修改，便于审计diff；本轮没有新建commit。HEAD仍为df3a2fb2b31dae92a2f4ae775f7a8f871b8c94c5。

只读GitHub API核对main仍为1bc92e53e9b3f8d570bb2a14d988a28c896c06bd，与开始前记录相同。本轮没有任何远端写入；没有git push、PR、Release、包发布、远程部署或用户数据上传。旧本地HEAD与先前API发布commit的元数据不同是既有情况，本轮没有重置或强推。

清理范围：本次临时旧版校验副本、下载的Schema副本、Python/lint/type缓存与空的旧目录。保留源码、uv.lock、必要测试、.venv复现环境及本地1.2.0构建包；这些依赖/构建目录不入Git。

**尚未上传 GitHub，等待用户审计批准。**
