# 安装 agentcosplay

这里安装完整 Runtime、依赖、当前宿主配置和角色 Skill。人工安装与 Agent 自动安装使用同一个仓库、安装器和数据格式。仅下载 Skill 不满足完整安装。

## 环境与首次安装

- Python 3.11 或更新版本（可运行 venv）、Git、依赖下载网络。
- macOS / Linux / Windows；Windows 命令中的 `python3` 换为 `py -3`。
- 已能正常聊天的 Codex、Hermes 或 AstrBot。模型由宿主提供，不需要另交 API Key。
- 在真正运行 Agent 的机器和用户身份下操作。安装程序和角色数据应位于本地持久磁盘，不放共享网络盘、源码或 Git 目录。

```bash
git clone https://github.com/luoyi0000000/agentcosplay.git
cd agentcosplay
python3 install.py --host codex
python3 install.py doctor
```

安装器在独立版本目录构建锁定依赖并进行真实 MCP 协议检查，然后合并宿主原生配置。已有 uv 时复用；没有时仅在安装目录创建 bootstrap 环境安装 uv，不使用全局 pip。配置及恢复备份在 POSIX 上使用私有权限；Windows 依赖当前用户目录的 ACL，不要选公共目录。

选择宿主：

| 宿主 | 参数 | 修改的原生配置 |
|---|---|---|
| Codex | `--host codex` | `CODEX_HOME/config.toml`，默认 `~/.codex` |
| Hermes | `--host hermes` | `HERMES_HOME/config.yaml`，默认 `~/.hermes` |
| AstrBot | `--host astrbot --host-dir /实际持久数据目录` | `mcp_server.json` 的 `mcpServers` |
| 通用执行宿主 | `--host generic` | 只安装 Runtime，接入现有 MCP 客户端后验收 |

Codex/Hermes 的 `--host-dir` 可明确指定 profile 根目录。保留原有其他服务，不覆写同名的不同配置或用户修改过的 Skill。Hermes YAML 重写会保留配置值，但可能失去注释；原文件包含在私密恢复备份中。修改配置前停止宿主，避免它同时写文件；安装完成后重新启动/加载。

AstrBot 的目录必须从实际部署配置取得，不能直接照抄示例。Docker 部署需在容器内执行安装，程序和数据都放在容器可见的持久卷，宿主提供的绝对 Python 路径也必须在容器内可执行。不要把 Runtime 装进仅供工具执行的临时沙盒。Skill 位于所选宿主根目录的 `skills/agentcosplay`；人格限制 Skills 时把它加入允许列表。

省略 `--host` 时只自动选择唯一已存在的 Codex/Hermes 目录；多个候选会拒绝猜测，没有候选则安装通用 Runtime。Agent 应根据当前宿主明确选择参数。

## 默认目录与数据保护

| 系统 | 基础目录 |
|---|---|
| macOS | `~/Library/Application Support/agentcosplay` |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/agentcosplay` |
| Windows | `%LOCALAPPDATA%/agentcosplay` |

基础目录下：`runtime/` 保存程序、版本、安装记录和私密恢复备份；`characters/runtime.sqlite3` 保存人物定义、状态、记忆、关系和成长。两者彼此独立。

可用 `--install-root /绝对程序目录 --data-dir /绝对人物目录` 自定义；后续命令须使用同一个 `--install-root`。安装器拒绝目录重叠、Git 内的人物数据和可能携带凭据的宿主配置。删除下载的源码不会删除已安装程序或人物数据。

`--owner` 默认 `local-user`。它是单用户本地身份，不是登录系统。更新不能暗中更换身份或数据路径。多人机器人不能把不同人的会话全部映射到此身份；使用宿主权限限制为同一授权用户，或配置高级 OAuth 身份隔离。

旧版直接启动产生的 `./data` **不会自动迁移或删除**。先停止旧进程，用角色导出/导入迁移；完整机器备份可在停止所有连接后备份整个数据库目录。不要只复制正在写入的 SQLite 主文件而漏掉 WAL。

## 验证安装

`python3 install.py doctor` 应输出 `ok:true`，并显示版本、数据路径和检查项。它验证真实数据库可打开、宿主配置/Skill 未缺失或改写，并在临时数据库执行真实 stdio 工具发现、证据提交、跨会话隔离、遗忘重试和上下文校验；不会向你的角色库写测试人物。

隔离合成验收运行 `python -m scripts.check_installation`，临时库自动清理，不在用户库制造测试人物。随后重新加载宿主，发现 agentcosplay 工具和 Skill，按用户选择创建真实角色并验证一次 context/commit/重新连接召回。**doctor 通过不等于宿主已经重新加载**；对话、QQ 路由和人格启用还需实际宿主验收。

## 多个入口连接同一个 Runtime

一个 Hermes/AstrBot Gateway 接入手机和电脑时，默认 stdio 已能复用它的本地角色库。若同一机器上的 Hermes、AstrBot 两个 Gateway 要连接**同一个进程**，先完整安装一次，然后注册共同回环服务：

```bash
python3 install.py connect --host hermes --transport http
python3 install.py connect --host astrbot --host-dir /实际AstrBot数据目录 --transport http
python3 install.py run --transport http
```

第三条在前台运行，保持终端开启；长期常驻用宿主已有进程管理器管理同一启动命令。注册动作不自动启动进程，不创建第二个数据库。`connect` 也可给 Codex 注册 HTTP，或用 `--transport stdio` 切回由宿主拉起进程。

安装器自动生成本机专用随机 token，私密保存并写入对应宿主请求头，终端不会显示 token。默认 `127.0.0.1:8765/mcp`；首次 connect 可用 `--port` 选择其他非特权端口，后续入口须使用相同端口。更新会保留端口和身份。不要提交 host 配置、`http-token`、`installed.json` 或 `backups/` 到 Git。

两个入口选择相同 **character ID / owner**，各自使用不同 session ID，才是同一人物的连续互动。进程重启后状态从同一 SQLite 恢复。不要在另一个目录安装第二份 Runtime 来代替共享。

此快捷配置限于同一网络命名空间。两个 Docker 容器、分离主机或 ChatGPT 云端不能把各自的 localhost 当成同一服务。跨主机走用户自己的受认证 HTTPS/OAuth 入口，见 [高级适配](docs/adapters.md)，不需要作者托管角色云。

## 更新、回滚、卸载

先停止相关宿主及共享 Runtime，避免旧进程继续运行旧代码。源码没有自行修改时：

```bash
git pull --ff-only
python3 install.py update --host codex
python3 install.py doctor
```

若同一安装已绑定多个宿主，会刷新已登记的适配。`--host generic` 可更新已有绑定而不新增宿主。程序先构建并检查新版本，再切换活动版本；失败保留旧版本和数据。重新启动宿主/共享服务才会使用新进程。

```bash
python3 install.py rollback
python3 install.py uninstall
```

rollback 切回上一个已安装版本，并验证它能打开现有数据库；不会把人物数据恢复成旧快照。uninstall 删除本安装登记且未被用户改写的配置项和 Skill，移除版本/缓存/bootstrap，**保留人物数据库、安装记录和私密恢复备份**。用户改写过的文件会导致卸载拒绝，请先自行保留并处理冲突。同样的 install 命令可重新安装并继续使用保留下来的数据。

当前数据库 schema 为 2。首次打开 V1 时，先创建私有 SQLite 备份，再事务迁移。安装预检只验证临时快照，不提前迁移正在使用的数据库；正式启动新 Runtime 时才迁移；原始记录与无法映射内容保留并提示，撤销旧跨角色共享权限。默认导出 V3，仍接受 V1/V2 导入。旧程序不能打开 schema 2，安装回滚会拒绝不兼容的数据版本，不会删除数据库或偷偷恢复旧快照。确需回到旧程序时，由用户停止服务并选择恢复升级前备份；升级后的新数据不会自动反向合并。详见 docs/reference.md。

## 中断恢复与排障

- `pending.json`：检测到未提交的安装事务时，执行 `python3 install.py recover`，再重试原操作。它先校验全部文件，再恢复本次改动；中断后又被用户改过的文件会拒绝自动恢复，保留文件和日志供人工比对。
- 进程强制终止：内核会释放安装锁；`install.lock` 文件保留是正常现象，不需要删除它。仍有安装进程时新安装会拒绝并发写入。安装事务覆盖文件写入与活动版本选择；中断在构建阶段可能留下未启用的版本目录，卸载会清理。
- 同名配置/Skill 冲突：先备份原文件，核对是否属于其他项目或用户版本；不要直接删除整份宿主配置。仅 Skill 旧安装与新版规则不同也会拒绝覆盖。
- 下载或依赖失败：检查 Git/包索引网络、Python 版本、venv 支持和磁盘空间；重试不会清空数据。安装器不打印依赖工具的原始输出，因为其中可能含私有索引凭据。
- doctor 失败：核对安装根、文件权限、配置冲突、数据库版本。不要上传数据库、配置全文或恢复备份到公开 issue。
- 工具不可见：重载宿主，检查 profile 和 Skill 启用列表。HTTP 还要确认共享服务正在运行且端口未占用。
- Windows 文件被占用：先停止宿主再更新/卸载。释放占用后重试原命令；恢复流程保留用户数据。

## 迁移人物

调用 `character_export` 导出带版本的 Character Package，在另一 Runtime 用 `character_import` 导入。默认不带记忆；需要迁移角色经历时显式 opt-in。真实用户记忆不会混入角色包。导入验证 schema 和全部内容后一次性提交，重新分配 ID 并重映射允许的引用，失败不留下半个人物。

新主机继续选择导入后的 character ID。不同安装默认不会自动寻找、复制或同步原数据；备份与迁移是明确操作，日常跨设备访问由 Gateway 完成。

## 陪伴配置与调度

完整字段和维护命令见 [Companion](docs/companion.md)。功能按角色启用；主动联系默认关闭。只安装 Runtime 不会自动替你发送消息，仍需要宿主当前模型和获准 Gateway。

本地旧版 Skill 可能与这次的新规则不同：完整 Runtime 安装器会安全更新它自己登记的文件；未登记或用户手改的文件先报告冲突，不盲目覆盖。
