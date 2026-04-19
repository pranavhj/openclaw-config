# openclaw System Architecture
_Last updated: 2026-04-18 (OC-020 — post-Gemini-gateway migration)_

---

## Message Flow (End-to-End)

```
┌─────────────────────────────────────────────────────────────────┐
│                     INBOUND CHANNEL                              │
│                                                                  │
│   Discord DM ──────────────────────► discord-bot.py             │
│   (allowFrom: 1277144623231537274)    systemd service            │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│          discord-bot.py  — /home/pranav/.local/bin/              │
│                                                                  │
│  Library: discord.py with Message Content Intent                 │
│  Token: read from ~/.openclaw/openclaw.json at startup           │
│  Allowlist: ALLOWED_USER = 1277144623231537274 (DMs only)        │
│                                                                  │
│  On message:                                                     │
│    1. Ignore bots and non-allowlisted users                      │
│    2. Download attachments → /tmp/openclaw/attachments/<msg_id>/ │
│       Set DELEGATE_ATTACHMENTS env var if any                    │
│    3. Replace newlines with spaces                               │
│    4. subprocess.Popen(['delegate', ch, target, content],        │
│         start_new_session=True)   ← detached, survives restart   │
│                                                                  │
│  Logs to journald (systemd --user unit: discord-bot.service)     │
│  Also runs async session watcher (watch_claude_sessions):        │
│    • Polls ~/.claude/projects/**/*.jsonl every 1s                │
│    • Pretty-prints tool calls + text to stdout → journald        │
│    • Shows: [project] [tool] Bash: ..., [project] [assistant] …  │
│    • Skip memory files                                           │
│                                                                  │
│  View live logs: bot-logs  (journalctl --user -u discord-bot -f) │
└─────────────────────────────────────────────────────────────────┘
                    │ subprocess.Popen (detached)
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│              /home/pranav/.local/bin/delegate                     │
│                                                                  │
│  1. Log: delegate_recv (timestamp, channel, target, msg_len)     │
│  2. Sanitize message:                                            │
│     • Apostrophes → U+2019 right single quote (OC-015)          │
│     • Backticks → U+2018 left single quote                      │
│     • Newlines → spaces (OC-016)                                 │
│  3. Log: sanitize (orig_len, sanitized_len, chars_replaced)      │
│  4. Acquire lock: /tmp/openclaw/delegate.lock (mkdir atomic)     │
│     ├─ If locked → notify user via discord-send, echo SENT, exit │
│     └─ If free → log lock_acquired, continue                     │
│  5. Collect context:                                             │
│     • Projects list: ls /home/pranav/projects/                   │
│     • Recent history: last 5 entries from timeline log           │
│  6. Build prompt in temp file (## Reply, ## Known projects,      │
│     ## Recent messages, ## Request, ## Attachments if any)       │
│  7. Log: prompt_ready (file path, bytes)                         │
│  8. Log: agent_start → Run Claude:                               │
│     cd /home/pranav/projects/openclaw                            │
│     agent-smart --continue --permission-mode bypassPermissions   │
│                 --model sonnet --print "$(cat $PROMPT_FILE)"     │
│  9. Log: agent_done (exit_code, duration_ms, output_preview)     │
│  10. If failure (exit≠0 AND output≠"SENT"):                     │
│     • Log: failure_detected                                      │
│     • discord-send error notification to user                    │
│     • Log: failure_notified                                      │
│  11. session-reset (clears openclaw session after each run)      │
│  12. Log: delegate_exit (total_ms, final_output)                 │
│  13. Echo OUTPUT                                                 │
│                                                                  │
│  Logs:                                                           │
│    Human-readable: /tmp/openclaw/delegate-YYYY-MM-DD.log         │
│    Machine JSON:   /tmp/openclaw/timeline-YYYY-MM-DD.log         │
└─────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│         agent-smart  — /home/pranav/.local/bin/                  │
│                                                                  │
│  Wrapper around `agent --continue` with auto-compaction:         │
│    • Reads ~/.claude/projects/<cwd-key>/*.jsonl                  │
│    • If session > 400KB: compact to last 5 message pairs         │
│      Python: keeps user/assistant entries only, drops metadata   │
│      Creates new UUID-named JSONL, deletes old one               │
│    • Then: exec agent "$@"                                       │
└─────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│         openclaw_claude (Claude) — projects/openclaw/            │
│                                                                  │
│  Model: claude-sonnet-4-6 (--model sonnet)                       │
│  Working dir: /home/pranav/projects/openclaw/                    │
│  Config: /home/pranav/projects/openclaw/CLAUDE.md                │
│  Session: --continue (persists across delegations)               │
│                                                                  │
│  Receives prompt with:                                           │
│    ## Reply  (channel + target for response delivery)            │
│    ## Known projects (list from /home/pranav/projects/)          │
│    ## Recent messages (last 5, tagged by project)                │
│    ## Request (user's full message verbatim)                     │
│    ## Attachments (paths if files were uploaded)                 │
│                                                                  │
│  ┌─────────────────────────────────────────────────┐             │
│  │  ONE-OFF request (question, analysis, fix)       │             │
│  │  → Handle directly                               │             │
│  │  → discord-send to Discord                       │             │
│  │  → Output: SENT                                  │             │
│  └─────────────────────────────────────────────────┘             │
│                                                                  │
│  ┌─────────────────────────────────────────────────┐             │
│  │  PROJECT request (build/implement/continue)      │             │
│  │  → Match slug in known projects list             │             │
│  │  → mkdir -p /home/pranav/projects/<slug>         │             │
│  │  → Spawn isolated sub-session:                   │             │
│  │    cd projects/<slug> &&                         │             │
│  │    agent-smart --continue --print "..."          │             │
│  │  → Sub-session handles delivery + outputs SENT   │             │
│  └─────────────────────────────────────────────────┘             │
└─────────────────────────────────────────────────────────────────┘
         │ one-off                    │ project work
         │                           ▼
         │              ┌────────────────────────────┐
         │              │  Project sub-session        │
         │              │  (Claude in projects/<slug>)│
         │              │                             │
         │              │  Config: inherits from      │
         │              │  projects/CLAUDE.md +       │
         │              │  /home/pranav/CLAUDE.md     │
         │              │                             │
         │              │  • Reads PROGRESS.md        │
         │              │  • Does the work            │
         │              │  • Updates PROGRESS.md      │
         │              │  • discord-send to Discord  │
         │              │  • Exits (one-shot)         │
         │              │  • Session history persists │
         │              │    in JSONL for next call   │
         │              └────────────────────────────┘
         │                           │
         └───────────────────────────┘
                                     │
                    discord-send --target <tgt> --message "..."
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
| **openclaw_claude** | claude-sonnet-4-6 | `projects/openclaw/` | `projects/openclaw/CLAUDE.md` | Entry point for all channel traffic. One-off: handles directly. Project work: spawns isolated sub-session. |
| **Project sub-session** | claude-sonnet-4-6 | `projects/<slug>/` | `projects/CLAUDE.md` + `CLAUDE.md` | Isolated per-project Claude session. Reads PROGRESS.md, does work, updates PROGRESS.md, sends to Discord, exits. |
| **Claude Code** (terminal) | claude-sonnet-4-6 | `/home/pranav/` | `CLAUDE.md` | Direct dev work with Pranav in terminal |

---

## Config Files — What Lives Where

```
/home/pranav/.openclaw/
└── openclaw.json                    ← BOT + GATEWAY CONFIG
    • Discord bot token (used by discord-bot.py)
    • API keys (Gemini, Groq, Ollama) — retained for potential future use
    • Gateway port: 18789 (not used by discord-bot.py path)
    • Session idle reset: 5 minutes

/home/pranav/.local/bin/
├── discord-bot.py                   ← DISCORD GATEWAY (replaces openclaw gateway)
│   • discord.py service (systemd discord-bot.service)
│   • Reads token from ~/.openclaw/openclaw.json
│   • Spawns delegate as detached subprocess per message
│   • Async session watcher: pretty-prints JSONL activity to journald
│
├── discord-send                     ← OUTBOUND DISCORD REST
│   • curl POST to Discord v10 API
│   • Reads token from ~/.openclaw/openclaw.json
│   • Args: --target <channel_id> --message <text>
│
├── delegate                         ← DELEGATION ORCHESTRATOR
│   • Sanitize, lock, log, collect context, build prompt
│   • Calls agent-smart (not agent) for auto-compaction
│   • --model sonnet, --continue, --permission-mode bypassPermissions
│   • Failure notification to Discord
│   • Dual logging: human-readable + JSON timeline
│   • session-reset after each delegation
│
├── agent-smart                      ← AUTO-COMPACTING AGENT WRAPPER
│   • Checks session size before delegating (threshold: 400KB)
│   • Compact: keep last 5 user/assistant pairs, drop metadata
│   • Then: exec agent "$@"
│
├── bot-logs                         ← LIVE LOG VIEWER
│   • journalctl --user -u discord-bot -f --no-pager
│
├── route-audit                      ← DAILY LOG ANALYSIS
│   • Gathers delegate + timeline logs + bot health from journald
│   • cd projects/openclaw && agent-smart --continue --model sonnet
│   • Claude analyzes routing health, sends report to Discord
│
└── run-tests                        ← FULL TEST SUITE RUNNER
    • Runs all 3 test suites, sends Discord summary

/home/pranav/
├── CLAUDE.md                        ← DIRECT TERMINAL CLAUDE CONFIG
│   • openclaw agent instructions, user profile, response format
│
├── projects/
│   ├── CLAUDE.md                    ← PROJECT SUB-SESSION GUARD
│   │   • "You're in a project dir — do the work, don't spawn sub-sessions"
│   │
│   ├── openclaw/
│   │   └── CLAUDE.md               ← OPENCLAW_CLAUDE CONFIG
│   │       • Job: do work, send via discord-send, output SENT
│   │       • User profile, Discord format, watermark
│   │       • Project routing (one-off vs spawn sub-session)
│   │
│   ├── openclaw-config/             ← THIS REPO
│   │
│   └── <user-projects>/             ← Actual project work
│       ├── PROGRESS.md              ← State bookmark (Claude maintains)
│       └── <source files>

/home/pranav/.config/systemd/user/
└── discord-bot.service              ← SYSTEMD SERVICE
    • KillMode=process (delegate subprocesses survive service restarts)
    • Enabled, starts on login

/home/pranav/projects/openclaw-config/  ← THIS REPO
    config/openclaw.json             ← sanitized (secrets as ${VAR})
    bin/discord-bot.py, discord-send, delegate, agent-smart, bot-logs
    bin/route-audit, run-tests, session-reset, openclaw-timeline
    agents/openclaw-CLAUDE.md
    agents/projects-CLAUDE.md
    scripts/sync-from-live.sh        ← copies live → repo + redacts secrets
    scripts/sync-to-live.sh          ← deploys repo → live paths
    docs/openclaw-architecture.md    ← this file
```

---

## Logging System

```
/tmp/openclaw/
├── delegate-YYYY-MM-DD.log          ← Human-readable log (per delegation)
│   • Timestamp, channel, target, message preview
│   • Timing: ts_recv, ts_agent_start, ts_agent_done, ts_exit
│   • Duration: agent_ms, total_ms
│   • Exit code and output preview
│
└── timeline-YYYY-MM-DD.log          ← Machine-parseable JSON-lines
    Events:
    • delegate_recv   — message received (channel, target, msg_len, preview)
    • sanitize        — chars replaced (orig_len, sanitized_len)
    • lock_acquired   — lock obtained
    • lock_blocked    — duplicate run prevented
    • project_match   — always "openclaw" (Claude does routing)
    • prompt_ready    — prompt file built (path, bytes)
    • agent_start     — Claude invocation started
    • agent_done      — Claude finished (exit_code, duration_ms, output)
    • failure_detected — delegation failed
    • failure_notified — error message sent to Discord
    • delegate_exit   — final output returned (total_ms)

journald (via discord-bot.py service):
    • dispatch events (message receipt)
    • delegate pid
    • [project] [tool] / [assistant] lines from JSONL watcher
    View: bot-logs

Daily audit: route-audit (systemd timer, 8am PT)
  Reads delegate + timeline logs + bot journal health
  Passes to agent-smart --model sonnet --continue
```

---

## Source Control

```
┌─────────────────────────────────────────────────────────────────┐
│          github.com/pranavhj/openclaw-config (public)            │
│          /home/pranav/projects/openclaw-config/                  │
│                                                                   │
│  AUTO-COMMIT (systemd path watcher)                              │
│  openclaw-config-sync.path watches live files:                   │
│    delegate, route-audit, discord-bot.py, discord-send,          │
│    agent-smart, openclaw-CLAUDE.md, projects-CLAUDE.md,          │
│    openclaw.json, SKILL.md files                                 │
│                                                                   │
│  On change → sync-from-live.sh + git add -A + commit + push      │
│                                                                   │
│  Secrets: openclaw.json stored with ${VAR} placeholders          │
│  Pre-commit hook: blocks real secrets from being committed        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Key Design Decisions & Why

**discord-bot.py replaces openclaw gateway + Gemini**
Gemini was unreliably classifying messages, occasionally bypassing delegation, and consuming API quota as a passthrough router. The Python discord.py service is simpler: receive DM → spawn delegate → done. No AI in the hot path.

**`start_new_session=True` on Popen**
Detaches delegate from the discord-bot.py process group. If the service restarts (e.g., from a path watcher auto-reload), running delegates survive and complete normally.

**`KillMode=process` in systemd unit**
Prevents systemd from killing the entire cgroup on service stop. Combined with `start_new_session=True`, delegate processes are fully isolated.

**agent-smart auto-compaction (400KB threshold, 5 pairs)**
Claude Code JSONL sessions grow unboundedly. At 400KB the context window starts filling up. Compaction keeps the last 5 user/assistant exchanges as history context, drops tool call metadata. Triggers before each agent invocation.

**Always delegate to openclaw project dir**
No bash pre-filter layer. Claude handles routing via CLAUDE.md instructions. Simpler code, same result.

**`--model sonnet` everywhere**
Sonnet (claude-sonnet-4-6) handles all delegations and route-audit. Opus reserved only if explicitly needed.

**session-reset after each delegation**
Clears the openclaw_claude session after each completed delegation. Prevents cross-request context contamination and keeps token usage low.

**discord-send uses REST API directly**
`curl POST` to Discord v10. No gateway dependency. Simple, reliable, no external process dependencies.

**`projects/CLAUDE.md` as recursion guard**
Sub-sessions in `projects/<slug>/` walk up to `projects/CLAUDE.md` before reaching `/home/pranav/CLAUDE.md`. Says "you're in a project dir, just do the work" — prevents recursive sub-session spawning.

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
KillMode=process + start_new_session=True mean delegate survives discord-bot.py restarts. But a machine reboot mid-delegation would still kill in-flight work.

---

## Test Suites

| Suite | File | Scope |
|---|---|---|
| Unit tests | `/home/pranav/test_delegate.sh` | Delegate script: lock, logging, sanitization, config validation, timeline events, failure notification |
| Integration tests | `/home/pranav/test_integration.sh` | End-to-end: live delegation, workspace integrity |
| Behavior tests | `/home/pranav/test_claude_behavior.sh` | Claude response quality: multi-line, special chars, watermark, format |
| Runner | `/home/pranav/.local/bin/run-tests` | Runs all 3 suites, sends Discord summary |
| Daily audit | `/home/pranav/.local/bin/route-audit` | Log analysis via Claude Sonnet: routing health, failure patterns, bot health |

---

## Cron & Scheduled Jobs

| Job | Schedule | Mechanism | Script |
|---|---|---|---|
| route-audit | 8am PT daily | systemd timer | `/home/pranav/.local/bin/route-audit` |
