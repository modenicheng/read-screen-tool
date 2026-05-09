"""Tests for the transparent overlay window (OutputOverlay)."""

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from overlay import OutputOverlay


# Use a session-scoped QApplication so widgets can be created in all tests.
# This overrides pytest-qt's default function-scoped qapp to reduce overhead.
@pytest.fixture(scope="session")
def qapp():
    """Provide a session-scoped QApplication instance."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def overlay(qtbot):
    """Create an OutputOverlay managed by qtbot for cleanup."""
    widget = OutputOverlay()
    qtbot.addWidget(widget)
    return widget


class TestOverlayCreation:
    """Tests for overlay instantiation and window flags."""

    def test_overlay_created_with_correct_flags(self, overlay: OutputOverlay) -> None:
        """Verify Qt.FramelessWindowHint, WA_TranslucentBackground, Qt.Tool set."""
        flags = overlay.windowFlags()
        assert flags & Qt.FramelessWindowHint, "Missing FramelessWindowHint"
        assert flags & Qt.Tool, "Missing Qt.Tool flag"
        assert overlay.testAttribute(Qt.WA_TranslucentBackground), (
            "Missing WA_TranslucentBackground"
        )

    def test_overlay_no_background(self, overlay: OutputOverlay) -> None:
        """Verify WA_TranslucentBackground is True."""
        assert overlay.testAttribute(Qt.WA_TranslucentBackground) is True

    def test_font_config_passed(self, qapp) -> None:
        """Create overlay with custom font config and verify values stored."""
        widget = OutputOverlay(
            font_family="Arial",
            font_size=20,
            font_color="#FF0000",
            shadow=False,
        )
        assert widget._font_family == "Arial"
        assert widget._font_size == 20
        assert widget._font_color == QColor("#FF0000")
        assert widget._shadow_enabled is False


class TestTextOperations:
    """Tests for text buffer manipulation."""

    def test_append_text(self, overlay: OutputOverlay, qtbot) -> None:
        """Append text and verify buffer + signal emission."""
        spy = QSignalSpy(overlay.text_added)
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
        # The empty separator block gets filled by the next append_text
        assert len(overlay._text_blocks) == 2
        assert overlay._text_blocks[0] == "A"
        assert overlay._text_blocks[1] == "B"


class TestWindowManagement:
    """Tests for visibility, position, and sizing."""

    def test_toggle_visibility(self, overlay: OutputOverlay) -> None:
        """Start hidden -> toggle shows -> toggle hides."""
        overlay.hide()
        assert not overlay.isVisible()
        overlay.toggle_visibility()
        assert overlay.isVisible()
        overlay.toggle_visibility()
        assert not overlay.isVisible()

    def test_set_position_and_size(self, overlay: OutputOverlay) -> None:
        """Move and resize the window."""
        overlay.set_position(50, 60)
        overlay.set_size(800, 600)
        assert overlay.pos().x() == 50
        assert overlay.pos().y() == 60
        assert overlay.width() == 800
        assert overlay.height() == 600
