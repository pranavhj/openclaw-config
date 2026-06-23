# OC-036 -- agent-smart.py dual thresholds + Discord compact command

**Type:** feature
**Status:** fixed
**Severity:** medium

## Symptom
OC-035 overcorrected: it disabled auto-compaction entirely (only warning at 1MB). User clarified the actual intent:
- Auto-compact should still happen — at 1MB (hard limit)
- 200KB should be a warning only (early heads-up, no action)
- keep_pairs should be chosen autonomously (default 5), not left to the user to specify
- A Discord command ("compact <project>") should trigger manual compaction without opening a session

## Fix

### agent-smart.py (bin/agent-smart.py)

Three constants now:
- `WARN_BYTES = 200_000` (200KB) — notice printed, no action
- `COMPACT_BYTES = 1_000_000` (1MB) — auto-compact triggered
- `DEFAULT_KEEP_PAIRS = 5` — pairs kept when compacting autonomously

New function `check_and_maybe_compact(session_dir, keep_pairs)`:
- < 200KB: silent
- 200KB–1MB: prints `[agent-smart] session NNKb >= 195KB — approaching limit`
- ≥ 1MB: prints notice and calls `compact_session()`

`--keep-pairs N` still works as a per-project override. Default is now 5 (not None).

New `--compact-only` flag: compacts the session in the cwd and exits without running claude. Used by the Discord compact command.

### CLAUDE.md (routing)

Added "Compact project session" routing case before "Project work":
- Triggers on: "compact <project>", "compact <project> session", "reset context <project>"
- Router matches project → runs `(cd <path> && python agent-smart.py --compact-only)` → sends output to Discord

Also updated the stale "100KB" comment in the "How it works" paragraph to reflect actual thresholds.

## Files Changed
- `bin/agent-smart.py`
- `agents/openclaw-CLAUDE.md` (synced from C:\Users\prana\projects\openclaw\CLAUDE.md)
