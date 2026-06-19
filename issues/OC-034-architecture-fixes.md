# OC-034 -- Architecture fixes: log dates, config user, project discovery, discord retry

**Type:** bug + feature
**Status:** fixed
**Severity:** low

## Symptom
Four low-priority architecture issues identified in analysis (2026-06-19):
1. `gateway-delegate.py` used UTC for log file dates while `delegate.py`/`discord-bot.py` used local time — on IST (+5:30) gateway logs landed in a different file, confusing nightly audit.
2. `ALLOWED_USER` hardcoded in `discord-bot.py` — not read from config despite `allowFrom` list in `openclaw.json`.
3. Project discovery duplicated: `delegate.py` had its own inline scan (FILTERED_ROOTS, UNFILTERED_ROOTS, EXCLUDE_NAMES) that mirrored `project_list.py`. Root dir changes required edits in two places.
4. `discord-send.py` had no retry — any transient Discord 5xx/429/URLError caused silent message loss.

## Root Cause
Incremental development: each script was written independently without back-references to shared modules or config.

## Fix
1. **gateway-delegate.py**: Changed `_tl()` to use `datetime.now()` (local time) for the log file date. Event timestamps inside logs remain UTC.
2. **discord-bot.py**: Read `ALLOWED_USER` from `config['channels']['discord']['allowFrom'][0]` with fallback to the hardcoded value.
3. **delegate.py**: Added `sys.path.insert(0, str(SCRIPT_DIR))` + `from project_list import discover_projects`. Replaced 30-line inline discovery loop in `_run()` with `discover_projects()` call. Updated `test_delegate.py` to check `project_list.py` for discovery internals.
4. **discord-send.py**: Added `import time` and retry loop in `_do_request()` — up to 3 attempts with exponential backoff (2s, 4s) on HTTP 429/5xx and URLError.

## Files Changed
- `bin/gateway-delegate.py`
- `bin/discord-bot.py`
- `bin/delegate.py`
- `bin/discord-send.py`
- `tests/test_delegate.py`
