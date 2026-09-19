# 本地审计报告 — 0.1.0

> 本文保留初版设计/验证历史，不代表当前发布入口或托管状态。最新分发说明见 [distribution.md](distribution.md)。

本报告记录初始快照 `5d28049` 的验证结果；后续中断点自查修复与最新结果见 [追加复核报告](interruption-review.md)。

日期：2026-09-19（Asia/Shanghai）。范围：本地可运行 Runtime、MCP、Skill、分发元数据与平台接入契约。**没有上传、创建远程仓库/PR、发布包、建隧道或部署公网服务。** 这是一版本地可审计实现，不代表 ChatGPT 手机与所有宿主已经验收。

## 验证结果

| 检查 | 实际结果 |
|---|---|
| unittest 全套 | 45/45 通过；含三轴 × 三种 mutability 子用例 |
| Ruff lint / format | 通过 |
| mypy strict | 14 个核心源文件，无错误 |
| 构建 | wheel 与 sdist 成功；运行/开发 lock + 独立构建约束 |
| 独立安装 | 在源码目录外的新虚拟环境安装 wheel 和锁定依赖，导入路径确认为安装包；console script 与完整演示通过 |
| MCP stdio | 官方 Client 真实子进程往返，工具发现、创建、提交、召回通过 |
| MCP HTTP | ASGI 协议测试通过；另外实际绑定 127.0.0.1，官方 Client 发现 10 个工具，未认证请求 401 |
| JWT | 真实 RSA 签名校验；错误签名/issuer/audience/过期/scope/subject 拒绝；JWKS 读取在测试中替换成本地 key |
| Plugin | portable manifest 对官方 1.0.0 JSON Schema 通过；Plugin Creator 兼容包校验通过 |
| Skill | Skill Creator 校验通过 |
| 运行时 Schema | 四份 JSON Schema 与 Pydantic 一致；原创示例卡校验通过 |
| 产物内容 | wheel 仅代码/metadata；sdist 含源码、锁文件、测试、Schema、Skill、文档；无数据库/.env/cache |

运行命令见 [README](../README.md) 与 [开发说明](development.md)。[本地演示记录](demo.md)包含真实输出及当前助手参与的角色续接，分别标注确定性脚本和模型生成，未把预写台词当成自动 LLM 验收。

## 已实现

- 独立 Definition / State / Memory、Storage 协议、事务 SQLite、跨 owner/character/session 隔离。
- 原创/IP 数据模型；Canon/AU/Inspired；六级 provenance 优先级；用户事实不被自动覆盖。
- 持久默认角色、项目路由、会话覆盖/关闭、OOC 恢复、三种任务模式与临时任务恢复。
- 自动候选阈值、短期/session TTL、衰减排序、修改、显式共享、过期、遗忘、现实记忆提升。
- 语义关系状态、三轴可变性、相邻关系变化、至少三次新互动证据、幂等回合及原子状态/记忆提交。
- versioned JSON 角色包；记忆默认不导出；可携带成长摘要；显式包含角色记忆；现实/会话/过期/遗忘排除；导入新 ID 与权限剥离。
- 10 个 MCP 工具、stdio、认证 HTTP、现成 OAuth 提供方的 JWT 资源服务器接口。
- 移动端不依赖桌面文件的 Skill；Codex/Hermes/AstrBot 示例与远程 ChatGPT 接入说明。

关键目录与架构图见 [README](../README.md#结构与架构)，模型/记忆/隐私说明见 [数据契约](reference.md)。

## 复核与修复记录

独立子代理复核了存储与核心边界，主任务实际检查代码并重跑测试。发现并加回归测试修复：

1. 现实记忆提升后原角色正文可能重复导出：改为迁移正文、擦除来源、双向遗忘。
2. 会话/短期/现实记录可作为长期成长证据：按持久类型白名单拒绝。
3. 关系成长可以无证据或无限复用旧证据：核对三次真实回合 receipt，且证据必须晚于上次关系变化。
4. 自动成长可能覆盖已有定义：保护所有已存在 Definition key，显式修改走 OOC。
5. 默认导出丢失全部有证据的演化：独立 portable_summary 保留非事件摘要；无摘要使用省略标记。
6. 认证 HTTP 的远程 Host 白名单遗漏 resource 域名；最大长度 session 无法提交 Memory：分别复现并修复。

这些复核不是第三方安全认证。语义授权、角色表现和摘要脱敏仍有以下边界。

## 尚未验证或未来扩展

| 项目 | 当前边界 |
|---|---|
| ChatGPT 手机 / Codex 自动插件路由 | 目标架构与包已准备，尚未在真实账号注册/连接；当前助手通过本地 Client 桥接做展示 |
| 远程 OAuth / 跨设备 | 验签与资源服务器已实现；真实身份提供方登录、刷新/注册、HTTPS 部署与手机续接尚未执行，须审计后另行授权 |
| Hermes / AstrBot | 官方机制与示例配置；无真实宿主端到端结果 |
| Windows / Linux | 标准 Python/pathlib/uv，未实机测试；macOS arm64 + Python 3.11.15 已验证 |
| 自动角色质量 / Memory 提取 | 依赖宿主遵循 Skill、每轮调用与诚实候选评分；MCP 本身没有强制回合 hook |
| 隐私语义 | 非空 confirmation 不能证明真人授权；portable_summary 不能自动证明脱敏，分享前需审阅包 |
| 删除 | 擦除活动数据库正文与派生证据；不能追删历史导出、导入副本、备份或宿主上下文，不承诺磁盘物理擦除 |
| 规模 | 单服务 SQLite、owner 内 O(n) 召回、简单关键词；高吞吐/海量记忆再换索引与 Storage |
| 多角色群聊 | 显式知道其他角色、逐条共享、共享世界 ID 槽；无完整关系图/组权限 UI 或群聊调度 |
| 其他 | 无网页后台、计费、原生 ChatGPT Memory 写入、模型 API 绑定、向量集群或公网基础设施 |

## 清理、Git 与审计门槛

本次演示/测试只使用合成数据。短暂 loopback 服务已停止。项目保留源码、uv.lock、构建约束、tests/docs/schemas/examples、必要 `.venv` 和 `dist`；临时演示 DB、临时安装环境、下载缓存与 Python/lint/typecheck 缓存在最终清理中移除。

新仓库使用本地 `development` 分支，未设置 remote。本地快照用于复核；最终 `git status --short` 与提交结果在当前任务交付消息中确认。 `.gitignore` 排除 `.env`、数据库、日志、缓存、依赖与构建目录；检查未发现真实 Token、API Key 或用户私人 Memory 入仓。字符检测/文件扫描不构成绝对无泄漏证明。

测试、lint/typecheck、构建、独立安装和实际本地闭环均已通过；接下来是用户审计。若要求修改，执行修改→复测→再演示。只有明确“审计通过，可以上传”或等价授权后才允许进入远程阶段；该授权不会自动等于公开发布或上传私人记忆。
