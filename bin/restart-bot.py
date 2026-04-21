#!/usr/bin/env python3
"""restart-bot.py — restart the discord-bot service without admin elevation.

Prerequisite (one-time admin setup):
    powershell -File D:\MyData\Software\openclaw-config\bin\manage-service.ps1 grant-user

After that one-time setup this script works from any non-elevated process,
including Claude Code sessions.
"""
import subprocess
import sys
import time

SERVICE = "discord-bot"


def query_state():
    r = subprocess.run(["sc", "query", SERVICE], capture_output=True, text=True)
    for state in ("RUNNING", "STOP_PENDING", "START_PENDING", "STOPPED"):
        if state in r.stdout:
            return state
    return "UNKNOWN"


def sc_cmd(action):
    return subprocess.run(["sc", action, SERVICE], capture_output=True, text=True)


def main():
    state = query_state()
    print(f"discord-bot: {state}")

    # If stuck in STOP_PENDING wait a bit — sometimes the SCM just needs a moment
    if state == "STOP_PENDING":
        print("STOP_PENDING — waiting up to 15s for it to clear...")
        for _ in range(15):
            time.sleep(1)
            state = query_state()
            if state != "STOP_PENDING":
                print(f"  cleared → {state}")
                break
        if state == "STOP_PENDING":
            print("Still STOP_PENDING after 15s.")
            print("The underlying Python/NSSM process is running as SYSTEM and cannot be killed")
            print("without elevation. Run manage-service.ps1 restart once as admin to clear it.")
            sys.exit(1)

    if state == "RUNNING":
        print("Stopping...")
        sc_cmd("stop")
        for _ in range(15):
            time.sleep(1)
            state = query_state()
            if state == "STOPPED":
                print("  stopped.")
                break
        else:
            print(f"  timed out waiting for STOPPED (state: {state})")

    print("Starting...")
    r = sc_cmd("start")
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        if "already running" in err.lower():
            pass  # race: already up
        elif "access is denied" in err.lower():
            print(f"Access denied — run 'manage-service.ps1 grant-user' as admin first.")
            sys.exit(1)
        else:
            print(f"sc start failed (exit {r.returncode}): {err}")
            sys.exit(1)

    print("Waiting for RUNNING...")
    for i in range(20):
        time.sleep(1)
        state = query_state()
        if state == "RUNNING":
            print(f"\u2705 discord-bot RUNNING (after {i + 1}s)")
            sys.exit(0)

    print(f"\u274c discord-bot did not reach RUNNING state (final: {query_state()})")
    sys.exit(1)


if __name__ == "__main__":
    main()
