---
name: discord-send
description: "Send a message to pranav on Discord. Use whenever you need to proactively notify the user, deliver results, or send any output to Discord. Pass the message text as the argument."
---

# Discord Send Skill

Sends a message directly to pranav's Discord DM channel.

## Usage

When invoked, run this exact command via exec, substituting the message text for `<message>`:

```bash
openclaw message send --channel discord --target 1482473282925101217 --message "<message>"
```

## Notes

- Target `1482473282925101217` is pranav's DM channel ID (user ID `1277144623231537274`)
- Pass the full message content as-is — do not summarize or shorten it
- If the message contains special characters or newlines, ensure they are handled properly in the shell command
