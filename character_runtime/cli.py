"""Cross-platform local entry point. No networking occurs unless serve HTTP is requested."""

import argparse
import os
from pathlib import Path

import uvicorn

from .server import build_server, http_app
from .storage import SQLiteStorage


def main() -> None:
    parser = argparse.ArgumentParser(description="Character Runtime")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    args = parser.parse_args()
    data = Path(os.environ.get("CHARACTER_DATA_DIR", "data"))
    storage = SQLiteStorage(data / "runtime.sqlite3")
    try:
        owner = os.environ.get("CHARACTER_OWNER", "local-user")
        if args.transport == "stdio":
            build_server(storage, local_owner=owner).run(transport="stdio")
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
