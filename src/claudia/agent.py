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
import signal
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


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

    def _request(self, method: str, path: str, data: dict = None) -> dict:
        """Make HTTP request to coordinator."""
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
        except socket.timeout:
            raise RuntimeError("Coordinator request timed out")
        except ConnectionRefusedError:
            raise RuntimeError("Coordinator not running or connection refused")
        except OSError as e:
            raise RuntimeError(f"Network error communicating with coordinator: {e}")

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

    def _load_tasks(self) -> dict:
        """Load tasks from JSON file."""
        # First check for orphaned tmp files from crash recovery
        self._recover_tmp_file()

        tasks_file = self.state_dir / 'tasks.json'
        if tasks_file.exists():
            return json.loads(tasks_file.read_text())
        return {'version': 1, 'next_id': 1, 'tasks': []}

    def _save_tasks(self, data: dict):
        """Save tasks to JSON file."""
        tasks_file = self.state_dir / 'tasks.json'
        tasks_file.parent.mkdir(parents=True, exist_ok=True)
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

    def get_next_task(self, preferred_labels: list = None) -> Optional[dict]:
        """
        Get the next available task.

        In parallel mode: coordinator assigns atomically
        In single mode: finds and claims directly
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

    def complete_task(self, task_id: str, note: str = "", branch: str = None) -> bool:
        """Mark a task as complete."""
        if self._parallel_mode:
            result = self._request('POST', '/task/complete', {
                'task_id': task_id,
                'session_id': self.session_id,
                'note': note,
                'branch': branch,
            })
            return result.get('success', False)
        else:
            data = self._load_tasks()
            for task in data['tasks']:
                if task['id'] == task_id:
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

                    # Log to history
                    self._log_event('task_completed', {'task_id': task_id, 'note': note})
                    return True
            return False

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

                    # Log to history
                    self._log_event('task_reopened', {'task_id': task_id, 'note': note})
                    return True
            return False

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

    def get_status(self) -> dict:
        """Get system status."""
        if self._parallel_mode:
            result = self._request('GET', '/status')
            result['mode'] = 'parallel'
            return result
        else:
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

    def _log_event(self, event: str, details: dict = None):
        """Append to history log."""
        history_file = self.state_dir / 'history.jsonl'
        entry = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'event': event,
            'session_id': self.session_id,
            **(details or {}),
        }
        with open(history_file, 'a') as f:
            f.write(json.dumps(entry) + '\n')

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
