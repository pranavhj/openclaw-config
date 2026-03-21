# OC-008 — All projects shared one Claude session (no isolation)

**Type:** feature
**Status:** fixed
**Reported:** 2026-03-20
**Fixed:** 2026-03-20

## Description

All Discord messages routed to a single Claude session in `projects/openclaw/`. For project work (build/implement/continue), this meant:
- All project histories mixed into one growing context
- No per-project session continuity — Claude reconstructed state from PROGRESS.md alone
- Context window filled with unrelated conversations over time

## Fix

`projects/openclaw/CLAUDE.md` now detects project work and spawns an isolated sub-session:

```bash
cd /home/pranav/projects/<slug> && \
  agent --continue --permission-mode bypassPermissions \
        --print "## Reply ..."
```

Each project gets its own JSONL session in `~/.claude/projects/<path>/`. The sub-session handles delivery and exits. `--continue` resumes full history on next message.

`projects/CLAUDE.md` created as a sub-session override to prevent recursion (sub-sessions do the work directly, don't try to spawn further sub-sessions).
