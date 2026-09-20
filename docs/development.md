# 本地开发与验收

Python 3.11+，使用项目锁文件；不更改真实宿主配置，不自动发布。

```bash
uv sync --locked
uv run --locked python -m unittest discover -s tests -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy character_runtime
uv build --build-constraints build-constraints.txt
uv run --locked python -m scripts.check_installation
```

最后一项下载依赖并在中文、空格路径的临时目录安装。覆盖 install/doctor、真实 stdio 进程重连、源码移动、同一 HTTP 进程两个客户端双向读写、update/rollback/uninstall/reinstall。临时角色和配置自动删除；这不是 Hermes/AstrBot 应用实际聊天验收。

单测包含新旧角色契约、隔离、真实记忆确认、遗忘派生数据、Companion、Provider 过期、离线模拟、幂等回合、调度保留/回执/中断、安装文件占用与恢复。Skill 首用还需要代理场景复核，不能用静态字符串测试冒充实际 UI。

.github/workflows/verify.yml 为 macOS/Windows/Linux 配置同样命令；未上传时该工作流未执行。Windows 依赖用户 ACL，POSIX 权限/符号链接测试只在适用系统执行；跨平台路径与文件占用恢复测试在所有平台运行。

## 契约与分发

`python -m scripts.schemas` 生成公开契约。旧 Definition/State/Memory/Package V1 不变；新增 CompanionState/Observation V1、可选 Companion Package V2。Schema 漂移由测试检测。

正式安装器只有 install.py；Marketplace 直接消费 plugins/agentcosplay，不再维护单独 Skill ZIP 或 Bash 下载器。wheel 包含 Runtime，源码分发包含完整 Plugin/安装器/契约；普通用户从仓库安装。旧 character-runtime CLI 别名保留，避免破坏已有启动配置。

.venv 用于开发复现；dist、构建缓存、临时数据库不入 Git。清理只针对本次生成且可再生的路径，不能使用 git clean -fdx 删除未知用户文件。

版本变更同步 pyproject.toml、__init__.py、两个 plugin manifest 和 uv.lock。作者未选择 LICENSE，本轮不代选。
