#!/usr/bin/env python3
"""restart-bot.py — restart the discord-bot without touching the NSSM service.

Drops a signal file that discord-bot.py watches; the bot exits cleanly and
NSSM auto-restarts it (AppExit Default Restart). The NSSM service itself never
enters STOP_PENDING, so no admin elevation is needed.

Prerequisite: manage-service.ps1 must have been run at least once as admin
to apply AppExit=Restart and the other NSSM settings.
"""
import io
import os
import sys
import time
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

LOGDIR = Path(os.getenv('LOCALAPPDATA', '')) / 'openclaw'
SIGNAL_FILE = LOGDIR / 'restart-bot.signal'
LOG_FILE = LOGDIR / 'bot.log'


def tail_log(n=3):
    """Return last n lines of the bot log."""
    try:
        lines = LOG_FILE.read_text(encoding='utf-8', errors='replace').splitlines()
        return lines[-n:]
    except Exception:
        return []


def main():
    LOGDIR.mkdir(parents=True, exist_ok=True)

    # Drop the signal file — discord-bot.py picks it up within 2s and calls client.close()
    SIGNAL_FILE.write_text('restart', encoding='utf-8')
    print("Signal sent. Waiting for bot to pick it up...")

    # Wait for signal file to be consumed (bot saw it)
    for i in range(10):
        time.sleep(1)
        if not SIGNAL_FILE.exists():
            print(f"  bot acknowledged signal after {i + 1}s")
            break
    else:
        SIGNAL_FILE.unlink(missing_ok=True)
        print("Bot did not respond to signal within 10s.")
        print("The bot may not be running or may not have loaded the signal watcher.")
        print("Check bot.log or run manage-service.ps1 restart as admin.")
        sys.exit(1)

    # Wait for NSSM to restart the app (AppRestartDelay=3000) and bot to reconnect
    print("Waiting for bot to reconnect to Discord (~5-10s)...")
    for i in range(20):
        time.sleep(1)
        recent = tail_log(5)
        if any('ready user=' in l for l in recent):
            print(f"OK discord-bot ready (after {i + 1}s)")
            sys.exit(0)

    print("Bot did not log 'ready' within 20s after restart.")
    print("Last log lines:")
    for line in tail_log(5):
        print(f"  {line}")
    sys.exit(1)


if __name__ == "__main__":
    main()
