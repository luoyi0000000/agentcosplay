"""Verify migration and recovery using synthetic data in disposable SQLite databases.

Run: uv run --locked python -m scripts.check_migration
"""

import asyncio
import json
import os
import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

from character_runtime.models import Memory
from character_runtime.operations import Operations
from character_runtime.storage import SQLiteStorage


def scope_migration(root: Path) -> None:
    """Retain legacy private life byte-for-byte; public life starts clean.

    原样保留旧私有生活记录；新公共生活不能继承私有内容或未知字段。
    """
    from character_runtime.models import CharacterDefinition
    from character_runtime.runtime import Runtime

    path = root / "scope-v2.sqlite3"
    store = SQLiteStorage(path)
    runtime = Runtime(store, "owner")
    cid = runtime.characters.create(CharacterDefinition(name="migration")).id
    private = runtime.companion.get(cid).model_dump(mode="json")
    private["life"]["reason"] = "private-calendar-sentinel"
    private["unknown_extension"] = {"keep": [1, 2, 3]}
    store.put("owner", "companion", cid, private)
    store.delete("owner", "character_companion", cid)
    store.close()
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA user_version=2")
    connection.commit()
    original = connection.execute(
        "SELECT value FROM records WHERE collection='companion'"
    ).fetchone()[0]
    rows = sqlite3.connect(path)
    before_rows = rows.execute("SELECT * FROM records ORDER BY owner, collection, key").fetchall()
    rows.close()
    connection.close()
    original_migrate = SQLiteStorage._migrate_scopes

    def interrupted(store, version):
        original_migrate(store, version)
        raise RuntimeError("synthetic interruption after scope migration writes")

    with patch.object(SQLiteStorage, "_migrate_scopes", interrupted):
        rejected(RuntimeError, lambda: SQLiteStorage(path))
    connection = sqlite3.connect(path)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
    assert (
        connection.execute("SELECT * FROM records ORDER BY owner, collection, key").fetchall()
        == before_rows
    )
    connection.close()
    migrated = SQLiteStorage(path)
    try:
        assert migrated.migration_backup is not None, "Scope migration needs a private backup"
        public = migrated.get("owner", "character_companion", cid)
        assert public and public["life"]["reason"] == "" and public["goals"] == []
        assert "private-calendar-sentinel" not in json.dumps(public)
        assert migrated.get("owner", "companion", cid) == private
        assert migrated.get("owner", "migration_original", "v2:companion:" + cid) == {
            "raw_json": original
        }
        assert migrated.get("owner", "migration_warning", "v2:companion:" + cid)
        backup = sqlite3.connect(migrated.migration_backup)
        assert backup.execute("PRAGMA user_version").fetchone()[0] == 2
        assert (
            backup.execute("SELECT value FROM records WHERE collection='companion'").fetchone()[0]
            == original
        )
        backup.close()
    finally:
        migrated.close()
    print("PASS scope migration: private originals, unknown fields, backup, clean public state")


def rejected(error: type[Exception], action: Callable[[], Any]) -> None:
    try:
        action()
    except error:
        return
    raise AssertionError(f"Expected {error.__name__}")


def migration(root: Path) -> None:
    path = root / "legacy.sqlite3"
    legacy = Memory(id="m", owner="owner", character_id="a", content="合成旧记忆").model_dump(
        mode="json"
    )
    legacy.pop("legacy_unverified")
    legacy.update(scope="shared", shared_with=["b"], recipients=["b"])
    state = {"character_id": "a", "known_characters": {"b": "friend"}, "shared_world_id": "w"}
    rows = [
        ("owner", "definition", "a", json.dumps({"id": "a"})),
        ("owner", "memory", "m", json.dumps(legacy)),
        ("owner", "state", "a", json.dumps(state)),
        ("owner", "memory", "broken", "{broken"),
        ("owner", "memory", "invalid", json.dumps({"recipients": ["b"]})),
    ]
    connection = sqlite3.connect(path)
    os.chmod(path, 0o600)
    try:
        connection.execute(
            "CREATE TABLE records(owner TEXT, collection TEXT, key TEXT, value TEXT, "
            "PRIMARY KEY(owner, collection, key))"
        )
        connection.execute("PRAGMA user_version=1")
        connection.executemany("INSERT INTO records VALUES (?, ?, ?, ?)", rows)
        connection.commit()
    finally:
        connection.close()

    from character_runtime.health import check

    preflight = root / "preflight"
    preflight.mkdir()
    original = path.read_bytes()
    (preflight / "runtime.sqlite3").write_bytes(original)
    os.chmod(preflight / "runtime.sqlite3", 0o600)
    asyncio.run(check(preflight))
    assert (preflight / "runtime.sqlite3").read_bytes() == original

    # The failure occurs after migration has already written original/warning records.
    with patch.object(SQLiteStorage, "_index_memory", side_effect=RuntimeError("injected")):
        rejected(RuntimeError, lambda: SQLiteStorage(path))
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute("SELECT * FROM records ORDER BY rowid").fetchall() == rows
        assert not connection.execute(
            "SELECT name FROM sqlite_master WHERE name='memory_index'"
        ).fetchall()
    finally:
        connection.close()

    storage = SQLiteStorage(path)
    try:
        backup = storage.migration_backup
        assert backup is not None
        if os.name == "posix":
            assert backup.stat().st_mode & 0o777 == 0o600
        connection = sqlite3.connect(backup)
        try:
            assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
            assert connection.execute("SELECT * FROM records ORDER BY rowid").fetchall() == rows
        finally:
            connection.close()
        assert storage.get("owner", "migration_original", "memory:m") == legacy
        assert storage.get("owner", "migration_original", "state:a") == state
        assert storage.get("owner", "migration_original", "memory:broken") == {
            "raw_json": "{broken"
        }
        assert storage.get("owner", "migration_original", "memory:invalid") == {"recipients": ["b"]}
        memory = storage.get("owner", "memory", "m")
        migrated_state = storage.get("owner", "state", "a")
        assert memory and memory["legacy_unverified"]
        assert not {"scope", "shared_with", "recipients"} & memory.keys()
        assert (
            migrated_state and not {"known_characters", "shared_world_id"} & migrated_state.keys()
        )
        assert len(storage.list("owner", "migration_warning")) == 5
        for owner, character, count in [("owner", "a", 1), ("owner", "b", 0), ("other", "a", 0)]:
            assert (
                len(
                    storage.memory_candidates(
                        owner,
                        character,
                        "合成旧记忆",
                        session_id=None,
                        real=False,
                        at=datetime.now(UTC),
                    )
                )
                == count
            )
    finally:
        storage.close()
    storage = SQLiteStorage(path)
    try:
        assert storage.migration_backup is None
        connection = sqlite3.connect(path)
        try:
            assert (
                connection.execute("PRAGMA user_version").fetchone()[0]
                == SQLiteStorage.SCHEMA_VERSION
            )
            assert (
                connection.execute(
                    "SELECT value FROM records WHERE collection='memory' AND key='broken'"
                ).fetchone()[0]
                == "{broken"
            )
        finally:
            connection.close()
    finally:
        storage.close()
    print(
        "PASS migration: private backup, originals/warnings, "
        "malformed retention, rollback, isolation"
    )


def operations(root: Path) -> None:
    path = root / "operations.sqlite3"
    stores = [SQLiteStorage(path) for _ in range(6)]
    storage = stores[0]
    try:
        for owner, character in [("owner", "a"), ("owner", "b"), ("other", "a")]:
            storage.put(owner, "definition", character, {"id": character})

        def once(store: SQLiteStorage) -> dict[str, Any]:
            def apply() -> dict[str, Any]:
                counter = store.get("owner", "counter", "n") or {"n": 0}
                counter["n"] += 1
                store.put("owner", "counter", "n", counter)
                return counter

            return Operations(store, "owner", "a").execute(
                "once", {"value": 1}, apply, domain="memory", operation="CREATE"
            )

        with ThreadPoolExecutor(max_workers=len(stores)) as workers:
            assert list(workers.map(once, stores)) == [{"n": 1}] * len(stores)
        assert storage.get("owner", "counter", "n") == {"n": 1}
        assert len(storage.list("owner", "mutation")) == 1
        ops = Operations(storage, "owner", "a")
        rejected(
            ValueError,
            lambda: ops.execute(
                "once", {"value": 2}, lambda: {}, domain="memory", operation="CREATE"
            ),
        )
        for owner, character in [("owner", "b"), ("other", "a")]:
            assert Operations(storage, owner, character).execute(
                "once", {}, lambda: {"isolated": True}, domain="memory", operation="CREATE"
            ) == {"isolated": True}

        target = {"character_id": "a", "revision": 1}
        storage.put("owner", "target", "t", target)
        storage.put("owner", "other_collection", "t", target)

        def consume(grant: dict[str, Any], collection: str = "target") -> None:
            ops.consume_allowlist(grant["id"], "FORGET", ["t"], collection=collection)

        grant = ops.issue_allowlist("target", ["t"], ["FORGET"])
        rejected(ValueError, lambda: consume(grant, "other_collection"))
        for owner, character in [("owner", "b"), ("other", "a")]:
            rejected(
                ValueError,
                lambda: Operations(storage, owner, character).consume_allowlist(
                    grant["id"], "FORGET", ["t"], collection="target"
                ),
            )
        storage.put("owner", "target", "t", {**target, "revision": 2})
        rejected(ValueError, lambda: consume(grant))
        grant = ops.issue_allowlist("target", ["t"], ["FORGET"])

        def fail_mutation() -> dict[str, Any]:
            consume(grant)
            storage.delete("owner", "target", "t")
            raise RuntimeError("injected")

        rejected(
            RuntimeError,
            lambda: ops.execute("rollback", {}, fail_mutation, domain="memory", operation="FORGET"),
        )
        assert storage.get("owner", "target", "t") == {**target, "revision": 2}
        consume(grant)
        rejected(ValueError, lambda: consume(grant))
        assert ops.execute("rollback", {}, lambda: {}, domain="memory", operation="FORGET") == {}
        print(
            "PASS operations: concurrent receipts, digest conflict, "
            "scoped grants, revision, rollback"
        )

        instant = [datetime.now(UTC)]
        ops = Operations(storage, "owner", "a", lambda: instant[0])
        ops.enqueue("safe", "local", {}, retry_safe=True)
        claim = ops.claim("safe", lease_seconds=1)
        assert claim and ops.claim("safe") is None
        ops.enqueue("unsafe", "external", {})
        assert ops.claim("unsafe", lease_seconds=1)
        instant[0] += timedelta(seconds=2)
        recovery = Operations(stores[1], "owner", "a", lambda: instant[0])
        fresh = recovery.claim("safe")
        assert fresh and fresh["claim_id"] != claim["claim_id"] and fresh["attempts"] == 2
        rejected(ValueError, lambda: ops.finish("safe", claim["claim_id"], {}))
        recovery.finish("safe", fresh["claim_id"], {})
        assert recovery.claim("safe") is None
        assert recovery.claim("unsafe") is None
        unsafe = next(
            job for job in storage.list("owner", "job") if job["operation_id"] == "unsafe"
        )
        assert unsafe["status"] == "quarantined" and unsafe["error_code"] == "outcome_unknown"
        assert ops.checkpoint("source", "event1", instant[0])["revision"] == 1
        rejected(ValueError, lambda: ops.checkpoint("source", "event2", instant[0]))
        assert (
            recovery.checkpoint("source", "event2", instant[0], expected_revision=1)["revision"]
            == 2
        )
        print(
            "PASS recovery: safe lease retry, stale claim rejection, "
            "unsafe quarantine, checkpoint CAS"
        )
    finally:
        for store in stores:
            store.close()


def main() -> None:
    with TemporaryDirectory(prefix="agentcosplay-migration-") as temporary:
        root = Path(temporary)
        migration(root)
        scope_migration(root)
        operations(root)


if __name__ == "__main__":
    main()
