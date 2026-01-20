# API Reference

API documentation for `claudia` v2.0

## src/claudia

### `agent.py`

Unified Agent Client for Claudia.

Works in two modes:
1. **SINGLE MODE** (default): Direct JSON file access with file locking for concurrent safety
2. **PARALLEL MODE**: Connects to coordinator via HTTP with retry logic and exponential backoff

#### Classes

**FileLock**

Cross-platform file locking for single-mode concurrent safety.

- `__init__(lock_path, timeout=10.0)` - Initialize with lock file path
- `acquire() -> bool` - Acquire lock, returns True on success
- `release()` - Release the lock

**Agent**

Main client class for task coordination.

*Initialization & Mode Detection:*
- `__post_init__()` - Initialize agent, detect mode
- `is_parallel_mode() -> bool` - Check if running in parallel mode
- `get_mode() -> str` - Returns "single" or "parallel"

*Session Management:*
- `register(context, role, labels)` - Register session with coordinator
- `heartbeat()` - Send heartbeat to keep session alive
- `end_session()` - End session, release claimed tasks

*Core Task Operations:*
- `get_next_task(preferred_labels) -> dict` - Claim next available task
- `complete_task(task_id, note, branch, force) -> dict` - Mark task done
- `reopen_task(task_id, note) -> bool` - Reopen completed task
- `create_task(title, description, priority, labels, blocked_by) -> dict` - Create new task
- `add_note(task_id, note)` - Add progress note to task

*Task Editing (v1.1):*
- `edit_task(task_id, title, description, priority, labels) -> dict` - Edit task properties
- `delete_task(task_id, force) -> dict` - Delete task (force=True deletes subtasks)

*Bulk Operations (v1.1):*
- `bulk_complete(task_ids, note, branch, force) -> dict` - Complete multiple tasks at once
  - Returns: `{succeeded: [...], failed: [{id, error, ...}], total_succeeded, total_failed}`
- `bulk_reopen(task_ids, note) -> dict` - Reopen multiple tasks at once
  - Returns: `{succeeded: [...], failed: [{id, error}], total_succeeded, total_failed}`

*Subtasks (v2.0):*
- `create_subtask(parent_id, title, description, priority, labels) -> dict` - Create subtask
- `get_subtasks(parent_id) -> list` - Get all subtasks of a parent
- `get_subtask_progress(parent_id) -> dict` - Get completion progress

*Templates (v2.0):*
- `list_templates() -> list` - List all templates
- `get_template(template_id) -> dict` - Get template by ID
- `create_template(name, description, default_priority, default_labels, subtasks) -> dict`
- `delete_template(template_id) -> bool` - Delete template
- `create_from_template(template_id, title, description, priority, labels) -> dict`

*Time Tracking (v2.0):*
- `start_timer(task_id) -> dict` - Start timer for task
- `stop_timer(task_id) -> dict` - Stop timer, save elapsed time
- `pause_timer(task_id) -> dict` - Pause timer, save elapsed time
- `get_task_time(task_id) -> dict` - Get time tracking info
- `get_time_report(by, labels) -> dict` - Get time report by task/label/day

*Archiving (v1.1):*
- `archive_tasks(days_old, dry_run) -> dict` - Archive old completed tasks
- `list_archived(limit) -> list` - List archived tasks
- `restore_from_archive(task_id) -> dict` - Restore task from archive

*Undo (v1.1):*
- `undo_last_action() -> dict` - Undo last reversible action

*Status & Queries:*
- `get_status() -> dict` - Get system status
- `get_tasks(status) -> list` - List tasks, optionally filtered

*Parallel Mode Control:*
- `start_parallel_mode(port) -> bool` - Start coordinator server
- `stop_parallel_mode() -> bool` - Stop coordinator
- `get_parallel_summary() -> dict` - Get summary for merge phase

#### Functions

- `is_task_ready(task, task_map) -> bool` - Check if task is ready to claim

### `cli.py`

Command-line interface with colored output.

#### Functions

*Formatting Helpers:*
- `_format_priority(p)` - Format priority as P0-P3
- `_format_duration(iso_start)` - Format duration from timestamp
- `_format_task_short(task, use_color)` - Format task one-liner with colors
- `_format_task_status_summary(status_counts, ready_count, use_color)` - Format status summary

*Interactive Mode:*
- `_interactive_create(agent, use_json)` - Guided task creation wizard

*Commands:*
- `cmd_init(args)` - Initialize Claudia in project
- `cmd_uninstall(args)` - Remove Claudia from project
- `cmd_update(args)` - Check for updates
- `cmd_status(args, agent, use_json)` - Show system status
- `cmd_tasks(args, agent, use_json)` - List tasks with colors
- `cmd_show(args, agent, use_json)` - Show task details
- `cmd_create(args, agent, use_json, dry_run)` - Create task
- `cmd_next(args, agent, use_json, dry_run)` - Claim next task
- `cmd_complete(args, agent, use_json, dry_run)` - Complete task(s)
- `cmd_edit(args, agent, use_json, dry_run)` - Edit task
- `cmd_delete(args, agent, use_json, dry_run)` - Delete task
- `cmd_reopen(args, agent, use_json, dry_run)` - Reopen task
- `cmd_archive(args, agent, use_json, dry_run)` - Archive operations
- `cmd_time(args, agent, use_json, dry_run)` - Time tracking
- `cmd_template(args, agent, use_json, dry_run)` - Template management
- `cmd_subtask(args, agent, use_json, dry_run)` - Subtask management
- `cmd_session(args, agent, use_json)` - Show session info
- `main()` - Entry point

### `coordinator.py`

Async HTTP server for parallel mode coordination.

#### Classes

**TaskStatus** (Enum)
- `OPEN`, `IN_PROGRESS`, `DONE`, `BLOCKED`

**Task** (dataclass)
- Core fields: `id`, `title`, `description`, `status`, `priority`, `labels`
- Assignment: `assignee`, `blocked_by`, `branch`
- Timestamps: `created_at`, `updated_at`
- v2 fields: `parent_id`, `subtasks`, `is_subtask`, `time_tracking`
- `to_dict() -> dict`
- `from_dict(data) -> Task`

**Session** (dataclass)
- `session_id`, `role`, `context`, `labels`
- `started_at`, `last_heartbeat`, `working_on`
- `to_dict() -> dict`
- `from_dict(data) -> Session`

**CoordinatorState**
- `__init__(state_dir)` - Initialize state
- `subscribe(callback)` - Subscribe to state changes
- `unsubscribe(callback)` - Unsubscribe

**Coordinator**
- `__init__(state)` - Initialize coordinator
- `score_task(task, session)` - Score task-session affinity
- `_calculate_session_affinity(session_id, task)` - Calculate label overlap
- `_get_session_load(session_id)` - Get number of assigned tasks

### `dashboard.py`

Terminal UI for monitoring tasks and sessions.

#### Constants
- `STALE_WARNING_THRESHOLD = 60` - Yellow warning after 60s
- `STALE_DANGER_THRESHOLD = 120` - Red STALE badge after 120s

#### Functions

- `clear()` - Clear terminal screen
- `time_ago(iso_time) -> str` - Convert timestamp to relative time
- `load_state_direct(state_dir) -> dict` - Load state from files
- `render(state_dir)` - Render dashboard with timeout warnings
- `enter_alt_screen()` - Enter alternate screen buffer
- `exit_alt_screen()` - Exit alternate screen buffer
- `main(state_dir, refresh, once, no_alt_screen)` - Run dashboard

### `colors.py`

Terminal color utilities with automatic detection.

#### Functions

- `_supports_color() -> bool` - Check terminal color support (respects FORCE_COLOR, NO_COLOR)

#### Classes

**Colors**
- Class attributes: `RESET`, `BOLD`, `DIM`, `UNDERLINE`
- Colors: `BLACK`, `RED`, `GREEN`, `YELLOW`, `BLUE`, `MAGENTA`, `CYAN`, `WHITE`
- Bright: `BRIGHT_RED`, `BRIGHT_GREEN`, `BRIGHT_YELLOW`, `BRIGHT_BLUE`, `BRIGHT_MAGENTA`, `BRIGHT_CYAN`
- `is_enabled() -> bool` - Check if colors enabled
- `priority_color(priority) -> str` - Get color for priority
- `status_color(status) -> str` - Get color for status
- `format_priority(priority) -> str` - Format priority with color
- `format_status(status) -> str` - Format status with color

#### Convenience Functions
- `priority_str(p) -> str` - Shorthand for format_priority
- `status_str(s) -> str` - Shorthand for format_status
- `colorize(text, color) -> str` - Apply color to text

### `docs.py`

Documentation generation agent.

#### Classes

**ProjectMetadata** (dataclass)
- `name`, `version`, `description`, `python_version`
- `dependencies`, `dev_dependencies`, `entry_points`

**FileInfo** (dataclass)
- `path`, `language`, `lines`, `functions`, `classes`, `imports`

**DocsAgent**
- `__post_init__()` - Initialize analyzer
- `extract_toml_value(content, key)` - Extract value from TOML
- `extract_value(content, key)` - Extract value from config
- `analyze() -> dict` - Analyze codebase structure
- `generate(doc_type, level) -> str` - Generate documentation

#### Functions

- `cmd_docs(args)` - CLI handler for docs commands
