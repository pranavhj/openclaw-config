#!/bin/bash
# Pull live configs into the repo, redacting secrets from openclaw.json.
# Safe to run any time — will never commit real credentials.
REPO="$(cd "$(dirname "$0")/.." && pwd)"

# BOOT.md deleted (OC-016) — dead code, never loaded by openclaw gateway
cp /home/pranav/.openclaw/workspace/AGENTS.md                            "$REPO/workspace/AGENTS.md"
cp /home/pranav/.openclaw/workspace/skills/delegate/SKILL.md             "$REPO/workspace/skills/delegate/SKILL.md"
cp /home/pranav/.openclaw/workspace/skills/discord-send/SKILL.md         "$REPO/workspace/skills/discord-send/SKILL.md"
cp /home/pranav/.openclaw/workspace/skills/quota/SKILL.md                "$REPO/workspace/skills/quota/SKILL.md"
cp /home/pranav/.openclaw/workspace/skills/gemini-requests/SKILL.md      "$REPO/workspace/skills/gemini-requests/SKILL.md"
cp /home/pranav/.openclaw/workspace/skills/routing-audit/SKILL.md        "$REPO/workspace/skills/routing-audit/SKILL.md"
cp /home/pranav/projects/openclaw/CLAUDE.md                              "$REPO/agents/openclaw-CLAUDE.md"
cp /home/pranav/projects/CLAUDE.md                                       "$REPO/agents/projects-CLAUDE.md"
cp /home/pranav/.local/bin/delegate                                      "$REPO/bin/delegate"
cp /home/pranav/.local/bin/route-audit                                   "$REPO/bin/route-audit"
cp /home/pranav/.local/bin/discord-bot.py                               "$REPO/bin/discord-bot.py"
cp /home/pranav/.local/bin/discord-send                                  "$REPO/bin/discord-send"
cp /home/pranav/.local/bin/agent-smart                                   "$REPO/bin/agent-smart"
cp /home/pranav/.local/bin/bot-logs                                      "$REPO/bin/bot-logs"
[ -f /home/pranav/.local/bin/run-tests ] && \
  cp /home/pranav/.local/bin/run-tests                                   "$REPO/bin/run-tests"

[ -f /home/pranav/docs/openclaw-architecture.md ] && \
  cp /home/pranav/docs/openclaw-architecture.md                          "$REPO/docs/openclaw-architecture.md"

# Redact secrets from openclaw.json
python3 - <<'EOF'
import json, re

LIVE = "/home/pranav/.openclaw/openclaw.json"
REPO_OUT = "/home/pranav/openclaw-config/config/openclaw.json"

with open(LIVE) as f:
    data = json.load(f)

# Redact env API keys
for key in list(data.get("env", {}).keys()):
    if key not in ("OLLAMA_API_KEY",):
        data["env"][key] = f"${{{key}}}"

# Redact discord bot token
if "discord" in data.get("channels", {}):
    if "token" in data["channels"]["discord"]:
        data["channels"]["discord"]["token"] = "${DISCORD_BOT_TOKEN}"
    if "allowFrom" in data["channels"]["discord"]:
        data["channels"]["discord"]["allowFrom"] = ["${DISCORD_ALLOWED_USER_ID}"]

# Redact whatsapp allowFrom
if "whatsapp" in data.get("channels", {}):
    if "allowFrom" in data["channels"]["whatsapp"]:
        data["channels"]["whatsapp"]["allowFrom"] = ["${WHATSAPP_ALLOWED_NUMBER}"]

# Redact gateway auth token
if "auth" in data.get("gateway", {}):
    if "token" in data["gateway"]["auth"]:
        data["gateway"]["auth"]["token"] = "${GATEWAY_AUTH_TOKEN}"

# Redact web search API key
try:
    data["tools"]["web"]["search"]["gemini"]["apiKey"] = "${GEMINI_SEARCH_API_KEY}"
except (KeyError, TypeError):
    pass

# Remove lastTouchedAt (changes every run, noisy diffs)
data.get("meta", {}).pop("lastTouchedAt", None)

with open(REPO_OUT, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")

print("openclaw.json synced and redacted")
EOF

echo "Synced live configs into $REPO"
echo "Review changes with: git -C $REPO diff"
