# openclaw-config

## State
Currently: Android tooling complete and tested; infrastructure stable
Last session: 2026-06-07

## Done
- **Android pipeline built:**
  - `bin/android-deploy.sh` — local build + CI artifact deploy over Tailscale ADB
  - `bin/android-logs.sh` — logcat (default/full/crash modes, `--dump` boolean flag)
  - `bin/android-new.sh` — scaffold new project from skeleton + generate CLAUDE.md
  - `android-skeleton/` — 22-file minimal Android project (AGP 8.2.2, minSdk 24, debug keystore)
  - `agents/android.md` — canonical Android knowledge base
  - `AndroidStudioProjects/TableNew/CLAUDE.md` — project config for TableNew
  - `openclaw/CLAUDE.md` — router updated with Android detection + routing table + android-new.sh
- **Tests:** `tests/run-android-tests.sh` — 152 automated tests, 0 FAIL
- **Live device tests passed:** D9/D10/D11/D12/D13/D19/L9/N30/N31
- **Bugs fixed:** #1 (logs crash), #2 (local.properties), #3 (router crash routing), #4 (deploy exit code)
- **delegate.py:** removed openclaw-config from EXCLUDE_NAMES — now visible as a project

## Next
- E1-E9: End-to-end Discord integration tests (require openclaw stack running)
- D14: Signature mismatch recovery test (install with different keystore first)
- D15-D18: CI path tests (require GitHub Actions successful run for TableNew)

## Key decisions
- Scripts in bin/: system-wide, shared across all Android projects via flags
- APPSLUG placeholder: skeleton text files replaced via sed by android-new.sh
- Tailscale IP 100.122.101.27:5555: always prefer over local IP
- `--dump` flag independent of `--mode` (Bug #1 fix — last --mode wins issue)
- `.gitignore` uses `build/` (not `/build`) to cover app/build/ in scaffolded projects
