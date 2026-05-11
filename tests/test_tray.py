"""Tests for system tray manager."""

from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from signals import SignalSpy


@pytest.fixture
def tray_manager():
    from tray import TrayManager

    return TrayManager(show_icon=True)


@pytest.fixture
def mock_tk_root():
    """Mock overlay._get_root so safe_emit() fires immediately."""
    with patch("overlay._get_root") as mock_get_root:
        mock_root = MagicMock()

        def after_idle_immediate(cb, *args):
            cb(*args)

        mock_root.after_idle = after_idle_immediate
        mock_get_root.return_value = mock_root
        yield mock_root


class TestTrayInitialization:
    def test_default_config(self):
        """Default creates tray with show_icon=True."""
        from tray import TrayManager

        tm = TrayManager()
        assert tm._show_icon is True
        assert tm.is_running is False

    def test_show_icon_disabled(self):
        """When show_icon=False, tray should not start."""
        from tray import TrayManager

        tm = TrayManager(show_icon=False)
        assert tm._show_icon is False

    def test_custom_tooltip(self):
        """Custom tooltip should be stored."""
        from tray import TrayManager

        tm = TrayManager(tooltip="My Tool")
        assert tm._tooltip == "My Tool"

    def test_default_icon_created(self):
        """Default icon should be created when none provided."""
        from tray import TrayManager

        tm = TrayManager()
        assert isinstance(tm._icon, Image.Image)


class TestTrayStartStop:
    def test_start_with_icon_disabled(self, tray_manager):
        """When show_icon=False, start() should not create tray."""
        tray_manager._show_icon = False
        tray_manager.start()
        assert not tray_manager.is_running

    def test_start_creates_tray(self, tray_manager):
        """start() should create pystray.Icon and start thread."""
        mock_icon = MagicMock()

        with (
            patch("pystray.Icon", return_value=mock_icon) as mock_icon_cls,
            patch("threading.Thread") as mock_thread,
        ):
            tray_manager.start()

        assert mock_icon_cls.called
        mock_thread.assert_called_once()
        assert tray_manager.is_running

    def test_stop_when_not_running(self, tray_manager):
        """stop() on not-running tray should be safe."""
        tray_manager.stop()  # Should not raise
        assert not tray_manager.is_running

    def test_stop_stops_tray(self, tray_manager):
        """stop() should call tray.stop()."""
        mock_tray = MagicMock()
        tray_manager._tray = mock_tray
        tray_manager._running = True

        tray_manager.stop()

        mock_tray.stop.assert_called_once()
        assert not tray_manager.is_running


class TestTrayCallbacks:
    def test_show_callback_emits_signal(self, tray_manager, mock_tk_root):
        """_on_show should emit show_requested signal."""
        spy = SignalSpy(tray_manager.show_requested)
        tray_manager._on_show()
        assert spy.count() == 1

    def test_hide_callback_emits_signal(self, tray_manager, mock_tk_root):
        """_on_hide should emit hide_requested signal."""
        spy = SignalSpy(tray_manager.hide_requested)
        tray_manager._on_hide()
        assert spy.count() == 1

    def test_exit_callback_emits_signal(self, tray_manager, mock_tk_root):
        """_on_exit should emit exit_requested signal and stop."""
        mock_tray = MagicMock()
        tray_manager._tray = mock_tray
        tray_manager._running = True

        spy = SignalSpy(tray_manager.exit_requested)
        tray_manager._on_exit()

        assert spy.count() == 1

        # Verify stop was called
        assert not tray_manager.is_running
