# Agent System Instructions

This file provides comprehensive instructions for Claude Code sessions using Claudia.

---

This project uses Claudia, a unified task coordination system that supports both single-session and parallel multi-session workflows.

---

## Quick Start (Every Session)

```python
from claudia import Agent

agent = Agent()
agent.register(context="Brief description of focus", labels=["backend", "python"])

# Check for work
status = agent.get_status()
print(f"Mode: {agent.get_mode()}")  # 'single' or 'parallel'
print(f"Ready tasks: {status['ready_tasks']}")

# Get and work on a task
task = agent.get_next_task()
if task:
    print(f"Working on: {task['id']} - {task['title']}")
    # ... do the work ...
    agent.complete_task(task['id'], "Brief completion note")
```

---

## Mode Detection

**On session start, always check the mode:**

```python
from claudia import Agent

agent = Agent()

if agent.is_parallel_mode():
    # You're a worker session - coordinator is running
    # Register and request work from coordinator
    agent.register(role="worker", context="Worker session", labels=["backend"])
    task = agent.get_next_task()  # Atomically assigned by coordinator
else:
    # Single session mode - you're the only one
    # Direct JSON access, no coordinator needed
    agent.register(context="Main session")
```

**The mode is determined by `.agent-state/.parallel-mode` file existence.**

---

## Single Session Mode (Default)

In single-session mode, Claude Code works directly with the task JSON:

```python
from claudia import Agent

agent = Agent()
agent.register(context="Working on feature X")

# All operations go directly to tasks.json
task = agent.get_next_task()
agent.add_note(task['id'], "Making progress...")
agent.complete_task(task['id'], "Implemented feature")

# Create new tasks as you discover work
agent.create_task(
    title="Fix: edge case in validation",
    description="Discovered while implementing...",
    priority=1,
    labels=["bug", "discovered"]
)

agent.end_session()
```

---

## Parallel Mode

### When to Suggest Parallelism

**Analyze the task backlog and suggest parallel sessions when:**

1. **Multiple high-priority independent tasks exist**
   ```
   Ready tasks with no dependency overlap:
   - P1: Implement auth API (backend)
   - P1: Build login UI (frontend)
   - P1: Set up CI pipeline (devops)

   → These can run in parallel
   ```

2. **Work is clearly dividable by domain**
   ```
   Labels indicate separate domains:
   - 4 tasks labeled "backend"
   - 3 tasks labeled "frontend"
   - 2 tasks labeled "database"

   → Suggest: "I can handle backend. Want to spin up sessions for frontend and database?"
   ```

3. **User explicitly requests it**
   - "parallelize this"
   - "spin up more sessions"
   - "can we work on this faster"
   - "use multiple sessions"

4. **Large independent workstreams identified**
   ```
   User: "Build me a full-stack app with auth, dashboard, and API"

   → Identify 3 independent streams
   → Suggest parallel approach
   ```

### How to Start Parallel Mode (Main Session)

```python
from claudia import Agent

agent = Agent()
agent.register(context="Main session - orchestrating", role="main")

# Analyze work and decide to parallelize
tasks = agent.get_tasks(status='open')
# ... analysis shows parallelizable work ...

# Start parallel mode
agent.start_parallel_mode(port=8765)

# Tell user what to do
print("""
Parallel mode activated!

I've identified 3 independent workstreams:
1. Backend API (I'll handle this)
2. Frontend UI
3. Database setup

To spin up workers, open new terminals and run:
    claude

They'll automatically connect and receive assignments.
""")
```

### Worker Session Behavior

When a new Claude Code session starts and detects `.parallel-mode`:

```python
from claudia import Agent

agent = Agent()

if agent.is_parallel_mode():
    # I'm a worker
    agent.register(
        role="worker",
        context="Worker session",
        labels=["frontend"]  # My specialty
    )

    # Get work from coordinator (atomic, no race conditions)
    while True:
        task = agent.get_next_task()
        if not task:
            print("No more tasks for me")
            break

        # Create a branch for my work
        branch = f"worker/{agent.session_id}/{task['id']}"
        # git checkout -b {branch}

        # Do the work...

        # Complete with branch reference
        agent.complete_task(task['id'], "Implemented feature", branch=branch)

    agent.end_session()
```

### Merge Phase (Main Session)

When workers finish, main session merges:

```python
# Check if workers are done
status = agent.get_status()
if status['active_workers'] == 0:
    print("All workers finished!")

    # Get summary of parallel work
    summary = agent.get_parallel_summary()

    print(f"Completed {summary['total_completed']} tasks")
    print(f"Branches to merge: {summary['branches_to_merge']}")

    # For each branch, review and merge
    for branch in summary['branches_to_merge']:
        tasks = summary['branches'][branch]
        print(f"\nBranch: {branch}")
        for t in tasks:
            print(f"  - {t['id']}: {t['title']}")
            # Show recent notes for context
            for note in t['notes']:
                print(f"    → {note['note']}")

    # After merging, stop parallel mode
    agent.stop_parallel_mode()
```

---

## Communication Protocol

### Main → Workers

Main session communicates by:
1. Creating tasks with specific labels
2. Setting priorities to control order
3. Task descriptions contain instructions

### Workers → Main

Workers communicate by:
1. Task completion notes (detailed)
2. Branch names reference task IDs
3. Creating follow-up tasks for issues found

### Example Flow

```
MAIN SESSION:
1. Creates tasks:
   - task-001: "Build auth API" [backend, auth] P1
   - task-002: "Create login page" [frontend, auth] P1
   - task-003: "Add user table" [database, auth] P1

2. Starts parallel mode
3. Tells user to open worker terminals

WORKER 1 (backend specialist):
1. Detects parallel mode
2. Registers with labels=["backend"]
3. Gets task-001 (matched by labels)
4. Creates branch: worker/abc123/task-001
5. Implements, commits
6. Completes with note: "JWT auth implemented. Endpoints: /login, /logout, /refresh"

WORKER 2 (frontend specialist):
1. Detects parallel mode
2. Registers with labels=["frontend"]
3. Gets task-002
4. Creates branch: worker/def456/task-002
5. Implements, commits
6. Completes with note: "Login page done. Uses /login endpoint. Needs task-001 merged first."

MAIN SESSION:
1. Sees workers finished
2. Gets summary
3. Merges worker/abc123/task-001 to main
4. Merges worker/def456/task-002 to main
5. Runs integration tests
6. Stops parallel mode
```

---

## Task Schema

```json
{
  "id": "task-001",
  "title": "Short description",
  "description": "Detailed instructions",
  "status": "open",           // open | in_progress | done | blocked
  "priority": 1,              // 0=critical, 1=high, 2=medium, 3=low
  "blocked_by": [],           // Task IDs that must complete first
  "assignee": null,           // Session ID when claimed
  "labels": ["backend"],      // For routing to specialized workers
  "branch": null,             // Git branch where work was done
  "created_at": "ISO-8601",
  "updated_at": "ISO-8601",
  "notes": [
    {
      "timestamp": "ISO-8601",
      "session_id": "abc123",
      "note": "Progress update or completion note"
    }
  ]
}
```

---

## CLI Quick Reference

```bash
# Check status
claudia status

# List and search tasks
claudia tasks
claudia tasks --status open
claudia tasks --search "auth"           # Search by title/description

# View task details
claudia show task-001                   # Full task view with history

# Create task
claudia create "Fix bug" -p 1 -l bug backend

# Get next task (claims it)
claudia next --labels backend

# Complete task
claudia complete task-001 --note "Fixed the bug"

# Reopen a completed task (undo)
claudia reopen task-001 --note "Needs revision"

# Start parallel mode (main session)
claudia start-parallel --port 8765

# Stop parallel mode
claudia stop-parallel

# View sessions
claudia session                         # List all sessions
claudia session abc123                  # View specific session

# Global flags
claudia --json tasks                    # JSON output for scripting
claudia --dry-run complete task-001     # Preview without executing
claudia --verbose status                # Show detailed errors
```

---

## Git Workflow for Parallel Mode

### Workers create branches:
```bash
git checkout -b worker/{session_id}/{task_id}
# ... do work ...
git add .
git commit -m "{task_id}: {description}"
git push origin worker/{session_id}/{task_id}
```

### Main session merges:
```bash
# After all workers done
git checkout main
git pull

# For each worker branch
git merge worker/abc123/task-001 --no-ff -m "Merge task-001: Auth API"
git merge worker/def456/task-002 --no-ff -m "Merge task-002: Login page"

# Run tests
make test

# Push
git push origin main

# Cleanup
git branch -d worker/abc123/task-001
git branch -d worker/def456/task-002
```

---

## Session Lifecycle Summary

### Single Session
```
START → register() → get_next_task() → work → complete_task() → ... → end_session()
```

### Parallel Mode (Main)
```
START → register(role="main") → analyze_work() → start_parallel_mode()
      → tell_user_to_open_workers → work_on_own_tasks
      → wait_for_workers → get_parallel_summary() → merge_branches
      → stop_parallel_mode() → end_session()
```

### Parallel Mode (Worker)
```
START → detect_parallel_mode → register(role="worker")
      → get_next_task() → create_branch → work → complete_task(branch=...)
      → ... → end_session()
```

---

## Suggested Parallel Mode Prompt

When suggesting parallelism to the user:

```
I've analyzed the work and found {N} independent task streams:

1. **{Domain 1}** ({count} tasks): {brief description}
2. **{Domain 2}** ({count} tasks): {brief description}
3. **{Domain 3}** ({count} tasks): {brief description}

I can handle {Domain 1}. Would you like to spin up parallel sessions for the others?

If yes:
1. I'll start the coordinator
2. Open {N-1} new terminal tabs
3. Run `claude` in each - they'll auto-connect and start working

The work will complete faster and I'll merge everything when done.
```
