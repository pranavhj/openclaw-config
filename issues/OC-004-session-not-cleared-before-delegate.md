# OC-004 — Gemini accumulates cross-turn context as router

**Type:** feature
**Status:** fixed
**Reported:** 2026-03-20
**Fixed:** 2026-03-20

## Description

Gemini (the router) was accumulating full session history across turns. Since Gemini is a pure router (every message should be stateless: receive → delegate → done), this growing context served no purpose and wasted tokens every turn.

## Fix

Added session-clearing logic to the `delegate` script. At the start of each delegation, the Gemini session JSONL is truncated to 0 bytes:

```bash
[[ -n "$SESSION_ID" && -f "$SESSIONS_DIR/${SESSION_ID}.jsonl" ]] && \
  > "$SESSIONS_DIR/${SESSION_ID}.jsonl"
```

Gemini starts each routing turn with a clean context, loaded fresh from BOOT.md + AGENTS.md only.
