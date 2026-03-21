# OC-012 — Gemini does second model turn after exec(delegate) returns error

**Type:** bug
**Status:** fixed
**Reported:** 2026-03-20
**Fixed:** 2026-03-20

## Description

After exec(delegate) returns an error (e.g., all models 429, "All models failed (3)"),
Gemini runs a second model turn to "handle" the error. This causes:

1. A typing indicator to appear in Discord after the error message was already sent
2. A second embedded runner attempt that also hits rate limits or produces unexpected output

## Root cause

BOOT.md and AGENTS.md only instructed Gemini to stop after `exec returns SENT`. No
instruction covered the error case. When exec returns a non-SENT result, Gemini had
no explicit stop rule and defaulted to continuing — attempting to report or handle the
error itself.

This is the same class of bug as OC-011 (second turn after SENT) but triggered by
exec failure rather than exec success.

## User-visible symptom

- API rate limit error appears in Discord (sent by gateway fallback)
- THEN "openclaw agent is typing" indicator appears — Gemini is still processing

If Gemini had exited after exec, no typing indicator would appear.

## Fix

Changed both BOOT.md and AGENTS.md from:
```
After exec returns SENT, stop immediately. Output nothing. Do not run any further commands.
```

To:
```
After exec returns any result (SENT, error, or anything else), stop immediately.
Output nothing. Do not run any further commands. Do not attempt to handle errors.
```

The gateway is responsible for error routing — Gemini should never try to handle exec failures.
