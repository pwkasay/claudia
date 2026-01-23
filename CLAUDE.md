# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Claudia is a lightweight task coordination system for Claude Code that supports both single-session and parallel multi-session workflows. It enables atomic task assignment, session tracking, and git-native branch workflows.

## Installation

```bash
pip install git+https://github.com/pwkasay/claudia.git
```

## Commands

### Task Management

```bash
# Check status
claudia status

# List and search tasks
claudia tasks
claudia tasks --status open
claudia tasks --search "auth"          # Search by title/description

# View task details
claudia show task-001                  # Full task view with history

# Create task
claudia create "Task title" -p 1 -l backend frontend
claudia create -i                      # Interactive wizard mode
claudia create "Task" --template tpl-001  # Create from template

# Get next task (claims it)
claudia next --labels backend

# Complete task(s)
claudia complete task-001 --note "Implementation notes"
claudia complete task-001 task-002 task-003  # Bulk complete

# Reopen task(s)
claudia reopen task-001 --note "Needs revision"
claudia reopen task-001 task-002 task-003  # Bulk reopen

# Edit task
claudia edit task-001 --title "New title" --priority 1
claudia edit task-001 --labels bug urgent

# Delete task
claudia delete task-001
claudia delete task-001 --force        # Delete with subtasks
```

### Subtasks (v2.0)

```bash
# Create subtask under a parent task
claudia subtask create task-001 "Subtask title"
claudia subtask create task-001 "Subtask" -p 1 -l backend

# List subtasks
claudia subtask list task-001

# Check subtask progress
claudia subtask progress task-001
```

### Templates (v2.0)

```bash
# List templates
claudia template list

# Create template with subtasks
claudia template create "Feature Template" -p 1 -l feature \
    -s "Write tests" -s "Implement feature" -s "Update docs"

# Show template details
claudia template show tpl-001

# Delete template
claudia template delete tpl-001
```

### Time Tracking (v2.0)

```bash
# Start/stop/pause timer
claudia time start task-001
claudia time stop task-001
claudia time pause task-001

# Check timer status
claudia time status task-001

# Get time reports
claudia time report --by task
claudia time report --by label
claudia time report --by day
```

### Archiving (v1.1)

```bash
# Archive old completed tasks
claudia archive run --days 30

# List archived tasks
claudia archive list

# Restore from archive
claudia archive restore task-001
```

### Parallel Mode

```bash
# Start/stop parallel mode
claudia start-parallel --port 8765
claudia stop-parallel

# View active sessions
claudia session
claudia session session-abc123        # Session details

# Clean up stale sessions (orphaned from crashed/force-quit sessions)
claudia session cleanup               # Remove sessions inactive >3 min
claudia session cleanup --threshold 60  # Custom threshold in seconds

# Watch real-time dashboard
claudia dashboard
claudia dashboard --refresh 2
claudia dashboard --once
```

### Project Setup

```bash
# Initialize in another project
claudia init /path/to/project
claudia init --force                   # Reinitialize existing

# Remove Claudia from project
claudia uninstall
claudia uninstall --keep-history       # Backup task history

# Check for updates
claudia update --check
```

### Documentation Generation

```bash
claudia docs analyze                   # Analyze codebase structure
claudia docs generate --type architecture
claudia docs generate --type onboarding --level junior
claudia docs all                       # Generate all doc types
```

## Global CLI Flags

```bash
--json       # Output in JSON format (for scripting)
--verbose    # Show detailed error information
--dry-run    # Preview changes without executing
```

Example:
```bash
claudia --dry-run complete task-001    # Preview what would happen
claudia --json tasks                   # Machine-readable output
```

## Architecture

### Two Operating Modes

**Single Mode (default):** `Agent` reads/writes `.agent-state/tasks.json` directly with atomic file operations (tmp file + rename). File locking ensures concurrent safety.

**Parallel Mode:** `coordinator.py` runs as background HTTP server. `Agent` detects `.agent-state/.parallel-mode` file and routes all operations through HTTP to the coordinator, which handles atomic task assignment with smart load balancing.

### Package Structure

| Module | Role |
|--------|------|
| `claudia.agent` | Unified client API. Auto-detects mode via `.parallel-mode` file. Includes retry logic with exponential backoff. |
| `claudia.cli` | Command-line interface with colored output and all subcommands |
| `claudia.coordinator` | Async HTTP server (`asyncio`, raw sockets). Atomic task claiming, session heartbeats, smart assignment |
| `claudia.dashboard` | Terminal UI with stale session warnings. Reads state files directly |
| `claudia.colors` | Terminal color utilities with automatic detection |
| `claudia.docs` | Documentation generation agent |

### State Directory Structure

```
.agent-state/
├── tasks.json           # {version, next_id, tasks[]} - v2 schema
├── templates.json       # Task templates for reuse
├── archive.jsonl        # Archived completed tasks
├── history.jsonl        # Append-only event log with undo data
├── sessions/            # session-{id}.json files
├── .parallel-mode       # Flag file with {port, main_session}
└── coordinator.pid      # PID for process management
```

### Coordinator HTTP API

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/status` | GET | System status, task counts, sessions |
| `/tasks` | GET | List tasks, optional `?status=` filter |
| `/parallel-summary` | GET | Completed tasks by branch (merge phase) |
| `/session/register` | POST | Register session with role/labels |
| `/session/heartbeat` | POST | Keep session alive |
| `/session/end` | POST | End session, release tasks |
| `/task/create` | POST | Create new task |
| `/task/request` | POST | Atomically claim next task (smart assignment) |
| `/task/complete` | POST | Mark done with note/branch |
| `/task/reopen` | POST | Reopen completed task |
| `/task/edit` | POST | Edit task properties |
| `/task/delete` | POST | Delete task |
| `/task/note` | POST | Add progress note |
| `/task/bulk-complete` | POST | Complete multiple tasks |
| `/task/bulk-reopen` | POST | Reopen multiple tasks |
| `/subtask/create` | POST | Create subtask |
| `/subtask/progress` | GET | Get subtask completion progress |

### Task Schema (v2)

```json
{
  "id": "task-001",
  "title": "Task title",
  "description": "Optional description",
  "status": "open|in_progress|done|blocked",
  "priority": 0-3,
  "labels": ["backend", "bug"],
  "assignee": "session-id or null",
  "blocked_by": ["task-002"],
  "branch": "feature/task-001",
  "notes": [{"timestamp": "...", "note": "..."}],
  "created_at": "ISO timestamp",
  "updated_at": "ISO timestamp",
  "parent_id": "task-000 or null",
  "subtasks": ["task-002", "task-003"],
  "is_subtask": false,
  "time_tracking": {
    "total_seconds": 3600,
    "started_at": "ISO timestamp or null",
    "is_running": false,
    "is_paused": false
  }
}
```

### Task Priority

- 0 = critical (red)
- 1 = high (yellow)
- 2 = medium (default)
- 3 = low (dim)

## Requirements

- Python 3.10+ (dataclasses, `list[str]` type hints)
- Standard library only (certifi optional for SSL on macOS)

## Python API

```python
from claudia import Agent

agent = Agent()
agent.register(context="Working on feature X")

# Get and work on tasks
task = agent.get_next_task()
if task:
    print(f"Working on: {task['id']} - {task['title']}")
    agent.start_timer(task['id'])  # Start time tracking
    # ... do the work ...
    agent.stop_timer(task['id'])
    agent.complete_task(task['id'], "Brief completion note")

# Create new tasks
agent.create_task(
    title="Fix: edge case in validation",
    description="Discovered while implementing...",
    priority=1,
    labels=["bug", "discovered"]
)

# Subtasks
subtask = agent.create_subtask(
    parent_id="task-001",
    title="Write unit tests"
)
progress = agent.get_subtask_progress("task-001")
print(f"Progress: {progress['percentage']}%")

# Templates
agent.create_template(
    name="Bug Fix",
    default_priority=1,
    default_labels=["bug"],
    subtasks=[{"title": "Reproduce"}, {"title": "Fix"}, {"title": "Test"}]
)
task = agent.create_from_template("tpl-001", title="Fix login bug")

# Bulk operations
agent.bulk_complete(["task-001", "task-002", "task-003"], note="All done")
agent.bulk_reopen(["task-001", "task-002"], note="Need rework")

# Time reports
report = agent.get_time_report(by="label")
for item in report['items']:
    print(f"{item['label']}: {item['hours']}h")

# Undo last action
agent.undo_last_action()

# Archiving
agent.archive_tasks(days_old=30)
archived = agent.list_archived()
agent.restore_from_archive("task-001")
```

## Reference Documentation

See `AGENT_INSTRUCTIONS.md` for comprehensive usage instructions including:
- Session lifecycle workflows
- Parallel mode orchestration
- Git branch workflows
- Communication protocols between main/worker sessions

## Testing

Run the test suite:
```bash
python -m pytest tests/ -v
```

Run specific test categories:
```bash
python -m pytest tests/test_agent.py -v      # Agent tests
python -m pytest tests/test_cli.py -v        # CLI tests
python -m pytest tests/test_coordinator.py -v # Coordinator tests
```
