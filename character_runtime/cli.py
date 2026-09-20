"""Cross-platform local entry point. No networking occurs unless serve HTTP is requested."""

import argparse
import asyncio
import json
import os
import time
from pathlib import Path

import uvicorn

from .paths import runtime_data_dir
from .providers import JSONFileProvider, Kind
from .runtime import Runtime
from .scheduler import tick
from .server import build_server, http_app
from .storage import SQLiteStorage


def main() -> None:
    parser = argparse.ArgumentParser(description="agentcosplay")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    schedule = sub.add_parser(
        "scheduler", help="Emit intents to a trusted host; never send messages"
    )
    schedule.add_argument("--character", action="append", required=True)
    schedule.add_argument("--once", action="store_true")
    schedule.add_argument("--interval", type=int, default=300)
    for command in (serve, schedule):
        command.add_argument("--provider-file", action="append", default=[], metavar="KIND=PATH")
    sub.add_parser("doctor", help="Verify storage and real MCP discovery without user records")
    args = parser.parse_args()
    data = runtime_data_dir()
    if args.command == "doctor":
        from .health import check

        print(json.dumps(asyncio.run(check(data)), ensure_ascii=False))
        return
    storage = SQLiteStorage(data / "runtime.sqlite3")
    try:
        owner = os.environ.get("CHARACTER_OWNER", "local-user")
        providers = []
        for value in args.provider_file:
            kind, separator, path = value.partition("=")
            if not separator or kind not in ("time", "weather", "schedule", "location"):
                parser.error("Provider must be time/weather/schedule/location=PATH")
            from typing import cast

            providers.append(JSONFileProvider(Path(path).expanduser(), cast(Kind, kind)))
        if args.command == "scheduler":
            if args.interval < 60:
                parser.error("Scheduler interval must be at least 60 seconds")
            rt = Runtime(storage, owner, providers=providers)
            while True:
                for decision in tick(rt, args.character):
                    print(json.dumps(decision, ensure_ascii=False), flush=True)
                if args.once:
                    return
                time.sleep(args.interval)
        if args.transport == "stdio":
            build_server(storage, local_owner=owner, providers=tuple(providers)).run(
                transport="stdio"
            )
        else:
            host = os.environ.get("CHARACTER_HOST", "127.0.0.1")
            port = int(os.environ.get("CHARACTER_PORT", "8765"))
            issuer = os.environ.get("CHARACTER_OAUTH_ISSUER")
            if host not in ("127.0.0.1", "localhost") and not issuer:
                raise ValueError("Non-loopback HTTP requires a configured OAuth provider")
            server = build_server(
                storage,
                local_owner=owner,
                token=os.environ.get("CHARACTER_TOKEN"),
                issuer=issuer,
                audience=os.environ.get("CHARACTER_OAUTH_AUDIENCE"),
                jwks_url=os.environ.get("CHARACTER_OAUTH_JWKS_URL"),
                resource=os.environ.get("CHARACTER_RESOURCE_URL", f"http://{host}:{port}/mcp"),
                providers=tuple(providers),
            )
            uvicorn.run(
                http_app(server, host, port),
                host=host,
                port=port,
                access_log=False,
                log_level="critical",
            )
    finally:
        storage.close()


if __name__ == "__main__":
    main()
