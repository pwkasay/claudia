# Publishing Claudia to PyPI

This guide covers publishing Claudia as a real Python package on PyPI.

## Prerequisites

### 1. PyPI Account Setup

1. Create account at https://pypi.org/account/register/
2. Create API token at https://pypi.org/manage/account/token/
3. Save token securely (you'll need it for upload)

### 2. Install Build Tools

```bash
pip install build twine
```

## Update pyproject.toml

Add these fields to `pyproject.toml`:

```toml
[project]
name = "claudia"
version = "0.1.0"
description = "Lightweight task coordination for Claude Code"
readme = "README.md"
license = {text = "MIT"}
authors = [{name = "Paul Kasay"}]
keywords = ["claude", "ai", "task-management", "coordination"]
classifiers = [
    "Development Status :: 4 - Beta",
    "Environment :: Console",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
]

[project.urls]
Homepage = "https://github.com/pwkasay/claudia"
Repository = "https://github.com/pwkasay/claudia"
```

## Build the Package

```bash
cd /path/to/claudia
python -m build
```

This creates:
- `dist/claudia-0.1.0.tar.gz` (source distribution)
- `dist/claudia-0.1.0-py3-none-any.whl` (wheel)

## Upload to PyPI

### Option A: Test on TestPyPI First (Recommended)

```bash
# Upload to test server
twine upload --repository testpypi dist/*

# Test installation from TestPyPI
pip install --index-url https://test.pypi.org/simple/ claudia
```

### Option B: Upload Directly to PyPI

```bash
twine upload dist/*
```

You'll be prompted for:
- Username: `__token__`
- Password: your API token (starts with `pypi-`)

## Verify Installation

```bash
pip install claudia
claudia --version
```

## After Publishing

Users can install with:

```bash
# Basic install
pip install claudia

# With SSL certificate support (recommended for macOS)
pip install 'claudia[ssl]'
```

## Version Bumping

For new releases:

1. Update version in `pyproject.toml` and `src/claudia/__init__.py`
2. Commit: `git commit -am "Bump version to X.Y.Z"`
3. Tag: `git tag vX.Y.Z`
4. Push: `git push && git push --tags`
5. Build: `python -m build`
6. Upload: `twine upload dist/*`

## Troubleshooting

### "Package name already exists"
The name `claudia` may be taken. Check https://pypi.org/project/claudia/
If taken, consider alternatives like `claudia-tasks` or `claude-claudia`.

### Upload fails with authentication error
- Use `__token__` as username (literally)
- Use your API token as password
- Ensure token has upload permissions

### Package not found after upload
PyPI can take a few minutes to index new packages. Wait and retry.
