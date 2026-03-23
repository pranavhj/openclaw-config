# OC-016 — Newlines in user messages break delegate exec command

**Type:** bug
**Status:** fixed
**Severity:** high

## Symptom
Multi-line Discord messages silently failed to delegate. Gateway log showed: `Exec failed (code 127) :: /bin/bash: line 2: I: command not found`. User received no response.

## Root Cause
When a user's Discord message contains newline characters, Gemini passed them verbatim in the exec command string. Bash interpreted the literal newline as a command separator — everything after the first newline became a separate command. Example:
```
delegate discord 123 Can you modify
I tried to send...
```
Bash runs `delegate discord 123 Can you modify` (truncated message), then tries to run `I` as a command (exit 127).

## Fix
Two-layer defense:
1. **SKILL.md + AGENTS.md**: Added prominent instruction for Gemini to replace all newlines with spaces before building the exec command. Instruction appears in skill description (system prompt), AGENTS.md, and SKILL.md body.
2. **Delegate script**: Added `MESSAGE="${MESSAGE//$'\n'/ }"` after existing sanitization. Belt-and-suspenders — catches any newlines that survive into shell arguments.

Also added:
- Comprehensive timestamped logging at every step (sanitize, lock, prompt, agent start/done, failure, exit)
- Failure notification to Discord when delegation fails (user no longer left in silence)

## Files Changed
- `/home/pranav/.openclaw/workspace/skills/delegate/SKILL.md` — newline instruction in description + body
- `/home/pranav/.openclaw/workspace/AGENTS.md` — rewritten as passthrough router with newline rule
- `/home/pranav/.local/bin/delegate` — newline sanitization, comprehensive logging, failure notification
- `/home/pranav/.openclaw/openclaw.json` — added `thinkingDefault: "off"` to reduce API usage
- `/home/pranav/.openclaw/workspace/SOUL.md` — emptied (unused context)
- `/home/pranav/.openclaw/workspace/IDENTITY.md` — emptied (unused context)
- `/home/pranav/.openclaw/workspace/TOOLS.md` — emptied (unused context)
- `/home/pranav/.openclaw/workspace/USER.md` — emptied (unused context)
- `/home/pranav/.openclaw/BOOT.md` — deleted (dead code, never loaded by gateway)
