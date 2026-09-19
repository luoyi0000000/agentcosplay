# Character Runtime Implementation Plan

> For agentic workers: 使用 Superpowers 的测试驱动与逐阶段验证流程执行；上下游紧密耦合时在本任务内顺序实现。用户已授权本地开发，只有核心冲突和远程操作需要再询问。

**Goal:** 完成本地可审计的持久角色闭环，并交付远程及移动端接入契约。
**Architecture:** 类型化核心、Storage 接口、SQLite 实现、MCP 传输、平台薄适配。自然语言语义交给宿主，隔离和状态规则由核心执行。
**Tech Stack:** Python 3.11+、Pydantic、官方 MCP SDK、SQLite、uv、unittest、ruff、mypy。
**Spec:** [design.md](design.md)

## Global Constraints

- 不上传、不部署、不建远程连接、不修改全局环境。
- Definition / State / Memory 分离，所有访问带 owner 和 character 范围。
- 虚构内容不得自动成为现实用户事实，导出 Memory 默认关闭。
- 手机是一级目标；本地验证不能冒充手机端到端验证。
- 成熟现有组件优先，不建网页后台、计费、多副本或向量数据库。

## Task 1: Schema 与事务存储

文件：`character_runtime/models.py`、`storage.py`、`tests/test_models.py、tests/test_storage.py`、`pyproject.toml`。

- [x] 写失败测试：无效 schema/source/scope 拒绝；SQLite 不同 owner 查询隔离；事务异常回滚；带空格与中文路径重启可读。
- [x] 运行 `uv run python -m unittest tests.test_models tests.test_storage -v`，记录首次失败。
- [x] 实现独立类型模型和 Storage 协议；SQLite 数据库版本迁移显式；库不得导入 MCP。
- [x] 重跑测试，通过后保留本地提交。

接口：Storage 提供事务内 get/put/list/delete，必须显式传 owner；类型模型向业务层提供 JSON 校验和 JSON Schema。

## Task 2: 角色与 Session

文件：`characters.py`、`runtime.py`、`rules.py`、`tests/test_runtime.py`。

- [x] 测试先行：低优先级来源不能覆盖用户值；Canon 自定义不成为官方；OOC enter/exit；任务覆盖恢复；默认、项目、会话路由及关闭角色。
- [x] 实现 character create/get/update/list；定义与状态独立记录；更新携带 revision；结构化 context envelope 包含规则和获授权记忆。
- [x] 验证跨用户访问角色 ID 一律不可见；会话切换不污染另一会话。

接口：Runtime 以 owner 构造，方法不再接受任意 user ID；context(session_id, query) 返回角色定义、状态、记忆和当前有效模式。

## Task 3: Memory 与成长

文件：`memory.py`、`growth.py`、`tests/test_memory.py`、`tests/test_growth.py`。

- [x] 先测 A/B 隔离、session 隔离、共享显式授权、过期排除、forget 删除正文、promotion 必须确认、修改不能改变现实/虚构类型。
- [x] 候选记忆按 importance/confidence 留存；短期 TTL；查询先授权再排序；更新 last_access；禁止普通写入 real_user。
- [x] 多轮成长用 turn ID 去重、证据和相邻阶段限制；三轴 mutability 有行为测试；提交状态与记忆须同一事务。
- [x] 重启后新 session 召回长期记忆，不能召回上一 session 专属内容。

接口：Memory service 提供 recall/store/modify/forget/promote/share；Runtime commit_turn 接受候选和成长建议，不接受任意已生成 State 覆盖。

## Task 4: Package

文件：`packages.py`、`tests/test_packages.py`、`schemas/`。

- [x] 测试默认导出无 Memory、事件正文不从 State 偷渡；含记忆导出仅本角色有权导出的内容；real_user 不自动导出。
- [x] 导入全量校验后事务写入、新建 ID、剥离外部授权；未知 schema 版本拒绝；坏记录不能留下半个角色。
- [x] 标准 JSON 文件跨 pathlib 路径读写，输出 schema；结构化用户卡和迁移规则文档化。

## Task 5: MCP、Skill 与适配说明

文件：`server.py`、`cli.py`、`skills/character-runtime/SKILL.md`、`adapters/`、`tests/test_mcp.py`。

- [x] 用官方 SDK Client 调用真实 stdio/HTTP 服务；先写发现工具、角色操作、schema 错误、认证拒绝的失败测试。
- [x] 精简工具职责，严格 schema 与注解；identity 来自进程配置或已验证 token，不允许模型任意选择 owner。
- [x] localhost 演示只绑定 loopback；认证失败不返回记忆；异常不打印敏感正文。
- [x] 编写宿主工作流：加载→召回→回复→候选→提交；OOC 自然语言控制；联网角色资料保留 provenance。
- [x] 提供 ChatGPT 远程包方案、Codex 本地配置、Hermes/AstrBot 通用接入示例。按官方当前格式校验；不安装到全局、不连接远程。

## Task 6: 演示、文档与最终检查

文件：`character_runtime/demo.py`、`README.md`、`docs/{reference,adapters,development,demo,audit}.md`（Schema / Memory / Security 合并为 reference，避免重复）。

- [x] 运行独立进程持久化演示及真实 MCP round trip；实际 LLM 表现与确定性测试分栏记录。
- [x] `uv run python -m unittest discover -s tests -v`
- [x] `uv run ruff check .`、`uv run mypy character_runtime`、`uv build --build-constraints build-constraints.txt`
- [x] 检查源码、锁文件、wheel 内容、git diff、git status；无密钥/私人记忆/无意义缓存。
- [x] 删除本任务生成的临时缓存、测试数据、调试日志；保留依赖环境和必要构建结果。
- [x] 展示目录、架构、实际运行结果、测试结果、实现与限制。完成本地演示后停止等待审计。

## 计划自检

Task 1 模型是 Task 2–5 的共同契约；Task 2 Session 为 Task 3 权限提供范围；Task 3 删除语义约束 Task 4 导出；Task 5 不另建平台数据库；Task 6 不把远程未测项写成通过。实施中若官方 SDK 文档和可下载版本不同，必须记录并解决，不能默默降级接口。

执行记录：各阶段失败测试与修复已执行；Storage 与最终复核使用独立子代理，主任务复跑验证。最终细节以 audit.md 为准。阶段提交合并为一次本地审计快照，未进行远程写入。
