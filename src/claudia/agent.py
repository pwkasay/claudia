"""
Unified Agent Client for Claudia.

Works in two modes:
1. SINGLE MODE (default): Direct JSON file access, no server needed
2. PARALLEL MODE: Connects to coordinator for atomic operations

The mode is detected automatically based on whether .agent-state/.parallel-mode exists.

Usage:
    from claudia import Agent

    agent = Agent()

    # Works the same in both modes
    task = agent.get_next_task()
    agent.complete_task(task['id'], "Done!")
"""

import json
import os
import random
import signal
import socket
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# Platform-specific file locking
try:
    import fcntl
    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False

try:
    import msvcrt
    HAS_MSVCRT = True
except ImportError:
    HAS_MSVCRT = False


class FileLock:
    """
    Cross-platform file locking for single-mode concurrent safety.

    Uses fcntl on Unix, msvcrt on Windows.
    """

    def __init__(self, lock_path: Path, timeout: float = 10.0):
        self.lock_path = lock_path
        self.timeout = timeout
        self._fd = None

    def acquire(self) -> bool:
        """
        Acquire the file lock.

        Returns:
            True if lock acquired, False if timeout
        """
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = open(self.lock_path, 'w')

        start_time = time.time()
        while True:
            try:
                if HAS_FCNTL:
                    fcntl.flock(self._fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return True
                elif HAS_MSVCRT:
                    msvcrt.locking(self._fd.fileno(), msvcrt.LK_NBLCK, 1)
                    return True
                else:
                    # No locking available, proceed without
                    return True
            except (IOError, OSError):
                if time.time() - start_time >= self.timeout:
                    self._fd.close()
                    self._fd = None
                    return False
                time.sleep(0.1)

    def release(self):
        """Release the file lock."""
        if self._fd is not None:
            try:
                if HAS_FCNTL:
                    fcntl.flock(self._fd.fileno(), fcntl.LOCK_UN)
                elif HAS_MSVCRT:
                    msvcrt.locking(self._fd.fileno(), msvcrt.LK_UNLCK, 1)
            except (IOError, OSError):
                pass
            finally:
                self._fd.close()
                self._fd = None

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError(f"Could not acquire lock on {self.lock_path} within {self.timeout}s")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False


@contextmanager
def file_lock(lock_path: Path, timeout: float = 10.0):
    """Context manager for file locking."""
    lock = FileLock(lock_path, timeout)
    if not lock.acquire():
        raise RuntimeError(f"Could not acquire lock on {lock_path} within {timeout}s")
    try:
        yield lock
    finally:
        lock.release()


def is_task_ready(task: dict, task_map: dict) -> bool:
    """
    Check if a task is ready to be worked on.

    A task is ready if:
    - Status is 'open'
    - Not assigned to anyone
    - All blocking tasks are 'done'

    Args:
        task: The task dict to check
        task_map: Dict mapping task_id -> task for dependency lookup

    Returns:
        True if task is ready, False otherwise
    """
    if task.get('status') != 'open':
        return False
    if task.get('assignee') is not None:
        return False

    for blocker_id in task.get('blocked_by', []):
        blocker = task_map.get(blocker_id)
        if blocker and blocker.get('status') != 'done':
            return False
    return True


@dataclass
class Agent:
    """
    Unified agent that works in both single-session and parallel modes.
    """

    state_dir: Path = None
    session_id: str = None
    role: str = "worker"
    context: str = ""
    labels: list = None
    _coordinator_port: int = 8765
    _parallel_mode: bool = False

    # Retry configuration for coordinator connections
    _max_retries: int = 3
    _initial_retry_delay: float = 0.5  # seconds
    _max_retry_delay: float = 8.0  # seconds
    _retry_backoff_multiplier: float = 2.0
    _retry_jitter: float = 0.25  # ±25% randomness

    def __post_init__(self):
        if self.state_dir is None:
            self.state_dir = Path('.agent-state')
        else:
            self.state_dir = Path(self.state_dir)

        if self.labels is None:
            self.labels = []

        # Generate session ID if not provided
        if self.session_id is None:
            self.session_id = str(uuid.uuid4())[:8]

        # Detect mode
        self._parallel_mode = (self.state_dir / '.parallel-mode').exists()

        if self._parallel_mode:
            # Read coordinator port from flag file
            try:
                config = json.loads((self.state_dir / '.parallel-mode').read_text())
                self._coordinator_port = config.get('port', 8765)
            except (json.JSONDecodeError, OSError, KeyError):
                pass  # Use default port 8765

    # ========================================================================
    # Mode Detection
    # ========================================================================

    def is_parallel_mode(self) -> bool:
        """Check if running in parallel mode."""
        return self._parallel_mode

    def get_mode(self) -> str:
        """Get current mode string."""
        return "parallel" if self._parallel_mode else "single"

    # ========================================================================
    # Parallel Mode: Coordinator Communication
    # ========================================================================

    def _calculate_retry_delay(self, attempt: int) -> float:
        """
        Calculate delay for retry attempt using exponential backoff with jitter.

        Args:
            attempt: Current attempt number (0-indexed)

        Returns:
            Delay in seconds before next retry
        """
        delay = self._initial_retry_delay * (self._retry_backoff_multiplier ** attempt)
        delay = min(delay, self._max_retry_delay)

        # Add jitter: ±25% randomness to prevent thundering herd
        jitter_range = delay * self._retry_jitter
        delay += random.uniform(-jitter_range, jitter_range)

        return max(0.1, delay)  # Minimum 100ms delay

    def _request(self, method: str, path: str, data: dict = None) -> dict:
        """
        Make HTTP request to coordinator with retry logic.

        Implements exponential backoff for transient connection failures.
        """
        if not self._parallel_mode:
            raise RuntimeError("Not in parallel mode")

        body = json.dumps(data) if data else ""
        request = (
            f"{method} {path} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{self._coordinator_port}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"\r\n"
            f"{body}"
        )

        last_error = None

        for attempt in range(self._max_retries + 1):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(10.0)
                    sock.connect(('127.0.0.1', self._coordinator_port))
                    sock.sendall(request.encode())

                    response = b""
                    while True:
                        chunk = sock.recv(4096)
                        if not chunk:
                            break
                        response += chunk
                        if b"\r\n\r\n" in response:
                            header_end = response.index(b"\r\n\r\n")
                            headers = response[:header_end].decode('utf-8', errors='replace')
                            for line in headers.split("\r\n"):
                                if line.lower().startswith("content-length:"):
                                    content_length = int(line.split(":")[1].strip())
                                    body_start = header_end + 4
                                    if len(response) >= body_start + content_length:
                                        break
                            else:
                                continue
                            break

                # Success - break out of retry loop
                break

            except (socket.timeout, ConnectionRefusedError, OSError) as e:
                last_error = e

                # Check if we should retry
                if attempt < self._max_retries:
                    delay = self._calculate_retry_delay(attempt)
                    time.sleep(delay)
                    continue

                # No more retries - raise appropriate error
                if isinstance(e, socket.timeout):
                    raise RuntimeError(
                        f"Coordinator request timed out after {self._max_retries + 1} attempts"
                    )
                elif isinstance(e, ConnectionRefusedError):
                    raise RuntimeError(
                        f"Coordinator not running or connection refused after {self._max_retries + 1} attempts"
                    )
                else:
                    raise RuntimeError(
                        f"Network error communicating with coordinator after {self._max_retries + 1} attempts: {e}"
                    )

        # Decode response with error handling
        response_text = response.decode('utf-8', errors='replace')

        # Parse and validate status line
        lines = response_text.split('\r\n')
        if not lines:
            raise RuntimeError("Empty response from coordinator")

        status_line = lines[0]
        if not status_line.startswith('HTTP/1.1'):
            raise RuntimeError(f"Invalid HTTP response: {status_line}")

        # Extract status code
        try:
            status_code = int(status_line.split(' ')[1])
        except (IndexError, ValueError):
            raise RuntimeError(f"Could not parse status code from: {status_line}")

        # Parse body
        if "\r\n\r\n" in response_text:
            body_text = response_text.split("\r\n\r\n", 1)[1]
            try:
                result = json.loads(body_text)
            except json.JSONDecodeError:
                raise RuntimeError(f"Invalid JSON response from coordinator")

            # Check for error responses
            if status_code >= 400:
                error_msg = result.get('error', f'HTTP {status_code}')
                raise RuntimeError(f"Coordinator error: {error_msg}")

            return result

        return {}

    # ========================================================================
    # Single Mode: Direct JSON Access
    # ========================================================================

    def _recover_tmp_file(self) -> bool:
        """Check for and recover from orphaned .tmp file. Returns True if recovery occurred."""
        tasks_file = self.state_dir / 'tasks.json'
        tmp_file = tasks_file.with_suffix('.tmp')

        if not tmp_file.exists():
            return False

        # If main file doesn't exist, definitely use tmp
        if not tasks_file.exists():
            tmp_file.rename(tasks_file)
            return True

        # Both exist - use the newer one
        tmp_mtime = tmp_file.stat().st_mtime
        main_mtime = tasks_file.stat().st_mtime

        if tmp_mtime > main_mtime:
            # tmp is newer, validate it before using
            try:
                json.loads(tmp_file.read_text())  # Validate JSON
                tmp_file.rename(tasks_file)
                return True
            except (json.JSONDecodeError, OSError):
                # tmp file is corrupt, delete it
                tmp_file.unlink()
                return False
        else:
            # Main file is newer or same age, remove stale tmp
            tmp_file.unlink()
            return False

    def _migrate_schema(self, data: dict) -> dict:
        """
        Migrate task schema from v1 to v2 if needed.

        v2 additions:
        - parent_id: ID of parent task (for subtasks)
        - subtasks: List of subtask IDs
        - is_subtask: Boolean flag for quick filtering
        - time_tracking: Object with timer data
        """
        version = data.get('version', 1)

        if version < 2:
            # Migrate to v2: add subtask and time tracking fields
            for task in data.get('tasks', []):
                if 'parent_id' not in task:
                    task['parent_id'] = None
                if 'subtasks' not in task:
                    task['subtasks'] = []
                if 'is_subtask' not in task:
                    task['is_subtask'] = False
                if 'time_tracking' not in task:
                    task['time_tracking'] = None

            data['version'] = 2

        return data

    def _load_tasks(self) -> dict:
        """Load tasks from JSON file with schema migration."""
        # First check for orphaned tmp files from crash recovery
        self._recover_tmp_file()

        tasks_file = self.state_dir / 'tasks.json'
        if tasks_file.exists():
            data = json.loads(tasks_file.read_text())
            # Apply schema migrations if needed
            migrated = self._migrate_schema(data)
            if migrated.get('version', 1) != data.get('version', 1):
                # Save migrated data
                self._save_tasks(migrated)
            return migrated
        return {'version': 2, 'next_id': 1, 'tasks': []}

    def _save_tasks(self, data: dict):
        """Save tasks to JSON file with file locking for concurrent safety."""
        tasks_file = self.state_dir / 'tasks.json'
        tasks_file.parent.mkdir(parents=True, exist_ok=True)
        lock_file = self.state_dir / '.tasks.lock'

        with file_lock(lock_file, timeout=10.0):
            tmp_file = tasks_file.with_suffix('.tmp')
            tmp_file.write_text(json.dumps(data, indent=2))
            tmp_file.rename(tasks_file)

    def _is_task_ready(self, task: dict, all_tasks: list) -> bool:
        """Check if a task is ready (no open blockers)."""
        task_map = {t['id']: t for t in all_tasks}
        return is_task_ready(task, task_map)

    # ========================================================================
    # Unified API (works in both modes)
    # ========================================================================

    def register(self, context: str = "", labels: list = None, role: str = "worker") -> dict:
        """
        Register this session.

        In parallel mode: registers with coordinator
        In single mode: creates session tracking file
        """
        self.context = context
        self.labels = labels or []
        self.role = role

        if self._parallel_mode:
            return self._request('POST', '/session/register', {
                'session_id': self.session_id,
                'role': role,
                'context': context,
                'labels': self.labels,
            })
        else:
            # Single mode: write session file
            session_data = {
                'session_id': self.session_id,
                'role': role,
                'context': context,
                'labels': self.labels,
                'started_at': datetime.now(timezone.utc).isoformat(),
                'last_heartbeat': datetime.now(timezone.utc).isoformat(),
                'working_on': [],
            }
            sessions_dir = self.state_dir / 'sessions'
            sessions_dir.mkdir(parents=True, exist_ok=True)
            (sessions_dir / f'session-{self.session_id}.json').write_text(
                json.dumps(session_data, indent=2)
            )
            return session_data

    def heartbeat(self) -> bool:
        """Update session heartbeat."""
        if self._parallel_mode:
            result = self._request('POST', '/session/heartbeat', {
                'session_id': self.session_id
            })
            return result.get('success', False)
        else:
            session_file = self.state_dir / 'sessions' / f'session-{self.session_id}.json'
            if session_file.exists():
                data = json.loads(session_file.read_text())
                data['last_heartbeat'] = datetime.now(timezone.utc).isoformat()
                session_file.write_text(json.dumps(data, indent=2))
                return True
            return False

    def _ensure_session_registered(self) -> None:
        """
        Ensure a session file exists, creating one if needed.

        This enables CLI commands to auto-register sessions when claiming tasks,
        so they appear in the dashboard.
        """
        if self._parallel_mode:
            return  # Coordinator handles sessions in parallel mode

        session_file = self.state_dir / 'sessions' / f'session-{self.session_id}.json'
        if not session_file.exists():
            # Auto-register with minimal context
            self.register(context="CLI session", labels=self.labels, role=self.role)

    def _update_session_working_on(self, task_id: str, action: str) -> None:
        """
        Update the session's working_on list.

        This keeps track of what tasks this session is actively working on,
        which helps with context recovery after autocompact.

        Args:
            task_id: The task ID to add or remove
            action: 'add' to add task, 'remove' to remove task
        """
        if self._parallel_mode:
            return  # Coordinator handles this in parallel mode

        session_file = self.state_dir / 'sessions' / f'session-{self.session_id}.json'
        if not session_file.exists():
            return

        data = json.loads(session_file.read_text())
        working_on = data.get('working_on', [])

        if action == 'add' and task_id not in working_on:
            working_on.append(task_id)
        elif action == 'remove' and task_id in working_on:
            working_on.remove(task_id)

        data['working_on'] = working_on
        data['last_heartbeat'] = datetime.now(timezone.utc).isoformat()
        session_file.write_text(json.dumps(data, indent=2))

    def end_session(self, release_tasks: bool = True) -> bool:
        """End this session."""
        if self._parallel_mode:
            result = self._request('POST', '/session/end', {
                'session_id': self.session_id,
                'release_tasks': release_tasks,
            })
            return result.get('success', False)
        else:
            # Release tasks
            if release_tasks:
                data = self._load_tasks()
                for task in data['tasks']:
                    if task.get('assignee') == self.session_id:
                        task['assignee'] = None
                        task['status'] = 'open'
                        task['updated_at'] = datetime.now(timezone.utc).isoformat()
                self._save_tasks(data)

            # Remove session file
            session_file = self.state_dir / 'sessions' / f'session-{self.session_id}.json'
            if session_file.exists():
                session_file.unlink()
            return True

    def _cleanup_stale_sessions(self, max_age_seconds: int = 300) -> int:
        """
        Remove stale session files that haven't had a heartbeat recently.

        This handles CLI sessions that exit without calling end_session(),
        as well as crashed or killed processes.

        Args:
            max_age_seconds: Remove sessions with no heartbeat for this long (default: 5 min)

        Returns:
            Number of sessions cleaned up
        """
        if self._parallel_mode:
            return 0  # Coordinator handles session cleanup in parallel mode

        sessions_dir = self.state_dir / 'sessions'
        if not sessions_dir.exists():
            return 0

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=max_age_seconds)
        cleaned = 0

        for session_file in sessions_dir.glob('session-*.json'):
            try:
                data = json.loads(session_file.read_text())
                last_heartbeat = data.get('last_heartbeat', '')

                if last_heartbeat:
                    # Parse timestamp
                    if last_heartbeat.endswith('Z'):
                        last_heartbeat = last_heartbeat[:-1] + '+00:00'
                    heartbeat_time = datetime.fromisoformat(last_heartbeat)
                    if heartbeat_time.tzinfo is None:
                        heartbeat_time = heartbeat_time.replace(tzinfo=timezone.utc)

                    if heartbeat_time < cutoff:
                        # Session is stale - clean it up
                        session_id = data.get('session_id')

                        # Release any tasks assigned to this session
                        tasks_data = self._load_tasks()
                        tasks_modified = False
                        for task in tasks_data['tasks']:
                            if task.get('assignee') == session_id:
                                task['assignee'] = None
                                if task.get('status') == 'in_progress':
                                    task['status'] = 'open'
                                task['updated_at'] = now.isoformat()
                                task.setdefault('notes', []).append({
                                    'timestamp': now.isoformat(),
                                    'session_id': 'system',
                                    'note': f'Released from stale session {session_id}',
                                })
                                tasks_modified = True

                        if tasks_modified:
                            self._save_tasks(tasks_data)

                        # Remove the session file
                        session_file.unlink()
                        cleaned += 1

            except (json.JSONDecodeError, OSError, ValueError):
                # Malformed session file - remove it
                try:
                    session_file.unlink()
                    cleaned += 1
                except OSError:
                    pass

        return cleaned

    def get_next_task(self, preferred_labels: list = None) -> Optional[dict]:
        """
        Get the next available task.

        In parallel mode: coordinator assigns atomically
        In single mode: finds and claims directly

        Auto-registers a session if one doesn't exist, so CLI commands
        appear in the dashboard.
        """
        labels = preferred_labels or self.labels

        if self._parallel_mode:
            result = self._request('POST', '/task/request', {
                'session_id': self.session_id,
                'preferred_labels': labels,
            })
            return result.get('task')
        else:
            data = self._load_tasks()

            # Find ready tasks
            ready = [t for t in data['tasks'] if self._is_task_ready(t, data['tasks'])]

            if not ready:
                return None

            # Score and sort
            def score(task):
                priority = task.get('priority', 2)
                label_match = -len(set(task.get('labels', [])) & set(labels)) if labels else 0
                return (priority, label_match, task.get('created_at', ''))

            ready.sort(key=score)
            task = ready[0]

            # Ensure session is registered before claiming
            self._ensure_session_registered()

            # Claim it
            task['assignee'] = self.session_id
            task['status'] = 'in_progress'
            task['updated_at'] = datetime.now(timezone.utc).isoformat()
            task.setdefault('notes', []).append({
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'session_id': self.session_id,
                'note': 'Claimed task',
            })

            self._save_tasks(data)
            self._update_session_working_on(task['id'], 'add')
            return task

    def complete_task(self, task_id: str, note: str = "", branch: str = None, force: bool = False) -> dict:
        """
        Mark a task as complete.

        Args:
            task_id: Task ID to complete
            note: Completion note
            branch: Git branch name
            force: If True, complete even if subtasks are incomplete

        Returns:
            Dict with 'success' bool, and optionally 'incomplete_subtasks' list
        """
        if self._parallel_mode:
            result = self._request('POST', '/task/complete', {
                'task_id': task_id,
                'session_id': self.session_id,
                'note': note,
                'branch': branch,
                'force': force,
            })
            return result
        else:
            data = self._load_tasks()
            task_map = {t['id']: t for t in data['tasks']}

            task = task_map.get(task_id)
            if not task:
                return {'success': False, 'error': 'Task not found'}

            # Check for incomplete subtasks
            subtask_ids = task.get('subtasks', [])
            if subtask_ids and not force:
                incomplete = []
                for sid in subtask_ids:
                    subtask = task_map.get(sid)
                    if subtask and subtask.get('status') != 'done':
                        incomplete.append({
                            'id': sid,
                            'title': subtask.get('title'),
                            'status': subtask.get('status'),
                        })

                if incomplete:
                    return {
                        'success': False,
                        'error': 'incomplete_subtasks',
                        'incomplete_subtasks': incomplete,
                        'message': f'{len(incomplete)} subtask(s) not complete',
                    }

            # Store undo data before modifying
            undo_data = {
                'previous_status': task.get('status'),
                'previous_assignee': task.get('assignee'),
            }

            task['status'] = 'done'
            task['assignee'] = None
            task['updated_at'] = datetime.now(timezone.utc).isoformat()
            if branch:
                task['branch'] = branch
            if note:
                task.setdefault('notes', []).append({
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'session_id': self.session_id,
                    'note': f'Completed: {note}',
                })
            self._save_tasks(data)
            self._update_session_working_on(task_id, 'remove')

            # Log to history with undo data
            self._log_event('task_completed', {'task_id': task_id, 'note': note}, undo_data)
            return {'success': True}

    def reopen_task(self, task_id: str, note: str = "") -> bool:
        """Reopen a completed or blocked task."""
        if self._parallel_mode:
            result = self._request('POST', '/task/reopen', {
                'task_id': task_id,
                'session_id': self.session_id,
                'note': note,
            })
            return result.get('success', False)
        else:
            data = self._load_tasks()
            for task in data['tasks']:
                if task['id'] == task_id:
                    old_status = task.get('status', 'open')

                    # Store undo data before modifying
                    undo_data = {
                        'previous_status': old_status,
                    }

                    task['status'] = 'open'
                    task['assignee'] = None
                    task['updated_at'] = datetime.now(timezone.utc).isoformat()
                    note_text = f'Reopened (was {old_status})'
                    if note:
                        note_text += f': {note}'
                    task.setdefault('notes', []).append({
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'session_id': self.session_id,
                        'note': note_text,
                    })
                    self._save_tasks(data)

                    # Log to history with undo data
                    self._log_event('task_reopened', {'task_id': task_id, 'note': note}, undo_data)
                    return True
            return False

    def bulk_complete(
        self,
        task_ids: list,
        note: str = "",
        branch: str = None,
        force: bool = False,
    ) -> dict:
        """
        Complete multiple tasks at once.

        Args:
            task_ids: List of task IDs to complete
            note: Completion note (applied to all tasks)
            branch: Git branch name (applied to all tasks)
            force: If True, complete even if subtasks are incomplete

        Returns:
            Dict with 'succeeded' list, 'failed' list (with reasons), and 'total' counts
        """
        if self._parallel_mode:
            result = self._request('POST', '/task/bulk-complete', {
                'task_ids': task_ids,
                'session_id': self.session_id,
                'note': note,
                'branch': branch,
                'force': force,
            })
            return result
        else:
            data = self._load_tasks()
            task_map = {t['id']: t for t in data['tasks']}

            succeeded = []
            failed = []

            for task_id in task_ids:
                task = task_map.get(task_id)
                if not task:
                    failed.append({'id': task_id, 'error': 'Task not found'})
                    continue

                # Check for incomplete subtasks
                subtask_ids = task.get('subtasks', [])
                if subtask_ids and not force:
                    incomplete = []
                    for sid in subtask_ids:
                        subtask = task_map.get(sid)
                        if subtask and subtask.get('status') != 'done':
                            incomplete.append({
                                'id': sid,
                                'title': subtask.get('title'),
                                'status': subtask.get('status'),
                            })

                    if incomplete:
                        failed.append({
                            'id': task_id,
                            'error': 'incomplete_subtasks',
                            'incomplete_subtasks': incomplete,
                        })
                        continue

                # Store undo data before modifying
                undo_data = {
                    'previous_status': task.get('status'),
                    'previous_assignee': task.get('assignee'),
                }

                task['status'] = 'done'
                task['assignee'] = None
                task['updated_at'] = datetime.now(timezone.utc).isoformat()
                if branch:
                    task['branch'] = branch
                if note:
                    task.setdefault('notes', []).append({
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'session_id': self.session_id,
                        'note': f'Completed: {note}',
                    })
                else:
                    task.setdefault('notes', []).append({
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'session_id': self.session_id,
                        'note': 'Completed (bulk)',
                    })

                self._update_session_working_on(task_id, 'remove')
                self._log_event('task_completed', {'task_id': task_id, 'note': note, 'bulk': True}, undo_data)
                succeeded.append(task_id)

            # Save all changes at once
            self._save_tasks(data)

            return {
                'succeeded': succeeded,
                'failed': failed,
                'total_succeeded': len(succeeded),
                'total_failed': len(failed),
            }

    def bulk_reopen(self, task_ids: list, note: str = "") -> dict:
        """
        Reopen multiple tasks at once.

        Args:
            task_ids: List of task IDs to reopen
            note: Note to add (applied to all tasks)

        Returns:
            Dict with 'succeeded' list, 'failed' list (with reasons), and 'total' counts
        """
        if self._parallel_mode:
            result = self._request('POST', '/task/bulk-reopen', {
                'task_ids': task_ids,
                'session_id': self.session_id,
                'note': note,
            })
            return result
        else:
            data = self._load_tasks()
            task_map = {t['id']: t for t in data['tasks']}

            succeeded = []
            failed = []

            for task_id in task_ids:
                task = task_map.get(task_id)
                if not task:
                    failed.append({'id': task_id, 'error': 'Task not found'})
                    continue

                old_status = task.get('status', 'open')
                if old_status == 'open':
                    failed.append({'id': task_id, 'error': 'Task is already open'})
                    continue

                # Store undo data before modifying
                undo_data = {
                    'previous_status': old_status,
                }

                task['status'] = 'open'
                task['assignee'] = None
                task['updated_at'] = datetime.now(timezone.utc).isoformat()
                note_text = f'Reopened (was {old_status})'
                if note:
                    note_text += f': {note}'
                task.setdefault('notes', []).append({
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'session_id': self.session_id,
                    'note': note_text,
                })

                self._log_event('task_reopened', {'task_id': task_id, 'note': note, 'bulk': True}, undo_data)
                succeeded.append(task_id)

            # Save all changes at once
            self._save_tasks(data)

            return {
                'succeeded': succeeded,
                'failed': failed,
                'total_succeeded': len(succeeded),
                'total_failed': len(failed),
            }

    def create_task(
        self,
        title: str,
        description: str = "",
        priority: int = 2,
        blocked_by: list = None,
        labels: list = None,
        branch: str = None,
    ) -> dict:
        """Create a new task."""
        if self._parallel_mode:
            return self._request('POST', '/task/create', {
                'title': title,
                'description': description,
                'priority': priority,
                'blocked_by': blocked_by or [],
                'labels': labels or [],
                'branch': branch,
                'session_id': self.session_id,
            })
        else:
            data = self._load_tasks()
            task_id = f"task-{data['next_id']:03d}"
            data['next_id'] += 1

            task = {
                'id': task_id,
                'title': title,
                'description': description,
                'status': 'open',
                'priority': priority,
                'blocked_by': blocked_by or [],
                'assignee': None,
                'labels': labels or [],
                'branch': branch,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'updated_at': datetime.now(timezone.utc).isoformat(),
                'notes': [{
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'session_id': self.session_id,
                    'note': 'Created task',
                }],
                # v2 fields
                'parent_id': None,
                'subtasks': [],
                'is_subtask': False,
                'time_tracking': None,
            }

            data['tasks'].append(task)
            self._save_tasks(data)

            self._log_event('task_created', {'task_id': task_id, 'title': title})
            return task

    def add_note(self, task_id: str, note: str) -> bool:
        """Add a note to a task."""
        if self._parallel_mode:
            result = self._request('POST', '/task/note', {
                'task_id': task_id,
                'session_id': self.session_id,
                'note': note,
            })
            return result.get('success', False)
        else:
            data = self._load_tasks()
            for task in data['tasks']:
                if task['id'] == task_id:
                    task.setdefault('notes', []).append({
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'session_id': self.session_id,
                        'note': note,
                    })
                    task['updated_at'] = datetime.now(timezone.utc).isoformat()
                    self._save_tasks(data)
                    return True
            return False

    # ========================================================================
    # Subtask Operations (v2)
    # ========================================================================

    def create_subtask(
        self,
        parent_id: str,
        title: str,
        description: str = "",
        priority: int = None,
        labels: list = None,
    ) -> Optional[dict]:
        """
        Create a subtask under a parent task.

        Args:
            parent_id: ID of the parent task
            title: Subtask title
            description: Subtask description
            priority: Priority (inherits from parent if not specified)
            labels: Labels (inherits from parent if not specified)

        Returns:
            The created subtask dict, or None if parent not found
        """
        if self._parallel_mode:
            result = self._request('POST', '/task/create-subtask', {
                'parent_id': parent_id,
                'title': title,
                'description': description,
                'priority': priority,
                'labels': labels,
                'session_id': self.session_id,
            })
            return result.get('task')
        else:
            data = self._load_tasks()

            # Find parent task
            parent = None
            for task in data['tasks']:
                if task['id'] == parent_id:
                    parent = task
                    break

            if not parent:
                return None

            # Create subtask with inherited properties
            task_id = f"task-{data['next_id']:03d}"
            data['next_id'] += 1

            subtask = {
                'id': task_id,
                'title': title,
                'description': description,
                'status': 'open',
                'priority': priority if priority is not None else parent.get('priority', 2),
                'blocked_by': [],
                'assignee': None,
                'labels': labels if labels is not None else parent.get('labels', []).copy(),
                'branch': parent.get('branch'),
                'created_at': datetime.now(timezone.utc).isoformat(),
                'updated_at': datetime.now(timezone.utc).isoformat(),
                'notes': [{
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'session_id': self.session_id,
                    'note': f'Created as subtask of {parent_id}',
                }],
                # v2 fields
                'parent_id': parent_id,
                'subtasks': [],
                'is_subtask': True,
                'time_tracking': None,
            }

            # Add subtask to parent's subtask list
            parent.setdefault('subtasks', []).append(task_id)
            parent['updated_at'] = datetime.now(timezone.utc).isoformat()

            data['tasks'].append(subtask)
            self._save_tasks(data)

            self._log_event('subtask_created', {
                'task_id': task_id,
                'parent_id': parent_id,
                'title': title,
            })
            return subtask

    def get_subtask_progress(self, task_id: str) -> Optional[dict]:
        """
        Get progress of a task's subtasks.

        Returns:
            Dict with total, completed, in_progress, open counts and percentage
        """
        if self._parallel_mode:
            result = self._request('GET', f'/task/{task_id}/subtask-progress')
            return result
        else:
            data = self._load_tasks()
            task_map = {t['id']: t for t in data['tasks']}

            task = task_map.get(task_id)
            if not task:
                return None

            subtask_ids = task.get('subtasks', [])
            if not subtask_ids:
                return {
                    'total': 0,
                    'completed': 0,
                    'in_progress': 0,
                    'open': 0,
                    'blocked': 0,
                    'percentage': 100,  # No subtasks = 100% complete
                }

            counts = {'open': 0, 'in_progress': 0, 'done': 0, 'blocked': 0}
            for sid in subtask_ids:
                subtask = task_map.get(sid)
                if subtask:
                    status = subtask.get('status', 'open')
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

    def get_subtasks(self, task_id: str) -> list:
        """Get all subtasks for a task."""
        if self._parallel_mode:
            result = self._request('GET', f'/task/{task_id}/subtasks')
            return result.get('subtasks', [])
        else:
            data = self._load_tasks()
            task_map = {t['id']: t for t in data['tasks']}

            task = task_map.get(task_id)
            if not task:
                return []

            subtask_ids = task.get('subtasks', [])
            subtasks = []
            for sid in subtask_ids:
                subtask = task_map.get(sid)
                if subtask:
                    subtasks.append(subtask)

            return subtasks

    # ========================================================================
    # Task Editing & Deletion (v1.1)
    # ========================================================================

    def edit_task(
        self,
        task_id: str,
        title: str = None,
        description: str = None,
        priority: int = None,
        labels: list = None,
    ) -> Optional[dict]:
        """
        Edit a task's properties.

        Args:
            task_id: Task ID to edit
            title: New title (None to keep existing)
            description: New description (None to keep existing)
            priority: New priority (None to keep existing)
            labels: New labels (None to keep existing)

        Returns:
            Updated task dict, or None if task not found
        """
        if self._parallel_mode:
            result = self._request('POST', '/task/edit', {
                'task_id': task_id,
                'session_id': self.session_id,
                'title': title,
                'description': description,
                'priority': priority,
                'labels': labels,
            })
            return result.get('task')
        else:
            data = self._load_tasks()

            for task in data['tasks']:
                if task['id'] == task_id:
                    # Store previous values for undo
                    previous = {}
                    changes = []

                    if title is not None and title != task.get('title'):
                        previous['title'] = task.get('title')
                        task['title'] = title
                        changes.append(f"title")

                    if description is not None and description != task.get('description'):
                        previous['description'] = task.get('description')
                        task['description'] = description
                        changes.append(f"description")

                    if priority is not None and priority != task.get('priority'):
                        previous['priority'] = task.get('priority')
                        task['priority'] = priority
                        changes.append(f"priority to P{priority}")

                    if labels is not None and labels != task.get('labels'):
                        previous['labels'] = task.get('labels', []).copy()
                        task['labels'] = labels
                        changes.append(f"labels")

                    if changes:
                        task['updated_at'] = datetime.now(timezone.utc).isoformat()
                        task.setdefault('notes', []).append({
                            'timestamp': datetime.now(timezone.utc).isoformat(),
                            'session_id': self.session_id,
                            'note': f'Edited: {", ".join(changes)}',
                        })
                        self._save_tasks(data)

                        # Log with undo data
                        self._log_event('task_edited', {
                            'task_id': task_id,
                            'changes': changes,
                        }, {'previous': previous})

                    return task

            return None

    def delete_task(self, task_id: str, force: bool = False) -> dict:
        """
        Delete a task.

        Args:
            task_id: Task ID to delete
            force: If True, delete even if task has subtasks

        Returns:
            Dict with 'success', optionally 'error', 'subtasks'
        """
        if self._parallel_mode:
            result = self._request('POST', '/task/delete', {
                'task_id': task_id,
                'session_id': self.session_id,
                'force': force,
            })
            return result
        else:
            data = self._load_tasks()
            task_map = {t['id']: t for t in data['tasks']}

            task = task_map.get(task_id)
            if not task:
                return {'success': False, 'error': 'Task not found'}

            # Check for subtasks
            subtask_ids = task.get('subtasks', [])
            if subtask_ids and not force:
                return {
                    'success': False,
                    'error': 'has_subtasks',
                    'subtasks': subtask_ids,
                    'message': f'Task has {len(subtask_ids)} subtask(s). Use --force to delete.',
                }

            # Store task for undo
            undo_data = {'task': task.copy()}

            # Remove from parent's subtask list if this is a subtask
            parent_id = task.get('parent_id')
            if parent_id:
                parent = task_map.get(parent_id)
                if parent and task_id in parent.get('subtasks', []):
                    parent['subtasks'].remove(task_id)
                    parent['updated_at'] = datetime.now(timezone.utc).isoformat()

            # If deleting with force, also delete subtasks
            if subtask_ids and force:
                for sid in subtask_ids:
                    data['tasks'] = [t for t in data['tasks'] if t['id'] != sid]

            # Delete the task
            data['tasks'] = [t for t in data['tasks'] if t['id'] != task_id]
            self._save_tasks(data)

            # Log with undo data
            self._log_event('task_deleted', {'task_id': task_id}, undo_data)

            return {'success': True, 'deleted_subtasks': subtask_ids if force else []}

    # ========================================================================
    # Time Tracking Operations (v2)
    # ========================================================================

    def start_timer(self, task_id: str) -> Optional[dict]:
        """
        Start the timer for a task.

        Returns:
            Updated task dict, or None if task not found
        """
        if self._parallel_mode:
            result = self._request('POST', '/task/timer/start', {
                'task_id': task_id,
                'session_id': self.session_id,
            })
            return result.get('task')
        else:
            data = self._load_tasks()
            for task in data['tasks']:
                if task['id'] == task_id:
                    now = datetime.now(timezone.utc).isoformat()

                    # Initialize or update time_tracking
                    if task.get('time_tracking') is None:
                        task['time_tracking'] = {
                            'started_at': now,
                            'paused_at': None,
                            'total_seconds': 0,
                        }
                    elif task['time_tracking'].get('paused_at'):
                        # Resume from pause
                        task['time_tracking']['started_at'] = now
                        task['time_tracking']['paused_at'] = None
                    elif task['time_tracking'].get('started_at'):
                        # Already running
                        return task
                    else:
                        task['time_tracking']['started_at'] = now

                    task['updated_at'] = now
                    self._save_tasks(data)
                    self._log_event('timer_started', {'task_id': task_id})
                    return task

            return None

    def stop_timer(self, task_id: str) -> Optional[dict]:
        """
        Stop the timer for a task (accumulates time, clears timer).

        Returns:
            Updated task dict with final time, or None if task not found
        """
        if self._parallel_mode:
            result = self._request('POST', '/task/timer/stop', {
                'task_id': task_id,
                'session_id': self.session_id,
            })
            return result.get('task')
        else:
            data = self._load_tasks()
            for task in data['tasks']:
                if task['id'] == task_id:
                    tt = task.get('time_tracking')
                    if not tt or not tt.get('started_at'):
                        return task  # No timer running

                    now = datetime.now(timezone.utc)
                    started = datetime.fromisoformat(tt['started_at'].replace('Z', '+00:00'))
                    elapsed = (now - started).total_seconds()

                    task['time_tracking']['total_seconds'] = tt.get('total_seconds', 0) + elapsed
                    task['time_tracking']['started_at'] = None
                    task['time_tracking']['paused_at'] = None
                    task['updated_at'] = now.isoformat()

                    self._save_tasks(data)
                    self._log_event('timer_stopped', {
                        'task_id': task_id,
                        'elapsed_seconds': elapsed,
                    })
                    return task

            return None

    def pause_timer(self, task_id: str) -> Optional[dict]:
        """
        Pause the timer for a task (saves elapsed time).

        Returns:
            Updated task dict, or None if task not found
        """
        if self._parallel_mode:
            result = self._request('POST', '/task/timer/pause', {
                'task_id': task_id,
                'session_id': self.session_id,
            })
            return result.get('task')
        else:
            data = self._load_tasks()
            for task in data['tasks']:
                if task['id'] == task_id:
                    tt = task.get('time_tracking')
                    if not tt or not tt.get('started_at'):
                        return task  # No timer running

                    now = datetime.now(timezone.utc)
                    started = datetime.fromisoformat(tt['started_at'].replace('Z', '+00:00'))
                    elapsed = (now - started).total_seconds()

                    task['time_tracking']['total_seconds'] = tt.get('total_seconds', 0) + elapsed
                    task['time_tracking']['started_at'] = None
                    task['time_tracking']['paused_at'] = now.isoformat()
                    task['updated_at'] = now.isoformat()

                    self._save_tasks(data)
                    self._log_event('timer_paused', {
                        'task_id': task_id,
                        'elapsed_seconds': elapsed,
                    })
                    return task

            return None

    def get_task_time(self, task_id: str) -> Optional[dict]:
        """
        Get time tracking info for a task.

        Returns:
            Dict with total_seconds, is_running, current_elapsed
        """
        tasks = self.get_tasks()
        for task in tasks:
            if task['id'] == task_id:
                tt = task.get('time_tracking')
                if not tt:
                    return {'total_seconds': 0, 'is_running': False, 'current_elapsed': 0}

                is_running = tt.get('started_at') is not None
                current_elapsed = 0

                if is_running:
                    now = datetime.now(timezone.utc)
                    started = datetime.fromisoformat(tt['started_at'].replace('Z', '+00:00'))
                    current_elapsed = (now - started).total_seconds()

                return {
                    'total_seconds': tt.get('total_seconds', 0),
                    'is_running': is_running,
                    'current_elapsed': current_elapsed,
                    'is_paused': tt.get('paused_at') is not None,
                }

        return None

    def get_time_report(self, by: str = 'task', labels: list = None) -> dict:
        """
        Get a time report aggregated by task, label, or day.

        Args:
            by: Aggregation type ('task', 'label', 'day')
            labels: Filter by labels (optional)

        Returns:
            Dict with aggregated time data
        """
        tasks = self.get_tasks()

        # Filter by labels if specified
        if labels:
            tasks = [t for t in tasks if any(l in t.get('labels', []) for l in labels)]

        report = {'total_seconds': 0, 'items': []}

        if by == 'task':
            for task in tasks:
                tt = task.get('time_tracking')
                if tt and tt.get('total_seconds', 0) > 0:
                    seconds = tt.get('total_seconds', 0)
                    report['items'].append({
                        'id': task['id'],
                        'title': task['title'],
                        'seconds': seconds,
                        'hours': round(seconds / 3600, 2),
                    })
                    report['total_seconds'] += seconds

        elif by == 'label':
            label_times = {}
            for task in tasks:
                tt = task.get('time_tracking')
                seconds = tt.get('total_seconds', 0) if tt else 0
                if seconds > 0:
                    for label in task.get('labels', ['unlabeled']):
                        label_times[label] = label_times.get(label, 0) + seconds
                    report['total_seconds'] += seconds

            for label, seconds in sorted(label_times.items(), key=lambda x: -x[1]):
                report['items'].append({
                    'label': label,
                    'seconds': seconds,
                    'hours': round(seconds / 3600, 2),
                })

        elif by == 'day':
            day_times = {}
            for task in tasks:
                tt = task.get('time_tracking')
                if tt and tt.get('total_seconds', 0) > 0:
                    # Use task's updated_at as rough approximation for when work was done
                    updated = task.get('updated_at', '')[:10]  # YYYY-MM-DD
                    if updated:
                        day_times[updated] = day_times.get(updated, 0) + tt.get('total_seconds', 0)
                        report['total_seconds'] += tt.get('total_seconds', 0)

            for day, seconds in sorted(day_times.items(), reverse=True):
                report['items'].append({
                    'day': day,
                    'seconds': seconds,
                    'hours': round(seconds / 3600, 2),
                })

        report['total_hours'] = round(report['total_seconds'] / 3600, 2)
        return report

    # ========================================================================
    # Template Operations (v2)
    # ========================================================================

    def _load_templates(self) -> dict:
        """Load templates from JSON file."""
        templates_file = self.state_dir / 'templates.json'
        if templates_file.exists():
            return json.loads(templates_file.read_text())
        return {'version': 1, 'templates': []}

    def _save_templates(self, data: dict):
        """Save templates to JSON file."""
        templates_file = self.state_dir / 'templates.json'
        templates_file.parent.mkdir(parents=True, exist_ok=True)
        lock_file = self.state_dir / '.templates.lock'

        with file_lock(lock_file, timeout=10.0):
            tmp_file = templates_file.with_suffix('.tmp')
            tmp_file.write_text(json.dumps(data, indent=2))
            tmp_file.rename(templates_file)

    def list_templates(self) -> list:
        """List all task templates."""
        data = self._load_templates()
        return data.get('templates', [])

    def get_template(self, template_id: str) -> Optional[dict]:
        """Get a specific template by ID."""
        templates = self.list_templates()
        for template in templates:
            if template['id'] == template_id:
                return template
        return None

    def create_template(
        self,
        name: str,
        description: str = "",
        default_priority: int = 2,
        default_labels: list = None,
        subtasks: list = None,
    ) -> dict:
        """
        Create a new task template.

        Args:
            name: Template name
            description: Template description
            default_priority: Default priority for tasks from this template
            default_labels: Default labels for tasks from this template
            subtasks: List of subtask dicts with 'title' and optional 'description'

        Returns:
            The created template dict
        """
        data = self._load_templates()

        # Generate template ID
        existing_ids = {t['id'] for t in data.get('templates', [])}
        template_num = 1
        while f"template-{template_num:03d}" in existing_ids:
            template_num += 1
        template_id = f"template-{template_num:03d}"

        template = {
            'id': template_id,
            'name': name,
            'description': description,
            'default_priority': default_priority,
            'default_labels': default_labels or [],
            'subtasks': subtasks or [],
            'created_at': datetime.now(timezone.utc).isoformat(),
        }

        data.setdefault('templates', []).append(template)
        self._save_templates(data)

        self._log_event('template_created', {'template_id': template_id, 'name': name})
        return template

    def delete_template(self, template_id: str) -> bool:
        """Delete a template."""
        data = self._load_templates()
        templates = data.get('templates', [])

        for i, template in enumerate(templates):
            if template['id'] == template_id:
                del templates[i]
                self._save_templates(data)
                self._log_event('template_deleted', {'template_id': template_id})
                return True

        return False

    def create_from_template(
        self,
        template_id: str,
        title: str,
        description: str = None,
        priority: int = None,
        labels: list = None,
    ) -> Optional[dict]:
        """
        Create a task (with subtasks) from a template.

        Args:
            template_id: Template ID to use
            title: Task title (overrides template name)
            description: Task description (uses template description if not specified)
            priority: Priority (uses template default if not specified)
            labels: Labels (uses template defaults if not specified)

        Returns:
            The created parent task dict with subtasks created
        """
        template = self.get_template(template_id)
        if not template:
            return None

        # Create parent task
        task = self.create_task(
            title=title,
            description=description or template.get('description', ''),
            priority=priority if priority is not None else template.get('default_priority', 2),
            labels=labels if labels is not None else template.get('default_labels', []),
        )

        if not task:
            return None

        # Create subtasks from template
        for st in template.get('subtasks', []):
            self.create_subtask(
                parent_id=task['id'],
                title=st.get('title', ''),
                description=st.get('description', ''),
            )

        # Reload task to include subtasks
        tasks = self.get_tasks()
        for t in tasks:
            if t['id'] == task['id']:
                return t

        return task

    # ========================================================================
    # Task Archiving (v1.1)
    # ========================================================================

    def archive_tasks(self, days_old: int = 30, dry_run: bool = False) -> dict:
        """
        Archive completed tasks older than specified days.

        Args:
            days_old: Archive tasks completed more than this many days ago
            dry_run: If True, just return what would be archived

        Returns:
            Dict with 'archived' count and 'tasks' list
        """
        if self._parallel_mode:
            # Archive is a local operation, not supported in parallel mode
            return {'error': 'Archive not supported in parallel mode', 'archived': 0, 'tasks': []}

        data = self._load_tasks()
        archive_file = self.state_dir / 'archive.jsonl'

        cutoff = datetime.now(timezone.utc) - timedelta(days=days_old)
        to_archive = []
        remaining = []

        for task in data['tasks']:
            if task.get('status') != 'done':
                remaining.append(task)
                continue

            # Check completion date from updated_at
            updated = task.get('updated_at', '')
            if updated:
                try:
                    task_date = datetime.fromisoformat(updated.replace('Z', '+00:00'))
                    if task_date < cutoff:
                        to_archive.append(task)
                        continue
                except ValueError:
                    pass

            remaining.append(task)

        if dry_run:
            return {
                'archived': len(to_archive),
                'tasks': to_archive,
                'dry_run': True,
            }

        # Write to archive file
        if to_archive:
            with open(archive_file, 'a') as f:
                for task in to_archive:
                    task['archived_at'] = datetime.now(timezone.utc).isoformat()
                    f.write(json.dumps(task) + '\n')

            # Update tasks.json
            data['tasks'] = remaining
            self._save_tasks(data)

            self._log_event('tasks_archived', {
                'count': len(to_archive),
                'days_old': days_old,
            })

        return {
            'archived': len(to_archive),
            'tasks': to_archive,
        }

    def list_archived(self, limit: int = 50) -> list:
        """List archived tasks."""
        archive_file = self.state_dir / 'archive.jsonl'
        if not archive_file.exists():
            return []

        tasks = []
        with open(archive_file, 'r') as f:
            for line in f:
                try:
                    tasks.append(json.loads(line.strip()))
                except json.JSONDecodeError:
                    continue

        # Return most recent first
        tasks.reverse()
        return tasks[:limit]

    def restore_from_archive(self, task_id: str) -> Optional[dict]:
        """Restore a task from the archive."""
        archive_file = self.state_dir / 'archive.jsonl'
        if not archive_file.exists():
            return None

        # Read all archived tasks
        archived = []
        restored_task = None
        with open(archive_file, 'r') as f:
            for line in f:
                try:
                    task = json.loads(line.strip())
                    if task.get('id') == task_id:
                        restored_task = task
                    else:
                        archived.append(task)
                except json.JSONDecodeError:
                    continue

        if not restored_task:
            return None

        # Remove archived_at field
        restored_task.pop('archived_at', None)
        restored_task['status'] = 'open'
        restored_task['updated_at'] = datetime.now(timezone.utc).isoformat()
        restored_task.setdefault('notes', []).append({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'session_id': self.session_id,
            'note': 'Restored from archive',
        })

        # Write back archive without restored task
        with open(archive_file, 'w') as f:
            for task in archived:
                f.write(json.dumps(task) + '\n')

        # Add to active tasks
        data = self._load_tasks()
        data['tasks'].append(restored_task)
        self._save_tasks(data)

        self._log_event('task_restored', {'task_id': task_id})
        return restored_task

    def get_status(self) -> dict:
        """Get system status. Also cleans up stale sessions."""
        if self._parallel_mode:
            result = self._request('GET', '/status')
            result['mode'] = 'parallel'
            return result
        else:
            # Clean up stale sessions before reporting status
            self._cleanup_stale_sessions()

            data = self._load_tasks()

            by_status = {}
            ready_count = 0
            for task in data['tasks']:
                status = task.get('status', 'open')
                by_status[status] = by_status.get(status, 0) + 1
                if self._is_task_ready(task, data['tasks']):
                    ready_count += 1

            # Count sessions
            sessions_dir = self.state_dir / 'sessions'
            sessions = {}
            if sessions_dir.exists():
                for f in sessions_dir.glob('session-*.json'):
                    try:
                        s = json.loads(f.read_text())
                        sessions[s['session_id']] = s
                    except (json.JSONDecodeError, OSError, KeyError):
                        continue  # Skip malformed session files

            return {
                'mode': 'single',
                'total_tasks': len(data['tasks']),
                'tasks_by_status': by_status,
                'ready_tasks': ready_count,
                'active_sessions': len(sessions),
                'sessions': sessions,
            }

    def get_tasks(self, status: str = None) -> list:
        """Get all tasks, optionally filtered."""
        if self._parallel_mode:
            path = '/tasks'
            if status:
                path += f'?status={status}'
            result = self._request('GET', path)
            return result.get('tasks', [])
        else:
            data = self._load_tasks()
            tasks = data['tasks']
            if status:
                tasks = [t for t in tasks if t.get('status') == status]
            return tasks

    def _log_event(self, event: str, details: dict = None, undo_data: dict = None):
        """
        Append to history log with optional undo data.

        Args:
            event: Event type (e.g., 'task_completed', 'task_deleted')
            details: Event-specific details
            undo_data: Previous state data for reversible actions
        """
        history_file = self.state_dir / 'history.jsonl'
        entry = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'event': event,
            'session_id': self.session_id,
            **(details or {}),
        }
        if undo_data:
            entry['undo_data'] = undo_data
        with open(history_file, 'a') as f:
            f.write(json.dumps(entry) + '\n')

    def get_last_undoable_action(self) -> Optional[dict]:
        """
        Get the most recent action that can be undone.

        Returns:
            The history entry with undo_data, or None if no undoable actions
        """
        history_file = self.state_dir / 'history.jsonl'
        if not history_file.exists():
            return None

        # Read history in reverse to find last undoable action
        undoable_events = {'task_completed', 'task_deleted', 'task_edited', 'task_reopened'}

        with open(history_file, 'r') as f:
            lines = f.readlines()

        for line in reversed(lines):
            try:
                entry = json.loads(line.strip())
                if entry.get('event') in undoable_events and 'undo_data' in entry:
                    return entry
            except json.JSONDecodeError:
                continue

        return None

    def undo_last_action(self) -> Optional[dict]:
        """
        Undo the most recent reversible action.

        Returns:
            Dict with 'success', 'action', and 'task_id' on success, None if nothing to undo
        """
        last_action = self.get_last_undoable_action()
        if not last_action:
            return None

        event = last_action.get('event')
        undo_data = last_action.get('undo_data', {})
        task_id = last_action.get('task_id')

        if self._parallel_mode:
            # In parallel mode, we'd need a coordinator endpoint for undo
            # For now, return None (not supported in parallel mode)
            return None

        data = self._load_tasks()
        result = None

        if event == 'task_completed':
            # Restore task to previous status
            for task in data['tasks']:
                if task['id'] == task_id:
                    task['status'] = undo_data.get('previous_status', 'in_progress')
                    task['assignee'] = undo_data.get('previous_assignee')
                    task['updated_at'] = datetime.now(timezone.utc).isoformat()
                    task.setdefault('notes', []).append({
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'session_id': self.session_id,
                        'note': 'Undone: task completion reverted',
                    })
                    result = {'success': True, 'action': 'undo_complete', 'task_id': task_id}
                    break

        elif event == 'task_deleted':
            # Restore deleted task
            restored_task = undo_data.get('task')
            if restored_task:
                restored_task['updated_at'] = datetime.now(timezone.utc).isoformat()
                restored_task.setdefault('notes', []).append({
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'session_id': self.session_id,
                    'note': 'Undone: task restored from deletion',
                })
                data['tasks'].append(restored_task)
                result = {'success': True, 'action': 'undo_delete', 'task_id': task_id}

        elif event == 'task_edited':
            # Restore previous field values
            for task in data['tasks']:
                if task['id'] == task_id:
                    previous = undo_data.get('previous', {})
                    for field, value in previous.items():
                        task[field] = value
                    task['updated_at'] = datetime.now(timezone.utc).isoformat()
                    task.setdefault('notes', []).append({
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'session_id': self.session_id,
                        'note': 'Undone: edit reverted',
                    })
                    result = {'success': True, 'action': 'undo_edit', 'task_id': task_id}
                    break

        elif event == 'task_reopened':
            # Restore task to previous status (before reopen)
            for task in data['tasks']:
                if task['id'] == task_id:
                    task['status'] = undo_data.get('previous_status', 'done')
                    task['updated_at'] = datetime.now(timezone.utc).isoformat()
                    task.setdefault('notes', []).append({
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'session_id': self.session_id,
                        'note': 'Undone: reopen reverted',
                    })
                    result = {'success': True, 'action': 'undo_reopen', 'task_id': task_id}
                    break

        if result:
            self._save_tasks(data)
            self._log_event('action_undone', {
                'original_event': event,
                'task_id': task_id,
            })

        return result

    # ========================================================================
    # Parallel Mode Management
    # ========================================================================

    def start_parallel_mode(self, port: int = 8765) -> bool:
        """
        Start parallel mode by launching coordinator and creating flag file.
        Call this from the main session when spawning workers.
        """
        if self._parallel_mode:
            return True  # Already in parallel mode

        # Ensure state directory exists
        self.state_dir.mkdir(parents=True, exist_ok=True)

        # Write flag file
        flag_file = self.state_dir / '.parallel-mode'
        flag_file.write_text(json.dumps({
            'port': port,
            'started_at': datetime.now(timezone.utc).isoformat(),
            'main_session': self.session_id,
        }))

        # Start coordinator in background
        # Try to find coordinator module
        try:
            from claudia import coordinator
            coordinator_path = coordinator.__file__
        except ImportError:
            # Fallback to same directory as this file
            coordinator_path = Path(__file__).parent / 'coordinator.py'

        state_path = self.state_dir / 'tasks.json'

        subprocess.Popen(
            [sys.executable, str(coordinator_path), '--port', str(port), '--state', str(state_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        # Wait for coordinator to be ready (up to 5 seconds)
        for attempt in range(10):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(0.5)
                    sock.connect(('127.0.0.1', port))
                    # Connection successful - coordinator is listening
                    break
            except (ConnectionRefusedError, socket.timeout, OSError):
                time.sleep(0.5)
        else:
            # Cleanup flag file on failure
            if flag_file.exists():
                flag_file.unlink()
            raise RuntimeError(f"Coordinator failed to start on port {port} within 5 seconds")

        # Update our mode
        self._parallel_mode = True
        self._coordinator_port = port

        # Re-register as main
        self.register(context=self.context, labels=self.labels, role='main')

        return True

    def stop_parallel_mode(self) -> bool:
        """
        Stop parallel mode. Call from main session after workers finish.
        """
        if not self._parallel_mode:
            return True

        # Gracefully stop coordinator
        pid_file = self.state_dir / 'coordinator.pid'
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text())
                # First try SIGTERM for graceful shutdown
                os.kill(pid, signal.SIGTERM)
                # Wait up to 2 seconds for graceful shutdown
                for _ in range(4):
                    time.sleep(0.5)
                    try:
                        os.kill(pid, 0)  # Check if process still exists
                    except OSError:
                        break  # Process is gone
                else:
                    # Process still running, force kill
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except OSError:
                        pass
            except (ValueError, OSError, ProcessLookupError):
                pass  # Process already dead or PID invalid
            try:
                pid_file.unlink()
            except OSError:
                pass

        # Remove flag file
        flag_file = self.state_dir / '.parallel-mode'
        if flag_file.exists():
            try:
                flag_file.unlink()
            except OSError:
                pass

        self._parallel_mode = False
        return True

    def get_parallel_summary(self) -> dict:
        """Get summary of parallel work (for merge phase)."""
        if self._parallel_mode:
            return self._request('GET', '/parallel-summary')
        else:
            # Single mode: just return completed tasks
            data = self._load_tasks()
            completed = [t for t in data['tasks'] if t.get('status') == 'done']
            by_branch = {}
            for t in completed:
                branch = t.get('branch', 'main')
                if branch not in by_branch:
                    by_branch[branch] = []
                by_branch[branch].append({
                    'id': t['id'],
                    'title': t['title'],
                    'notes': t.get('notes', [])[-3:],
                })
            return {
                'total_completed': len(completed),
                'branches': by_branch,
                'branches_to_merge': [b for b in by_branch if b != 'main'],
            }
