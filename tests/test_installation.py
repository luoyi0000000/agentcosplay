import os
import tempfile
import unittest
from pathlib import Path

from character_runtime.paths import default_base, validate_data_path


class DataPathTests(unittest.TestCase):
    def test_os_defaults_and_repository_overlap(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertEqual(
                default_base("darwin", {}, root), root / "Library/Application Support/agentcosplay"
            )
            self.assertEqual(default_base("linux", {}, root), root / ".local/share/agentcosplay")
            self.assertEqual(
                default_base("win32", {"LOCALAPPDATA": str(root / "local")}, root),
                root / "local/agentcosplay",
            )
            repo = root / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            with self.assertRaises(ValueError):
                validate_data_path(repo / "data")
            with self.assertRaises(ValueError):
                validate_data_path(root / "app/data", [root / "app"])
            with self.assertRaises(ValueError):
                validate_data_path(Path("relative/data"))
            self.assertEqual(validate_data_path(root / "private"), (root / "private").resolve())

    @unittest.skipUnless(os.name == "posix", "symlink support")
    def test_symlink_into_repository_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            repo = root / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            link = root / "outside"
            link.symlink_to(repo, target_is_directory=True)
            with self.assertRaises(ValueError):
                validate_data_path(link / "data")


class HostConfigTests(unittest.TestCase):
    def test_merge_conflict_and_uninstall_preserve_other_servers(self):
        from character_runtime.host_config import edit_config

        server = {"command": "/private/python", "args": ["/private/launch.py", "serve"]}
        original = '# keep this comment\nmodel = "custom"\n[mcp_servers.other]\ncommand = "other"\n'
        updated = edit_config("codex", original, server)
        self.assertIn("# keep this comment", updated)
        self.assertIn('command = "other"', updated)
        self.assertEqual(edit_config("codex", updated, server), updated)
        with self.assertRaises(ValueError):
            edit_config("codex", updated, {"command": "unrelated"})
        removed = edit_config("codex", updated, server, remove=True)
        self.assertNotIn("[mcp_servers.agentcosplay]", removed)
        self.assertIn('command = "other"', removed)
        for host, content in [
            ("hermes", "model: keep\nmcp_servers:\n  other:\n    command: keep\n"),
            ("astrbot", '{"mcpServers":{"other":{"command":"keep"}}}'),
        ]:
            with self.subTest(host=host):
                changed = edit_config(host, content, server)
                self.assertIn("keep", changed)
                self.assertEqual(edit_config(host, changed, server), changed)
                self.assertNotIn("agentcosplay", edit_config(host, changed, server, remove=True))


class TransactionTests(unittest.TestCase):
    def test_recovery_restores_only_unchanged_managed_writes(self):
        import install

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            host = root / "config"
            host.write_bytes(b"original secret config")
            tx = install.Transaction(root)
            tx.write(host, b"new config")
            self.assertTrue((root / "pending.json").exists())
            install.recover(root)
            self.assertEqual(host.read_bytes(), b"original secret config")
            tx = install.Transaction(root)
            tx.write(host, b"new config")
            host.write_bytes(b"user edit after interruption")
            with self.assertRaises(ValueError):
                install.recover(root)
            self.assertEqual(host.read_bytes(), b"user edit after interruption")
            self.assertTrue((root / "pending.json").exists())

    def test_failed_update_keeps_previous_release_and_data(self):
        from unittest.mock import patch

        import install

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            app, data = root / "app", root / "private"
            app.mkdir()
            data.mkdir()
            (data / "precious").write_text("user data")
            state = {
                "active": "previous",
                "owner": "local-user",
                "data_dir": str(data),
                "integrations": [],
            }
            install.atomic_write(app / "installed.json", install.encode(state))
            candidate = app / "releases/candidate"
            candidate.mkdir(parents=True)
            with (
                patch("install.build_release", return_value=candidate),
                patch("install.health", side_effect=RuntimeError("failure")),
            ):
                with self.assertRaises(RuntimeError):
                    install.install(app, install.SOURCE, data, "local-user", "generic")
            self.assertEqual(install.state_of(app), state)
            self.assertEqual((data / "precious").read_text(), "user data")
            self.assertFalse(candidate.exists())

    def test_managed_layout_rejects_data_as_ancestor_of_program(self):
        import install

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            with self.assertRaises(ValueError):
                install.validate_layout(root / "data/app", root / "data", install.SOURCE)


class ReviewRegressionTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "Executable symlinks need privileges on Windows")
    def test_launcher_ignores_working_directory_modules(self):
        import subprocess
        import sys

        import install

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            release = root / "releases/a"
            python = install.python_at(release)
            python.parent.mkdir(parents=True)
            python.symlink_to(sys.executable)
            install.atomic_write(root / "launch.py", install.LAUNCHER.encode())
            install.atomic_write(
                root / "installed.json",
                install.encode({"active": "a", "data_dir": str(root / "data"), "owner": "test"}),
            )
            shadow = root / "shadow/character_runtime"
            shadow.mkdir(parents=True)
            (shadow / "__init__.py").write_text("")
            (shadow / "__main__.py").write_text('print("SHADOW EXECUTED")')
            result = subprocess.run(
                [sys.executable, str(root / "launch.py"), "--help"],
                cwd=shadow.parent,
                capture_output=True,
                text=True,
            )
            self.assertNotIn("SHADOW EXECUTED", result.stdout)

    def test_host_credentials_cannot_be_written_under_git(self):
        import install

        with tempfile.TemporaryDirectory() as folder:
            host = Path(folder) / "host"
            host.mkdir()
            (host / ".git").mkdir()
            with self.assertRaises(ValueError):
                install.host_paths("codex", host)

    def test_killed_installer_can_recover_without_deleting_lock(self):
        import subprocess
        import sys

        import install

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            config = root / "config"
            config.write_bytes(b"original")
            script = (
                "import install,os; from pathlib import Path; r=Path("
                + repr(str(root))
                + ");\nwith install.lock(r):\n t=install.Transaction(r);"
                + ' t.write(r/"config",b"changed"); os._exit(9)'
            )
            result = subprocess.run([sys.executable, "-c", script], cwd=install.SOURCE)
            self.assertEqual(result.returncode, 9)
            with install.lock(root):
                install.recover(root)
            self.assertEqual(config.read_bytes(), b"original")

    def test_uninstall_can_resume_cleanup_after_locked_release(self):
        from unittest.mock import patch

        import install

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            app, data = root / "应用 runtime", root / "角色 data"
            (app / "releases/a").mkdir(parents=True)
            data.mkdir()
            (data / "keep").write_bytes(b"precious")
            install.atomic_write(
                app / "installed.json",
                install.encode(
                    {"active": "a", "data_dir": str(data), "integrations": [], "owner": "test"}
                ),
            )
            with patch("install.shutil.rmtree", side_effect=PermissionError("locked")):
                with self.assertRaises(PermissionError):
                    install.uninstall(app)
            self.assertTrue(install.state_of(app)["uninstalled"])
            install.uninstall(app)
            self.assertFalse((app / "releases").exists())
            self.assertEqual((data / "keep").read_bytes(), b"precious")

    def test_locked_file_replacement_preserves_original_and_cleans_temp(self):
        from unittest.mock import patch

        import install

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "配置 文件"
            path.write_bytes(b"original")
            with patch("install.os.replace", side_effect=PermissionError("locked")):
                with self.assertRaises(PermissionError):
                    install.atomic_write(path, b"replacement")
            self.assertEqual(path.read_bytes(), b"original")
            self.assertEqual(list(Path(folder).iterdir()), [path])
