# agentcosplay

让 Agent 持续作为你选择的人物交流。角色有独立设定、关系、记忆和成长；表达自然、少套话，句尾语气随性格与情绪变化。

**1.1.0 · 本地运行，人物数据归你。** 完整安装包含 Runtime、持久化存储、宿主适配和角色 Skill。无需作者提供云服务；模型与聊天渠道由你正在使用的 Agent 提供。

## 让 Agent 安装

把整个仓库链接发给有文件和执行权限的 Codex、Hermes 或 AstrBot 管理 Agent：

> 安装这个项目：https://github.com/luoyi0000000/agentcosplay 。识别当前宿主，安装完整 Runtime 和角色规则，验证持久记忆，再带我创建角色。

也可以使用可直接读取的安装入口：

> 根据 https://raw.githubusercontent.com/luoyi0000000/agentcosplay/main/skills.md 为我安装 agentcosplay，包括本地 Runtime、当前平台适配和全部 Skills，并验证安装成功。

Agent 会使用与人工安装相同的安装器。只有聊天权限的机器人不能替你修改宿主，需要在实际运行它的机器或管理界面操作。

## 自己安装

需要 **Python 3.11+、Git 和可下载依赖的网络**。在 Runtime 宿主执行，以下示例选择 Codex；Hermes 将 `codex` 换成 `hermes`：

```bash
git clone https://github.com/luoyi0000000/agentcosplay.git
cd agentcosplay
python3 install.py --host codex
python3 install.py doctor
```

Windows 使用 `py -3` 代替 `python3`，不需要 WSL。安装器自动准备独立依赖、合并配置并验证协议；随后重新加载宿主。AstrBot、容器、更新/回滚/卸载见 [INSTALL.md](INSTALL.md)。

可选的 macOS / Linux 快捷入口：

```bash
curl -fsSL https://raw.githubusercontent.com/luoyi0000000/agentcosplay/main/install.sh | bash -s -- --host hermes
```

这会下载并执行仓库安装代码；需要先审查时，请使用上面的 clone 路线。

## 数据与跨设备

人物数据默认放在操作系统用户数据目录，与源码和程序安装目录分离。卸载程序保留人物数据。更新不会清空记忆，也不改变身份；版本不兼容时拒绝打开数据库。

手机 QQ、电脑等渠道通过 **Hermes / AstrBot / Gateway** 使用 Runtime 主机上的同一份人物数据。主机可以是你的电脑或 VPS。多个 Gateway 接同一进程的方法见 [共享 Runtime](INSTALL.md#多个入口连接同一个-runtime)。这不是把数据库同步到每台设备，也不取决于模型是否相同。

角色迁移通过导出包 → 导入完成。默认不导出聊天记忆；明确选择后才包含角色记忆，真实用户记忆仍被排除。详见 [数据契约](docs/reference.md)。

## ChatGPT / Codex 插件页

仓库提供官方格式的 [marketplace 清单](.agents/plugins/marketplace.json)。可添加此仓库为来源，选择 agentcosplay 安装；有权限的 ChatGPT 工作区管理员可从 **Admin → Plugins → Add → Import marketplace** 导入仓库，Path 留空。

**仅从 marketplace 安装的是角色对话规则。** 没有可访问的 Runtime 时，只能维持当前会话，不能声称开启了长期记忆。ChatGPT 云端不能直接访问你电脑的 stdio 或回环地址；手机连续对话优先通过已有 Gateway。仓库不提供作者托管服务，也不保证每个账号都有导入权限或已经公开上架。[平台安装规则](https://learn.chatgpt.com/docs/enterprise/plugin-management)。

AstrBot 的可选[对话 Skill ZIP](https://raw.githubusercontent.com/luoyi0000000/agentcosplay/main/downloads/agentcosplay-skill.zip) 也不是完整 Runtime 安装。

## 开始聊天

> 扮演林舟，一个安静、可靠的灯塔守望者。今天有点累，陪我聊会儿。

支持创建和切换人物、OOC 修改设定、按实际互动发展关系。切换人物不共享私人经历；普通技术任务可以临时退出人物口吻。不会为沉浸感伪造共同经历、现实行动或 AI 身份。

[安装与排障](INSTALL.md) · [Agent 入口](skills.md) · [适配与工具](docs/adapters.md) · [验收及问题修复](docs/installation-audit.md) · [开发](docs/development.md)
