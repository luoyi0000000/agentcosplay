# 项目进度

当前分发版本：1.0.1；用户确认暂无托管服务，先交付安装入口与当前会话角色对话。已提供 marketplace、skills.md、AstrBot ZIP、Bash 安装器；实际宿主验收和托管长期记忆状态见 [分发说明](distribution.md)。

## 初版开发记录

- [x] 附件 42 节和共享对话全部读取。
- [x] 环境检查：空项目；Node 24.21.0；Python 3.14.5 / 已有 3.11.15；Git 2.54.0；uv 0.11.7。
- [x] 当前官方机制核实：Skill、Plugin、移动端、Codex MCP、Python SDK、Hermes、AstrBot。
- [x] 设计规格与实施计划。
- [x] 类型模型与 Storage。
- [x] Runtime、Memory、成长、Package。
- [x] MCP、Skill、Adapters。
- [x] 测试、构建、本地演示；清理与 Git 最终状态见 audit.md。
- [x] 中断点追加自查与缺陷修复，见 interruption-review.md。
- [x] 用户授权上传 GitHub；后续调整为正式分发。

工程决定：用户明确要求只询问真正阻塞问题，本地实现已授权；不额外插入逐阶段审批。远程端到端验收在明确远程授权后进行，不冒充本地完成项。
