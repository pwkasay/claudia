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

    async def request_task(
        self,
        session_id: str,
        preferred_labels: list[str] = None,
    ) -> Optional[Task]:
        """Atomically assign the best available task to a session."""
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

            def score_task(task: Task) -> tuple:
                priority_score = task.priority
                label_score = 0
                if preferred_labels:
                    matching = set(task.labels) & set(preferred_labels)
                    label_score = -len(matching)
                return (priority_score, label_score, task.created_at)

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
    ) -> Optional[Task]:
        async with self.state._lock:
            if task_id not in self.state.tasks:
                return None

            task = self.state.tasks[task_id]
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
        return task

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
            task = await coordinator.complete_task(
                task_id=data['task_id'],
                session_id=data['session_id'],
                completion_note=data.get('note', ''),
                branch=data.get('branch'),
            )
            if task:
                return {'success': True, 'task': task.to_dict()}, 200
            return {'success': False, 'error': 'Task not found'}, 404

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
