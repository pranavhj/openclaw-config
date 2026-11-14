# OC-049: answer plan-driver owner questions from Discord

Type: feature. Status: fixed (2026-11-13).

plan-driver (DESIGN §11b) asks the owner with an id and numbered options, posted in #reminders. The owner answers
`Q-7K2M 1` (or `Q-7K2M <own words>`), one per line or several on a line, as a DM to the bot or in #reminders.
`bin/driver_answers.py` parses it (the hyphen is required, so "Query: ..." stays chat; a message whose ids are all
unknown goes to the router), finds the project in plan-driver's index (`~/.claude/state/plan-driver-questions.json`)
and runs `python -m plan_driver answer --root <root> --by discord <id> <answer>` there. The first answer from any
channel (Discord, Claude, the orchestrator) wins; the driver applies it between tasks. Deterministic: no triage, no
Claude call. Hook: `bin/discord-bot.py` on_message, after the allowed-user check, before the DM-only rule.
Reviewed adversarially twice (no tests, owner's choice); findings fixed (space/semicolon-separated answers, chat
starting with Q-words, @/- argument injection, multi-line answers, timeouts).
