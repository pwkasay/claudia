"""
Claudia - A lightweight task coordination system for Claude Code.

Supports both single-session and parallel multi-session workflows with
atomic task assignment, session tracking, and git-native branch workflows.
"""

__version__ = "0.1.0"
__author__ = "Paul Kasay"

from claudia.agent import Agent

__all__ = ["Agent", "__version__"]
