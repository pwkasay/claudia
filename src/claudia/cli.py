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
import shutil
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

from claudia import __version__
from claudia.agent import Agent, is_task_ready
from claudia.colors import Colors, priority_str as _color_priority, status_str as _color_status


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


def _format_task_short(task: dict, use_color: bool = True) -> str:
    """Format task as a short one-liner."""
    task_id = task.get('id', '?')
    title = task.get('title', 'Untitled')[:50]
    priority = task.get('priority', 2)
    labels = task.get('labels', [])

    parts = [f'{task_id}: "{title}"']
    if use_color and Colors.is_enabled():
        parts.append(f"[{_color_priority(priority)}]")
    else:
        parts.append(f"[P{priority}]")
    if labels:
        label_str = ', '.join(labels[:3])
        if use_color and Colors.is_enabled():
            parts.append(f"{Colors.DIM}[{label_str}]{Colors.RESET}")
        else:
            parts.append(f"[{label_str}]")

    return ' '.join(parts)


def _format_task_status_summary(status_counts: dict, ready_count: int, use_color: bool = True) -> str:
    """Format task status counts as summary string."""
    parts = []
    use_c = use_color and Colors.is_enabled()
    if status_counts.get('open'):
        count = status_counts['open']
        parts.append(f"{Colors.CYAN}{count} open{Colors.RESET}" if use_c else f"{count} open")
    if ready_count:
        parts.append(f"{Colors.GREEN}{ready_count} ready{Colors.RESET}" if use_c else f"{ready_count} ready")
    if status_counts.get('in_progress'):
        count = status_counts['in_progress']
        parts.append(f"{Colors.YELLOW}{count} in progress{Colors.RESET}" if use_c else f"{count} in progress")
    if status_counts.get('done'):
        count = status_counts['done']
        parts.append(f"{Colors.GREEN}{count} done{Colors.RESET}" if use_c else f"{count} done")
    if status_counts.get('blocked'):
        count = status_counts['blocked']
        parts.append(f"{Colors.RED}{count} blocked{Colors.RESET}" if use_c else f"{count} blocked")
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
            print("  ✓ Updated .gitignore")
    else:
        with open(gitignore, 'w') as f:
            f.write('# Claudia agent state\n')
            for entry in gitignore_entries:
                f.write(entry + '\n')
        print("  ✓ Created .gitignore")

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

    print("\n✅ Claudia initialized!")
    print("\nNext steps:")
    print("  claudia create 'My first task' -p 1")
    print("  claudia status")

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
        print("  - Delete .agent-state/ directory")
        if not args.keep_history:
            print("  - Including task history")
        print("  - Clean CLAUDE.md")
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
        print("  ✓ Backed up history to .claudia-backup/")

    # Remove state directory
    shutil.rmtree(state_dir)
    print("  ✓ Removed .agent-state/")

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
                print("  ✓ Cleaned CLAUDE.md")
            else:
                claude_md.unlink()
                print("  ✓ Removed empty CLAUDE.md")

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
        print("  ✓ Cleaned .gitignore")

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
                    print("  pip install certifi")
                    print()

                if latest and latest != __version__:
                    print(f"New version available: {latest}")
                    print("\nTo upgrade:")
                    print(f"  pip install --upgrade git+https://github.com/{GITHUB_REPO}.git")
                elif latest:
                    print("You're on the latest version!")
                else:
                    print("No releases found yet")

        except urllib.error.URLError as e:
            if 'SSL' in str(e) or 'certificate' in str(e).lower():
                print("SSL certificate error. To fix:")
                print("  pip install 'claudia[ssl]'")
                print("  # or: pip install certifi")
            else:
                print(f"Could not check for updates: {e}")
            return 1
        except Exception as e:
            print(f"Error checking for updates: {e}")
            return 1
    else:
        print("\nUsage:")
        print("  claudia update --check     Check for new versions")
        print(f"  pip install --upgrade git+https://github.com/{GITHUB_REPO}.git")

    return 0


# ============================================================================
# Interactive Mode
# ============================================================================

def _interactive_create(agent, use_json):
    """Guided task creation wizard with prompts."""
    print("\n━━━ Create New Task ━━━\n")

    # Title (required)
    while True:
        title = input("Title: ").strip()
        if title:
            break
        print("  Title is required. Please enter a title.")

    # Priority selection
    print("\nPriority:")
    print("  0) P0 - Critical (urgent, blocking)")
    print("  1) P1 - High (important)")
    print("  2) P2 - Medium (default)")
    print("  3) P3 - Low (nice to have)")
    priority_input = input("Select priority [2]: ").strip()
    if priority_input in ('0', '1', '2', '3'):
        priority = int(priority_input)
    else:
        priority = 2
    print(f"  → {_format_priority(priority)}")

    # Labels (optional)
    print("\nLabels (comma-separated, or press Enter to skip):")
    labels_input = input("Labels: ").strip()
    if labels_input:
        labels = [label.strip() for label in labels_input.split(',') if label.strip()]
    else:
        labels = []
    if labels:
        print(f"  → {', '.join(labels)}")
    else:
        print("  → No labels")

    # Description (optional, multi-line)
    print("\nDescription (optional, press Enter twice to finish):")
    desc_lines = []
    while True:
        line = input()
        if line == '' and (not desc_lines or desc_lines[-1] == ''):
            break
        desc_lines.append(line)

    # Remove trailing empty line if present
    while desc_lines and desc_lines[-1] == '':
        desc_lines.pop()
    description = '\n'.join(desc_lines)

    if description:
        print(f"  → Description added ({len(description)} chars)")
    else:
        print("  → No description")

    # Confirm
    print("\n━━━ Review ━━━")
    print(f"  Title:       {title}")
    print(f"  Priority:    {_format_priority(priority)}")
    print(f"  Labels:      {', '.join(labels) if labels else '(none)'}")
    if description:
        preview = description[:50] + '...' if len(description) > 50 else description
        print(f"  Description: {preview}")

    confirm = input("\nCreate this task? [Y/n]: ").strip().lower()
    if confirm in ('n', 'no'):
        print("Cancelled.")
        return None

    # Create the task
    task = agent.create_task(
        title=title,
        description=description,
        priority=priority,
        labels=labels,
    )

    if use_json:
        print(json.dumps(task, indent=2))
    else:
        print(f"\n✓ Created {_format_task_short(task)}")

    return task


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
                status = task.get('status', 'open')
                status_display = _color_status(status) if Colors.is_enabled() else status
                print(f"  {_format_task_short(task)} [{status_display}]")
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

        # v2: Show parent task if this is a subtask
        parent_id = task.get('parent_id')
        if parent_id:
            print(f"Parent:      {parent_id}")

        # v2: Show subtask progress if this task has subtasks
        subtasks = task.get('subtasks', [])
        if subtasks:
            progress = agent.get_subtask_progress(task['id'])
            if progress:
                pct = progress.get('percentage', 0)
                total = progress.get('total', 0)
                completed = progress.get('completed', 0)
                print(f"Subtasks:    {completed}/{total} completed ({pct}%)")

        description = task.get('description', '')
        if description:
            print("\nDescription:")
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
    # Check for interactive mode
    interactive = getattr(args, 'interactive', False)
    if interactive:
        _interactive_create(agent, use_json)
        return

    # Check if title is provided (required in non-interactive mode)
    if not args.title:
        print("✗ Title is required. Use 'claudia create \"Task title\"' or 'claudia create -i' for interactive mode.")
        return

    # Check if creating from template
    template_id = getattr(args, 'template', None)

    if template_id:
        # Create from template
        if dry_run:
            template = agent.get_template(template_id)
            if template:
                print(f"Would create task from template {template_id}:")
                print(f"  Title: {args.title}")
                print(f"  Template: {template.get('name')}")
                subtask_count = len(template.get('subtasks', []))
                if subtask_count:
                    print(f"  Would create {subtask_count} subtask(s)")
            else:
                print(f"Template '{template_id}' not found")
            return

        task = agent.create_from_template(
            template_id=template_id,
            title=args.title,
            description=args.description if args.description else None,
            priority=args.priority if args.priority != 2 else None,
            labels=args.labels if args.labels else None,
        )

        if use_json:
            print(json.dumps(task, indent=2))
        elif task:
            subtask_count = len(task.get('subtasks', []))
            print(f"✓ Created {_format_task_short(task)} from template {template_id}")
            if subtask_count:
                print(f"  With {subtask_count} subtask(s)")
        else:
            print(f"✗ Template '{template_id}' not found")
        return

    if dry_run:
        print("Would create task:")
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
            print("  Status would change: open → in_progress")
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
    """Complete one or more tasks."""
    task_ids = args.task_ids
    tasks = agent.get_tasks()
    task_map = {t['id']: t for t in tasks}
    force = getattr(args, 'force', False)

    # Single task: use original detailed behavior
    if len(task_ids) == 1:
        task_id = task_ids[0]
        task_info = task_map.get(task_id)

        if not task_info:
            print(f"✗ Task '{task_id}' not found")
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
            # Check for subtasks
            subtasks = task_info.get('subtasks', [])
            if subtasks:
                progress = agent.get_subtask_progress(task_id)
                if progress and progress.get('completed', 0) < progress.get('total', 0):
                    print(f"  Warning: {progress['total'] - progress['completed']} subtask(s) not complete")
                    if not force:
                        print("  Use --force to complete anyway")
            for note in task_info.get('notes', []):
                if 'Claimed' in note.get('note', ''):
                    print(f"  Duration: {_format_duration(note['timestamp'])}")
                    break
            return

        result = agent.complete_task(task_id, note=args.note, force=force)

        if use_json:
            print(json.dumps(result, indent=2))
        elif result.get('success'):
            duration = ""
            for note in task_info.get('notes', []):
                if 'Claimed' in note.get('note', ''):
                    duration = f" (was in_progress for {_format_duration(note['timestamp'])})"
                    break
            print(f"✓ Completed {_format_task_short(task_info)}{duration}")
        elif result.get('error') == 'incomplete_subtasks':
            incomplete = result.get('incomplete_subtasks', [])
            print(f"✗ Cannot complete '{task_id}': {len(incomplete)} subtask(s) not complete")
            for st in incomplete[:5]:
                print(f"  • {st['id']}: {st['title']} [{st['status']}]")
            if len(incomplete) > 5:
                print(f"  ... and {len(incomplete) - 5} more")
            print("\nUse --force to complete anyway")
        else:
            status = task_info.get('status', 'unknown')
            if status == 'done':
                print(f"✗ Task '{task_id}' is already completed")
            elif status == 'open':
                print(f"✗ Task '{task_id}' is not in progress (claim it first with 'next')")
            else:
                print(f"✗ Could not complete '{task_id}' (status: {status})")
        return

    # Multiple tasks: use bulk operation
    if dry_run:
        print(f"Would complete {len(task_ids)} task(s):")
        for task_id in task_ids:
            task_info = task_map.get(task_id)
            if task_info:
                print(f"  • {_format_task_short(task_info)}")
            else:
                print(f"  • {task_id} (not found)")
        if args.note:
            print(f"Note: {args.note}")
        return

    result = agent.bulk_complete(task_ids, note=args.note, force=force)

    if use_json:
        print(json.dumps(result, indent=2))
    else:
        succeeded = result.get('succeeded', [])
        failed = result.get('failed', [])

        if succeeded:
            print(f"✓ Completed {len(succeeded)} task(s):")
            for tid in succeeded:
                task_info = task_map.get(tid)
                if task_info:
                    print(f"  • {_format_task_short(task_info)}")
                else:
                    print(f"  • {tid}")

        if failed:
            print(f"\n✗ Failed to complete {len(failed)} task(s):")
            for f in failed:
                tid = f.get('id')
                error = f.get('error', 'Unknown error')
                task_info = task_map.get(tid)
                if error == 'incomplete_subtasks':
                    incomplete = f.get('incomplete_subtasks', [])
                    if task_info:
                        print(f"  • {_format_task_short(task_info)}: {len(incomplete)} subtask(s) not complete")
                    else:
                        print(f"  • {tid}: {len(incomplete)} subtask(s) not complete")
                else:
                    if task_info:
                        print(f"  • {_format_task_short(task_info)}: {error}")
                    else:
                        print(f"  • {tid}: {error}")
            if any(f.get('error') == 'incomplete_subtasks' for f in failed):
                print("\nUse --force to complete tasks with incomplete subtasks")


def cmd_edit(args, agent, use_json, dry_run):
    """Edit a task."""
    tasks = agent.get_tasks()
    task_info = next((t for t in tasks if t['id'] == args.task_id), None)

    if not task_info:
        print(f"✗ Task '{args.task_id}' not found")
        return

    # Check if any changes were specified
    if args.title is None and args.description is None and args.priority is None and args.labels is None:
        print("✗ No changes specified. Use --title, --description, --priority, or --labels")
        return

    if dry_run:
        print(f"Would edit: {_format_task_short(task_info)}")
        if args.title:
            print(f"  Title: {task_info.get('title')} → {args.title}")
        if args.description:
            print("  Description: (updated)")
        if args.priority is not None:
            print(f"  Priority: P{task_info.get('priority', 2)} → P{args.priority}")
        if args.labels is not None:
            print(f"  Labels: {task_info.get('labels', [])} → {args.labels}")
        return

    task = agent.edit_task(
        task_id=args.task_id,
        title=args.title,
        description=args.description,
        priority=args.priority,
        labels=args.labels,
    )

    if use_json:
        print(json.dumps(task or {'error': 'Task not found'}, indent=2))
    elif task:
        print(f"✓ Updated {_format_task_short(task)}")
    else:
        print(f"✗ Could not edit '{args.task_id}'")


def cmd_delete(args, agent, use_json, dry_run):
    """Delete a task."""
    tasks = agent.get_tasks()
    task_info = next((t for t in tasks if t['id'] == args.task_id), None)

    if not task_info:
        print(f"✗ Task '{args.task_id}' not found")
        return

    subtasks = task_info.get('subtasks', [])

    if dry_run:
        print(f"Would delete: {_format_task_short(task_info)}")
        if subtasks:
            print(f"  Warning: Has {len(subtasks)} subtask(s)")
            if not args.force:
                print("  Use --force to delete with subtasks")
        return

    result = agent.delete_task(args.task_id, force=args.force)

    if use_json:
        print(json.dumps(result, indent=2))
    elif result.get('success'):
        deleted_subtasks = result.get('deleted_subtasks', [])
        if deleted_subtasks:
            print(f"✓ Deleted {_format_task_short(task_info)} and {len(deleted_subtasks)} subtask(s)")
        else:
            print(f"✓ Deleted {_format_task_short(task_info)}")
    elif result.get('error') == 'has_subtasks':
        subtasks = result.get('subtasks', [])
        print(f"✗ Cannot delete '{args.task_id}': has {len(subtasks)} subtask(s)")
        print(f"  Subtasks: {', '.join(subtasks[:5])}")
        if len(subtasks) > 5:
            print(f"  ... and {len(subtasks) - 5} more")
        print("\nUse --force to delete anyway")
    else:
        print(f"✗ Could not delete '{args.task_id}'")


def cmd_reopen(args, agent, use_json, dry_run):
    """Reopen one or more tasks."""
    task_ids = args.task_ids
    tasks = agent.get_tasks()
    task_map = {t['id']: t for t in tasks}

    # Single task: use original detailed behavior
    if len(task_ids) == 1:
        task_id = task_ids[0]
        task_info = task_map.get(task_id)

        if not task_info:
            print(f"✗ Task '{task_id}' not found")
            return

        old_status = task_info.get('status', 'unknown')
        if old_status == 'open':
            print(f"✗ Task '{task_id}' is already open")
            return

        if dry_run:
            print(f"Would reopen: {_format_task_short(task_info)}")
            print(f"  Status would change: {old_status} → open")
            if args.note:
                print(f"  Note: {args.note}")
            return

        success = agent.reopen_task(task_id, note=args.note)

        if use_json:
            print(json.dumps({'success': success, 'task_id': task_id}, indent=2))
        elif success:
            print(f"✓ Reopened {_format_task_short(task_info)} (was {old_status})")
        else:
            print(f"✗ Could not reopen '{task_id}'")
        return

    # Multiple tasks: use bulk operation
    if dry_run:
        print(f"Would reopen {len(task_ids)} task(s):")
        for task_id in task_ids:
            task_info = task_map.get(task_id)
            if task_info:
                old_status = task_info.get('status', 'unknown')
                print(f"  • {_format_task_short(task_info)} (currently {old_status})")
            else:
                print(f"  • {task_id} (not found)")
        if args.note:
            print(f"Note: {args.note}")
        return

    result = agent.bulk_reopen(task_ids, note=args.note)

    if use_json:
        print(json.dumps(result, indent=2))
    else:
        succeeded = result.get('succeeded', [])
        failed = result.get('failed', [])

        if succeeded:
            print(f"✓ Reopened {len(succeeded)} task(s):")
            for tid in succeeded:
                task_info = task_map.get(tid)
                if task_info:
                    print(f"  • {_format_task_short(task_info)}")
                else:
                    print(f"  • {tid}")

        if failed:
            print(f"\n✗ Failed to reopen {len(failed)} task(s):")
            for f in failed:
                tid = f.get('id')
                error = f.get('error', 'Unknown error')
                task_info = task_map.get(tid)
                if task_info:
                    print(f"  • {_format_task_short(task_info)}: {error}")
                else:
                    print(f"  • {tid}: {error}")


def cmd_archive(args, agent, use_json, dry_run):
    """Archive commands."""
    if args.archive_command == 'run':
        result = agent.archive_tasks(days_old=args.days, dry_run=dry_run)

        if use_json:
            print(json.dumps(result, indent=2))
        elif result.get('error'):
            print(f"✗ {result['error']}")
        elif dry_run:
            count = result.get('archived', 0)
            if count == 0:
                print(f"No tasks older than {args.days} days to archive")
            else:
                print(f"Would archive {count} task(s) older than {args.days} days:")
                for task in result.get('tasks', [])[:5]:
                    print(f"  {task['id']}: {task['title']}")
                if count > 5:
                    print(f"  ... and {count - 5} more")
        else:
            count = result.get('archived', 0)
            if count == 0:
                print(f"No tasks older than {args.days} days to archive")
            else:
                print(f"✓ Archived {count} task(s)")

    elif args.archive_command == 'list':
        tasks = agent.list_archived(limit=args.limit)

        if use_json:
            print(json.dumps(tasks, indent=2))
        elif not tasks:
            print("No archived tasks")
        else:
            print(f"Archived tasks ({len(tasks)}):")
            for task in tasks:
                archived_at = task.get('archived_at', '')[:10]
                print(f"  {task['id']}: {task['title'][:40]} (archived {archived_at})")

    elif args.archive_command == 'restore':
        if dry_run:
            print(f"Would restore {args.task_id} from archive")
            return

        task = agent.restore_from_archive(args.task_id)

        if use_json:
            print(json.dumps(task, indent=2))
        elif task:
            print(f"✓ Restored {_format_task_short(task)}")
        else:
            print(f"✗ Task '{args.task_id}' not found in archive")

    else:
        print("Usage: claudia archive <run|list|restore> ...")


def _format_time(seconds: float) -> str:
    """Format seconds as human-readable time."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def cmd_time(args, agent, use_json, dry_run):
    """Time tracking commands."""
    if args.time_command == 'start':
        if dry_run:
            print(f"Would start timer for {args.task_id}")
            return

        task = agent.start_timer(args.task_id)
        if use_json:
            print(json.dumps(task, indent=2))
        elif task:
            print(f"✓ Timer started for {_format_task_short(task)}")
        else:
            print(f"✗ Task '{args.task_id}' not found")

    elif args.time_command == 'stop':
        if dry_run:
            print(f"Would stop timer for {args.task_id}")
            return

        task = agent.stop_timer(args.task_id)
        if use_json:
            print(json.dumps(task, indent=2))
        elif task:
            tt = task.get('time_tracking', {})
            total = tt.get('total_seconds', 0)
            print(f"✓ Timer stopped for {_format_task_short(task)}")
            print(f"  Total time: {_format_time(total)}")
        else:
            print(f"✗ Task '{args.task_id}' not found")

    elif args.time_command == 'pause':
        if dry_run:
            print(f"Would pause timer for {args.task_id}")
            return

        task = agent.pause_timer(args.task_id)
        if use_json:
            print(json.dumps(task, indent=2))
        elif task:
            tt = task.get('time_tracking', {})
            total = tt.get('total_seconds', 0)
            print(f"✓ Timer paused for {_format_task_short(task)}")
            print(f"  Accumulated time: {_format_time(total)}")
        else:
            print(f"✗ Task '{args.task_id}' not found")

    elif args.time_command == 'status':
        info = agent.get_task_time(args.task_id)

        if use_json:
            print(json.dumps(info, indent=2))
        elif info:
            total = info.get('total_seconds', 0)
            current = info.get('current_elapsed', 0)
            is_running = info.get('is_running', False)
            is_paused = info.get('is_paused', False)

            if is_running:
                print(f"Timer for {args.task_id}: RUNNING")
                print(f"  Current session: {_format_time(current)}")
                print(f"  Total (saved): {_format_time(total)}")
            elif is_paused:
                print(f"Timer for {args.task_id}: PAUSED")
                print(f"  Total time: {_format_time(total)}")
            elif total > 0:
                print(f"Timer for {args.task_id}: STOPPED")
                print(f"  Total time: {_format_time(total)}")
            else:
                print(f"Timer for {args.task_id}: Not started")
        else:
            print(f"✗ Task '{args.task_id}' not found")

    elif args.time_command == 'report':
        report = agent.get_time_report(
            by=args.by,
            labels=args.labels,
        )

        if use_json:
            print(json.dumps(report, indent=2))
        else:
            print(f"Time Report (by {args.by})")
            print("=" * 50)

            if not report.get('items'):
                print("No time tracked yet.")
            else:
                for item in report['items']:
                    if args.by == 'task':
                        print(f"  {item['id']}: {item['title'][:30]}")
                        print(f"    {_format_time(item['seconds'])} ({item['hours']}h)")
                    elif args.by == 'label':
                        print(f"  [{item['label']}] {_format_time(item['seconds'])} ({item['hours']}h)")
                    elif args.by == 'day':
                        print(f"  {item['day']}: {_format_time(item['seconds'])} ({item['hours']}h)")

            print("-" * 50)
            print(f"Total: {_format_time(report['total_seconds'])} ({report['total_hours']}h)")

    else:
        print("Usage: claudia time <start|stop|pause|status|report> ...")


def cmd_template(args, agent, use_json, dry_run):
    """Manage task templates."""
    if args.template_command == 'list':
        templates = agent.list_templates()

        if use_json:
            print(json.dumps(templates, indent=2))
        else:
            if not templates:
                print("No templates found. Create one with 'claudia template create <name>'")
            else:
                print(f"Templates ({len(templates)}):")
                for t in templates:
                    subtask_count = len(t.get('subtasks', []))
                    subtask_str = f" ({subtask_count} subtasks)" if subtask_count else ""
                    labels = t.get('default_labels', [])
                    label_str = f" [{', '.join(labels)}]" if labels else ""
                    print(f"  {t['id']}: {t['name']}{subtask_str}{label_str}")

    elif args.template_command == 'create':
        if dry_run:
            print("Would create template:")
            print(f"  Name: {args.name}")
            print(f"  Priority: P{args.priority}")
            if args.labels:
                print(f"  Labels: {', '.join(args.labels)}")
            if args.subtasks:
                print(f"  Subtasks: {len(args.subtasks)}")
                for st in args.subtasks:
                    print(f"    - {st}")
            return

        # Convert subtask strings to dicts
        subtask_dicts = [{'title': st} for st in (args.subtasks or [])]

        template = agent.create_template(
            name=args.name,
            description=args.description,
            default_priority=args.priority,
            default_labels=args.labels,
            subtasks=subtask_dicts,
        )

        if use_json:
            print(json.dumps(template, indent=2))
        else:
            subtask_count = len(template.get('subtasks', []))
            print(f"✓ Created template {template['id']}: {template['name']}")
            if subtask_count:
                print(f"  With {subtask_count} subtask(s)")

    elif args.template_command == 'delete':
        if dry_run:
            template = agent.get_template(args.template_id)
            if template:
                print(f"Would delete template: {template['id']}: {template['name']}")
            else:
                print(f"Template '{args.template_id}' not found")
            return

        success = agent.delete_template(args.template_id)

        if use_json:
            print(json.dumps({'success': success}, indent=2))
        elif success:
            print(f"✓ Deleted template {args.template_id}")
        else:
            print(f"✗ Template '{args.template_id}' not found")

    elif args.template_command == 'show':
        template = agent.get_template(args.template_id)

        if use_json:
            print(json.dumps(template, indent=2))
        elif template:
            print(f"Template: {template['id']}")
            print(f"Name:     {template['name']}")
            print(f"Priority: P{template.get('default_priority', 2)}")
            labels = template.get('default_labels', [])
            if labels:
                print(f"Labels:   {', '.join(labels)}")
            if template.get('description'):
                print("\nDescription:")
                print(f"  {template['description']}")
            subtasks = template.get('subtasks', [])
            if subtasks:
                print(f"\nSubtasks ({len(subtasks)}):")
                for st in subtasks:
                    print(f"  • {st.get('title')}")
        else:
            print(f"✗ Template '{args.template_id}' not found")

    else:
        print("Usage: claudia template <list|create|delete|show> ...")


def cmd_subtask(args, agent, use_json, dry_run):
    """Manage subtasks."""
    if args.subtask_command == 'create':
        if dry_run:
            print(f"Would create subtask under {args.parent_id}:")
            print(f"  Title: {args.title}")
            if args.description:
                print(f"  Description: {args.description[:50]}...")
            if args.priority is not None:
                print(f"  Priority: P{args.priority}")
            if args.labels:
                print(f"  Labels: {', '.join(args.labels)}")
            return

        subtask = agent.create_subtask(
            parent_id=args.parent_id,
            title=args.title,
            description=args.description,
            priority=args.priority,
            labels=args.labels,
        )

        if subtask:
            if use_json:
                print(json.dumps(subtask, indent=2))
            else:
                print(f"✓ Created subtask {_format_task_short(subtask)}")
                print(f"  Parent: {args.parent_id}")
        else:
            print(f"✗ Parent task '{args.parent_id}' not found")

    elif args.subtask_command == 'list':
        subtasks = agent.get_subtasks(args.task_id)

        if use_json:
            print(json.dumps(subtasks, indent=2))
        else:
            if not subtasks:
                print(f"No subtasks for {args.task_id}")
            else:
                print(f"Subtasks of {args.task_id}:")
                for st in subtasks:
                    status = st.get('status', 'open')
                    status_display = _color_status(status) if Colors.is_enabled() else status
                    print(f"  {_format_task_short(st)} [{status_display}]")
                print(f"\n{len(subtasks)} subtask(s)")

    elif args.subtask_command == 'progress':
        progress = agent.get_subtask_progress(args.task_id)

        if progress is None:
            print(f"✗ Task '{args.task_id}' not found")
            return

        if use_json:
            print(json.dumps(progress, indent=2))
        else:
            total = progress.get('total', 0)
            if total == 0:
                print(f"Task {args.task_id} has no subtasks")
            else:
                pct = progress.get('percentage', 0)
                completed = progress.get('completed', 0)
                in_progress = progress.get('in_progress', 0)
                open_count = progress.get('open', 0)
                blocked = progress.get('blocked', 0)

                print(f"Subtask progress for {args.task_id}: {pct}%")
                print(f"  {completed}/{total} completed")
                if in_progress:
                    print(f"  {in_progress} in progress")
                if open_count:
                    print(f"  {open_count} open")
                if blocked:
                    print(f"  {blocked} blocked")

    else:
        print("Usage: claudia subtask <create|list|progress> ...")


def _get_session_age_seconds(session: dict) -> float:
    """Get seconds since last heartbeat for a session."""
    hb_time = session.get('last_heartbeat', '')
    if not hb_time:
        return float('inf')
    try:
        if hb_time.endswith('Z'):
            hb_time = hb_time[:-1] + '+00:00'
        dt = datetime.fromisoformat(hb_time)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds()
    except (ValueError, TypeError):
        return float('inf')


def cmd_session(args, agent, use_json, dry_run=False):
    """Show session info or manage sessions."""
    sessions_dir = agent.state_dir / 'sessions'

    # Handle cleanup subcommand (can be triggered by subparser or session_id='cleanup')
    session_command = getattr(args, 'session_command', None)
    session_id_arg = getattr(args, 'session_id', None)

    # Support both 'claudia session cleanup' via subparser and positional arg
    if session_command == 'cleanup' or session_id_arg == 'cleanup':
        threshold = getattr(args, 'threshold', 180)  # 3 minutes default

        if not sessions_dir.exists():
            print("No sessions directory")
            return

        session_files = list(sessions_dir.glob('session-*.json'))
        if not session_files:
            print("No sessions to clean up")
            return

        stale_sessions = []
        for sf in session_files:
            try:
                session = json.loads(sf.read_text())
                age = _get_session_age_seconds(session)
                if age > threshold:
                    stale_sessions.append((sf, session, age))
            except (json.JSONDecodeError, OSError):
                # Corrupt file, mark for cleanup
                stale_sessions.append((sf, {'session_id': sf.stem.replace('session-', '')}, float('inf')))

        if not stale_sessions:
            print(f"No stale sessions (threshold: {threshold}s)")
            return

        if dry_run:
            print(f"Would remove {len(stale_sessions)} stale session(s):")
            for sf, session, age in stale_sessions:
                sid = session.get('session_id', 'unknown')
                age_str = f"{int(age)}s" if age != float('inf') else "corrupt"
                print(f"  • {sid} (last heartbeat: {age_str} ago)")
            return

        if use_json:
            removed = []
            for sf, session, age in stale_sessions:
                sf.unlink()
                removed.append(session.get('session_id', sf.stem))
            print(json.dumps({'removed': removed, 'count': len(removed)}, indent=2))
        else:
            print(f"Removing {len(stale_sessions)} stale session(s):")
            for sf, session, age in stale_sessions:
                sid = session.get('session_id', 'unknown')
                sf.unlink()
                print(f"  ✓ {sid}")
            print(f"\n✓ Cleaned up {len(stale_sessions)} session(s)")
        return

    # Handle show subcommand or direct session_id argument
    if session_id_arg and session_id_arg != 'cleanup':
        session_file = sessions_dir / f'session-{session_id_arg}.json'
        if not session_file.exists():
            print(f"✗ Session '{session_id_arg}' not found")
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
                assigned = [t for t in tasks if t.get('assignee') == session_id_arg]
                if assigned:
                    print(f"\nAssigned tasks ({len(assigned)}):")
                    for task in assigned:
                        print(f"  • {_format_task_short(task)}")
                else:
                    print("\nNo active tasks.")
            print()
    else:
        # List all sessions
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
            except (json.JSONDecodeError, OSError):
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
            print("\nTip: Use 'claudia session <id>' for details")
            print("     Use 'claudia session cleanup' to remove stale sessions")


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
    create_p.add_argument('title', nargs='?', default=None, help='Task title (optional with -i)')
    create_p.add_argument('--description', '-d', default='')
    create_p.add_argument('--priority', '-p', type=int, default=2)
    create_p.add_argument('--labels', '-l', nargs='*', default=[])
    create_p.add_argument('--template', '-T', help='Create from template ID')
    create_p.add_argument('--interactive', '-i', action='store_true', help='Interactive wizard mode')

    # next
    next_p = subparsers.add_parser('next', help='Claim next task')
    next_p.add_argument('--labels', '-l', nargs='*', default=[])

    # complete
    complete_p = subparsers.add_parser('complete', help='Complete one or more tasks')
    complete_p.add_argument('task_ids', nargs='+', metavar='task_id', help='Task ID(s) to complete')
    complete_p.add_argument('--note', '-n', default='')
    complete_p.add_argument('--force', '-f', action='store_true', help='Complete even if subtasks are incomplete')

    # edit
    edit_p = subparsers.add_parser('edit', help='Edit a task')
    edit_p.add_argument('task_id')
    edit_p.add_argument('--title', '-t', help='New title')
    edit_p.add_argument('--description', '-d', help='New description')
    edit_p.add_argument('--priority', '-p', type=int, choices=[0, 1, 2, 3], help='New priority')
    edit_p.add_argument('--labels', '-l', nargs='*', help='New labels (replaces existing)')

    # delete
    delete_p = subparsers.add_parser('delete', help='Delete a task')
    delete_p.add_argument('task_id')
    delete_p.add_argument('--force', '-f', action='store_true', help='Delete even if task has subtasks')

    # reopen
    reopen_p = subparsers.add_parser('reopen', help='Reopen one or more tasks')
    reopen_p.add_argument('task_ids', nargs='+', metavar='task_id', help='Task ID(s) to reopen')
    reopen_p.add_argument('--note', '-n', default='')

    # archive
    archive_p = subparsers.add_parser('archive', help='Archive old completed tasks')
    archive_sub = archive_p.add_subparsers(dest='archive_command')

    archive_run = archive_sub.add_parser('run', help='Archive tasks older than N days')
    archive_run.add_argument('--days', '-d', type=int, default=30, help='Days old threshold')

    archive_list = archive_sub.add_parser('list', help='List archived tasks')
    archive_list.add_argument('--limit', '-n', type=int, default=20)

    archive_restore = archive_sub.add_parser('restore', help='Restore a task from archive')
    archive_restore.add_argument('task_id')

    # time
    time_p = subparsers.add_parser('time', help='Time tracking')
    time_sub = time_p.add_subparsers(dest='time_command')

    time_start = time_sub.add_parser('start', help='Start timer for a task')
    time_start.add_argument('task_id')

    time_stop = time_sub.add_parser('stop', help='Stop timer for a task')
    time_stop.add_argument('task_id')

    time_pause = time_sub.add_parser('pause', help='Pause timer for a task')
    time_pause.add_argument('task_id')

    time_status = time_sub.add_parser('status', help='Show timer status for a task')
    time_status.add_argument('task_id')

    time_report = time_sub.add_parser('report', help='Show time report')
    time_report.add_argument('--by', choices=['task', 'label', 'day'], default='task')
    time_report.add_argument('--labels', '-l', nargs='*', help='Filter by labels')

    # template
    template_p = subparsers.add_parser('template', help='Manage task templates')
    template_sub = template_p.add_subparsers(dest='template_command')

    template_sub.add_parser('list', help='List templates')

    template_create = template_sub.add_parser('create', help='Create a template')
    template_create.add_argument('name', help='Template name')
    template_create.add_argument('--description', '-d', default='')
    template_create.add_argument('--priority', '-p', type=int, default=2)
    template_create.add_argument('--labels', '-l', nargs='*', default=[])
    template_create.add_argument('--subtask', '-s', action='append', dest='subtasks',
                                  help='Add subtask (can be repeated)')

    template_delete = template_sub.add_parser('delete', help='Delete a template')
    template_delete.add_argument('template_id')

    template_show = template_sub.add_parser('show', help='Show template details')
    template_show.add_argument('template_id')

    # subtask
    subtask_p = subparsers.add_parser('subtask', help='Manage subtasks')
    subtask_sub = subtask_p.add_subparsers(dest='subtask_command')

    subtask_create = subtask_sub.add_parser('create', help='Create a subtask')
    subtask_create.add_argument('parent_id', help='Parent task ID')
    subtask_create.add_argument('title', help='Subtask title')
    subtask_create.add_argument('--description', '-d', default='')
    subtask_create.add_argument('--priority', '-p', type=int, help='Override parent priority')
    subtask_create.add_argument('--labels', '-l', nargs='*', help='Override parent labels')

    subtask_list = subtask_sub.add_parser('list', help='List subtasks of a task')
    subtask_list.add_argument('task_id', help='Parent task ID')

    subtask_progress = subtask_sub.add_parser('progress', help='Show subtask progress')
    subtask_progress.add_argument('task_id', help='Parent task ID')

    # start-parallel
    parallel_p = subparsers.add_parser('start-parallel', help='Start parallel mode')
    parallel_p.add_argument('--port', type=int, default=8765)

    # stop-parallel
    subparsers.add_parser('stop-parallel', help='Stop parallel mode')

    # session
    session_p = subparsers.add_parser('session', help='Manage sessions')
    session_sub = session_p.add_subparsers(dest='session_command')

    # session (no subcommand) - list sessions
    session_p.add_argument('session_id', nargs='?', help='Session ID to show details')

    # session cleanup
    session_cleanup = session_sub.add_parser('cleanup', help='Remove stale sessions')
    session_cleanup.add_argument('--threshold', '-t', type=int, default=180,
                                  help='Stale threshold in seconds (default: 180 = 3 minutes)')

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
    docs_analyze.add_argument('--force', '-f', action='store_true', help='Force full re-analysis (ignore cache)')

    docs_generate = docs_sub.add_parser('generate', help='Generate documentation')
    docs_generate.add_argument('--type', '-t', default='architecture',
                               choices=['architecture', 'onboarding', 'api', 'readme', 'insights'],
                               help='Documentation type (insights=AI-assisted analysis)')
    docs_generate.add_argument('--level', '-L', default='mid',
                               choices=['junior', 'mid', 'senior'],
                               help='Detail level (junior=verbose, mid=balanced, senior=minimal)')
    docs_generate.add_argument('--output', '-o', help='Output file path')
    docs_generate.add_argument('path', nargs='?', help='Project path')

    docs_context = docs_sub.add_parser('context', help='Output structured context for Claude Code')
    docs_context.add_argument('path', nargs='?', help='Project path')

    docs_all = docs_sub.add_parser('all', help='Generate all documentation')
    docs_all.add_argument('--level', '-L', default='mid',
                          choices=['junior', 'mid', 'senior'],
                          help='Detail level (junior=verbose, mid=balanced, senior=minimal)')
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
        elif args.command == 'edit':
            cmd_edit(args, agent, use_json, dry_run)
        elif args.command == 'delete':
            cmd_delete(args, agent, use_json, dry_run)
        elif args.command == 'reopen':
            cmd_reopen(args, agent, use_json, dry_run)
        elif args.command == 'archive':
            cmd_archive(args, agent, use_json, dry_run)
        elif args.command == 'time':
            cmd_time(args, agent, use_json, dry_run)
        elif args.command == 'template':
            cmd_template(args, agent, use_json, dry_run)
        elif args.command == 'subtask':
            cmd_subtask(args, agent, use_json, dry_run)
        elif args.command == 'session':
            cmd_session(args, agent, use_json, dry_run)
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
    except FileNotFoundError:
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
