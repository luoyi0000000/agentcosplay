"""Check that native plugin imports and metadata cannot pull in the Runtime.
检查原生插件导入与元数据不能引入 Runtime 服务依赖。
"""

import ast
import importlib.abc
import importlib.metadata
import importlib.util
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert metadata["project"]["dependencies"] == [], "Plugin must use Host-owned dependencies"
    # Host SDKs may themselves import server libraries; only our dependency edge is forbidden.
    # 宿主 SDK 自身可能导入服务库；此处禁止的是本项目越过 Runtime 边界。
    sdk = importlib.import_module("mcp")
    importlib.import_module("mcp.client.streamable_http")
    importlib.import_module("httpx2" if hasattr(sdk, "Client") else "httpx")
    importlib.import_module("pydantic")

    forbidden = {"character_runtime", "sqlite3", "uvicorn", "jwt"}
    for source in (ROOT / "agentcosplay_host").glob("*.py"):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            assert not any(set(name.split(".")) & forbidden for name in names), source.name
    before = {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()}

    class Boundary(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if any(part in forbidden for part in fullname.split(".")):
                raise AssertionError("Host SDK imported a Runtime dependency: " + fullname)

    guard = Boundary()
    sys.meta_path.insert(0, guard)
    try:
        spec = importlib.util.spec_from_file_location(
            "isolated_agentcosplay_plugin",
            ROOT / "__init__.py",
            submodule_search_locations=[str(ROOT)],
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        assert callable(module.register)
    finally:
        sys.meta_path.remove(guard)
    assert before == {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()}
    print("PASS native import boundary, empty Host requirements and unchanged installed versions")


if __name__ == "__main__":
    main()
