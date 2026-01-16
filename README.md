# Claudia

A lightweight task coordination system for Claude Code that supports both single-session and parallel multi-session workflows.

## Features

- **Task Management**: Create, track, and complete tasks with priorities and labels
- **Parallel Mode**: Coordinate multiple Claude Code sessions working on the same codebase
- **Session Tracking**: Monitor active sessions and their assigned work
- **Documentation Generation**: Auto-generate architecture docs, onboarding guides, and API references
- **Git-Native Workflows**: Branch-per-task support for parallel development

## Installation

```bash
pip install git+https://github.com/pwkasay/claudia.git
```

For SSL certificate support (recommended on macOS):
```bash
pip install 'claudia[ssl]'
```

## Quick Start

```bash
# Initialize in your project
cd your-project
claudia init

# Create a task
claudia create "Implement user authentication" -p 1 -l backend auth

# Check status
claudia status

# Claim and work on a task
claudia next
# ... do the work ...
claudia complete task-001 --note "Implemented JWT auth"
```

## Commands

| Command | Description |
|---------|-------------|
| `claudia init` | Initialize Claudia in a project |
| `claudia status` | Show system status |
| `claudia tasks` | List all tasks |
| `claudia create <title>` | Create a new task |
| `claudia next` | Claim the next available task |
| `claudia complete <id>` | Mark a task as complete |
| `claudia show <id>` | View task details |
| `claudia session` | View active sessions |
| `claudia docs analyze` | Analyze codebase structure |
| `claudia docs generate` | Generate documentation |
| `claudia update --check` | Check for updates |

## Parallel Mode

For large projects, spin up multiple Claude Code sessions:

```bash
# Main session: start parallel mode
claudia start-parallel

# Other terminals: just run claude - they auto-connect
# Each session claims tasks atomically, no conflicts

# When done, stop parallel mode
claudia stop-parallel
```

### How It Works

```
Single Mode:  Claude → claudia → tasks.json (direct)
Parallel:     Main → coordinator.py → Workers (atomic assignment)
```

Workers create branches, main session merges when done.

## Documentation Generation

```bash
# Analyze your codebase
claudia docs analyze

# Generate architecture docs
claudia docs generate --type architecture

# Generate all doc types
claudia docs all
```

Generates:
- `docs/architecture.md` - Project structure, key modules, dependencies
- `docs/onboarding.md` - Developer setup guide
- `docs/api.md` - API reference

## Dashboard

Watch task progress in real-time:

```bash
claudia dashboard
```

```
═════════════════════════════════════════════════════════════════
  AGENT DASHBOARD │ Mode: PARALLEL
═════════════════════════════════════════════════════════════════

📊 OVERVIEW
   Tasks: 12 total, 3 ready

👥 SESSIONS (3 active)
   abc123 [MAIN] Orchestrating backend
   def456 [worker] Frontend work
      └─ Working: task-004

📋 READY QUEUE
   P1 task-007: Add rate limiting [backend,security]
   P2 task-008: Write tests [testing]

⚡ IN PROGRESS
   task-004: Build login page
      → def456: "Styling the form..."
```

## Task Priorities

| Priority | Label | Use Case |
|----------|-------|----------|
| P0 | critical | Blocking issues, security fixes |
| P1 | high | Important features, bugs |
| P2 | medium | Normal work (default) |
| P3 | low | Nice-to-haves, cleanup |

## Project Structure

```
your-project/
├── .agent-state/           # Claudia state
│   ├── tasks.json          # Task database
│   ├── history.jsonl       # Event log
│   └── sessions/           # Active session tracking
├── CLAUDE.md               # Project context for Claude Code
└── docs/                   # Generated documentation
```

## Requirements

- Python 3.10+
- No external dependencies (stdlib only)

## License

MIT
