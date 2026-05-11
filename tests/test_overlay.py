"""Tests for the transparent overlay window (OutputOverlay)."""

import pytest

from overlay import OutputOverlay, _parse_inline
from signals import SignalSpy


@pytest.fixture
def overlay():
    """Create an OutputOverlay with immediate rendering (no debounce)."""
    widget = OutputOverlay()
    # Monkeypatch _schedule_render to call _render immediately
    widget._schedule_render = lambda: widget._render()
    yield widget
    widget.close()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _widget_text(overlay_instance: OutputOverlay) -> str:
    """Return the current text content of the overlay widget."""
    overlay_instance._text_widget.config(state="normal")
    text = overlay_instance._text_widget.get("1.0", "end-1c")
    overlay_instance._text_widget.config(state="disabled")
    return text


# ---------------------------------------------------------------------------
# _parse_inline unit tests
# ---------------------------------------------------------------------------


class TestParseInline:
    """Unit tests for the module-level _parse_inline function."""

    def test_plain_text_returns_as_is(self) -> None:
        result = _parse_inline("hello world")
        assert result == [("hello world", ())]

    def test_empty_string_returns_empty_tuple(self) -> None:
        result = _parse_inline("")
        assert result == [("", ())]

    def test_bold_double_asterisk(self) -> None:
        result = _parse_inline("this is **bold** text")
        assert result == [
            ("this is ", ()),
            ("bold", ("bold",)),
            (" text", ()),
        ]

    def test_bold_double_underscore(self) -> None:
        result = _parse_inline("this __too__")
        assert result == [
            ("this ", ()),
            ("too", ("bold",)),
        ]

    def test_italic_single_asterisk(self) -> None:
        result = _parse_inline("lean *back*")
        assert result == [
            ("lean ", ()),
            ("back", ("italic",)),
        ]

    def test_italic_single_underscore(self) -> None:
        result = _parse_inline("_hello_ world")
        assert result == [
            ("hello", ("italic",)),
            (" world", ()),
        ]

    def test_code_inline(self) -> None:
        result = _parse_inline("use `print()` function")
        assert result == [
            ("use ", ()),
            ("print()", ("code",)),
            (" function", ()),
        ]

    def test_multiple_formats_in_one_line(self) -> None:
        result = _parse_inline("**bold** and *italic* and `code`")
        assert result == [
            ("bold", ("bold",)),
            (" and ", ()),
            ("italic", ("italic",)),
            (" and ", ()),
            ("code", ("code",)),
        ]

    def test_unmatched_bold_delimiter_renders_plain(self) -> None:
        result = _parse_inline("this is **incomplete")
        assert result == [("this is **incomplete", ())]

    def test_unmatched_italic_delimiter_renders_plain(self) -> None:
        result = _parse_inline("half *italic")
        assert result == [("half *italic", ())]

    def test_code_prevents_inner_formatting(self) -> None:
        result = _parse_inline("`**not bold**`")
        assert len(result) == 1
        assert result[0] == ("**not bold**", ("code",))

    def test_bold_containing_code(self) -> None:
        result = _parse_inline("**核心逻辑 (`ocr.py`)**")
        assert result == [
            ("核心逻辑 (", ("bold",)),
            ("ocr.py", ("bold", "code")),
            (")", ("bold",)),
        ]

    def test_italic_containing_code(self) -> None:
        result = _parse_inline("*see `config.yaml` for details*")
        assert result == [
            ("see ", ("italic",)),
            ("config.yaml", ("italic", "code")),
            (" for details", ("italic",)),
        ]

    def test_code_between_bold_and_plain(self) -> None:
        result = _parse_inline("`code` and **bold**")
        assert result == [
            ("code", ("code",)),
            (" and ", ()),
            ("bold", ("bold",)),
        ]


# ---------------------------------------------------------------------------
# OutputOverlay creation tests
# ---------------------------------------------------------------------------


class TestOverlayCreation:
    """Tests for overlay instantiation and window flags."""

    def test_overlay_created_with_correct_flags(self, overlay: OutputOverlay) -> None:
        """Verify root is tk.Tk, window is tk.Toplevel, and it's frameless."""
        import tkinter as tk

        assert isinstance(overlay._root, tk.Tk)
        assert isinstance(overlay._window, tk.Toplevel)
        assert overlay._window.overrideredirect() is True

    def test_overlay_no_background(self, overlay: OutputOverlay) -> None:
        """Verify alpha transparency is set."""
        alpha = overlay._window.attributes("-alpha")
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

    def test_text_widget_read_only(self) -> None:
        """Verify the text widget is created in disabled (read-only) state."""
        widget = OutputOverlay()
        assert widget._text_widget.cget("state") == "disabled"
        widget.close()


# ---------------------------------------------------------------------------
# Text operations
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Markdown rendering — inline formatting
# ---------------------------------------------------------------------------


class TestMarkdownInline:
    """Tests for inline markdown formatting in the widget."""

    def test_bold_rendered(self, overlay: OutputOverlay) -> None:
        overlay.append_text("This is **bold** text.")
        text = _widget_text(overlay)
        assert "bold" in text
        assert "**" not in text

    def test_italic_rendered(self, overlay: OutputOverlay) -> None:
        overlay.append_text("This is *italic* text.")
        text = _widget_text(overlay)
        assert "italic" in text
        assert "*" not in text

    def test_code_inline_rendered(self, overlay: OutputOverlay) -> None:
        overlay.append_text("Use `print()` here.")
        text = _widget_text(overlay)
        assert "print()" in text
        assert "`" not in text

    def test_bold_and_italic_together(self, overlay: OutputOverlay) -> None:
        overlay.append_text("**bold** and *italic*")
        text = _widget_text(overlay)
        assert "bold" in text
        assert "italic" in text
        assert "**" not in text
        assert "*" not in text

    def test_unmatched_delimiter_renders_plain(self, overlay: OutputOverlay) -> None:
        overlay.append_text("The value is **42")
        text = _widget_text(overlay)
        assert "**42" in text


# ---------------------------------------------------------------------------
# Markdown rendering — headings
# ---------------------------------------------------------------------------


class TestMarkdownHeadings:
    """Tests for heading rendering (H1, H2, H3)."""

    def test_h1_rendered(self, overlay: OutputOverlay) -> None:
        overlay.append_text("# Main Title")
        text = _widget_text(overlay)
        assert "Main Title" in text
        assert "#" not in text

    def test_h2_rendered(self, overlay: OutputOverlay) -> None:
        overlay.append_text("## Section")
        text = _widget_text(overlay)
        assert "Section" in text
        assert "##" not in text

    def test_h3_rendered(self, overlay: OutputOverlay) -> None:
        overlay.append_text("### Subsection")
        text = _widget_text(overlay)
        assert "Subsection" in text

    def test_multiple_headings(self, overlay: OutputOverlay) -> None:
        overlay.append_text("# H1\n## H2\n### H3")
        text = _widget_text(overlay)
        assert "H1" in text
        assert "H2" in text
        assert "H3" in text


# ---------------------------------------------------------------------------
# Markdown rendering — lists
# ---------------------------------------------------------------------------


class TestMarkdownLists:
    """Tests for ordered and unordered list rendering."""

    def test_unordered_list_dash(self, overlay: OutputOverlay) -> None:
        overlay.append_text("- item one\n- item two")
        text = _widget_text(overlay)
        assert "item one" in text
        assert "item two" in text
        assert "-" not in text

    def test_unordered_list_asterisk(self, overlay: OutputOverlay) -> None:
        overlay.append_text("* first\n* second")
        text = _widget_text(overlay)
        assert "first" in text
        assert "second" in text

    def test_unordered_list_plus(self, overlay: OutputOverlay) -> None:
        overlay.append_text("+ alpha\n+ beta")
        text = _widget_text(overlay)
        assert "alpha" in text
        assert "beta" in text

    def test_ordered_list(self, overlay: OutputOverlay) -> None:
        overlay.append_text("1. first\n2. second\n3. third")
        text = _widget_text(overlay)
        assert "first" in text
        assert "second" in text
        assert "third" in text

    def test_list_with_inline_formatting(self, overlay: OutputOverlay) -> None:
        overlay.append_text("- **bold** item\n- *italic* item")
        text = _widget_text(overlay)
        assert "bold" in text
        assert "italic" in text
        assert "**" not in text


# ---------------------------------------------------------------------------
# Markdown rendering — blockquotes and code blocks
# ---------------------------------------------------------------------------


class TestMarkdownBlocks:
    """Tests for blockquotes and fenced code blocks."""

    def test_blockquote_rendered(self, overlay: OutputOverlay) -> None:
        overlay.append_text("> This is a quote")
        text = _widget_text(overlay)
        assert "This is a quote" in text
        assert ">" not in text

    def test_code_block_rendered(self, overlay: OutputOverlay) -> None:
        overlay.append_text("```\ndef foo():\n    pass\n```")
        text = _widget_text(overlay)
        assert "def foo():" in text
        assert "pass" in text
        assert "```" not in text

    def test_horizontal_rule_rendered(self, overlay: OutputOverlay) -> None:
        overlay.append_text("before\n\n---\n\nafter")
        text = _widget_text(overlay)
        assert "before" in text
        assert "after" in text
        assert "---" not in text


# ---------------------------------------------------------------------------
# Streaming behavior
# ---------------------------------------------------------------------------


class TestStreamingBehavior:
    """Tests for streaming LLM output behavior."""

    def test_partial_token_does_not_flash_raw_markdown(self, overlay: OutputOverlay) -> None:
        """When building **bold** incrementally, delimiters appear only when incomplete."""
        overlay.append_text("**")
        text1 = _widget_text(overlay)
        assert "**" in text1  # incomplete, rendered as plain

        overlay.append_text("bo")
        text2 = _widget_text(overlay)
        assert "**bo" in text2

        overlay.append_text("ld**")
        text3 = _widget_text(overlay)
        assert "**" not in text3  # complete, delimiters removed
        assert "bold" in text3


# ---------------------------------------------------------------------------
# Window management
# ---------------------------------------------------------------------------


class TestWindowManagement:
    """Tests for visibility, position, and sizing."""

    def test_toggle_visibility(self, overlay: OutputOverlay) -> None:
        """Start hidden -> toggle shows -> toggle hides."""
        overlay.hide()
        assert not overlay.isVisible()
        assert overlay._window.attributes("-alpha") == 0.0

        overlay.toggle_visibility()
        assert overlay.isVisible()
        assert overlay._window.attributes("-alpha") > 0

        overlay.toggle_visibility()
        assert not overlay.isVisible()
        assert overlay._window.attributes("-alpha") == 0.0

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


# ---------------------------------------------------------------------------
# Shadow effect
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Agent status
# ---------------------------------------------------------------------------


class TestAgentStatus:
    """Tests for set_status / clear_status / status_changed Signal."""

    def test_set_status_updates_label(self, overlay: OutputOverlay) -> None:
        """set_status() sets the label text."""
        overlay.set_status("Thinking...")
        assert overlay._status_label.cget("text") == "Thinking..."

    def test_clear_status_clears_label(self, overlay: OutputOverlay) -> None:
        """clear_status() empties the label text."""
        overlay.set_status("搜索test...")
        overlay.clear_status()
        assert overlay._status_label.cget("text") == ""

    def test_set_status_emits_signal(self, overlay: OutputOverlay) -> None:
        """set_status() emits the status_changed signal."""
        spy = SignalSpy(overlay.status_changed)
        overlay.set_status("读取文件")
        assert spy.count() == 1
        assert spy.at(0)[0] == "读取文件"

    def test_clear_status_emits_empty_signal(self, overlay: OutputOverlay) -> None:
        """clear_status() emits status_changed with empty string."""
        overlay.set_status("Thinking...")
        spy = SignalSpy(overlay.status_changed)
        overlay.clear_status()
        assert spy.count() == 1
        assert spy.at(0)[0] == ""

    def test_multiple_set_status_updates(self, overlay: OutputOverlay) -> None:
        """Multiple set_status calls update the label correctly."""
        overlay.set_status("Thinking...")
        overlay.set_status("搜索test...")
        overlay.set_status("读取文件")
        assert overlay._status_label.cget("text") == "读取文件"


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


class TestCleanup:
    """Tests for proper resource cleanup."""

    def test_close_cleanup(self) -> None:
        """Closing the overlay destroys the tkinter window."""
        widget = OutputOverlay()
        window = widget._window
        widget.close()
        assert not window.winfo_exists()
