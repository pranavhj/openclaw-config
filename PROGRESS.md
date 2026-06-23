# openclaw-config

## State
Currently: Bot and delegate stable; agent-smart dual-threshold + compact command (OC-036)
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

## Next
- OC-027: NSSM service broken (logon failure) — bot runs manually for now
- Check ISSUES.md for open issues before starting new work

## Key decisions
- Bot runs manually: `python D:\MyData\Software\openclaw-config\bin\discord-bot.py`
- openclaw/CLAUDE.md and agents/openclaw-CLAUDE.md must stay in sync
- AndroidAppDev project is the hub for Android script maintenance work
