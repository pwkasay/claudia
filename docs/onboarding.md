# Developer Onboarding Guide

Welcome to **Claudia v2.0**! A lightweight task coordination system for Claude Code

## Getting Started

### Prerequisites

- Python 3.10+
- pip or pipenv

### Installation

```bash
# Install from GitHub
pip install git+https://github.com/pwkasay/claudia.git

# Or clone and install in development mode
git clone https://github.com/pwkasay/claudia
cd claudia
pip install -e .
```

### Quick Start

```bash
# Initialize in your project
cd your-project
claudia init

# Create your first task
claudia create "My first task" -p 1 -l backend

# Claim and work on it
claudia next
# ... do the work ...
claudia complete task-001 --note "Done!"
```

## Project Structure

```
src/claudia/
├── __init__.py      # Package exports
├── agent.py         # Core Agent class (single/parallel modes)
├── cli.py           # Command-line interface
├── coordinator.py   # HTTP server for parallel mode
├── dashboard.py     # Terminal monitoring UI
├── colors.py        # Terminal color utilities
└── docs.py          # Documentation generator
```

## Key Concepts

### Operating Modes

**Single Mode** (default): Direct file access, great for solo work
- Just run `claudia` commands - no server needed
- State stored in `.agent-state/tasks.json`

**Parallel Mode**: For multi-session collaboration
```bash
claudia start-parallel --port 8765
# Now multiple Claude Code sessions can coordinate
claudia stop-parallel
```

### Task Lifecycle

```
open → in_progress → done
         ↓
      blocked
```

### Priority Levels

- **P0** (critical) - Urgent blockers
- **P1** (high) - Important work
- **P2** (medium) - Normal tasks (default)
- **P3** (low) - Nice to have

## Key Files to Understand

Start with these files:

1. **`agent.py`** - Core API. Understand the `Agent` class and how single/parallel modes work.

2. **`cli.py`** - Entry point. See how commands map to Agent methods.

3. **`coordinator.py`** - For parallel mode. Understand `Coordinator` class and HTTP endpoints.

## Common Development Tasks

### Adding a New CLI Command

1. Add command parser in `cli.py`:
```python
new_p = subparsers.add_parser('mycommand', help='Description')
new_p.add_argument('--flag', action='store_true')
```

2. Create command handler:
```python
def cmd_mycommand(args, agent, use_json, dry_run):
    # Implementation
```

3. Wire up in `main()`:
```python
elif args.command == 'mycommand':
    cmd_mycommand(args, agent, use_json, dry_run)
```

### Adding a New Agent Method

1. Add method to `Agent` class in `agent.py`:
```python
def my_method(self, param: str) -> dict:
    if self._parallel_mode:
        return self._request('POST', '/my/endpoint', {'param': param})
    else:
        # Single mode implementation
        ...
```

2. Add coordinator endpoint if needed in `coordinator.py`.

### Testing Your Changes

```bash
# Run the test suite
python -m pytest tests/ -v

# Test specific module
python -m pytest tests/test_agent.py -v

# Quick manual test
claudia status
claudia create "Test task"
claudia tasks
```

## Development Workflow

1. Create a feature branch:
```bash
git checkout -b feature/my-feature
```

2. Make your changes with tests

3. Run tests:
```bash
python -m pytest tests/ -v
```

4. Submit a pull request

## v2.0 Features

New in v2.0:
- **Subtasks**: Hierarchical task organization
- **Templates**: Reusable task patterns
- **Time Tracking**: Start/stop timers on tasks
- **Smart Assignment**: Label-based task routing in parallel mode

New in v1.1:
- **Bulk Operations**: Complete/reopen multiple tasks
- **Task Editing**: Update title, description, priority, labels
- **Archiving**: Move old completed tasks to archive
- **Undo**: Revert last action
- **Colored Output**: Priority/status colors in CLI

## Getting Help

- Check `CLAUDE.md` for command reference
- Read `docs/architecture.md` for system design
- See `docs/api.md` for full API reference
- Run `claudia --help` for command help
