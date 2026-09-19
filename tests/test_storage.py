import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from character_runtime.storage import SQLiteStorage


class SQLiteStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "角色 数据.sqlite3"
        self.storage = SQLiteStorage(self.path)

    def tearDown(self) -> None:
        self.storage.close()
        self.directory.cleanup()

    def test_owner_and_collection_are_isolated(self) -> None:
        self.storage.put("owner-a", "characters", "same", {"name": "A"})
        self.storage.put("owner-b", "characters", "same", {"name": "B"})
        self.storage.put("owner-a", "sessions", "same", {"name": "session"})

        self.assertEqual(self.storage.get("owner-a", "characters", "same"), {"name": "A"})
        self.assertEqual(self.storage.get("owner-b", "characters", "same"), {"name": "B"})
        self.assertEqual(self.storage.list("owner-a", "characters"), [{"name": "A"}])
        self.assertEqual(self.storage.list("owner-a", "sessions"), [{"name": "session"}])

    def test_nested_transaction_rolls_back_only_failed_savepoint(self) -> None:
        with self.storage.transaction():
            self.storage.put("owner", "items", "before", {"value": 1})
            with self.assertRaises(RuntimeError):
                with self.storage.transaction():
                    self.storage.put("owner", "items", "failed", {"value": 2})
                    raise RuntimeError("rollback inner transaction")
            self.storage.put("owner", "items", "after", {"value": 3})

        self.assertCountEqual(
            self.storage.list("owner", "items"),
            [{"value": 3}, {"value": 1}],
        )

    def test_outer_transaction_rolls_back_all_writes(self) -> None:
        with self.assertRaises(RuntimeError):
            with self.storage.transaction():
                self.storage.put("owner", "items", "one", {"value": 1})
                with self.storage.transaction():
                    self.storage.put("owner", "items", "two", {"value": 2})
                raise RuntimeError("rollback outer transaction")

        self.assertEqual(self.storage.list("owner", "items"), [])

    def test_data_survives_reopen_at_unicode_path(self) -> None:
        self.storage.put("用户", "角色 列表", "甲", {"名字": "旅人"})
        self.storage.close()

        self.storage = SQLiteStorage(self.path)

        self.assertEqual(self.storage.get("用户", "角色 列表", "甲"), {"名字": "旅人"})

    def test_process_interruption_preserves_committed_data_and_rolls_back_pending_write(
        self,
    ) -> None:
        self.storage.put("owner", "items", "committed", {"content": "keep"})
        self.storage.close()
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import os, sys\n"
                "from character_runtime.storage import SQLiteStorage\n"
                "storage = SQLiteStorage(sys.argv[1])\n"
                "with storage.transaction():\n"
                "    storage.put('owner', 'items', 'committed', {'content': 'changed'})\n"
                "    storage.put('owner', 'items', 'pending', {'content': 'discard'})\n"
                "    os._exit(17)\n",
                str(self.path),
            ],
            timeout=10,
            capture_output=True,
        )
        self.storage = SQLiteStorage(self.path)
        self.assertEqual(result.returncode, 17, result.stderr.decode())
        self.assertEqual(self.storage.get("owner", "items", "committed"), {"content": "keep"})
        self.assertIsNone(self.storage.get("owner", "items", "pending"))

    def test_creates_missing_unicode_parent_directories(self) -> None:
        path = Path(self.directory.name) / "缺少 的目录" / "子目录" / "角色.sqlite3"

        storage = SQLiteStorage(path)
        try:
            storage.put("owner", "items", "one", {"value": "saved"})
        finally:
            storage.close()

        reopened = SQLiteStorage(path)
        try:
            self.assertEqual(reopened.get("owner", "items", "one"), {"value": "saved"})
        finally:
            reopened.close()

    @unittest.skipUnless(os.name == "posix", "POSIX file permissions")
    def test_new_database_and_journals_are_private(self) -> None:
        path = Path(self.directory.name) / "private" / "db"
        storage = SQLiteStorage(path)
        try:
            storage.put("owner", "private", "one", {"content": "synthetic private fact"})
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            for file in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
                self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)
        finally:
            storage.close()

    @unittest.skipUnless(os.name == "posix", "POSIX file permissions")
    def test_refuses_existing_public_database_without_changing_permissions(self) -> None:
        path = Path(self.directory.name) / "public.db"
        path.touch(mode=0o644)
        path.chmod(0o644)
        before = path.parent.stat().st_mode
        with self.assertRaises(PermissionError):
            SQLiteStorage(path)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)
        self.assertEqual(path.parent.stat().st_mode, before)
        self.assertEqual(path.read_bytes(), b"")

    @unittest.skipUnless(os.name == "posix", "POSIX file permissions and links")
    def test_refuses_public_sidecars_and_database_symlinks(self) -> None:
        for suffix in ("-wal", "-shm"):
            path = Path(self.directory.name) / f"sidecar{suffix}.db"
            path.touch(mode=0o600)
            sidecar = Path(str(path) + suffix)
            sidecar.touch(mode=0o644)
            sidecar.chmod(0o644)
            with self.assertRaises(PermissionError):
                SQLiteStorage(path)
            self.assertEqual(stat.S_IMODE(sidecar.stat().st_mode), 0o644)
        link = Path(self.directory.name) / "linked.db"
        link.symlink_to(self.path)
        with self.assertRaises(PermissionError):
            SQLiteStorage(link)

    def test_concurrent_first_open_initializes_one_database(self) -> None:
        for run in range(10):
            path = Path(self.directory.name) / f"concurrent-{run}.db"
            barrier = threading.Barrier(8)
            errors: list[BaseException] = []

            def open_database() -> None:
                barrier.wait()
                try:
                    storage = SQLiteStorage(path)
                    try:
                        storage.put("owner", "items", threading.current_thread().name, {"ok": True})
                    finally:
                        storage.close()
                except BaseException as error:
                    errors.append(error)

            threads = [threading.Thread(target=open_database) for _ in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            storage = SQLiteStorage(path)
            try:
                self.assertEqual(len(storage.list("owner", "items")), 8)
            finally:
                storage.close()

    def test_sql_metacharacters_are_plain_values(self) -> None:
        hostile = "x'; DROP TABLE records; --"
        self.storage.put(hostile, hostile, hostile, {"text": hostile})

        self.assertEqual(self.storage.get(hostile, hostile, hostile), {"text": hostile})
        self.storage.delete(hostile, hostile, hostile)
        self.assertIsNone(self.storage.get(hostile, hostile, hostile))

    def test_rejects_empty_identifiers(self) -> None:
        for owner, collection, key in (("", "c", "k"), ("o", "", "k"), ("o", "c", "")):
            with self.subTest(owner=owner, collection=collection, key=key):
                with self.assertRaises(ValueError):
                    self.storage.get(owner, collection, key)

    def test_refuses_database_from_newer_schema(self) -> None:
        self.storage.close()
        connection = sqlite3.connect(self.path)
        self.assertEqual(connection.execute("PRAGMA user_version").fetchone(), (1,))
        connection.execute("PRAGMA user_version = 2")
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.close()

        with self.assertRaises(RuntimeError):
            SQLiteStorage(self.path)

        connection = sqlite3.connect(self.path)
        try:
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone(), ("delete",))
        finally:
            connection.close()
        self.storage = SQLiteStorage(":memory:")

    def test_transaction_lock_prevents_lost_updates_on_shared_connection(self) -> None:
        self.storage.put("owner", "counters", "turns", {"count": 0})
        barrier = threading.Barrier(3)

        def increment() -> None:
            barrier.wait()
            with self.storage.transaction():
                current = self.storage.get("owner", "counters", "turns")
                assert current is not None
                self.storage.put("owner", "counters", "turns", {"count": current["count"] + 1})

        threads = [threading.Thread(target=increment) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()

        self.assertEqual(self.storage.get("owner", "counters", "turns"), {"count": 2})

    def test_transactions_serialize_read_modify_write_across_connections(self) -> None:
        second = SQLiteStorage(self.path)
        self.storage.put("owner", "counters", "turns", {"count": 0})
        attempting = threading.Event()
        entered = threading.Event()
        errors: list[BaseException] = []

        def increment_on_second_connection() -> None:
            attempting.set()
            try:
                with second.transaction():
                    current = second.get("owner", "counters", "turns")
                    assert current is not None
                    entered.set()
                    second.put("owner", "counters", "turns", {"count": current["count"] + 1})
            except BaseException as error:
                errors.append(error)

        thread = threading.Thread(target=increment_on_second_connection)
        try:
            with self.storage.transaction():
                current = self.storage.get("owner", "counters", "turns")
                assert current is not None
                thread.start()
                self.assertTrue(attempting.wait(1))
                self.assertFalse(entered.wait(0.1))
                self.storage.put("owner", "counters", "turns", {"count": current["count"] + 1})
        finally:
            thread.join(2)
            second.close()

        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(self.storage.get("owner", "counters", "turns"), {"count": 2})


if __name__ == "__main__":
    unittest.main()
