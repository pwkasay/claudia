# Claudia Roadmap

This document tracks planned improvements and future directions for Claudia.

## Current State (v1.0)

A working task coordination system with:
- Single/parallel mode auto-detection
- Atomic task claiming via HTTP coordinator
- Priority-based scheduling (P0-P3)
- Label-based filtering
- Task dependencies (`blocked_by`)
- Session tracking with heartbeats
- Git branch workflow support
- Terminal dashboard
- Zero external dependencies

---

## v1.1 - Polish & Stability

Near-term improvements to solidify the foundation.

### Task Management
- [ ] **Task editing** - Update title/description/priority after creation
- [ ] **Task deletion** - Remove tasks (with confirmation)
- [ ] **Bulk operations** - Complete/reopen multiple tasks at once
- [ ] **Task archiving** - Move old done tasks to archive file

### CLI Improvements
- [ ] **Interactive mode** - `agent.py interactive` for guided task creation
- [ ] **Better tab completion** - Shell completions for bash/zsh/fish
- [ ] **Colored output** - Priority-aware colors in task listings
- [ ] **Undo last action** - Revert accidental complete/claim

### Reliability
- [ ] **Lock file for single mode** - Prevent concurrent file corruption
- [ ] **Graceful coordinator reconnect** - Auto-retry on connection drop
- [ ] **Session timeout warnings** - Alert before session goes stale

---

## v2.0 - Major Features

### Subtasks & Checklists
```
task-001: Implement auth API
  ├─ [ ] Design JWT structure
  ├─ [x] Create user model
  └─ [ ] Write login endpoint
```
- Subtasks as first-class citizens with their own IDs
- Progress tracking (3/5 subtasks done)
- Subtask dependencies

### Task Templates
```bash
# Define reusable templates
python agent.py template create "feature" \
  --subtasks "Design,Implement,Test,Document" \
  --labels "feature"

# Use template
python agent.py create "User profiles" --template feature
```
- Pre-defined task structures
- Default labels and priorities
- Project-specific templates in `.agent-state/templates.json`

### SQLite Backend (Optional)
- Better concurrent access than JSON files
- Full-text search on descriptions
- Faster queries for large task counts
- Migration path: `python agent.py migrate --to sqlite`
- Keep JSON as default for simplicity

### Time Tracking
```bash
python agent.py start task-001      # Start timer
python agent.py pause task-001      # Pause (keep claimed)
python agent.py stop task-001       # Stop timer, show duration
python agent.py report --week       # Time spent this week
```
- Optional time logging per task
- Session-based tracking
- Reports and analytics

### Smart Assignment
- **Affinity scoring** - Prefer assigning related tasks to same session
- **Label expertise** - Track which sessions handle which labels best
- **Load balancing** - Distribute work evenly in parallel mode
- **Conflict detection** - Warn if two sessions edit same files

---

## v2.1 - Integrations

### GitHub Integration
```bash
# Sync with GitHub Issues
python agent.py github sync owner/repo
python agent.py github import owner/repo#123

# Auto-link branches to issues
python agent.py complete task-001 --close-issue 123
```
- Two-way sync with GitHub Issues
- Import issues as tasks
- Link task completion to issue closing
- PR creation from task branches

### Git Hooks
```bash
# Auto-complete task when branch merged
# .git/hooks/post-merge
python agent.py git-hook post-merge

# Validate commit references task ID
# .git/hooks/commit-msg
python agent.py git-hook commit-msg
```
- Post-merge: auto-complete tasks for merged branches
- Pre-commit: ensure task is claimed before committing
- Commit-msg: validate task ID in commit message

### Import/Export
```bash
# Export for backup or migration
python agent.py export tasks.csv
python agent.py export tasks.json --include-history

# Import from other tools
python agent.py import --from jira JQL_QUERY
python agent.py import --from linear team/project
python agent.py import --from markdown TODO.md
```

---

## v3.0 - Advanced Features

### Web Dashboard
- Real-time updates via WebSocket
- Drag-and-drop task reordering
- Kanban board view
- Mobile-friendly
- Optional - keep terminal dashboard as primary

### Multi-Project Support
```bash
# Work across multiple projects
python agent.py --project backend status
python agent.py --project frontend next

# Global dashboard
python agent.py dashboard --all-projects
```
- Central coordination across repos
- Cross-project dependencies
- Unified reporting

### AI-Assisted Features
- **Smart task breakdown** - Suggest subtasks for large tasks
- **Dependency detection** - Infer blocked_by from task descriptions
- **Effort estimation** - Predict complexity based on history
- **Similar task search** - Find related past tasks

### Workflow Automation
```yaml
# .agent-state/workflows.yaml
on_task_complete:
  - run: pytest
    if: labels contains 'backend'
  - notify: slack
    channel: dev-updates

on_all_tasks_done:
  - run: git merge --no-ff
  - run: npm run build
```

---

## Ideas Under Consideration

These may or may not happen depending on user needs:

- **Task comments** - Discussion threads on tasks
- **Attachments** - Link files/screenshots to tasks
- **Recurring tasks** - Auto-create weekly/monthly tasks
- **Task estimation** - Story points or t-shirt sizing
- **Custom fields** - User-defined metadata
- **Notifications** - Desktop/system notifications
- **API mode** - JSON-RPC or REST API for external tools
- **Plugin system** - User-defined hooks and extensions

---

## Non-Goals

Things we explicitly won't do:

- **Full project management** - Not replacing Jira/Linear/Asana
- **User authentication** - Single-user/team tool, not multi-tenant
- **Cloud sync** - State stays local (use git for sharing)
- **GUI-first** - Terminal remains the primary interface
- **Complex workflows** - Keep it simple, not a workflow engine

---

## Contributing Ideas

Have a feature request? Consider:

1. Does it fit the "lightweight coordination" philosophy?
2. Can it work without external dependencies?
3. Does it help Claude Code sessions work better together?

Open an issue or PR with your proposal!
