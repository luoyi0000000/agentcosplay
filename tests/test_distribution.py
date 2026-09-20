import hashlib
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DistributionTests(unittest.TestCase):
    def test_manifest_versions_assets_and_authoritative_overlay(self):
        import tomllib

        from character_runtime import __version__

        catalog = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
        plugin = ROOT / catalog["plugins"][0]["source"]["path"]
        root = json.loads((plugin / "plugin.json").read_text())
        overlay = json.loads((plugin / ".codex-plugin/plugin.json").read_text())
        self.assertEqual(root["version"], __version__)
        self.assertEqual(overlay["version"], __version__)
        self.assertEqual(
            tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"], __version__
        )
        interface = root["extensions"]["com.openai"]["interface"]
        self.assertEqual(interface, overlay["interface"])
        for key in ("logo", "composerIcon"):
            path = (plugin / interface[key]).resolve()
            self.assertTrue(path.is_relative_to(plugin.resolve()))
            self.assertTrue(path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(),
                "6705d3ecc42b9cebaaa4881faf0b57429275d8cc560845af438d20a3568a9ae1",
            )

    def test_single_skill_and_all_relative_reference_links_resolve(self):
        plugin = ROOT / "plugins/agentcosplay"
        self.assertEqual(len(list(plugin.rglob("SKILL.md"))), 1)
        for doc in (plugin / "skills").rglob("*.md"):
            for target in re.findall(r"\]\(([^)]+)\)", doc.read_text()):
                if "://" not in target:
                    self.assertTrue((doc.parent / target).is_file(), (doc, target))
        self.assertLess(len((plugin / "skills/agentcosplay/SKILL.md").read_text()), 2600)

    def test_readme_has_only_two_install_routes(self):
        readme = (ROOT / "README.md").read_text()
        self.assertIn("## 1. ChatGPT Marketplace", readme)
        self.assertIn("## 2. Agent 对话中自动安装", readme)
        for legacy in ("git clone", "python3 install.py", "curl ", ".zip"):
            self.assertNotIn(legacy, readme)
