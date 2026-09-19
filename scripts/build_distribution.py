"""Rebuild the deterministic AstrBot/Agent Skill download and installer checksum."""

import hashlib
import re
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    skill = ROOT / "plugins/agentcosplay/skills/agentcosplay"
    output = ROOT / "downloads/agentcosplay-skill.zip"
    output.parent.mkdir(exist_ok=True)
    with ZipFile(output, "w") as archive:
        for file in sorted(skill.rglob("*")):
            if file.is_file():
                info = ZipInfo("agentcosplay/" + file.relative_to(skill).as_posix())
                info.compress_type = ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, file.read_bytes())
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    installer = ROOT / "install.sh"
    content, count = re.subn(
        r'^expected_sha256="[^"]*"$',
        f'expected_sha256="{digest}"',
        installer.read_text(),
        flags=re.MULTILINE,
    )
    if count != 1:
        raise ValueError("Expected exactly one installer checksum")
    installer.write_text(content)


if __name__ == "__main__":
    main()
