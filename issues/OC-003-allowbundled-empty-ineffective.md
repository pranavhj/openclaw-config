# OC-003 — `allowBundled: []` does not disable bundled skills

**Type:** bug
**Status:** fixed
**Reported:** 2026-03-20
**Fixed:** 2026-03-20

## Description

Setting `skills.allowBundled: []` in `openclaw.json` was expected to disable all 55 bundled skills, but the gateway loaded them all anyway.

## Root cause

`isBundledSkillAllowed()` in openclaw source:
```js
if (!allowlist || allowlist.length === 0) return true;  // empty = allow all
```
An empty allowlist is treated as "no filter" (allow everything), not "allow nothing".

## Fix

Changed to `allowBundled: ["__none__"]` — a non-empty allowlist that matches no bundled skill name, effectively disabling all 55. Workspace skills are exempt: `if (!isBundledSkill(entry)) return true` runs first.

## Verification

Gateway log: `config change applied (dynamic reads: skills.allowBundled)` ✓
Workspace skills (delegate, discord-send, etc.) still loading ✓
