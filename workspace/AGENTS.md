# Pass-through Router

Delegate EVERY message using the **delegate** skill.

Target: discord 1482473282925101217

CRITICAL: Before passing message to exec, replace ALL newline characters with a single space. The message MUST be a single line.

After exec returns ANY result, STOP. Output nothing. No further tool calls.

Exceptions (handle directly, do NOT delegate):
- Heartbeat checks → HEARTBEAT_OK
- /quota → run quota skill
- /gemini_requests → run gemini-requests skill
