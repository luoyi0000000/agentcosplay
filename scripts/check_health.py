"""Exercise real doctor staging and hostile diagnostic redaction.
验证真实 doctor 阶段与恶意诊断脱敏。
"""

import asyncio
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import install
from character_runtime.health import check
from character_runtime.health_diagnostics import HealthFailure, health_stage


def main():
    try:
        with health_stage("health.mcp-initialize"):
            raise ExceptionGroup(
                "private", [HealthFailure("health.stdio-spawn", OSError("private"))]
            )
    except HealthFailure as error:
        assert error.envelope() == {
            "ok": False,
            "stage": "health.stdio-spawn",
            "exception_type": "OSError",
        }
    with TemporaryDirectory() as directory:
        database = Path(directory) / "runtime.sqlite3"
        sqlite3.connect(database).close()
        database.chmod(0o600)
        source = sqlite3.connect(database)
        try:
            with (
                patch("character_runtime.health.sqlite3.connect", return_value=source),
                patch("character_runtime.health.os.open", side_effect=OSError("private-path")),
            ):
                try:
                    asyncio.run(check(Path(directory)))
                except HealthFailure:
                    pass
            try:
                source.execute("SELECT 1")
            except sqlite3.ProgrammingError:
                pass
            else:
                raise AssertionError("Snapshot failure leaked the source connection")
        finally:
            source.close()
        database.unlink()
        with patch("character_runtime.health.SQLiteStorage", side_effect=OSError("private-data")):
            try:
                asyncio.run(check(Path(directory)))
            except HealthFailure as error:
                assert error.envelope() == {
                    "ok": False,
                    "stage": "health.storage-check",
                    "exception_type": "OSError",
                }
            else:
                raise AssertionError("Missing health stage")
    for metadata in (
        {"ok": False, "stage": "health.stdio-spawn", "exception_type": "FileNotFoundError"},
        {"ok": False, "stage": "private-path", "exception_type": "private-secret"},
        {"ok": False, "stage": ["private-path"], "exception_type": {}},
    ):
        result = subprocess.CompletedProcess([], 1, json.dumps(metadata).encode(), b"private-data")
        with patch("install.subprocess.run", return_value=result):
            try:
                install.run([sys.executable], stage="health")
            except RuntimeError as error:
                assert "private" not in str(error)
                if metadata["stage"] == "health.stdio-spawn":
                    assert "health.stdio-spawn" in str(error) and "FileNotFoundError" in str(error)
            else:
                raise AssertionError("Failed health reported success")
    print("PASS health stages and bounded diagnostic privacy")


if __name__ == "__main__":
    main()
