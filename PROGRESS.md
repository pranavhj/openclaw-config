# openclaw-config

## State
Currently: OC-041 Discord `rc` command (Remote Control launcher) built + tested; bot restart needed to activate
Last session: 2026-06-22

## Done
- Discord bot (discord-bot.py), delegate pipeline, agent-smart.py — stable
- Android tooling pipeline built and tested (scripts, skeleton, router updates)
  → Full context in AndroidAppDev project at C:\Users\prana\projects\AndroidAppDev
- delegate.py: openclaw-config now visible as project (removed from EXCLUDE_NAMES)
- OC-033: Triage improvements — removed 10-min timeouts, always use gateway, opus model, attachment skip
- OC-034: Architecture fixes — gateway log date UTC→local, ALLOWED_USER from config, project discovery consolidated, discord-send retry
- OC-035: agent-smart.py — no auto-compact; warn only at 1MB; --keep-pairs opts in to compaction explicitly
- OC-036: agent-smart dual thresholds (warn 200KB, auto-compact 1MB, default 5 pairs); Discord "compact <project>" command via --compact-only flag + CLAUDE.md routing
- OC-037: Project misrouting fix — continuity fallback when triage errors, "screen" prefix blocklist
- 2026-10-05 OC-041: `rc` command — create/resume/takeover/list/stop/restore Remote Control sessions; delegate guard for RC-live projects

## Next
- OC-027: NSSM service broken (logon failure) — bot runs manually for now
- Check ISSUES.md for open issues before starting new work

## Key decisions
- Bot runs manually: `python D:\MyData\Software\openclaw-config\bin\discord-bot.py`
- openclaw/CLAUDE.md and agents/openclaw-CLAUDE.md must stay in sync
- AndroidAppDev project is the hub for Android script maintenance work
