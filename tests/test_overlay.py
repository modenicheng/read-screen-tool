"""Tests for the transparent overlay window (OutputOverlay)."""

import pytest

from overlay import OutputOverlay
from signals import SignalSpy


@pytest.fixture
def overlay():
    """Create an OutputOverlay managed by the fixture for cleanup."""
    widget = OutputOverlay()
    yield widget
    widget.close()  # Clean up tkinter window


class TestOverlayCreation:
    """Tests for overlay instantiation and window flags."""

    def test_overlay_created_with_correct_flags(self, overlay: OutputOverlay) -> None:
        """Verify root is tk.Tk, window is tk.Toplevel, and it's frameless."""
        import tkinter as tk
        assert isinstance(overlay._root, tk.Tk)
        assert isinstance(overlay._window, tk.Toplevel)
        assert overlay._window.overrideredirect() is True

    def test_overlay_no_background(self, overlay: OutputOverlay) -> None:
        """Verify alpha transparency is set (not color-key)."""
        alpha = overlay._window.attributes('-alpha')
        assert alpha is not None
        assert 0 < alpha < 1

    def test_font_config_passed(self) -> None:
        """Create overlay with custom font config and verify values stored."""
        widget = OutputOverlay(
            font_family="Arial",
            font_size=20,
            font_color="#FF0000",
            shadow=False,
        )
        assert widget._font_family == "Arial"
        assert widget._font_size == 20
        assert widget._font_color == "#FF0000"
        assert widget._shadow_enabled is False
        widget.close()


class TestTextOperations:
    """Tests for text buffer manipulation."""

    def test_append_text(self, overlay: OutputOverlay) -> None:
        """Append text and verify buffer + signal emission."""
        spy = SignalSpy(overlay.text_added)
        overlay.append_text("Hello")
        assert overlay._text_blocks == ["Hello"]
        assert spy.count() == 1
        assert spy.at(0)[0] == "Hello"

    def test_append_text_accumulates(self, overlay: OutputOverlay) -> None:
        """Consecutive appends accumulate within the same block."""
        overlay.append_text("a")
        overlay.append_text("b")
        assert overlay._text_blocks == ["ab"]

    def test_add_separator(self, overlay: OutputOverlay) -> None:
        """A separator adds a new empty block."""
        overlay.append_text("First")
        overlay.add_separator()
        assert len(overlay._text_blocks) == 2
        assert overlay._text_blocks[0] == "First"
        assert overlay._text_blocks[1] == ""

    def test_clear(self, overlay: OutputOverlay) -> None:
        """Clearing empties all text blocks."""
        overlay.append_text("Something")
        overlay.clear()
        assert overlay._text_blocks == []

    def test_multiple_text_blocks(self, overlay: OutputOverlay) -> None:
        """Appending after separator creates independent blocks."""
        overlay.append_text("A")
        overlay.add_separator()
        overlay.append_text("B")
        assert len(overlay._text_blocks) == 2
        assert overlay._text_blocks[0] == "A"
        assert overlay._text_blocks[1] == "B"


class TestWindowManagement:
    """Tests for visibility, position, and sizing."""

    def test_toggle_visibility(self, overlay: OutputOverlay) -> None:
        """Start hidden -> toggle shows -> toggle hides."""
        overlay.hide()
        assert not overlay.isVisible()
        # Verify alpha is 0 (actually invisible)
        assert overlay._window.attributes('-alpha') == 0.0

        overlay.toggle_visibility()
        assert overlay.isVisible()
        # Verify alpha is restored (actually visible)
        assert overlay._window.attributes('-alpha') > 0

        overlay.toggle_visibility()
        assert not overlay.isVisible()
        assert overlay._window.attributes('-alpha') == 0.0

    def test_set_position_and_size(self, overlay: OutputOverlay) -> None:
        """Move and resize the window."""
        overlay.set_position(50, 60)
        overlay.set_size(800, 600)
        assert overlay._window.winfo_x() == 50
        assert overlay._window.winfo_y() == 60
        assert overlay._window.winfo_width() == 800
        assert overlay._window.winfo_height() == 600

    def test_move_to_cursor(self, overlay: OutputOverlay) -> None:
        """move_to_cursor(x, y) moves the window to the given position."""
        overlay.move_to_cursor(150, 250)
        assert overlay._window.winfo_x() == 150
        assert overlay._window.winfo_y() == 250


class TestShadowEffect:
    """Tests for the shadow effect approach (accepted but ignored in tkinter)."""

    def test_shadow_effect_created_when_enabled(self) -> None:
        """When shadow=True, _shadow_effect is None (tkinter ignores this)."""
        widget = OutputOverlay(shadow=True)
        assert widget._shadow_effect is None
        widget.close()

    def test_shadow_effect_none_when_disabled(self) -> None:
        """When shadow=False, no shadow effect is created."""
        widget = OutputOverlay(shadow=False)
        assert widget._shadow_effect is None
        widget.close()

    def test_text_widget_created(self) -> None:
        """Verify a text widget is created for output."""
        import tkinter as tk
        widget = OutputOverlay()
        assert isinstance(widget._text_widget, tk.Text)
        widget.close()


class TestMarkdownRendering:
    """Tests for Markdown rendering support."""

    def test_is_markdown_detects_heading(self, overlay: OutputOverlay) -> None:
        """Text starting with # is identified as markdown."""
        assert overlay._is_markdown("# Heading") is True

    def test_is_markdown_detects_asterisk(self, overlay: OutputOverlay) -> None:
        """Text containing * is identified as markdown."""
        assert overlay._is_markdown("*bold*") is True

    def test_is_markdown_detects_backtick(self, overlay: OutputOverlay) -> None:
        """Text containing ` is identified as markdown."""
        assert overlay._is_markdown("`code`") is True

    def test_is_markdown_plain_text(self, overlay: OutputOverlay) -> None:
        """Plain text without markdown syntax is not identified."""
        assert overlay._is_markdown("Hello world.") is False

    def test_append_markdown_text_renders(self, overlay: OutputOverlay) -> None:
        """Appending markdown text emits signal without crashing."""
        spy = SignalSpy(overlay.text_added)
        overlay.append_text("# Hello")
        assert spy.count() == 1


class TestCleanup:
    """Tests for proper resource cleanup."""

    def test_close_cleanup(self) -> None:
        """Closing the overlay destroys the tkinter window."""
        widget = OutputOverlay()
        window = widget._window
        widget.close()
        assert not window.winfo_exists()
