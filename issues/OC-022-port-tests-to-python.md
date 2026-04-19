# OC-022 — Port test suites to Windows Python

**Type:** feature
**Status:** fixed
**Severity:** medium

## Symptom

After OC-021 migrated all scripts to Python, the test suite remained as Linux bash scripts
(`tests/test_delegate.sh`, `test_integration.sh`, `test_claude_behavior.sh`) with hard-coded
`/home/pranav` paths, systemctl, Gemini quota checks, and openclaw mock binaries.
Tests were not runnable on Windows.

## Root Cause

Test suite was written for the Linux VM environment and not updated as part of the Windows
migration.

## Fix

Ported all three test suites to Python with Windows-compatible equivalents:

- **`tests/test_delegate.py`** — 80 unit tests, no live prerequisites.
  Uses `importlib.util.spec_from_file_location` to import hyphen-named modules.
  Tests: script presence, imports, CWD key derivation, atomic lock, sanitization,
  `parse_history()`, `ts_ms()`, timeline events in source, config validation,
  CLAUDE.md Windows paths, bin/ integrity, agent-smart shell=True.

- **`tests/test_integration.py`** — Live integration tests.
  Replaces systemctl with `sc query discord-bot` / nssm; uses LOGDIR on Windows;
  checks live delegation, lock deduplication, discord-send, timeline log JSON validity,
  NSSM service health, config sanity.

- **`tests/test_claude_behavior.py`** — Live behavior tests (skipped until stack deployed).
  Replaces openclaw mock binary with `OPENCLAW_TEST_CAPTURE_FILE` env var (added to
  `discord-send.py`). Tests watermark, no-markdown-tables, URL wrapping, special chars,
  project lifecycle, routing integrity. All tests skip gracefully if live config absent.

- **`bin/run-tests.py`** — Test runner.
  Runs all three suites, prints summary, optionally sends Discord notification via `--discord`.

Added `OPENCLAW_TEST_CAPTURE_FILE` env var to `discord-send.py`: when set, successful sends
also append the message to the file (for behavior test inspection without a mock binary).

All files add `sys.stdout = io.TextIOWrapper(..., encoding='utf-8')` to handle Windows
cp1252 console encoding.

## Results (on dev machine, stack not fully deployed)

- Unit tests: **80/80 PASS**
- Integration tests: **18/20 PASS** (2 expected failures: `exit_code: 0` requires full
  stack, discord-bot not yet registered with NSSM)
- Behavior tests: **all SKIP** (live config at `C:\Users\prana\.openclaw\openclaw.json`
  not yet deployed — will run when NSSM service is live)

## Files Changed

- `tests/test_delegate.py` (new)
- `tests/test_integration.py` (new)
- `tests/test_claude_behavior.py` (new)
- `bin/run-tests.py` (new)
- `bin/discord-send.py` — added `OPENCLAW_TEST_CAPTURE_FILE` capture hook
- `ISSUES.md` — added OC-022 row
