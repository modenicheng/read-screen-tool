"""Tests for ScreenshotOverlay — tkinter-based screenshot selection."""

from __future__ import annotations

import tkinter as tk
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from screenshot import ScreenshotOverlay
from signals import SignalSpy

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_win_api():
    """Mock ctypes Windows API calls for headless testing.

    Patches ``ctypes.byref`` so the mocked WinAPI functions receive
    the actual struct objects (not CArgObject wrappers), allowing
    side_effect callbacks to directly set struct fields like ``pt.x``
    and ``mi.rcMonitor.right``.
    """

    # -- side-effect callbacks -------------------------------------------------
    def set_cursor(pt):
        """Simulate ::GetCursorPos — fills POINT with known coordinates."""
        pt.x, pt.y = 500, 300
        return True

    def set_monitor_info(hmon, mi):
        """Simulate ::GetMonitorInfoW — fills MONITORINFO.rcMonitor."""
        mi.rcMonitor.left = 0
        mi.rcMonitor.top = 0
        mi.rcMonitor.right = 1920
        mi.rcMonitor.bottom = 1080
        return True

    # -- patches (function-scoped) ---------------------------------------------
    with (
        # Let GetCursorPos / GetMonitorInfoW receive the raw ctypes struct
        # instead of a CArgObject so side_effect can directly set fields.
        patch("screenshot.ctypes.byref", side_effect=lambda obj: obj),
        patch(
            "screenshot.ctypes.windll.user32.GetCursorPos",
            side_effect=set_cursor,
        ),
        patch(
            "screenshot.ctypes.windll.user32.MonitorFromPoint",
            return_value=1,
        ),
        patch(
            "screenshot.ctypes.windll.user32.GetMonitorInfoW",
            side_effect=set_monitor_info,
        ),
        patch(
            "screenshot.ctypes.windll.user32.GetWindowLongPtrW",
            return_value=0,
        ),
        patch(
            "screenshot.ctypes.windll.user32.SetWindowLongPtrW",
            return_value=0,
        ),
    ):
        yield


@pytest.fixture
def overlay(mock_win_api):
    """Create a ScreenshotOverlay.  Cleans up Toplevel after each test."""
    widget = ScreenshotOverlay()
    yield widget
    widget._cleanup()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWindowCreation:
    """Tests for ScreenshotOverlay window creation."""

    def test_creates_toplevel_window(self, overlay: ScreenshotOverlay) -> None:
        """start_selection() creates two Toplevels (capture + overlay)."""
        overlay.start_selection()
        assert isinstance(overlay._capture_win, tk.Toplevel)
        assert isinstance(overlay._overlay_win, tk.Toplevel)
        assert overlay._capture_win.overrideredirect() is True
        assert overlay._overlay_win.overrideredirect() is True

    def test_start_selection_shows_window(self, overlay: ScreenshotOverlay) -> None:
        """After start_selection both windows exist and selection state is active."""
        overlay.start_selection()
        assert overlay._capture_win is not None
        assert overlay._overlay_win is not None
        assert overlay._capture_win.winfo_exists()
        assert overlay._selecting is True
        assert isinstance(overlay._canvas, tk.Canvas)


class TestMouseInteraction:
    """Tests for mouse press / drag / release handling."""

    def test_mouse_drag_draws_selection(self, overlay: ScreenshotOverlay) -> None:
        """Press + drag updates _start_point and _end_point."""
        overlay.start_selection()

        ev = MagicMock()
        ev.x, ev.y = 100, 100
        overlay._on_mouse_press(ev)
        assert overlay._selecting is True
        assert overlay._start_point == (100, 100)
        assert overlay._end_point == (100, 100)

        ev.x, ev.y = 300, 200
        overlay._on_mouse_drag(ev)
        assert overlay._end_point == (300, 200)

    def test_small_selection_cancels(self, overlay: ScreenshotOverlay) -> None:
        """Dragging < 10 px emits selection_cancelled instead of capturing."""
        overlay.start_selection()
        spy = SignalSpy(overlay.selection_cancelled)

        # Simulate a tiny drag: (100,100) -> (105,105)
        overlay._start_point = (100, 100)
        overlay._end_point = (105, 105)

        ev = MagicMock()
        ev.x, ev.y = 105, 105
        overlay._on_mouse_release(ev)

        assert spy.count() == 1
        spy.disconnect()


class TestCancellation:
    """Tests for Escape-key cancellation."""

    def test_escape_cancels(self, overlay: ScreenshotOverlay) -> None:
        """Pressing Escape emits selection_cancelled and destroys both windows."""
        overlay.start_selection()
        spy = SignalSpy(overlay.selection_cancelled)

        overlay._on_escape(MagicMock())

        assert spy.count() == 1
        assert overlay._capture_win is None
        assert overlay._overlay_win is None
        spy.disconnect()


class TestCoordinates:
    """Tests for coordinate normalization."""

    def test_get_selection_rect_normalizes(self) -> None:
        """When start > end the rect width/height are always positive."""
        widget = ScreenshotOverlay()
        widget._start_point = (300, 200)
        widget._end_point = (100, 50)

        x, y, w, h = widget._get_selection_rect()

        assert x == 100
        assert y == 50
        assert w == 200
        assert h == 150


class TestScreenshotCapture:
    """Tests for screenshot capture and signal emission."""

    def test_screenshot_taken_signal(self, overlay: ScreenshotOverlay) -> None:
        """A valid selection emits screenshot_taken with a numpy array (BGR)."""
        mock_img = np.zeros((100, 200, 4), dtype=np.uint8)

        with patch("screenshot.mss.mss") as mock_mss:
            mock_mss.return_value.__enter__.return_value.grab.return_value = mock_img

            overlay.start_selection()
            spy = SignalSpy(overlay.screenshot_taken)

            # Simulate a valid drag: (100,100) -> (300,200), w=200 h=100
            overlay._start_point = (100, 100)
            overlay._end_point = (300, 200)

            ev = MagicMock()
            ev.x, ev.y = 300, 200
            overlay._on_mouse_release(ev)

            assert spy.count() == 1
            emitted_img = spy.at(0)[0]
            assert isinstance(emitted_img, np.ndarray)
            assert emitted_img.shape == (100, 200, 3)  # alpha dropped
            spy.disconnect()

    def test_window_destroyed_after_capture(self, overlay: ScreenshotOverlay) -> None:
        """After a valid capture both Toplevel refs and Canvas are cleared."""
        mock_img = np.zeros((100, 200, 4), dtype=np.uint8)

        with patch("screenshot.mss.mss") as mock_mss:
            mock_mss.return_value.__enter__.return_value.grab.return_value = mock_img

            overlay.start_selection()

            overlay._start_point = (100, 100)
            overlay._end_point = (300, 200)

            ev = MagicMock()
            ev.x, ev.y = 300, 200
            overlay._on_mouse_release(ev)

            assert overlay._capture_win is None
            assert overlay._overlay_win is None
            assert overlay._canvas is None
