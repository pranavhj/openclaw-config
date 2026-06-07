# openclaw System Architecture
_Last updated: 2026-06-07 (router CLAUDE.md deployed, ops.md split, recent-messages passthrough removed, --continue verified)_

---

## Message Flow (End-to-End)

```
┌─────────────────────────────────────────────────────────────────┐
│                     INBOUND CHANNEL                              │
│                                                                  │
│   Discord DM ──────────────────────► discord-bot.py             │
│   (allowFrom: 1277144623231537274)    manual process             │
│                                       (NSSM service broken --   │
│                                        see Known Risks)          │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│          discord-bot.py  — D:\MyData\Software\openclaw-config\bin\ │
│                                                                  │
│  Library: discord.py with Message Content Intent                 │
│  Token: read from ~/.openclaw/openclaw.json at startup           │
│  Allowlist: ALLOWED_USER = 1277144623231537274 (DMs only)        │
│                                                                  │
│  On message:                                                     │
│    1. Ignore bots and non-allowlisted users                      │
│    2. Download attachments → %TEMP%\openclaw\attachments\<id>\   │
│       Set DELEGATE_ATTACHMENTS env var if any                    │
│    3. Replace newlines with spaces                               │
│    4. subprocess.Popen([python, delegate.py, ch, tgt, content],  │
│         creationflags=CREATE_NEW_PROCESS_GROUP|DETACHED_PROCESS) │
│       <- detached, survives service restarts                     │
│                                                                  │
│  Logs to %LOCALAPPDATA%\openclaw\bot.log                         │
│  Also runs async session watcher (watch_claude_sessions):        │
│    • Polls ~/.claude/projects/**/*.jsonl every 1s                │
│    • Pretty-prints tool calls + text to stdout -> bot.log        │
│    • Shows: [project] [tool] Bash: ..., [project] [assistant] …  │
│    • Skip memory files                                           │
│                                                                  │
│  View live logs: python bot-logs.py  (tails bot.log)             │
│  Status: Get-Process python (bot is NOT an NSSM service)         │
└─────────────────────────────────────────────────────────────────┘
                    │ subprocess.Popen (detached)
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│              delegate.py  (same bin\ dir)                        │
│                                                                  │
│  1. Log: delegate_recv (timestamp, channel, target, msg_len)     │
│  2. Sanitize message:                                            │
│     • Apostrophes -> U+2019 right single quote (OC-015)         │
│     • Backticks -> U+2018 left single quote                     │
│     • Newlines -> spaces (OC-016)                               │
│  3. Log: sanitize (orig_len, sanitized_len, chars_replaced)      │
│  4. Acquire lock: %LOCALAPPDATA%\openclaw\delegate.lock (mkdir)  │
│     |- If locked -> notify user via discord-send, echo SENT, exit│
│     `- If free -> log lock_acquired, continue                    │
│  5. Collect context:                                             │
│     • Projects: scan ~/projects, ~/AndroidStudioProjects,        │
│       ~/PycharmProjects, ~/UnityProjects, D:\MyData\Software     │
│       Include dirs with .claude or PROGRESS.md; include full path│
│     • Recent history: last 5 entries from timeline log           │
│  6. Build prompt in temp file (## Reply, ## Known projects,      │
│     ## Recent messages, ## Request, ## Attachments if any)       │
│     Written to %LOCALAPPDATA%\openclaw\delegate-prompt-*.txt     │
│  7. Log: prompt_ready (bytes)                                    │
│  8. Strip CLAUDECODE from env (prevents nested-session error)    │
│  9. Log: agent_start -> Run Claude:                              │
│     cd C:\Users\prana\projects\openclaw                          │
│     python agent-smart.py --permission-mode bypassPermissions    │
│       --model haiku --print-file <file>                          │
│     (stateless haiku router -- no --continue, OC-026)            │
│  10. Log: agent_done (exit_code, duration_ms, output_preview)    │
│  11. If failure (exit!=0 AND output!="SENT"):                    │
│     • Log: failure_detected                                      │
│     • discord-send error notification to user                    │
│     • Log: failure_notified                                      │
│  12. Cleanup prompt temp file                                    │
│  13. session-reset (no-op on Windows)                            │
│  14. Log: delegate_exit (total_ms, final_output)                 │
│  15. Echo OUTPUT                                                 │
│                                                                  │
│  Logs:                                                           │
│    Human-readable: %LOCALAPPDATA%\openclaw\delegate-YYYY-MM-DD.log│
│    Machine JSON:   %LOCALAPPDATA%\openclaw\timeline-YYYY-MM-DD.log│
└─────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│         agent-smart.py  (same bin\ dir)                          │
│                                                                  │
│  Wrapper around `claude` with auto-compaction:                   │
│    • --print-file: reads prompt from file, pipes to claude stdin │
│    • Reads ~/.claude/projects/<cwd-key>/*.jsonl                  │
│    • If session > 100KB: compact to last 3 message pairs (OC-026)│
│      Keeps user/assistant entries only, drops metadata           │
│      Creates new UUID-named JSONL, deletes old one               │
│    • Then: subprocess.run(['claude'] + args, shell=True on Win)  │
└─────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│     openclaw_claude (Claude) — C:\Users\prana\projects\openclaw\ │
│                                                                  │
│  Model: claude-haiku-4-5 (--model haiku, stateless, OC-026)     │
│  Working dir: C:\Users\prana\projects\openclaw\                  │
│  Config: C:\Users\prana\projects\openclaw\CLAUDE.md              │
│    ↳ Repo: github.com/pranavhj/openclaw                          │
│    ↳ Git backup: agents/openclaw-CLAUDE.md in openclaw-config    │
│    ↳ Overrides ~/projects/CLAUDE.md recursion guard              │
│  Session: stateless (no --continue — fresh context each call)    │
│                                                                  │
│  Receives prompt with:                                           │
│    ## Reply  (channel + target for response delivery)            │
│    ## Known projects (name + full path, multi-root scan)         │
│    ## Recent messages (last 4, tagged by project — routing ctx)  │
│    ## Request (user's full message verbatim)                     │
│    ## Attachments (paths if files were uploaded)                 │
│                                                                  │
│  ┌─────────────────────────────────────────────────┐             │
│  │  ONE-OFF request (question, analysis, fix)       │             │
│  │  -> Handle directly                              │             │
│  │  -> discord-send.py to Discord                   │             │
│  │  -> Output: SENT                                 │             │
│  └─────────────────────────────────────────────────┘             │
│                                                                  │
│  ┌─────────────────────────────────────────────────┐             │
│  │  TOOL INVOKE (project has ## Quick invoke)       │             │
│  │  -> Read <full_path>\CLAUDE.md                   │             │
│  │  -> If ## Quick invoke section found:            │             │
│  │     Run command directly (no sub-session)        │             │
│  │  -> Send output to Discord                       │             │
│  │  -> Output: SENT                                 │             │
│  └─────────────────────────────────────────────────┘             │
│                                                                  │
│  ┌─────────────────────────────────────────────────┐             │
│  │  PROJECT request (build/implement/continue)      │             │
│  │  -> Match name in Known projects, use full path  │             │
│  │  -> mkdir -p <full_path> (for new projects)      │             │
│  │  -> Spawn isolated sub-session:                  │             │
│  │    (unset CLAUDECODE; cd <full_path> &&           │             │
│  │     python agent-smart.py --continue             │             │
│  │       --permission-mode bypassPermissions        │             │
│  │       --model sonnet --print "...")              │             │
│  │  -> Sub-session handles delivery + outputs SENT  │             │
│  └─────────────────────────────────────────────────┘             │
└─────────────────────────────────────────────────────────────────┘
         │ one-off / tool invoke      │ project work
         │                           ▼
         │              ┌────────────────────────────┐
         │              │  Project sub-session        │
         │              │  (Claude in <full_path>)    │
         │              │  Model: sonnet              │
         │              │  Session: --continue        │
         │              │                             │
         │              │  Config: project CLAUDE.md  │
         │              │  + ~/projects/CLAUDE.md     │
         │              │  (recursion guard)          │
         │              │  No ## Recent messages —    │
         │              │  --continue has full history│
         │              │                             │
         │              │  • Reads PROGRESS.md        │
         │              │  • Does the work            │
         │              │  • Updates PROGRESS.md      │
         │              │  • discord-send.py to Discord│
         │              │  • Exits (one-shot)         │
         │              │  • Session history persists │
         │              │    in JSONL for next call   │
         │              └────────────────────────────┘
         │                           │
         └───────────────────────────┘
                                     │
                    discord-send.py --target <tgt> --message "..."
                                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                   OUTBOUND DELIVERY                              │
│                                                                  │
│   Discord DM ---- target=1482473282925101217                     │
│   All messages end with: -# sent by claude (watermark)           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Agent Responsibilities

| Agent | Model | Working Dir | Session | Responsibility |
|---|---|---|---|---|
| **openclaw_claude** | haiku | `~/projects/openclaw/` | stateless (no --continue) | Entry point for all channel traffic. One-off: handles directly. Tool invoke: runs Quick invoke command. Project work: spawns isolated sub-session. |
| **Project sub-session** | sonnet | `<full_path>` | --continue | Isolated per-project Claude session. Reads PROGRESS.md, does work, updates PROGRESS.md, sends to Discord, exits. |
| **Claude Code** (terminal) | sonnet | varies | --continue | Direct dev work with Pranav in terminal |

---

## Quick invoke convention

Tool projects (stateless, run-and-return) declare a `## Quick invoke` section in their `CLAUDE.md`. The openclaw haiku reads this before deciding to spawn a sub-session.

**Format** (`<project>/CLAUDE.md`):
```markdown
## Quick invoke
<command to run directly>
```

**Projects using this pattern:**
- `flightchecker` — `venv\Scripts\python.exe -m flightchecker --ask "<question>"`

**Benefits:** No session history growth, no `--continue` overhead, immune to context accumulation across repeated queries.

---

## Config Files — What Lives Where

```
C:\Users\prana\.openclaw\
└── openclaw.json                    <- BOT CONFIG
    • Discord bot token (used by discord-bot.py and discord-send.py)
    • API keys retained for potential future use
    • Session idle reset: 5 minutes

C:\Users\prana\AppData\Local\openclaw\   <- LOG DIR
├── delegate-YYYY-MM-DD.log          <- Human-readable delegation log
├── timeline-YYYY-MM-DD.log          <- JSON-lines machine log
├── bot.log                          <- discord-bot.py stdout
└── delegate.lock\                   <- Atomic lock dir (mkdir/rmdir)
    If stuck: rmdir %LOCALAPPDATA%\openclaw\delegate.lock

D:\MyData\Software\openclaw-config\bin\   <- ALL SCRIPTS (live = repo)
├── discord-bot.py                   <- DISCORD GATEWAY
│   • discord.py -- run manually (not as NSSM service)
│   • Reads token from ~/.openclaw/openclaw.json
│   • Spawns delegate.py as detached subprocess per message
│   • Async session watcher: pretty-prints JSONL activity to bot.log
│
├── discord-send.py                  <- OUTBOUND DISCORD REST
│   • urllib POST to Discord v10 API (no curl dependency)
│   • Reads token from ~/.openclaw/openclaw.json
│   • Args: --target <channel_id> --message <text>
│   • Optional: --edit <message_id> to edit existing message
│
├── delegate.py                      <- DELEGATION ORCHESTRATOR
│   • Sanitize, lock, log, collect context, build prompt
│   • Multi-root project scan (~/projects, ~/AndroidStudioProjects,
│     ~/PycharmProjects, ~/UnityProjects, D:\MyData\Software)
│   • Strips CLAUDECODE env var (prevents nested-session error)
│   • Writes prompt to temp file (avoids cmd.exe newline-splitting)
│   • Calls agent-smart.py with --model haiku (stateless routing)
│   • Failure notification to Discord
│   • Dual logging: human-readable + JSON timeline
│
├── agent-smart.py                   <- AUTO-COMPACTING AGENT WRAPPER
│   • --print-file: reads prompt from file, pipes to claude stdin
│   • Checks session size before delegating (threshold: 100KB, OC-026)
│   • Compact: keep last 3 user/assistant pairs (OC-026), drop metadata
│   • Then: subprocess.run(['claude'] + args, shell=True on Windows)
│
├── bot-logs.py                      <- LIVE LOG VIEWER
│   • Tails %LOCALAPPDATA%\openclaw\bot.log
│
├── route-audit.py                   <- DAILY LOG ANALYSIS
│   • Gathers delegate + timeline logs + bot health
│   • Writes prompt to file (avoids cmd.exe newline-splitting)
│   • cd ~/projects/openclaw && agent-smart.py --continue --model sonnet
│   • Claude analyzes routing health, sends report to Discord
│
└── run-tests.py                     <- FULL TEST SUITE RUNNER
    • Runs all 3 test suites, optional --discord summary

C:\Users\prana\projects\
├── CLAUDE.md                        <- PROJECT SUB-SESSION GUARD
│   • "You're in a project dir -- do the work, don't spawn sub-sessions"
│
└── openclaw\                        <- git repo: github.com/pranavhj/openclaw
    └── CLAUDE.md                    <- OPENCLAW_CLAUDE CONFIG (live, versioned)
        • Overrides parent ~/projects/CLAUDE.md recursion guard
        • Job: do work, send via discord-send.py, output SENT
        • User profile, Discord format, watermark
        • Project routing: one-off / tool invoke / sub-session
        • Quick invoke: read project CLAUDE.md for ## Quick invoke section
        • Sub-session spawn: (unset CLAUDECODE; cd <path> && claude ...)
        • For system changes: read agents/ops.md (git, gh CLI)

D:\MyData\Software\openclaw-config\  <- THIS REPO (live = repo)
    config/openclaw.json             <- sanitized (secrets as ${VAR})
    bin/discord-bot.py, discord-send.py, delegate.py, agent-smart.py
    bin/bot-logs.py, route-audit.py, run-tests.py, session-reset.py
    bin/restart-bot.py               <- sc stop + Start-Process restart
    agents/openclaw-CLAUDE.md        <- git backup of ~/projects/openclaw/CLAUDE.md
    agents/projects-CLAUDE.md        <- canonical copy of ~/projects/CLAUDE.md
    agents/ops.md                    <- source control + gh CLI (read on demand)
    docs/openclaw-architecture.md    <- this file

NSSM service (discord-bot):
    Registered but NOT used -- has logon failure (stale .\prana password).
    Cannot fix without admin rights to sc config.
    Run bot manually: python D:\MyData\Software\openclaw-config\bin\discord-bot.py
    Service will not auto-start on reboot -- must start manually.
```

---

## Startup on Reboot

discord-bot.py does NOT auto-start on reboot (NSSM service broken). Start manually:

```
python D:\MyData\Software\openclaw-config\bin\discord-bot.py
```

**Note:** The `Ubuntu_openclaw` VirtualBox VM (old Linux openclaw host) was previously
auto-starting via a Startup folder shortcut (`start_openclaw_headless.bat`). That shortcut
has been removed (2026-04-29). The VM still exists but no longer starts automatically.
Do NOT restart the VM -- it runs an older agent that conflicts with the Windows pipeline.

---

## Logging System

```
%LOCALAPPDATA%\openclaw\
├── delegate-YYYY-MM-DD.log          <- Human-readable log (per delegation)
│   • Timestamp, channel, target, message preview
│   • Timing: ts_recv, ts_agent_start, ts_agent_done, ts_exit
│   • Duration: agent_ms, total_ms
│   • Exit code and output preview
│
├── timeline-YYYY-MM-DD.log          <- Machine-parseable JSON-lines
│   Events:
│   • delegate_recv   -- message received (channel, target, msg_len, preview)
│   • sanitize        -- chars replaced (orig_len, sanitized_len)
│   • lock_acquired   -- lock obtained
│   • lock_blocked    -- duplicate run prevented
│   • project_match   -- always "openclaw" (Claude does routing)
│   • prompt_ready    -- prompt built (bytes)
│   • agent_start     -- Claude invocation started
│   • agent_done      -- Claude finished (exit_code, duration_ms, output)
│   • failure_detected -- delegation failed
│   • failure_notified -- error message sent to Discord
│   • delegate_exit   -- final output returned (total_ms)
│
└── bot.log                          <- discord-bot.py stdout
    • dispatch events (message receipt)
    • [project] [tool] / [assistant] lines from JSONL watcher
    View: python bot-logs.py

Daily audit: route-audit.py (manual or Task Scheduler, 8am PT)
  Reads delegate + timeline logs + process health
  Passes to agent-smart.py --model sonnet --continue
```

---

## Source Control

```
┌─────────────────────────────────────────────────────────────────┐
│          github.com/pranavhj/openclaw-config (public)            │
│          D:\MyData\Software\openclaw-config\                     │
│                                                                   │
│  On Windows: scripts live directly in the repo.                   │
│  "Live" = repo. Edit -> commit -> push = deployed.               │
│                                                                   │
│  Secrets: openclaw.json stored with ${VAR} placeholders          │
│  Pre-commit hook: blocks real secrets from being committed        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Key Design Decisions & Why

**Stateless haiku router (OC-026)**
The openclaw routing agent runs as haiku with no `--continue`. Each delegation is a fresh
context. This is cheap and fast for routing. Heavy project work is delegated to sonnet
sub-sessions with `--continue` that accumulate history only within the project scope.

**Router CLAUDE.md deployed to ~/projects/openclaw/ (2026-06-07)**
Previously `~/projects/openclaw/CLAUDE.md` did not exist. The router was working purely
off the prompt, and also reading `~/projects/CLAUDE.md` (the recursion guard) which
explicitly says "do NOT spawn sub-sessions" — conflicting with its actual job.
The fix: deploy `agents/openclaw-CLAUDE.md` as the live file at `~/projects/openclaw/CLAUDE.md`,
with an explicit override note for the recursion guard. The directory is now a git repo at
`github.com/pranavhj/openclaw`. Git backup still kept at `agents/openclaw-CLAUDE.md`.

**Recent messages not passed to sub-sessions (2026-06-07)**
The router prompt includes `## Recent messages` (last 4 exchanges) for routing context —
essential for resolving references like "fix the above" or "continue that". Previously
this was also passed through to sub-sessions via the spawn `--print` content. Removed:
sub-sessions have the full conversation via `--continue` JSONL history, making the
passthrough redundant noise.

**ops.md split from router CLAUDE.md (2026-06-07)**
Source control workflow and gh CLI instructions moved to `agents/ops.md`. The router
reads it only when making openclaw system changes (rare). This reduces Haiku's prompt
size on every single message by ~30 lines.

**Quick invoke convention**
Tool projects (flightchecker, etc.) that are run-and-return declare a `## Quick invoke`
section in CLAUDE.md. The router reads this and runs the command directly, avoiding a
`--continue` sub-session. History never grows no matter how many queries are made.
This keeps the router CLAUDE.md project-agnostic -- each project owns its own invocation.

**discord-bot.py replaces openclaw gateway + Gemini**
Gemini was unreliably classifying messages, occasionally bypassing delegation, and
consuming API quota as a passthrough router. The Python discord.py service is simpler:
receive DM -> spawn delegate -> done. No AI in the hot path.

**`CREATE_NEW_PROCESS_GROUP|DETACHED_PROCESS` on Popen (Windows)**
Detaches delegate.py from the discord-bot.py process group. If the bot is restarted,
running delegates survive and complete normally.

**agent-smart auto-compaction (100KB threshold, 3 pairs, OC-026)**
Claude Code JSONL sessions grow unboundedly. Compaction keeps the last 3 user/assistant
exchanges as history context, drops tool call metadata. Triggers before each agent
invocation. Threshold lowered from 400KB to 100KB in OC-026.

**Prompt via temp file (`--print-file`), not `--print`**
On Windows, cmd.exe splits commands at newline characters. Writing to a temp file and
using `--print-file` bypasses cmd.exe entirely (agent-smart.py pipes via stdin).

**CLAUDECODE stripped from delegate env**
Claude Code sets `CLAUDECODE` in its process environment. If not stripped before spawning
agent-smart.py, claude would refuse to start. delegate.py filters it out.

**`unset CLAUDECODE` in sub-session spawns**
When openclaw_claude spawns a project sub-session via Bash, the child process inherits
`CLAUDECODE`. The spawn command explicitly unsets it: `(unset CLAUDECODE; cd <path> && ...)`.

**Live = repo on Windows**
On Linux, scripts lived in `~/.local/bin/` and were synced to/from the repo. On Windows,
the scripts live directly in `D:\MyData\Software\openclaw-config\bin\` -- the repo IS the
live deployment. No sync step needed.

---

## Known Risks

### OC-002 -- Silent message drop on full RPM exhaustion (OPEN)
If Discord bot or Claude Code hits rate limits, the message may be silently dropped.
**Workaround:** wait 2+ minutes after heavy usage.

### NSSM service broken -- no auto-start on reboot (OPEN)
The `discord-bot` NSSM service fails to start with "logon failure" (stale `.\prana`
account password). Cannot fix without admin rights (`sc config` / `nssm set` denied).
**Workaround:** run discord-bot.py manually after each reboot.
**Permanent fix:** run elevated terminal, then `nssm set discord-bot ObjectName LocalSystem`.

### Delegate lock stuck after process kill (LOW)
If delegate.py is killed mid-run, the lock dir remains. Bot refuses all new messages.
**Fix:** `rmdir %LOCALAPPDATA%\openclaw\delegate.lock`

### Delegate lock drops parallel requests (LOW-MEDIUM)
Two simultaneous messages: second gets "still working" notification and is dropped.
Intentional for duplicate prevention, but legitimate parallel requests lose the second.

### Tool project session growth for project-mode invocations (MEDIUM -- mitigated)
Project sub-sessions accumulate history. agent-smart compaction at 100KB caps growth.
Tool projects using Quick invoke are immune (stateless).

### Prompt injection via message content (MEDIUM)
User message is passed verbatim into Claude's prompt.

### Service restart race (LOW -- mitigated)
`DETACHED_PROCESS` + `CREATE_NEW_PROCESS_GROUP` mean delegate survives bot restarts.
But a machine reboot mid-delegation would still kill in-flight work.

---

## Test Suites

| Suite | File | Count | Scope |
|---|---|---|---|
| Unit tests | `tests/test_delegate.py` | 91 | Script presence, imports, lock, sanitization, timeline events, failure notification, CLAUDECODE stripping, recursion guard |
| Integration tests | `tests/test_integration.py` | 28 | Live delegation, lock dedup, discord-send, timeline validation, config, sub-session isolation |
| Behavior tests | `tests/test_claude_behavior.py` | 12 | Claude response quality: watermark, format, routing (requires live token) |
| Continue session | `tests/test_continue_session.py` | 1 | Verifies `--continue` preserves session history across sub-session invocations. Run standalone. |
| Runner | `tests/run-tests.py` | -- | Runs all 3 suites, optional --discord summary |
| Daily audit | `bin/route-audit.py` | -- | Log analysis via Claude Sonnet: routing health, failure patterns, bot health |

---

## Scheduled Jobs

| Job | Schedule | Mechanism | Script |
|---|---|---|---|
| route-audit | 8am PT daily | Windows Task Scheduler (not yet configured) | `bin/route-audit.py` |
