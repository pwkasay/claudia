# Developer Onboarding Guide

Welcome to **claudia**!

> A lightweight task coordination system for Claude Code

This guide will help you get set up and start contributing.
Follow each section in order for the best experience.

## Getting Started

### Prerequisites

- **Python 3.10+** - [Download Python](https://python.org/downloads/)
  - Verify with: `python --version` or `python3 --version`
- **pip** - Usually comes with Python. Verify with: `pip --version`
- **Git** - [Download Git](https://git-scm.com/downloads)

### Setup

```bash
# Clone the repository
git clone https://github.com/paulkasay/claudia
cd claudia

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Install dependencies
pip install -e .
```

#### Troubleshooting Setup

**"python" command not found?**
- Try `python3` instead of `python`
- Make sure Python is in your PATH

**Permission denied on `source venv/bin/activate`?**
- Make sure you're in the project directory
- On Windows, use: `venv\Scripts\activate`

**pip install fails?**
- Make sure your virtual environment is activated (you should see `(venv)` in your prompt)
- Try: `pip install --upgrade pip` first

## Project Structure

Here's how the codebase is organized:

- **src/claudia/**: 6 python files

## Key Files to Understand

Start by reading these files to understand the codebase:

1. `src/claudia/cli.py` - Entry point: cli.py

## Quick Examples

Here are some common tasks to try after setup:

### Check your installation

```bash
# Make sure claudia is installed
python -c "import claudia; print('OK')"
```

### Run the tests

```bash
# If tests exist in the project
pytest  # or python -m pytest
```

## Development Workflow

Follow these steps when making changes:

### 1. Create a feature branch

```bash
# Start from the main branch
git checkout main
git pull origin main

# Create your feature branch
git checkout -b feature/my-feature
```

### 2. Make your changes

- Edit the files you need to change
- Test your changes locally
- Commit frequently with clear messages

```bash
git add .
git commit -m "Add: brief description of change"
```

### 3. Run tests

Before submitting, make sure all tests pass.

### 4. Submit a pull request

```bash
git push origin feature/my-feature
```

Then open a Pull Request on GitHub.

## Common Pitfalls

Avoid these common mistakes:

### 1. Forgetting to activate the virtual environment

**Symptom:** `ModuleNotFoundError` when running code

**Solution:** Run `source venv/bin/activate` (or `venv\Scripts\activate` on Windows)

### 2. Committing to main branch directly

**Symptom:** Push rejected or PR conflicts

**Solution:** Always create a feature branch first

### 3. Not pulling latest changes

**Symptom:** Merge conflicts when submitting PR

**Solution:** Run `git pull origin main` before starting work

## Getting Help

- Check existing issues for similar problems
- Read the architecture docs for system design
- Ask questions in discussions/chat
