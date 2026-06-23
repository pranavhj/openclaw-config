# OC-035 -- agent-smart.py: disable auto-compaction, raise threshold to 1MB

**Type:** feature
**Status:** fixed
**Severity:** low

## Symptom
agent-smart.py auto-compacted sessions at 200KB (THRESHOLD_KB=200) and always kept the last 10 pairs (KEEP_PAIRS=10). This caused Claude to lose earlier conversation context without the user choosing to compact, and the 200KB threshold was too aggressive — sessions hit it frequently.

## Root Cause
Design decision from original implementation: auto-compact was intended as a safety valve to prevent context exhaustion. In practice it trims context the user may still need and runs without user consent.

## Fix
Three changes to `bin/agent-smart.py`:

1. **Threshold raised to 1MB**: `THRESHOLD_KB = 200` → `THRESHOLD_BYTES = 1_000_000`. Warning fires when session exceeds 1MB.

2. **No auto-compaction**: Removed `KEEP_PAIRS = 10` constant and the auto-compact trigger. `maybe_compact()` replaced by two separate functions:
   - `check_session_size()` — only logs a warning if >1MB; no file modification
   - `compact_session()` — performs actual compaction (same logic as before); only called when `--keep-pairs` is passed

3. **`--keep-pairs` is opt-in only**: Default changed from `KEEP_PAIRS=10` to `None`. Compaction only happens when the caller explicitly passes `--keep-pairs N`. Without it, agent-smart just warns and continues.

**New behavior summary:**
- Normal run: check size, warn if >1MB, pass through to claude unchanged
- With `--keep-pairs 5`: compact to last 5 pairs, then run claude

## Files Changed
- `bin/agent-smart.py`
