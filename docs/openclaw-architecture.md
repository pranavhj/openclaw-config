# openclaw System Architecture
_Last updated: 2026-04-19 (OC-021 — Windows migration complete)_

---

## Message Flow (End-to-End)

```
┌─────────────────────────────────────────────────────────────────┐
│                     INBOUND CHANNEL                              │
│                                                                  │
│   Discord DM ──────────────────────► discord-bot.py             │
│   (allowFrom: 1277144623231537274)    NSSM service               │
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
│       ← detached, survives service restarts                      │
│                                                                  │
│  Logs to %LOCALAPPDATA%\openclaw\bot.log (NSSM stdout/stderr)    │
│  Also runs async session watcher (watch_claude_sessions):        │
│    • Polls ~/.claude/projects/**/*.jsonl every 1s                │
│    • Pretty-prints tool calls + text to stdout → bot.log         │
│    • Shows: [project] [tool] Bash: ..., [project] [assistant] …  │
│    • Skip memory files                                           │
│                                                                  │
│  View live logs: python bot-logs.py  (tails bot.log)            │
│  Service: nssm status discord-bot                                │
└─────────────────────────────────────────────────────────────────┘
                    │ subprocess.Popen (detached)
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│              delegate.py  (same bin\ dir)                        │
│                                                                  │
│  1. Log: delegate_recv (timestamp, channel, target, msg_len)     │
│  2. Sanitize message:                                            │
│     • Apostrophes → U+2019 right single quote (OC-015)          │
│     • Backticks → U+2018 left single quote                      │
│     • Newlines → spaces (OC-016)                                 │
│  3. Log: sanitize (orig_len, sanitized_len, chars_replaced)      │
│  4. Acquire lock: %LOCALAPPDATA%\openclaw\delegate.lock (mkdir)  │
│     ├─ If locked → notify user via discord-send, echo SENT, exit │
│     └─ If free → log lock_acquired, continue                     │
│  5. Collect context:                                             │
│     • Projects: scan ~/projects, ~/AndroidStudioProjects,        │
│       ~/PycharmProjects, ~/UnityProjects, D:\MyData\Software     │
│       Include dirs with .claude or PROGRESS.md; include full path│
│     • Recent history: last 5 entries from timeline log           │
│  6. Build prompt in temp file (## Reply, ## Known projects,      │
│     ## Recent messages, ## Request, ## Attachments if any)       │
│     Written to %LOCALAPPDATA%\openclaw\delegate-prompt-*.txt     │
│  7. Log: prompt_ready (bytes)                                     │
│  8. Strip CLAUDECODE from env (prevents nested-session error)    │
│  9. Log: agent_start → Run Claude:                               │
│     cd C:\Users\prana\projects\openclaw                          │
│     python agent-smart.py --continue --permission-mode           │
│       bypassPermissions --model sonnet --print-file <file>       │
│     (--print-file avoids cmd.exe newline-splitting, OC-016)      │
│  10. Log: agent_done (exit_code, duration_ms, output_preview)    │
│  11. If failure (exit≠0 AND output≠"SENT"):                     │
│     • Log: failure_detected                                      │
│     • discord-send error notification to user                    │
│     • Log: failure_notified                                      │
│  12. Cleanup prompt temp file                                    │
│  13. session-reset (no-op on Windows — openclaw gateway absent)  │
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
│  Wrapper around `claude --continue` with auto-compaction:        │
│    • --print-file: reads prompt from file, pipes to claude stdin │
│    • Reads ~/.claude/projects/<cwd-key>/*.jsonl                  │
│    • If session > 400KB: compact to last 5 message pairs         │
│      Keeps user/assistant entries only, drops metadata           │
│      Creates new UUID-named JSONL, deletes old one               │
│    • Then: subprocess.run(['claude'] + args, shell=True on Win)  │
└─────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│         openclaw_claude (Claude) — C:\Users\prana\projects\openclaw\ │
│                                                                  │
│  Model: claude-sonnet-4-6 (--model sonnet)                       │
│  Working dir: C:\Users\prana\projects\openclaw\                  │
│  Config: C:\Users\prana\projects\openclaw\CLAUDE.md              │
│  Session: --continue (persists across delegations)               │
│                                                                  │
│  Receives prompt with:                                           │
│    ## Reply  (channel + target for response delivery)            │
│    ## Known projects (name + full path, multi-root scan)         │
│    ## Recent messages (last 5, tagged by project)                │
│    ## Request (user's full message verbatim)                     │
│    ## Attachments (paths if files were uploaded)                 │
│                                                                  │
│  ┌─────────────────────────────────────────────────┐             │
│  │  ONE-OFF request (question, analysis, fix)       │             │
│  │  → Handle directly                               │             │
│  │  → discord-send.py to Discord                    │             │
│  │  → Output: SENT                                  │             │
│  └─────────────────────────────────────────────────┘             │
│                                                                  │
│  ┌─────────────────────────────────────────────────┐             │
│  │  PROJECT request (build/implement/continue)      │             │
│  │  → Match name in Known projects, use full path   │             │
│  │  → mkdir -p <full_path> (for new projects)       │             │
│  │  → Spawn isolated sub-session:                   │             │
│  │    (unset CLAUDECODE; cd <full_path> &&           │             │
│  │     claude --continue --permission-mode           │             │
│  │       bypassPermissions --print "...")            │             │
│  │  → Sub-session handles delivery + outputs SENT   │             │
│  └─────────────────────────────────────────────────┘             │
└─────────────────────────────────────────────────────────────────┘
         │ one-off                    │ project work
         │                           ▼
         │              ┌────────────────────────────┐
         │              │  Project sub-session        │
         │              │  (Claude in <full_path>)    │
         │              │                             │
         │              │  Config: inherits from      │
         │              │  ~/projects/CLAUDE.md       │
         │              │  (recursion guard)          │
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
│   Discord DM ──── target=1482473282925101217                     │
│   All messages end with: -# sent by claude (watermark)           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Agent Responsibilities

| Agent | Model | Working Dir | Config | Responsibility |
|---|---|---|---|---|
| **openclaw_claude** | claude-sonnet-4-6 | `~/projects/openclaw/` | `~/projects/openclaw/CLAUDE.md` | Entry point for all channel traffic. One-off: handles directly. Project work: spawns isolated sub-session. |
| **Project sub-session** | claude-sonnet-4-6 | `<full_path>` | `~/projects/CLAUDE.md` | Isolated per-project Claude session. Reads PROGRESS.md, does work, updates PROGRESS.md, sends to Discord, exits. |
| **Claude Code** (terminal) | claude-sonnet-4-6 | `D:\MyData\Software\openclaw-config\` | `CLAUDE.md` | Direct dev work with Pranav in terminal |

---

## Config Files — What Lives Where

```
C:\Users\prana\.openclaw\
└── openclaw.json                    ← BOT CONFIG
    • Discord bot token (used by discord-bot.py and discord-send.py)
    • API keys (Gemini, Groq, Ollama) — retained for potential future use
    • Session idle reset: 5 minutes

C:\Users\prana\AppData\Local\openclaw\   ← LOG DIR
├── delegate-YYYY-MM-DD.log          ← Human-readable delegation log
├── timeline-YYYY-MM-DD.log          ← JSON-lines machine log
├── bot.log                          ← NSSM stdout (discord-bot.py)
└── delegate.lock\                   ← Atomic lock dir (mkdir/rmdir)

D:\MyData\Software\openclaw-config\bin\   ← ALL SCRIPTS (live = repo)
├── discord-bot.py                   ← DISCORD GATEWAY
│   • discord.py NSSM service
│   • Reads token from ~/.openclaw/openclaw.json
│   • Spawns delegate.py as detached subprocess per message
│   • Async session watcher: pretty-prints JSONL activity to bot.log
│
├── discord-send.py                  ← OUTBOUND DISCORD REST
│   • urllib POST to Discord v10 API (no curl dependency)
│   • Reads token from ~/.openclaw/openclaw.json
│   • Args: --target <channel_id> --message <text>
│
├── delegate.py                      ← DELEGATION ORCHESTRATOR
│   • Sanitize, lock, log, collect context, build prompt
│   • Multi-root project scan (~/projects, ~/AndroidStudioProjects,
│     ~/PycharmProjects, ~/UnityProjects, D:\MyData\Software)
│   • Strips CLAUDECODE env var (prevents nested-session error)
│   • Writes prompt to temp file (avoids cmd.exe newline-splitting)
│   • Calls agent-smart.py (not claude directly) for auto-compaction
│   • --model sonnet, --continue, --permission-mode bypassPermissions
│   • Failure notification to Discord
│   • Dual logging: human-readable + JSON timeline
│   • session-reset after each delegation (no-op on Windows)
│
├── agent-smart.py                   ← AUTO-COMPACTING AGENT WRAPPER
│   • --print-file: reads prompt from file, pipes to claude stdin
│   • Checks session size before delegating (threshold: 400KB)
│   • Compact: keep last 5 user/assistant pairs, drop metadata
│   • Then: subprocess.run(['claude'] + args, shell=True on Windows)
│
├── bot-logs.py                      ← LIVE LOG VIEWER
│   • Tails %LOCALAPPDATA%\openclaw\bot.log (replaces journalctl -f)
│
├── route-audit.py                   ← DAILY LOG ANALYSIS
│   • Gathers delegate + timeline logs + bot health (sc query)
│   • Writes prompt to file (avoids cmd.exe newline-splitting)
│   • cd ~/projects/openclaw && agent-smart.py --continue --model sonnet
│   • Claude analyzes routing health, sends report to Discord
│
└── run-tests.py                     ← FULL TEST SUITE RUNNER
    • Runs all 3 test suites, optional --discord summary

C:\Users\prana\projects\
├── CLAUDE.md                        ← PROJECT SUB-SESSION GUARD
│   • "You're in a project dir — do the work, don't spawn sub-sessions"
│
└── openclaw\
    └── CLAUDE.md                    ← OPENCLAW_CLAUDE CONFIG
        • Job: do work, send via discord-send.py, output SENT
        • User profile, Discord format, watermark
        • Project routing (one-off vs spawn sub-session)
        • Sub-session spawn: (unset CLAUDECODE; cd <path> && claude ...)

D:\MyData\Software\openclaw-config\  ← THIS REPO (live = repo)
    config/openclaw.json             ← sanitized (secrets as ${VAR})
    bin/discord-bot.py, discord-send.py, delegate.py, agent-smart.py
    bin/bot-logs.py, route-audit.py, run-tests.py, session-reset.py
    bin/openclaw-timeline
    agents/openclaw-CLAUDE.md        ← canonical copy of openclaw/CLAUDE.md
    agents/projects-CLAUDE.md        ← canonical copy of ~/projects/CLAUDE.md
    scripts/sync-from-live.sh        ← Linux VM only (N/A on Windows)
    tests/test_delegate.py           ← unit tests (91 tests)
    tests/test_integration.py        ← integration tests (28 tests)
    tests/test_claude_behavior.py    ← behavior tests (live, uses capture file)
    docs/openclaw-architecture.md    ← this file

NSSM service:
    discord-bot  ← python discord-bot.py, AUTO_START
                    AppEnvironmentExtra USERPROFILE=C:\Users\prana
                    Logs to %LOCALAPPDATA%\openclaw\bot.log
```

---

## Logging System

```
%LOCALAPPDATA%\openclaw\
├── delegate-YYYY-MM-DD.log          ← Human-readable log (per delegation)
│   • Timestamp, channel, target, message preview
│   • Timing: ts_recv, ts_agent_start, ts_agent_done, ts_exit
│   • Duration: agent_ms, total_ms
│   • Exit code and output preview
│
├── timeline-YYYY-MM-DD.log          ← Machine-parseable JSON-lines
│   Events:
│   • delegate_recv   — message received (channel, target, msg_len, preview)
│   • sanitize        — chars replaced (orig_len, sanitized_len)
│   • lock_acquired   — lock obtained
│   • lock_blocked    — duplicate run prevented
│   • project_match   — always "openclaw" (Claude does routing)
│   • prompt_ready    — prompt built (bytes)
│   • agent_start     — Claude invocation started
│   • agent_done      — Claude finished (exit_code, duration_ms, output)
│   • failure_detected — delegation failed
│   • failure_notified — error message sent to Discord
│   • delegate_exit   — final output returned (total_ms)
│
└── bot.log                          ← discord-bot.py via NSSM
    • dispatch events (message receipt)
    • [project] [tool] / [assistant] lines from JSONL watcher
    View: python bot-logs.py

Daily audit: route-audit.py (manual or Task Scheduler, 8am PT)
  Reads delegate + timeline logs + sc query health
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
│  "Live" = repo. Edit → commit → push = deployed.                 │
│                                                                   │
│  Secrets: openclaw.json stored with ${VAR} placeholders          │
│  Pre-commit hook: blocks real secrets from being committed        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Key Design Decisions & Why

**discord-bot.py replaces openclaw gateway + Gemini**
Gemini was unreliably classifying messages, occasionally bypassing delegation, and consuming API quota as a passthrough router. The Python discord.py service is simpler: receive DM → spawn delegate → done. No AI in the hot path.

**`CREATE_NEW_PROCESS_GROUP|DETACHED_PROCESS` on Popen (Windows)**
Detaches delegate.py from the discord-bot.py process group. If the service restarts, running delegates survive and complete normally. Equivalent to `start_new_session=True` + `KillMode=process` on Linux.

**NSSM with USERPROFILE env override**
Running as LocalSystem makes `~` resolve to the SYSTEM profile dir. `AppEnvironmentExtra USERPROFILE=C:\Users\prana` ensures all scripts find the right home directory.

**agent-smart auto-compaction (400KB threshold, 5 pairs)**
Claude Code JSONL sessions grow unboundedly. At 400KB the context window starts filling up. Compaction keeps the last 5 user/assistant exchanges as history context, drops tool call metadata. Triggers before each agent invocation.

**Prompt via temp file (`--print-file`), not `--print`**
On Windows, cmd.exe splits commands at newline characters. Passing a multi-line prompt via `--print "..."` would cause truncation. Writing to a temp file and using `--print-file` bypasses cmd.exe entirely (agent-smart.py pipes via stdin).

**CLAUDECODE stripped from delegate env**
Claude Code sets `CLAUDECODE` in its process environment. If not stripped before spawning agent-smart.py, claude would refuse with "cannot launch inside another Claude Code session". delegate.py filters it out before spawning the agent subprocess.

**`unset CLAUDECODE` in sub-session spawns**
When openclaw_claude spawns a project sub-session via Bash, the child process inherits `CLAUDECODE` from the parent claude process. The spawn command explicitly unsets it: `(unset CLAUDECODE; cd <path> && claude --continue ...)`.

**Always delegate to openclaw project dir**
No bash pre-filter layer. Claude handles routing via CLAUDE.md instructions. Simpler code, same result.

**`--model sonnet` everywhere**
Sonnet (claude-sonnet-4-6) handles all delegations and route-audit. Opus reserved only if explicitly needed.

**`~/projects/CLAUDE.md` as recursion guard**
Sub-sessions in any project directory walk up to `~/projects/CLAUDE.md`. Says "you're in a project dir, just do the work" — prevents recursive sub-session spawning.

**Live = repo on Windows**
On Linux, scripts lived in `~/.local/bin/` and were copied to/from the repo. On Windows, the scripts live directly in `D:\MyData\Software\openclaw-config\bin\` — the repo IS the live deployment. No sync step needed.

---

## Known Risks

### OC-002 — Silent message drop on full RPM exhaustion (OPEN)
If Discord bot or Claude Code hits rate limits, the message may be silently dropped.
**Workaround:** wait 2+ minutes after heavy usage.

### Delegate lock drops parallel requests (LOW-MEDIUM)
If two messages arrive simultaneously, the second gets a "still working" notification and is dropped. Intentional for duplicate prevention, but legitimate parallel requests lose the second.

### `--continue` session context growth (MEDIUM — mitigated)
openclaw_claude accumulates session history. agent-smart compaction triggers at 400KB to cap growth.

### Prompt injection via message content (MEDIUM)
User message is passed verbatim into Claude's prompt.

### Service restart race (LOW — mitigated)
`DETACHED_PROCESS` + `CREATE_NEW_PROCESS_GROUP` mean delegate survives discord-bot.py restarts. But a machine reboot mid-delegation would still kill in-flight work.

---

## Test Suites

| Suite | File | Count | Scope |
|---|---|---|---|
| Unit tests | `tests/test_delegate.py` | 91 | Script presence, imports, lock, sanitization (OC-015/016), timeline events, failure notification, session reset, CLAUDECODE stripping, recursion guard, route-audit newline fix |
| Integration tests | `tests/test_integration.py` | 28 | Live delegation, lock dedup, discord-send, timeline validation, NSSM health, config, sub-session isolation |
| Behavior tests | `tests/test_claude_behavior.py` | 12 | Claude response quality: watermark, format, routing (requires live token) |
| Runner | `tests/run-tests.py` | — | Runs all 3 suites, optional --discord summary |
| Daily audit | `bin/route-audit.py` | — | Log analysis via Claude Sonnet: routing health, failure patterns, bot health |

---

## Scheduled Jobs

| Job | Schedule | Mechanism | Script |
|---|---|---|---|
| route-audit | 8am PT daily | Windows Task Scheduler (not yet configured) | `bin/route-audit.py` |
