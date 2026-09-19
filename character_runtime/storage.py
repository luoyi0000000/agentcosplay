"""Transactional SQLite storage for JSON-shaped runtime records."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import threading
import time
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import Any, Protocol, cast


class Storage(Protocol):
    def transaction(self) -> AbstractContextManager[None]: ...

    def get(self, owner: str, collection: str, key: str) -> dict[str, Any] | None: ...

    def put(self, owner: str, collection: str, key: str, value: dict[str, Any]) -> None: ...

    def list(self, owner: str, collection: str) -> list[dict[str, Any]]: ...

    def delete(self, owner: str, collection: str, key: str) -> None: ...

    def close(self) -> None: ...


class SQLiteStorage:
    """A single-connection SQLite record store safe for shared-thread use."""

    SCHEMA_VERSION = 1

    def __init__(self, path: Path | str) -> None:
        self._lock = threading.RLock()
        self._transaction_depth = 0
        if str(path) != ":memory:":
            Path(path).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            try:
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
            for suffix in ("", "-wal", "-shm"):
                try:
                    mode = Path(str(path) + suffix).lstat().st_mode
                except FileNotFoundError:
                    continue
                if stat.S_ISLNK(mode) or (os.name == "posix" and mode & 0o077):
                    raise PermissionError(
                        "Database and journal files must be private, non-symlink files; "
                        "restrict existing files to owner access before opening"
                    )
        self._connection = sqlite3.connect(path, timeout=5, check_same_thread=False)
        try:
            # Refuse a future database before changing its journal mode; migration rechecks below.
            version = self._connection.execute("PRAGMA user_version").fetchone()[0]
            if version > self.SCHEMA_VERSION:
                raise RuntimeError("Database schema is newer than supported")
            deadline = time.monotonic() + 5
            while True:
                try:
                    self._connection.execute("PRAGMA journal_mode = WAL")
                    break
                except sqlite3.OperationalError as error:
                    # SQLite can skip busy_timeout while upgrading the journal mode lock.
                    if (
                        error.sqlite_errorcode != sqlite3.SQLITE_BUSY
                        or time.monotonic() >= deadline
                    ):
                        raise
                    time.sleep(0.01)
            self._connection.execute("PRAGMA secure_delete = ON")
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA busy_timeout = 5000")
            with self.transaction():
                row = self._connection.execute("PRAGMA user_version").fetchone()
                assert row is not None
                version = int(row[0])
                if version > self.SCHEMA_VERSION:
                    raise RuntimeError(
                        f"database schema {version} is newer than supported {self.SCHEMA_VERSION}"
                    )
                if version == 0:
                    self._connection.execute(
                        """
                        CREATE TABLE records (
                            owner TEXT NOT NULL,
                            collection TEXT NOT NULL,
                            key TEXT NOT NULL,
                            value TEXT NOT NULL,
                            PRIMARY KEY (owner, collection, key)
                        )
                        """
                    )
                    self._connection.execute(f"PRAGMA user_version = {self.SCHEMA_VERSION}")
        except BaseException:
            self._connection.close()
            raise

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._lock:
            depth = self._transaction_depth
            savepoint = f"storage_{depth}"
            if depth == 0:
                self._connection.execute("BEGIN IMMEDIATE")
            else:
                self._connection.execute(f"SAVEPOINT {savepoint}")
            self._transaction_depth = depth + 1
            try:
                yield
                if depth == 0:
                    self._connection.commit()
                else:
                    self._connection.execute(f"RELEASE {savepoint}")
            except BaseException:
                if depth == 0:
                    self._connection.rollback()
                else:
                    self._connection.execute(f"ROLLBACK TO {savepoint}")
                    self._connection.execute(f"RELEASE {savepoint}")
                raise
            finally:
                self._transaction_depth = depth

    def get(self, owner: str, collection: str, key: str) -> dict[str, Any] | None:
        self._validate(owner, collection, key)
        with self._lock:
            row = self._connection.execute(
                "SELECT value FROM records WHERE owner = ? AND collection = ? AND key = ?",
                (owner, collection, key),
            ).fetchone()
        return None if row is None else self._decode(row[0])

    def put(self, owner: str, collection: str, key: str, value: dict[str, Any]) -> None:
        self._validate(owner, collection, key)
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO records (owner, collection, key, value) VALUES (?, ?, ?, ?)
                ON CONFLICT (owner, collection, key) DO UPDATE SET value = excluded.value
                """,
                (owner, collection, key, encoded),
            )
            if self._transaction_depth == 0:
                self._connection.commit()

    def list(self, owner: str, collection: str) -> list[dict[str, Any]]:
        self._validate(owner, collection)
        with self._lock:
            rows = self._connection.execute(
                "SELECT value FROM records WHERE owner = ? AND collection = ?",
                (owner, collection),
            ).fetchall()
        return [self._decode(row[0]) for row in rows]

    def delete(self, owner: str, collection: str, key: str) -> None:
        self._validate(owner, collection, key)
        with self._lock:
            self._connection.execute(
                "DELETE FROM records WHERE owner = ? AND collection = ? AND key = ?",
                (owner, collection, key),
            )
            if self._transaction_depth == 0:
                self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    @staticmethod
    def _validate(*identifiers: str) -> None:
        if any(not identifier for identifier in identifiers):
            raise ValueError("owner, collection, and key must not be empty")

    @staticmethod
    def _decode(value: str) -> dict[str, Any]:
        decoded = json.loads(value)
        if not isinstance(decoded, dict):
            raise RuntimeError("stored record is not a JSON object")
        return cast(dict[str, Any], decoded)
