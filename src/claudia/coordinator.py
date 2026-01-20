#!/usr/bin/env python3
"""
Agent Coordinator

A lightweight coordination server for multi-session Claude Code workflows.

Only runs when parallel mode is active. In single-session mode, Claude Code
reads/writes tasks.json directly without this server.

Features:
- Atomic task claiming (prevents race conditions)
- Session tracking with heartbeats
- Stale session recovery
- Branch-per-session workflow support
- Auto-shutdown when only main session remains

Usage:
    python coordinator.py                    # Start on default port
    python coordinator.py --port 8765        # Custom port
    python coordinator.py --state ./tasks.json
"""

import asyncio
import json
import logging
import os
import signal
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Optional
import argparse

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


# ============================================================================
# Data Models
# ============================================================================

# Maximum number of notes to keep per task (prevents unbounded growth)
MAX_NOTES_PER_TASK = 50


class TaskStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"


@dataclass
class Task:
    id: str
    title: str
    description: str = ""
    status: TaskStatus = TaskStatus.OPEN
    priority: int = 2
    blocked_by: list[str] = field(default_factory=list)
    assignee: Optional[str] = None
    labels: list[str] = field(default_factory=list)
    branch: Optional[str] = None  # Git branch for this task's work
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat() + 'Z')
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat() + 'Z')
    notes: list[dict] = field(default_factory=list)
    # v2 fields for subtasks and time tracking
    parent_id: Optional[str] = None  # ID of parent task (for subtasks)
    subtasks: list[str] = field(default_factory=list)  # List of subtask IDs
    is_subtask: bool = False  # Quick filter flag
    time_tracking: Optional[dict] = None  # Timer data: {started_at, paused_at, total_seconds}

    def to_dict(self) -> dict:
        # Truncate notes to prevent unbounded growth (keep most recent)
        truncated_notes = self.notes[-MAX_NOTES_PER_TASK:] if len(self.notes) > MAX_NOTES_PER_TASK else self.notes
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'status': self.status.value if isinstance(self.status, TaskStatus) else self.status,
            'priority': self.priority,
            'blocked_by': self.blocked_by,
            'assignee': self.assignee,
            'labels': self.labels,
            'branch': self.branch,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'notes': truncated_notes,
            # v2 fields
            'parent_id': self.parent_id,
            'subtasks': self.subtasks,
            'is_subtask': self.is_subtask,
            'time_tracking': self.time_tracking,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Task':
        status = data.get('status', 'open')
        if isinstance(status, str):
            try:
                status = TaskStatus(status)
            except ValueError:
                status = TaskStatus.OPEN
        return cls(
            id=data['id'],
            title=data['title'],
            description=data.get('description', ''),
            status=status,
            priority=data.get('priority', 2),
            blocked_by=data.get('blocked_by', []),
            assignee=data.get('assignee'),
            labels=data.get('labels', []),
            branch=data.get('branch'),
            created_at=data.get('created_at', datetime.now(timezone.utc).isoformat() + 'Z'),
            updated_at=data.get('updated_at', datetime.now(timezone.utc).isoformat() + 'Z'),
            notes=data.get('notes', []),
            # v2 fields with defaults for backward compatibility
            parent_id=data.get('parent_id'),
            subtasks=data.get('subtasks', []),
            is_subtask=data.get('is_subtask', False),
            time_tracking=data.get('time_tracking'),
        )


@dataclass 
class Session:
    session_id: str
    role: str = "worker"  # "main" or "worker"
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat() + 'Z')
    last_heartbeat: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat() + 'Z')
    working_on: list[str] = field(default_factory=list)
    status: str = "active"
    context: str = ""
    labels: list[str] = field(default_factory=list)
    branch: Optional[str] = None  # Current git branch

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'Session':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ============================================================================
# Coordinator State
# ============================================================================

class CoordinatorState:
    def __init__(self, state_file: Path):
        self.state_file = state_file
        self.tasks: dict[str, Task] = {}
        self.sessions: dict[str, Session] = {}
        self.next_id: int = 1
        self.version: int = 1
        self._lock = asyncio.Lock()
        self._subscribers: list[asyncio.Queue] = []

    def _recover_tmp_file(self) -> bool:
        """Check for and recover from orphaned .tmp file. Returns True if recovery occurred."""
        tmp_file = self.state_file.with_suffix('.tmp')

        if not tmp_file.exists():
            return False

        # If main file doesn't exist, definitely use tmp
        if not self.state_file.exists():
            logger.warning(f"Recovering from orphaned tmp file: {tmp_file}")
            tmp_file.rename(self.state_file)
            return True

        # Both exist - use the newer one
        tmp_mtime = tmp_file.stat().st_mtime
        main_mtime = self.state_file.stat().st_mtime

        if tmp_mtime > main_mtime:
            # tmp is newer, validate it before using
            try:
                with open(tmp_file) as f:
                    json.load(f)  # Validate JSON
                logger.warning(f"Recovering from newer tmp file: {tmp_file}")
                tmp_file.rename(self.state_file)
                return True
            except (json.JSONDecodeError, OSError) as e:
                # tmp file is corrupt, delete it
                logger.warning(f"Corrupt tmp file, removing: {e}")
                tmp_file.unlink()
                return False
        else:
            # Main file is newer or same age, remove stale tmp
            logger.info(f"Removing stale tmp file: {tmp_file}")
            tmp_file.unlink()
            return False

    def _load_sync(self) -> dict:
        """Synchronous file load - run in thread pool to avoid blocking event loop."""
        # First check for orphaned tmp files from crash recovery
        self._recover_tmp_file()

        with open(self.state_file) as f:
            return json.load(f)

    def _save_sync(self, data: dict):
        """Synchronous file save - run in thread pool to avoid blocking event loop."""
        tmp_file = self.state_file.with_suffix('.tmp')
        with open(tmp_file, 'w') as f:
            json.dump(data, f, indent=2)
        tmp_file.rename(self.state_file)

    async def load(self):
        if self.state_file.exists():
            async with self._lock:
                # Run file I/O in thread pool to avoid blocking event loop
                data = await asyncio.to_thread(self._load_sync)
                self.version = data.get('version', 1)
                self.next_id = data.get('next_id', 1)
                self.tasks = {
                    t['id']: Task.from_dict(t)
                    for t in data.get('tasks', [])
                }
            logger.info(f"Loaded {len(self.tasks)} tasks from {self.state_file}")

    async def save(self):
        async with self._lock:
            data = {
                'version': self.version,
                'next_id': self.next_id,
                'tasks': [t.to_dict() for t in self.tasks.values()],
            }
            # Run file I/O in thread pool to avoid blocking event loop
            await asyncio.to_thread(self._save_sync, data)

    def subscribe(self) -> asyncio.Queue:
        queue = asyncio.Queue(maxsize=100)  # Limit queue size to prevent memory bloat
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue):
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    async def broadcast(self, event: dict):
        event['timestamp'] = datetime.now(timezone.utc).isoformat() + 'Z'
        dead_queues = []
        for queue in self._subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                dead_queues.append(queue)  # Queue full = subscriber not consuming
        # Clean up unresponsive subscribers to prevent memory leak
        for q in dead_queues:
            self._subscribers.remove(q)


# ============================================================================
# Coordinator Logic
# ============================================================================

class Coordinator:
    def __init__(self, state: CoordinatorState, auto_shutdown: bool = True):
        self.state = state
        self.stale_threshold = timedelta(minutes=10)
        self.auto_shutdown = auto_shutdown
        self._shutdown_event = asyncio.Event()

    async def register_session(
        self,
        session_id: Optional[str] = None,
        role: str = "worker",
        context: str = "",
        labels: list[str] = None,
        branch: Optional[str] = None,
    ) -> Session:
        async with self.state._lock:
            if session_id is None:
                import uuid
                session_id = str(uuid.uuid4())[:8]

            session = Session(
                session_id=session_id,
                role=role,
                context=context,
                labels=labels or [],
                branch=branch,
            )
            self.state.sessions[session_id] = session

        await self.state.broadcast({
            'event': 'session_registered',
            'session_id': session_id,
            'role': role,
        })

        logger.info(f"Session {session_id} registered as {role}")
        return session

    async def heartbeat(self, session_id: str) -> bool:
        async with self.state._lock:
            if session_id not in self.state.sessions:
                return False
            self.state.sessions[session_id].last_heartbeat = datetime.now(timezone.utc).isoformat() + 'Z'
        return True

    async def end_session(self, session_id: str, release_tasks: bool = True):
        async with self.state._lock:
            if session_id not in self.state.sessions:
                return

            session = self.state.sessions[session_id]
            was_worker = session.role == "worker"

            if release_tasks:
                for task in self.state.tasks.values():
                    if task.assignee == session_id:
                        task.assignee = None
                        task.status = TaskStatus.OPEN
                        task.updated_at = datetime.now(timezone.utc).isoformat() + 'Z'
                        task.notes.append({
                            'timestamp': datetime.now(timezone.utc).isoformat() + 'Z',
                            'session_id': session_id,
                            'note': 'Released on session end',
                        })

            del self.state.sessions[session_id]

        await self.state.broadcast({
            'event': 'session_ended',
            'session_id': session_id,
        })
        await self.state.save()
        logger.info(f"Session {session_id} ended")

        # Check if we should auto-shutdown (only main session left)
        if self.auto_shutdown and was_worker:
            await self._check_auto_shutdown()

    async def _check_auto_shutdown(self):
        """Shutdown coordinator if only main session remains."""
        async with self.state._lock:
            workers = [s for s in self.state.sessions.values() if s.role == "worker"]
            if len(workers) == 0:
                logger.info("All workers finished. Signaling main session.")
                await self.state.broadcast({
                    'event': 'parallel_complete',
                    'message': 'All worker sessions have finished',
                })

    async def cleanup_stale_sessions(self) -> list[str]:
        now = datetime.now(timezone.utc)
        stale_ids = []

        async with self.state._lock:
            for session_id, session in list(self.state.sessions.items()):
                last_hb = datetime.fromisoformat(session.last_heartbeat.replace('Z', ''))
                if now - last_hb > self.stale_threshold:
                    stale_ids.append(session_id)

        for session_id in stale_ids:
            logger.warning(f"Cleaning up stale session: {session_id}")
            await self.end_session(session_id, release_tasks=True)

        return stale_ids

    async def create_task(
        self,
        title: str,
        description: str = "",
        priority: int = 2,
        blocked_by: list[str] = None,
        labels: list[str] = None,
        branch: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Task:
        async with self.state._lock:
            task_id = f"task-{self.state.next_id:03d}"
            self.state.next_id += 1

            task = Task(
                id=task_id,
                title=title,
                description=description,
                priority=priority,
                blocked_by=blocked_by or [],
                labels=labels or [],
                branch=branch,
            )

            if session_id:
                task.notes.append({
                    'timestamp': datetime.now(timezone.utc).isoformat() + 'Z',
                    'session_id': session_id,
                    'note': 'Created task',
                })

            self.state.tasks[task_id] = task

        await self.state.broadcast({
            'event': 'task_created',
            'task_id': task_id,
            'title': title,
        })
        await self.state.save()
        logger.info(f"Task {task_id} created: {title}")
        return task

    def _calculate_session_affinity(self, session_id: str, task: 'Task') -> float:
        """
        Calculate affinity score between a session and a task.

        Higher scores = better fit. Considers:
        - Label overlap with session's preferred labels
        - Historical completions with matching labels
        """
        affinity = 0.0

        session = self.state.sessions.get(session_id)
        if not session:
            return affinity

        # Bonus for label match with session preferences
        if session.preferred_labels and task.labels:
            matching = set(task.labels) & set(session.preferred_labels)
            affinity += len(matching) * 2.0

        # Bonus for completing similar tasks before (from history)
        # Check session's completed tasks for label overlap
        for other_task in self.state.tasks.values():
            if other_task.status == TaskStatus.DONE:
                # Check if this session completed it (via notes)
                for note in other_task.notes:
                    if note.get('session_id') == session_id and 'Completed' in note.get('note', ''):
                        # Label match with completed task
                        if task.labels and other_task.labels:
                            overlap = set(task.labels) & set(other_task.labels)
                            affinity += len(overlap) * 0.5
                        break

        return affinity

    def _get_session_load(self, session_id: str) -> int:
        """Get number of tasks currently assigned to a session."""
        session = self.state.sessions.get(session_id)
        if session:
            return len(session.working_on)
        return 0

    async def request_task(
        self,
        session_id: str,
        preferred_labels: list[str] = None,
    ) -> Optional[Task]:
        """
        Atomically assign the best available task to a session.

        Uses smart assignment with:
        - Affinity scoring (label match, historical completions)
        - Load balancing (prefer less busy sessions)
        """
        async with self.state._lock:
            ready_tasks = []
            for task in self.state.tasks.values():
                if task.status != TaskStatus.OPEN:
                    continue
                if task.assignee is not None:
                    continue

                blocked = False
                for blocker_id in task.blocked_by:
                    blocker = self.state.tasks.get(blocker_id)
                    if blocker and blocker.status != TaskStatus.DONE:
                        blocked = True
                        break
                if blocked:
                    continue

                ready_tasks.append(task)

            if not ready_tasks:
                return None

            # Get session load for load balancing
            session_load = self._get_session_load(session_id)

            def score_task(task: Task) -> tuple:
                # Priority is most important (lower = higher priority)
                priority_score = task.priority

                # Affinity scoring (negative = better, for sorting)
                affinity = self._calculate_session_affinity(session_id, task)
                affinity_score = -affinity

                # Preferred labels bonus
                label_score = 0
                if preferred_labels:
                    matching = set(task.labels) & set(preferred_labels)
                    label_score = -len(matching) * 3  # Strong preference

                # Load balancing: if session is busy, prefer simpler tasks
                load_penalty = session_load * 0.5 if task.subtasks else 0

                return (priority_score, label_score, affinity_score, load_penalty, task.created_at)

            ready_tasks.sort(key=score_task)
            best_task = ready_tasks[0]

            # Claim it
            best_task.assignee = session_id
            best_task.status = TaskStatus.IN_PROGRESS
            best_task.updated_at = datetime.now(timezone.utc).isoformat() + 'Z'
            best_task.notes.append({
                'timestamp': datetime.now(timezone.utc).isoformat() + 'Z',
                'session_id': session_id,
                'note': 'Claimed task',
            })

            if session_id in self.state.sessions:
                self.state.sessions[session_id].working_on.append(best_task.id)

        await self.state.broadcast({
            'event': 'task_claimed',
            'task_id': best_task.id,
            'session_id': session_id,
        })
        await self.state.save()
        logger.info(f"Task {best_task.id} claimed by {session_id}")
        return best_task

    async def complete_task(
        self,
        task_id: str,
        session_id: str,
        completion_note: str = "",
        branch: Optional[str] = None,
        force: bool = False,
    ) -> dict:
        """
        Complete a task, checking for incomplete subtasks.

        Returns:
            Dict with 'success', optionally 'task', 'error', 'incomplete_subtasks'
        """
        async with self.state._lock:
            if task_id not in self.state.tasks:
                return {'success': False, 'error': 'Task not found'}

            task = self.state.tasks[task_id]

            # Check for incomplete subtasks
            if task.subtasks and not force:
                incomplete = []
                for sid in task.subtasks:
                    subtask = self.state.tasks.get(sid)
                    if subtask and subtask.status != TaskStatus.DONE:
                        status_val = subtask.status.value if isinstance(subtask.status, TaskStatus) else subtask.status
                        incomplete.append({
                            'id': sid,
                            'title': subtask.title,
                            'status': status_val,
                        })

                if incomplete:
                    return {
                        'success': False,
                        'error': 'incomplete_subtasks',
                        'incomplete_subtasks': incomplete,
                        'message': f'{len(incomplete)} subtask(s) not complete',
                    }

            task.status = TaskStatus.DONE
            task.assignee = None
            task.updated_at = datetime.now(timezone.utc).isoformat() + 'Z'
            if branch:
                task.branch = branch

            if completion_note:
                task.notes.append({
                    'timestamp': datetime.now(timezone.utc).isoformat() + 'Z',
                    'session_id': session_id,
                    'note': f'Completed: {completion_note}',
                })

            if session_id in self.state.sessions:
                session = self.state.sessions[session_id]
                if task_id in session.working_on:
                    session.working_on.remove(task_id)

        await self.state.broadcast({
            'event': 'task_completed',
            'task_id': task_id,
            'session_id': session_id,
            'branch': branch,
        })
        await self.state.save()
        logger.info(f"Task {task_id} completed by {session_id}")
        return {'success': True, 'task': task.to_dict()}

    async def add_note(self, task_id: str, session_id: str, note: str) -> bool:
        async with self.state._lock:
            if task_id not in self.state.tasks:
                return False
            task = self.state.tasks[task_id]
            task.notes.append({
                'timestamp': datetime.now(timezone.utc).isoformat() + 'Z',
                'session_id': session_id,
                'note': note,
            })
            task.updated_at = datetime.now(timezone.utc).isoformat() + 'Z'

        await self.state.save()
        return True

    async def reopen_task(
        self,
        task_id: str,
        session_id: str,
        note: str = "",
    ) -> Optional[Task]:
        """Reopen a completed or blocked task."""
        async with self.state._lock:
            if task_id not in self.state.tasks:
                return None

            task = self.state.tasks[task_id]
            old_status = task.status.value if isinstance(task.status, TaskStatus) else task.status
            task.status = TaskStatus.OPEN
            task.assignee = None
            task.updated_at = datetime.now(timezone.utc).isoformat() + 'Z'

            note_text = f'Reopened (was {old_status})'
            if note:
                note_text += f': {note}'
            task.notes.append({
                'timestamp': datetime.now(timezone.utc).isoformat() + 'Z',
                'session_id': session_id,
                'note': note_text,
            })

        await self.state.broadcast({
            'event': 'task_reopened',
            'task_id': task_id,
            'session_id': session_id,
        })
        await self.state.save()
        logger.info(f"Task {task_id} reopened by {session_id}")
        return task

    async def bulk_complete_tasks(
        self,
        task_ids: list[str],
        session_id: str,
        completion_note: str = "",
        branch: Optional[str] = None,
        force: bool = False,
    ) -> dict:
        """
        Complete multiple tasks at once.

        Returns:
            Dict with 'succeeded' list, 'failed' list (with reasons), and 'total' counts
        """
        succeeded = []
        failed = []

        async with self.state._lock:
            for task_id in task_ids:
                if task_id not in self.state.tasks:
                    failed.append({'id': task_id, 'error': 'Task not found'})
                    continue

                task = self.state.tasks[task_id]

                # Check for incomplete subtasks
                if task.subtasks and not force:
                    incomplete = []
                    for sid in task.subtasks:
                        subtask = self.state.tasks.get(sid)
                        if subtask and subtask.status != TaskStatus.DONE:
                            status_val = subtask.status.value if isinstance(subtask.status, TaskStatus) else subtask.status
                            incomplete.append({
                                'id': sid,
                                'title': subtask.title,
                                'status': status_val,
                            })

                    if incomplete:
                        failed.append({
                            'id': task_id,
                            'error': 'incomplete_subtasks',
                            'incomplete_subtasks': incomplete,
                        })
                        continue

                task.status = TaskStatus.DONE
                task.assignee = None
                task.updated_at = datetime.now(timezone.utc).isoformat() + 'Z'
                if branch:
                    task.branch = branch

                if completion_note:
                    task.notes.append({
                        'timestamp': datetime.now(timezone.utc).isoformat() + 'Z',
                        'session_id': session_id,
                        'note': f'Completed: {completion_note}',
                    })
                else:
                    task.notes.append({
                        'timestamp': datetime.now(timezone.utc).isoformat() + 'Z',
                        'session_id': session_id,
                        'note': 'Completed (bulk)',
                    })

                if session_id in self.state.sessions:
                    session = self.state.sessions[session_id]
                    if task_id in session.working_on:
                        session.working_on.remove(task_id)

                succeeded.append(task_id)

        if succeeded:
            await self.state.broadcast({
                'event': 'tasks_bulk_completed',
                'task_ids': succeeded,
                'session_id': session_id,
                'count': len(succeeded),
            })
            await self.state.save()
            logger.info(f"{len(succeeded)} task(s) bulk completed by {session_id}")

        return {
            'succeeded': succeeded,
            'failed': failed,
            'total_succeeded': len(succeeded),
            'total_failed': len(failed),
        }

    async def bulk_reopen_tasks(
        self,
        task_ids: list[str],
        session_id: str,
        note: str = "",
    ) -> dict:
        """
        Reopen multiple tasks at once.

        Returns:
            Dict with 'succeeded' list, 'failed' list (with reasons), and 'total' counts
        """
        succeeded = []
        failed = []

        async with self.state._lock:
            for task_id in task_ids:
                if task_id not in self.state.tasks:
                    failed.append({'id': task_id, 'error': 'Task not found'})
                    continue

                task = self.state.tasks[task_id]
                old_status = task.status.value if isinstance(task.status, TaskStatus) else task.status

                if old_status == 'open':
                    failed.append({'id': task_id, 'error': 'Task is already open'})
                    continue

                task.status = TaskStatus.OPEN
                task.assignee = None
                task.updated_at = datetime.now(timezone.utc).isoformat() + 'Z'

                note_text = f'Reopened (was {old_status})'
                if note:
                    note_text += f': {note}'
                task.notes.append({
                    'timestamp': datetime.now(timezone.utc).isoformat() + 'Z',
                    'session_id': session_id,
                    'note': note_text,
                })

                succeeded.append(task_id)

        if succeeded:
            await self.state.broadcast({
                'event': 'tasks_bulk_reopened',
                'task_ids': succeeded,
                'session_id': session_id,
                'count': len(succeeded),
            })
            await self.state.save()
            logger.info(f"{len(succeeded)} task(s) bulk reopened by {session_id}")

        return {
            'succeeded': succeeded,
            'failed': failed,
            'total_succeeded': len(succeeded),
            'total_failed': len(failed),
        }

    async def create_subtask(
        self,
        parent_id: str,
        title: str,
        description: str = "",
        priority: int = None,
        labels: list[str] = None,
        session_id: Optional[str] = None,
    ) -> Optional[Task]:
        """Create a subtask under a parent task."""
        async with self.state._lock:
            if parent_id not in self.state.tasks:
                return None

            parent = self.state.tasks[parent_id]

            task_id = f"task-{self.state.next_id:03d}"
            self.state.next_id += 1

            # Inherit priority and labels from parent if not specified
            subtask = Task(
                id=task_id,
                title=title,
                description=description,
                priority=priority if priority is not None else parent.priority,
                labels=labels if labels is not None else parent.labels.copy(),
                branch=parent.branch,
                parent_id=parent_id,
                is_subtask=True,
            )

            if session_id:
                subtask.notes.append({
                    'timestamp': datetime.now(timezone.utc).isoformat() + 'Z',
                    'session_id': session_id,
                    'note': f'Created as subtask of {parent_id}',
                })

            # Add to parent's subtask list
            parent.subtasks.append(task_id)
            parent.updated_at = datetime.now(timezone.utc).isoformat() + 'Z'

            self.state.tasks[task_id] = subtask

        await self.state.broadcast({
            'event': 'subtask_created',
            'task_id': task_id,
            'parent_id': parent_id,
            'title': title,
        })
        await self.state.save()
        logger.info(f"Subtask {task_id} created under {parent_id}: {title}")
        return subtask

    async def get_subtask_progress(self, task_id: str) -> Optional[dict]:
        """Get progress of a task's subtasks."""
        async with self.state._lock:
            if task_id not in self.state.tasks:
                return None

            task = self.state.tasks[task_id]
            subtask_ids = task.subtasks

            if not subtask_ids:
                return {
                    'total': 0,
                    'completed': 0,
                    'in_progress': 0,
                    'open': 0,
                    'blocked': 0,
                    'percentage': 100,
                }

            counts = {'open': 0, 'in_progress': 0, 'done': 0, 'blocked': 0}
            for sid in subtask_ids:
                subtask = self.state.tasks.get(sid)
                if subtask:
                    status = subtask.status.value if isinstance(subtask.status, TaskStatus) else subtask.status
                    counts[status] = counts.get(status, 0) + 1

            total = len(subtask_ids)
            completed = counts.get('done', 0)

            return {
                'total': total,
                'completed': completed,
                'in_progress': counts.get('in_progress', 0),
                'open': counts.get('open', 0),
                'blocked': counts.get('blocked', 0),
                'percentage': round((completed / total) * 100) if total > 0 else 100,
            }

    async def get_subtasks(self, task_id: str) -> list[dict]:
        """Get all subtasks for a task."""
        async with self.state._lock:
            if task_id not in self.state.tasks:
                return []

            task = self.state.tasks[task_id]
            subtasks = []
            for sid in task.subtasks:
                subtask = self.state.tasks.get(sid)
                if subtask:
                    subtasks.append(subtask.to_dict())

            return subtasks

    async def edit_task(
        self,
        task_id: str,
        session_id: str,
        title: str = None,
        description: str = None,
        priority: int = None,
        labels: list[str] = None,
    ) -> Optional[Task]:
        """Edit a task's properties."""
        async with self.state._lock:
            if task_id not in self.state.tasks:
                return None

            task = self.state.tasks[task_id]
            changes = []

            if title is not None and title != task.title:
                task.title = title
                changes.append("title")

            if description is not None and description != task.description:
                task.description = description
                changes.append("description")

            if priority is not None and priority != task.priority:
                task.priority = priority
                changes.append(f"priority to P{priority}")

            if labels is not None and labels != task.labels:
                task.labels = labels
                changes.append("labels")

            if changes:
                task.updated_at = datetime.now(timezone.utc).isoformat() + 'Z'
                task.notes.append({
                    'timestamp': datetime.now(timezone.utc).isoformat() + 'Z',
                    'session_id': session_id,
                    'note': f'Edited: {", ".join(changes)}',
                })

        if changes:
            await self.state.broadcast({
                'event': 'task_edited',
                'task_id': task_id,
                'session_id': session_id,
                'changes': changes,
            })
            await self.state.save()
            logger.info(f"Task {task_id} edited by {session_id}: {', '.join(changes)}")

        return task

    async def delete_task(
        self,
        task_id: str,
        session_id: str,
        force: bool = False,
    ) -> dict:
        """Delete a task."""
        async with self.state._lock:
            if task_id not in self.state.tasks:
                return {'success': False, 'error': 'Task not found'}

            task = self.state.tasks[task_id]

            # Check for subtasks
            if task.subtasks and not force:
                return {
                    'success': False,
                    'error': 'has_subtasks',
                    'subtasks': task.subtasks,
                    'message': f'Task has {len(task.subtasks)} subtask(s). Use --force to delete.',
                }

            deleted_subtasks = []

            # Remove from parent's subtask list if this is a subtask
            if task.parent_id and task.parent_id in self.state.tasks:
                parent = self.state.tasks[task.parent_id]
                if task_id in parent.subtasks:
                    parent.subtasks.remove(task_id)
                    parent.updated_at = datetime.now(timezone.utc).isoformat() + 'Z'

            # Delete subtasks if force
            if task.subtasks and force:
                for sid in task.subtasks:
                    if sid in self.state.tasks:
                        del self.state.tasks[sid]
                        deleted_subtasks.append(sid)

            # Delete the task
            del self.state.tasks[task_id]

        await self.state.broadcast({
            'event': 'task_deleted',
            'task_id': task_id,
            'session_id': session_id,
        })
        await self.state.save()
        logger.info(f"Task {task_id} deleted by {session_id}")

        return {'success': True, 'deleted_subtasks': deleted_subtasks}

    async def get_status(self) -> dict:
        async with self.state._lock:
            tasks_by_status = {}
            for task in self.state.tasks.values():
                status = task.status.value if isinstance(task.status, TaskStatus) else task.status
                tasks_by_status[status] = tasks_by_status.get(status, 0) + 1

            ready_count = 0
            for task in self.state.tasks.values():
                if task.status != TaskStatus.OPEN or task.assignee is not None:
                    continue
                blocked = False
                for blocker_id in task.blocked_by:
                    blocker = self.state.tasks.get(blocker_id)
                    if blocker and blocker.status != TaskStatus.DONE:
                        blocked = True
                        break
                if not blocked:
                    ready_count += 1

            # Separate main and worker sessions
            main_session = None
            worker_sessions = {}
            for sid, s in self.state.sessions.items():
                if s.role == "main":
                    main_session = {
                        'session_id': sid,
                        'working_on': s.working_on,
                        'context': s.context,
                        'last_heartbeat': s.last_heartbeat,
                    }
                else:
                    worker_sessions[sid] = {
                        'working_on': s.working_on,
                        'context': s.context,
                        'labels': s.labels,
                        'branch': s.branch,
                        'last_heartbeat': s.last_heartbeat,
                    }

            # Get completed tasks with branches (for merge summary)
            completed_with_branches = [
                {'id': t.id, 'title': t.title, 'branch': t.branch}
                for t in self.state.tasks.values()
                if t.status == TaskStatus.DONE and t.branch
            ]

            return {
                'total_tasks': len(self.state.tasks),
                'tasks_by_status': tasks_by_status,
                'ready_tasks': ready_count,
                'main_session': main_session,
                'worker_sessions': worker_sessions,
                'active_workers': len(worker_sessions),
                'completed_with_branches': completed_with_branches,
            }

    async def get_tasks(self, status: Optional[str] = None) -> list[dict]:
        async with self.state._lock:
            tasks = list(self.state.tasks.values())
            if status:
                tasks = [t for t in tasks if (t.status.value if isinstance(t.status, TaskStatus) else t.status) == status]
            return [t.to_dict() for t in tasks]

    async def get_parallel_summary(self) -> dict:
        """Get summary of parallel work for merge phase."""
        async with self.state._lock:
            completed_tasks = [
                t for t in self.state.tasks.values()
                if t.status == TaskStatus.DONE
            ]

            # Group by branch
            by_branch = {}
            for task in completed_tasks:
                branch = task.branch or 'main'
                if branch not in by_branch:
                    by_branch[branch] = []
                by_branch[branch].append({
                    'id': task.id,
                    'title': task.title,
                    'notes': task.notes[-3:] if task.notes else [],  # Last 3 notes
                })

            return {
                'total_completed': len(completed_tasks),
                'branches': by_branch,
                'branches_to_merge': [b for b in by_branch.keys() if b != 'main'],
            }


# ============================================================================
# HTTP Server
# ============================================================================

MAX_CONTENT_LENGTH = 1_000_000  # 1MB limit to prevent memory exhaustion

HTTP_STATUS_TEXT = {
    200: "OK",
    400: "Bad Request",
    404: "Not Found",
    413: "Payload Too Large",
    422: "Unprocessable Entity",
    500: "Internal Server Error",
}


def _send_error(writer: asyncio.StreamWriter, status_code: int, message: str = "") -> bytes:
    """Helper to create error response."""
    body = json.dumps({'error': message or HTTP_STATUS_TEXT.get(status_code, "Error")})
    return (
        f"HTTP/1.1 {status_code} {HTTP_STATUS_TEXT.get(status_code, 'Error')}\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"\r\n"
        f"{body}"
    ).encode()


async def handle_request(coordinator: Coordinator, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    try:
        request_line = await reader.readline()
        if not request_line:
            return

        request_line = request_line.decode().strip()
        parts = request_line.split(' ', 2)
        if len(parts) < 2:
            writer.write(_send_error(writer, 400, "Malformed request line"))
            await writer.drain()
            return
        method, path = parts[0], parts[1]

        headers = {}
        while True:
            line = await reader.readline()
            if line == b'\r\n' or line == b'\n' or not line:
                break
            if b': ' in line:
                key, value = line.decode().strip().split(': ', 1)
                headers[key.lower()] = value

        body = b''
        if 'content-length' in headers:
            try:
                length = int(headers['content-length'])
                if length < 0 or length > MAX_CONTENT_LENGTH:
                    writer.write(_send_error(writer, 413, f"Content-Length exceeds {MAX_CONTENT_LENGTH} bytes"))
                    await writer.drain()
                    return
                body = await reader.read(length)
            except ValueError:
                writer.write(_send_error(writer, 400, "Invalid Content-Length header"))
                await writer.drain()
                return

        data = {}
        if body:
            try:
                data = json.loads(body.decode())
            except json.JSONDecodeError:
                writer.write(_send_error(writer, 400, "Invalid JSON body"))
                await writer.drain()
                return

        response_data, status_code = await route_request(coordinator, method, path, data)
        response_body = json.dumps(response_data, indent=2)

        response = (
            f"HTTP/1.1 {status_code} {HTTP_STATUS_TEXT.get(status_code, 'OK')}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(response_body)}\r\n"
            f"Access-Control-Allow-Origin: *\r\n"
            f"\r\n"
            f"{response_body}"
        )

        writer.write(response.encode())
        await writer.drain()

    except Exception as e:
        logger.error(f"Request error: {e}")
        writer.write(_send_error(writer, 500, str(e)))
        await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


async def route_request(coordinator: Coordinator, method: str, path: str, data: dict) -> tuple[dict, int]:
    """Route request to appropriate handler. Returns (response_data, status_code)."""
    try:
        if method == 'GET' and path == '/status':
            return await coordinator.get_status(), 200

        if method == 'GET' and path == '/parallel-summary':
            return await coordinator.get_parallel_summary(), 200

        if method == 'GET' and path.startswith('/tasks'):
            status = None
            if '?' in path:
                for param in path.split('?')[1].split('&'):
                    if param.startswith('status='):
                        status = param.split('=')[1]
            return {'tasks': await coordinator.get_tasks(status)}, 200

        if method == 'POST' and path == '/session/register':
            session = await coordinator.register_session(
                session_id=data.get('session_id'),
                role=data.get('role', 'worker'),
                context=data.get('context', ''),
                labels=data.get('labels', []),
                branch=data.get('branch'),
            )
            return session.to_dict(), 200

        if method == 'POST' and path == '/session/heartbeat':
            if 'session_id' not in data:
                return {'error': 'Missing required field: session_id'}, 422
            success = await coordinator.heartbeat(data['session_id'])
            return {'success': success}, 200

        if method == 'POST' and path == '/session/end':
            if 'session_id' not in data:
                return {'error': 'Missing required field: session_id'}, 422
            await coordinator.end_session(
                data['session_id'],
                release_tasks=data.get('release_tasks', True),
            )
            return {'success': True}, 200

        if method == 'POST' and path == '/task/create':
            if 'title' not in data:
                return {'error': 'Missing required field: title'}, 422
            task = await coordinator.create_task(
                title=data['title'],
                description=data.get('description', ''),
                priority=data.get('priority', 2),
                blocked_by=data.get('blocked_by', []),
                labels=data.get('labels', []),
                branch=data.get('branch'),
                session_id=data.get('session_id'),
            )
            return task.to_dict(), 200

        if method == 'POST' and path == '/task/request':
            if 'session_id' not in data:
                return {'error': 'Missing required field: session_id'}, 422
            task = await coordinator.request_task(
                session_id=data['session_id'],
                preferred_labels=data.get('preferred_labels', []),
            )
            if task:
                return {'task': task.to_dict()}, 200
            return {'task': None}, 200

        if method == 'POST' and path == '/task/complete':
            if 'task_id' not in data or 'session_id' not in data:
                return {'error': 'Missing required fields: task_id, session_id'}, 422
            result = await coordinator.complete_task(
                task_id=data['task_id'],
                session_id=data['session_id'],
                completion_note=data.get('note', ''),
                branch=data.get('branch'),
                force=data.get('force', False),
            )
            # Result is now a dict with success/error/incomplete_subtasks
            return result, 200 if result.get('success') else 400

        if method == 'POST' and path == '/task/note':
            if 'task_id' not in data or 'session_id' not in data or 'note' not in data:
                return {'error': 'Missing required fields: task_id, session_id, note'}, 422
            success = await coordinator.add_note(
                task_id=data['task_id'],
                session_id=data['session_id'],
                note=data['note'],
            )
            if success:
                return {'success': True}, 200
            return {'success': False, 'error': 'Task not found'}, 404

        if method == 'POST' and path == '/task/reopen':
            if 'task_id' not in data or 'session_id' not in data:
                return {'error': 'Missing required fields: task_id, session_id'}, 422
            task = await coordinator.reopen_task(
                task_id=data['task_id'],
                session_id=data['session_id'],
                note=data.get('note', ''),
            )
            if task:
                return {'success': True, 'task': task.to_dict()}, 200
            return {'success': False, 'error': 'Task not found'}, 404

        # Bulk operations
        if method == 'POST' and path == '/task/bulk-complete':
            if 'task_ids' not in data or 'session_id' not in data:
                return {'error': 'Missing required fields: task_ids, session_id'}, 422
            result = await coordinator.bulk_complete_tasks(
                task_ids=data['task_ids'],
                session_id=data['session_id'],
                completion_note=data.get('note', ''),
                branch=data.get('branch'),
                force=data.get('force', False),
            )
            return result, 200

        if method == 'POST' and path == '/task/bulk-reopen':
            if 'task_ids' not in data or 'session_id' not in data:
                return {'error': 'Missing required fields: task_ids, session_id'}, 422
            result = await coordinator.bulk_reopen_tasks(
                task_ids=data['task_ids'],
                session_id=data['session_id'],
                note=data.get('note', ''),
            )
            return result, 200

        # Edit and delete routes
        if method == 'POST' and path == '/task/edit':
            if 'task_id' not in data or 'session_id' not in data:
                return {'error': 'Missing required fields: task_id, session_id'}, 422
            task = await coordinator.edit_task(
                task_id=data['task_id'],
                session_id=data['session_id'],
                title=data.get('title'),
                description=data.get('description'),
                priority=data.get('priority'),
                labels=data.get('labels'),
            )
            if task:
                return {'task': task.to_dict()}, 200
            return {'error': 'Task not found'}, 404

        if method == 'POST' and path == '/task/delete':
            if 'task_id' not in data or 'session_id' not in data:
                return {'error': 'Missing required fields: task_id, session_id'}, 422
            result = await coordinator.delete_task(
                task_id=data['task_id'],
                session_id=data['session_id'],
                force=data.get('force', False),
            )
            return result, 200 if result.get('success') else 400

        # Subtask routes
        if method == 'POST' and path == '/task/create-subtask':
            if 'parent_id' not in data or 'title' not in data:
                return {'error': 'Missing required fields: parent_id, title'}, 422
            task = await coordinator.create_subtask(
                parent_id=data['parent_id'],
                title=data['title'],
                description=data.get('description', ''),
                priority=data.get('priority'),
                labels=data.get('labels'),
                session_id=data.get('session_id'),
            )
            if task:
                return {'task': task.to_dict()}, 200
            return {'error': 'Parent task not found'}, 404

        # Match /task/{task_id}/subtask-progress
        if method == 'GET' and path.startswith('/task/') and path.endswith('/subtask-progress'):
            task_id = path.split('/')[2]
            progress = await coordinator.get_subtask_progress(task_id)
            if progress is not None:
                return progress, 200
            return {'error': 'Task not found'}, 404

        # Match /task/{task_id}/subtasks
        if method == 'GET' and path.startswith('/task/') and path.endswith('/subtasks'):
            task_id = path.split('/')[2]
            subtasks = await coordinator.get_subtasks(task_id)
            return {'subtasks': subtasks}, 200

        return {'error': f'Unknown route: {method} {path}'}, 404

    except KeyError as e:
        return {'error': f'Missing required field: {e}'}, 422


async def stale_monitor(coordinator: Coordinator):
    while True:
        await asyncio.sleep(60)
        await coordinator.cleanup_stale_sessions()


async def periodic_save(state: CoordinatorState):
    while True:
        await asyncio.sleep(30)
        await state.save()


async def main(port: int, state_file: Path):
    state = CoordinatorState(state_file)
    await state.load()

    coordinator = Coordinator(state)

    asyncio.create_task(stale_monitor(coordinator))
    asyncio.create_task(periodic_save(state))

    server = await asyncio.start_server(
        lambda r, w: handle_request(coordinator, r, w),
        '127.0.0.1',
        port,
    )

    # Write PID file for management
    pid_file = state_file.parent / 'coordinator.pid'
    pid_file.write_text(str(os.getpid()))

    addr = server.sockets[0].getsockname()
    logger.info(f"Coordinator running on http://{addr[0]}:{addr[1]}")

    async with server:
        await server.serve_forever()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Agent Coordinator')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--state', type=Path, default=Path('.agent-state/tasks.json'))
    args = parser.parse_args()

    try:
        asyncio.run(main(args.port, args.state))
    except KeyboardInterrupt:
        logger.info("Shutting down...")
