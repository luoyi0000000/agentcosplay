# agentcosplay

选一个角色，开始聊天。

agentcosplay 让 Agent 按人物的身份、性格、经历和关系自然说话：少套话，保留事实，语气词随性格而变。支持原创人物、原作人物、平行世界设定、切换角色和 OOC。

**1.0.1 · 安装即可开始当前会话的角色对话。** 不需要 API Key、终端操作或自行启动服务。当前没有托管记忆服务，跨会话保存与跨设备同步尚未随插件启用。

## 在 ChatGPT / Codex 的插件页安装

将此仓库添加为 marketplace 来源：

**https://github.com/luoyi0000000/agentcosplay**

选择 **agentcosplay → 安装**，在新会话选中插件，然后说：

> 扮演一个安静、可靠的灯塔守望者，叫林舟。今天有点累，陪我聊会儿。

如果你是 ChatGPT 工作区管理员，在 **Admin → Plugins → Add → Import marketplace** 填入上面的仓库地址，Path 留空，导入后向成员开放。成员从插件页安装即可。没有该管理入口时，用下方 Agent 安装方式。

仓库已提供官方格式的 marketplace 文件；这不代表已经收录进 OpenAI 公开插件目录，也不保证每个账号都有导入权限。[平台安装规则](https://learn.chatgpt.com/docs/enterprise/plugin-management)。

## 让 Agent 帮你装（推荐）

把下面一句发给 Hermes、AstrBot 或其他支持 Skills 的 Agent：

> 根据 https://raw.githubusercontent.com/luoyi0000000/agentcosplay/main/skills.md 为我安装 agentcosplay 的全部 skills。请识别当前平台，完成安装和可用性检查，然后带我创建一个角色开始对话。

不需要理解内部配置。[skills.md](skills.md) 会告诉 Agent 如何使用当前平台的安装机制、保留已有配置并验证是否加载。当前包含一个完整 Skill：`agentcosplay`。

Hermes 可使用其原生 Skill 安装机制。AstrBot 用户也可以直接[下载技能包](https://raw.githubusercontent.com/luoyi0000000/agentcosplay/main/downloads/agentcosplay-skill.zip)，在 **插件 → 技能 → 上传技能** 中导入并启用；若人格配置只允许指定 Skills，把 `agentcosplay` 加入列表。

### 可选：单行安装

给有终端的 Agent 使用，支持 macOS / Linux；自动识别单一 Hermes 或 Codex 安装：

```bash
curl -fsSL https://raw.githubusercontent.com/luoyi0000000/agentcosplay/main/install.sh | bash
```

安装器只下载校验后的 Skill，不安装服务、不修改其他插件。多宿主、AstrBot 或自定义目录交给上面的自然语言安装指令处理。安装后宿主可能需要开启新会话才会加载。

## 怎么聊

- “用你自己的方式说话，别每句话都加同一个语气词。”
- “进入 OOC，把称呼改一下；改好后回到角色。”
- “换成另一个角色，之前的私人经历不要共享给他。”
- “这段代码先用普通语气讲，讲完再恢复角色。”
- “把角色设定整理出来，方便我下次粘贴接着聊。”

当前会话内可以维持角色和经历；上下文丢失后不会编造回忆。手动导出的设定文本可以带到新会话，但不是自动长期记忆。原有持久记忆引擎仍在仓库中，连接真实后端后才启用保存、隔离、成长和迁移能力。

## 项目与文档

- [Agent 安装入口](skills.md)
- [Marketplace 清单](.agents/plugins/marketplace.json)
- [插件与角色规则](plugins/agentcosplay/skills/agentcosplay/SKILL.md)
- [分发格式与发布状态](docs/distribution.md)
- [数据与隐私契约](docs/reference.md)
- [开发与测试](docs/development.md) · [高级持久记忆接入](docs/adapters.md)

角色扮演不会授权工具操作、伪造 AI 身份或将虚构经历写入真实用户记忆。数据库和密钥不包含在安装包中。
