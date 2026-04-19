# OC-021 — Migrate openclaw pipeline to Windows (eliminate VM dependency)

**Type:** feature
**Status:** fixed
**Severity:** high

## Symptom
The entire openclaw pipeline (discord-bot.py, delegate, agent-smart, discord-send, session-reset,
route-audit, bot-logs) assumed Linux: bash scripts, /home/pranav paths, /tmp logs, systemd service,
journalctl. Required a running Linux VM (VirtualBox/Ubuntu) to function.

## Root Cause
Original implementation was Linux-native. No Windows-compatible scripts existed.

## Fix
Full port to Windows-native Python. Zero VM dependency.

**New script inventory (all in `D:\MyData\Software\openclaw-config\bin\`):**

| Script | Change | Notes |
|--------|--------|-------|
| `discord-send.py` | Rewrite (was bash) | `urllib.request` replaces `curl`; `argparse` replaces `while [[ $# ]]` |
| `session-reset.py` | Rewrite (was bash) | No-op on Windows (no openclaw gateway) |
| `agent-smart.py` | Rewrite (was bash) | `shell=True` on Windows for `.cmd` file invocation; compaction logic ported inline |
| `delegate.py` | Rewrite (was bash) | All bash-isms replaced; `LOCALAPPDATA` log dir; `mkdir` atomic lock; Python timing |
| `bot-logs.py` | New | `tail -f` equivalent for NSSM log; replaces `journalctl -f` |
| `route-audit.py` | Rewrite (was bash) | `sc query` replaces `systemctl`; NSSM log replaces journalctl |
| `discord-bot.py` | Minor edits | Remove hardcoded PATH; platform-specific process detach; call `delegate.py` |
| `openclaw-timeline` | Minor edit | `LOGDIR` updated to `%LOCALAPPDATA%/openclaw` |

**Config changes:**
- `config/openclaw.json`: workspace path → `C:\Users\prana\.openclaw\workspace`
- `agents/openclaw-CLAUDE.md`: all Linux paths → Windows equivalents

**Service management:** NSSM replaces systemd. Setup commands:
```
nssm install discord-bot python.exe
nssm set discord-bot AppParameters D:\MyData\Software\openclaw-config\bin\discord-bot.py
nssm set discord-bot AppDirectory C:\Users\prana
nssm set discord-bot AppStdout C:\Users\prana\AppData\Local\openclaw\bot.log
nssm set discord-bot AppStderr C:\Users\prana\AppData\Local\openclaw\bot.log
nssm set discord-bot AppRotateFiles 1
nssm set discord-bot AppRotateOnline 1
nssm set discord-bot AppRotateBytes 5000000
nssm set discord-bot Start SERVICE_AUTO_START
nssm start discord-bot
```

**Key implementation notes:**
- `agent-smart.py` CWD key: `C:\Users\prana\projects\openclaw` → `C--Users-prana-projects-openclaw`
  (verify by running `claude --continue` in that dir and checking `~/.claude/projects/` dir names)
- On Windows, `claude` is a `.cmd` file (npm install); `shell=True` needed in agent-smart.py
- `delegate.py` uses `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP` (Windows equivalent of `start_new_session=True`)
- Log dir: `C:\Users\prana\AppData\Local\openclaw\` replaces `/tmp/openclaw/`

## Files Changed
- `bin/discord-send.py` (new)
- `bin/session-reset.py` (new)
- `bin/agent-smart.py` (new)
- `bin/delegate.py` (new)
- `bin/bot-logs.py` (new)
- `bin/route-audit.py` (new)
- `bin/discord-bot.py` (edited)
- `bin/openclaw-timeline` (edited)
- `config/openclaw.json` (edited)
- `agents/openclaw-CLAUDE.md` (rewritten)
