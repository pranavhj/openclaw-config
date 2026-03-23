# OC-015 — Delegate exec failed on apostrophes (shell parse error)

**Type:** bug
**Status:** fixed
**Severity:** medium

## Symptom
Messages containing apostrophes (e.g. "I'm", "don't") caused shell parse errors when Gemini wrapped them in single quotes in the exec command.

## Root Cause
Gemini wrapped the message argument in single quotes: `delegate discord 123 'I'm looking for software'` — the apostrophe in "I'm" terminated the quote early, causing a bash syntax error.

## Fix
1. SKILL.md updated to instruct Gemini to NEVER use single quotes around the message
2. Delegate script sanitizes apostrophes by replacing `'` with Unicode U+2019 (RIGHT SINGLE QUOTATION MARK) and backticks with U+2018

## Files Changed
- `/home/pranav/.openclaw/workspace/skills/delegate/SKILL.md`
- `/home/pranav/.local/bin/delegate`
