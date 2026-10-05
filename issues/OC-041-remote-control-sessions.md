# OC-041 -- Start/resume Claude Remote Control sessions from Discord

**Type:** feature
**Status:** fixed
**Severity:** medium

## Symptom
Claude Code Remote Control (claude.ai/code, mobile app) replaces much of the Discord
delegate pipeline, but there was no way to start a Remote Control session remotely:
new projects, or projects whose terminal was closed, needed someone at the PC.

## Root Cause
No launcher. Verified behaviour (claude 2.1.289, 2026-10-05):
- `claude --bg --remote-control -n NAME` runs headless; ~/.claude/sessions/<pid>.json gets
  `bridgeSessionId` once connected (terminal sessions with /remote-control have it too).
- `--bg --resume <id> --remote-control` on a closed conversation keeps the SAME session id
  and the same bridge id across restarts.
- `--bg --resume <id>` with no flags wakes a stopped bg session with its saved options;
  adding flags (or resuming a running session) starts a COPY.
- Untrusted folders fail ("Workspace not trusted") until
  ~/.claude.json projects["C:/fwd/path"].hasTrustDialogAccepted = true. Only ~10 folders
  were trusted, so this affects existing projects too.
- A running session cannot be switched to Remote Control from outside (peer messages are
  held and are not slash commands).
- User setting `remoteControlAtStartup: true` (~/.claude/settings.json; project settings
  cannot set it) turns RC on for every new session.

## Fix
Deterministic Discord `rc` command in discord-bot.py (bypasses triage), backed by
bin/rc_sessions.py (CLI/session logic) and bin/rc_commands.py (parse/format, pure).

| # | Case | Handling |
|---|------|----------|
| 1 | New project | `rc create <name>` -> asks root (numbered) -> folder + git + PROGRESS.md -> trust -> start |
| 2 | Folder with conversations | `rc <project>` -> numbered list (title, date, turns, terminal/Discord, live markers) -> reply number |
| 3 | No conversations / fresh | `rc <project> new` or `0` -> trust -> start |
| 4 | Already live on RC | link returned, nothing started |
| 5 | Open in terminal without RC | offers `takeover` (idle only: end terminal claude, resume same id) or `copy` |
| 6 | Background session | woken without flags; copy fallback if it never had RC |
| 7 | Ambiguous name | candidate list; unrelated "rc ..." text falls through to normal routing |
| 8 | Bridge never connects | session stopped, log tail reported |
| 9 | Discord msg to project live on RC | link returned instead of delegating; `!` prefix forces Discord |
| 10 | Reboot | `rc restore` brings back bot-started sessions (registry: %LOCALAPPDATA%\openclaw\rc-registry.json) |
| 11 | Housekeeping | `rc list`, `rc stop <project>` (bg sessions only; also drops them from the restore list) |

Default permission mode: bypassPermissions (user decision 2026-10-05).
Logs: %LOCALAPPDATA%\openclaw\rc-sessions.log + timeline events `rc_*`.

## Open / unverified
- Link format `https://claude.ai/code/<bridgeSessionId>` is assumed, not confirmed.
- Takeover's process kill not tested live against a real terminal (pid identity is checked via procStart before killing; only idle interactive sessions are killed).

## Files Changed
- bin/rc_sessions.py (new)
- bin/rc_commands.py (new)
- bin/discord-bot.py
- bin/run-tests.py
- tests/test_rc_sessions.py (new)
- tests/test_rc_commands.py (new)
