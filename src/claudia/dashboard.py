#!/usr/bin/env python3
"""
Agent Dashboard

Real-time terminal UI showing task and session status.
Works in both single and parallel modes.

Usage:
    python dashboard.py              # Auto-detect mode
    python dashboard.py --refresh 2  # Custom refresh rate
    python dashboard.py --once       # Single snapshot
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Try to import agent utilities
try:
    from agent import Agent, is_task_ready
except ImportError:
    Agent = None
    # Fallback implementation if agent.py not available
    def is_task_ready(task: dict, task_map: dict) -> bool:
        if task.get('status') != 'open':
            return False
        if task.get('assignee') is not None:
            return False
        for blocker_id in task.get('blocked_by', []):
            blocker = task_map.get(blocker_id)
            if blocker and blocker.get('status') != 'done':
                return False
        return True


# Import colors from shared module
try:
    from claudia.colors import Colors, priority_str
except ImportError:
    # Fallback for standalone usage
    class Colors:
        """ANSI color codes - fallback for standalone usage."""
        _enabled = True
        RESET = "\033[0m"
        BOLD = "\033[1m"
        DIM = "\033[2m"
        RED = "\033[31m"
        GREEN = "\033[32m"
        YELLOW = "\033[33m"
        BLUE = "\033[34m"
        MAGENTA = "\033[35m"
        CYAN = "\033[36m"

    def priority_str(p: int) -> str:
        colors = {0: Colors.RED, 1: Colors.YELLOW, 2: Colors.RESET, 3: Colors.DIM}
        labels = {0: "P0", 1: "P1", 2: "P2", 3: "P3"}
        return f"{colors.get(p, '')}{labels.get(p, 'P?')}{Colors.RESET}"


def clear():
    os.system('clear' if os.name == 'posix' else 'cls')


def time_ago(iso_time: str) -> str:
    """Convert ISO timestamp to human-readable relative time."""
    try:
        # Handle 'Z' suffix (UTC) by replacing with proper timezone offset
        if iso_time.endswith('Z'):
            iso_time = iso_time[:-1] + '+00:00'

        dt = datetime.fromisoformat(iso_time)

        # Ensure we compare with UTC time
        now = datetime.now(timezone.utc)

        # If dt has no timezone info, assume UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        seconds = max(0, (now - dt).total_seconds())  # Clamp to non-negative

        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            return f"{round(seconds / 60)}m"
        elif seconds < 86400:
            return f"{round(seconds / 3600)}h"
        return f"{round(seconds / 86400)}d"
    except (ValueError, TypeError, AttributeError):
        return "?"


def load_state_direct(state_dir: Path) -> dict:
    """Load state directly from files (no agent/coordinator)."""
    tasks_file = state_dir / 'tasks.json'
    if not tasks_file.exists():
        return {'tasks': [], 'sessions': {}, 'mode': 'single'}

    data = json.loads(tasks_file.read_text())
    tasks = data.get('tasks', [])

    # Load sessions
    sessions = {}
    sessions_dir = state_dir / 'sessions'
    if sessions_dir.exists():
        for f in sessions_dir.glob('session-*.json'):
            try:
                s = json.loads(f.read_text())
                sessions[s['session_id']] = s
            except (json.JSONDecodeError, OSError, KeyError):
                continue  # Skip malformed session files

    # Check mode
    mode = 'parallel' if (state_dir / '.parallel-mode').exists() else 'single'

    # Calculate stats using shared ready-task logic
    by_status = {}
    ready_count = 0
    task_map = {t['id']: t for t in tasks}

    for t in tasks:
        status = t.get('status', 'open')
        by_status[status] = by_status.get(status, 0) + 1

        # Use shared function for ready check
        if is_task_ready(t, task_map):
            ready_count += 1

    return {
        'mode': mode,
        'tasks': tasks,
        'sessions': sessions,
        'total_tasks': len(tasks),
        'tasks_by_status': by_status,
        'ready_tasks': ready_count,
    }


def render(state_dir: Path):
    """Render the dashboard."""
    state = load_state_direct(state_dir)
    
    mode = state.get('mode', 'single')
    mode_color = Colors.CYAN if mode == 'single' else Colors.MAGENTA
    
    # Header
    print(f"{Colors.BOLD}{'═' * 65}{Colors.RESET}")
    print(f"{Colors.BOLD}  AGENT DASHBOARD {Colors.DIM}│{Colors.RESET} Mode: {mode_color}{mode.upper()}{Colors.RESET}")
    print(f"{Colors.BOLD}{'═' * 65}{Colors.RESET}")
    print()
    
    # Stats
    total = state.get('total_tasks', 0)
    ready = state.get('ready_tasks', 0)
    by_status = state.get('tasks_by_status', {})
    sessions = state.get('sessions', {})
    
    print(f"{Colors.BOLD}📊 OVERVIEW{Colors.RESET}")
    print(f"   Tasks: {Colors.BOLD}{total}{Colors.RESET} total, {Colors.GREEN}{ready}{Colors.RESET} ready")
    
    status_parts = []
    if by_status.get('open'):
        status_parts.append(f"{Colors.CYAN}{by_status['open']} open{Colors.RESET}")
    if by_status.get('in_progress'):
        status_parts.append(f"{Colors.YELLOW}{by_status['in_progress']} active{Colors.RESET}")
    if by_status.get('done'):
        status_parts.append(f"{Colors.GREEN}{by_status['done']} done{Colors.RESET}")
    
    if status_parts:
        print(f"   Status: {' │ '.join(status_parts)}")
    print()
    
    # Sessions (with timeout warnings)
    # Timeout thresholds in seconds
    STALE_WARNING_THRESHOLD = 60  # Warning if no heartbeat for 60s
    STALE_DANGER_THRESHOLD = 120  # Danger if no heartbeat for 120s

    print(f"{Colors.BOLD}👥 SESSIONS{Colors.RESET} ({len(sessions)} active)")
    if not sessions:
        print(f"   {Colors.DIM}No active sessions{Colors.RESET}")
    else:
        for sid, s in sessions.items():
            role = s.get('role', 'worker')
            role_badge = f"{Colors.MAGENTA}MAIN{Colors.RESET}" if role == 'main' else f"{Colors.CYAN}worker{Colors.RESET}"
            hb_time = s.get('last_heartbeat', '')
            hb = time_ago(hb_time)
            context = s.get('context', '')[:30]
            working = s.get('working_on', [])

            # Check for stale session
            stale_badge = ""
            if hb_time:
                try:
                    if hb_time.endswith('Z'):
                        hb_time = hb_time[:-1] + '+00:00'
                    dt = datetime.fromisoformat(hb_time)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    now = datetime.now(timezone.utc)
                    seconds_since_hb = (now - dt).total_seconds()

                    if seconds_since_hb >= STALE_DANGER_THRESHOLD:
                        stale_badge = f" {Colors.RED}⚠ STALE ({hb} ago){Colors.RESET}"
                    elif seconds_since_hb >= STALE_WARNING_THRESHOLD:
                        stale_badge = f" {Colors.YELLOW}⚠ {hb} ago{Colors.RESET}"
                except (ValueError, TypeError, AttributeError):
                    pass

            print(f"   {Colors.BOLD}{sid}{Colors.RESET} [{role_badge}]{stale_badge} {Colors.DIM}{context}{Colors.RESET}")
            if working:
                print(f"      └─ Working: {', '.join(working)}")
    print()
    
    # Ready queue - use shared function
    tasks = state.get('tasks', [])
    task_map = {t['id']: t for t in tasks}

    ready_tasks = [t for t in tasks if is_task_ready(t, task_map)]
    ready_tasks.sort(key=lambda t: (t.get('priority', 2), t.get('created_at', '')))
    
    print(f"{Colors.BOLD}📋 READY QUEUE{Colors.RESET}")
    if not ready_tasks:
        print(f"   {Colors.DIM}No tasks ready{Colors.RESET}")
    else:
        for t in ready_tasks[:6]:
            p = priority_str(t.get('priority', 2))
            labels = t.get('labels', [])
            label_str = f" {Colors.DIM}[{','.join(labels[:3])}]{Colors.RESET}" if labels else ""
            print(f"   {p} {t['id']}: {t['title'][:40]}{label_str}")
        if len(ready_tasks) > 6:
            print(f"   {Colors.DIM}... +{len(ready_tasks) - 6} more{Colors.RESET}")
    print()
    
    # In progress
    in_progress = [t for t in tasks if t.get('status') == 'in_progress']
    
    print(f"{Colors.BOLD}⚡ IN PROGRESS{Colors.RESET}")
    if not in_progress:
        print(f"   {Colors.DIM}Nothing in progress{Colors.RESET}")
    else:
        for t in in_progress[:4]:
            assignee = t.get('assignee', '?')
            notes = t.get('notes', [])
            last_note = notes[-1]['note'][:35] if notes else ''
            print(f"   {Colors.YELLOW}{t['id']}{Colors.RESET}: {t['title'][:35]}")
            print(f"      {Colors.DIM}→ {assignee}: \"{last_note}\"{Colors.RESET}")
    print()
    
    # Recently done
    done = [t for t in tasks if t.get('status') == 'done']
    done.sort(key=lambda t: t.get('updated_at', ''), reverse=True)
    
    print(f"{Colors.BOLD}✅ RECENTLY COMPLETED{Colors.RESET}")
    if not done:
        print(f"   {Colors.DIM}Nothing completed yet{Colors.RESET}")
    else:
        for t in done[:3]:
            age = time_ago(t.get('updated_at', ''))
            branch = t.get('branch')
            branch_str = f" {Colors.DIM}[{branch}]{Colors.RESET}" if branch else ""
            print(f"   {Colors.GREEN}{t['id']}{Colors.RESET}: {t['title'][:35]} ({age}){branch_str}")
    print()
    
    # Footer
    now = datetime.now().strftime("%H:%M:%S")
    print(f"{Colors.DIM}{'─' * 65}{Colors.RESET}")
    print(f"{Colors.DIM}Updated: {now} │ State: {state_dir} │ Ctrl+C to exit{Colors.RESET}")


def enter_alt_screen():
    """Enter alternate screen buffer (preserves scrollback)."""
    if Colors._enabled:
        sys.stdout.write('\033[?1049h')  # Enter alternate screen
        sys.stdout.write('\033[H')        # Move cursor to top
        sys.stdout.flush()


def exit_alt_screen():
    """Exit alternate screen buffer (restores scrollback)."""
    if Colors._enabled:
        sys.stdout.write('\033[?1049l')  # Exit alternate screen
        sys.stdout.flush()


def main(state_dir=None, refresh=3.0, once=False, no_alt_screen=False):
    """
    Run the dashboard.

    Args:
        state_dir: Path to state directory (default: .agent-state)
        refresh: Refresh interval in seconds (default: 3.0)
        once: Run once and exit (default: False)
        no_alt_screen: Disable alternate screen buffer (default: False)
    """
    # Support both direct calls and CLI invocation
    if state_dir is None:
        parser = argparse.ArgumentParser(description='Agent Dashboard')
        parser.add_argument('--state-dir', default='.agent-state', help='State directory')
        parser.add_argument('--refresh', type=float, default=3.0, help='Refresh interval')
        parser.add_argument('--once', action='store_true', help='Run once and exit')
        parser.add_argument('--no-alt-screen', action='store_true',
                            help='Disable alternate screen buffer (clears scrollback)')
        args = parser.parse_args()
        state_dir = args.state_dir
        refresh = args.refresh
        once = args.once
        no_alt_screen = args.no_alt_screen

    state_dir = Path(state_dir).resolve()

    if not state_dir.exists():
        print(f"{Colors.RED}State directory not found: {state_dir}{Colors.RESET}")
        print("Initialize with: python setup.py")
        sys.exit(1)

    use_alt_screen = not once and not no_alt_screen

    try:
        if once:
            clear()
            render(state_dir)
        else:
            if use_alt_screen:
                enter_alt_screen()
            while True:
                if use_alt_screen:
                    # Just move cursor to top instead of clearing
                    sys.stdout.write('\033[H\033[J')
                    sys.stdout.flush()
                else:
                    clear()
                render(state_dir)
                time.sleep(refresh)
    except KeyboardInterrupt:
        pass
    finally:
        if use_alt_screen:
            exit_alt_screen()
        print(f"{Colors.DIM}Dashboard stopped.{Colors.RESET}")


if __name__ == '__main__':
    main()
