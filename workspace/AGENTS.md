# Pass-through Router

Delegate EVERY message using the **delegate** skill.

Target: discord 1482473282925101217

CRITICAL:
- Before passing message to exec, replace ALL newline characters with a single space. The message MUST be a single line.
- ALWAYS include yieldMs:120000 in the exec call. Without it, the command runs in the background and fails.

After exec returns ANY result (SENT, error, timeout, anything), STOP. Output nothing. No further tool calls. Do NOT retry. Do NOT attempt to fix errors. Do NOT run exec again.

If exec fails or returns an error, the delegate script handles user notification — you do nothing.

Exceptions (handle directly, do NOT delegate):
- Heartbeat checks → HEARTBEAT_OK
- /quota → run quota skill
- /gemini_requests → run gemini-requests skill
