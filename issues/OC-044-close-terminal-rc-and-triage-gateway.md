# OC-044 -- Close terminal Remote Control sessions from Discord; triage gateway not running

**Type:** feature
**Status:** fixed
**Severity:** medium

## Symptom
1. "Close 002b harden guard" (a Claude terminal session with Remote Control on, in claudeInfra)
   was routed correctly to `rc stop claudeinfra`, but the bot replied "No Remote Control
   background sessions running there (terminal sessions are left alone)" and did nothing.
2. Every message logged a triage error (`localhost:18789` connection refused), ~4s wasted,
   routing fell back to continuity (the close request went to `searchproduct`).

## Root Cause
1. `stop_rc_in_dir` only stops background (`--bg`) sessions by design (OC-041); terminal
   sessions had no path at all, and the reply hid that one was running.
2. `bin/llm-gateway.py` was never started: its NSSM service was not installed (NSSM is broken,
   OC-027) and nothing else launched it. Logs stopped on 2026-08-17.

## Fix
1. `rc stop <project>` still stops background sessions, then lists terminal sessions with
   Remote Control on and asks:
   - idle → reply `yes` to close (strict "yes" when the router caused the question);
   - busy/shell → refused, but reply `force` to kill anyway (for a hung session).
   Only the user's own reply counts: `close`/`force_close` are in `ROUTER_FORBIDDEN`, and the
   question is cancelled by any other message (a stray "ok" can never close a terminal; the
   router re-submits `rc stop` so the bot asks again). Before each kill the record is re-read
   and pid + procStart re-checked; status is re-checked at close time; records without
   procStart are never killed. Leftover busy sessions stay in the question so `force` works.
2. `bin/run-gateway.cmd` restart loop; `run-bot.cmd` starts it (unless port 18789 is already
   listening), so the `OpenclawDiscordBot` boot task now runs both. Triage verified live.

Live Discord test (2026-10-06): NL "close the remote control session in closetest" → question
→ `yes` closed idle session; busy session: `yes` refused, `force` killed it.

## Files Changed
- bin/rc_sessions.py (terminal_rc_in_dir, close_terminal, close_terminals)
- bin/rc_commands.py (close pending kind, CLOSE_YES_RE/CLOSE_STRICT_RE/FORCE_RE, formatters)
- bin/discord-bot.py (stop asks about terminals; close/force_close handler)
- agents/remote-control.md
- bin/run-gateway.cmd (new), bin/run-bot.cmd
- tests/test_rc_sessions.py, tests/test_rc_commands.py
