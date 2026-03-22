---
name: delegate
description: "Delegate ANY non-trivial request. Run exec with yieldMs:120000 (wait up to 2 minutes for Claude to respond): delegate <channel> <target> <full message verbatim>. Example: exec({command:\"delegate discord 1482473282925101217 What is the speed of light?\", yieldMs:120000}). NEVER wrap the message in single quotes — pass words unquoted. When exec returns SENT, stop — do not read any file first, just exec delegate directly. Use for: questions, explanations, coding, debugging, analysis, writing, math — anything non-trivial."
---

# Delegate Skill

Run this exec command with `yieldMs:120000`:

```
delegate <channel> <target> <user's full original message, verbatim>
```

Parameters to pass to exec tool:
- `command`: `delegate <channel> <target> <message>`
- `yieldMs`: `120000` (wait up to 2 minutes — Claude needs time to respond)

Example exec call:
```json
{"command": "delegate discord 1482473282925101217 Write a fizzbuzz program in C++", "yieldMs": 120000}
```

**IMPORTANT: Pass yieldMs:120000 — do NOT use background:true or default yieldMs (10s is too short). Wait for SENT.**

**QUOTING: NEVER wrap the message argument in single quotes. Pass the message as unquoted words. Apostrophes (e.g. "I'm", "don't") must NOT be surrounded by single quotes in the shell command — just pass them literally.**

Correct: `delegate discord 123 I'm looking for software`
Wrong:   `delegate discord 123 'I'\''m looking for software'`

When exec returns any result, stop immediately. No quota footer. No further tool calls. Claude already delivered the response.
