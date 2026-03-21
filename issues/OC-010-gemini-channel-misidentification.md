# OC-010 — Gemini routed Discord message to WhatsApp

**Type:** bug
**Status:** fixed
**Reported:** 2026-03-20
**Fixed:** 2026-03-20

## Description

User sent standingTableController project creation message via Discord. Gemini called `delegate whatsapp +12403967835` instead of `delegate discord 1482473282925101217`. User received the API error on Discord and Claude's response on WhatsApp.

## Root causes

1. **BOOT.md was severely out of date** — still had Mode 2/Mode 3 using the old direct `agent` exec format, not the delegate skill. Gemini was reading conflicting instructions between BOOT.md (old) and AGENTS.md (current). The channel/target logic was ambiguous.

2. **AGENTS.md had WhatsApp as an explicit option** — with a stateless (session-cleared) Gemini, if channel context was ambiguous, it could pick either Discord or WhatsApp. It picked wrong.

3. **No single source of truth for channel** — two files (BOOT.md + AGENTS.md) both described routing, inconsistently.

## Fix

- BOOT.md rewritten to match current architecture: delegate skill only, Discord hardcoded as the only channel, no Mode 2/Mode 3 direct exec
- AGENTS.md: removed WhatsApp option, simplified to "Always use: discord 1482473282925101217"
- openclaw.json: WhatsApp channel disabled (`enabled: false`)

## Verification

Gateway restarted. Gemini now has consistent, unambiguous instructions from both BOOT.md and AGENTS.md. Only one possible channel target.
