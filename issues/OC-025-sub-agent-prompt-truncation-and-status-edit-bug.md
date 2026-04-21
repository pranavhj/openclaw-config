# OC-025 — Sub-agent prompt truncated + status "Done" edit never fires

**Type:** bug
**Status:** fixed
**Severity:** high

## Symptom

User sent "Let's implement task 5 above in cricket analyzer". Bot replied with
"🔄 Working…" but nothing after — no task response, and the status message
never updated to "✅ Done".

## Root Cause

Three separate bugs:

**1. Sub-agent received only `"## Reply"`**
When the openclaw main agent spawns a sub-agent via Bash tool using
`--print "## Reply\nChannel:..."`, cmd.exe (shell=True) truncates the
argument at the first literal newline. The sub-agent received only `"## Reply"`
and responded "It looks like your message is incomplete."

**2. `client.http.edit_message` wrong signature (discord.py 2.7.1)**
In discord.py 2.7.1, `HTTPClient.edit_message` only accepts
`params: MultipartParameters`, not `**fields`. Calling it with
`content='...'` raised `TypeError`, caught silently at `log.debug`.
Neither the 3-second intermediate updates nor the "Done" final edit
ever reached Discord.

**3. `client.close()` does not exit the Python process**
`watch_restart_signal()` called `await client.close()` but the asyncio
event loop kept running — the Python process never exited, so NSSM
never triggered an auto-restart. Restart hung indefinitely.

## Fix

- **`bin/agent-smart.py`**: Intercept `--print <value>` on Windows and pass
  via stdin instead, bypassing cmd.exe newline truncation (same approach
  as the existing `--print-file` path).

- **`bin/discord-bot.py`**:
  - `_edit_status()`: replace `client.http.edit_message(...)` with
    `client.get_partial_messageable(channel_id).get_partial_message(message_id).edit(content=...)`
    (public API, correct for discord.py 2.x).
  - Changed `log.debug` → `log.warning` for edit failures.
  - `watch_restart_signal()`: replace `await client.close()` with
    `os._exit(0)` — guarantees immediate process exit so NSSM auto-restarts.

- **`bin/delegate.py`**: Added "✅ Done · Xs" edit call in the `finally`
  block as primary/reliable path (doesn't depend on watcher timing).
  `status_msg_id` declared before the outer try so finally can access it.

## Files Changed

- `bin/agent-smart.py`
- `bin/discord-bot.py`
- `bin/delegate.py`
