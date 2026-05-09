"""Tests for the ScreenshotOverlay widget."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    """Create a QApplication for the test session."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def overlay(qtbot):
    """Create a ScreenshotOverlay instance managed by qtbot."""
    from screenshot import ScreenshotOverlay

    widget = ScreenshotOverlay()
    qtbot.addWidget(widget)
    return widget


class TestScreenshotOverlay:
    """Test suite for ScreenshotOverlay."""

    def test_overlay_created_with_correct_flags(self, qapp, overlay) -> None:
        """Verify window flags and attributes are set correctly."""
        assert overlay.windowFlags() & Qt.FramelessWindowHint
        assert overlay.testAttribute(Qt.WA_TranslucentBackground)
        assert overlay.testAttribute(Qt.WA_ShowWithoutActivating)

    def test_start_selection_shows_fullscreen(self, qapp, overlay, qtbot) -> None:
        """Call start_selection(), verify isVisible() returns True."""
        overlay.start_selection()
        assert overlay.isVisible()
        assert overlay.cursor().shape() == Qt.CrossCursor
        overlay.hide()

    def test_mouse_press_starts_selection(self, qapp, overlay, qtbot) -> None:
        """Simulate mouse press, verify internal state."""
        overlay.show()
        qtbot.mousePress(overlay, Qt.LeftButton, pos=QPoint(100, 100))
        assert overlay._selecting
        assert overlay._start_point == QPoint(100, 100)
        assert overlay._end_point == QPoint(100, 100)
        overlay.hide()

    def test_mouse_move_updates_selection(self, qapp, overlay, qtbot) -> None:
        """Simulate press + move, verify end_point updated."""
        overlay.show()
        qtbot.mousePress(overlay, Qt.LeftButton, pos=QPoint(100, 100))
        qtbot.mouseMove(overlay, pos=QPoint(300, 200))
        assert overlay._end_point == QPoint(300, 200)
        overlay.hide()

    def test_mouse_release_small_selection_cancels(self, qapp, overlay, qtbot) -> None:
        """Press, tiny move (width < 10), release -> verify selection_cancelled signal."""
        with qtbot.waitSignal(overlay.selection_cancelled, timeout=1000) as blocker:
            overlay.show()
            qtbot.mousePress(overlay, Qt.LeftButton, pos=QPoint(100, 100))
            qtbot.mouseMove(overlay, pos=QPoint(105, 105))
            qtbot.mouseRelease(overlay, Qt.LeftButton, pos=QPoint(105, 105))
        assert blocker.signal_triggered

    def test_escape_key_cancels(self, qapp, overlay, qtbot) -> None:
        """Show overlay, send Escape key -> verify selection_cancelled signal emitted."""
        with qtbot.waitSignal(overlay.selection_cancelled, timeout=1000) as blocker:
            overlay.show()
            qtbot.keyClick(overlay, Qt.Key_Escape)
        assert blocker.signal_triggered

    def test_get_selection_rect_normalizes(self, qapp, overlay) -> None:
        """Set start > end, verify rect has positive dimensions."""
        overlay._start_point = QPoint(300, 200)
        overlay._end_point = QPoint(100, 50)
        rect = overlay._get_selection_rect()
        assert rect.width() == 200
        assert rect.height() == 150
        assert rect.x() == 100
        assert rect.y() == 50

    def test_screenshot_taken_signal_emitted(self, qapp, overlay, qtbot) -> None:
        """Mock _capture_screen_region, simulate valid selection, verify signal emitted."""
        mock_img = np.zeros((100, 200, 3), dtype=np.uint8)

        with patch.object(overlay, "_capture_screen_region", return_value=mock_img):
            with qtbot.waitSignal(overlay.screenshot_taken, timeout=1000) as blocker:
                overlay.show()
                qtbot.mousePress(overlay, Qt.LeftButton, pos=QPoint(100, 100))
                qtbot.mouseMove(overlay, pos=QPoint(300, 200))
                qtbot.mouseRelease(overlay, Qt.LeftButton, pos=QPoint(300, 200))

        assert blocker.signal_triggered
        emitted_img = blocker.args[0]
        assert isinstance(emitted_img, np.ndarray)
        assert emitted_img.shape == (100, 200, 3)
