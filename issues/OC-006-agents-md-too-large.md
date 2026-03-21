# OC-006 — AGENTS.md was 9.3KB, loaded on every Gemini turn

**Type:** feature
**Status:** fixed
**Reported:** 2026-03-20
**Fixed:** 2026-03-20

## Description

`workspace/AGENTS.md` contained ~2,300 tokens of routing rules, examples, and explanatory text loaded into every Gemini model turn. Most content was redundant with BOOT.md.

## Fix

Trimmed from 9.3KB to ~1.3KB (86% reduction). Kept only:
- Mode 1 / Mode 2 distinction (crisp rules)
- Channel/target defaults
- Quota footer reminder
- Heartbeat and group chat rules

Removed: Mode 3 (project mode), verbose examples, duplicate explanations already in BOOT.md.
