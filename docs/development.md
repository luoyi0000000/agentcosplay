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
uv build --build-constraints build-constraints.txt
uv run --locked python -m scripts.check_installation
```

安装 smoke 使用真实子进程和 MCP 协议：依赖/启动、数据库、工具发现、合成人物与会话、提交、重连、召回、源码移动、配置合并、更新、回滚、卸载及重装保留数据。临时人物和配置随临时目录一起清理。

`.github/workflows/verify.yml` 在三个 runner 上执行同一组命令。锁文件必须能被 TOML 解析并满足 `--locked`，不能通过删文件、解除锁定或忽略失败绕过问题。

## 契约与分发

`python -m scripts.schemas` 更新公开 Schema；`--check` 检查它们与当前模型一致且不写文件。插件维护检查核对两份 manifest、唯一 Skill、引用路径、版本、原始 Logo 摘要和 PNG 完整性。

完整安装入口为 `install.py`；Marketplace 消费 `plugins/agentcosplay`。wheel 包含 Runtime；源码分发包含完整 Plugin、安装器、契约和标准 MIT LICENSE。保留 `character-runtime` CLI 别名供已有启动配置使用。

`.venv` 用于开发复现；dist、缓存、临时数据库不入 Git。只清理本次生成且可再生的文件，不删除未知用户数据。

版本变更同步 `pyproject.toml`、`__init__.py`、两份 plugin manifest 和 `uv.lock`。

上传仅在用户明确批准后执行。API 传输必须逐个比较远端 blob SHA 与本地 Git 对象 SHA，再比较完整 tree；只有分支指针更新成功不足以证明内容完整。大文件不得经过可能截断的终端展示输出。读取远端后再次验证锁文件和品牌图片。
