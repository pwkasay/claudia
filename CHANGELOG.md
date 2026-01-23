# Changelog

All notable changes to Claudia are documented here.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.1.0] - 2026-01-23

### Added
- Session cleanup command (`claudia session cleanup`) for removing stale sessions
- Continuous task processing improvements in Agent class
- Documentation generation with incremental analysis and atomic writes

### Changed
- Improved DocsAgent reliability with better state management

## [1.0.0] - 2026-01-20

### Added
- **Subtasks**: Create hierarchical task structures with `claudia subtask create`
- **Templates**: Reusable task templates with predefined subtasks via `claudia template`
- **Time tracking**: Start/stop/pause timers with `claudia time` commands
- **Bulk operations**: Complete or reopen multiple tasks at once
- **Archiving**: Archive old tasks with `claudia archive`
- **Undo support**: Revert last action via history tracking

### Changed
- Task schema upgraded to v2 with parent_id, subtasks, and time_tracking fields
- Enhanced coordinator with smart task assignment

## [0.1.0] - 2026-01-16

### Added
- Core task management (create, list, complete, reopen)
- Single-session mode with atomic file operations
- Parallel mode with HTTP coordinator for multi-session workflows
- CLI interface with 20+ commands
- Real-time terminal dashboard
- Session tracking and heartbeats
- Git-native branch workflows
- Priority levels (P0-P3) and label system
- Documentation generation (`claudia docs`)

[1.1.0]: https://github.com/pwkasay/claudia/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/pwkasay/claudia/compare/v0.1.0...v1.0.0
[0.1.0]: https://github.com/pwkasay/claudia/releases/tag/v0.1.0
