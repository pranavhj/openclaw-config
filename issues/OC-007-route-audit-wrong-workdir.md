# OC-007 — route-audit ran agent from wrong working directory

**Type:** bug
**Status:** fixed
**Reported:** 2026-03-20
**Fixed:** 2026-03-20

## Description

`/home/pranav/.local/bin/route-audit` ran:
```bash
cd /home/pranav && agent --permission-mode bypassPermissions ...
```

This meant the agent read `/home/pranav/CLAUDE.md` (the base agent config) instead of `projects/openclaw/CLAUDE.md` (openclaw_claude config), and had no session continuity.

## Fix

Changed to:
```bash
cd /home/pranav/projects/openclaw && agent --continue --permission-mode bypassPermissions ...
```

Now route-audit uses the correct openclaw_claude context and session history.
