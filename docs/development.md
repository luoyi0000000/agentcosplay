# 本地开发与维护

Python 3.11+，使用锁文件；维护检查在隔离临时目录运行，不修改真实宿主配置。

```bash
uv sync --locked
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy character_runtime
uv run --locked python -m scripts.check_plugin
uv run --locked python -m scripts.schemas --check
uv run --locked python -m scripts.check_migration
uv run --locked python -m scripts.check_runtime
uv run --locked python -m scripts.check_scope
uv run --locked python -m scripts.check_expression
uv run --locked python -m scripts.check_conversation
uv run --locked python -m scripts.check_hermes
uv run --locked python -m scripts.check_lifecycle
uv run --locked python -m scripts.check_affect
uv build --build-constraints build-constraints.txt
uv run --locked python -m scripts.check_installation
```

安装 smoke 使用真实子进程和 MCP 协议：依赖/启动、数据库、工具发现、合成人物与会话、提交、重连、召回、源码移动、配置合并、更新、回滚、卸载及重装保留数据。临时人物和配置随临时目录一起清理。

`.github/workflows/verify.yml` 在三个 runner 上执行同一组命令。锁文件必须能被 TOML 解析并满足 `--locked`，不能通过删文件、解除锁定或忽略失败绕过问题。

Installer subprocess JSON uses ASCII escapes because isolated Python (`-I`) ignores `PYTHONUTF8`; decoded configuration and character data remain Unicode. Diagnostics expose only an allowlisted stage, error category and exit code, never raw dependency stderr. The installation check also exercises CP1252 pipes and interrupted journal recovery. These checks do not replace a real Windows run.

安装子进程 JSON 使用 ASCII 转义，因为隔离 Python（`-I`）会忽略 `PYTHONUTF8`；解码后的配置和角色数据仍完整保留中文。错误诊断仅输出白名单阶段、类别和退出码，不回显依赖工具的 stderr。安装验收覆盖 CP1252 管道与中断事务恢复；这些检查不能替代真实 Windows 验证。

## 契约与分发

`python -m scripts.schemas` 更新公开 Schema；`--check` 检查它们与当前模型一致且不写文件。插件维护检查核对两份 manifest、唯一 Skill、引用路径、版本、当前发布 Logo 摘要和 PNG 完整性。摘要用于发现传输损坏，不要求与历史 P1 原始文件逐字节一致；后续经确认的资源调整应同步更新发布摘要。

完整安装入口为 `install.py`；Marketplace 消费 `plugins/agentcosplay`。wheel 包含 Runtime；源码分发包含完整 Plugin、安装器、契约和标准 MIT LICENSE。保留 `character-runtime` CLI 别名供已有启动配置使用。

`.venv` 用于开发复现；dist、缓存、临时数据库不入 Git。只清理本次生成且可再生的文件，不删除未知用户数据。

版本变更同步 `pyproject.toml`、`character_runtime/__init__.py`、两份 OpenAI plugin manifest、Hermes `plugin.yaml` 和 `uv.lock`。

Hermes checks exercise synthetic official-hook contracts plus real Runtime/MCP transport in `check_scope`; they do not prove a live Hermes model/platform installation. The official-hooks adapter deliberately has no final delivery acknowledgement capability.

Hermes 检查覆盖合成官方钩子契约，`check_scope` 使用真实 Runtime/MCP 传输；这些不代表已完成真实 Hermes 模型和平台验收。官方钩子 Adapter 不支持最终投递确认。

上传仅在用户明确批准后执行。API 传输必须逐个比较远端 blob SHA 与本地 Git 对象 SHA，再比较完整 tree；只有分支指针更新成功不足以证明内容完整。大文件不得经过可能截断的终端展示输出。读取远端后再次验证锁文件和品牌图片。
