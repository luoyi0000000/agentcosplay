#!/usr/bin/env bash
# Full Runtime installation. The Python installer owns all changes and recovery.
set -euo pipefail
umask 077
command -v git >/dev/null || { echo 'agentcosplay needs Git for repository installation' >&2; exit 1; }
command -v python3 >/dev/null || { echo 'agentcosplay needs Python 3.11+' >&2; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else "Python 3.11+ required")'
task_source="$(mktemp -d)"
trap 'rm -rf -- "$task_source"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
GIT_TERMINAL_PROMPT=0 git clone --quiet --depth 1 https://github.com/luoyi0000000/agentcosplay.git "$task_source/repo"
python3 "$task_source/repo/install.py" "$@"
