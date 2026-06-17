# OpenClaw Issue Tracker

Format: `OC-NNN | type | status | title`
Types: `bug` `feature` `config`
Statuses: `open` `fixed` `wontfix` `investigating`

| ID | Type | Status | Title | Commit |
|----|------|--------|-------|--------|
| [OC-001](issues/OC-001-retry-attempts-not-applying.md) | bug | wontfix | `retry.attempts=1` not applied to embedded agent — 4× retry hardcoded in `@google/genai` SDK, not configurable | — |
| [OC-002](issues/OC-002-rpm-exhaustion-drops-messages.md) | bug | open | RPM exhaustion: all fallbacks 429, gateway sends error but user must resend manually | — |
| [OC-003](issues/OC-003-allowbundled-empty-ineffective.md) | bug | fixed | `allowBundled: []` does not disable bundled skills (empty = allow all) | `init` |
| [OC-004](issues/OC-004-session-not-cleared-before-delegate.md) | feature | fixed | Gemini accumulates cross-turn context as router (add session clear) | `init` |
| [OC-005](issues/OC-005-bundled-skills-token-overhead.md) | feature | fixed | 55 bundled skills inflate every Gemini prompt by ~2500 tokens | `init` |
| [OC-006](issues/OC-006-agents-md-too-large.md) | feature | fixed | AGENTS.md was 9.3KB, trimmed to ~1.3KB (86% reduction) | `init` |
| [OC-007](issues/OC-007-route-audit-wrong-workdir.md) | bug | fixed | route-audit ran `agent` from wrong directory (used `~` not `projects/openclaw`) | `init` |
| [OC-008](issues/OC-008-per-project-session-isolation.md) | feature | fixed | All projects shared one Claude session — no isolation between projects | `init` |
| [OC-009](issues/OC-009-standingTable-dropped-quota.md) | bug | fixed | standingTableController message silently dropped (quota exhaustion at 17:54 PDT) | `init` |
| [OC-010](issues/OC-010-gemini-channel-misidentification.md) | bug | fixed | Gemini routed Discord message to WhatsApp (BOOT.md out of date, ambiguous channel rules) | `fix(OC-010)` |
| [OC-011](issues/OC-011-gemini-second-turn-after-delegate.md) | bug | fixed | Gemini did second model turn after delegate (quota footer) — caused gateway error on Discord | `fix(OC-011)` |
| [OC-012](issues/OC-012-gemini-second-turn-after-exec-error.md) | bug | fixed | Gemini did second model turn after exec(delegate) returned error — typing indicator after rate limit error | `fix(OC-012)` |
| [OC-013](issues/OC-013-quota-footer-typing-after-response.md) | bug | fixed | Quota footer exec kept typing indicator alive 5–10s after Claude already responded | — |
| [OC-014](issues/OC-014-gemini-delegates-own-text-not-user-message.md) | bug | fixed | Gemini composed its own text and delegated that instead of the original user message verbatim | — |
| [OC-015](issues/OC-015-delegate-exec-failed-on-apostrophes.md) | bug | fixed | Delegate exec fails when message contains apostrophe — Gemini wraps in single quotes, shell parse error | `fix(OC-015)` |
| [OC-016](issues/OC-016-newlines-break-delegate-exec.md) | bug | fixed | Newlines in user messages break delegate exec (bash exit 127) — message silently dropped | `fix(OC-016)` |
| [OC-017](issues/OC-017-gemini-overwrote-agents-md.md) | bug | fixed | Gemini used write tool to overwrite AGENTS.md with anti-delegation instructions | `fix(OC-017)` |
| [OC-018](issues/OC-018-claude-created-rogue-gemini-skill.md) | bug | fixed | Claude created rogue Alexa skill in Gemini workspace + alexa-send binary in ~/.local/bin | `fix(OC-018)` |
| [OC-019](issues/OC-019-gemini-handled-requests-directly-bypassing-delegation.md) | bug | fixed | Gemini used write tool and replied directly when exec-completed + new user message arrived in same turn | `fix(OC-019)` |
| [OC-020](issues/OC-020-repo-out-of-sync-after-gateway-migration.md) | config | fixed | Repo out of sync after Gemini→discord-bot.py migration: missing bin scripts + stale architecture doc | `docs(OC-020)` |
| [OC-021](issues/OC-021-windows-migration.md) | feature | fixed | Migrate openclaw pipeline to Windows — rewrite all bash scripts to Python, eliminate VM dependency | `feat(OC-021)` |
| [OC-022](issues/OC-022-port-tests-to-python.md) | feature | fixed | Port Linux bash test suites to Windows Python (test_delegate.py, test_integration.py, test_claude_behavior.py, run-tests.py) | `feat(OC-022)` |
| [OC-023](issues/OC-023-live-discord-progress.md) | feature | fixed | Real-time Discord progress display — status message edited every 3s with live tool calls during delegation | `feat(OC-023)` |
| [OC-024](issues/OC-024-non-elevated-service-restart.md) | feature | fixed | Non-elevated service restart — grant-user DACL action + restart-bot.py so Claude can restart bot without admin | `feat(OC-024)` |
| [OC-025](issues/OC-025-sub-agent-prompt-truncation-and-status-edit-bug.md) | bug | fixed | Sub-agent gets only `"## Reply"` (cmd.exe newline truncation) + status "Done" edit never fires (wrong discord.py API + client.close() doesn't exit) | `fix(OC-025)` |
| [OC-026](issues/OC-026-quota-optimization.md) | feature | fixed | Quota optimization: stateless Haiku routing (remove --continue + sonnet→haiku) + lower compaction threshold (400→100KB, 5→3 pairs) | `feat(OC-026)` |
| [OC-027](issues/OC-027-nssm-service-logon-failure.md) | bug | open | NSSM discord-bot service fails to start — stale `.\prana` account password, cannot fix without admin | — |
| [OC-028](issues/OC-028-ubuntu-vm-shadow-agent.md) | bug | fixed | Ubuntu_openclaw VM was silently handling Discord messages via SSH to Windows, conflicting with Windows pipeline | `docs(misc)` |
| [OC-029](issues/OC-029-flightchecker-infinite-loop.md) | bug | fixed | flightchecker invoked without --once entered infinite scheduler loop, hung delegate indefinitely | `feat(misc)` |
| [OC-030](issues/OC-030-nightly-audit.md) | feature | fixed | Nightly audit: rule-based log health checks + daily Discord report + safe auto-fix cycle (Phase 4) | `feat(OC-030)` |
| [OC-031](issues/OC-031-nightly-audit-followup.md) | bug | fixed | Nightly audit 6/16 followups: llm_gateway_down now notifies user, rate limit forwards reset time, stdout_forward severity lowered to low | `fix(OC-031)` |
