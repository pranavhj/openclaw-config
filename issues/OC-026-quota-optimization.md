# OC-026 — Quota Optimization: Stateless Haiku Routing + Lower Compaction Threshold

**Type:** feature
**Status:** fixed
**Severity:** medium

## Symptom
Every Discord message consumed 2 Claude Sonnet API calls:
1. Main routing session via `--continue` — re-read full 283KB JSONL history every message
2. Project sub-session via `--continue` — read project history (up to 400KB)

The 283KB openclaw session history was the biggest waste: re-sent on every message even though
routing doesn't need it — delegate.py already injects the last 5 messages via "## Recent messages".

## Root Cause
- `delegate.py` passed `--continue` to agent-smart.py for the routing call, causing Claude to load
  the full openclaw session history (~283KB) on every single message.
- `--model sonnet` used for routing even though routing is simple classify/dispatch logic.
- Compaction threshold of 400KB meant project sub-sessions accumulated large histories before trimming.

## Fix

### 1. `bin/delegate.py` — stateless Haiku routing
- Removed `--continue` flag → routing call is now stateless (no 283KB JSONL re-read)
- Switched from `sonnet` to `haiku` (~20× cheaper per token)
- "## Recent messages" in the prompt already covers all routing context needs

### 2. `bin/agent-smart.py` — lower compaction threshold
- `THRESHOLD_KB`: 400 → 100
- `KEEP_PAIRS`: 5 → 3
- Project sub-sessions compact earlier, reducing per-call context overhead

### 3. `C:\Users\prana\projects\openclaw\CLAUDE.md` — pin sub-sessions to Sonnet
- Added `--model sonnet` to sub-session spawn command (was implicitly inheriting default)
- Updated comment: `>400KB (keeps last 5 pairs)` → `>100KB (keeps last 3 pairs)`

## Files Changed
- `bin/delegate.py`
- `bin/agent-smart.py`
- `C:\Users\prana\projects\openclaw\CLAUDE.md`
