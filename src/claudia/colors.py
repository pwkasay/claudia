"""
Colors Utility Module

Provides terminal color support with automatic detection of terminal capabilities.
Extracted from dashboard.py for reuse across CLI components.
"""

import os
import sys


def _supports_color() -> bool:
    """Check if the terminal supports ANSI color codes."""
    # Check for FORCE_COLOR to override all detection (check first)
    if 'FORCE_COLOR' in os.environ:
        return True

    # Check for NO_COLOR environment variable (standard convention)
    if 'NO_COLOR' in os.environ:
        return False

    # Check if stdout is a TTY
    if not hasattr(sys.stdout, 'isatty') or not sys.stdout.isatty():
        return False

    # Check for dumb terminal
    term = os.environ.get('TERM', '')
    if term == 'dumb':
        return False

    # Most modern terminals support color
    return True


class Colors:
    """
    ANSI color codes - automatically disabled on unsupported terminals.

    Usage:
        from claudia.colors import Colors
        print(f"{Colors.GREEN}Success!{Colors.RESET}")
    """
    _enabled = _supports_color()

    # Reset
    RESET = "\033[0m" if _enabled else ""

    # Styles
    BOLD = "\033[1m" if _enabled else ""
    DIM = "\033[2m" if _enabled else ""
    UNDERLINE = "\033[4m" if _enabled else ""

    # Colors
    BLACK = "\033[30m" if _enabled else ""
    RED = "\033[31m" if _enabled else ""
    GREEN = "\033[32m" if _enabled else ""
    YELLOW = "\033[33m" if _enabled else ""
    BLUE = "\033[34m" if _enabled else ""
    MAGENTA = "\033[35m" if _enabled else ""
    CYAN = "\033[36m" if _enabled else ""
    WHITE = "\033[37m" if _enabled else ""

    # Bright colors
    BRIGHT_RED = "\033[91m" if _enabled else ""
    BRIGHT_GREEN = "\033[92m" if _enabled else ""
    BRIGHT_YELLOW = "\033[93m" if _enabled else ""
    BRIGHT_BLUE = "\033[94m" if _enabled else ""
    BRIGHT_MAGENTA = "\033[95m" if _enabled else ""
    BRIGHT_CYAN = "\033[96m" if _enabled else ""

    @classmethod
    def is_enabled(cls) -> bool:
        """Check if color output is enabled."""
        return cls._enabled

    @classmethod
    def priority_color(cls, priority: int) -> str:
        """Get color for a priority level."""
        colors = {
            0: cls.RED,       # Critical
            1: cls.YELLOW,    # High
            2: cls.RESET,     # Medium (default)
            3: cls.DIM,       # Low
        }
        return colors.get(priority, cls.RESET)

    @classmethod
    def status_color(cls, status: str) -> str:
        """Get color for a status."""
        colors = {
            'open': cls.CYAN,
            'in_progress': cls.YELLOW,
            'done': cls.GREEN,
            'blocked': cls.RED,
        }
        return colors.get(status, cls.RESET)

    @classmethod
    def format_priority(cls, priority: int) -> str:
        """Format a priority with color."""
        labels = {0: "P0", 1: "P1", 2: "P2", 3: "P3"}
        color = cls.priority_color(priority)
        label = labels.get(priority, "P?")
        return f"{color}{label}{cls.RESET}"

    @classmethod
    def format_status(cls, status: str) -> str:
        """Format a status with color."""
        color = cls.status_color(status)
        return f"{color}{status}{cls.RESET}"


# Convenience functions
def priority_str(p: int) -> str:
    """Format priority with color (shorthand)."""
    return Colors.format_priority(p)


def status_str(s: str) -> str:
    """Format status with color (shorthand)."""
    return Colors.format_status(s)


def colorize(text: str, color: str) -> str:
    """Apply a color to text if colors are enabled."""
    if Colors._enabled:
        return f"{color}{text}{Colors.RESET}"
    return text
