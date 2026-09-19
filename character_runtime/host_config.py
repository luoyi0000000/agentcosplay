"""Merge native host config without replacing other servers or printing secrets."""

import json
import sys
from typing import Any

import tomlkit
import yaml  # type: ignore[import-untyped]


def edit_config(host: str, text: str, server: dict[str, Any], *, remove: bool = False) -> str:
    if host == "codex":
        config = tomlkit.parse(text)
    elif host == "hermes":
        config = yaml.safe_load(text) if text.strip() else {}
    elif host == "astrbot":
        config = json.loads(text) if text.strip() else {}
    else:
        raise ValueError("Unsupported host")
    if not isinstance(config, dict):
        raise ValueError("Host config must be a mapping")
    key = "mcpServers" if host == "astrbot" else "mcp_servers"
    servers = config.setdefault(key, {})
    if not isinstance(servers, dict):
        raise ValueError("Host MCP config must be a mapping")
    existing = servers.get("agentcosplay")
    if existing is not None and existing != server:
        raise ValueError("Existing agentcosplay server differs; refusing to overwrite")
    if remove:
        if existing is None:
            return text
        del servers["agentcosplay"]
    else:
        if existing is not None:
            return text
        servers["agentcosplay"] = server
    if host == "codex":
        return tomlkit.dumps(config)
    if host == "hermes":
        return str(yaml.safe_dump(config, allow_unicode=True, sort_keys=False))
    return json.dumps(config, ensure_ascii=False, indent=2) + "\n"


if __name__ == "__main__":
    request = json.load(sys.stdin)
    try:
        print(json.dumps({"text": edit_config(**request)}, ensure_ascii=False))
    except (ValueError, yaml.YAMLError):
        # Do not echo parser errors: they can contain source lines with credentials.
        print("Invalid or conflicting host configuration", file=sys.stderr)
        raise SystemExit(1) from None
