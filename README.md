# openclaw-config

Source control for the Discord delegation pipeline: configs, agent prompts, scripts, and issue tracker.

## Structure

```
config/
  openclaw.json          # Bot config (secrets redacted — use .env for real values)
workspace/
  AGENTS.md              # Archived — openclaw-gateway disabled
  skills/                # Archived — openclaw-gateway disabled
agents/
  openclaw-CLAUDE.md     # Claude config for projects/openclaw/ (openclaw_claude agent)
  projects-CLAUDE.md     # Claude config for projects/*/ (sub-session override)
bin/
  delegate               # Delegation script — called by discord-bot, invokes Claude
  discord-bot.py         # Discord gateway — listens for DMs, calls delegate
  discord-send           # Discord REST sender — curl wrapper around Discord API v10
  route-audit            # Log analysis script
  run-tests              # Full test suite runner
  session-reset          # Gemini session reset (legacy, no-op)
config/
  systemd/user/
    discord-bot.service  # Systemd service for discord-bot.py
scripts/
  sync-from-live.sh      # Pull live configs into repo
  sync-to-live.sh        # Deploy repo configs to live paths
issues/                  # Bug and feature tracker
ISSUES.md                # Issue index
```

## Live file paths

| Repo path | Live path |
|-----------|-----------|
| `config/openclaw.json` | `~/.openclaw/openclaw.json` |
| `agents/openclaw-CLAUDE.md` | `~/projects/openclaw/CLAUDE.md` |
| `agents/projects-CLAUDE.md` | `~/projects/CLAUDE.md` |
| `bin/delegate` | `~/.local/bin/delegate` |
| `bin/discord-bot.py` | `~/.local/bin/discord-bot.py` |
| `bin/discord-send` | `~/.local/bin/discord-send` |
| `bin/route-audit` | `~/.local/bin/route-audit` |
| `bin/run-tests` | `~/.local/bin/run-tests` |
| `config/systemd/user/discord-bot.service` | `~/.config/systemd/user/discord-bot.service` |

## Workflow

### Making a config change

1. Edit the file in this repo
2. Reference the issue ID in your commit: `fix(OC-001): description`
3. Run `scripts/sync-to-live.sh` to deploy
4. Restart bot if needed: `systemctl --user restart discord-bot`

### Pulling in live changes

```bash
bash scripts/sync-from-live.sh
git add -A && git commit -m "sync(OC-NNN): description"
git push
```

## Commit convention

```
<type>(<issue>): <description>

Types: fix | feat | config | sync | docs
```

Examples:
- `fix(OC-001): set agents.retry.attempts to reduce RPM burn`
- `feat(OC-008): add per-project session isolation`
- `sync(misc): update delegate script`

## Secrets

`config/openclaw.json` uses `${VAR_NAME}` placeholders. Store real values in `~/.openclaw/.env` (gitignored).

## Issues

See [ISSUES.md](ISSUES.md) for the full tracker.
