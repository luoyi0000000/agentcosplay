import json
import os
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DistributionTests(unittest.TestCase):
    def test_marketplace_archive_and_runtime_versions_match(self):
        import tomllib

        from character_runtime import __version__

        catalog = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
        plugin = ROOT / catalog["plugins"][0]["source"]["path"]
        manifest = json.loads((plugin / "plugin.json").read_text())
        self.assertEqual(manifest["name"], "agentcosplay")
        self.assertEqual(manifest["version"], __version__)
        package = tomllib.loads((ROOT / "pyproject.toml").read_text())
        self.assertEqual(package["project"]["version"], __version__)
        self.assertEqual(package["project"]["name"], "agentcosplay")
        with zipfile.ZipFile(ROOT / "downloads/agentcosplay-skill.zip") as archive:
            files = sorted(p for p in (plugin / "skills/agentcosplay").rglob("*") if p.is_file())
            self.assertEqual(len(archive.namelist()), len(files))
            for file in files:
                name = "agentcosplay/" + file.relative_to(plugin / "skills/agentcosplay").as_posix()
                self.assertEqual(archive.read(name), file.read_bytes())

    def test_installer_preserves_edits_and_never_leaves_partial_skill(self):
        # Only replace the network boundary; execute the actual installer and unzip.
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            bin_dir = temp / "bin"
            bin_dir.mkdir()
            curl = bin_dir / "curl"
            curl.write_text(
                "#!/bin/bash\nset -e\n"
                'out=""\nwhile [ "$#" -gt 0 ]; do\n'
                'if [ "$1" = "-o" ]; then shift; out="$1"; fi\nshift\ndone\n'
                'if [ "${FAIL_DOWNLOAD:-}" = "1" ]; then exit 22; fi\n'
                'cp "$TEST_ARCHIVE" "$out"\n'
            )
            curl.chmod(0o755)
            env = dict(os.environ, PATH=f"{bin_dir}:" + os.environ["PATH"])
            env["TEST_ARCHIVE"] = str(ROOT / "downloads/agentcosplay-skill.zip")
            dest = temp / "中文 skills"
            command = ["bash", str(ROOT / "install.sh"), "--skills-dir", str(dest)]

            def run(**values):
                return subprocess.run(
                    command, env={**env, **values}, capture_output=True, text=True
                )

            failed = run(FAIL_DOWNLOAD="1")
            self.assertNotEqual(failed.returncode, 0)
            self.assertFalse((dest / "agentcosplay").exists())
            invalid = temp / "invalid.zip"
            invalid.write_bytes(b"not a zip")
            self.assertNotEqual(run(TEST_ARCHIVE=str(invalid)).returncode, 0)
            self.assertFalse((dest / "agentcosplay").exists())
            installed = run()
            self.assertEqual(installed.returncode, 0, installed.stderr)
            skill = dest / "agentcosplay/SKILL.md"
            self.assertIn("name: agentcosplay", skill.read_text())
            self.assertEqual(run().returncode, 0)
            skill.write_text("user edits")
            self.assertNotEqual(run().returncode, 0)
            self.assertEqual(skill.read_text(), "user edits")
            self.assertFalse(list(dest.glob(".agentcosplay-*")))

    def test_installer_refuses_symlink_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            external = temp / "external"
            external.mkdir()
            (temp / "agentcosplay").symlink_to(external, target_is_directory=True)
            result = subprocess.run(
                ["bash", str(ROOT / "install.sh"), "--skills-dir", str(temp)],
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(list(external.iterdir()), [])
