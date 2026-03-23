# openclaw System Architecture
_Last updated: 2026-03-23_

---

## Message Flow (End-to-End)

```
┌─────────────────────────────────────────────────────────────────┐
│                     INBOUND CHANNEL                              │
│                                                                  │
│   Discord DM ──────────────────────► openclaw gateway            │
│   (allowFrom: 1277144623231537274)    port 18789                 │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│               GEMINI (agent:main) — PASSTHROUGH ROUTER           │
│                                                                  │
│  Model: google/gemini-2.5-flash                                  │
│  Thinking: off (thinkingDefault: "off")                          │
│  Fallbacks: none (empty array)                                   │
│  Workspace: /home/pranav/.openclaw/workspace/                    │
│  Skills: 5 workspace only (bundled disabled via                  │
│          allowBundled: ["__none__"])                              │
│                                                                  │
│  Reads on startup:                                               │
│    AGENTS.md   → passthrough routing rules (~15 lines)           │
│    SOUL.md     → # unused (stripped)                             │
│    IDENTITY.md → # unused (stripped)                             │
│    TOOLS.md    → # unused (stripped)                             │
│    USER.md     → # unused (stripped)                             │
│    HEARTBEAT.md → heartbeat config (kept)                        │
│                                                                  │
│  ┌──────────────────────────────────────────────────┐            │
│  │  ALL messages → delegate skill → exec(delegate)   │            │
│  │  After exec returns → STOP. No further output.    │            │
│  │  No retries. No error handling. No thinking.      │            │
│  └──────────────────────────────────────────────────┘            │
│                                                                  │
│  Exceptions (handled directly, no delegation):                   │
│    - Heartbeat checks → HEARTBEAT_OK                             │
│    - /quota → exec-dispatch quota skill                          │
│    - /gemini_requests → exec-dispatch gemini-requests skill      │
└─────────────────────────────────────────────────────────────────┘
                    │ exec(delegate discord <tgt> <msg>)
                    │ yieldMs: 120000
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
│     ├─ If locked → log lock_blocked, echo SENT, exit             │
│     └─ If free → log lock_acquired, continue                     │
│  5. Collect context:                                             │
│     • Projects list: ls /home/pranav/projects/                   │
│  6. Build prompt in temp file (## Reply, ## Known projects,      │
│     ## Request)                                                  │
│  7. Log: prompt_ready (file path, bytes)                         │
│  8. Log: agent_start → Run Claude:                               │
│     cd /home/pranav/projects/openclaw                            │
│     agent --continue --permission-mode bypassPermissions         │
│            --print "$(cat $PROMPT_FILE)"                         │
│  9. Log: agent_done (exit_code, duration_ms, output_preview)     │
│  10. If failure (exit≠0 AND output≠"SENT"):                     │
│     • Log: failure_detected                                      │
│     • Send error notification to Discord                         │
│     • Log: failure_notified                                      │
│     • Set OUTPUT="SENT" to stop Gemini                           │
│  11. Log: delegate_exit (total_ms, final_output)                 │
│  12. Echo output (openclaw sees "SENT")                          │
│                                                                  │
│  Logs:                                                           │
│    Human-readable: /tmp/openclaw/delegate-YYYY-MM-DD.log         │
│    Machine JSON:   /tmp/openclaw/timeline-YYYY-MM-DD.log         │
└─────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│         openclaw_claude (Claude) — projects/openclaw/            │
│                                                                  │
│  Working dir: /home/pranav/projects/openclaw/                    │
│  Config: /home/pranav/projects/openclaw/CLAUDE.md                │
│  Session: --continue (persists across conversations)             │
│                                                                  │
│  Receives prompt with:                                           │
│    ## Reply  (channel + target for response delivery)            │
│    ## Known projects (list from /home/pranav/projects/)          │
│    ## Request (user's full message verbatim)                     │
│                                                                  │
│  ┌─────────────────────────────────────────────────┐             │
│  │  ONE-OFF request (question, analysis, fix)       │             │
│  │  → Handle directly                               │             │
│  │  → openclaw message send to Discord              │             │
│  │  → Output: SENT                                  │             │
│  └─────────────────────────────────────────────────┘             │
│                                                                  │
│  ┌─────────────────────────────────────────────────┐             │
│  │  PROJECT request (build/implement/continue)      │             │
│  │  → Match slug in known projects list             │             │
│  │  → mkdir -p /home/pranav/projects/<slug>         │             │
│  │  → Spawn isolated sub-session:                   │             │
│  │    cd projects/<slug> &&                         │             │
│  │    agent --continue --print "..."                │             │
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
         │              │  • Sends to Discord         │
         │              │  • Exits (one-shot)         │
         │              │  • Session history persists │
         │              │    in JSONL for next call   │
         │              └────────────────────────────┘
         │                           │
         └───────────────────────────┘
                                     │
                    openclaw message send --channel discord --target <tgt>
                                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                   OUTBOUND DELIVERY                              │
│                                                                  │
│   Discord DM ──── channel=discord, target=1482473282925101217    │
│   All messages end with: -# sent by claude (watermark)           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Special Paths (bypass delegate)

```
User: "run tests" / "check routing"
    │
    ▼
Gemini loads routing-audit skill
    │
    ▼
exec({command: 'run-tests'})
    │
    ▼
/home/pranav/.local/bin/run-tests
  • SKIP_GATEWAY_RESTART=1
  • Runs test_delegate.sh       → unit results
  • Runs test_integration.sh    → integration results
  • Runs test_claude_behavior.sh → behavior results
  • Sends formatted summary to Discord (itself, no Claude involved)

User: "analyze logs" / "route-audit"
    │
    ▼
Gemini loads routing-audit skill → exec({command: 'route-audit'})
    │
    ▼
/home/pranav/.local/bin/route-audit
  • Gathers delegate log + timeline log + gateway log + session JSONLs
  • Passes to: cd /home/pranav/projects/openclaw && agent --continue --model claude-opus-4-6
  • Claude analyzes + sends Discord report

User: "/quota" or "/gemini_requests"
    │
    ▼
Gemini exec-dispatches directly (no delegate, no Claude):
  quota:            python3 /home/pranav/gemini_counter.py status
  gemini-requests:  /gemini_requests gq
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
├── timeline-YYYY-MM-DD.log          ← Machine-parseable JSON-lines
│   Events:
│   • delegate_recv   — message received (channel, target, msg_len, preview)
│   • sanitize        — chars replaced (orig_len, sanitized_len)
│   • lock_acquired   — lock obtained
│   • lock_blocked    — duplicate run prevented
│   • prompt_ready    — prompt file built (path, bytes)
│   • agent_start     — Claude invocation started
│   • agent_done      — Claude finished (exit_code, duration_ms, output)
│   • failure_detected — delegation failed
│   • failure_notified — error message sent to Discord
│   • delegate_exit   — final output returned (total_ms)
│
└── openclaw-YYYY-MM-DD.log          ← Gateway log (all subsystems)

Daily audit: route-audit (systemd timer, 8am PT)
  Reads all three logs + session JSONLs, passes to Claude Opus for analysis
```

---

## Source Control & Issue Tracking

```
┌─────────────────────────────────────────────────────────────────┐
│          github.com/pranavhj/openclaw-config (private)           │
│          /home/pranav/openclaw-config/  (also in ~/projects/)    │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  AUTO-COMMIT (systemd path watcher)                       │    │
│  │  openclaw-config-sync.path watches live files:            │    │
│  │    AGENTS.md, all SKILL.md files, openclaw-CLAUDE.md,     │    │
│  │    projects-CLAUDE.md, delegate, route-audit, openclaw.json│   │
│  │                                                            │    │
│  │  On any change → openclaw-config-sync.service runs:        │    │
│  │    1. sync-from-live.sh (redacts secrets)                  │    │
│  │    2. git add -A                                           │    │
│  │    3. git commit "sync(misc): auto-commit..."              │    │
│  │    4. git push                                             │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  ISSUE TRACKER  (issues/OC-NNN-*.md + ISSUES.md index)    │    │
│  │  OC-001 (wontfix) retry.attempts=1 not applying           │    │
│  │  OC-002 (open)    silent drop on full RPM exhaustion      │    │
│  │  OC-003–OC-009    (fixed) various routing/config issues   │    │
│  │  OC-010–OC-014    (fixed) Gemini behavioral issues        │    │
│  │  OC-015 (fixed)   apostrophes break delegate exec         │    │
│  │  OC-016 (fixed)   newlines break delegate exec            │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                   │
│  Secrets: openclaw.json stored with ${VAR} placeholders          │
│  Credentials: token in ~/.git-credentials (not in remote URL)    │
│  Pre-commit hook: blocks real secrets from being committed        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Config Files — What Lives Where

```
/home/pranav/.openclaw/
├── openclaw.json                    ← GATEWAY CONFIG
│   • API keys (Gemini, Groq, Ollama)
│   • Agent model: gemini-2.5-flash (no fallbacks)
│   • thinkingDefault: "off" (saves API quota)
│   • Workspace: /home/pranav/.openclaw/workspace/
│   • skills.allowBundled: ["__none__"] (disables all bundled)
│   • Channel: discord only (retry=1)
│   • allowFrom: user ID (allowlist)
│   • Gateway port: 18789, auth token
│   • Tools: coding profile, web search, exec security=full
│   • Session idle reset: 5 minutes
│
├── workspace/
│   ├── AGENTS.md                    ← PASSTHROUGH ROUTER (~15 lines)
│   │   • Delegate EVERY message via delegate skill
│   │   • Newline replacement instruction (OC-016)
│   │   • After exec: STOP, no retries, no error handling
│   │   • Exceptions: heartbeat, /quota, /gemini_requests
│   │
│   ├── SOUL.md                      ← # unused (stripped to save tokens)
│   ├── IDENTITY.md                  ← # unused (stripped)
│   ├── TOOLS.md                     ← # unused (stripped)
│   ├── USER.md                      ← # unused (stripped)
│   ├── HEARTBEAT.md                 ← Periodic task checklist (kept)
│   │
│   └── skills/                      ← WORKSPACE SKILLS ONLY
│       ├── delegate/SKILL.md        ← HOW TO CALL DELEGATE
│       │   • description embeds exec command + yieldMs:120000
│       │   • Newline handling (OC-016), quoting rules (OC-015)
│       │   • No retries, no further output after exec returns
│       │
│       ├── routing-audit/SKILL.md   ← HOW TO RUN TESTS / AUDIT LOGS
│       ├── discord-send/SKILL.md    ← PROACTIVE DISCORD MESSAGES
│       ├── quota/SKILL.md           ← /quota COMMAND
│       └── gemini-requests/SKILL.md ← /gemini_requests COMMAND
│
└── agents/
    └── main/
        └── sessions/                ← GEMINI SESSION STORE
            ├── sessions.json        ← session index
            └── *.jsonl              ← session history

/home/pranav/
├── CLAUDE.md                        ← DIRECT TERMINAL CLAUDE CONFIG
│   • openclaw agent instructions, user profile, response format
│   • Workspace paths, project detection, project mode
│   • NOT read by openclaw-mediated calls
│
├── projects/
│   ├── CLAUDE.md                    ← PROJECT SUB-SESSION OVERRIDE
│   │   • "You're in a project dir — do the work, don't spawn sub-sessions"
│   │   • Prevents recursion when openclaw_claude spawns sub-sessions
│   │
│   ├── openclaw/
│   │   └── CLAUDE.md               ← OPENCLAW_CLAUDE CONFIG
│   │       • Job: do work, send via openclaw, output SENT
│   │       • User profile, Discord format, -# sent by claude watermark
│   │       • Project routing (one-off vs spawn sub-session)
│   │       • Source control workflow (sync + commit with OC-NNN)
│   │       • openclaw system knowledge + failure patterns
│   │
│   ├── openclaw-config -> /home/pranav/openclaw-config   ← SYMLINK
│   │
│   └── <user-projects>/             ← Actual project work
│       ├── PROGRESS.md              ← State bookmark (Claude maintains)
│       └── <source files>
│
└── .local/bin/
    ├── delegate                     ← DELEGATION ORCHESTRATOR
    │   • Sanitize, lock, log, build prompt, invoke Claude
    │   • Failure notification to Discord
    │   • Dual logging: human-readable + JSON timeline
    │
    ├── run-tests                    ← FULL TEST SUITE RUNNER
    │   • SKIP_GATEWAY_RESTART=1
    │   • Runs all 3 suites, sends Discord summary
    │
    └── route-audit                  ← DAILY LOG ANALYSIS
        • Gathers delegate + timeline + gateway logs + session JSONLs
        • cd projects/openclaw && agent --continue --model claude-opus-4-6
        • Claude analyzes routing health, sends report to Discord

/home/pranav/openclaw-config/        ← SOURCE CONTROL REPO
    config/openclaw.json             ← sanitized (secrets as ${VAR})
    workspace/AGENTS.md
    workspace/skills/*/SKILL.md
    agents/openclaw-CLAUDE.md
    agents/projects-CLAUDE.md
    bin/delegate, route-audit, run-tests
    issues/OC-NNN-*.md
    scripts/sync-from-live.sh        ← copies live → repo + redacts secrets
    scripts/sync-to-live.sh          ← deploys repo → live paths
    docs/openclaw-architecture.md    ← this file

/home/pranav/.config/systemd/user/
    openclaw-config-sync.path        ← watches live config files
    openclaw-config-sync.service     ← auto-sync + commit + push on change
```

---

## Agent Responsibilities

| Agent | Model | Working Dir | Config | Responsibility |
|---|---|---|---|---|
| **Gemini** (agent:main) | gemini-2.5-flash | `.openclaw/workspace/` | AGENTS.md | Passthrough router: exec delegate for every message. No thinking, no classification, no retries. |
| **openclaw_claude** | claude-sonnet-4-6 | `projects/openclaw/` | `projects/openclaw/CLAUDE.md` | Entry point for all channel traffic. One-off: handles directly. Project work: spawns isolated sub-session in project dir. |
| **Project sub-session** | claude-sonnet-4-6 | `projects/<slug>/` | `projects/CLAUDE.md` + `CLAUDE.md` | Isolated per-project Claude session. Reads PROGRESS.md, does work, updates PROGRESS.md, sends to Discord, exits. |
| **Claude Code** (terminal) | claude-opus-4-6 | `/home/pranav/` | `CLAUDE.md` | Direct dev work with Pranav in terminal |

---

## Skill Responsibilities

| Skill | Trigger | Action | Who Runs |
|---|---|---|---|
| **delegate** | Every message (default) | `exec(delegate <ch> <tgt> <msg>, yieldMs:120000)` | Gemini |
| **routing-audit** | "run tests", "check routing" | `exec(run-tests)` or `exec(route-audit)` | Gemini directly |
| **discord-send** | Proactive notifications | `exec(openclaw message send ...)` | Gemini |
| **quota** | `/quota` | `exec(python3 gemini_counter.py status)` | Gemini exec-dispatch |
| **gemini-requests** | `/gemini_requests` | `exec(/gemini_requests gq)` | Gemini exec-dispatch |

---

## Token Optimization

Per-request token breakdown (before → after passthrough rewrite):

| Source | Before | After |
|---|---|---|
| AGENTS.md | ~2,300 | ~200 (passthrough, 15 lines) |
| SOUL/IDENTITY/TOOLS/USER.md | ~2,000 | ~40 (all `# unused`) |
| 55 bundled skill definitions | ~2,500 | 0 (disabled) |
| Gemini thinking overhead | ~500-1000 | 0 (thinkingDefault: off) |
| **Total per request** | **~7,300** | **~300** |

---

## Key Design Decisions & Why

**Passthrough router (no Mode 1/Mode 2)**
Gemini was unreliably classifying messages. Removing classification means every message gets one exec call — simpler, more reliable, fewer API calls.

**`thinkingDefault: "off"`**
Gemini's thinking budget was wasted on a passthrough router. Saves tokens and latency.

**Workspace files stripped to `# unused`**
SOUL.md, IDENTITY.md, TOOLS.md, USER.md are irrelevant for a router. Stripping saves ~2KB per turn.

**No fallback models**
Groq models can't use exec tool (skills are Gemini-specific). Fallbacks just waste API calls. If Gemini is down, delegation simply fails and the delegate script notifies via Discord.

**`yieldMs: 120000` on delegate exec**
Default is 10s which backgrounds the command before Claude responds. 2 min gives Claude time to complete.

**`allowBundled: ["__none__"]` (not `[]`)**
Empty allowlist means "allow all" in openclaw's logic. A non-empty list with no matching names disables all 55 bundled skills.

**`--continue` on delegate, and per-project sub-sessions**
openclaw_claude accumulates session history for diagnostics. Project work gets isolated `--continue` sessions in their own dirs — each project's Claude has full conversation history without cross-project contamination.

**`projects/CLAUDE.md` as recursion guard**
Sub-sessions spawned in `projects/<slug>/` walk up to `projects/CLAUDE.md` before reaching `/home/pranav/CLAUDE.md`. This file says "you're in a project dir, just do the work" — preventing recursive sub-session spawning.

**Lock file on delegate**
Gemini sometimes double-fires execs. The `mkdir` lock (atomic) ensures only one Claude invocation runs at a time; second caller gets SENT immediately.

**Skill description embeds the exec command**
Gemini was hallucinating wrong SKILL.md paths (ENOENT). Embedding the command in the frontmatter `description` means Gemini never needs to read the file.

**Dual logging (human + timeline JSON)**
Human-readable log for quick debugging, JSON timeline for machine parsing by route-audit. Every step is timestamped in UTC.

**Failure notification to Discord**
When delegation fails, delegate script sends an error message to Discord so the user isn't left waiting in silence. Then returns "SENT" to Gemini so it stops.

**Message sanitization (OC-015, OC-016)**
Apostrophes → U+2019, backticks → U+2018, newlines → spaces. Prevents shell parse errors that silently dropped messages.

---

## Known Risks

### OC-002 — Silent message drop on full RPM exhaustion (HIGH)
When Gemini hits per-minute rate limits, the message may be silently dropped. No Discord notification at the gateway level.
**Workaround:** wait 2+ minutes after heavy usage before sending real messages.

### Gemini bypasses AGENTS.md and answers directly (HIGH)
Gemini sometimes ignores passthrough instructions and answers via web_search or direct text. This is a fundamental LLM reliability issue — instructions are probabilistic, not guaranteed.
**Mitigation:** Instructions reinforced in 3 places (AGENTS.md, SKILL.md description, SKILL.md body). Daily route-audit flags violations.

### Background exec ("Command still running") (MEDIUM)
Gemini occasionally runs exec in background despite `yieldMs: 120000`. Returns "Command still running" before Claude finishes.
**Mitigation:** delegate script still completes in background; Claude delivers to Discord. But Gemini may do an extra turn.

### `--continue` session context growth (MEDIUM)
openclaw_claude accumulates session history across all conversations. Over weeks the context window fills up.
**Mitigation:** openclaw compaction mode set to "safeguard".

### Delegate lock drops parallel requests (LOW-MEDIUM)
If two messages arrive simultaneously, the second is dropped (returns SENT without delegating). Intentional for duplicate prevention, but legitimate parallel requests lose the second message.

### Prompt injection via message content (MEDIUM)
User message is passed verbatim into Claude's prompt. A crafted message could attempt to override instructions.

### Gateway restart kills active sessions (LOW — mitigated)
`systemctl --user restart openclaw-gateway` SIGTERMs any active delegate call.
**Mitigation:** `SKIP_GATEWAY_RESTART=1` in run-tests.

---

## Test Suites

| Suite | File | Scope |
|---|---|---|
| Unit tests | `/home/pranav/test_delegate.sh` | Delegate script: lock, logging, sanitization, config validation, timeline events, failure notification |
| Integration tests | `/home/pranav/test_integration.sh` | End-to-end: live delegation, Gemini session analysis, cron jobs, config consistency |
| Behavior tests | `/home/pranav/test_claude_behavior.sh` | Claude response quality: multi-line, special chars, watermark, format |
| Runner | `/home/pranav/.local/bin/run-tests` | Runs all 3 suites, sends Discord summary |
| Daily audit | `/home/pranav/.local/bin/route-audit` | Log analysis via Claude Opus (systemd timer, 8am PT) |

---

## Cron & Scheduled Jobs

| Job | Schedule | Mechanism | Script |
|---|---|---|---|
| route-audit | 8am PT daily | systemd timer | `/home/pranav/.local/bin/route-audit` |
| gemini-stats | daily | native crontab | `/home/pranav/.local/bin/send-gemini-stats` |
