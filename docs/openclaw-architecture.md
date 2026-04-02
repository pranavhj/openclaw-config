# openclaw System Architecture
_Last updated: 2026-04-01 — replaced openclaw/Gemini gateway with custom discord-bot.py_

---

## Message Flow (End-to-End)

```
┌─────────────────────────────────────────────────────────────────┐
│                     INBOUND CHANNEL                              │
│                                                                  │
│   Discord DM ──────────────────────► discord-bot.py              │
│   (allowFrom: 1277144623231537274)    (systemd service)          │
└─────────────────────────────────────────────────────────────────┘
                                │
                                │ subprocess.Popen(
                                │   ['delegate', 'discord', channel_id, content]
                                │ )
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│              /home/pranav/.local/bin/delegate                     │
│                                                                  │
│  1. Log: delegate_recv (timestamp, channel, target, msg_len)     │
│  2. Sanitize message:                                            │
│     • Apostrophes → U+2019 right single quote (OC-015)          │
│     • Backticks → U+2018 left single quote                       │
│     • Newlines → spaces (OC-016)                                 │
│  3. Log: sanitize (orig_len, sanitized_len, chars_replaced)      │
│  4. Acquire lock: /tmp/openclaw/delegate.lock (mkdir atomic)     │
│     ├─ If locked → log lock_blocked, discord-send notification,  │
│     │              echo SENT, exit                               │
│     └─ If free → log lock_acquired, continue                     │
│  5. Collect context:                                             │
│     • Projects list: ls -d /home/pranav/projects/*/             │
│     • Yesterday log fallback (if today < 3 entries)             │
│     • Recent message history (last 3, annotated with [project]) │
│  6. Match project from message + history → set WORK_DIR          │
│  7. Log: project_match (project name, work_dir)                  │
│  8. Build prompt in temp file (## Reply, ## Known projects,      │
│     ## Recent messages, ## Request)                              │
│  9. Log: prompt_ready (file path, bytes)                         │
│  10. Log: agent_start → Run Claude:                              │
│      cd /home/pranav/projects/<matched>                          │
│      agent --continue --permission-mode bypassPermissions        │
│             --print "$(cat $PROMPT_FILE)"                        │
│  11. Log: agent_done (exit_code, duration_ms, output_preview)    │
│  12. If failure (exit≠0 AND output≠"SENT"):                     │
│      • Log: failure_detected                                     │
│      • discord-send error notification                           │
│      • Log: failure_notified                                     │
│  13. Log: delegate_exit (total_ms, final_output)                 │
│                                                                  │
│  Logs:                                                           │
│    Human-readable: /tmp/openclaw/delegate-YYYY-MM-DD.log         │
│    Machine JSON:   /tmp/openclaw/timeline-YYYY-MM-DD.log         │
└─────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│         Claude agent — projects/<matched>/                       │
│                                                                  │
│  Working dir: /home/pranav/projects/<matched>/                   │
│  Config: /home/pranav/CLAUDE.md (+ projects/CLAUDE.md override)  │
│  Session: --continue (persists per project dir)                  │
│                                                                  │
│  Receives:  ## Reply, ## Known projects,                         │
│             ## Recent messages (tagged [project]), ## Request    │
│                                                                  │
│  Does the work, then:                                            │
│    discord-send --target <target> --message "<response>"         │
│  Output: SENT                                                    │
└─────────────────────────────────────────────────────────────────┘
                    │
                    │ discord-send → POST /channels/<id>/messages
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│   Discord DM — target=1482473282925101217                        │
│   All messages end with: -# sent by claude (watermark)           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Logging System

```
/tmp/openclaw/
├── delegate-YYYY-MM-DD.log          ← Human-readable (per delegation)
│   • channel, target, message preview, projects list
│   • ts_recv, ts_agent_start, ts_agent_done, ts_exit
│   • duration_agent_ms, duration_total_ms, exit_code
│
└── timeline-YYYY-MM-DD.log          ← Machine-parseable JSON-lines
    Events: delegate_recv, sanitize, lock_acquired, lock_blocked,
            project_match, prompt_ready, agent_start, agent_done,
            failure_detected, failure_notified, delegate_exit
```

---

## Source Control & Issue Tracking

```
github.com/pranavhj/openclaw-config (private)
/home/pranav/openclaw-config/  (also in ~/projects/)

AUTO-COMMIT (systemd path watcher)
  openclaw-config-sync.path watches live files:
    CLAUDE.md files, delegate, discord-bot.py, discord-send,
    route-audit, openclaw.json
  On change → sync-from-live.sh + git add -A + git commit + git push

ISSUE TRACKER: issues/OC-NNN-*.md + ISSUES.md index
```

---

## Config Files — What Lives Where

```
/home/pranav/
├── CLAUDE.md                        ← CLAUDE AGENT CONFIG
│   • discord-send command, user profile, response format
│   • Project detection, project mode
│
├── projects/
│   ├── CLAUDE.md                    ← PROJECT SUB-SESSION GUARD
│   │   • "You're in a project dir — just do the work"
│   │   • Prevents recursive sub-session spawning
│   │
│   └── openclaw/
│       └── CLAUDE.md               ← OPENCLAW_CLAUDE CONFIG
│           • Full system knowledge, source control workflow
│           • Known failure patterns
│
└── .local/bin/
    ├── delegate                     ← DELEGATION ORCHESTRATOR
    ├── discord-bot.py               ← DISCORD GATEWAY
    ├── discord-send                 ← DISCORD REST SENDER (curl)
    ├── session-reset                ← GEMINI SESSION RESET (legacy)
    ├── run-tests                    ← FULL TEST SUITE RUNNER
    └── route-audit                  ← DAILY LOG ANALYSIS

/home/pranav/.config/systemd/user/
    discord-bot.service              ← DISCORD BOT (replaces openclaw-gateway)
    openclaw-config-sync.path/.service ← AUTO-SYNC TO GIT

/home/pranav/.openclaw/
    openclaw.json                    ← BOT TOKEN + CHANNEL CONFIG
    workspace/AGENTS.md              ← ARCHIVED (gateway disabled)
```

---

## Agent Responsibilities

| Agent | Working Dir | Config | Responsibility |
|---|---|---|---|
| **discord-bot.py** | — | openclaw.json (token only) | Discord gateway: DM → subprocess delegate |
| **Claude agent** | projects/<matched>/ | CLAUDE.md + projects/CLAUDE.md | Do work, discord-send response, output SENT |
| **Claude Code** (terminal) | /home/pranav/ | CLAUDE.md | Direct dev work in terminal |

---

## Key Design Decisions

**Replaced openclaw/Gemini with discord-bot.py**
Gemini was a passthrough router burning free-tier API quota (20 RPM), causing rate limit failures and exec retry loops. The custom bot is a direct subprocess call — no AI in the routing layer.

**discord-send over openclaw message send**
Direct curl POST to Discord REST API v10. No gateway process. Token read from existing openclaw.json.

**Per-project cwd matching**
Delegate matches project name from message + recent history, cds to matching project dir. `--continue` session is per-project — no cross-project history contamination.

**Project-annotated history**
Recent messages tagged `[project]` in the prompt. Claude filters cross-project context.

**Lock file on delegate**
Atomic `mkdir` lock prevents concurrent invocations. Second caller gets "still working" Discord notification.

**Dual logging**
Human-readable log for quick debugging; JSON timeline for machine parsing by route-audit. Every step UTC-timestamped.

---

## Known Risks

### Claude Code usage limit (HIGH)
`delegate` calls `agent --continue` (Claude Code subprocess). If the Claude Code usage cap is hit, all delegations fail with "You've hit your limit · resets Xpm". Failure notification sent to Discord, but no fallback.
**Mitigation:** failure notification informs user; wait for reset.

### Delegate lock drops parallel requests (LOW-MEDIUM)
Simultaneous messages: second gets "still working" and is dropped. Intentional but legitimate parallel requests lose the second.

### `--continue` session context growth (MEDIUM)
Per-project sessions accumulate history. Eventually the context window fills.

### Prompt injection (MEDIUM)
Message passed verbatim into Claude's prompt.

---

## Test Suites

| Suite | File | Tests |
|---|---|---|
| Unit | `/home/pranav/test_delegate.sh` | 86 tests — delegate logic, locks, logging, sanitization, discord-bot.py/discord-send presence, CLAUDE.md send command |
| Integration | `/home/pranav/test_integration.sh` | 45 tests — e2e delegation, discord-bot health, discord-send, timeline, crons |
| Behavior | `/home/pranav/test_claude_behavior.sh` | Claude response quality |
| Runner | `~/.local/bin/run-tests` | All 3 suites → Discord summary |
| Daily audit | `~/.local/bin/route-audit` | Log analysis via Claude Opus |
