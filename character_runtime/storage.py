"""Transactional SQLite storage for JSON-shaped runtime records.

事务化 SQLite 记录存储；检索通道在排序和数量截断前校验记忆受众。
"""

from __future__ import annotations

import builtins
import json
import os
import sqlite3
import stat
import threading
import time
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import uuid4

from pydantic import ValidationError

from .models import CharacterState, Memory, MemoryScope
from .retrieval import normalize, tokens


def memory_scope_sql(
    alias: str, owner: str, scope: MemoryScope | None
) -> tuple[str, tuple[Any, ...]]:
    """Apply audience authorization before every retrieval lane and LIMIT.

    在所有检索通道与 LIMIT 前检查受众；旧记录只属于 Owner，群聊只读 Endpoint。
    The alias comes only from internal constant call sites, never from user input.
    alias 仅来自内部固定调用点，不能接受用户输入。
    """
    if alias not in {"m", "i"}:
        raise ValueError("Unknown memory index alias")
    scope = (
        MemoryScope.model_validate(scope.model_dump())
        if scope
        else MemoryScope(kind="PARTICIPANT_CHARACTER", participant_id=owner)
    )
    field = "participant_id" if scope.kind == "PARTICIPANT_CHARACTER" else "endpoint_id"
    target = scope.participant_id or scope.endpoint_id
    public_only = (
        " AND json_extract(sr.value,'$.sensitivity')='public' "
        "AND json_extract(sr.value,'$.kind') NOT IN ('real_user','relationship')"
        if scope.kind == "ENDPOINT_CHARACTER"
        else ""
    )
    return (
        "EXISTS (SELECT 1 FROM records sr WHERE sr.collection='memory' "
        f"AND sr.owner={alias}.owner AND sr.key={alias}.key AND "
        "COALESCE(json_extract(sr.value,'$.record_scope.kind'),'PARTICIPANT_CHARACTER')=? "
        f"AND COALESCE(json_extract(sr.value,'$.record_scope.{field}'),sr.owner)=?{public_only})",
        (scope.kind, target),
    )


class Storage(Protocol):
    """Require owner-keyed persistence and scoped retrieval before ranking or limits.

    要求按 Owner 持久化；检索必须在排序和限额前约束作用域。
    """

    def transaction(self) -> AbstractContextManager[None]:
        """Commit as a unit or roll back, preserving nested transaction semantics.

        作为一个单元提交或回滚，保留嵌套事务语义。
        """
        ...

    def get(self, owner: str, collection: str, key: str) -> dict[str, Any] | None:
        """Read one owner-keyed record; turn-level authorization belongs to ScopedStorage.

        读取一个 Owner 记录；回合权限由 ScopedStorage 约束。
        """
        ...

    def put(self, owner: str, collection: str, key: str, value: dict[str, Any]) -> None:
        """Persist an owner-keyed record within the caller's transaction boundary.

        在调用方事务边界内保存 Owner 记录。
        """
        ...

    def list(self, owner: str, collection: str) -> builtins.list[dict[str, Any]]:
        """List one owner's collection; callers must retain character and audience boundaries.

        列出 Owner 的集合；调用方仍须保持角色与受众边界。
        """
        ...

    def delete(self, owner: str, collection: str, key: str) -> None:
        """Delete only the addressed owner record, never another namespace.

        仅删除指定 Owner 的记录，不越过命名空间。
        """
        ...

    def memory_window(
        self,
        owner: str,
        character_id: str,
        *,
        start: datetime | None,
        end: datetime | None,
        session_id: str | None,
        real: bool,
        include_archived: bool,
        semantic_key: str | None,
        kind: str | None,
        limit: int,
        scope: MemoryScope | None = None,
    ) -> builtins.list[dict[str, Any]]:
        """Select time-bounded memories after applying audience scope in SQL.

        先在 SQL 中应用受众范围，再选择时间窗口记忆。
        """
        ...

    def memory_candidates(
        self,
        owner: str,
        character_id: str,
        query: str,
        *,
        session_id: str | None,
        real: bool,
        at: datetime,
        include_archived: bool = False,
        limit: int = 256,
        scope: MemoryScope | None = None,
    ) -> builtins.list[tuple[dict[str, Any], float]]:
        """Union bounded lexical, FTS, recent and important lanes before Python scoring.

        合并有界词法、全文、近期及重要性通道，再进行 Python 排序。
        """
        ...

    def memory_duplicates(
        self,
        owner: str,
        character_id: str,
        content: str,
        kind: str,
        source: str,
        session_id: str | None,
        since: datetime,
        *,
        scope: MemoryScope | None = None,
    ) -> builtins.list[dict[str, Any]]:
        """Find cosmetic duplicates only within the authorized memory audience.

        只在授权受众内查找表面差异的重复记忆。
        """
        ...

    def memory_related(
        self,
        owner: str,
        character_id: str,
        memory_id: str,
        *,
        scope: MemoryScope | None = None,
    ) -> builtins.list[dict[str, Any]]:
        """Find promotion-related records without crossing audience boundaries.

        查找提升关系记录，不跨越受众边界。
        """
        ...

    def memory_stale(
        self,
        owner: str,
        character_id: str,
        before: datetime,
        *,
        scope: MemoryScope | None = None,
    ) -> builtins.list[dict[str, Any]]:
        """Select maintenance candidates within owner, character and audience limits.

        在 Owner、角色和受众限制内选择维护候选。
        """
        ...

    def close(self) -> None:
        """Release the database connection; this does not delete persistent data.

        释放数据库连接，不删除持久数据。
        """
        ...


class SQLiteStorage:
    """A single-connection SQLite record store safe for shared-thread use.

    单连接 SQLite 记录存储，支持共享线程安全访问。
    """

    SCHEMA_VERSION = 5

    def __init__(self, path: Path | str) -> None:
        self._lock = threading.RLock()
        self._transaction_depth = 0
        self.fts_available = False
        self.migration_backup: Path | None = None
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
            if 0 < version < self.SCHEMA_VERSION and str(path) != ":memory:":
                backup = Path(f"{path}.v{version}-backup-{uuid4().hex}.sqlite3")
                descriptor = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(descriptor)
                target = sqlite3.connect(backup)
                try:
                    self._connection.backup(target)
                finally:
                    target.close()
                self.migration_backup = backup
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
                self._setup_memory_index(version < 2)
                self._connection.execute(
                    """CREATE UNIQUE INDEX IF NOT EXISTS raw_event_identity ON records(
                        owner, json_extract(value, '$.character_id'),
                        json_extract(value, '$.source_id'), json_extract(value, '$.source_event_id')
                    ) WHERE collection = 'raw_event'"""
                )
                self._connection.execute(
                    """CREATE UNIQUE INDEX IF NOT EXISTS active_fact_identity ON records(
                        owner, json_extract(value, '$.character_id'),
                        json_extract(value, '$.subject'), json_extract(value, '$.semantic_key')
                    ) WHERE collection = 'fact' AND json_extract(value, '$.validity') = 'active'"""
                )
                if version < 3:
                    self._migrate_scopes(version)
                if 0 < version < 5:
                    self._archive_legacy_mood(version)
                self._connection.execute(f"PRAGMA user_version = {self.SCHEMA_VERSION}")
        except BaseException:
            self._connection.close()
            raise

    def _archive_legacy_mood(self, version: int) -> None:
        """Archive exact JSON without translating labels or modifying any original row.

        保留精确 JSON，不翻译标签、不修改原记录；事务失败时全部回滚。
        """
        for owner, collection, key, encoded in self._connection.execute(
            "SELECT owner, collection, key, value FROM records "
            "WHERE collection IN ('companion', 'character_companion')"
        ).fetchall():
            # Empty defaults created by an earlier migration are not legacy Mood history.
            # 前序迁移新建的空默认值不是旧 Mood 历史；不要制造额外告警。
            try:
                original = json.loads(encoded)
                if isinstance(original, dict) and not original.get("mood"):
                    continue
            except (ValueError, TypeError):
                pass  # Preserve malformed source bytes for audit. / 损坏源数据仍原样归档。
            archive = f"mood-v{version}:{collection}:{key}"
            self._migration_record(owner, "migration_original", archive, {"raw_json": encoded})
            self._migration_record(
                owner,
                "migration_warning",
                archive,
                {
                    "collection": collection,
                    "key": key,
                    "reason": "Legacy Mood is read-only history; "
                    "no Affect conversion or trust elevation",
                },
            )

    def _migrate_scopes(self, version: int) -> None:
        """Keep legacy state private and create empty character-level life atomically.

        在同一事务内保留旧私有状态并新建空白角色公共生活；不删除未知字段、
        不提升信任，也不把私人计划或关系历史默认为群聊可见内容。
        """
        from .companion_models import CompanionState
        from .lifelike_models import LifelikeState

        if version:
            rows = self._connection.execute(
                "SELECT owner, collection, key, value FROM records "
                "WHERE collection IN ('companion', 'lifelike', 'state', 'relationship')"
            ).fetchall()
            for owner, collection, key, encoded in rows:
                record_key = f"v{version}:{collection}:{key}"
                self._migration_record(
                    owner, "migration_original", record_key, {"raw_json": encoded}
                )
                self._migration_record(
                    owner,
                    "migration_warning",
                    record_key,
                    {
                        "collection": collection,
                        "key": key,
                        "reason": "Legacy mixed state retained owner-private; "
                        "public life starts empty",
                    },
                )
        for owner, cid in self._connection.execute(
            "SELECT owner, key FROM records WHERE collection='definition'"
        ).fetchall():
            # Only the stable record key is needed. Malformed definitions remain untouched.
            # 仅使用稳定主键；旧定义的未知或损坏字段不被重写。
            try:
                companion = CompanionState(character_id=cid).model_dump(mode="json")
                lifelike = LifelikeState(character_id=cid).model_dump(mode="json")
            except ValidationError:
                continue
            self._migration_record(owner, "character_companion", cid, companion)
            self._migration_record(owner, "character_lifelike", cid, lifelike)

    def _setup_memory_index(self, backfill: bool) -> None:
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS memory_index (
                id INTEGER PRIMARY KEY, owner TEXT NOT NULL, key TEXT NOT NULL,
                character_id TEXT NOT NULL, kind TEXT NOT NULL, source TEXT NOT NULL,
                session_id TEXT, status TEXT NOT NULL, created REAL NOT NULL,
                observed REAL NOT NULL, expires REAL, importance REAL NOT NULL,
                normalized TEXT NOT NULL, terms TEXT NOT NULL, promoted_from TEXT,
                UNIQUE(owner, key))"""
        )
        for name, columns in (
            ("memory_recent", "owner, character_id, status, kind, observed DESC"),
            ("memory_important", "owner, character_id, status, kind, importance DESC"),
            ("memory_duplicate", "owner, character_id, normalized, kind, source"),
            ("memory_promoted", "owner, character_id, promoted_from"),
        ):
            self._connection.execute(
                f"CREATE INDEX IF NOT EXISTS {name} ON memory_index({columns})"
            )
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS memory_tokens (
                owner TEXT NOT NULL, character_id TEXT NOT NULL, token TEXT NOT NULL,
                memory_id INTEGER NOT NULL REFERENCES memory_index(id) ON DELETE CASCADE,
                PRIMARY KEY(owner, character_id, token, memory_id)) WITHOUT ROWID"""
        )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS memory_tokens_id ON memory_tokens(memory_id)"
        )
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS retrieval_meta (key TEXT PRIMARY KEY, value INTEGER)"
        )
        self._connection.execute("INSERT OR IGNORE INTO retrieval_meta VALUES ('fts_dirty', 1)")
        try:
            self._connection.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(terms)"
            )
            self._connection.execute("SELECT rowid FROM memory_fts LIMIT 1").fetchall()
            self.fts_available = True
        except sqlite3.OperationalError as error:
            if "no such module" not in str(error).lower():
                raise
        if backfill:
            cursor = self._connection.execute(
                "SELECT owner, collection, key, value FROM records "
                "WHERE collection IN ('memory', 'state')"
            )
            for owner, collection, key, encoded in cursor.fetchall():
                record_key = collection + ":" + key
                try:
                    original = self._decode(encoded)
                except (ValueError, RuntimeError):
                    self._migration_record(
                        owner,
                        "migration_original",
                        record_key,
                        {
                            "raw_json": encoded,
                        },
                    )
                    self._migration_record(
                        owner,
                        "migration_warning",
                        record_key,
                        {
                            "collection": collection,
                            "key": key,
                            "reason": "Malformed legacy record retained unchanged and not indexed",
                        },
                    )
                    continue
                revoked = (
                    {"scope", "shared_with", "recipients"}
                    if collection == "memory"
                    else {"known_characters", "shared_world_id"}
                )
                candidate = {k: v for k, v in original.items() if k not in revoked}
                if collection == "memory":
                    candidate["legacy_unverified"] = True
                try:
                    if collection == "memory":
                        if (
                            original.get("owner") != owner
                            or original.get("id") != key
                            or not original.get("created_at")
                        ):
                            raise ValueError("Legacy memory identity/time cannot be inferred")
                        normalized = Memory.model_validate(candidate).model_dump(mode="json")
                    else:
                        if original.get("character_id") != key:
                            raise ValueError("Legacy state identity cannot be inferred")
                        normalized = CharacterState.model_validate(candidate).model_dump(
                            mode="json"
                        )
                except (ValidationError, ValueError):
                    self._migration_record(owner, "migration_original", record_key, original)
                    self._migration_record(
                        owner,
                        "migration_warning",
                        record_key,
                        {
                            "collection": collection,
                            "key": key,
                            "reason": "Legacy record cannot be safely interpreted; "
                            "original retained; "
                            "sharing and social fields revoked",
                        },
                    )
                    self._connection.execute(
                        "UPDATE records SET value = ? "
                        "WHERE owner = ? AND collection = ? AND key = ?",
                        (json.dumps(candidate, ensure_ascii=False), owner, collection, key),
                    )
                    continue
                if original != normalized:
                    self._migration_record(owner, "migration_original", record_key, original)
                    self._migration_record(
                        owner,
                        "migration_warning",
                        record_key,
                        {
                            "collection": collection,
                            "key": key,
                            "reason": "Legacy record normalized; original retained; "
                            "memory unverified and sharing/social grants revoked",
                        },
                    )
                    self._connection.execute(
                        "UPDATE records SET value = ? "
                        "WHERE owner = ? AND collection = ? AND key = ?",
                        (json.dumps(normalized, ensure_ascii=False), owner, collection, key),
                    )
                if collection == "memory":
                    self._index_memory(owner, key, normalized)
        dirty = self._connection.execute(
            "SELECT value FROM retrieval_meta WHERE key = 'fts_dirty'"
        ).fetchone()[0]
        if self.fts_available and dirty:
            self._connection.execute("DELETE FROM memory_fts")
            self._connection.execute(
                "INSERT INTO memory_fts(rowid, terms) SELECT id, terms FROM memory_index"
            )
            self._connection.execute("UPDATE retrieval_meta SET value = 0 WHERE key = 'fts_dirty'")

    def _migration_record(
        self,
        owner: str,
        collection: str,
        key: str,
        value: dict[str, Any],
    ) -> None:
        self._connection.execute(
            "INSERT OR IGNORE INTO records(owner, collection, key, value) VALUES (?, ?, ?, ?)",
            (owner, collection, key, json.dumps(value, ensure_ascii=False)),
        )

    @staticmethod
    def _timestamp(value: Any) -> float:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()

    def _remove_memory_index(self, owner: str, key: str) -> None:
        row = self._connection.execute(
            "SELECT id FROM memory_index WHERE owner = ? AND key = ?", (owner, key)
        ).fetchone()
        if row is None:
            return
        if self.fts_available:
            self._connection.execute("DELETE FROM memory_fts WHERE rowid = ?", row)
        else:
            self._connection.execute("UPDATE retrieval_meta SET value = 1 WHERE key = 'fts_dirty'")
        self._connection.execute("DELETE FROM memory_index WHERE id = ?", row)

    def _index_memory(self, owner: str, key: str, value: dict[str, Any]) -> None:
        if value.get("owner") != owner or value.get("status") == "forgotten":
            self._remove_memory_index(owner, key)
            return
        content = value["content"]
        term_set = tokens(content)
        terms = " ".join(sorted(term_set))
        existing = self._connection.execute(
            "SELECT id, terms, character_id FROM memory_index WHERE owner = ? AND key = ?",
            (owner, key),
        ).fetchone()
        self._connection.execute(
            """INSERT INTO memory_index (
                owner, key, character_id, kind, source, session_id, status, created,
                observed, expires, importance, normalized, terms, promoted_from
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(owner, key) DO UPDATE SET
                character_id=excluded.character_id, kind=excluded.kind, source=excluded.source,
                session_id=excluded.session_id, status=excluded.status, created=excluded.created,
                observed=excluded.observed, expires=excluded.expires,
                importance=excluded.importance,
                normalized=excluded.normalized, terms=excluded.terms,
                promoted_from=excluded.promoted_from""",
            (
                owner,
                key,
                value["character_id"],
                value["kind"],
                value.get("source", "conversation"),
                value.get("session_id"),
                value.get("status", "active"),
                self._timestamp(value["created_at"]),
                self._timestamp(value.get("last_observed_at") or value["created_at"]),
                self._timestamp(value["expires_at"]) if value.get("expires_at") else None,
                value.get("importance", 0.5),
                normalize(content),
                terms,
                value.get("promoted_from"),
            ),
        )
        if existing and existing[1:] == (terms, value["character_id"]):
            return
        row = self._connection.execute(
            "SELECT id FROM memory_index WHERE owner = ? AND key = ?", (owner, key)
        ).fetchone()
        self._connection.execute("DELETE FROM memory_tokens WHERE memory_id = ?", row)
        self._connection.executemany(
            "INSERT INTO memory_tokens VALUES (?, ?, ?, ?)",
            ((owner, value["character_id"], token, row[0]) for token in term_set),
        )
        if self.fts_available:
            self._connection.execute("DELETE FROM memory_fts WHERE rowid = ?", row)
            self._connection.execute(
                "INSERT INTO memory_fts(rowid, terms) VALUES (?, ?)", (row[0], terms)
            )
        else:
            self._connection.execute("UPDATE retrieval_meta SET value = 1 WHERE key = 'fts_dirty'")

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Commit as a unit or roll back, preserving nested transaction semantics.

        作为一个单元提交或回滚，保留嵌套事务语义。
        """

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
        """Read one owner-keyed record; turn-level authorization belongs to ScopedStorage.

        读取一个 Owner 记录；回合权限由 ScopedStorage 约束。
        """

        self._validate(owner, collection, key)
        with self._lock:
            row = self._connection.execute(
                "SELECT value FROM records WHERE owner = ? AND collection = ? AND key = ?",
                (owner, collection, key),
            ).fetchone()
        return None if row is None else self._decode(row[0])

    def put(self, owner: str, collection: str, key: str, value: dict[str, Any]) -> None:
        """Persist an owner-keyed record within the caller's transaction boundary.

        在调用方事务边界内保存 Owner 记录。
        """

        self._validate(owner, collection, key)
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        with self.transaction():
            self._connection.execute(
                """
                INSERT INTO records (owner, collection, key, value) VALUES (?, ?, ?, ?)
                ON CONFLICT (owner, collection, key) DO UPDATE SET value = excluded.value
                """,
                (owner, collection, key, encoded),
            )
            if collection == "memory":
                self._index_memory(owner, key, value)

    def list(self, owner: str, collection: str) -> builtins.list[dict[str, Any]]:
        """List one owner's collection; callers must retain character and audience boundaries.

        列出 Owner 的集合；调用方仍须保持角色与受众边界。
        """

        self._validate(owner, collection)
        with self._lock:
            rows = self._connection.execute(
                "SELECT value FROM records WHERE owner = ? AND collection = ?",
                (owner, collection),
            ).fetchall()
        return [self._decode(row[0]) for row in rows]

    def delete(self, owner: str, collection: str, key: str) -> None:
        """Delete only the addressed owner record, never another namespace.

        仅删除指定 Owner 的记录，不越过命名空间。
        """

        self._validate(owner, collection, key)
        with self.transaction():
            self._connection.execute(
                "DELETE FROM records WHERE owner = ? AND collection = ? AND key = ?",
                (owner, collection, key),
            )
            if collection == "memory":
                self._remove_memory_index(owner, key)

    def memory_window(
        self,
        owner: str,
        character_id: str,
        *,
        start: datetime | None,
        end: datetime | None,
        session_id: str | None,
        real: bool,
        include_archived: bool,
        semantic_key: str | None,
        kind: str | None,
        limit: int,
        scope: MemoryScope | None = None,
    ) -> builtins.list[dict[str, Any]]:
        """Select time-bounded memories after applying audience scope in SQL.

        先在 SQL 中应用受众范围，再选择时间窗口记忆。
        """

        clauses = [
            "r.owner = ?",
            "r.collection = 'memory'",
            "i.character_id = ?",
            "i.status IN ('active', 'archived')" if include_archived else "i.status = 'active'",
            "(i.expires IS NULL OR i.expires > ?)",
            "(i.session_id IS NULL OR i.session_id = ?)",
        ]
        from .models import now

        scope_sql, scope_args = memory_scope_sql("i", owner, scope)
        clauses.append(scope_sql)
        args: builtins.list[Any] = [owner, character_id, now().timestamp(), session_id, *scope_args]
        event_time = (
            "julianday(COALESCE(json_extract(r.value,'$.event_at'), "
            "json_extract(r.value,'$.created_at')))"
        )
        if not real:
            clauses.append("i.kind != 'real_user'")
        for boundary, op in ((start, ">="), (end, "<")):
            if boundary:
                clauses.append(f"{event_time} {op} julianday(?)")
                args.append(boundary.isoformat())
        if semantic_key:
            clauses.append("json_extract(r.value,'$.semantic_key') = ?")
            args.append(semantic_key)
        if kind:
            clauses.append("i.kind = ?")
            args.append(kind)
        args.append(max(1, min(1000, limit)))
        with self._lock:
            rows = self._connection.execute(
                "SELECT r.value FROM records r JOIN memory_index i "
                "ON i.owner=r.owner AND i.key=r.key "
                + "WHERE "
                + " AND ".join(clauses)
                + f" ORDER BY {event_time} DESC, r.key LIMIT ?",
                args,
            )
            return [json.loads(row[0]) for row in rows]

    def memory_candidates(
        self,
        owner: str,
        character_id: str,
        query: str,
        *,
        session_id: str | None,
        real: bool,
        at: datetime,
        include_archived: bool = False,
        limit: int = 256,
        scope: MemoryScope | None = None,
    ) -> builtins.list[tuple[dict[str, Any], float]]:
        """Union bounded lexical, FTS, recent and important lanes before Python scoring.

        合并有界词法、全文、近期及重要性通道，再进行 Python 排序。
        """
        if not 1 <= limit <= 256 or len(query) > 8000:
            raise ValueError("Memory candidates require limit 1..256 and query <=8000 characters")
        wanted = sorted(tokens(query))[:64]
        status = "m.status IN ('active', 'archived')" if include_archived else "m.status = 'active'"
        where = (
            f"m.owner = ? AND m.character_id = ? AND {status} "
            f"AND m.kind {'=' if real else '!='} 'real_user' "
            "AND (m.kind != 'session' OR m.session_id = ?) "
            "AND (m.expires IS NULL OR m.expires > ?)"
        )
        scope_sql, scope_args = memory_scope_sql("m", owner, scope)
        where += " AND " + scope_sql
        parameters = (owner, character_id, session_id, at.timestamp(), *scope_args)
        lane = max(1, limit // 4)
        ids: dict[int, float] = {}
        with self._lock:
            # Do not use corpus-wide BM25: other private audiences must not affect ranking.
            # 不使用全库 BM25，避免其他私有受众的数据影响本轮排序。
            if wanted and self.fts_available:
                expression = " OR ".join('"' + term.replace('"', '""') + '"' for term in wanted)
                rows = self._connection.execute(
                    "SELECT m.id FROM memory_fts JOIN memory_index m ON m.id = memory_fts.rowid "
                    f"WHERE memory_fts MATCH ? AND {where} ORDER BY m.observed DESC, m.id LIMIT ?",
                    (expression, *parameters, lane),
                ).fetchall()
                ids.update((row[0], 1 / (rank + 1)) for rank, row in enumerate(rows))
            if wanted:
                placeholders = ",".join("?" for _ in wanted)
                rows = self._connection.execute(
                    "SELECT m.id FROM memory_tokens t JOIN memory_index m ON m.id = t.memory_id "
                    f"WHERE t.owner = ? AND t.character_id = ? AND t.token IN ({placeholders}) "
                    f"AND {where} GROUP BY m.id ORDER BY count(*) DESC, m.importance DESC, "
                    "m.observed DESC, m.id LIMIT ?",
                    (
                        owner,
                        character_id,
                        *wanted,
                        *parameters,
                        lane if self.fts_available else lane * 2,
                    ),
                ).fetchall()
                for row in rows:
                    ids.setdefault(row[0], 0)
            for order in ("observed DESC, importance DESC", "importance DESC, observed DESC"):
                rows = self._connection.execute(
                    f"SELECT m.id FROM memory_index m WHERE {where} ORDER BY {order}, id LIMIT ?",
                    (*parameters, lane),
                ).fetchall()
                for row in rows:
                    ids.setdefault(row[0], 0)
            selected = list(ids)[:limit]
            if not selected:
                return []
            placeholders = ",".join("?" for _ in selected)
            rows = self._connection.execute(
                "SELECT r.value, m.id FROM memory_index m JOIN records r "
                "ON r.owner = m.owner AND r.collection = 'memory' AND r.key = m.key "
                f"WHERE m.id IN ({placeholders})",
                selected,
            ).fetchall()
        return [(self._decode(value), ids[key]) for value, key in rows]

    def memory_duplicates(
        self,
        owner: str,
        character_id: str,
        content: str,
        kind: str,
        source: str,
        session_id: str | None,
        since: datetime,
        *,
        scope: MemoryScope | None = None,
    ) -> builtins.list[dict[str, Any]]:
        """Find cosmetic duplicates only within the authorized memory audience.

        只在授权受众内查找表面差异的重复记忆。
        """

        scope_sql, scope_args = memory_scope_sql("m", owner, scope)
        with self._lock:
            rows = self._connection.execute(
                f"""SELECT r.value FROM memory_index m JOIN records r
                ON r.owner = m.owner AND r.collection = 'memory' AND r.key = m.key
                WHERE m.owner = ? AND m.character_id = ? AND {scope_sql} AND m.normalized = ?
                AND m.kind = ? AND m.source = ? AND m.session_id IS ? AND m.status = 'active'
                AND m.observed >= ? ORDER BY m.observed DESC LIMIT 8""",
                (
                    owner,
                    character_id,
                    *scope_args,
                    normalize(content),
                    kind,
                    source,
                    session_id,
                    since.timestamp(),
                ),
            ).fetchall()
        return [self._decode(row[0]) for row in rows]

    def memory_related(
        self,
        owner: str,
        character_id: str,
        memory_id: str,
        *,
        scope: MemoryScope | None = None,
    ) -> builtins.list[dict[str, Any]]:
        """Find promotion-related records without crossing audience boundaries.

        查找提升关系记录，不跨越受众边界。
        """

        scope_sql, scope_args = memory_scope_sql("m", owner, scope)
        with self._lock:
            rows = self._connection.execute(
                f"""SELECT r.value FROM memory_index m JOIN records r
                ON r.owner = m.owner AND r.collection = 'memory' AND r.key = m.key
                WHERE m.owner = ? AND m.character_id = ? AND {scope_sql}
                AND (m.key = ? OR m.promoted_from = ?)""",
                (owner, character_id, *scope_args, memory_id, memory_id),
            ).fetchall()
        return [self._decode(row[0]) for row in rows]

    def memory_stale(
        self,
        owner: str,
        character_id: str,
        before: datetime,
        *,
        scope: MemoryScope | None = None,
    ) -> builtins.list[dict[str, Any]]:
        """Select maintenance candidates within owner, character and audience limits.

        在 Owner、角色和受众限制内选择维护候选。
        """

        scope_sql, scope_args = memory_scope_sql("m", owner, scope)
        with self._lock:
            rows = self._connection.execute(
                f"""SELECT r.value FROM memory_index m JOIN records r
                ON r.owner = m.owner AND r.collection = 'memory' AND r.key = m.key
                WHERE m.owner = ? AND m.character_id = ? AND {scope_sql} AND m.status = 'active'
                AND m.kind = 'character_long_term' AND m.importance < 0.7 AND m.observed < ?
                AND m.source IN ('conversation', 'model', 'inferred', 'simulated_life')
                ORDER BY m.observed LIMIT 100""",
                (owner, character_id, *scope_args, before.timestamp()),
            ).fetchall()
        return [self._decode(row[0]) for row in rows]

    def close(self) -> None:
        """Release the database connection; this does not delete persistent data.

        释放数据库连接，不删除持久数据。
        """

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
