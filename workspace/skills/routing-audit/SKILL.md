---
name: routing-audit
description: "Run the openclaw test suite (unit + integration + behavior tests) and send results to Discord. Use when asked to: run tests, run integration tests, check routing, audit the delegation pipeline, run all tests. Do NOT delegate to Claude — run the script directly via exec."
---

# Routing Audit Skill

Run this via exec (**not** via delegate — the script sends its own Discord message):

```
run-tests
```

That's it. The script runs all three test suites and sends a formatted pass/fail summary to Discord automatically.

**IMPORTANT:**
- Run directly: `exec({command: "run-tests"})` — do NOT wrap in `delegate`
- This takes 10-15 minutes total (live Claude calls are made during behavior tests)
- The script sends its own Discord message when done — you do not need to send anything

**For quick log analysis only** (no live tests):
```
route-audit
```
This analyzes today's session logs and sends a routing health report to Discord.
