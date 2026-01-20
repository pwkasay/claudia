"""
Tests for the Agent class (single mode).
"""

import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from claudia.agent import Agent, is_task_ready


class TestAgentBasics:
    """Basic Agent functionality tests."""

    def test_agent_init(self, agent):
        """Test Agent initialization."""
        assert agent is not None
        assert agent.get_mode() == 'single'
        assert not agent.is_parallel_mode()

    def test_get_status_empty(self, agent):
        """Test get_status with no tasks."""
        status = agent.get_status()
        assert status['mode'] == 'single'
        assert status['total_tasks'] == 0
        assert status['ready_tasks'] == 0

    def test_get_status_with_tasks(self, agent_with_tasks):
        """Test get_status with sample tasks."""
        status = agent_with_tasks.get_status()
        assert status['total_tasks'] == 4
        assert status['tasks_by_status']['open'] == 3
        assert status['tasks_by_status']['done'] == 1
        # task-001 and task-002 are ready, task-003 is blocked
        assert status['ready_tasks'] == 2


class TestTaskCRUD:
    """Task create, read, update, delete tests."""

    def test_create_task(self, agent):
        """Test creating a new task."""
        task = agent.create_task(
            title='Test task',
            description='A test',
            priority=1,
            labels=['test', 'unit']
        )

        assert task['id'] == 'task-001'
        assert task['title'] == 'Test task'
        assert task['description'] == 'A test'
        assert task['priority'] == 1
        assert task['labels'] == ['test', 'unit']
        assert task['status'] == 'open'
        assert task['assignee'] is None

    def test_get_tasks(self, agent_with_tasks):
        """Test getting all tasks."""
        tasks = agent_with_tasks.get_tasks()
        assert len(tasks) == 4

    def test_get_tasks_filtered(self, agent_with_tasks):
        """Test getting tasks filtered by status."""
        open_tasks = agent_with_tasks.get_tasks(status='open')
        assert len(open_tasks) == 3

        done_tasks = agent_with_tasks.get_tasks(status='done')
        assert len(done_tasks) == 1

    def test_edit_task(self, agent_with_tasks):
        """Test editing a task."""
        task = agent_with_tasks.edit_task(
            task_id='task-001',
            title='Updated title',
            priority=0,
            labels=['critical']
        )

        assert task['title'] == 'Updated title'
        assert task['priority'] == 0
        assert task['labels'] == ['critical']
        # Description should be unchanged
        assert task['description'] == 'Test task 1'

    def test_edit_task_not_found(self, agent_with_tasks):
        """Test editing a non-existent task."""
        task = agent_with_tasks.edit_task(
            task_id='task-999',
            title='No such task'
        )
        assert task is None

    def test_delete_task(self, agent_with_tasks):
        """Test deleting a task."""
        result = agent_with_tasks.delete_task('task-001')
        assert result['success'] is True

        tasks = agent_with_tasks.get_tasks()
        assert len(tasks) == 3
        assert not any(t['id'] == 'task-001' for t in tasks)

    def test_delete_task_not_found(self, agent_with_tasks):
        """Test deleting a non-existent task."""
        result = agent_with_tasks.delete_task('task-999')
        assert result.get('success') is not True


class TestTaskWorkflow:
    """Task workflow tests (claim, complete, reopen)."""

    def test_get_next_task(self, agent_with_tasks):
        """Test claiming the next task."""
        task = agent_with_tasks.get_next_task()

        # Should get task-001 (highest priority ready task)
        assert task['id'] == 'task-001'
        assert task['status'] == 'in_progress'
        assert task['assignee'] is not None

    def test_get_next_task_with_labels(self, agent_with_tasks):
        """Test claiming task with label preference."""
        # Note: Priority takes precedence over labels, so task-001 (P1) will be
        # picked before task-002 (P2) even with frontend preference
        task = agent_with_tasks.get_next_task(preferred_labels=['frontend'])

        # First task claimed (highest priority)
        assert task['id'] == 'task-001'

        # Claim another - now task-002 should be picked (frontend preference)
        task2 = agent_with_tasks.get_next_task(preferred_labels=['frontend'])
        assert task2['id'] == 'task-002'
        assert 'frontend' in task2['labels']

    def test_get_next_task_empty(self, agent):
        """Test get_next_task when no tasks available."""
        task = agent.get_next_task()
        assert task is None

    def test_complete_task(self, agent_with_tasks):
        """Test completing a task."""
        # First claim the task
        agent_with_tasks.get_next_task()

        result = agent_with_tasks.complete_task('task-001', note='Done!')
        assert result['success'] is True

        tasks = agent_with_tasks.get_tasks(status='done')
        task = next(t for t in tasks if t['id'] == 'task-001')
        assert task['status'] == 'done'

    def test_reopen_task(self, agent_with_tasks):
        """Test reopening a completed task."""
        success = agent_with_tasks.reopen_task('task-004', note='Need more work')
        assert success is True

        tasks = agent_with_tasks.get_tasks()
        task = next(t for t in tasks if t['id'] == 'task-004')
        assert task['status'] == 'open'
        assert task['assignee'] is None


class TestSubtasks:
    """Subtask functionality tests."""

    def test_create_subtask(self, agent_with_tasks):
        """Test creating a subtask."""
        subtask = agent_with_tasks.create_subtask(
            parent_id='task-001',
            title='Subtask 1',
            description='A subtask'
        )

        assert subtask is not None
        assert subtask['parent_id'] == 'task-001'
        assert subtask['is_subtask'] is True

        # Parent should have subtask in list
        tasks = agent_with_tasks.get_tasks()
        parent = next(t for t in tasks if t['id'] == 'task-001')
        assert subtask['id'] in parent['subtasks']

    def test_create_subtask_parent_not_found(self, agent_with_tasks):
        """Test creating subtask with invalid parent."""
        subtask = agent_with_tasks.create_subtask(
            parent_id='task-999',
            title='Orphan subtask'
        )
        assert subtask is None

    def test_get_subtasks(self, agent_with_tasks):
        """Test getting subtasks of a parent."""
        # Create some subtasks
        agent_with_tasks.create_subtask('task-001', 'Sub 1')
        agent_with_tasks.create_subtask('task-001', 'Sub 2')

        subtasks = agent_with_tasks.get_subtasks('task-001')
        assert len(subtasks) == 2

    def test_get_subtask_progress(self, agent_with_tasks):
        """Test getting subtask progress."""
        # Create subtasks
        agent_with_tasks.create_subtask('task-001', 'Sub 1')
        sub2 = agent_with_tasks.create_subtask('task-001', 'Sub 2')

        # Complete one subtask
        agent_with_tasks.get_next_task()  # Claim a task first
        # Mark subtask as done directly
        tasks_file = agent_with_tasks.state_dir / 'tasks.json'
        data = json.loads(tasks_file.read_text())
        for t in data['tasks']:
            if t['id'] == sub2['id']:
                t['status'] = 'done'
        tasks_file.write_text(json.dumps(data, indent=2))

        progress = agent_with_tasks.get_subtask_progress('task-001')
        assert progress['total'] == 2
        assert progress['completed'] == 1
        assert progress['percentage'] == 50


class TestTemplates:
    """Template functionality tests."""

    def test_list_templates_empty(self, agent):
        """Test listing templates when none exist."""
        templates = agent.list_templates()
        assert templates == []

    def test_create_template(self, agent):
        """Test creating a template."""
        template = agent.create_template(
            name='Feature Template',
            description='For new features',
            default_priority=2,
            default_labels=['feature'],
            subtasks=[
                {'title': 'Design'},
                {'title': 'Implement'},
                {'title': 'Test'}
            ]
        )

        assert template['id'] == 'template-001'
        assert template['name'] == 'Feature Template'
        assert len(template['subtasks']) == 3

    def test_get_template(self, agent, sample_template):
        """Test getting a template by ID."""
        template = agent.get_template('tpl-001')
        assert template is not None
        assert template['name'] == 'Bug Fix'

    def test_delete_template(self, agent, sample_template):
        """Test deleting a template."""
        success = agent.delete_template('tpl-001')
        assert success is True

        template = agent.get_template('tpl-001')
        assert template is None

    def test_create_from_template(self, agent, sample_template):
        """Test creating task from template."""
        task = agent.create_from_template(
            template_id='tpl-001',
            title='Fix login bug'
        )

        assert task is not None
        assert task['title'] == 'Fix login bug'
        assert task['priority'] == 1  # From template
        assert 'bug' in task['labels']  # From template
        assert len(task['subtasks']) == 4  # Template has 4 subtasks


class TestTimeTracking:
    """Time tracking functionality tests."""

    def test_start_timer(self, agent_with_tasks):
        """Test starting a timer."""
        task = agent_with_tasks.start_timer('task-001')
        assert task is not None

        tt = task.get('time_tracking', {})
        # Timer is running when started_at is set and paused_at is None
        assert tt.get('started_at') is not None
        assert tt.get('paused_at') is None

    def test_stop_timer(self, agent_with_tasks):
        """Test stopping a timer."""
        agent_with_tasks.start_timer('task-001')
        time.sleep(0.1)  # Small delay to accumulate time
        task = agent_with_tasks.stop_timer('task-001')

        tt = task.get('time_tracking', {})
        # Timer is stopped when started_at is None
        assert tt.get('started_at') is None
        assert tt.get('total_seconds', 0) > 0

    def test_pause_timer(self, agent_with_tasks):
        """Test pausing a timer."""
        agent_with_tasks.start_timer('task-001')
        time.sleep(0.1)
        task = agent_with_tasks.pause_timer('task-001')

        tt = task.get('time_tracking', {})
        # Timer is paused when paused_at is set
        assert tt.get('paused_at') is not None
        assert tt.get('started_at') is None
        assert tt.get('total_seconds', 0) > 0

    def test_get_task_time(self, agent_with_tasks):
        """Test getting task time info."""
        agent_with_tasks.start_timer('task-001')
        time.sleep(0.1)

        info = agent_with_tasks.get_task_time('task-001')
        assert info is not None
        assert info['is_running'] is True
        assert info['current_elapsed'] > 0

    def test_get_time_report(self, agent_with_tasks):
        """Test getting time report."""
        # Start and stop timer to record time
        agent_with_tasks.start_timer('task-001')
        time.sleep(0.1)
        agent_with_tasks.stop_timer('task-001')

        report = agent_with_tasks.get_time_report(by='task')
        assert 'items' in report
        assert 'total_seconds' in report


class TestBulkOperations:
    """Bulk operation tests."""

    def test_bulk_complete(self, agent_with_tasks):
        """Test bulk completing tasks."""
        # First claim the tasks
        agent_with_tasks.get_next_task()  # task-001
        agent_with_tasks.get_next_task()  # task-002

        result = agent_with_tasks.bulk_complete(['task-001', 'task-002'])
        assert len(result['succeeded']) == 2
        assert len(result['failed']) == 0

    def test_bulk_reopen(self, agent_with_tasks):
        """Test bulk reopening tasks."""
        result = agent_with_tasks.bulk_reopen(['task-004'])
        assert len(result['succeeded']) == 1


class TestArchiving:
    """Archiving functionality tests."""

    def test_archive_tasks_dry_run(self, agent_with_tasks):
        """Test archive dry run."""
        result = agent_with_tasks.archive_tasks(days_old=0, dry_run=True)
        assert result['archived'] == 1  # task-004 is done
        assert 'tasks' in result

    def test_archive_and_restore(self, agent_with_tasks):
        """Test archiving and restoring tasks."""
        # Archive done tasks
        result = agent_with_tasks.archive_tasks(days_old=0)
        assert result['archived'] == 1

        # List archived
        archived = agent_with_tasks.list_archived()
        assert len(archived) == 1
        assert archived[0]['id'] == 'task-004'

        # Restore
        task = agent_with_tasks.restore_from_archive('task-004')
        assert task is not None
        assert task['id'] == 'task-004'

        # Should be back in tasks
        tasks = agent_with_tasks.get_tasks()
        assert any(t['id'] == 'task-004' for t in tasks)


class TestIsTaskReady:
    """Tests for the is_task_ready function."""

    def test_ready_task(self):
        """Test that an open unblocked task is ready."""
        task = {'id': 't1', 'status': 'open', 'assignee': None, 'blocked_by': []}
        task_map = {'t1': task}
        assert is_task_ready(task, task_map) is True

    def test_assigned_task_not_ready(self):
        """Test that an assigned task is not ready."""
        task = {'id': 't1', 'status': 'open', 'assignee': 'session-1', 'blocked_by': []}
        task_map = {'t1': task}
        assert is_task_ready(task, task_map) is False

    def test_blocked_task_not_ready(self):
        """Test that a blocked task is not ready."""
        blocker = {'id': 't1', 'status': 'open', 'assignee': None, 'blocked_by': []}
        blocked = {'id': 't2', 'status': 'open', 'assignee': None, 'blocked_by': ['t1']}
        task_map = {'t1': blocker, 't2': blocked}
        assert is_task_ready(blocked, task_map) is False

    def test_unblocked_when_blocker_done(self):
        """Test that task becomes ready when blocker is done."""
        blocker = {'id': 't1', 'status': 'done', 'assignee': None, 'blocked_by': []}
        blocked = {'id': 't2', 'status': 'open', 'assignee': None, 'blocked_by': ['t1']}
        task_map = {'t1': blocker, 't2': blocked}
        assert is_task_ready(blocked, task_map) is True
