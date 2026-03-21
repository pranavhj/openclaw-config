# openclaw-config — Terminal Claude Instructions

You are working on the openclaw configuration repo. Follow these rules for every fix or change.

## After fixing anything

1. Create or update the issue file:
   - New bug/fix → `issues/OC-NNN-<slug>.md` (next available number from ISSUES.md)
   - Update existing → edit the relevant `issues/OC-NNN-*.md`

2. Update `ISSUES.md` index with the new/updated row.

3. Sync live configs and commit:
   ```bash
   bash scripts/sync-from-live.sh
   git add -A
   git commit -m "fix(OC-NNN): description"
   git push
   ```

Commit format: `<type>(<scope>): <description>`
- type: `fix` | `feat` | `config` | `sync` | `docs` | `misc`
- scope: `OC-NNN` (issue ID) or `misc` | `docs`

## Issue file format

```markdown
# OC-NNN — Title

**Type:** bug | feature | config
**Status:** open | fixed | wontfix
**Severity:** high | medium | low

## Symptom
What the user observed.

## Root Cause
Why it happened.

## Fix
What was changed.

## Files Changed
- path/to/file
```

## Live config paths (authoritative)

| What | Path |
|------|------|
| Gateway config | `/home/pranav/.openclaw/openclaw.json` |
| Gemini routing | `/home/pranav/.openclaw/BOOT.md` + `workspace/AGENTS.md` |
| Skills | `/home/pranav/.openclaw/workspace/skills/<name>/SKILL.md` |
| Delegate script | `/home/pranav/.local/bin/delegate` |

Check open issues before starting: `cat ISSUES.md`
