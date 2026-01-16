# Architecture Overview

## Project Structure

```
  src/claudia/ (6 files, python)
```

## Key Modules

### `agent.py`

**Classes:**
- `Agent`

**Key functions:**
- `is_task_ready()`
- `main()`

### `coordinator.py`

**Classes:**
- `TaskStatus`
- `Task`
- `Session`
- `CoordinatorState`
- `Coordinator`

### `dashboard.py`

**Classes:**
- `Colors`

**Key functions:**
- `clear()`
- `time_ago()`
- `priority_str()`
- `load_state_direct()`
- `render()`

### `setup.py`

**Key functions:**
- `create_state_dir()`
- `create_tasks_json()`
- `create_history()`
- `create_readme()`
- `create_gitkeep()`

### `src/claudia/agent.py`
Unified Agent Client for Claudia.

Works in two modes:
1. SINGLE MODE (default): Direct JSON file access, no server needed
2. PARALLEL MODE: Connects to coordinator for atomic operations

The mode is 

**Classes:**
- `Agent`

**Key functions:**
- `is_task_ready()`

### `src/claudia/cli.py`

**Key functions:**
- `cmd_init()`
- `cmd_uninstall()`
- `cmd_update()`
- `cmd_status()`
- `cmd_tasks()`

### `src/claudia/coordinator.py`

**Classes:**
- `TaskStatus`
- `Task`
- `Session`
- `CoordinatorState`
- `Coordinator`

### `src/claudia/dashboard.py`

**Classes:**
- `Colors`

**Key functions:**
- `clear()`
- `time_ago()`
- `priority_str()`
- `load_state_direct()`
- `render()`

### `src/claudia/docs.py`
Documentation Agent for Claudia.

Generates human-centered documentation about codebase architecture,
development workflows, and APIs. Designed to be concise and actionable,
not verbose AI-speak.

Usa

**Classes:**
- `FileInfo`
- `DocsAgent`

**Key functions:**
- `cmd_docs()`

## Entry Points

- **src/claudia/cli.py**: Entry point: cli.py

## Dependencies

- `argparse`
- `asyncio`
- `certifi`
- `claudia`
- `dataclasses`
- `datetime`
- `enum`
- `fnmatch`
- `json`
- `logging`
- `os`
- `pathlib`
- `re`
- `shutil`
- `signal`
- `socket`
- `ssl`
- `subprocess`
- `sys`
- `time`
