#!/usr/bin/env python3
"""restart-bot.py — restart the discord-bot service without admin elevation.

Prerequisite (one-time admin setup):
    powershell -File D:\MyData\Software\openclaw-config\bin\manage-service.ps1 grant-user

After that one-time setup this script works from any non-elevated process,
including Claude Code sessions.
"""
import io
import subprocess
import sys
import time

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

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

    # If already stuck in STOP_PENDING on entry, wait up to 10s for natural clearance
    if state == "STOP_PENDING":
        print("STOP_PENDING on entry — waiting up to 10s for it to clear...")
        for _ in range(10):
            time.sleep(1)
            state = query_state()
            if state != "STOP_PENDING":
                print(f"  cleared -> {state}")
                break
        if state == "STOP_PENDING":
            print("Still STOP_PENDING. NSSM/Python runs as SYSTEM and needs admin to force-kill.")
            print("Run as admin: manage-service.ps1 restart")
            sys.exit(1)

    if state == "RUNNING":
        print("Stopping...")
        sc_cmd("stop")
        # With AppStopMethodConsole=3000 + AppKillProcessTree, service stops within ~5s.
        # Allow up to 30s for the kill to propagate through SCM.
        for _ in range(30):
            time.sleep(1)
            state = query_state()
            if state == "STOPPED":
                print("  stopped.")
                break
        else:
            print(f"  timed out waiting for STOPPED (state: {state})")
            print("Run as admin: manage-service.ps1 restart")
            sys.exit(1)

    print("Starting...")
    r = sc_cmd("start")
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        if "already running" in err.lower():
            pass  # race: already up
        elif "access is denied" in err.lower():
            print("Access denied — run 'manage-service.ps1 grant-user' as admin first.")
            sys.exit(1)
        else:
            print(f"sc start failed (exit {r.returncode}): {err}")
            sys.exit(1)

    print("Waiting for RUNNING...")
    for i in range(20):
        time.sleep(1)
        state = query_state()
        if state == "RUNNING":
            print(f"OK discord-bot RUNNING (after {i + 1}s)")
            sys.exit(0)

    print(f"FAIL discord-bot did not reach RUNNING state (final: {query_state()})")
    sys.exit(1)


if __name__ == "__main__":
    main()
