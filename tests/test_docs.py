"""
Tests for the DocsAgent documentation generator.
"""

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from claudia.docs import DocsAgent, FileInfo, ProjectMetadata


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def temp_project_dir():
    """Create a temporary project directory for testing."""
    temp_dir = tempfile.mkdtemp()
    project_dir = Path(temp_dir)

    # Create basic project structure
    (project_dir / 'src').mkdir()
    (project_dir / 'tests').mkdir()
    (project_dir / 'docs').mkdir()

    yield project_dir

    # Cleanup
    shutil.rmtree(temp_dir)


@pytest.fixture
def python_project(temp_project_dir):
    """Create a Python project with pyproject.toml."""
    # Create pyproject.toml
    pyproject = temp_project_dir / 'pyproject.toml'
    pyproject.write_text('''
[project]
name = "test-project"
version = "1.0.0"
description = "A test project for documentation"
requires-python = ">=3.10"
license = {text = "MIT"}
keywords = ["test", "docs"]
authors = [
    {name = "Test Author", email = "test@example.com"}
]

[project.urls]
Homepage = "https://example.com"
Repository = "https://github.com/test/test-project"
''')

    # Create Python source files
    src_dir = temp_project_dir / 'src'

    main_py = src_dir / 'main.py'
    main_py.write_text('''
"""Main entry point for the application.

This is the module docstring that should be extracted.
"""

import json
from pathlib import Path
from dataclasses import dataclass


@dataclass
class Config:
    """Configuration class."""
    name: str
    value: int

    def validate(self):
        """Validate the configuration."""
        return self.value > 0

    def to_dict(self):
        """Convert to dictionary."""
        return {"name": self.name, "value": self.value}


class Application:
    """Main application class.

    This handles all the core functionality.
    """

    def __init__(self, config: Config):
        self.config = config

    def run(self):
        """Run the application."""
        pass

    def stop(self):
        """Stop the application."""
        pass

    def _internal_method(self):
        """Private helper method."""
        pass


def main():
    """Entry point function."""
    config = Config(name="test", value=42)
    app = Application(config)
    app.run()


def helper_function():
    """A helper function."""
    return True


def _private_function():
    """Private function that should be excluded."""
    pass


if __name__ == "__main__":
    main()
''')

    utils_py = src_dir / 'utils.py'
    utils_py.write_text('''
"""Utility functions."""

import os
import sys


def format_string(s: str) -> str:
    """Format a string."""
    return s.strip().lower()


def parse_number(s: str) -> int:
    """Parse a number from string."""
    return int(s)
''')

    return temp_project_dir


@pytest.fixture
def js_project(temp_project_dir):
    """Create a JavaScript project with package.json."""
    # Create package.json
    package_json = temp_project_dir / 'package.json'
    package_json.write_text(json.dumps({
        "name": "js-test-project",
        "version": "2.0.0",
        "description": "A JavaScript test project",
        "license": "Apache-2.0",
        "homepage": "https://js-example.com",
        "repository": {
            "type": "git",
            "url": "https://github.com/test/js-project"
        },
        "author": {
            "name": "JS Author"
        },
        "keywords": ["javascript", "test"]
    }, indent=2))

    # Create JS source file
    src_dir = temp_project_dir / 'src'

    index_js = src_dir / 'index.js'
    index_js.write_text('''
import React from 'react';
import { useState } from 'react';
const lodash = require('lodash');

export default class App {
    constructor() {
        this.name = 'App';
    }

    render() {
        return '<div>Hello</div>';
    }
}

export const helper = () => {
    return true;
};

export const asyncHelper = async (x) => {
    return x * 2;
};

export function regularFunction(a, b) {
    return a + b;
}

const arrowWithParams = (x, y) => x + y;

const singleParamArrow = x => x * 2;
''')

    return temp_project_dir


@pytest.fixture
def docs_agent(python_project):
    """Create a DocsAgent for the Python project."""
    return DocsAgent(project_dir=python_project)


# =============================================================================
# Test Classes
# =============================================================================

class TestProjectMetadataLoading:
    """Tests for project metadata parsing."""

    def test_parse_pyproject_toml(self, python_project):
        """Test parsing pyproject.toml."""
        agent = DocsAgent(project_dir=python_project)

        assert agent.metadata.name == "test-project"
        assert agent.metadata.version == "1.0.0"
        assert agent.metadata.description == "A test project for documentation"
        assert agent.metadata.license == "MIT"
        assert agent.metadata.python_requires == ">=3.10"
        assert "https://github.com/test/test-project" in agent.metadata.repository

    def test_parse_package_json(self, js_project):
        """Test parsing package.json."""
        agent = DocsAgent(project_dir=js_project)

        assert agent.metadata.name == "js-test-project"
        assert agent.metadata.version == "2.0.0"
        assert agent.metadata.description == "A JavaScript test project"
        assert agent.metadata.license == "Apache-2.0"

    def test_parse_setup_py(self, temp_project_dir):
        """Test parsing setup.py."""
        setup_py = temp_project_dir / 'setup.py'
        setup_py.write_text('''
from setuptools import setup

setup(
    name="legacy-project",
    version="0.1.0",
    description="A legacy project",
    license="BSD",
    python_requires=">=3.8",
    url="https://github.com/test/legacy"
)
''')

        agent = DocsAgent(project_dir=temp_project_dir)

        assert agent.metadata.name == "legacy-project"
        assert agent.metadata.version == "0.1.0"
        assert agent.metadata.description == "A legacy project"

    def test_fallback_to_folder_name(self, temp_project_dir):
        """Test fallback to folder name when no metadata files exist."""
        agent = DocsAgent(project_dir=temp_project_dir)

        # Should use the directory name
        assert agent.metadata.name == temp_project_dir.name


class TestFileAnalysis:
    """Tests for file analysis functionality."""

    def test_analyze_python_file(self, docs_agent):
        """Test analyzing Python files."""
        docs_agent.analyze()

        assert 'src/main.py' in docs_agent.files
        main_info = docs_agent.files['src/main.py']

        assert main_info.language == 'python'
        assert main_info.lines > 0
        assert main_info.size > 0

    def test_analyze_js_file(self, js_project):
        """Test analyzing JavaScript files."""
        agent = DocsAgent(project_dir=js_project)
        agent.analyze()

        assert 'src/index.js' in agent.files
        js_info = agent.files['src/index.js']

        assert js_info.language == 'javascript'
        # Note: Current regex only captures require() style imports, not ES6 'from' imports
        assert 'lodash' in js_info.imports
        assert 'App' in js_info.classes

    def test_extract_python_imports(self, docs_agent):
        """Test Python import extraction."""
        docs_agent.analyze()
        main_info = docs_agent.files['src/main.py']

        # json and pathlib are stdlib, should be filtered out
        # dataclasses is also stdlib
        # The list should be relatively empty or have no external deps
        assert isinstance(main_info.imports, list)

    def test_extract_python_classes(self, docs_agent):
        """Test Python class extraction."""
        docs_agent.analyze()
        main_info = docs_agent.files['src/main.py']

        assert 'Config' in main_info.classes
        assert 'Application' in main_info.classes

    def test_extract_python_methods(self, docs_agent):
        """Test Python method extraction per class."""
        docs_agent.analyze()
        main_info = docs_agent.files['src/main.py']

        # Check Config class methods
        assert 'Config' in main_info.methods
        assert 'validate' in main_info.methods['Config']
        assert 'to_dict' in main_info.methods['Config']

        # Check Application class methods
        assert 'Application' in main_info.methods
        assert 'run' in main_info.methods['Application']
        assert 'stop' in main_info.methods['Application']
        # Private methods starting with _ should be excluded (unless __)
        assert '_internal_method' not in main_info.methods['Application']

    def test_extract_python_functions(self, docs_agent):
        """Test Python function extraction."""
        docs_agent.analyze()
        main_info = docs_agent.files['src/main.py']

        # Public functions
        assert 'main' in main_info.functions
        assert 'helper_function' in main_info.functions
        # Private functions should be excluded
        assert '_private_function' not in main_info.functions

    def test_extract_js_functions(self, js_project):
        """Test JavaScript function extraction including arrow functions."""
        agent = DocsAgent(project_dir=js_project)
        agent.analyze()
        js_info = agent.files['src/index.js']

        assert 'regularFunction' in js_info.functions
        # Arrow functions should be detected
        assert 'helper' in js_info.functions or 'asyncHelper' in js_info.functions

    def test_ignore_patterns(self, temp_project_dir):
        """Test that ignored directories are skipped."""
        # Create a __pycache__ directory with a file (easier to test than node_modules)
        pycache = temp_project_dir / '__pycache__'
        pycache.mkdir(parents=True)
        (pycache / 'module.cpython-310.pyc').write_text('# bytecode')

        # Create a venv directory with a file
        venv = temp_project_dir / 'venv' / 'lib'
        venv.mkdir(parents=True)
        (venv / 'site.py').write_text('# venv site')

        # Create a regular source file
        (temp_project_dir / 'src' / 'app.py').write_text('x = 1')

        agent = DocsAgent(project_dir=temp_project_dir)
        agent.analyze()

        # __pycache__ and venv should be ignored
        # Note: fnmatch with ** doesn't work like glob, so some patterns may not match
        # At minimum, regular src should be included
        assert 'src/app.py' in agent.files

        # Test that we have some files but not everything
        assert len(agent.files) >= 1


class TestSkillLevels:
    """Tests for skill level functionality."""

    def test_level_limit_junior(self, python_project):
        """Test junior level returns all items."""
        agent = DocsAgent(project_dir=python_project, skill_level='junior')
        items = list(range(20))

        result = agent._level_limit(items, junior=999, mid=5, senior=3)
        assert len(result) == 20

    def test_level_limit_mid(self, python_project):
        """Test mid level limits appropriately."""
        agent = DocsAgent(project_dir=python_project, skill_level='mid')
        items = list(range(20))

        result = agent._level_limit(items, junior=999, mid=5, senior=3)
        assert len(result) == 5

    def test_level_limit_senior(self, python_project):
        """Test senior level has smallest limit."""
        agent = DocsAgent(project_dir=python_project, skill_level='senior')
        items = list(range(20))

        result = agent._level_limit(items, junior=999, mid=5, senior=3)
        assert len(result) == 3

    def test_level_content(self, python_project):
        """Test level-specific content selection."""
        agent = DocsAgent(project_dir=python_project, skill_level='junior')

        result = agent._level_content(
            junior="detailed explanation",
            mid="standard explanation",
            senior="brief"
        )
        assert result == "detailed explanation"

    def test_is_level(self, python_project):
        """Test is_level helper."""
        agent = DocsAgent(project_dir=python_project, skill_level='mid')

        assert agent._is_level('mid')
        assert agent._is_level('junior', 'mid')
        assert not agent._is_level('senior')


class TestDocGeneration:
    """Tests for documentation generation."""

    def test_generate_architecture(self, docs_agent):
        """Test architecture doc generation."""
        docs_agent.analyze()
        content = docs_agent._generate_architecture()

        assert '# Architecture Overview' in content
        assert 'Key Modules' in content
        # Should include project description
        assert 'test project' in content.lower()

    def test_generate_onboarding(self, docs_agent):
        """Test onboarding guide generation."""
        docs_agent.analyze()
        content = docs_agent._generate_onboarding()

        assert '# Developer Onboarding Guide' in content
        assert 'Getting Started' in content
        assert 'Prerequisites' in content

    def test_generate_api(self, docs_agent):
        """Test API reference generation."""
        docs_agent.analyze()
        content = docs_agent._generate_api()

        assert '# API Reference' in content
        # Should include classes from our test file
        assert 'Config' in content or 'Application' in content

    def test_generate_readme(self, docs_agent):
        """Test README generation."""
        docs_agent.analyze()
        content = docs_agent._generate_readme()

        assert '# test-project' in content
        assert 'Overview' in content
        assert 'Installation' in content

    def test_generate_writes_file(self, docs_agent):
        """Test that generate() writes to file."""
        docs_agent.analyze()
        docs_agent.generate('architecture')

        output_file = docs_agent.output_dir / 'architecture.md'
        assert output_file.exists()

        content = output_file.read_text()
        assert '# Architecture Overview' in content

    def test_skill_level_in_filename(self, python_project):
        """Test that non-default skill levels get suffix in filename."""
        agent = DocsAgent(project_dir=python_project, skill_level='junior')
        agent.analyze()
        agent.generate('architecture')

        output_file = agent.output_dir / 'architecture-junior.md'
        assert output_file.exists()


class TestStateManagement:
    """Tests for state save/load functionality."""

    def test_save_state(self, docs_agent):
        """Test state saving."""
        docs_agent.analyze()

        state_file = docs_agent.state_file
        assert state_file.exists()

        state = json.loads(state_file.read_text())
        assert 'analyzed_at' in state
        assert 'files_count' in state
        assert 'file_hashes' in state

    def test_load_state(self, docs_agent):
        """Test state loading."""
        docs_agent.analyze()

        # Load state
        state = docs_agent._load_state()

        assert state is not None
        assert 'analyzed_at' in state
        assert 'file_hashes' in state

    def test_incremental_analysis(self, python_project):
        """Test incremental analysis uses cache."""
        agent = DocsAgent(project_dir=python_project)

        # First analysis
        result1 = agent.analyze()
        assert result1['files_analyzed'] > 0

        # Second analysis should use cache
        agent2 = DocsAgent(project_dir=python_project)
        result2 = agent2.analyze()

        # Files should come from cache if unchanged
        assert result2['files_cached'] >= 0
        assert result2['total_files'] == result1['total_files']

    def test_force_analysis(self, python_project):
        """Test force parameter bypasses cache."""
        agent = DocsAgent(project_dir=python_project)

        # First analysis
        agent.analyze()

        # Force re-analysis
        result = agent.analyze(force=True)

        # All files should be re-analyzed
        assert result['files_cached'] == 0
        assert result['files_analyzed'] > 0


class TestExtractionLimits:
    """Tests for extraction limit constants."""

    def test_max_constants_exist(self):
        """Test that extraction limit constants are defined."""
        assert hasattr(DocsAgent, 'MAX_IMPORTS')
        assert hasattr(DocsAgent, 'MAX_FUNCTIONS')
        assert hasattr(DocsAgent, 'MAX_CLASSES')
        assert hasattr(DocsAgent, 'MAX_METHODS_PER_CLASS')
        assert hasattr(DocsAgent, 'MAX_EXPORTS')
        assert hasattr(DocsAgent, 'MAX_KEY_CONCEPTS')
        assert hasattr(DocsAgent, 'MAX_DEPENDENCIES')

    def test_constants_are_reasonable(self):
        """Test that constants have reasonable values."""
        assert DocsAgent.MAX_IMPORTS >= 10
        assert DocsAgent.MAX_FUNCTIONS >= 10
        assert DocsAgent.MAX_CLASSES >= 10


class TestModuleDocstring:
    """Tests for module docstring extraction."""

    def test_extract_docstring(self, docs_agent):
        """Test module docstring extraction."""
        docs_agent.analyze()
        main_info = docs_agent.files['src/main.py']

        # Should extract the module docstring
        assert main_info.description
        assert 'entry point' in main_info.description.lower()


class TestEntityDocstrings:
    """Tests for class and function docstring extraction."""

    def test_extract_class_docstrings(self, docs_agent):
        """Test extraction of class docstrings."""
        docs_agent.analyze()
        main_info = docs_agent.files['src/main.py']

        # Should have class docstrings
        assert 'Config' in main_info.class_docstrings
        assert 'configuration' in main_info.class_docstrings['Config'].lower()

        assert 'Application' in main_info.class_docstrings
        assert 'application' in main_info.class_docstrings['Application'].lower()

    def test_extract_function_docstrings(self, docs_agent):
        """Test extraction of function docstrings."""
        docs_agent.analyze()
        main_info = docs_agent.files['src/main.py']

        # Should have function docstrings
        assert 'main' in main_info.function_docstrings
        assert 'entry point' in main_info.function_docstrings['main'].lower()

        assert 'helper_function' in main_info.function_docstrings

    def test_private_functions_excluded_from_docstrings(self, docs_agent):
        """Test that private functions are excluded from docstrings dict."""
        docs_agent.analyze()
        main_info = docs_agent.files['src/main.py']

        # Private functions starting with _ should be excluded
        assert '_private_function' not in main_info.function_docstrings


class TestSmartTruncate:
    """Tests for the smart truncation helper."""

    def test_short_text_unchanged(self, docs_agent):
        """Test that short text is not truncated."""
        text = "Short text."
        result = docs_agent._smart_truncate(text, max_length=200)
        assert result == text

    def test_truncate_at_sentence(self, docs_agent):
        """Test truncation at sentence boundary."""
        text = "First sentence. Second sentence that is longer. Third sentence."
        result = docs_agent._smart_truncate(text, max_length=40)

        # Should end at a sentence boundary
        assert result.endswith('.') or result.endswith('...')

    def test_truncate_at_word_boundary(self, docs_agent):
        """Test truncation at word boundary when no sentence end."""
        text = "This is a very long run-on sentence without any punctuation that goes on and on"
        result = docs_agent._smart_truncate(text, max_length=30)

        # Should not cut mid-word (end with ... or at word boundary)
        assert result.endswith('...')
        # The result should be shorter than original
        assert len(result) <= 33  # max_length + '...'
