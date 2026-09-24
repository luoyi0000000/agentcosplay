"""Check local release manifests, Skill links, and complete brand PNG integrity.

检查本地发布清单、Skill 引用及品牌 PNG 完整性，不要求历史原图逐字节相同。

Run: python -m scripts.check_plugin (standard library only).
"""

import hashlib
import json
import re
import struct
import sys
import tomllib
import zlib
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
# Integrity of the accepted release asset, not a prohibition on future approved resizing.
# 校验当前已接受的发布资源，不禁止以后经确认的合理缩放或压缩。
RELEASE_LOGO_SHA256 = "038bd1960e363e0e01e7c7f7c0c6a9bf040206e16ba934c12e77424a241b5a44"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    require(isinstance(value, dict), f"Expected JSON object: {path}")
    return value


def local_path(root: Path, value: str) -> Path:
    require(isinstance(value, str) and value.startswith("./"), f"Invalid local path: {value}")
    require("\\" not in value and ".." not in Path(value).parts, f"Unsafe path: {value}")
    path = (root / value).resolve()
    require(path.is_relative_to(root.resolve()) and path.exists(), f"Missing/unsafe path: {value}")
    return path


def check_png(path: Path) -> tuple[int, int]:
    """Validate the shipped non-interlaced, 8-bit RGB/RGBA asset format without Pillow."""
    data = path.read_bytes()
    require(data[:8] == b"\x89PNG\r\n\x1a\n", f"Invalid PNG signature: {path}")
    offset, width, height, channels = 8, 0, 0, 0
    chunks: list[bytes] = []
    compressed = bytearray()
    while offset < len(data):
        require(offset + 12 <= len(data), f"Truncated PNG chunk: {path}")
        size, kind = struct.unpack_from(">I4s", data, offset)
        end = offset + 12 + size
        require(end <= len(data), f"Truncated {kind!r} chunk: {path}")
        payload = data[offset + 8 : end - 4]
        crc = struct.unpack_from(">I", data, end - 4)[0]
        require(zlib.crc32(kind + payload) == crc, f"PNG CRC mismatch: {path} {kind!r}")
        require(re.fullmatch(rb"[A-Za-z]{4}", kind) is not None, f"Invalid PNG chunk: {path}")
        require(not (kind[2] & 32), f"Invalid PNG reserved chunk bit: {path}")
        require(chunks or kind == b"IHDR", f"PNG must start with IHDR: {path}")
        if kind == b"IHDR":
            require(not chunks and size == 13, f"Invalid PNG IHDR: {path}")
            width, height, depth, color, method, filtering, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
            require(0 < width == height <= 8192, f"PNG must be square (1–8192px): {path}")
            require(
                depth == 8 and color in (2, 6) and (method, filtering, interlace) == (0, 0, 0),
                f"Brand PNG must be non-interlaced 8-bit RGB/RGBA: {path}",
            )
            channels = 3 if color == 2 else 4
        elif kind == b"IDAT":
            require(b"IDAT" not in chunks or chunks[-1] == b"IDAT", f"Split PNG IDAT: {path}")
            compressed.extend(payload)
        elif kind == b"IEND":
            require(size == 0 and end == len(data), f"Invalid PNG IEND/trailing data: {path}")
        elif kind == b"PLTE":
            require(
                b"PLTE" not in chunks
                and b"IDAT" not in chunks
                and 0 < size <= 768
                and size % 3 == 0,
                f"Invalid PNG palette: {path}",
            )
        else:
            require(bool(kind[0] & 32), f"Unknown critical PNG chunk: {path} {kind!r}")
        chunks.append(kind)
        offset = end
    require(chunks[-1:] == [b"IEND"] and b"IDAT" in chunks, f"Incomplete PNG: {path}")
    row_size = width * channels + 1
    expected = row_size * height
    decoder = zlib.decompressobj()
    pixels = decoder.decompress(compressed, expected + 1)
    require(
        decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail,
        f"Incomplete/extra PNG compressed stream: {path}",
    )
    require(len(pixels) == expected, f"PNG pixel data length mismatch: {path}")
    require(
        all(pixels[i] <= 4 for i in range(0, expected, row_size)), f"Invalid PNG filter: {path}"
    )
    return width, height


def check(root: Path = ROOT) -> dict:
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    runtime = (root / "character_runtime/__init__.py").read_text(encoding="utf-8")
    require(f'__version__ = "{version}"' in runtime, "Runtime/package version mismatch")
    for name in ("plugin.yaml", "metadata.yaml"):
        metadata = (root / name).read_text(encoding="utf-8")
        require(
            re.search(r"(?m)^name: agentcosplay$", metadata) is not None,
            "Native plugin name mismatch",
        )
        require(f"version: {version}\n" in metadata, "Native plugin version mismatch")
    require(
        "  - post_llm_call\n" in (root / "plugin.yaml").read_text(),
        "Missing Hermes generation hook declaration",
    )
    require((root / "main.py").is_file(), "Missing AstrBot native entry")
    require(
        set(read_json(root / "_conf_schema.json"))
        == {"runtime_url", "token_file", "host_id", "routes_json"},
        "AstrBot configuration mismatch",
    )
    catalog = read_json(root / ".agents/plugins/marketplace.json")
    names = [entry["name"] for entry in catalog["plugins"]]
    require(
        bool(names) and len(names) == len(set(names)), "Empty/duplicate marketplace plugin names"
    )
    assets = {}
    for entry in catalog["plugins"]:
        require(entry["source"]["source"] == "local", "Expected local plugin source")
        plugin = local_path(root, entry["source"]["path"])
        manifest = read_json(plugin / "plugin.json")
        overlay = read_json(plugin / ".codex-plugin/plugin.json")
        require(
            entry["name"] == plugin.name == manifest["name"] == overlay["name"],
            "Marketplace/folder/manifest name mismatch",
        )
        require(manifest["version"] == overlay["version"] == version, "Plugin version mismatch")
        require(manifest["description"] == overlay["description"], "Plugin description mismatch")
        require(
            re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", manifest["name"]) is not None,
            "Invalid plugin name",
        )
        require(bool(overlay["author"]["name"].strip()), "Missing plugin author")
        require(bool(manifest["description"].strip()), "Missing plugin description")
        interface = manifest["extensions"]["com.openai"]["interface"]
        require(interface == overlay["interface"], "Plugin interface mismatch")
        for field in (
            "displayName",
            "shortDescription",
            "longDescription",
            "developerName",
            "category",
        ):
            require(
                isinstance(interface[field], str) and bool(interface[field].strip()),
                f"Missing interface {field}",
            )
        require(
            re.fullmatch(r"#[0-9A-Fa-f]{6}", interface["brandColor"]) is not None,
            "Invalid plugin brand color",
        )
        website = urlsplit(interface["websiteURL"])
        require(website.scheme == "https" and bool(website.netloc), "Invalid plugin website URL")
        prompts = interface["defaultPrompt"]
        require(
            isinstance(prompts, list)
            and 1 <= len(prompts) <= 3
            and all(isinstance(prompt, str) and 0 < len(prompt) <= 128 for prompt in prompts),
            "Invalid plugin default prompts",
        )
        require(interface["logo"] == "./assets/logo.png", "Unexpected logo path")
        require(interface["composerIcon"] == "./assets/composer-icon.png", "Unexpected icon path")
        for field in ("logo", "composerIcon"):
            path = local_path(plugin, interface[field])
            size = check_png(path)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if field == "logo":
                require(digest == RELEASE_LOGO_SHA256, "Release logo integrity mismatch")
            else:
                require(size in ((128, 128), (256, 256)), "Composer icon must be 128px or 256px")
            assets[field] = {"size": size, "sha256": digest}
        skills = local_path(plugin, overlay["skills"])
        skill_files = list(skills.rglob("SKILL.md"))
        require(len(skill_files) == 1, "Expected one primary Skill")
        skill_names = []
        for skill in skill_files:
            text = skill.read_text(encoding="utf-8")
            name = re.search(r"\A---\nname: ([a-z0-9-]+)\n", text)
            require(name is not None and "\n---\n" in text[4:], f"Invalid Skill metadata: {skill}")
            require(
                re.search(r"(?m)^description: \S.+$", text.split("\n---\n", 1)[0]) is not None,
                f"Missing Skill description: {skill}",
            )
            skill_names.append(name.group(1) if name else "")
            require(skill_names[-1] == skill.parent.name, "Skill name/folder mismatch")
        require(len(skill_names) == len(set(skill_names)), "Duplicate Skill names")
        for document in skills.rglob("*.md"):
            for target in re.findall(r"\]\(([^)]+)\)", document.read_text(encoding="utf-8")):
                link = urlsplit(target)
                if not link.scheme and not link.netloc and link.path:
                    resolved = (document.parent / unquote(link.path)).resolve()
                    require(
                        resolved.is_relative_to(plugin) and resolved.is_file(),
                        f"Missing/unsafe Skill link: {document}: {target}",
                    )
    return {"ok": True, "version": version, "plugins": names, "assets": assets}


def main() -> None:
    try:
        print(json.dumps(check(), ensure_ascii=False))
    except (OSError, ValueError, KeyError, TypeError, zlib.error) as error:
        print(f"Plugin check failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
