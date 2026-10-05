# OC-041 -- Start/resume Claude Remote Control sessions from Discord

**Type:** feature
**Status:** open
**Severity:** medium

## Symptom
Claude Code Remote Control (claude.ai/code, mobile app) replaces much of the Discord
delegate pipeline, but there was no way to start a Remote Control session remotely:
new projects, or projects whose terminal was closed, needed someone at the PC.

## Root Cause
No launcher. Verified (claude 2.1.289): `claude --bg --remote-control -n NAME` runs
headless and records `bridgeSessionId` in ~/.claude/sessions/<pid>.json once connected.
Untrusted folders fail ("Workspace not trusted") until
~/.claude.json projects["C:/fwd/path"].hasTrustDialogAccepted = true.

## Fix
Deterministic Discord `rc` command handled in discord-bot.py (bypasses triage), backed by
bin/rc_sessions.py. Cases:
1. New project (asks for location)            -- pending
2. Existing folder: pick conversation to resume -- pending
3. Fresh session in existing folder (`rc <project> new`) -- done
4-6. Already live with RC / live without RC / stopped bg session -- pending
7. Ambiguous project name -- partial (candidate list)
8. Bridge never connects -- reports log tail
9. Delegate guard when RC live -- pending
10. Restore after reboot -- pending
11. rc list / rc stop -- pending

Default permission mode: bypassPermissions (user decision 2026-10-05).

## Files Changed
- bin/rc_sessions.py (new)
- bin/discord-bot.py
- tests/test_rc_sessions.py (new)
