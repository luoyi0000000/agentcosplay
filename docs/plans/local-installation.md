# Local-first installation implementation plan

> For agentic workers: use superpowers:executing-plans. Continue the already-authorized implementation in this task; record deviations here.

**Goal:** Install the complete agentcosplay Runtime and host integration from this repository, with local data surviving upgrades, rollback, and uninstall.

**Architecture:** One Python installer stages immutable releases and switches an atomic installation record only after health checks. The existing SQLite Runtime remains the only data system. Host adapters reference a stable local launcher; a shared HTTP endpoint allows multiple gateway clients to reach one Runtime process.

**Tech stack:** Python 3.11+, existing uv lock/MCP/SQLite. Native TOML/YAML/JSON host configuration; no new protocol or cloud service.

**Spec:** User's 2026-09-19 supplementary attachment (13 sections); original schema/roleplay/privacy requirements remain binding. Internal module names and database schema remain compatible.

## Global constraints

- Human and Agent installation use the same repository, installer, core, and data format.
- Runtime data is outside source and installed program trees, with OS-native defaults.
- No author-operated runtime dependency. Downloads are installation/update dependencies only.
- Never print credentials, delete character data on uninstall, or reset data on update.
- A copied Skill or generated adapter is not proof that a host loaded the full Runtime.

## Review focus

1. Failed/interrupted update: previous installation remains selected; data never removed.
2. Repo/data/install path overlap and symlinks: reject unsafe layouts before mutation.
3. Host config conflicts and modified skills: refuse overwrite; keep private backups.
4. Cross-gateway owner/session isolation: only deliberately shared identity and character share memory.
5. Corrupt/future-schema database: refuse startup/rollback without overwriting data.

## Tasks

- [x] Data paths + CLI health: add `character_runtime/paths.py`, test OS defaults and repository exclusion, make CLI use it. Health performs real MCP discovery in an isolated synthetic namespace and leaves no user records.
- [x] Installation: root `install.py` prepares private version directories using `uv sync --locked`; native config helper merges only agentcosplay, records undo data and refuses conflicts. Stable launcher selects verified release. Test install/update failure/rollback/uninstall with a temporary host and persistent record.
- [x] Shared Runtime: exercise two distinct configured MCP clients against one HTTP server and one SQLite store, both directions; preserve export privacy and migration tests.
- [x] Docs and distribution: README, INSTALL.md, AGENTS.md and skills.md route the entire repository request to full installation. Keep marketplace as a host package, not a replacement for Runtime. Update ZIP/version and record actual verification limits.
- [x] Validate clean environment installation, lock, full suite, static checks and upload via connected GitHub API after review.

## Execution notes

- Last interrupted publication verified: remote `ee1064878a567d701b963b32de904ec2b364e9a6`, tree matches the 1.0.1 local snapshot. Public installer completed in an isolated directory.
- That installer only placed a Skill; it is retained as an explicitly named optional skill-only utility, never the full-install default.
- Real Hermes/AstrBot UI testing requires those applications; protocol-client tests will be labelled separately.

## Verification ledger

- Complete isolated install, native config generation, real stdio reconnect, source relocation, one live HTTP process / two clients, update, rollback, uninstall and reinstall passed. All data synthetic; actual host apps were not altered.
- Independent final reviewer reproduced cwd module shadowing, Git-host credential placement, and killed-process lock recovery. Three regression tests failed before fixes and passed after isolation mode, host path guard and kernel-owned locks.
- Ruling: use the existing foreground Runtime and native host configuration; do not add a daemon supervisor. Persistent background operation belongs to the user's existing process manager. It requires that manager for unattended shared HTTP service.
- Ruling: preserve source module/API compatibility and database schema 1. No speculative data migration is needed; unsupported schema versions continue to fail closed.
- Optional marketplace/Skill-only distribution remains explicitly separate from a completed Runtime installation; ChatGPT cloud cannot reach localhost.
