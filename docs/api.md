# API Reference

## .

### `agent.py`

#### Classes

- **Agent**

#### Functions

- `is_task_ready()`
- `main()`

### `coordinator.py`

#### Classes

- **TaskStatus**
- **Task**
- **Session**
- **CoordinatorState**
- **Coordinator**

### `dashboard.py`

#### Classes

- **Colors**

#### Functions

- `clear()`
- `time_ago()`
- `priority_str()`
- `load_state_direct()`
- `render()`
- `enter_alt_screen()`
- `exit_alt_screen()`
- `main()`

### `setup.py`

#### Functions

- `create_state_dir()`
- `create_tasks_json()`
- `create_history()`
- `create_readme()`
- `create_gitkeep()`
- `update_gitignore()`
- `copy_agent_files()`
- `append_claude_md()`
- `main()`

## src/claudia

### `agent.py`

Unified Agent Client for Claudia.

Works in two modes:
1. SINGLE MODE (default): Direct JSON file access, no server needed
2. PARALLEL MODE: Connects to coordinator for atomic operations

The mode is 

#### Classes

- **Agent**

#### Functions

- `is_task_ready()`

### `cli.py`

#### Functions

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

### `coordinator.py`

#### Classes

- **TaskStatus**
- **Task**
- **Session**
- **CoordinatorState**
- **Coordinator**

### `dashboard.py`

#### Classes

- **Colors**

#### Functions

- `clear()`
- `time_ago()`
- `priority_str()`
- `load_state_direct()`
- `render()`
- `enter_alt_screen()`
- `exit_alt_screen()`
- `main()`

### `docs.py`

Documentation Agent for Claudia.

Generates human-centered documentation about codebase architecture,
development workflows, and APIs. Designed to be concise and actionable,
not verbose AI-speak.

Usa

#### Classes

- **FileInfo**
- **DocsAgent**

#### Functions

- `cmd_docs()`
