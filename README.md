# agentcosplay

<img src="plugins/agentcosplay/assets/logo.png" alt="agentcosplay" width="240">

让 Agent 作为你选择的人物自然交流：有独立设定、记忆、关系、情绪、目标和日常状态。角色直接由你正在使用的宿主模型表达，不经过另一个模型“润色”。

## 1. ChatGPT Marketplace

在支持导入 Marketplace 的 ChatGPT 环境中，将此仓库添加为 Plugin source，再安装 **agentcosplay**：

https://github.com/luoyi0000000/agentcosplay

Marketplace 安装角色规则和 Plugin。没有连接持久化后端也可以创建、切换角色和聊天，但只能使用当前会话，不能跨会话保存记忆。Marketplace 不会自动在你的电脑或手机部署 Python Runtime。导入权限取决于账号和工作区。

## 2. Agent 对话中自动安装

把下面这句话发给有仓库、文件和命令执行权限的 Codex、Hermes、AstrBot 管理 Agent 或其他 Agent：

> 安装这个项目：https://github.com/luoyi0000000/agentcosplay

Agent 会读取安装说明，安装完整 Runtime、连接当前宿主、检查持久记忆，再带你创建角色。只有聊天权限的机器人需要其管理者完成安装。

## 开始聊天

> 扮演林舟，一个安静、可靠的灯塔守望者。今天有点累，陪我聊会儿。

也可以创建原创角色、指定 IP 人物、导入角色，或进入 OOC 修改设定。语气随人物和关系自然变化；不会因为“沉浸感”编造你们的共同经历。

主动联系默认关闭，可按角色开启并设置免打扰。普通日常模拟不会擅自制造事故、关系突变或现实事件。

## 数据在哪里

完整安装的数据存放在 **Runtime 宿主的本地用户数据目录**。宿主可以是你的电脑或自有服务器。Hermes、AstrBot 等 Gateway 可连接同一个 Runtime，让不同设备使用同一角色与同一份数据；无需作者云服务，也不默认云同步。卸载程序保留人物数据。

导出默认不含私人记忆和 Companion 活动；显式选择后可以携带角色记忆，但真实用户记忆始终排除。

[安装与维护](INSTALL.md) · [Agent 安装入口](skills.md) · [宿主适配](docs/adapters.md) · [开发与验收](docs/development.md)
