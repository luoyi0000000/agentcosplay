#!/usr/bin/env bash
# Installs the conversation Skill only. No daemon, credentials or global config edits.
set -euo pipefail
umask 077

fail() { echo "agentcosplay: $*" >&2; exit 1; }
host="auto"
skills_dir=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --host) [ "$#" -ge 2 ] || fail "--host 缺少参数"; host="$2"; shift 2 ;;
    --skills-dir) [ "$#" -ge 2 ] && [ -n "$2" ] || fail "--skills-dir 缺少路径"; skills_dir="$2"; shift 2 ;;
    --help) echo "install-skill.sh [--host hermes|codex] [--skills-dir PATH]"; exit 0 ;;
    *) fail "未知参数：$1" ;;
  esac
done
case "$host" in auto|hermes|codex) ;; *) fail "不支持的宿主：$host" ;; esac
if [ -z "$skills_dir" ]; then
  if [ "$host" = auto ]; then
    candidates=()
    if [ -d "${HERMES_HOME:-$HOME/.hermes}" ]; then candidates+=(hermes); fi
    if [ -d "${CODEX_HOME:-$HOME/.codex}" ]; then candidates+=(codex); fi
    [ "${#candidates[@]}" -eq 1 ] || fail "无法唯一识别宿主；让 Agent 按 skills.md 选择目标。"
    host="${candidates[0]}"
  fi
  case "$host" in
    hermes) skills_dir="${HERMES_HOME:-$HOME/.hermes}/skills" ;;
    codex) skills_dir="${CODEX_HOME:-$HOME/.codex}/skills" ;;
  esac
fi

for cmd in curl unzip mktemp diff; do command -v "$cmd" >/dev/null || fail "缺少 $cmd"; done
if command -v shasum >/dev/null; then
  hash_cmd=(shasum -a 256)
elif command -v sha256sum >/dev/null; then
  hash_cmd=(sha256sum)
else
  fail "缺少 SHA-256 校验工具"
fi
mkdir -p -- "$skills_dir"
skills_dir="$(cd -- "$skills_dir" && pwd -P)"
target="$skills_dir/agentcosplay"
[ ! -L "$target" ] || fail "拒绝覆盖符号链接 $target"
lock="$skills_dir/.agentcosplay-install.lock"
mkdir -- "$lock" 2>/dev/null || fail "另一安装正在运行，或上次安装被强制终止；请检查 $lock"
staging=""
cleanup() {
  if [ -n "$staging" ]; then rm -rf -- "$staging"; fi
  rmdir -- "$lock"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
staging="$(mktemp -d "$skills_dir/.agentcosplay-XXXXXXXX")"
archive="$staging/skill.zip"
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
  --connect-timeout 15 --max-time 120 \
  https://raw.githubusercontent.com/luoyi0000000/agentcosplay/main/downloads/agentcosplay-skill.zip \
  -o "$archive"
expected_sha256="92e6dd4a91d6a1a5ce0cb6796992afbb4ef46c47b59985a60a702651e92f6473"
actual_sha256="$("${hash_cmd[@]}" "$archive")"
[ "${actual_sha256%% *}" = "$expected_sha256" ] || fail "下载校验失败，现有技能未更改。请重新获取安装器。"
unzip -q "$archive" -d "$staging/unpacked"
source_dir="$staging/unpacked/agentcosplay"
[ -f "$source_dir/SKILL.md" ] || fail "安装包缺少 SKILL.md"
if [ -e "$target" ]; then
  if diff -qr "$source_dir" "$target" >/dev/null; then
    echo "agentcosplay 已是当前版本。新会话中选择此 Skill 即可聊天。"
    exit 0
  fi
  fail "已存在不同版本或用户修改：${target}；保留原文件，请让 Agent 备份后更新。"
fi
mv -- "$source_dir" "$target"
echo "agentcosplay Skill 已安装到 $target"
echo "请在新会话中启用/选择 agentcosplay。当前会话角色对话可用；未启用跨会话记忆。"
