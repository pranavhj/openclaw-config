# openclaw-config

Source control for the Discord delegation pipeline: configs, agent prompts, scripts, and issue tracker.

## Structure

```
config/
  openclaw.json          # Bot config (secrets redacted -- use ${VAR} placeholders)
agents/
  openclaw-CLAUDE.md     # Claude config for projects/openclaw/ (openclaw_claude agent)
  projects-CLAUDE.md     # Claude config for projects/*/ (sub-session recursion guard)
bin/
  discord-bot.py         # Discord gateway -- listens for DMs, spawns delegate.py
  discord-send.py        # Discord REST sender -- direct HTTP to Discord API v10
  delegate.py            # Delegation orchestrator -- sanitize, lock, build prompt, run Claude
  agent-smart.py         # Auto-compacting Claude wrapper (threshold: 100KB, 3 pairs)
  restart-bot.py         # Bot restart via sc stop + Start-Process (no admin needed)
  bot-logs.py            # Live log viewer (tails bot.log)
  route-audit.py         # Daily log analysis script
  run-tests.py           # Full test suite runner
  session-reset.py       # No-op on Windows (legacy)
workspace/
  AGENTS.md              # Archived -- openclaw-gateway (Gemini) disabled
  skills/                # Archived -- openclaw-gateway (Gemini) disabled
docs/
  openclaw-architecture.md  # Full system architecture
issues/                  # Per-issue detail files
ISSUES.md                # Issue index
```

## Live file paths (Windows)

On Windows, the repo IS the live deployment -- scripts run directly from the repo.

| What | Path |
|------|------|
| Bot config | `C:\Users\prana\.openclaw\openclaw.json` |
| openclaw CLAUDE.md | `C:\Users\prana\projects\openclaw\CLAUDE.md` |
| projects CLAUDE.md | `C:\Users\prana\projects\CLAUDE.md` |
| All scripts | `D:\MyData\Software\openclaw-config\bin\` (live = repo) |
| Logs | `C:\Users\prana\AppData\Local\openclaw\` |

No sync step needed. Edit the repo file and it is immediately live.

## Starting the bot

The NSSM `discord-bot` service has a logon failure and cannot auto-start (see OC-027).
Run manually after each reboot:

```
python D:\MyData\Software\openclaw-config\bin\discord-bot.py
```

To restart a running bot:

```
python D:\MyData\Software\openclaw-config\bin\restart-bot.py
```

## Making a config change

1. Edit the file in this repo (already live)
2. If editing `openclaw/CLAUDE.md`, also copy to `agents/openclaw-CLAUDE.md`:
   ```
   copy C:\Users\prana\projects\openclaw\CLAUDE.md agents\openclaw-CLAUDE.md
   ```
3. Commit and push:
   ```
   git add -A && git commit -m "fix(OC-NNN): description"
   git push
   ```

## Commit convention

```
<type>(<scope>): <description>

Types: fix | feat | config | sync | docs | misc
Scope: OC-NNN (issue ID) or misc | docs | sync
```

## Secrets

`config/openclaw.json` uses `${VAR_NAME}` placeholders. Real values in `C:\Users\prana\.openclaw\openclaw.json` (not committed).

## Issues

See [ISSUES.md](ISSUES.md) for the full tracker.
See [docs/openclaw-architecture.md](docs/openclaw-architecture.md) for system design.
