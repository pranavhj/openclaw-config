#!/usr/bin/env python3
"""
trace-message.py — Trace the full data flow of a Discord message through openclaw.

Shows every step from Discord receipt to final response, pulling from all log sources:
  - discord-timeline (bot-level: message receipt, slug matching, delegate spawn)
  - timeline-{slug} (delegate-level: lock, prompt, agent, reply)
  - gateway-timeline (if Q&A fast path was used)

Usage:
    python trace-message.py <search>                   # search today's logs
    python trace-message.py <search> --date 2026-06-16 # search specific date
    python trace-message.py --last [N]                 # trace last N messages (default 1)

<search> can be:
    - A message snippet (e.g. "On now", "deploy dairy")
    - A Discord message ID (e.g. 1516576144562847865)
    - A timestamp prefix (e.g. "22:48", "2026-06-16T22:48")
"""

import io
import json
import os
import sys
import glob
from datetime import date, datetime, timedelta
from pathlib import Path

# Force UTF-8 output on Windows (cp1252 can't handle some chars in log data)
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

LOG_DIR = Path(os.environ.get('LOCALAPPDATA', r'C:\Users\prana\AppData\Local')) / 'openclaw'


def load_jsonl(path):
    events = []
    if not path.exists():
        return events
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return events


def find_messages(discord_events, search=None, last_n=None):
    """Find message_received events matching the search criteria."""
    msgs = [e for e in discord_events if e.get('event') == 'message_received']

    if last_n:
        return msgs[-last_n:]

    if not search:
        return msgs

    results = []
    for m in msgs:
        # Match by message ID
        if search.isdigit() and str(m.get('message_id', '')) == search:
            results.append(m)
            continue
        # Match by timestamp prefix
        ts = m.get('ts', '')
        if search in ts:
            results.append(m)
            continue
        # Match by content
        preview = m.get('content_preview', '').lower()
        if search.lower() in preview:
            results.append(m)
            continue

    return results


def find_discord_events_for_message(all_events, msg_event):
    """Find all discord-timeline events related to this message (same sid or sequential)."""
    sid = msg_event.get('sid', '')
    ts = msg_event.get('ts', '')
    related = []

    # Get all events with same sid
    if sid:
        related = [e for e in all_events if e.get('sid') == sid]

    # Also get session_watcher events that follow the delegate_spawn
    spawn_events = [e for e in related if e.get('event') == 'delegate_spawned']
    if spawn_events:
        slug = spawn_events[0].get('slug', '')
        spawn_ts = spawn_events[0].get('ts', '')
        # Find watcher start/done for this slug after spawn
        for e in all_events:
            if e.get('event') in ('session_watcher_start', 'session_watcher_done'):
                if e.get('slug') == slug and e.get('ts', '') >= spawn_ts:
                    if e not in related:
                        related.append(e)
                    if e.get('event') == 'session_watcher_done':
                        break

    return sorted(related, key=lambda e: e.get('ts', ''))


def find_delegate_events(slug, date_str, msg_ts):
    """Find delegate timeline events for this slug that match the message timestamp."""
    tl_path = LOG_DIR / f'timeline-{slug}-{date_str}.log'
    events = load_jsonl(tl_path)
    if not events:
        return []

    # Find the delegate_recv closest to (and after) msg_ts
    best_start = None
    for i, e in enumerate(events):
        if e.get('event') == 'delegate_recv':
            recv_ts = e.get('ts', '')
            # Must be within 2 seconds of the message
            if recv_ts >= msg_ts and (not best_start or recv_ts < best_start[1]):
                best_start = (i, recv_ts)

    if best_start is None:
        return []

    # Collect all events from this delegate_recv to the next one (or end)
    start_idx = best_start[0]
    result = []
    for i in range(start_idx, len(events)):
        result.append(events[i])
        if events[i].get('event') == 'delegate_exit':
            break
        if i > start_idx and events[i].get('event') == 'delegate_recv':
            result.pop()  # Don't include the next recv
            break

    return result


def find_qa_events(discord_events, msg_event):
    """Find Q&A fast path events for this message."""
    sid = msg_event.get('sid', '')
    return [e for e in discord_events
            if e.get('sid') == sid and e.get('event', '').startswith('qa_')]


def fmt_ts(ts_str):
    """Format ISO timestamp to HH:MM:SS."""
    if not ts_str:
        return '??:??:??'
    try:
        return ts_str.split('T')[1][:8]
    except (IndexError, AttributeError):
        return ts_str[:8]


def fmt_duration(ms):
    """Format milliseconds to human readable."""
    if ms is None:
        return '?'
    if ms < 1000:
        return f'{ms}ms'
    s = ms / 1000
    if s < 60:
        return f'{s:.1f}s'
    m = int(s // 60)
    s = s % 60
    return f'{m}m{s:.0f}s'


def print_trace(msg_event, discord_events, date_str):
    """Print the full trace for a single message."""
    ts = msg_event.get('ts', '')
    preview = msg_event.get('content_preview', '')
    msg_id = msg_event.get('message_id', '?')
    msg_num = msg_event.get('num', '?')
    channel = msg_event.get('channel_id', '?')
    attach_count = msg_event.get('attachment_count', 0)

    print()
    print('=' * 80)
    print(f'  MESSAGE: "{preview}"')
    print(f'  ID: {msg_id} | #{msg_num} in conversation | {attach_count} attachments')
    print(f'  Time: {ts}')
    print('=' * 80)

    # Step 1: Discord bot receives message
    print(f'\n  [{fmt_ts(ts)}] YOU -> Discord API -> discord-bot.py')
    print(f'  |')

    # Check for Q&A fast path
    qa_events = find_qa_events(discord_events, msg_event)
    if qa_events:
        for qe in qa_events:
            evt = qe.get('event', '')
            if evt in ('qa_fast_path_attempt', 'qa_triage_attempt'):
                print(f'  +- Q&A triage attempt (asking LLM to classify)')
            elif evt in ('qa_fast_path_done', 'qa_triage_done'):
                elapsed = qe.get('elapsed_ms', '?')
                decision = qe.get('decision', 'answer')
                resp_len = qe.get('response_len', '?')
                if decision == 'answer':
                    print(f'  +- Q&A triage: ANSWER ({resp_len} chars in {fmt_duration(elapsed)})')
                else:
                    print(f'  +- Q&A triage: DELEGATE ({fmt_duration(elapsed)})')
            elif evt == 'qa_fast_path_skipped':
                print(f'  +- Q&A skipped: {qe.get("reason", "?")}')
        if any(e.get('event') in ('qa_fast_path_done', 'qa_triage_done')
               and e.get('decision', 'answer') == 'answer' for e in qa_events):
            print(f'  \- DONE (answered by Q&A triage, no delegate)')
            return
        print(f'  |')

    # Find delegate events from discord timeline
    disc_related = find_discord_events_for_message(discord_events, msg_event)
    spawn_events = [e for e in disc_related if e.get('event') == 'delegate_spawn']

    if not spawn_events:
        print(f'  \- NO DELEGATE SPAWNED (message may have been dropped)')
        return

    spawn = spawn_events[0]
    slug = spawn.get('slug', '?')
    spawned = [e for e in disc_related if e.get('event') == 'delegate_spawned']
    pid = spawned[0].get('pid', '?') if spawned else '?'
    dispatch_ms = spawned[0].get('dispatch_ms', '?') if spawned else '?'

    # Check for continuity
    continuity = [e for e in disc_related if e.get('event') == 'slug_continuity']
    if continuity:
        c = continuity[0]
        print(f'  +- _match_project() -> "router" (no keyword match)')
        print(f'  +- CONTINUITY: router -> {c.get("to", "?")} ({c.get("reason", "")})')
    else:
        print(f'  +- _match_project() -> "{slug}"')

    # Check for delegate_busy
    busy = [e for e in disc_related if e.get('event') == 'delegate_busy']
    if busy:
        print(f'  +- BUSY: slug={slug} already has running delegate (pid={busy[0].get("existing_pid","?")})')
        print(f'  \- Replied "Still working on {slug}" — message dropped')
        return

    print(f'  +- spawn: delegate.py --slug {slug} (pid={pid}, dispatch={dispatch_ms}ms)')
    print(f'  |')

    # Step 2: Delegate processing
    delegate_events = find_delegate_events(slug, date_str, ts)
    if not delegate_events:
        print(f'  \- [delegate] No timeline events found for slug={slug}')
    else:
        print(f'  |  DELEGATE (slug={slug}, pid={pid})')
        print(f'  |  |')
        for de in delegate_events:
            evt = de.get('event', '')
            de_ts = fmt_ts(de.get('ts', ''))

            if evt == 'delegate_recv':
                print(f'  |  +- [{de_ts}] recv: "{de.get("msg_preview","")[:60]}"')
            elif evt == 'sanitize':
                replaced = de.get('chars_replaced', 0)
                if replaced > 0:
                    print(f'  |  +- [{de_ts}] sanitize: {replaced} chars replaced')
            elif evt == 'lock_acquired':
                print(f'  |  +- [{de_ts}] lock: delegate-{slug}.lock acquired')
            elif evt == 'lock_blocked':
                print(f'  |  +- [{de_ts}] BLOCKED: another delegate holds the lock!')
            elif evt == 'stale_lock_broken':
                print(f'  |  +- [{de_ts}] stale lock broken (previous run crashed)')
            elif evt == 'project_match':
                cwd = de.get('work_dir', '?')
                print(f'  |  +- [{de_ts}] project: {de.get("project","?")} | cwd: {cwd}')
            elif evt == 'prompt_ready':
                print(f'  |  +- [{de_ts}] prompt built: {de.get("bytes",0)} bytes')
            elif evt == 'agent_start':
                print(f'  |  +- [{de_ts}] agent started (claude in cwd)')
            elif evt == 'slow_warning':
                print(f'  |  +- [{de_ts}] SLOW WARNING: >{de.get("elapsed_s",60)}s')
            elif evt == 'max_duration_exceeded':
                print(f'  |  +- [{de_ts}] TIMEOUT: killed after {de.get("elapsed_s","?")}s (limit {de.get("limit_s","?")}s)')
            elif evt == 'agent_done':
                dur = fmt_duration(de.get('duration_ms'))
                exit_code = de.get('exit_code', '?')
                out = de.get('output_preview', '')[:70]
                status = 'OK' if exit_code == 0 else f'FAIL exit={exit_code}'
                print(f'  |  +- [{de_ts}] agent done: {status} ({dur})')
                if out:
                    print(f'  |  |  output: "{out}"')
            elif evt == 'delegate_reply':
                reply = de.get('reply_preview', '')[:100]
                print(f'  |  +- [{de_ts}] reply: "{reply}"')
            elif evt == 'failure_detected':
                print(f'  |  +- [{de_ts}] FAILURE detected (exit={de.get("exit_code","?")})')
            elif evt == 'failure_notified':
                print(f'  |  +- [{de_ts}] failure notification sent to Discord')
            elif evt == 'timeout_detected':
                print(f'  |  +- [{de_ts}] timeout notification sent ({de.get("limit_seconds","?")}s limit)')
            elif evt == 'stop_signal_detected':
                print(f'  |  +- [{de_ts}] STOP signal received')
            elif evt == 'stdout_forward':
                print(f'  |  +- [{de_ts}] stdout forwarded (agent printed to stdout)')
            elif evt == 'delegate_exit':
                total = fmt_duration(de.get('total_ms'))
                final = de.get('final_output', '')[:60]
                has_sent = 'SENT' in final
                status = 'OK SENT' if has_sent else f'FAIL no SENT (final="{final}")'
                print(f'  |  \- [{de_ts}] exit: {status} (total: {total})')

    # Step 3: Session watcher
    watcher_start = [e for e in disc_related if e.get('event') == 'session_watcher_start']
    watcher_done = [e for e in disc_related if e.get('event') == 'session_watcher_done']
    if watcher_start:
        ws = watcher_start[0]
        print(f'  |')
        print(f'  |  WATCHER')
        print(f'  |  +- [{fmt_ts(ws.get("ts",""))}] watching active-session-{slug}.json')
        if watcher_done:
            wd = watcher_done[0]
            elapsed = wd.get('elapsed_s', '?')
            print(f'  |  \- [{fmt_ts(wd.get("ts",""))}] session done ({elapsed}s)')
        else:
            print(f'  |  \- (still running or watcher data not found)')

    print()


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Trace a Discord message through openclaw')
    parser.add_argument('search', nargs='?', help='Message snippet, ID, or timestamp to search for')
    parser.add_argument('--date', '-d', help='Date to search (YYYY-MM-DD, default: today)')
    parser.add_argument('--last', '-l', type=int, nargs='?', const=1, help='Trace last N messages (default 1)')
    parser.add_argument('--all', '-a', action='store_true', help='Trace all messages for the date')
    args = parser.parse_args()

    if not args.search and not args.last and not args.all:
        parser.print_help()
        sys.exit(1)

    if args.date:
        date_str = args.date
    else:
        date_str = date.today().strftime('%Y-%m-%d')

    # Load discord timeline
    discord_log = LOG_DIR / f'discord-timeline-{date_str}.log'
    discord_events = load_jsonl(discord_log)

    if not discord_events:
        print(f'No discord-timeline-{date_str}.log found')
        sys.exit(1)

    # Find matching messages
    if args.all:
        messages = [e for e in discord_events if e.get('event') == 'message_received']
    elif args.last:
        messages = find_messages(discord_events, last_n=args.last)
    else:
        messages = find_messages(discord_events, search=args.search)

    if not messages:
        print(f'No messages found matching "{args.search or "last"}" in {date_str}')
        sys.exit(1)

    print(f'\nTracing {len(messages)} message(s) from {date_str}')
    print(f'Log dir: {LOG_DIR}')

    for msg in messages:
        print_trace(msg, discord_events, date_str)


if __name__ == '__main__':
    main()
