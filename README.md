# Claudia

[![PyPI version](https://img.shields.io/pypi/v/claudia.svg)](https://pypi.org/project/claudia/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-103%20passed-brightgreen.svg)](https://github.com/pwkasay/claudia)

Lightweight task coordination for Claude Code. Supports single-session and parallel multi-session workflows with zero external dependencies.

## Features

- **Task Management** — Create, track, and complete tasks with priorities and labels
- **Parallel Mode** — Coordinate multiple Claude Code sessions on the same codebase
- **Subtasks & Templates** — Hierarchical tasks and reusable templates
- **Time Tracking** — Built-in timers with reporting by task, label, or day
- **Real-time Dashboard** — Terminal UI showing task progress and active sessions
- **Documentation Generation** — Auto-generate architecture docs, onboarding guides, API references
- **Git-Native Workflows** — Branch-per-task support for parallel development

## Installation

```bash
pip install claudia
```

Optional extras:

```bash
pip install 'claudia[ssl]'   # SSL certificate support (recommended for macOS)
pip install 'claudia[dev]'   # Development dependencies (pytest)
```

From source:

```bash
git clone https://github.com/pwkasay/claudia.git
cd claudia
pip install -e .
```

## Quick Start

```bash
# Initialize in your project
claudia init

# Create a task
claudia create "Implement user authentication" -p 1 -l backend auth

# Claim and work on the next task
claudia next

# Complete it
claudia complete task-001 --note "Implemented JWT auth"
```

## Commands

### Task Management

| Command | Description |
|---------|-------------|
| `claudia create <title>` | Create a new task |
| `claudia tasks` | List all tasks |
| `claudia tasks --status open` | Filter by status |
| `claudia tasks --search "auth"` | Search tasks |
| `claudia show <id>` | View task details |
| `claudia next` | Claim the next available task |
| `claudia complete <id>` | Mark task as complete |
| `claudia reopen <id>` | Reopen a completed task |
| `claudia edit <id>` | Edit task properties |
| `claudia delete <id>` | Delete a task |

### Subtasks & Templates

| Command | Description |
|---------|-------------|
| `claudia subtask create <parent> <title>` | Create a subtask |
| `claudia subtask list <parent>` | List subtasks |
| `claudia subtask progress <parent>` | Check completion percentage |
| `claudia template list` | List templates |
| `claudia template create <name>` | Create a template |
| `claudia template show <id>` | View template details |

### Time Tracking

| Command | Description |
|---------|-------------|
| `claudia time start <id>` | Start timer |
| `claudia time stop <id>` | Stop timer |
| `claudia time pause <id>` | Pause timer |
| `claudia time status <id>` | Check timer status |
| `claudia time report` | Generate time report |

### Parallel Mode

| Command | Description |
|---------|-------------|
| `claudia start-parallel` | Start coordinator server |
| `claudia stop-parallel` | Stop coordinator server |
| `claudia session` | View active sessions |
| `claudia session cleanup` | Remove stale sessions |
| `claudia dashboard` | Real-time task dashboard |

### Documentation & Utilities

| Command | Description |
|---------|-------------|
| `claudia docs analyze` | Analyze codebase structure |
| `claudia docs generate` | Generate documentation |
| `claudia docs all` | Generate all doc types |
| `claudia status` | Show system status |
| `claudia archive run` | Archive old tasks |
| `claudia update --check` | Check for updates |

### Global Flags

```bash
--json      # Output in JSON format
--verbose   # Show detailed errors
--dry-run   # Preview without executing
```

## Python API

```python
from claudia import Agent

agent = Agent()
agent.register(context="Working on feature X")

# Create a task
task = agent.create_task(
    title="Fix validation bug",
    description="Edge case in email validation",
    priority=1,
    labels=["bug", "backend"]
)

# Get and work on tasks
task = agent.get_next_task()
if task:
    agent.start_timer(task['id'])
    # ... do the work ...
    agent.stop_timer(task['id'])
    agent.complete_task(task['id'], "Fixed edge case")

# Subtasks
agent.create_subtask(parent_id="task-001", title="Write tests")
progress = agent.get_subtask_progress("task-001")

# Templates
agent.create_template(
    name="Bug Fix",
    default_priority=1,
    default_labels=["bug"],
    subtasks=[{"title": "Reproduce"}, {"title": "Fix"}, {"title": "Test"}]
)
task = agent.create_from_template("tpl-001", title="Fix login bug")

# Bulk operations
agent.bulk_complete(["task-001", "task-002"], note="Batch complete")

# Time reports
report = agent.get_time_report(by="label")
```

## Parallel Mode

For large projects with multiple Claude Code sessions working concurrently:

```bash
# Terminal 1: Start the coordinator
claudia start-parallel

# Terminal 2, 3, etc: Sessions auto-connect
# Each session claims tasks atomically — no conflicts

# When done
claudia stop-parallel
```

### How It Works

```
Single Mode:    Agent → tasks.json (direct file access)

Parallel Mode:  Agent → HTTP → Coordinator → tasks.json
                                    ↓
                              Atomic assignment
                              Session tracking
                              Load balancing
```

Workers create feature branches. Main session merges when parallel mode ends.

## Dashboard

```bash
claudia dashboard
```

```
═══════════════════════════════════════════════════════════════
  CLAUDIA DASHBOARD │ Mode: PARALLEL
═══════════════════════════════════════════════════════════════

OVERVIEW
   Tasks: 12 total, 3 ready

SESSIONS (3 active)
   abc123 [MAIN] Orchestrating backend
   def456 [worker] Frontend work
      └─ Working: task-004

READY QUEUE
   P1 task-007: Add rate limiting [backend,security]
   P2 task-008: Write tests [testing]

IN PROGRESS
   task-004: Build login page
      → def456: "Styling the form..."
```

## Task Priorities

| Priority | Level | Use Case |
|----------|-------|----------|
| 0 | Critical | Blocking issues, security fixes |
| 1 | High | Important features, bugs |
| 2 | Medium | Normal work (default) |
| 3 | Low | Nice-to-haves, cleanup |

## Architecture

### State Directory

```
.agent-state/
├── tasks.json           # Task database (v2 schema)
├── templates.json       # Reusable templates
├── archive.jsonl        # Archived completed tasks
├── history.jsonl        # Event log with undo data
├── sessions/            # Active session files
├── .parallel-mode       # Parallel mode flag
└── coordinator.pid      # Coordinator process ID
```

### Task Schema

```json
{
  "id": "task-001",
  "title": "Task title",
  "description": "Optional description",
  "status": "open|in_progress|done|blocked",
  "priority": 2,
  "labels": ["backend", "bug"],
  "assignee": "session-id",
  "parent_id": null,
  "subtasks": [],
  "time_tracking": {
    "total_seconds": 0,
    "is_running": false
  },
  "created_at": "2026-01-20T10:00:00Z",
  "updated_at": "2026-01-20T10:00:00Z"
}
```

## Requirements

- Python 3.10+
- No external dependencies (stdlib only)

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history.

## License

[MIT](LICENSE)
