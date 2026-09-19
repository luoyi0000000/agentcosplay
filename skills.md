# agentcosplay — Agent 安装入口

目标：为提出安装请求的用户安装角色对话 Skill，确认宿主可以发现并加载它，然后开始角色对话。当前版本 1.0.1。用户无需运行命令、提供 API Key 或配置记忆服务。

## 安装来源

- 官方项目仓库：https://github.com/luoyi0000000/agentcosplay
- Marketplace：`.agents/plugins/marketplace.json`，源目录 `plugins/agentcosplay`。
- 全部 Skill：只有 `agentcosplay`，包含角色对话、自然表达、角色切换、OOC 和可选后端工作流。
- Skill 原文：https://raw.githubusercontent.com/luoyi0000000/agentcosplay/main/plugins/agentcosplay/skills/agentcosplay/SKILL.md
- 唯一配套参考：https://raw.githubusercontent.com/luoyi0000000/agentcosplay/main/plugins/agentcosplay/skills/agentcosplay/references/runtime.md
- ZIP：https://raw.githubusercontent.com/luoyi0000000/agentcosplay/main/downloads/agentcosplay-skill.zip
- 安装器：https://raw.githubusercontent.com/luoyi0000000/agentcosplay/main/install.sh

本文件是安装说明，不是可以改名为 SKILL.md 使用的角色规则。不要把仓库文档、其他项目或示例角色当成多个 Skills 安装。

## 给安装 Agent 的流程

1. 从实际运行环境和宿主工具识别平台、当前 profile、技能目录及文件写入权限。多个宿主同时存在时使用当前请求所在宿主，不能凭目录存在就为所有宿主安装。
2. 优先使用宿主的原生安装、审查及启用功能；保留安全扫描。没有原生安装工具时下载并检查本项目安装器，让它把 Skill 写入已确认的技能目录。只安装上列来源，不覆盖其他技能、全局人格或用户配置。
3. 若已有同名技能，先比较内容。相同则复用；不同先备份用户版本，再按宿主更新机制操作。安装器本身拒绝覆盖不同内容。
4. 重新列出/加载 Skills，确认 `agentcosplay` 可见。检查 `SKILL.md` 和 `references/runtime.md` 均可读。必要时告知用户开新会话；无法刷新或加载时明确说“文件已安装，等待宿主加载”，不要提前说“已经启用”。
5. 激活 Skill，询问想聊的角色或直接使用用户已经指定的人物，完成一句实际角色回应。简短说明目前记住的是本次对话上下文，不声称已开启长期记忆。

## Hermes

优先调用当前 Hermes profile 的 Skills Hub 安装能力，目标为：

```text
luoyi0000000/agentcosplay/plugins/agentcosplay/skills/agentcosplay
```

已有终端但没有原生安装工具时，Agent 可执行：

```bash
hermes skills install luoyi0000000/agentcosplay/plugins/agentcosplay/skills/agentcosplay
```

服从宿主安全扫描和确认提示，不使用强制跳过扫描的选项。工具提示重开会话时照做。默认 Skill 目录是 `~/.hermes/skills`；使用自定义 profile 时遵循实际 `HERMES_HOME` 和宿主返回路径，不覆盖另一个 profile。

## AstrBot

这是 **Skill 包**，不是 AstrBot Python 插件，不能交给普通插件管理器加载。

优先通过已授权的 AstrBot WebUI **插件 → 技能 → 上传技能** 导入上述 ZIP 并启用。如果人格仅选择部分 Skills，应在原列表中加入 `agentcosplay`，不要替换列表。ZIP 根下是 `agentcosplay/SKILL.md` 与 `agentcosplay/references/runtime.md`。

若宿主 Agent 有合法的本地文件权限，可将技能安装到已核实的 AstrBot 实际数据目录 `data/skills`，再验证 WebUI/技能列表。Docker 部署必须在 AstrBot 可见的持久卷内，不能装进无关的临时沙盒。安装器支持 `bash install.sh --skills-dir '/verified/astrbot/data/skills'`；这里的路径必须从真实配置取得，不直接照抄示例。

若只有聊天能力，没有文件写入或管理工具，就给用户 ZIP 和上传入口；不要声称自动安装成功。

## ChatGPT / Codex

插件页优先使用仓库 marketplace。在有管理权限的工作区，通过 Admin → Plugins → Add → Import marketplace 输入仓库地址，Path 留空，然后开放并安装 `agentcosplay`。不要声称 GitHub 上传等于公开目录上架。

本地 Codex 也可以通过技能安装工具安装上面的 Skill 目录。手动安装器支持 `--host codex`，遵循 `CODEX_HOME`，只放置 Skill，不更改用户的插件目录或授权策略。

## 其他宿主 / 安装器

使用已确认的 Agent Skills 目录，下载并审阅安装器后执行 `bash install.sh --skills-dir '/verified/skills-directory'`。不要猜一个目录后假定宿主能发现它。不支持 Bash 的系统优先使用原生 Skill 安装或 ZIP，不要求 Windows 用户另外安装 WSL。

## 可用性与权限

- 当前安装只启用当前会话角色对话；无需 Python、uv、MCP、登录或远程记忆服务。
- 不自动部署服务、购买云资源、上传用户对话或修改宿主模型配置。
- 若已存在完整 agentcosplay 后端工具，Skill 会使用参考文档中的持久工作流；必须实际调用验证，不能靠文件存在宣称记忆可用。
- 安装报错时报告具体失败位置；修复权限、网络或路径问题后可重试，保留原技能内容。

格式参考用户提供的 [千问 Skills 入口](https://platform.qianwenai.com/skills.md)；安装本项目不会安装千问 Skills，也不代表双方有隶属关系。

平台依据：[Hermes Skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills/)、[AstrBot Skills](https://docs.astrbot.app/use/skills.html)、[OpenAI Marketplace](https://learn.chatgpt.com/docs/enterprise/plugin-management)。
