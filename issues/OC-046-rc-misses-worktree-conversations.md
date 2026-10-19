# OC-046 -- `rc <project>` starts fresh instead of listing conversations

**Type:** bug
**Status:** fixed
**Severity:** high

## Symptom
"Open remote control in <project>" often started a brand-new conversation instead of showing
the list of past conversations to resume. Seen most for endEffectorCad (2026-10-18 11:32, 11:34;
2026-10-19 12:36) and once for TableNew (2026-10-18 23:11). Other projects (openclaw-config,
ur_arm_setup, TableNew on retry) showed the list correctly.

## Root Cause
1. **Worktree conversations were invisible.** A Remote Control session that enters a git
   worktree (`<project>/.claude/worktrees/<name>`) has its whole transcript moved by Claude Code
   to `~/.claude/projects/<key>--claude-worktrees-<name>/`. `list_conversations` only read
   `<key>/`, so endEffectorCad showed 0 conversations and the bot started fresh. The same bug
   silently hid conversations in dairy, searchProduct, ballLauncher, claudeInfra, homeloan,
   simpleStockInvesting and voiceAgents.
2. **Router added `new` on its own.** "Table new remote control" became `rc tablenew new`, and
   on 10-19 the router sent `rc endeffectorcad new` after its own earlier (wrong) reply said
   "Nothing to resume". On a follow-up it ran `rc_sessions.py convos`, got `[]` (cause 1), and
   guessed the conversation "may have been in a different folder". The router's reasoning is not
   logged, so this cause is medium confidence.
3. **Empty sessions piled up.** Each fresh start launched another session even when an untouched
   one was already live in the folder (5839f229 and a06772a3 were both idle and empty).

## Fix
- `rc_sessions.py`: `transcript_dirs()` returns the project dir plus its `--claude-worktrees-*`
  dirs. `list_conversations` lists across all of them (deduped by session id), and each entry
  carries `cwd` = the folder the session was last in. `live_in_dir` counts sessions in the
  project's worktrees (so they show as LIVE and `rc stop` finds them).
- `resume_rc(..., cwd=)` / `takeover(..., cwd=)` launch in the conversation's worktree when it
  still exists (`launch_dir`), else in the project folder. Verified 2026-10-19 that
  `claude --resume <id>` from the main folder finds a transcript stored under a worktree key
  (a throwaway `--fork-session` copy had full history), so a removed worktree still resumes.
- `start_fresh_rc`: a fresh request reuses a live background RC session in the folder that
  nobody has typed into yet, instead of starting another one (`empty_live_rc`).
- `discord-bot.py`: passes each conversation's `cwd` through list → pick → resume / copy /
  takeover. Fresh starts go through `start_fresh_rc`.
- `agents/remote-control.md`: new "When to add `new`" section. Default to plain `rc <project>`.
  Project-name words don't count, never infer "nothing to resume" from history, and don't
  speculate when `convos` is `[]`.

## Not fixed (noted for later)
- delegate.py's "Recent messages" header always says "Only use entries matching [openclaw]",
  whatever the project, and the router's stray text can be recorded under the wrong project tag.

## Files Changed
- bin/rc_sessions.py
- bin/rc_commands.py
- bin/discord-bot.py
- agents/remote-control.md
- tests/test_rc_sessions.py
