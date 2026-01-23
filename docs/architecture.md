# Architecture Overview

A lightweight task coordination system for Claude Code

## Project Structure

```
  src/claudia/ (7 files, python)
tests/ (6 files, python)
```

## Key Modules

### `src/claudia/agent.py`
Unified Agent Client for Claudia.

Works in two modes:
1. SINGLE MODE (default): Direct JSON file access, no server needed
2.

**Classes:**
- `FileLock`: __init__(), acquire(), release(), __enter__(), __exit__()
- `Agent`: __post_init__(), is_parallel_mode(), get_mode(), register(), heartbeat(), ... (+15 more)

**Key functions:**
- `file_lock()`
- `is_task_ready()`

### `src/claudia/cli.py`

**Key functions:**
- `cmd_init()`
- `cmd_uninstall()`
- `cmd_update()`
- `cmd_status()`
- `cmd_tasks()`

### `src/claudia/colors.py`
Colors Utility Module

Provides terminal color support with automatic detection of terminal capabilities.
Extracted from dashboard.py for reuse across CLI components.

**Classes:**
- `Colors`: is_enabled(), priority_color(), status_color(), format_priority(), format_status()

**Key functions:**
- `priority_str()`
- `status_str()`
- `colorize()`

### `src/claudia/coordinator.py`

**Classes:**
- `TaskStatus`
- `Task`: to_dict(), from_dict()
- `Session`: to_dict(), from_dict()
- `CoordinatorState`: __init__(), subscribe(), unsubscribe()
- `Coordinator`: __init__(), score_task()

### `src/claudia/dashboard.py`

**Key functions:**
- `clear()`
- `time_ago()`
- `load_state_direct()`
- `render()`
- `enter_alt_screen()`

### `src/claudia/docs.py`
Documentation Agent for Claudia.

Generates human-centered documentation about codebase architecture,
development workflows, and APIs. Designed to be concise and actionable,
not verbose AI-speak.

**Classes:**
- `ProjectMetadata`
- `FileInfo`
- `DocsAgent`: __post_init__(), extract_toml_value(), extract_value(), analyze(), generate()

**Key functions:**
- `cmd_docs()`

### `tests/conftest.py`
Pytest configuration and shared fixtures for Claudia tests.

**Key functions:**
- `temp_state_dir()`
- `agent()`
- `sample_tasks()`
- `agent_with_tasks()`
- `sample_template()`

### `tests/test_agent.py`
Tests for the Agent class (single mode).

**Classes:**
- `TestAgentBasics`: test_agent_init(), test_get_status_empty(), test_get_status_with_tasks()
- `TestTaskCRUD`: test_create_task(), test_get_tasks(), test_get_tasks_filtered(), test_edit_task(), test_edit_task_not_found(), ... (+2 more)
- `TestTaskWorkflow`: test_get_next_task(), test_get_next_task_with_labels(), test_get_next_task_empty(), test_complete_task(), test_reopen_task()
- `TestSubtasks`: test_create_subtask(), test_create_subtask_parent_not_found(), test_get_subtasks(), test_get_subtask_progress()
- `TestTemplates`: test_list_templates_empty(), test_create_template(), test_get_template(), test_delete_template(), test_create_from_template()

### `tests/test_cli.py`
Tests for the CLI module.

**Classes:**
- `TestCLICommands`: test_cli_help(), test_cli_version(), test_cli_status(), test_cli_status_json(), test_cli_create(), ... (+5 more)
- `TestCLISubtasks`: test_subtask_create(), test_subtask_list()
- `TestCLITemplates`: test_template_create(), test_template_list()
- `TestCLITime`: test_time_start_stop(), test_time_report()
- `TestCLIArchive`: test_archive_dry_run(), test_archive_list()

### `tests/test_colors.py`
Tests for the colors module.

**Classes:**
- `TestColorsDetection`: test_force_color_env(), test_no_color_env()
- `TestColorsFormatting`: test_format_priority(), test_format_status(), test_colorize()
- `TestColorsDisabled`: test_format_priority_no_color(), test_format_status_no_color()
- `TestColorConstants`: test_color_codes(), test_is_enabled()

### `tests/test_docs.py`
Tests for the DocsAgent documentation generator.

**Classes:**
- `Config`: validate(), to_dict()
- `Application`: __init__(), run(), stop()
- `TestProjectMetadataLoading`: test_parse_pyproject_toml(), test_parse_package_json(), test_parse_setup_py()
- `TestFileAnalysis`: test_analyze_python_file(), test_analyze_js_file(), test_extract_python_imports(), test_extract_python_classes(), test_extract_python_methods(), ... (+3 more)
- `TestSkillLevels`: test_level_limit_junior(), test_level_limit_mid(), test_level_limit_senior(), test_level_content(), test_is_level()

**Key functions:**
- `temp_project_dir()`
- `python_project()`
- `main()`
- `helper_function()`
- `format_string()`

## Entry Points

- **src/claudia/cli.py**: Entry point: cli.py

## Dependencies

- `React`
- `certifi`
- `pytest`
- `setuptools`
- `{`
