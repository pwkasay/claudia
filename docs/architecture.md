# Architecture Overview

Claudia v2.0 - A lightweight task coordination system for Claude Code

## Project Structure

```
src/claudia/
├── __init__.py      # Package exports (Agent, __version__)
├── agent.py         # Unified client API (single/parallel modes)
├── cli.py           # Command-line interface
├── coordinator.py   # Async HTTP server for parallel mode
├── dashboard.py     # Terminal UI with monitoring
├── colors.py        # Terminal color utilities
└── docs.py          # Documentation generation
```

## Operating Modes

### Single Mode (Default)
- Direct JSON file access with atomic write (tmp + rename)
- File locking (`FileLock`) for concurrent safety
- No server required - all state in `.agent-state/tasks.json`

### Parallel Mode
- Coordinator runs as background HTTP server
- Agent detects mode via `.agent-state/.parallel-mode` file
- All operations route through HTTP to coordinator
- Atomic task assignment with smart load balancing
- Retry logic with exponential backoff (0.5s → 1s → 2s → 4s, max 8s)

## Key Modules

### `agent.py` - Unified Client API

The Agent class provides a unified interface that works in both modes.

**Core Features:**
- Mode detection and automatic routing
- Session management (register, heartbeat, end)
- Task CRUD operations
- Subtask hierarchy (v2.0)
- Templates for reusable task patterns (v2.0)
- Time tracking with start/stop/pause (v2.0)
- Bulk operations (v1.1)
- Undo system with action history (v1.1)
- Archiving old completed tasks (v1.1)

**Key Classes:**
- `FileLock` - Cross-platform file locking (fcntl/msvcrt)
- `Agent` - Main client class with 40+ methods

### `cli.py` - Command Line Interface

Rich CLI with colored output and comprehensive commands.

**Command Categories:**
- Task management: create, show, edit, delete, complete, reopen
- Subtasks: create, list, progress
- Templates: list, create, show, delete
- Time tracking: start, stop, pause, status, report
- Archiving: run, list, restore
- Parallel mode: start-parallel, stop-parallel, session, dashboard

**Global Flags:**
- `--json` - Machine-readable output
- `--dry-run` - Preview changes
- `--verbose` - Detailed errors

### `coordinator.py` - Parallel Mode Server

Async HTTP server using raw sockets and asyncio.

**Features:**
- Atomic task claiming with locking
- Smart assignment based on label affinity
- Load balancing across sessions
- Session heartbeat monitoring
- Real-time state broadcasting

**Key Classes:**
- `TaskStatus` - Enum: OPEN, IN_PROGRESS, DONE, BLOCKED
- `Task` - Task dataclass with v2 schema
- `Session` - Session state tracking
- `CoordinatorState` - Shared state with pub/sub
- `Coordinator` - HTTP request handling

### `dashboard.py` - Terminal UI

Real-time monitoring dashboard.

**Features:**
- Task queue visualization
- Session status with stale warnings (60s yellow, 120s red)
- Ready/in-progress/completed task counts
- Alternate screen buffer (preserves scrollback)

### `colors.py` - Terminal Colors

Automatic color detection with override support.

**Environment Variables:**
- `FORCE_COLOR` - Force colors on (checked first)
- `NO_COLOR` - Force colors off

### `docs.py` - Documentation Generator

Analyzes codebase and generates documentation.

**Output Types:**
- Architecture overview
- Onboarding guide
- API reference
- README

## Data Flow

### Single Mode
```
CLI → Agent → FileLock → tasks.json
                ↓
           history.jsonl (undo data)
```

### Parallel Mode
```
CLI → Agent → HTTP Request → Coordinator → State
                    ↓              ↓
              Retry Logic    AsyncIO Lock
                    ↓              ↓
              Exponential      Atomic
              Backoff         Assignment
```

## State Directory

```
.agent-state/
├── tasks.json        # Main task storage (v2 schema)
├── templates.json    # Task templates
├── archive.jsonl     # Archived tasks
├── history.jsonl     # Event log with undo data
├── sessions/         # Session state files
├── .parallel-mode    # Mode flag + port info
├── coordinator.pid   # Process management
└── .lock             # File lock for single mode
```

## Task Schema (v2)

```json
{
  "id": "task-001",
  "title": "Task title",
  "description": "Optional description",
  "status": "open",
  "priority": 2,
  "labels": ["backend"],
  "assignee": null,
  "blocked_by": [],
  "notes": [],
  "created_at": "2024-01-15T10:00:00Z",
  "updated_at": "2024-01-15T10:00:00Z",
  "parent_id": null,
  "subtasks": [],
  "is_subtask": false,
  "time_tracking": {
    "total_seconds": 0,
    "started_at": null,
    "is_running": false,
    "is_paused": false
  }
}
```

## HTTP API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/status` | GET | System status |
| `/tasks` | GET | List tasks |
| `/session/register` | POST | Register session |
| `/session/heartbeat` | POST | Keep alive |
| `/task/create` | POST | Create task |
| `/task/request` | POST | Claim task |
| `/task/complete` | POST | Complete task |
| `/task/reopen` | POST | Reopen task |
| `/task/edit` | POST | Edit task |
| `/task/delete` | POST | Delete task |
| `/task/bulk-complete` | POST | Bulk complete |
| `/subtask/create` | POST | Create subtask |
| `/subtask/progress` | GET | Subtask progress |

## Dependencies

- Python 3.10+ (standard library only)
- Optional: `certifi` for SSL on macOS

## Entry Points

- CLI: `claudia` command (via `cli.main()`)
- Python API: `from claudia import Agent`
