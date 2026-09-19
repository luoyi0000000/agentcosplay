# agentcosplay 分发与验收

版本 1.0.1，核验日期 2026-09-19。用户确认暂无托管服务，本次范围为 marketplace、Agent 安装入口与安装后角色对话。

## 分发结构

```text
.agents/plugins/marketplace.json
plugins/agentcosplay/
  plugin.json
  .codex-plugin/plugin.json
  skills/agentcosplay/
    SKILL.md
    references/runtime.md
skills.md
install.sh
downloads/agentcosplay-skill.zip
```

清单的 `source.path` 是 `./plugins/agentcosplay`，从仓库根解析。插件目录自包含，复制或导入时不会引用外部源码路径。portable `plugin.json` 与 Codex 兼容清单使用同一名称、版本及界面描述。没有虚构服务 URL 或 `.app.json` 注册 ID。

普通用户安装 Skill 不需要 Python。Python 包、服务端显示名称及两份插件清单统一为 `agentcosplay` / 1.0.1。内部 Python import 仍为 `character_runtime`，旧 `character-runtime` CLI 别名继续可用，保护现有集成；数据格式、环境变量与数据库不因品牌改名而迁移。

## 能力状态

| 能力 | 当前状态 |
|---|---|
| 仓库 marketplace 清单与独立插件包 | 已提供，待目标账号导入验收 |
| 当前会话角色对话、OOC、自然表达 | Skill 已提供，无后端依赖 |
| Hermes 原生安装目标与自然语言指令 | 已提供；未在真实 Hermes 中验收 |
| AstrBot Skill ZIP 与自然语言指令 | 已提供；未在真实 AstrBot 中验收 |
| Bash 安装、校验、重复安装及保留用户修改 | 隔离目录测试；不更改本机实际宿主 |
| 后端持久化、身份隔离、导入导出 | 核心能力保留，自动化测试覆盖 |
| ChatGPT 托管长期记忆、跨设备同步 | 未部署，需真实 HTTPS / 身份服务 |
| OpenAI 公开目录收录 | 未提交、未收录；仓库清单不等于上架 |

## 平台机制

OpenAI 工作区管理员可以从 GitHub 导入清单，之后由工作区控制成员安装权限；本地 marketplace 与公开目录是不同的分发渠道。官方说明：[marketplace 导入](https://learn.chatgpt.com/docs/enterprise/plugin-management)、[插件打包](https://developers.openai.com/plugins/build/plugins)。

Hermes 支持按仓库内目录安装标准 Skill；AstrBot 支持包含 Skill 文件夹的 ZIP，并从实际数据目录发现本地 Skill。官方说明：[Hermes](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills/)、[AstrBot](https://docs.astrbot.app/use/skills.html)。文档可用不代表已经实测所有版本和账号。

## 维护下载包

修改 Skill 后运行 `python -m scripts.build_distribution`，生成确定性 ZIP，并更新安装器中的 SHA-256。运行 `python -m unittest tests.test_distribution` 检查版本、内容一致性与安装失败保护。生成 ZIP 是正式下载资产，应提交；普通 `dist/` 构建产物与缓存不提交。

自动安装不覆盖不同内容，也不绕过平台授权。发生校验失败、下载失败或中断，清理临时包，保留已有技能。强制终止可能留下安装锁；应先确认无安装进程后处理锁，不能盲删整个技能目录。
