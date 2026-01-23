# Developer Onboarding Guide

Welcome to **claudia**! A lightweight task coordination system for Claude Code

## Getting Started

### Prerequisites

- Python 3.10+
- pip or pipenv

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

## Project Structure

Here's how the codebase is organized:

- **src/claudia/**: 7 files
- **tests/**: 6 files

## Key Files to Understand

Start by reading these files to understand the codebase:

1. `src/claudia/cli.py` - Entry point: cli.py

## Development Workflow

1. Create a feature branch: `git checkout -b feature/my-feature`
2. Make your changes
3. Run tests (if available)
4. Submit a pull request

## Getting Help

- Check existing issues for similar problems
- Read the architecture docs for system design
- Ask questions in discussions/chat
