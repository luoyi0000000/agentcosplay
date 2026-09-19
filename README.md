# Character Runtime

平台无关的 AI Character Runtime。它把**角色定义、角色状态、长期记忆、关系成长和运行规则**从具体模型与客户端中分离出来，让同一个角色可以在 Codex、ChatGPT、Hermes、AstrBot 或自建 Agent 中持续运行。

当前正式版本：`1.0.0`。项目使用 Python 3.11+、SQLite 和官方 MCP Python SDK；不绑定模型供应商，不要求模型 API Key，也不把角色数据写进宿主客户端的专有格式。

## Agent 一键安装

在 Agent 的项目终端执行以下命令：

```bash
set -euo pipefail
git clone https://github.com/luoyi0000000/agentcosplay.git character-runtime
cd character-runtime
command -v python3 >/dev/null || { echo "需要 Python 3.11+" >&2; exit 1; }
python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("需要 Python 3.11+")
PY
command -v uv >/dev/null || { echo "未找到 uv：https://docs.astral.sh/uv/getting-started/installation/" >&2; exit 1; }
uv sync --locked --python 3.11
uv run --locked python -m unittest discover -s tests -q
```

启动本地 MCP stdio 服务：

```bash
cd character-runtime
export CHARACTER_OWNER="local-user"
export CHARACTER_DATA_DIR="$PWD/private-data"
uv run --locked python -m character_runtime serve --transport stdio
```

给 Agent 的 MCP 配置（替换为绝对路径）：

```json
{
  "command": "uv",
  "args": ["--directory", "/absolute/path/to/character-runtime", "run", "--locked", "python", "-m", "character_runtime", "serve", "--transport", "stdio"],
  "env": {
    "CHARACTER_OWNER": "local-user",
    "CHARACTER_DATA_DIR": "/absolute/path/to/private-character-data"
  }
}
```

安装 Skill 后，对 Agent 说：“创建一个安静、可靠的灯塔守望者，叫林舟；今后这个对话使用他。”之后可说“进入 OOC”“删除这条记忆”“导出角色，不含记忆”“本次任务用中性模式，完成后恢复”。

## 远程 HTTP 接入

移动端或远程 Agent 必须访问认证后的 HTTPS MCP 服务。生产环境不能使用示例 token，也不能把 SQLite 文件暴露给客户端：

```bash
export CHARACTER_HOST="0.0.0.0"
export CHARACTER_PORT="8765"
export CHARACTER_OAUTH_ISSUER="https://identity.example.com"
export CHARACTER_OAUTH_AUDIENCE="https://runtime.example.com/mcp"
export CHARACTER_OAUTH_JWKS_URL="https://identity.example.com/.well-known/jwks.json"
export CHARACTER_RESOURCE_URL="https://runtime.example.com/mcp"
uv run --locked python -m character_runtime serve --transport http
```

认证、所有者隔离和 Host 校验见 [适配文档](docs/adapters.md)。

## 项目结构

```text
character_runtime/          核心运行时、存储、MCP、认证和 CLI
skills/character-runtime/   Agent 角色工作流 Skill
adapters/                   Codex、Hermes、AstrBot 配置示例
schemas/                    CharacterDefinition/State/Memory/Package v1 契约
examples/                   可导入的原创角色示例
tests/                      单元、协议、并发、权限和隐私测试
docs/                       设计、适配、审计、开发和演示文档
plugin.json                 Plugin 分发元数据
```

宿主是 Adapter，不是核心。角色数据按所有者和角色 ID 隔离；默认导出不包含记忆；现实用户事实不能从角色扮演内容自动提升；成长需要明确证据。MCP 工具不会强制模型每轮调用，因此宿主必须遵循 Skill 工作流。

## 验证、演示与构建

```bash
uv run --locked python -m unittest discover -s tests -v
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy character_runtime
uv run --locked python -m character_runtime.demo
uv run --locked python -m scripts.schemas
uv build --build-constraints build-constraints.txt
```

- [系统设计](docs/design.md)
- [数据、记忆与隐私契约](docs/reference.md)
- [平台适配与认证](docs/adapters.md)
- [本地演示记录](docs/demo.md)
- [安全审计报告](docs/audit.md)
- [开发与发布流程](docs/development.md)

## 发布边界

仓库不包含 `.env`、token、数据库、构建目录或缓存。远程部署、OAuth 注册、域名和公网服务不由本仓库自动创建；请在自己的基础设施中完成并审计后再启用。
