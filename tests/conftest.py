"""
Pytest configuration and shared fixtures for Claudia tests.
"""

import json
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_state_dir():
    """Create a temporary state directory for testing."""
    temp_dir = tempfile.mkdtemp()
    state_dir = Path(temp_dir) / '.agent-state'
    state_dir.mkdir(parents=True)
    (state_dir / 'sessions').mkdir()

    # Initialize empty tasks.json
    tasks_file = state_dir / 'tasks.json'
    tasks_file.write_text(json.dumps({
        'version': 2,
        'next_id': 1,
        'tasks': []
    }, indent=2))

    # Initialize empty history.jsonl
    (state_dir / 'history.jsonl').write_text('')

    yield state_dir

    # Cleanup
    shutil.rmtree(temp_dir)


@pytest.fixture
def agent(temp_state_dir):
    """Create an Agent instance for testing."""
    from claudia.agent import Agent
    return Agent(state_dir=temp_state_dir)


@pytest.fixture
def sample_tasks(temp_state_dir):
    """Create sample tasks for testing."""
    tasks = [
        {
            'id': 'task-001',
            'title': 'First task',
            'description': 'Test task 1',
            'status': 'open',
            'priority': 1,
            'labels': ['backend', 'urgent'],
            'assignee': None,
            'blocked_by': [],
            'notes': [],
            'created_at': '2024-01-15T10:00:00Z',
            'updated_at': '2024-01-15T10:00:00Z',
            'parent_id': None,
            'subtasks': [],
            'is_subtask': False,
            'time_tracking': None
        },
        {
            'id': 'task-002',
            'title': 'Second task',
            'description': 'Test task 2',
            'status': 'open',
            'priority': 2,
            'labels': ['frontend'],
            'assignee': None,
            'blocked_by': [],
            'notes': [],
            'created_at': '2024-01-15T11:00:00Z',
            'updated_at': '2024-01-15T11:00:00Z',
            'parent_id': None,
            'subtasks': [],
            'is_subtask': False,
            'time_tracking': None
        },
        {
            'id': 'task-003',
            'title': 'Blocked task',
            'description': 'This task is blocked',
            'status': 'open',
            'priority': 2,
            'labels': ['backend'],
            'assignee': None,
            'blocked_by': ['task-001'],
            'notes': [],
            'created_at': '2024-01-15T12:00:00Z',
            'updated_at': '2024-01-15T12:00:00Z',
            'parent_id': None,
            'subtasks': [],
            'is_subtask': False,
            'time_tracking': None
        },
        {
            'id': 'task-004',
            'title': 'Done task',
            'description': 'This task is done',
            'status': 'done',
            'priority': 3,
            'labels': ['docs'],
            'assignee': None,
            'blocked_by': [],
            'notes': [{'timestamp': '2024-01-15T13:00:00Z', 'note': 'Completed'}],
            'created_at': '2024-01-15T09:00:00Z',
            'updated_at': '2024-01-15T13:00:00Z',
            'parent_id': None,
            'subtasks': [],
            'is_subtask': False,
            'time_tracking': None
        }
    ]

    tasks_file = temp_state_dir / 'tasks.json'
    tasks_file.write_text(json.dumps({
        'version': 2,
        'next_id': 5,
        'tasks': tasks
    }, indent=2))

    return tasks


@pytest.fixture
def agent_with_tasks(temp_state_dir, sample_tasks):
    """Create an Agent instance with sample tasks."""
    from claudia.agent import Agent
    return Agent(state_dir=temp_state_dir)


@pytest.fixture
def sample_template(temp_state_dir):
    """Create a sample template for testing."""
    templates = [
        {
            'id': 'tpl-001',
            'name': 'Bug Fix',
            'description': 'Standard bug fix template',
            'default_priority': 1,
            'default_labels': ['bug'],
            'subtasks': [
                {'title': 'Reproduce the bug'},
                {'title': 'Write failing test'},
                {'title': 'Fix the bug'},
                {'title': 'Verify fix'}
            ]
        }
    ]

    templates_file = temp_state_dir / 'templates.json'
    templates_file.write_text(json.dumps({
        'version': 1,
        'next_id': 2,
        'templates': templates
    }, indent=2))

    return templates[0]
