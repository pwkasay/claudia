# Architecture Overview

A lightweight task coordination system for Claude Code

> **What is this?** This document explains how the codebase is organized,
> what each part does, and how they work together. Start here to understand
> the big picture before diving into the code.

## Project Structure

```
  src/claudia/ (6 files, python)
```

**Directory purposes:**

- **src/claudia/**: Contains 6 python files

## Key Modules

### `src/claudia/agent.py`
Unified Agent Client for Claudia.

Works in two modes:
1. SINGLE MODE (default): Direct JSON file access, no server needed
2.

**Classes:**
- `Agent`: __post_init__(), is_parallel_mode(), get_mode(), register(), heartbeat(), end_session(), get_next_task(), score(), complete_task(), reopen_task(), create_task(), add_note(), get_status(), get_tasks(), start_parallel_mode(), stop_parallel_mode(), get_parallel_summary()
  - *Primary methods: __post_init__, is_parallel_mode, get_mode*

**Key functions:**
- `is_task_ready()`

### `src/claudia/cli.py`

**Key functions:**
- `cmd_init()`
- `cmd_uninstall()`
- `cmd_update()`
- `cmd_status()`
- `cmd_tasks()`
- `cmd_show()`
- `cmd_create()`
- `cmd_next()`
- `cmd_complete()`
- `cmd_reopen()`
- `cmd_session()`
- `main()`

### `src/claudia/coordinator.py`

**Classes:**
- `TaskStatus`
- `Task`: to_dict(), from_dict()
  - *Primary methods: to_dict, from_dict*
- `Session`: to_dict(), from_dict()
  - *Primary methods: to_dict, from_dict*
- `CoordinatorState`: __init__(), subscribe(), unsubscribe()
  - *Primary methods: __init__, subscribe, unsubscribe*
- `Coordinator`: __init__(), score_task()
  - *Primary methods: __init__, score_task*

### `src/claudia/dashboard.py`

**Classes:**
- `Colors`

**Key functions:**
- `clear()`
- `time_ago()`
- `priority_str()`
- `load_state_direct()`
- `render()`
- `enter_alt_screen()`
- `exit_alt_screen()`
- `main()`

### `src/claudia/docs.py`
Documentation Agent for Claudia.

Generates human-centered documentation about codebase architecture,
development workflows, and APIs. Designed to be concise and actionable,
not verbose AI-speak.

**Classes:**
- `ProjectMetadata`
- `FileInfo`
- `DocsAgent`: __post_init__(), extract_toml_value(), extract_value(), analyze(), generate()
  - *Primary methods: __post_init__, extract_toml_value, extract_value*

**Key functions:**
- `cmd_docs()`

## Entry Points

> **Tip:** Entry points are where the program starts running.
> These files are good starting points for understanding the code flow.

- **src/claudia/cli.py**: Entry point: cli.py

## Dependencies

External packages this project uses:

- `certifi`
