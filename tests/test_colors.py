"""
Tests for the colors module.
"""




class TestColorsDetection:
    """Test color detection logic."""

    def test_force_color_env(self, monkeypatch):
        """Test FORCE_COLOR environment variable."""
        monkeypatch.setenv('FORCE_COLOR', '1')

        # Need to reimport to pick up env change
        from importlib import reload
        import claudia.colors
        reload(claudia.colors)

        from claudia.colors import _supports_color
        assert _supports_color() is True

    def test_no_color_env(self, monkeypatch):
        """Test NO_COLOR environment variable."""
        monkeypatch.setenv('NO_COLOR', '1')
        # Remove FORCE_COLOR if set
        monkeypatch.delenv('FORCE_COLOR', raising=False)

        from importlib import reload
        import claudia.colors
        reload(claudia.colors)

        from claudia.colors import _supports_color
        assert _supports_color() is False


class TestColorsFormatting:
    """Test color formatting functions."""

    def test_format_priority(self, monkeypatch):
        """Test priority formatting."""
        monkeypatch.setenv('FORCE_COLOR', '1')

        from importlib import reload
        import claudia.colors
        reload(claudia.colors)

        from claudia.colors import Colors

        # P0 should be red
        p0 = Colors.format_priority(0)
        assert 'P0' in p0
        assert '\033[31m' in p0  # Red color code

        # P1 should be yellow
        p1 = Colors.format_priority(1)
        assert 'P1' in p1
        assert '\033[33m' in p1  # Yellow color code

        # P2 should use reset (default)
        p2 = Colors.format_priority(2)
        assert 'P2' in p2

        # P3 should be dim
        p3 = Colors.format_priority(3)
        assert 'P3' in p3
        assert '\033[2m' in p3  # Dim code

    def test_format_status(self, monkeypatch):
        """Test status formatting."""
        monkeypatch.setenv('FORCE_COLOR', '1')

        from importlib import reload
        import claudia.colors
        reload(claudia.colors)

        from claudia.colors import Colors

        # open should be cyan
        s = Colors.format_status('open')
        assert 'open' in s
        assert '\033[36m' in s  # Cyan

        # in_progress should be yellow
        s = Colors.format_status('in_progress')
        assert 'in_progress' in s
        assert '\033[33m' in s  # Yellow

        # done should be green
        s = Colors.format_status('done')
        assert 'done' in s
        assert '\033[32m' in s  # Green

        # blocked should be red
        s = Colors.format_status('blocked')
        assert 'blocked' in s
        assert '\033[31m' in s  # Red

    def test_colorize(self, monkeypatch):
        """Test colorize function."""
        monkeypatch.setenv('FORCE_COLOR', '1')

        from importlib import reload
        import claudia.colors
        reload(claudia.colors)

        from claudia.colors import colorize, Colors

        result = colorize('test', Colors.GREEN)
        assert '\033[32m' in result
        assert 'test' in result
        assert '\033[0m' in result  # Reset at end


class TestColorsDisabled:
    """Test behavior when colors are disabled."""

    def test_format_priority_no_color(self, monkeypatch):
        """Test priority formatting without colors."""
        monkeypatch.setenv('NO_COLOR', '1')
        monkeypatch.delenv('FORCE_COLOR', raising=False)

        from importlib import reload
        import claudia.colors
        reload(claudia.colors)

        from claudia.colors import Colors

        # Should not contain ANSI codes
        p0 = Colors.format_priority(0)
        assert 'P0' in p0
        assert '\033[' not in p0

    def test_format_status_no_color(self, monkeypatch):
        """Test status formatting without colors."""
        monkeypatch.setenv('NO_COLOR', '1')
        monkeypatch.delenv('FORCE_COLOR', raising=False)

        from importlib import reload
        import claudia.colors
        reload(claudia.colors)

        from claudia.colors import Colors

        s = Colors.format_status('done')
        assert 'done' in s
        assert '\033[' not in s


class TestColorConstants:
    """Test color constant values."""

    def test_color_codes(self, monkeypatch):
        """Test that color codes are correct."""
        monkeypatch.setenv('FORCE_COLOR', '1')

        from importlib import reload
        import claudia.colors
        reload(claudia.colors)

        from claudia.colors import Colors

        assert Colors.RED == '\033[31m'
        assert Colors.GREEN == '\033[32m'
        assert Colors.YELLOW == '\033[33m'
        assert Colors.BLUE == '\033[34m'
        assert Colors.MAGENTA == '\033[35m'
        assert Colors.CYAN == '\033[36m'
        assert Colors.RESET == '\033[0m'
        assert Colors.BOLD == '\033[1m'
        assert Colors.DIM == '\033[2m'

    def test_is_enabled(self, monkeypatch):
        """Test is_enabled method."""
        monkeypatch.setenv('FORCE_COLOR', '1')

        from importlib import reload
        import claudia.colors
        reload(claudia.colors)

        from claudia.colors import Colors
        assert Colors.is_enabled() is True

        monkeypatch.setenv('NO_COLOR', '1')
        monkeypatch.delenv('FORCE_COLOR', raising=False)

        reload(claudia.colors)
        from claudia.colors import Colors
        assert Colors.is_enabled() is False
