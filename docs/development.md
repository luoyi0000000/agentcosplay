# 开发、测试与构建

## 环境与命令

Python >=3.11，uv；不需要 Node、Homebrew、Bash 或 WSL。macOS/Windows/Linux 使用同样的 Python/uv 命令；路径用 pathlib。此版本实际在 macOS arm64 / Python 3.11.15 验证，Windows/Linux 尚未实机验证。

```text
uv sync --locked --python 3.11
uv run --locked python -m unittest discover -s tests -v
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy character_runtime
uv run --locked python -m character_runtime.demo
uv run --locked python -m scripts.schemas
uv build --build-constraints build-constraints.txt
```

运行/开发依赖由 uv.lock 锁定；构建后端及其依赖由 build-constraints.txt 锁定，更新任一依赖需重跑验证。首次安装需下载依赖；后续可使用已缓存依赖。无自动上传步骤。

`.venv` 保留给本地复现，`dist` 保留 wheel/sdist，均不入 Git。测试使用 TemporaryDirectory 自动清理数据库。不要用 `git clean -fdx` 清理可能包含用户数据的工作区。

## 测试范围

stdlib unittest 覆盖类型约束、所有者与角色隔离、来源优先级、session 路由、OOC/任务恢复、过期/遗忘/提升、显式共享、事务回滚、成长证据/限速、导入完整性、导出隐私、数据库重启、中文路径、并发 revision/事务。实际 SDK Client 测试 stdio 和 ASGI Streamable HTTP，不用假 MCP 接口。HTTP 测试校验未认证拒绝、不可伪造 owner 与 Host 保护；JWT 用真实 RSA 签名，JWKS 获取以本地 key 代替。

独立演示还启动/关闭两次真正的 stdio 服务进程。HTTP 的网络监听由本地回环检查补充，远程 OAuth 授权流程不以单元测试冒充。

## Schema / Plugin / Skill

`python -m scripts.schemas` 根据 Pydantic 重新生成四份公开契约；Schema 漂移测试保证契约和代码一致。示例角色卡只用合成身份。

Plugin 根目录为当前 portable manifest；`.codex-plugin/plugin.json` 提供兼容元数据。Skill 仅调用后端工具，不依赖 shell 或桌面。此环境已使用官方 Plugin Creator 和 Skill Creator 自带验证脚本，报告记录结果；脚本属于开发者环境，不作为本仓库运行依赖。PyYAML 是它们需要的开发依赖。

## 变更流程

先给角色隔离/记忆/授权等行为加失败测试，再改代码；运行相关测试后运行完整检查。修改模型需同步 schemas 和本契约说明。未知版本必须拒绝，增加迁移时保留旧版本回归样本（仍用合成数据）。

本项目暂未选择开源许可证，不代表授权第三方公开分发。仓库提交只包含源码、契约、测试和文档；不提交本地数据、凭据、缓存或构建产物。正式部署前仍需单独完成 OAuth、基础设施和公网安全审计。
