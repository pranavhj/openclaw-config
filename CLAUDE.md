# openclaw-config — infrastructure sub-session

You are working on the openclaw configuration repo at `D:\MyData\Software\openclaw-config\`.
Do NOT do project detection or spawn sub-sessions.

## Sub-session rules
1. Skim `PROGRESS.md` for current state
2. Do the work (edit files in this directory)
3. Update `PROGRESS.md`
4. Send response via `discord-send.py`
5. Output: SENT

Send using:
```
python D:\MyData\Software\openclaw-config\bin\discord-send.py --target <target> --message "<text>"
```

---

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
| openclaw CLAUDE.md | `C:\Users\prana\projects\openclaw\CLAUDE.md` (git: github.com/pranavhj/openclaw) |
| Logs | `C:\Users\prana\AppData\Local\openclaw\` |

On Windows, repo = live. No sync script needed.

## Starting/restarting bot

NSSM service is broken (logon failure -- OC-027). Run manually:
```
python D:\MyData\Software\openclaw-config\bin\discord-bot.py
```
Or restart a running bot: `python D:\MyData\Software\openclaw-config\bin\restart-bot.py`

Check open issues before diagnosing: read `ISSUES.md`

---

## Quick invoke

```bash
# Run full automated test suite (152 tests)
bash /d/MyData/Software/openclaw-config/tests/run-android-tests.sh

# Sync router backup after editing openclaw/CLAUDE.md
cp /c/Users/prana/projects/openclaw/CLAUDE.md /d/MyData/Software/openclaw-config/agents/openclaw-CLAUDE.md
```

---

## Android tooling (added 2026-06-07)

System-wide scripts in `bin/` shared across all Android projects. Each project's CLAUDE.md references them with project-specific flags.

**Files:**
- `bin/android-deploy.sh` — build APK locally or download CI artifact, ADB install over Tailscale
- `bin/android-logs.sh` — logcat by mode (default/full/crash) + `--dump` boolean for snapshot vs streaming
- `bin/android-new.sh` — scaffold new project from `android-skeleton/` with APPSLUG replacement + CLAUDE.md generation
- `android-skeleton/` — 22-file template (AGP 8.2.2, Gradle 8.2, minSdk 24, targetSdk 34, debug keystore)
- `agents/android.md` — canonical knowledge base: paths, versions, templates, troubleshooting
- `tests/run-android-tests.sh` + `tests/android-test-cases.md` — 152 automated tests + manual tracking

**Device:** Tailscale `100.122.101.27:5555` (always use); local `10.0.0.122:5555` (may change)

**android-deploy.sh:** reads applicationId from app/build.gradle automatically; signature mismatch recovery built-in
**android-logs.sh:** `--dump` is a boolean flag independent of `--mode`; `--mode dump` is legacy alias for `--mode default --dump`
**android-new.sh:** writes `local.properties` for CLI builds; generated CLAUDE.md has all 7 quick invoke entries

**Known projects using this tooling:** `AndroidStudioProjects/TableNew`
