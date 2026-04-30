# openclaw-config -- Terminal Claude Instructions

You are working on the openclaw configuration repo at `D:\MyData\Software\openclaw-config\`.
Follow these rules for every fix or change.

## After fixing anything

1. Create or update the issue file:
   - New bug/fix: `issues/OC-NNN-<slug>.md` (next available number from ISSUES.md)
   - Update existing: edit the relevant `issues/OC-NNN-*.md`

2. Update `ISSUES.md` index with the new/updated row.

3. If you edited `C:\Users\prana\projects\openclaw\CLAUDE.md`, copy it to `agents\openclaw-CLAUDE.md`.

4. Commit and push:
   ```
   git add -A
   git commit -m "fix(OC-NNN): description"
   git push
   ```

Commit format: `<type>(<scope>): <description>`
- type: `fix` | `feat` | `config` | `sync` | `docs` | `misc`
- scope: `OC-NNN` (issue ID) or `misc` | `docs`

## Issue file format

```markdown
# OC-NNN -- Title

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

## Live config paths (Windows -- authoritative)

| What | Path |
|------|------|
| Bot config (token) | `C:\Users\prana\.openclaw\openclaw.json` |
| Discord bot | `D:\MyData\Software\openclaw-config\bin\discord-bot.py` |
| Discord sender | `D:\MyData\Software\openclaw-config\bin\discord-send.py` |
| Delegate script | `D:\MyData\Software\openclaw-config\bin\delegate.py` |
| openclaw CLAUDE.md | `C:\Users\prana\projects\openclaw\CLAUDE.md` |
| Logs | `C:\Users\prana\AppData\Local\openclaw\` |

On Windows, repo = live. No sync script needed.

## Starting/restarting bot

NSSM service is broken (logon failure -- OC-027). Run manually:
```
python D:\MyData\Software\openclaw-config\bin\discord-bot.py
```
Or restart a running bot: `python D:\MyData\Software\openclaw-config\bin\restart-bot.py`

Check open issues before diagnosing: read `ISSUES.md`
