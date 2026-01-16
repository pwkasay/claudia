#!/usr/bin/env python3
"""
Claudia CLI - Task coordination for Claude Code.

Usage:
    claudia init                    # Initialize in current project
    claudia status                  # Show system status
    claudia tasks                   # List tasks
    claudia next                    # Claim next task
    claudia complete <task_id>      # Complete a task
    claudia update --check          # Check for updates
"""

import argparse
import json
import os
import shutil
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

from claudia import __version__
from claudia.agent import Agent, is_task_ready


# ============================================================================
# Formatting Helpers
# ============================================================================

def _format_priority(p: int) -> str:
    """Format priority as P0-P3 with label."""
    labels = {0: "P0 critical", 1: "P1 high", 2: "P2 medium", 3: "P3 low"}
    return labels.get(p, f"P{p}")


def _format_duration(iso_start: str) -> str:
    """Format duration from ISO timestamp to now as human-readable string."""
    try:
        # Handle various ISO formats
        if not iso_start:
            return "?"

        # Remove trailing Z and handle +00:00 suffix
        if iso_start.endswith('Z'):
            iso_start = iso_start[:-1] + '+00:00'
        elif '+00:00Z' in iso_start:
            iso_start = iso_start.replace('+00:00Z', '+00:00')

        start = datetime.fromisoformat(iso_start)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)

        delta = datetime.now(timezone.utc) - start
        total_seconds = int(delta.total_seconds())

        if total_seconds < 0:
            return "?"
        elif total_seconds < 60:
            return f"{total_seconds}s"
        elif total_seconds < 3600:
            mins = total_seconds // 60
            return f"{mins}m"
        elif total_seconds < 86400:
            hours = total_seconds // 3600
            mins = (total_seconds % 3600) // 60
            return f"{hours}h {mins}m" if mins else f"{hours}h"
        else:
            days = total_seconds // 86400
            hours = (total_seconds % 86400) // 3600
            return f"{days}d {hours}h" if hours else f"{days}d"
    except (ValueError, TypeError):
        return "?"


def _format_task_short(task: dict) -> str:
    """Format task as a short one-liner."""
    task_id = task.get('id', '?')
    title = task.get('title', 'Untitled')[:50]
    priority = task.get('priority', 2)
    labels = task.get('labels', [])

    parts = [f'{task_id}: "{title}"']
    parts.append(f"[P{priority}]")
    if labels:
        parts.append(f"[{', '.join(labels[:3])}]")

    return ' '.join(parts)


def _format_task_status_summary(status_counts: dict, ready_count: int) -> str:
    """Format task status counts as summary string."""
    parts = []
    if status_counts.get('open'):
        parts.append(f"{status_counts['open']} open")
    if ready_count:
        parts.append(f"{ready_count} ready")
    if status_counts.get('in_progress'):
        parts.append(f"{status_counts['in_progress']} in progress")
    if status_counts.get('done'):
        parts.append(f"{status_counts['done']} done")
    if status_counts.get('blocked'):
        parts.append(f"{status_counts['blocked']} blocked")
    return ', '.join(parts) if parts else "no tasks"


# ============================================================================
# Init Command
# ============================================================================

# Content to append to CLAUDE.md
CLAUDE_MD_CONTENT = '''
---

# Claudia Task Coordination

This project uses Claudia for task coordination. See [Claudia documentation](https://github.com/pwkasay/claudia) for details.

## Quick Start

```bash
claudia status              # Check system status
claudia tasks               # List all tasks
claudia next                # Claim next available task
claudia complete <task_id>  # Complete a task
```

## Task Management

```bash
claudia create "Task title" -p 1 -l backend   # Create task (P1 priority, backend label)
claudia show <task_id>                         # View task details
claudia tasks --status open                    # Filter by status
claudia tasks --search "auth"                  # Search tasks
```

## Parallel Mode

```bash
claudia start-parallel      # Start coordinator for multi-session work
claudia stop-parallel       # Stop parallel mode
claudia session             # View active sessions
```
'''


def cmd_init(args):
    """Initialize Claudia in the current directory."""
    target = Path(args.path or '.').resolve()
    state_dir = target / '.agent-state'

    if state_dir.exists() and not args.force:
        print(f"Claudia already initialized in {target}")
        print("Use --force to reinitialize")
        return 1

    print(f"Initializing Claudia in {target}")

    # Create state directory
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / 'sessions').mkdir(exist_ok=True)

    # Create tasks.json if doesn't exist
    tasks_file = state_dir / 'tasks.json'
    if not tasks_file.exists():
        tasks_file.write_text(json.dumps({
            'version': 1,
            'next_id': 1,
            'tasks': []
        }, indent=2))
        print("  ✓ Created tasks.json")
    else:
        print("  ⚠ tasks.json exists, skipping")

    # Create history.jsonl if doesn't exist
    history_file = state_dir / 'history.jsonl'
    if not history_file.exists():
        history_file.write_text('')
        print("  ✓ Created history.jsonl")
    else:
        print("  ⚠ history.jsonl exists, skipping")

    # Create .gitkeep in sessions
    gitkeep = state_dir / 'sessions' / '.gitkeep'
    if not gitkeep.exists():
        gitkeep.write_text('# Keep this directory in git\n')

    # Update .gitignore
    gitignore = target / '.gitignore'
    gitignore_entries = [
        '.agent-state/sessions/*.json',
        '.agent-state/.parallel-mode',
        '.agent-state/coordinator.pid',
    ]

    if gitignore.exists():
        content = gitignore.read_text()
        added = []
        for entry in gitignore_entries:
            if entry not in content:
                added.append(entry)
        if added:
            with open(gitignore, 'a') as f:
                f.write('\n# Claudia agent state\n')
                for entry in added:
                    f.write(entry + '\n')
            print(f"  ✓ Updated .gitignore")
    else:
        with open(gitignore, 'w') as f:
            f.write('# Claudia agent state\n')
            for entry in gitignore_entries:
                f.write(entry + '\n')
        print(f"  ✓ Created .gitignore")

    # Append to CLAUDE.md
    claude_md = target / 'CLAUDE.md'
    if claude_md.exists():
        content = claude_md.read_text()
        if 'Claudia' not in content:
            with open(claude_md, 'a') as f:
                f.write(CLAUDE_MD_CONTENT)
            print("  ✓ Appended to CLAUDE.md")
        else:
            print("  ⚠ CLAUDE.md already has Claudia section")
    else:
        claude_md.write_text(CLAUDE_MD_CONTENT.lstrip())
        print("  ✓ Created CLAUDE.md")

    # Store version
    version_file = state_dir / 'version.json'
    version_file.write_text(json.dumps({
        'version': __version__,
        'initialized_at': datetime.now(timezone.utc).isoformat(),
    }, indent=2))
    print(f"  ✓ Claudia v{__version__} initialized")

    print(f"\n✅ Claudia initialized!")
    print(f"\nNext steps:")
    print(f"  claudia create 'My first task' -p 1")
    print(f"  claudia status")

    return 0


# ============================================================================
# Uninstall Command
# ============================================================================

def cmd_uninstall(args):
    """Remove Claudia from the current directory."""
    target = Path(args.path or '.').resolve()
    state_dir = target / '.agent-state'

    if not state_dir.exists():
        print(f"Claudia not initialized in {target}")
        return 1

    if not args.force:
        print(f"This will remove Claudia from {target}")
        print(f"  - Delete .agent-state/ directory")
        if not args.keep_history:
            print(f"  - Including task history")
        print(f"  - Clean CLAUDE.md")
        response = input("\nProceed? [y/N] ")
        if response.lower() != 'y':
            print("Cancelled")
            return 0

    # Optionally preserve history
    if args.keep_history:
        history_file = state_dir / 'history.jsonl'
        tasks_file = state_dir / 'tasks.json'
        backup_dir = target / '.claudia-backup'
        backup_dir.mkdir(exist_ok=True)
        if history_file.exists():
            shutil.copy(history_file, backup_dir / 'history.jsonl')
        if tasks_file.exists():
            shutil.copy(tasks_file, backup_dir / 'tasks.json')
        print(f"  ✓ Backed up history to .claudia-backup/")

    # Remove state directory
    shutil.rmtree(state_dir)
    print(f"  ✓ Removed .agent-state/")

    # Clean CLAUDE.md
    claude_md = target / 'CLAUDE.md'
    if claude_md.exists():
        content = claude_md.read_text()
        # Remove Claudia section
        if '# Claudia Task Coordination' in content:
            # Find and remove the section
            lines = content.split('\n')
            new_lines = []
            skip = False
            for line in lines:
                if line.strip() == '# Claudia Task Coordination':
                    skip = True
                    # Also remove preceding ---
                    if new_lines and new_lines[-1].strip() == '---':
                        new_lines.pop()
                    continue
                if skip and line.startswith('# ') and 'Claudia' not in line:
                    skip = False
                if not skip:
                    new_lines.append(line)

            new_content = '\n'.join(new_lines).rstrip() + '\n'
            if new_content.strip():
                claude_md.write_text(new_content)
                print(f"  ✓ Cleaned CLAUDE.md")
            else:
                claude_md.unlink()
                print(f"  ✓ Removed empty CLAUDE.md")

    # Clean .gitignore
    gitignore = target / '.gitignore'
    if gitignore.exists():
        content = gitignore.read_text()
        lines = content.split('\n')
        new_lines = []
        skip_next = False
        for line in lines:
            if '# Claudia' in line:
                skip_next = True
                continue
            if skip_next and line.startswith('.agent-state'):
                continue
            skip_next = False
            new_lines.append(line)

        new_content = '\n'.join(new_lines)
        # Remove multiple blank lines
        while '\n\n\n' in new_content:
            new_content = new_content.replace('\n\n\n', '\n\n')
        gitignore.write_text(new_content.rstrip() + '\n')
        print(f"  ✓ Cleaned .gitignore")

    print(f"\n✅ Claudia removed from {target}")
    return 0


# ============================================================================
# Update Command
# ============================================================================

GITHUB_REPO = "pwkasay/claudia"


def _get_ssl_context():
    """Get SSL context, trying certifi first, then system certs, then unverified."""
    import ssl

    # Try certifi first (if installed)
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass

    # Try default system certificates
    try:
        ctx = ssl.create_default_context()
        # Test if it works by creating it
        return ctx
    except Exception:
        pass

    # Last resort: unverified (with warning)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def cmd_update(args):
    """Check for updates or upgrade Claudia."""
    print(f"Current version: {__version__}")

    if args.check:
        # Check GitHub for latest release
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        req = urllib.request.Request(url, headers={'User-Agent': 'Claudia'})

        # Try different SSL approaches
        ssl_context = None
        ssl_warning = False

        try:
            import ssl
            ssl_context = _get_ssl_context()
            if ssl_context.verify_mode == ssl.CERT_NONE:
                ssl_warning = True
        except Exception:
            pass

        try:
            with urllib.request.urlopen(req, timeout=10, context=ssl_context) as response:
                data = json.loads(response.read().decode())
                latest = data.get('tag_name', '').lstrip('v')

                if ssl_warning:
                    print("  (SSL verification disabled - install certifi for secure updates)")
                    print(f"  pip install certifi")
                    print()

                if latest and latest != __version__:
                    print(f"New version available: {latest}")
                    print(f"\nTo upgrade:")
                    print(f"  pip install --upgrade git+https://github.com/{GITHUB_REPO}.git")
                elif latest:
                    print(f"You're on the latest version!")
                else:
                    print(f"No releases found yet")

        except urllib.error.URLError as e:
            if 'SSL' in str(e) or 'certificate' in str(e).lower():
                print(f"SSL certificate error. To fix:")
                print(f"  pip install 'claudia[ssl]'")
                print(f"  # or: pip install certifi")
            else:
                print(f"Could not check for updates: {e}")
            return 1
        except Exception as e:
            print(f"Error checking for updates: {e}")
            return 1
    else:
        print(f"\nUsage:")
        print(f"  claudia update --check     Check for new versions")
        print(f"  pip install --upgrade git+https://github.com/{GITHUB_REPO}.git")

    return 0


# ============================================================================
# Task Commands (from original agent.py)
# ============================================================================

def cmd_status(args, agent, use_json):
    """Show system status."""
    status = agent.get_status()
    if use_json:
        print(json.dumps(status, indent=2))
    else:
        mode = status.get('mode', 'single')
        total = status.get('total_tasks', 0)
        summary = _format_task_status_summary(
            status.get('tasks_by_status', {}),
            status.get('ready_tasks', 0)
        )
        sessions = status.get('active_sessions', 0)
        print(f"Mode: {mode}")
        print(f"Tasks: {total} total ({summary})")
        print(f"Sessions: {sessions} active")


def cmd_tasks(args, agent, use_json):
    """List tasks."""
    tasks = agent.get_tasks(status=args.status)

    # Apply search filter if provided
    search_term = getattr(args, 'search', None)
    if search_term:
        search_lower = search_term.lower()
        tasks = [
            t for t in tasks
            if search_lower in t.get('title', '').lower()
            or search_lower in t.get('description', '').lower()
        ]

    if use_json:
        print(json.dumps(tasks, indent=2))
    else:
        if not tasks:
            if search_term:
                print(f"No tasks matching '{search_term}'")
            else:
                print("No tasks found")
        else:
            for task in tasks:
                status_str = task.get('status', 'open')
                print(f"  {_format_task_short(task)} [{status_str}]")
            print(f"\n{len(tasks)} task(s)")


def cmd_show(args, agent, use_json):
    """Show task details."""
    tasks = agent.get_tasks()
    task = next((t for t in tasks if t['id'] == args.task_id), None)

    if not task:
        print(f"✗ Task '{args.task_id}' not found")
        return

    if use_json:
        print(json.dumps(task, indent=2))
    else:
        print(f"\n{task['id']}: \"{task.get('title', 'Untitled')}\"")
        print("━" * 50)

        status = task.get('status', 'open')
        assignee = task.get('assignee')
        status_line = f"Status:      {status}"
        if assignee:
            status_line += f" (assigned to {assignee})"
        print(status_line)

        priority = task.get('priority', 2)
        print(f"Priority:    {_format_priority(priority)}")

        labels = task.get('labels', [])
        if labels:
            print(f"Labels:      {', '.join(labels)}")

        created = task.get('created_at', '')
        if created:
            print(f"Created:     {_format_duration(created)} ago")

        blocked_by = task.get('blocked_by', [])
        if blocked_by:
            print(f"Blocked by:  {', '.join(blocked_by)}")

        branch = task.get('branch')
        if branch:
            print(f"Branch:      {branch}")

        description = task.get('description', '')
        if description:
            print(f"\nDescription:")
            for line in description.split('\n'):
                print(f"  {line}")

        notes = task.get('notes', [])
        if notes:
            print(f"\nHistory ({len(notes)} entries):")
            for note in notes[-10:]:
                timestamp = note.get('timestamp', '')
                time_str = _format_duration(timestamp) + " ago" if timestamp else "?"
                note_text = note.get('note', '')
                print(f"  • {time_str:12} {note_text}")
            if len(notes) > 10:
                print(f"  ... and {len(notes) - 10} earlier entries")

        print()


def cmd_create(args, agent, use_json, dry_run):
    """Create a task."""
    if dry_run:
        print(f"Would create task:")
        print(f"  Title:       {args.title}")
        print(f"  Priority:    {_format_priority(args.priority)}")
        if args.labels:
            print(f"  Labels:      {', '.join(args.labels)}")
        if args.description:
            print(f"  Description: {args.description[:50]}...")
        return

    task = agent.create_task(
        title=args.title,
        description=args.description,
        priority=args.priority,
        labels=args.labels,
    )
    if use_json:
        print(json.dumps(task, indent=2))
    else:
        print(f"✓ Created {_format_task_short(task)}")


def cmd_next(args, agent, use_json, dry_run):
    """Get next task."""
    if dry_run:
        tasks = agent.get_tasks(status='open')
        task_map = {t['id']: t for t in agent.get_tasks()}
        ready = [t for t in tasks if is_task_ready(t, task_map) and t.get('assignee') is None]

        if args.labels:
            def score(t):
                label_match = -len(set(t.get('labels', [])) & set(args.labels))
                return (t.get('priority', 2), label_match, t.get('created_at', ''))
            ready.sort(key=score)
        else:
            ready.sort(key=lambda t: (t.get('priority', 2), t.get('created_at', '')))

        if ready:
            task = ready[0]
            print(f"Would claim: {_format_task_short(task)}")
            print(f"  Status would change: open → in_progress")
            if task.get('description'):
                print(f"  Description: {task['description'][:80]}...")
        else:
            status = agent.get_status()
            summary = _format_task_status_summary(
                status.get('tasks_by_status', {}),
                status.get('ready_tasks', 0)
            )
            print(f"No ready tasks. ({summary})")
        return

    task = agent.get_next_task(preferred_labels=args.labels)
    if task:
        if use_json:
            print(json.dumps(task, indent=2))
        else:
            print(f"✓ Claimed {_format_task_short(task)}")
            if task.get('description'):
                print(f"  {task['description'][:100]}")
    else:
        status = agent.get_status()
        summary = _format_task_status_summary(
            status.get('tasks_by_status', {}),
            status.get('ready_tasks', 0)
        )
        print(f"No ready tasks. ({summary})")


def cmd_complete(args, agent, use_json, dry_run):
    """Complete a task."""
    tasks = agent.get_tasks()
    task_info = next((t for t in tasks if t['id'] == args.task_id), None)

    if not task_info:
        print(f"✗ Task '{args.task_id}' not found")
        open_tasks = [t for t in tasks if t.get('status') in ('open', 'in_progress')]
        if open_tasks:
            print("\nAvailable tasks:")
            for t in open_tasks[:5]:
                print(f"  {_format_task_short(t)} [{t.get('status')}]")
            if len(open_tasks) > 5:
                print(f"  ... and {len(open_tasks) - 5} more")
        return

    if dry_run:
        current_status = task_info.get('status', 'open')
        print(f"Would complete: {_format_task_short(task_info)}")
        print(f"  Status would change: {current_status} → done")
        if args.note:
            print(f"  Note: {args.note}")
        for note in task_info.get('notes', []):
            if 'Claimed' in note.get('note', ''):
                print(f"  Duration: {_format_duration(note['timestamp'])}")
                break
        return

    success = agent.complete_task(args.task_id, note=args.note)

    if use_json:
        print(json.dumps({'success': success, 'task_id': args.task_id}, indent=2))
    elif success:
        duration = ""
        for note in task_info.get('notes', []):
            if 'Claimed' in note.get('note', ''):
                duration = f" (was in_progress for {_format_duration(note['timestamp'])})"
                break
        print(f"✓ Completed {_format_task_short(task_info)}{duration}")
    else:
        status = task_info.get('status', 'unknown')
        if status == 'done':
            print(f"✗ Task '{args.task_id}' is already completed")
        elif status == 'open':
            print(f"✗ Task '{args.task_id}' is not in progress (claim it first with 'next')")
        else:
            print(f"✗ Could not complete '{args.task_id}' (status: {status})")


def cmd_reopen(args, agent, use_json, dry_run):
    """Reopen a task."""
    tasks = agent.get_tasks()
    task_info = next((t for t in tasks if t['id'] == args.task_id), None)

    if not task_info:
        print(f"✗ Task '{args.task_id}' not found")
        return

    old_status = task_info.get('status', 'unknown')
    if old_status == 'open':
        print(f"✗ Task '{args.task_id}' is already open")
        return

    if dry_run:
        print(f"Would reopen: {_format_task_short(task_info)}")
        print(f"  Status would change: {old_status} → open")
        if args.note:
            print(f"  Note: {args.note}")
        return

    success = agent.reopen_task(args.task_id, note=args.note)

    if use_json:
        print(json.dumps({'success': success, 'task_id': args.task_id}, indent=2))
    elif success:
        print(f"✓ Reopened {_format_task_short(task_info)} (was {old_status})")
    else:
        print(f"✗ Could not reopen '{args.task_id}'")


def cmd_session(args, agent, use_json):
    """Show session info."""
    sessions_dir = agent.state_dir / 'sessions'

    if args.session_id:
        session_file = sessions_dir / f'session-{args.session_id}.json'
        if not session_file.exists():
            print(f"✗ Session '{args.session_id}' not found")
            return

        session = json.loads(session_file.read_text())
        if use_json:
            working_on_details = []
            tasks = agent.get_tasks()
            for tid in session.get('working_on', []):
                task = next((t for t in tasks if t['id'] == tid), None)
                if task:
                    working_on_details.append({
                        'id': tid,
                        'title': task.get('title'),
                        'priority': task.get('priority', 2),
                    })
            session['working_on_details'] = working_on_details
            print(json.dumps(session, indent=2))
        else:
            print(f"\nSession: {session['session_id']}")
            print("━" * 50)
            print(f"Role:        {session.get('role', 'worker')}")
            print(f"Context:     {session.get('context', 'No context')}")
            labels = session.get('labels', [])
            if labels:
                print(f"Labels:      {', '.join(labels)}")
            print(f"Started:     {_format_duration(session.get('started_at', ''))} ago")
            print(f"Heartbeat:   {_format_duration(session.get('last_heartbeat', ''))} ago")

            working_on = session.get('working_on', [])
            if working_on:
                print(f"\nWorking on ({len(working_on)} tasks):")
                tasks = agent.get_tasks()
                for tid in working_on:
                    task = next((t for t in tasks if t['id'] == tid), None)
                    if task:
                        print(f"  • {_format_task_short(task)}")
                    else:
                        print(f"  • {tid} (task not found)")
            else:
                tasks = agent.get_tasks()
                assigned = [t for t in tasks if t.get('assignee') == args.session_id]
                if assigned:
                    print(f"\nAssigned tasks ({len(assigned)}):")
                    for task in assigned:
                        print(f"  • {_format_task_short(task)}")
                else:
                    print("\nNo active tasks.")
            print()
    else:
        if not sessions_dir.exists():
            print("No sessions directory")
            return

        session_files = list(sessions_dir.glob('session-*.json'))
        if not session_files:
            print("No active sessions")
            return

        sessions = []
        for sf in session_files:
            try:
                sessions.append(json.loads(sf.read_text()))
            except:
                pass

        if use_json:
            print(json.dumps(sessions, indent=2))
        else:
            print(f"\nActive Sessions ({len(sessions)}):")
            print("━" * 50)
            for s in sessions:
                working = len(s.get('working_on', []))
                print(f"  {s['session_id']}: {s.get('context', 'No context')[:40]}")
                if s.get('labels'):
                    print(f"    Labels: {', '.join(s['labels'])}")
                print(f"    Working on: {working} task(s), heartbeat: {_format_duration(s.get('last_heartbeat', ''))} ago")
            print(f"\nTip: Use 'claudia session <id>' for details")


# ============================================================================
# Main CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Claudia - Task coordination for Claude Code',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  claudia init                    Initialize in current directory
  claudia status                  Show system status
  claudia create "Fix bug" -p 1   Create high-priority task
  claudia next                    Claim next available task
  claudia complete task-001       Complete a task
  claudia update --check          Check for updates
'''
    )
    parser.add_argument('--version', action='version', version=f'claudia {__version__}')
    parser.add_argument('--state-dir', default='.agent-state')
    parser.add_argument('--json', action='store_true', help='Output in JSON format')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes')

    subparsers = parser.add_subparsers(dest='command')

    # init
    init_p = subparsers.add_parser('init', help='Initialize Claudia in a project')
    init_p.add_argument('path', nargs='?', help='Path to initialize (default: current dir)')
    init_p.add_argument('--force', action='store_true', help='Force reinitialize')

    # uninstall
    uninstall_p = subparsers.add_parser('uninstall', help='Remove Claudia from a project')
    uninstall_p.add_argument('path', nargs='?', help='Path to uninstall from')
    uninstall_p.add_argument('--force', action='store_true', help='Skip confirmation')
    uninstall_p.add_argument('--keep-history', action='store_true', help='Backup task history')

    # update
    update_p = subparsers.add_parser('update', help='Check for updates')
    update_p.add_argument('--check', action='store_true', help='Check GitHub for new version')

    # status
    subparsers.add_parser('status', help='Show system status')

    # tasks
    tasks_p = subparsers.add_parser('tasks', help='List tasks')
    tasks_p.add_argument('--status', help='Filter by status')
    tasks_p.add_argument('--search', '-s', help='Search in title/description')

    # show
    show_p = subparsers.add_parser('show', help='Show task details')
    show_p.add_argument('task_id', help='Task ID')

    # create
    create_p = subparsers.add_parser('create', help='Create a task')
    create_p.add_argument('title')
    create_p.add_argument('--description', '-d', default='')
    create_p.add_argument('--priority', '-p', type=int, default=2)
    create_p.add_argument('--labels', '-l', nargs='*', default=[])

    # next
    next_p = subparsers.add_parser('next', help='Claim next task')
    next_p.add_argument('--labels', '-l', nargs='*', default=[])

    # complete
    complete_p = subparsers.add_parser('complete', help='Complete a task')
    complete_p.add_argument('task_id')
    complete_p.add_argument('--note', '-n', default='')

    # reopen
    reopen_p = subparsers.add_parser('reopen', help='Reopen a task')
    reopen_p.add_argument('task_id')
    reopen_p.add_argument('--note', '-n', default='')

    # start-parallel
    parallel_p = subparsers.add_parser('start-parallel', help='Start parallel mode')
    parallel_p.add_argument('--port', type=int, default=8765)

    # stop-parallel
    subparsers.add_parser('stop-parallel', help='Stop parallel mode')

    # session
    session_p = subparsers.add_parser('session', help='Show session info')
    session_p.add_argument('session_id', nargs='?')

    # dashboard
    dashboard_p = subparsers.add_parser('dashboard', help='Launch dashboard')
    dashboard_p.add_argument('--refresh', type=float, default=3.0, help='Refresh interval in seconds')
    dashboard_p.add_argument('--once', action='store_true', help='Run once and exit')
    dashboard_p.add_argument('--no-alt-screen', action='store_true', help='Disable alternate screen buffer')

    # docs - documentation generation
    docs_p = subparsers.add_parser('docs', help='Generate documentation')
    docs_sub = docs_p.add_subparsers(dest='docs_command')

    docs_analyze = docs_sub.add_parser('analyze', help='Analyze codebase structure')
    docs_analyze.add_argument('path', nargs='?', help='Project path')
    docs_analyze.add_argument('--verbose', '-v', action='store_true')

    docs_generate = docs_sub.add_parser('generate', help='Generate documentation')
    docs_generate.add_argument('--type', '-t', default='architecture',
                               choices=['architecture', 'onboarding', 'api', 'readme'],
                               help='Documentation type')
    docs_generate.add_argument('--output', '-o', help='Output file path')
    docs_generate.add_argument('path', nargs='?', help='Project path')

    docs_all = docs_sub.add_parser('all', help='Generate all documentation')
    docs_all.add_argument('path', nargs='?', help='Project path')
    docs_all.add_argument('--output', '-o', help='Output directory')

    args = parser.parse_args()

    # Handle commands that don't need Agent
    if args.command == 'init':
        sys.exit(cmd_init(args))
    elif args.command == 'uninstall':
        sys.exit(cmd_uninstall(args))
    elif args.command == 'update':
        sys.exit(cmd_update(args))
    elif args.command == 'dashboard':
        from claudia import dashboard
        dashboard.main(
            state_dir=args.state_dir,
            refresh=args.refresh,
            once=args.once,
            no_alt_screen=args.no_alt_screen,
        )
        sys.exit(0)
    elif args.command == 'docs':
        from claudia.docs import cmd_docs
        sys.exit(cmd_docs(args))
    elif args.command is None:
        parser.print_help()
        sys.exit(0)

    # Commands that need Agent
    use_json = getattr(args, 'json', False)
    verbose = getattr(args, 'verbose', False)
    dry_run = getattr(args, 'dry_run', False)

    try:
        agent = Agent(state_dir=args.state_dir)

        if args.command == 'status':
            cmd_status(args, agent, use_json)
        elif args.command == 'tasks':
            cmd_tasks(args, agent, use_json)
        elif args.command == 'show':
            cmd_show(args, agent, use_json)
        elif args.command == 'create':
            cmd_create(args, agent, use_json, dry_run)
        elif args.command == 'next':
            cmd_next(args, agent, use_json, dry_run)
        elif args.command == 'complete':
            cmd_complete(args, agent, use_json, dry_run)
        elif args.command == 'reopen':
            cmd_reopen(args, agent, use_json, dry_run)
        elif args.command == 'session':
            cmd_session(args, agent, use_json)
        elif args.command == 'start-parallel':
            success = agent.start_parallel_mode(port=args.port)
            if success:
                print(f"✓ Parallel mode started on port {args.port}")
                print("  Workers can connect by running 'claudia' in new terminals")
            else:
                print("✗ Failed to start parallel mode")
        elif args.command == 'stop-parallel':
            success = agent.stop_parallel_mode()
            if success:
                print("✓ Parallel mode stopped")
            else:
                print("✗ Could not stop parallel mode")

    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(130)
    except FileNotFoundError as e:
        print(f"✗ State directory not found: {args.state_dir}")
        print("  Run 'claudia init' to initialize")
        if verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)
    except RuntimeError as e:
        print(f"✗ {e}")
        if verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        if verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
