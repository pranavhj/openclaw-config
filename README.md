# openclaw-config

Source control for the openclaw gateway: configs, skills, agent prompts, and issue tracker.

## Structure

```
config/
  openclaw.json          # Gateway config (secrets redacted — use .env for real values)
workspace/
  AGENTS.md              # Gemini workspace routing rules
  skills/
    delegate/            # Core delegation skill — routes to Claude
    discord-send/        # Direct Discord message skill
    quota/               # Gemini quota checker
    gemini-requests/     # Real-time quota via exec-dispatch
    routing-audit/       # Run test suite and audit logs
agents/
  openclaw-CLAUDE.md     # Claude config for projects/openclaw/ (openclaw_claude agent)
  projects-CLAUDE.md     # Claude config for projects/*/ (sub-session override)
bin/
  delegate               # Delegation script — Gemini calls this, it invokes Claude
  route-audit            # Log analysis script
  run-tests              # Full test suite runner
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
| `workspace/AGENTS.md` | `~/.openclaw/workspace/AGENTS.md` |
| `workspace/skills/*/SKILL.md` | `~/.openclaw/workspace/skills/*/SKILL.md` |
| `agents/openclaw-CLAUDE.md` | `~/projects/openclaw/CLAUDE.md` |
| `agents/projects-CLAUDE.md` | `~/projects/CLAUDE.md` |
| `bin/delegate` | `~/.local/bin/delegate` |
| `bin/route-audit` | `~/.local/bin/route-audit` |
| `bin/run-tests` | `~/.local/bin/run-tests` |

## Workflow

### Making a config change

1. Edit the file in this repo
2. Reference the issue ID in your commit: `fix(OC-001): description`
3. Run `scripts/sync-to-live.sh` to deploy
4. Restart gateway if needed: `systemctl --user restart openclaw-gateway`

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
- `sync(OC-003): allowBundled set to __none__ to disable bundled skills`

## Secrets

`config/openclaw.json` uses `${VAR_NAME}` placeholders. Store real values in `~/.openclaw/.env` (gitignored).

## Issues

See [ISSUES.md](ISSUES.md) for the full tracker.
Open bugs: OC-001 (retry count wontfix), OC-002 (silent drop on RPM exhaustion). 18 issues tracked.
