# API Reference

API documentation for `claudia`

Version: 0.1.0

> **How to read this:** Each module lists its classes and functions.
> Classes show their methods. Start with the main classes to understand the API.

## src/claudia

### `agent.py`

Unified Agent Client for Claudia.

Works in two modes:
1. SINGLE MODE (default): Direct JSON file access, no server needed
2.

#### Classes

**Agent**

- `__post_init__()`
- `is_parallel_mode()`
- `get_mode()`
- `register()`
- `heartbeat()`
- `end_session()`
- `get_next_task()`
- `score()`
- `complete_task()`
- `reopen_task()`
- `create_task()`
- `add_note()`
- `get_status()`
- `get_tasks()`
- `start_parallel_mode()`
- `stop_parallel_mode()`
- `get_parallel_summary()`

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
**Task**

- `to_dict()`
- `from_dict()`

**Session**

- `to_dict()`
- `from_dict()`

**CoordinatorState**

- `__init__()`
- `subscribe()`
- `unsubscribe()`

**Coordinator**

- `__init__()`
- `score_task()`

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

#### Classes

- **ProjectMetadata**
- **FileInfo**
**DocsAgent**

- `__post_init__()`
- `extract_toml_value()`
- `extract_value()`
- `analyze()`
- `generate()`

#### Functions

- `cmd_docs()`
