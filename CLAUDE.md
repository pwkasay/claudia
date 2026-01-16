# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Claudia is a lightweight task coordination system for Claude Code that supports both single-session and parallel multi-session workflows. It enables atomic task assignment, session tracking, and git-native branch workflows.

## Installation

```bash
pip install git+https://github.com/pwkasay/claudia.git
```

## Commands

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

# Get next task (claims it)
claudia next --labels backend

# Complete task
claudia complete task-001 --note "Implementation notes"

# Reopen a completed task
claudia reopen task-001 --note "Needs revision"

# Start/stop parallel mode
claudia start-parallel --port 8765
claudia stop-parallel

# Watch real-time dashboard
claudia dashboard
claudia dashboard --refresh 2
claudia dashboard --once

# Initialize in another project
claudia init /path/to/project
claudia init --force                   # Reinitialize existing

# Documentation generation
claudia docs analyze                   # Analyze codebase structure
claudia docs generate --type architecture
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

**Single Mode (default):** `Agent` reads/writes `.agent-state/tasks.json` directly with atomic file operations (tmp file rename).

**Parallel Mode:** `coordinator.py` runs as background HTTP server. `Agent` detects `.agent-state/.parallel-mode` file and routes all operations through HTTP to the coordinator, which handles atomic task assignment.

### Package Structure

| Module | Role |
|--------|------|
| `claudia.agent` | Unified client API. Auto-detects mode via `.parallel-mode` file |
| `claudia.cli` | Command-line interface with all subcommands |
| `claudia.coordinator` | Async HTTP server (`asyncio`, raw sockets). Atomic task claiming, session heartbeats |
| `claudia.dashboard` | Terminal UI. Reads state files directly |
| `claudia.docs` | Documentation generation agent |

### State Directory Structure

```
.agent-state/
├── tasks.json           # {version, next_id, tasks[]}
├── history.jsonl        # Append-only event log
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
| `/task/request` | POST | Atomically claim next task |
| `/task/complete` | POST | Mark done with note/branch |
| `/task/note` | POST | Add progress note |

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
    # ... do the work ...
    agent.complete_task(task['id'], "Brief completion note")

# Create new tasks
agent.create_task(
    title="Fix: edge case in validation",
    description="Discovered while implementing...",
    priority=1,
    labels=["bug", "discovered"]
)
```

## Reference Documentation

See `AGENT_INSTRUCTIONS.md` for comprehensive usage instructions including:
- Session lifecycle workflows
- Parallel mode orchestration
- Git branch workflows
- Communication protocols between main/worker sessions
