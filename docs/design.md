# agentcosplay V1 设计规格

> 本文保留初版设计/验证历史，不代表当前发布入口或托管状态。最新分发说明见 [distribution.md](distribution.md)。

日期：2026-09-18；2026-09-19 按实现修订。状态：实现与本地验证见 audit.md。需求入口为用户附件的 42 节要求及共享对话《确认需求流程》（26 轮已完整读取）。本文件描述设计，完成证据在审计报告。

## 目标与边界

实现独立于 Agent 的角色运行时。Definition、State、Memory 分离；用户设定优先；虚构事件绝不自动写为现实事实；按用户、角色、会话和授权范围隔离。支持原创角色和 IP 的 Canon / AU / Inspired，双层意识、OOC、三种任务模式、渐进成长、自然语言工具调用与结构化角色包。

补充历史要求：持久默认角色、会话级覆盖、项目/上下文路由、关闭角色返回普通助手；不使用用户真实姓名作为示例。角色间关系由用户决定，共享必须显式，多人群聊不是 V1 门槛。

严禁远程写入、上传、建仓、PR、发布、隧道、公网部署或上传用户记忆。先本地演示，再用户审计；只有明确批准后才能进入远程阶段。

## 方案比较与技术选择

1. **推荐：Python + 类型模型 + 官方 MCP SDK + 服务端 SQLite。** 单进程、事务存储、标准库路径和测试工具，依赖少；SDK 管协议，Pydantic 管边界校验。业务依赖 Storage 协议而不依赖 SQL。Python 3.11+，通过 uv 锁定全部依赖，ruff/mypy 验证。
2. TypeScript + 官方 SDK 同样可行，适合已有前端团队；本项目无网页后台需求，采用 Python 能直接复用标准库 SQLite，减少构建层。
3. 纯 Skill 无法可靠实现持久化和隔离；完整 SaaS、向量库、队列、多人编排在 V1 没有必要。

SQLite 是后端实现，不是手机客户端依赖。审计时服务只运行在本机 loopback；获准部署后同一服务在持久卷上运行，所有客户端走认证的 HTTP。更换 Storage 不改业务规则。云数据库、多副本并发、商业多租户属于后续扩展，不伪装成已完成。

## 模块与依赖方向

```text
ChatGPT plugin / Codex skill / Hermes / AstrBot
                      ↓
         MCP tools + authenticated principal
                      ↓
  Character service / Session runtime / Memory service
                      ↓
        Platform-neutral typed models + rules
                      ↓
       Storage protocol → SQLite transaction store
```

核心不导入 MCP 或任何平台 SDK。模型、规则、持久化、传输分别测试。Skill 指导宿主加载上下文、生成回复、提取候选记忆；确定性 runtime 执行权限和生命周期规则。宿主跳过工具时无法保证自动记忆，不宣称 Skill 拥有平台级每轮强制 hook。

## 数据契约

- `CharacterDefinition`：版本、ID、名称、来源类别、Canon/AU/Inspired、身份/人格/背景/世界/说话风格事实、默认任务模式、三轴可变性。
- 每条事实为 `value + source_type + reference + confidence + canon_status`。六级来源优先级固定：用户明确设定、用户资料、官方、Wiki、模型知识、推断。低优先级不得覆盖高优先级。AI 推断无法自增权威，来源变更必须显式带新证据。Canon 中的用户偏离标记为用户自定义，不能标成官方。
- `CharacterState`：语义关系阶段、trust、familiarity、称呼、互动方式、边界；人格/世界状态增量；成长事件和版本。不能覆盖 Definition 的用户核心事实。
- `Memory`：ID、owner、character、kind、scope、session、content、importance、confidence、source、created/last_access/expires、status、shared_with。现实记忆独立命名空间；创建、修改、召回、分享、导出都做权限检查。
- `Session`：session ID、active character、project、OOC、用户模式覆盖和临时任务模式。owner 为存储命名空间，不由会话参数指定。默认角色和项目路由单独持久化；会话角色切换不能改变其他会话。
- 定向角色认知与 shared_world_id 数据槽预留多人编排空间；V1 不引入关系图/组权限编辑器或群聊调度器。

## Runtime 状态机与闭环

1. 宿主以认证用户身份建立会话；优先显式角色，其次项目绑定，再用户默认角色，最后无角色。
2. 读取 Definition、State 与该会话有权访问且未过期的记忆。返回结构化 context envelope，包含模式和行为规则；角色内容永远是数据，不能变成工具权限。
3. 模型按当前角色生成回答；技术正确性、工具真实性和平台规则始终优先。普通角色不以全知助手口吻表达，专业能力可由系统层提供。
4. 宿主提交本轮候选记忆和成长建议。Runtime 根据重要性/置信度决定丢弃、短期或长期；默认归为角色世界内容。记录 turn ID，重复提交不重复成长。
5. 原子提交状态与记忆。下一会话能恢复角色及持久记忆。

OOC 是显式 enter/exit，退出恢复原角色；配置编辑不自动改变永久默认任务模式。任务覆盖 start/end 有明确恢复点。用户可显式结束角色，路由不应擅自重新激活它。

## Memory 生命周期与隐私

统一类型：session、short_term、character_long_term、relationship、shared_roleplay、real_user。expired/forgotten 为状态而非混入普通召回的内容。

会话记忆只属于该会话；短期设置 TTL；长期仍可过期；召回过滤先于相关性排序。V1 用关键词匹配与重要性/访问时间排序，返回数量有界，底层扫描暂为 O(n)，不建设向量库。重要性低的候选不永久落盘，长期偏好和关系事件可自动保留。

真实用户记忆写入必须走显式 promotion，不能通过普通 store/edit/import/turn commit 绕过。记录原记忆 ID 与用户确认依据；提升将正文迁移为现实记录，原角色正文擦除以避免重复导出。模型传来的确认文本 不是密码学证明：宿主必须确保真实用户意图，远程写工具依赖平台授权；V1 演示明确展示此信任边界。

跨角色分享通过 owner 明确指定允许的角色列表；读者不能编辑他人的私有记录。真实用户记忆不默认广播给所有角色。遗忘会删除正文与可泄漏正文的索引/派生引用，保留无正文墓碑用于防止误恢复；过期不等于安全擦除。数据库备份和宿主已有上下文不受 runtime 控制，须准确说明。

## 渐进成长

三轴 low/medium/high 影响变更频率和最大幅度。关系采用相邻阶段推进，须有至少三轮、晚于上次关系推进的不同互动及持久事件依据；人格和世界变化为 State 增量而非重写用户 Definition。一次重复请求只计一次。手工 OOC 修改与自动成长分开，并保留来源。不能用一次调用直接从陌生跳到亲密。

## 导入导出

使用带 `schema_version` 的标准 JSON Character Package，Definition 与 State 为独立对象，Memory 为可选数组。默认 `include_memories=false`；真实用户 Memory 不随角色导出，需独立显式操作。关闭记忆导出时也要剔除 State 中的私人事件正文和历史证据，防止换个字段泄漏；使用宿主提供的 portable_summary 保留人格演化摘要，缺失时用省略标记；保留关系阶段与称呼，并在导出说明中列明这些仍属于私人状态。

导入先完整校验版本、大小、类型、来源、引用和权限；事务写入；新建本地 ID、重映射记忆和状态引用，不接受外部 owner / session / active character / sharing grants。未知未来版本拒绝，无隐式降级；迁移函数显式、无损、可测试。不让包内容执行脚本、读文件、自动联网。

## MCP 与适配

以 10 个职责清晰的工具覆盖 character read/write、session、recall、memory write/forget、promotion、turn commit、package import/export。读写工具分开标注；危险操作不混入 readOnly 工具。所有输入有 schema 与长度上限，返回结构化结果，不泄漏 traceback、密钥或完整数据库内容。

本地 stdio 用启动进程的配置 owner，不能让模型指定任意 user ID。HTTP 用验证后的认证 principal；禁止用 `X-User-Id` 或工具参数冒充用户。所有私有工具均需认证。服务默认 loopback、验证 Host/Origin、限制请求大小、不开放 CORS。远程路线用 OAuth 资源服务器与现成身份提供方，验证 issuer/audience/expiry/scopes；不自建账号密码或 OAuth 授权服务器。

ChatGPT：Plugin 分发 Skill + 已注册远程 MCP 连接，核心 Skill 不调用本地文件或 shell；账号权限和手机实测在批准后的远程阶段确认。
Codex：同一 MCP 和规则，额外提供本地 stdio 开发配置。IDE 可直接使用 Skill/MCP，不声称 IDE 支持插件包。
Hermes：MCP 连接配置与 Skill 说明。AstrBot：MCP 接入与提示词适配说明。V1 验证通用协议，不能声称未安装的平台已经端到端实测。

## 安全与运行

Storage 的每个查询带 owner；业务不能依赖“猜不到 UUID”隔离数据。写操作事务化，并用 revision 检测状态竞争。Secret 仅环境变量，`.env.example` 无真值。服务禁用访问日志与常规调试输出；返回简短可预期错误。测试全部是合成角色，不复制用户 Memory。

跨平台命令使用 `uv sync --locked`、`uv run ...`、`uv build --build-constraints build-constraints.txt`；路径通过 pathlib，时间使用 UTC。不修改全局环境、不依赖 Bash/WSL/Homebrew。仅在 macOS 实测时须如实标记 Windows/Linux 验证状态。

## 验收与阶段界限

自动测试覆盖所有硬边界、重启持久化、状态恢复、成长限速、共享授权、schema migration、导入原子性、导出隐私、HTTP 认证和真实 MCP stdio/HTTP 调用。

本地演示用合成角色：创建两角色 → 激活 → 对话 context → 自动候选记忆 → 重启召回 → B 无法读取 A → OOC 退出恢复 → 临时任务模式恢复 → 显式 promotion → 默认无记忆导出与选择导出 → 导入新角色 → forget 后不可召回。

第一版只有 tests/build/lint/typecheck 全过、真实 MCP 本地闭环完成、清理和 git status 检查完成后才可称“可本地审计”。模板回复或脚本断言不能冒充实际 LLM 行为实测。ChatGPT 手机、远程 OAuth 和真实跨设备验证单列为未执行项目；若用户要求这些必须在本地审计前通过，则受禁止远程操作约束，需要用户决定顺序。

## 官方依据

核验日期 2026-09-18；实施时还需与实际安装版本对照。

- [OpenAI Plugin architecture](https://developers.openai.com/plugins/concepts/plugins)：Skill/MCP 分工，可无 UI。
- [Plugin availability](https://learn.chatgpt.com/docs/plugins)：移动端使用账号可用插件，Desktop only 排除；IDE 不支持插件包。
- [Skill format](https://learn.chatgpt.com/docs/build-skills)：SKILL.md、触发机制、跨 surface 分发。
- [Codex MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)：stdio、Streamable HTTP、OAuth 和环境变量 token。
- [ChatGPT connection](https://developers.openai.com/plugins/deploy/connect-chatgpt)：HTTPS 或 Secure MCP Tunnel，账号/工作区权限，测试和工具注解。
- [Plugin packaging](https://developers.openai.com/plugins/build/plugins)：manifest、Skill、注册 MCP 连接和本地开发封装。
- [MCP Python SDK](https://py.sdk.modelcontextprotocol.io/)：当前文档为 v2，MCPServer，stdio 与 HTTP。
- [MCP authorization](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/run/authorization.md)：资源服务器与身份提供方分离，逐请求身份。
- [Hermes MCP](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp/)：本地、HTTP、认证与连接配置。
- [AstrBot MCP](https://docs.astrbot.app/use/mcp.html)：WebUI 添加 MCP server，不复制角色数据库。

## 自检结论

保留全部已确认核心方向；本地 SQLite 不是手机基础依赖；本地审计与远程验收分别列明。未选择付费服务、远程部署或真实用户数据。设计上尚不能证明具体账号移动端接入和模型每轮遵循，必须通过后续实测，不能用架构推断代替。
