# Architecture Overview

*A lightweight task coordination system for Claude Code*

## Key Modules

### `src/claudia/agent.py`
Unified Agent Client for Claudia.

Works in two modes:
1. SINGLE MODE (default): Direct JSON file access, no server needed
2.

**Classes:**
- `Agent`: __post_init__(), is_parallel_mode(), ... (+15 more)

### `src/claudia/cli.py`

### `src/claudia/coordinator.py`

**Classes:**
- `TaskStatus`
- `Task`: to_dict(), from_dict()
- `Session`: to_dict(), from_dict()

### `src/claudia/dashboard.py`

**Classes:**
- `Colors`

### `src/claudia/docs.py`
Documentation Agent for Claudia.

Generates human-centered documentation about codebase architecture,
development workflows, and APIs. Designed to be concise and actionable,
not verbose AI-speak.

**Classes:**
- `ProjectMetadata`
- `FileInfo`
- `DocsAgent`: __post_init__(), extract_toml_value(), ... (+3 more)

## Entry Points

- **src/claudia/cli.py**: Entry point: cli.py

## Dependencies

- `certifi`
