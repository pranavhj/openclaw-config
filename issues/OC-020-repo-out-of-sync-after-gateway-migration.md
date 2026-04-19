# OC-020 — Repo out of sync after Gemini gateway migration

**Type:** config
**Status:** fixed
**Severity:** medium

## Symptom
After replacing the openclaw gateway + Gemini pipeline with `discord-bot.py`, the repo still described the old architecture. `bin/discord-bot.py`, `bin/discord-send`, `bin/agent-smart`, and `bin/bot-logs` were not tracked. `docs/openclaw-architecture.md` described Gemini as the router with no mention of `discord-bot.py`, `agent-smart`, or the new session watcher.

## Root Cause
The migration to `discord-bot.py` (replacing Gemini) was done live without syncing the config repo. sync-from-live.sh was also missing the new scripts.

## Fix
- Added `bin/discord-bot.py`, `bin/discord-send`, `bin/agent-smart`, `bin/bot-logs` to the repo
- Updated `scripts/sync-from-live.sh` to copy all four new scripts
- Rewrote `docs/openclaw-architecture.md` to reflect the current architecture:
  - Discord → discord-bot.py (systemd) → delegate → agent-smart → Claude (Sonnet)
  - Removed all Gemini/openclaw-gateway references
  - Documented KillMode=process, start_new_session=True, session auto-compaction
  - Updated agent table, config paths, logging, design decisions, risk list

## Files Changed
- `bin/discord-bot.py` (added)
- `bin/discord-send` (added)
- `bin/agent-smart` (added)
- `bin/bot-logs` (added)
- `scripts/sync-from-live.sh` (updated)
- `docs/openclaw-architecture.md` (rewritten)
