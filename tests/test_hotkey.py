"""Tests for the global hotkey manager (HotkeyManager)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtTest import QSignalSpy

from hotkey import HotkeyManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def manager() -> HotkeyManager:
    """Create a fresh HotkeyManager for each test."""
    return HotkeyManager()


@pytest.fixture
def mock_key():
    """Return a factory for pynput-like key objects with a .name attribute."""

    def _make(name: str):
        key = MagicMock()
        key.name = name
        type(key).name = name  # ensure attribute access works
        return key

    return _make


@pytest.fixture
def mock_char_key():
    """Return a factory for pynput KeyCode objects with a .char attribute."""

    def _make(char: str):
        key = MagicMock()
        key.char = char
        type(key).char = char
        # KeyCode does NOT have .name attribute
        del key.name
        return key

    return _make


@pytest.fixture
def mock_button():
    """Return a factory for pynput Button objects with a .name attribute."""

    def _make(name: str):
        btn = MagicMock()
        btn.name = name
        type(btn).name = name
        return btn

    return _make


@pytest.fixture
def mock_listeners():
    """Create mock pynput Listener objects that record start/stop calls."""
    kb_listener = MagicMock()
    mouse_listener = MagicMock()
    return kb_listener, mouse_listener


# ---------------------------------------------------------------------------
# Helpers — simulate pynput key events
# ---------------------------------------------------------------------------


def _press(manager: HotkeyManager, key: object) -> None:
    """Simulate a pynput key-press callback."""
    manager._on_key_press(key)


def _release(manager: HotkeyManager, key: object) -> None:
    """Simulate a pynput key-release callback."""
    manager._on_key_release(key)


def _click(
    manager: HotkeyManager,
    button: object,
    pressed: bool = True,
    x: int = 0,
    y: int = 0,
) -> None:
    """Simulate a pynput mouse-click callback."""
    manager._on_mouse_click(x, y, button, pressed)


# ---------------------------------------------------------------------------
# Test: creation & initial state
# ---------------------------------------------------------------------------


class TestCreation:
    """HotkeyManager instantiation and initial state."""

    def test_signals_exist(self, manager: HotkeyManager) -> None:
        """Verify both signals are available on the instance."""
        assert hasattr(manager, "screenshot_requested")
        assert hasattr(manager, "toggle_overlay_requested")

    def test_initial_modifier_state_false(self, manager: HotkeyManager) -> None:
        """Both modifier flags start as False."""
        assert manager._ctrl_pressed is False
        assert manager._shift_pressed is False

    def test_initial_not_running(self, manager: HotkeyManager) -> None:
        """is_running is False before start() is called."""
        assert manager.is_running is False

    def test_is_qobject(self, manager: HotkeyManager) -> None:
        """HotkeyManager inherits from QObject."""
        from PySide6.QtCore import QObject

        assert isinstance(manager, QObject)


# ---------------------------------------------------------------------------
# Test: modifier state tracking
# ---------------------------------------------------------------------------


class TestModifierStateTracking:
    """Verify that Ctrl and Shift state is correctly tracked."""

    # -- Ctrl ------------------------------------------------------------------

    def test_ctrl_press_sets_flag(self, manager: HotkeyManager, mock_key) -> None:
        _press(manager, mock_key("ctrl_l"))
        assert manager._ctrl_pressed is True

    def test_ctrl_r_press_sets_flag(self, manager: HotkeyManager, mock_key) -> None:
        _press(manager, mock_key("ctrl_r"))
        assert manager._ctrl_pressed is True

    def test_ctrl_release_clears_flag(self, manager: HotkeyManager, mock_key) -> None:
        manager._ctrl_pressed = True
        _release(manager, mock_key("ctrl_l"))
        assert manager._ctrl_pressed is False

    # -- Shift ----------------------------------------------------------------

    def test_shift_press_sets_flag(self, manager: HotkeyManager, mock_key) -> None:
        _press(manager, mock_key("shift"))
        assert manager._shift_pressed is True

    def test_shift_l_press_sets_flag(self, manager: HotkeyManager, mock_key) -> None:
        _press(manager, mock_key("shift_l"))
        assert manager._shift_pressed is True

    def test_shift_r_press_sets_flag(self, manager: HotkeyManager, mock_key) -> None:
        _press(manager, mock_key("shift_r"))
        assert manager._shift_pressed is True

    def test_shift_release_clears_flag(self, manager: HotkeyManager, mock_key) -> None:
        manager._shift_pressed = True
        _release(manager, mock_key("shift_r"))
        assert manager._shift_pressed is False

    # -- Combined -------------------------------------------------------------

    def test_both_modifiers_tracked_independently(
        self, manager: HotkeyManager, mock_key
    ) -> None:
        _press(manager, mock_key("ctrl_l"))
        _press(manager, mock_key("shift_l"))
        assert manager._ctrl_pressed is True
        assert manager._shift_pressed is True

    def test_releasing_one_modifier_keeps_other(
        self, manager: HotkeyManager, mock_key
    ) -> None:
        manager._ctrl_pressed = True
        manager._shift_pressed = True
        _release(manager, mock_key("ctrl_l"))
        assert manager._ctrl_pressed is False
        assert manager._shift_pressed is True

    def test_non_modifier_key_does_not_change_state(
        self, manager: HotkeyManager, mock_char_key
    ) -> None:
        _press(manager, mock_char_key("a"))
        assert manager._ctrl_pressed is False
        assert manager._shift_pressed is False

    def test_none_key_does_not_crash(self, manager: HotkeyManager) -> None:
        """Passing None as key should not raise."""
        _press(manager, None)
        _release(manager, None)
        # No exception → pass

    def test_key_without_name_or_char_handled(
        self, manager: HotkeyManager
    ) -> None:
        """Fallback to str(key).lower() when key has neither .name nor .char."""
        key = MagicMock(spec=[])  # no attributes at all
        _press(manager, key)
        # No exception → pass


# ---------------------------------------------------------------------------
# Test: screenshot_requested signal (Ctrl+Shift+LeftClick)
# ---------------------------------------------------------------------------


class TestScreenshotHotkey:
    """Tests for the Ctrl+Shift+LeftClick → screenshot_requested hotkey."""

    def test_ctrl_shift_leftclick_emits_signal(
        self, manager: HotkeyManager, mock_key, mock_button
    ) -> None:
        spy = QSignalSpy(manager.screenshot_requested)
        manager._ctrl_pressed = True
        manager._shift_pressed = True
        _click(manager, mock_button("left"))
        assert spy.count() == 1

    def test_leftclick_without_modifiers_no_emit(
        self, manager: HotkeyManager, mock_button
    ) -> None:
        spy = QSignalSpy(manager.screenshot_requested)
        _click(manager, mock_button("left"))
        assert spy.count() == 0

    def test_leftclick_with_only_ctrl_no_emit(
        self, manager: HotkeyManager, mock_button
    ) -> None:
        spy = QSignalSpy(manager.screenshot_requested)
        manager._ctrl_pressed = True
        _click(manager, mock_button("left"))
        assert spy.count() == 0

    def test_leftclick_with_only_shift_no_emit(
        self, manager: HotkeyManager, mock_button
    ) -> None:
        spy = QSignalSpy(manager.screenshot_requested)
        manager._shift_pressed = True
        _click(manager, mock_button("left"))
        assert spy.count() == 0

    def test_rightclick_with_modifiers_no_emit(
        self, manager: HotkeyManager, mock_button
    ) -> None:
        spy = QSignalSpy(manager.screenshot_requested)
        manager._ctrl_pressed = True
        manager._shift_pressed = True
        _click(manager, mock_button("right"))
        assert spy.count() == 0

    def test_middleclick_with_modifiers_no_emit(
        self, manager: HotkeyManager, mock_button
    ) -> None:
        spy = QSignalSpy(manager.screenshot_requested)
        manager._ctrl_pressed = True
        manager._shift_pressed = True
        _click(manager, mock_button("middle"))
        assert spy.count() == 0

    def test_mouse_release_ignored(
        self, manager: HotkeyManager, mock_button
    ) -> None:
        """pressed=False (release event) should not emit."""
        spy = QSignalSpy(manager.screenshot_requested)
        manager._ctrl_pressed = True
        manager._shift_pressed = True
        _click(manager, mock_button("left"), pressed=False)
        assert spy.count() == 0


# ---------------------------------------------------------------------------
# Test: toggle_overlay_requested signal (Ctrl+Shift+Z)
# ---------------------------------------------------------------------------


class TestToggleOverlayHotkey:
    """Tests for the Ctrl+Shift+Z → toggle_overlay_requested hotkey."""

    def test_ctrl_shift_z_emits_signal(
        self, manager: HotkeyManager, mock_key, mock_char_key
    ) -> None:
        spy = QSignalSpy(manager.toggle_overlay_requested)
        _press(manager, mock_key("ctrl_l"))
        _press(manager, mock_key("shift_l"))
        _press(manager, mock_char_key("z"))
        assert spy.count() == 1

    def test_uppercase_z_still_emits(
        self, manager: HotkeyManager, mock_key, mock_char_key
    ) -> None:
        """'Z' (uppercase) key should also trigger (char is lowercased)."""
        spy = QSignalSpy(manager.toggle_overlay_requested)
        manager._ctrl_pressed = True
        manager._shift_pressed = True
        _press(manager, mock_char_key("Z"))
        assert spy.count() == 1

    def test_z_without_modifiers_no_emit(
        self, manager: HotkeyManager, mock_char_key
    ) -> None:
        spy = QSignalSpy(manager.toggle_overlay_requested)
        _press(manager, mock_char_key("z"))
        assert spy.count() == 0

    def test_z_with_only_ctrl_no_emit(
        self, manager: HotkeyManager, mock_key, mock_char_key
    ) -> None:
        spy = QSignalSpy(manager.toggle_overlay_requested)
        _press(manager, mock_key("ctrl_l"))
        _press(manager, mock_char_key("z"))
        assert spy.count() == 0

    def test_z_with_only_shift_no_emit(
        self, manager: HotkeyManager, mock_key, mock_char_key
    ) -> None:
        spy = QSignalSpy(manager.toggle_overlay_requested)
        _press(manager, mock_key("shift_l"))
        _press(manager, mock_char_key("z"))
        assert spy.count() == 0

    def test_other_key_with_modifiers_no_emit(
        self, manager: HotkeyManager, mock_key, mock_char_key
    ) -> None:
        spy = QSignalSpy(manager.toggle_overlay_requested)
        _press(manager, mock_key("ctrl_l"))
        _press(manager, mock_key("shift_l"))
        _press(manager, mock_char_key("x"))
        assert spy.count() == 0

    def test_modifier_keys_dont_trigger_toggle(
        self, manager: HotkeyManager, mock_key
    ) -> None:
        """Ctrl and Shift key presses themselves do not emit toggle."""
        spy = QSignalSpy(manager.toggle_overlay_requested)
        _press(manager, mock_key("ctrl_l"))
        _press(manager, mock_key("shift_l"))
        assert spy.count() == 0


# ---------------------------------------------------------------------------
# Test: start / stop lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    """Tests for start(), stop(), and lifecycle state."""

    def test_start_creates_listeners(self, manager: HotkeyManager) -> None:
        """start() spawns pynput keyboard and mouse listeners."""
        kb_mock = MagicMock()
        mouse_mock = MagicMock()

        with (
            patch("pynput.keyboard.Listener", return_value=kb_mock) as kb_cls,
            patch("pynput.mouse.Listener", return_value=mouse_mock) as mouse_cls,
        ):
            manager.start()

        kb_cls.assert_called_once()
        mouse_cls.assert_called_once()
        kb_mock.start.assert_called_once()
        mouse_mock.start.assert_called_once()
        assert manager.is_running is True

    def test_start_when_already_running_is_noop(
        self, manager: HotkeyManager
    ) -> None:
        """Calling start() twice only creates listeners once."""
        kb_mock = MagicMock()
        mouse_mock = MagicMock()

        with (
            patch("pynput.keyboard.Listener", return_value=kb_mock),
            patch("pynput.mouse.Listener", return_value=mouse_mock),
        ):
            manager.start()
            manager.start()  # second call

        # Only created once
        assert kb_mock.start.call_count == 1
        assert mouse_mock.start.call_count == 1

    def test_stop_stops_listeners(self, manager: HotkeyManager) -> None:
        """stop() calls listener.stop() and resets state."""
        kb_mock = MagicMock()
        mouse_mock = MagicMock()

        with (
            patch("pynput.keyboard.Listener", return_value=kb_mock),
            patch("pynput.mouse.Listener", return_value=mouse_mock),
        ):
            manager.start()

        manager.stop()

        kb_mock.stop.assert_called_once()
        mouse_mock.stop.assert_called_once()
        assert manager.is_running is False
        assert manager._keyboard_listener is None
        assert manager._mouse_listener is None

    def test_stop_when_not_running_is_noop(self, manager: HotkeyManager) -> None:
        """Calling stop() on a non-running manager is safe."""
        manager.stop()  # should not raise
        assert manager.is_running is False

    def test_stop_resets_modifier_state(self, manager: HotkeyManager) -> None:
        """After stop(), modifier flags are cleared."""
        manager._ctrl_pressed = True
        manager._shift_pressed = True

        kb_mock = MagicMock()
        mouse_mock = MagicMock()

        with (
            patch("pynput.keyboard.Listener", return_value=kb_mock),
            patch("pynput.mouse.Listener", return_value=mouse_mock),
        ):
            manager.start()

        manager.stop()

        assert manager._ctrl_pressed is False
        assert manager._shift_pressed is False

    def test_stop_handles_missing_listeners_gracefully(
        self, manager: HotkeyManager
    ) -> None:
        """If listener attributes are None, stop() should not raise."""
        manager._running = True
        manager._keyboard_listener = None
        manager._mouse_listener = None
        manager.stop()  # should not raise
        assert manager.is_running is False


# ---------------------------------------------------------------------------
# Test: Signal connectivity / integration
# ---------------------------------------------------------------------------


class TestSignalIntegration:
    """Verify signals can be connected and emit correctly."""

    def test_screenshot_signal_connectable(self, manager: HotkeyManager) -> None:
        """screenshot_requested signal can be connected to a slot."""
        received: list[bool] = []

        def slot() -> None:
            received.append(True)

        manager.screenshot_requested.connect(slot)
        manager.screenshot_requested.emit()
        assert received == [True]

    def test_toggle_signal_connectable(self, manager: HotkeyManager) -> None:
        """toggle_overlay_requested signal can be connected to a slot."""
        received: list[bool] = []

        def slot() -> None:
            received.append(True)

        manager.toggle_overlay_requested.connect(slot)
        manager.toggle_overlay_requested.emit()
        assert received == [True]

    def test_multiple_slots_receive_signal(self, manager: HotkeyManager) -> None:
        """Multiple connected slots all receive the signal."""
        calls: list[str] = []

        def slot_a() -> None:
            calls.append("a")

        def slot_b() -> None:
            calls.append("b")

        manager.screenshot_requested.connect(slot_a)
        manager.screenshot_requested.connect(slot_b)
        manager.screenshot_requested.emit()
        assert calls == ["a", "b"]
