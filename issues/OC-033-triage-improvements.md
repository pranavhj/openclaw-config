# OC-033 -- Triage improvements: remove unreliable timeouts, always use gateway, opus model

**Type:** feature
**Status:** fixed
**Severity:** medium

## Symptom
The 10-minute conversation continuity window and QA cooldown were unreliable — they caused wrong routing (stale slug reuse) and suppressed valid direct answers unnecessarily. The 500-char message limit on triage excluded longer messages from gateway routing. Router used sonnet model instead of opus.

## Root Cause
- `_CONTINUITY_WINDOW_S = 600`: reused old project slug for follow-up messages, but the window was too wide and caused misrouting
- `_QA_COOLDOWN_S = 600`: suppressed direct answers during conversations, even when the message was clearly a new standalone question
- `len(content.strip()) <= 500`: excluded longer messages from triage, falling back to less accurate keyword matching
- Triage ran even on attachment messages, but couldn't see the files

## Fix
1. **Disabled conversation continuity** (`_CONTINUITY_WINDOW_S = 0`): triage LLM now handles context routing via recent messages history
2. **Removed QA cooldown**: no `_QA_COOLDOWN_S`, no `_in_conversation` check — triage always decides freely
3. **Removed 500-char limit**: gateway triage runs for all message lengths
4. **Skip triage for attachments**: when message has attachments, go straight to delegate (triage can't see files)
5. **Switch to opus model**: delegate.py now uses `--model opus` for the main router
6. **Added concurrency + gateway tests to run-tests.py**: test_per_project_concurrency.py and test_gateway.py now run in the standard suite

## Files Changed
- `bin/discord-bot.py` — removed continuity window, cooldown, 500-char limit; added attachment skip
- `bin/delegate.py` — switched `--model sonnet` to `--model opus`
- `bin/run-tests.py` — added concurrency and gateway test suites
- `tests/test_delegate.py` — updated model check from sonnet to opus
- `tests/test_per_project_concurrency.py` — replaced continuity tests with triage improvement tests
