---
name: delegate
description: "Delegate ALL requests to Claude. FIRST replace newlines in the message with spaces. Then exec({command:\"delegate discord 1482473282925101217 <message as single line>\", yieldMs:120000}). NEVER wrap message in quotes. When exec returns, STOP — no further output or tool calls."
---

# Delegate Skill

Run this exec command with `yieldMs:120000`:

```
delegate <channel> <target> <user's message as a SINGLE LINE>
```

## CRITICAL: Newline handling (OC-016)

Before building the exec command, **replace ALL newline characters in the user's message with a single space**. The command string MUST be a single line. Multi-line messages passed to exec will break bash.

## Parameters

- `command`: `delegate <channel> <target> <message with newlines replaced by spaces>`
- `yieldMs`: `120000`

## Example

User sends:
```
Hello
Can you help me?
```

Exec call (newlines replaced with spaces):
```json
{"command": "delegate discord 1482473282925101217 Hello Can you help me?", "yieldMs": 120000}
```

## Rules

- **NEWLINES**: Replace all `\n` with space before exec. Single line only.
- **QUOTING**: NEVER wrap message in single quotes. Pass words unquoted.
- **yieldMs**: Always 120000. Never use background:true.
- **After exec returns**: STOP. No further output. No further tool calls. No retries. Even on error — delegate handles failure notification itself.
