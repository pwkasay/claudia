# Agent State Directory

This directory contains state for the agent coordination system.

## Files

- `tasks.json` - Task database (status, priorities, dependencies)
- `history.jsonl` - Event log
- `sessions/` - Active session tracking
- `.parallel-mode` - Present when parallel mode is active
- `coordinator.pid` - Coordinator process ID (parallel mode only)

## Modes

**Single mode** (default): One Claude Code session, direct JSON access.

**Parallel mode**: Multiple sessions coordinated by background server.

See CLAUDE.md in project root for usage instructions.
