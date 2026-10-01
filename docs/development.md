# 本地开发与维护

Python 3.11+，使用锁文件；维护检查在隔离临时目录运行，不修改真实宿主配置。

```bash
uv sync --project runtime --locked
uv run --project runtime --locked ruff check .
uv run --project runtime --locked ruff format --check .
uv run --project runtime --locked mypy --config-file pyproject.toml -p character_runtime -p agentcosplay_host
uv run --project runtime --locked python -m scripts.check_plugin
uv run --project runtime --locked python -m scripts.check_packaging
uv run --project runtime --locked python -m scripts.check_health
uv run --project runtime --locked python -m scripts.check_native_install
uv run --project runtime --locked python -m scripts.schemas --check
uv run --project runtime --locked python -m scripts.check_migration
uv run --project runtime --locked python -m scripts.check_runtime
uv run --project runtime --locked python -m scripts.check_scope
uv run --project runtime --locked python -m scripts.check_expression
uv run --project runtime --locked python -m scripts.check_conversation
uv run --project runtime --locked python -m scripts.check_hermes
uv run --project runtime --locked python -m scripts.check_lifecycle
uv run --project runtime --locked python -m scripts.check_affect
uv build --build-constraints build-constraints.txt
uv build runtime --build-constraints build-constraints.txt
uv run --project runtime --locked python -m scripts.check_installation
```

安装 smoke 使用真实子进程和 MCP 协议：依赖/启动、数据库、工具发现、合成人物与会话、提交、重连、召回、源码移动、配置合并、更新、回滚、卸载及重装保留数据。临时人物和配置随临时目录一起清理。

`.github/workflows/verify.yml` 在三个 runner 上执行同一组命令。锁文件必须能被 TOML 解析并满足 `--locked`，不能通过删文件、解除锁定或忽略失败绕过问题。

Installer subprocess JSON uses ASCII escapes because isolated Python (`-I`) ignores `PYTHONUTF8`; decoded configuration and character data remain Unicode. Diagnostics expose only an allowlisted stage, error category and exit code, never raw dependency stderr. The installation check also exercises CP1252 pipes and interrupted journal recovery. These checks do not replace a real Windows run.

安装子进程 JSON 使用 ASCII 转义，因为隔离 Python（`-I`）会忽略 `PYTHONUTF8`；解码后的配置和角色数据仍完整保留中文。错误诊断仅输出白名单阶段、类别和退出码，不回显依赖工具的 stderr。安装验收覆盖 CP1252 管道与中断事务恢复；这些检查不能替代真实 Windows 验证。

## 契约与分发

`python -m scripts.schemas` 更新公开 Schema；`--check` 检查它们与当前模型一致且不写文件。插件维护检查核对两份 manifest、唯一 Skill、引用路径、版本、当前发布 Logo 摘要和 PNG 完整性。摘要用于发现传输损坏，不要求与历史 P1 原始文件逐字节一致；后续经确认的资源调整应同步更新发布摘要。

完整安装入口为 `install.py`；Marketplace 消费 `plugins/agentcosplay`。根目录仅声明轻量 `agentcosplay-host`，由 Host 提供 MCP/Pydantic/HTTP SDK；`runtime/` 的 `agentcosplay` 包拥有独立锁文件与服务依赖。两个 wheel 分别包含 Host 客户端和 Runtime；完整安装器及插件资产通过同一个 Git 仓库分发。保留 `character-runtime` CLI 别名供已有启动配置使用。

The installer copies Runtime sources, its local Host SDK dependency and static Skill assets, then installs non-editable packages in a release-specific environment. Native plugin entry points are not needed by the service build. Compatibility imports under `character_runtime` remain available to old clients.

安装器只复制 Runtime、其本地 Host SDK 依赖与静态 Skill 资源，在独立发布环境中安装普通包；服务构建不需要原生插件入口。旧客户端仍可使用 `character_runtime` 下的兼容导入路径。开发环境若因系统隐藏文件标志跳过 editable 路径，可在 sync/run 时显式加 `--no-editable`，无需改动系统 Python。

Packaging/orchestration was checked against the [official Hermes plugin guide](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins/) and [installer source](https://github.com/NousResearch/hermes-agent/blob/main/hermes_cli/plugins_cmd_install.py) on 2026-10-01. Root project metadata participates in Host dependency admission; `--no-enable` stages a new plugin without activating it. We retain the repository-root entry with empty dependencies and invoke the official `hermes_cli.main:main` entry point in the explicitly selected Host Python. Doctor runs registration in an empty profile, so credentials are checked on first actual use rather than during registration.

2026-10-01 已核对 Hermes 官方文档与安装源码：根项目元数据参与宿主依赖准入，`--no-enable` 暂存新插件而不激活。项目保留根目录入口与空依赖，通过指定宿主 Python 调用官方入口，避免 PATH 指向另一套 Hermes。Doctor 在空配置中注册，因此凭据校验延迟到首次实际使用。`check_native_install` 验证真实隔离 Runtime 与合成 CLI 边界，覆盖失败清理、依赖基线续接、stdio 回退及原生卸载；不代表真实 Hermes/QQ 验收。

`.venv` 用于开发复现；dist、缓存、临时数据库不入 Git。只清理本次生成且可再生的文件，不删除未知用户数据。

版本变更同步两份 `pyproject.toml`、`runtime/character_runtime/__init__.py`、两份 OpenAI plugin manifest、Hermes `plugin.yaml` 和 `runtime/uv.lock`。

Hermes checks exercise synthetic official-hook contracts plus real Runtime/MCP transport in `check_scope`; they do not prove a live Hermes model/platform installation. The official-hooks adapter deliberately has no final delivery acknowledgement capability.

Hermes 检查覆盖合成官方钩子契约，`check_scope` 使用真实 Runtime/MCP 传输；这些不代表已完成真实 Hermes 模型和平台验收。官方钩子 Adapter 不支持最终投递确认。

上传仅在用户明确批准后执行。API 传输必须逐个比较远端 blob SHA 与本地 Git 对象 SHA，再比较完整 tree；只有分支指针更新成功不足以证明内容完整。大文件不得经过可能截断的终端展示输出。读取远端后再次验证锁文件和品牌图片。

`python -m scripts.check_host_session` verifies persistent session mapping, restart recovery, native ID isolation, scoped tool injection, OOC/switch continuity and explicit rotation/invalidation using synthetic local storage. Run it with the existing Host protocol, scope and native binding checks; synthetic checks do not certify real QQ/Telegram/CLI transports.

该检查使用合成本地存储验证持久映射、重启恢复、原生 ID 隔离、工具权限自动补齐、OOC/切换延续及显式轮换/注销；与已有协议、Scope 和原生绑定检查共同运行，不能冒充真实 QQ/TG/CLI 平台测试。
