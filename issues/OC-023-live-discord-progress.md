# OC-023 — Real-time Discord Progress Display

**Type:** feature
**Status:** fixed
**Severity:** medium

## Symptom
When Claude works on a project task via Discord, the user sees nothing until the final response
arrives (which could be 5–15 minutes). No feedback that work is in progress.

## Root Cause
`discord-send.py` only supported POST (new messages); `delegate.py` sent nothing until the agent
finished; `discord-bot.py`'s watcher only printed tool calls to stdout.

## Fix

Three-file change implementing a live status message edited in-place every ~3 seconds:

### `bin/discord-send.py`
- Added `--edit MESSAGE_ID` argument — uses PATCH to edit an existing message instead of POST
- On successful POST, prints `MSG_ID:<snowflake>` to stdout so callers can capture the message ID

### `bin/delegate.py`
- After acquiring the lock, sends `🔄 Working…` via `discord-send.py` and captures the `MSG_ID`
- Writes `active-session.json` to `LOGDIR` with `{target, status_message_id, project, ts_start}`
- In the `finally` block, deletes `active-session.json` so the watcher knows the session ended

### `bin/discord-bot.py`
- Added module-level state: `LOGDIR`, `ACTIVE_SESSION_FILE`, `TOOL_ICONS`, `_status_events`,
  `_last_edit_ts`, `_active_session`, `_session_start_mono`
- Added `_edit_status(session, elapsed_s, done)` — PATCH edits the status message with a header
  and up to 5 spoiler-tagged tool events
- Extended `watch_claude_sessions()`:
  - Each 1-second tick reads `active-session.json`; detects session start/end
  - Max-age guard: files older than 30 minutes are cleaned up (crash recovery)
  - Tool events from JSONL are appended to `_status_events` (rolling window of last 5)
  - Status message is edited at most once per 3 seconds
  - On session end (file gone), final edit to `✅ Done Xs · project`

### What it looks like

**While working** (edited in-place every ~3s):
```
🔄 Working… `45s` · cricket_analyzer
||🔧 **Bash**: python synthetic/test_velocity.py||
||📝 **Edit**: core/frame_processor.py||
||📖 **Read**: ui/stats_panel.py||
```

**When done**:
```
✅ Done `2m 15s` · cricket_analyzer
```

The actual response still arrives as a separate message from `discord-send.py` (unchanged).

## Edge Cases Handled
- `discord-send.py` fails → no `active-session.json` → no status, silent degradation
- Status edit rate-limited → logged at DEBUG, retried next 3-second cycle
- `delegate.py` crashes → active-session.json left; max-age guard cleans up after 30 min
- Second simultaneous message → still gets "Still working…" as before; no duplicate status

## Files Changed
- `bin/discord-send.py`
- `bin/delegate.py`
- `bin/discord-bot.py`
- `tests/test_delegate.py` (tests 27–28)
