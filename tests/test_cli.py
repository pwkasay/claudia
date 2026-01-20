"""
Tests for the CLI module.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest


class TestCLICommands:
    """Test CLI commands via subprocess."""

    def test_cli_help(self):
        """Test --help flag."""
        result = subprocess.run(
            [sys.executable, '-m', 'claudia.cli', '--help'],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert 'claudia' in result.stdout.lower()

    def test_cli_version(self):
        """Test --version flag."""
        result = subprocess.run(
            [sys.executable, '-m', 'claudia.cli', '--version'],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0

    def test_cli_status(self, temp_state_dir):
        """Test status command."""
        result = subprocess.run(
            [sys.executable, '-m', 'claudia.cli', '--state-dir', str(temp_state_dir), 'status'],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert 'Mode:' in result.stdout

    def test_cli_status_json(self, temp_state_dir):
        """Test status command with JSON output."""
        result = subprocess.run(
            [sys.executable, '-m', 'claudia.cli', '--state-dir', str(temp_state_dir), '--json', 'status'],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert 'mode' in data
        assert 'total_tasks' in data

    def test_cli_create(self, temp_state_dir):
        """Test create command."""
        result = subprocess.run(
            [sys.executable, '-m', 'claudia.cli', '--state-dir', str(temp_state_dir),
             'create', 'Test task', '-p', '1', '-l', 'test'],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert 'Created' in result.stdout

    def test_cli_create_json(self, temp_state_dir):
        """Test create command with JSON output."""
        result = subprocess.run(
            [sys.executable, '-m', 'claudia.cli', '--state-dir', str(temp_state_dir),
             '--json', 'create', 'Test task', '-p', '1'],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data['id'] == 'task-001'
        assert data['title'] == 'Test task'

    def test_cli_tasks(self, temp_state_dir, sample_tasks):
        """Test tasks command."""
        result = subprocess.run(
            [sys.executable, '-m', 'claudia.cli', '--state-dir', str(temp_state_dir), 'tasks'],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert 'task-001' in result.stdout

    def test_cli_tasks_filtered(self, temp_state_dir, sample_tasks):
        """Test tasks command with status filter."""
        result = subprocess.run(
            [sys.executable, '-m', 'claudia.cli', '--state-dir', str(temp_state_dir),
             'tasks', '--status', 'done'],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert 'task-004' in result.stdout
        assert 'task-001' not in result.stdout

    def test_cli_show(self, temp_state_dir, sample_tasks):
        """Test show command."""
        result = subprocess.run(
            [sys.executable, '-m', 'claudia.cli', '--state-dir', str(temp_state_dir),
             'show', 'task-001'],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert 'First task' in result.stdout
        assert 'P1' in result.stdout

    def test_cli_dry_run(self, temp_state_dir, sample_tasks):
        """Test --dry-run flag."""
        result = subprocess.run(
            [sys.executable, '-m', 'claudia.cli', '--state-dir', str(temp_state_dir),
             '--dry-run', 'next'],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert 'Would claim' in result.stdout

        # Verify task wasn't actually claimed
        result2 = subprocess.run(
            [sys.executable, '-m', 'claudia.cli', '--state-dir', str(temp_state_dir),
             '--json', 'tasks', '--status', 'in_progress'],
            capture_output=True,
            text=True
        )
        data = json.loads(result2.stdout)
        assert len(data) == 0


class TestCLISubtasks:
    """Test subtask CLI commands."""

    def test_subtask_create(self, temp_state_dir, sample_tasks):
        """Test subtask create command."""
        result = subprocess.run(
            [sys.executable, '-m', 'claudia.cli', '--state-dir', str(temp_state_dir),
             'subtask', 'create', 'task-001', 'Subtask title'],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert 'Created subtask' in result.stdout

    def test_subtask_list(self, temp_state_dir, sample_tasks):
        """Test subtask list command."""
        # First create a subtask
        subprocess.run(
            [sys.executable, '-m', 'claudia.cli', '--state-dir', str(temp_state_dir),
             'subtask', 'create', 'task-001', 'Sub 1'],
            capture_output=True,
            text=True
        )

        result = subprocess.run(
            [sys.executable, '-m', 'claudia.cli', '--state-dir', str(temp_state_dir),
             'subtask', 'list', 'task-001'],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert 'Sub 1' in result.stdout


class TestCLITemplates:
    """Test template CLI commands."""

    def test_template_create(self, temp_state_dir):
        """Test template create command."""
        result = subprocess.run(
            [sys.executable, '-m', 'claudia.cli', '--state-dir', str(temp_state_dir),
             'template', 'create', 'My Template', '-p', '1', '-s', 'Step 1', '-s', 'Step 2'],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert 'Created template' in result.stdout

    def test_template_list(self, temp_state_dir, sample_template):
        """Test template list command."""
        result = subprocess.run(
            [sys.executable, '-m', 'claudia.cli', '--state-dir', str(temp_state_dir),
             'template', 'list'],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert 'Bug Fix' in result.stdout


class TestCLITime:
    """Test time tracking CLI commands."""

    def test_time_start_stop(self, temp_state_dir, sample_tasks):
        """Test time start and stop commands."""
        # Start timer
        result = subprocess.run(
            [sys.executable, '-m', 'claudia.cli', '--state-dir', str(temp_state_dir),
             'time', 'start', 'task-001'],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert 'Timer started' in result.stdout

        # Stop timer
        result = subprocess.run(
            [sys.executable, '-m', 'claudia.cli', '--state-dir', str(temp_state_dir),
             'time', 'stop', 'task-001'],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert 'Timer stopped' in result.stdout

    def test_time_report(self, temp_state_dir, sample_tasks):
        """Test time report command."""
        result = subprocess.run(
            [sys.executable, '-m', 'claudia.cli', '--state-dir', str(temp_state_dir),
             'time', 'report', '--by', 'task'],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert 'Time Report' in result.stdout


class TestCLIArchive:
    """Test archive CLI commands."""

    def test_archive_dry_run(self, temp_state_dir, sample_tasks):
        """Test archive run with dry-run."""
        result = subprocess.run(
            [sys.executable, '-m', 'claudia.cli', '--state-dir', str(temp_state_dir),
             '--dry-run', 'archive', 'run', '--days', '0'],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert 'Would archive' in result.stdout

    def test_archive_list(self, temp_state_dir, sample_tasks):
        """Test archive list command."""
        # First archive some tasks
        subprocess.run(
            [sys.executable, '-m', 'claudia.cli', '--state-dir', str(temp_state_dir),
             'archive', 'run', '--days', '0'],
            capture_output=True,
            text=True
        )

        result = subprocess.run(
            [sys.executable, '-m', 'claudia.cli', '--state-dir', str(temp_state_dir),
             'archive', 'list'],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0


class TestCLIEdit:
    """Test edit CLI commands."""

    def test_edit_task(self, temp_state_dir, sample_tasks):
        """Test edit command."""
        result = subprocess.run(
            [sys.executable, '-m', 'claudia.cli', '--state-dir', str(temp_state_dir),
             'edit', 'task-001', '--title', 'New Title', '--priority', '0'],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert 'Updated' in result.stdout

        # Verify change
        result2 = subprocess.run(
            [sys.executable, '-m', 'claudia.cli', '--state-dir', str(temp_state_dir),
             '--json', 'show', 'task-001'],
            capture_output=True,
            text=True
        )
        data = json.loads(result2.stdout)
        assert data['title'] == 'New Title'
        assert data['priority'] == 0


class TestCLIDelete:
    """Test delete CLI commands."""

    def test_delete_task(self, temp_state_dir, sample_tasks):
        """Test delete command."""
        result = subprocess.run(
            [sys.executable, '-m', 'claudia.cli', '--state-dir', str(temp_state_dir),
             'delete', 'task-001'],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert 'Deleted' in result.stdout

    def test_delete_dry_run(self, temp_state_dir, sample_tasks):
        """Test delete with dry-run."""
        result = subprocess.run(
            [sys.executable, '-m', 'claudia.cli', '--state-dir', str(temp_state_dir),
             '--dry-run', 'delete', 'task-001'],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert 'Would delete' in result.stdout

        # Verify task still exists
        result2 = subprocess.run(
            [sys.executable, '-m', 'claudia.cli', '--state-dir', str(temp_state_dir),
             'show', 'task-001'],
            capture_output=True,
            text=True
        )
        assert 'First task' in result2.stdout
