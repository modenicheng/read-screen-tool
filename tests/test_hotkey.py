"""Tests for the global hotkey manager (HotkeyManager)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtTest import QSignalSpy

from hotkey import HotkeyManager, parse_hotkey

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
        """Verify all signals are available on the instance."""
        assert hasattr(manager, "screenshot_requested")
        assert hasattr(manager, "toggle_overlay_requested")
        assert hasattr(manager, "alt_state_changed")
        assert hasattr(manager, "move_overlay_to_cursor")

    def test_initial_modifier_state_false(self, manager: HotkeyManager) -> None:
        """Both modifier flags start as False."""
        assert manager._ctrl_pressed is False
        assert manager._shift_pressed is False
        assert manager._alt_pressed is False

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

    def test_ctrl_generic_press_sets_flag(self, manager: HotkeyManager, mock_key) -> None:
        """Key.ctrl (generic VK_CONTROL 0x11) must also set _ctrl_pressed."""
        _press(manager, mock_key("ctrl"))
        assert manager._ctrl_pressed is True

    def test_ctrl_generic_release_clears_flag(self, manager: HotkeyManager, mock_key) -> None:
        manager._ctrl_pressed = True
        _release(manager, mock_key("ctrl"))
        assert manager._ctrl_pressed is False

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

    # -- Alt -------------------------------------------------------------------

    def test_alt_l_press_sets_flag_and_emits(
        self, manager: HotkeyManager, mock_key
    ) -> None:
        spy = QSignalSpy(manager.alt_state_changed)
        _press(manager, mock_key("alt_l"))
        assert manager._alt_pressed is True
        assert spy.count() == 1
        assert spy.at(0)[0] is True

    def test_alt_r_press_sets_flag_and_emits(
        self, manager: HotkeyManager, mock_key
    ) -> None:
        spy = QSignalSpy(manager.alt_state_changed)
        _press(manager, mock_key("alt_r"))
        assert manager._alt_pressed is True
        assert spy.count() == 1
        assert spy.at(0)[0] is True

    def test_alt_gr_press_sets_flag_and_emits(
        self, manager: HotkeyManager, mock_key
    ) -> None:
        spy = QSignalSpy(manager.alt_state_changed)
        _press(manager, mock_key("alt_gr"))
        assert manager._alt_pressed is True
        assert spy.count() == 1

    def test_alt_release_clears_flag_and_emits(
        self, manager: HotkeyManager, mock_key
    ) -> None:
        manager._alt_pressed = True
        spy = QSignalSpy(manager.alt_state_changed)
        _release(manager, mock_key("alt_l"))
        assert manager._alt_pressed is False
        assert spy.count() == 1
        assert spy.at(0)[0] is False

    def test_alt_press_no_duplicate_emit(
        self, manager: HotkeyManager, mock_key
    ) -> None:
        """Holding Alt should not emit alt_state_changed(True) repeatedly."""
        _press(manager, mock_key("alt_l"))
        spy = QSignalSpy(manager.alt_state_changed)
        # Second press without release
        _press(manager, mock_key("alt_l"))
        assert spy.count() == 0  # already True, no emit

    def test_alt_release_no_duplicate_emit(
        self, manager: HotkeyManager, mock_key
    ) -> None:
        """Releasing Alt when already False should not emit."""
        manager._alt_pressed = False
        spy = QSignalSpy(manager.alt_state_changed)
        _release(manager, mock_key("alt_l"))
        assert spy.count() == 0

    def test_alt_generic_press_sets_flag_and_emits(
        self, manager: HotkeyManager, mock_key
    ) -> None:
        """Key.alt (generic VK_MENU) must also set _alt_pressed and emit."""
        spy = QSignalSpy(manager.alt_state_changed)
        _press(manager, mock_key("alt"))
        assert manager._alt_pressed is True
        assert spy.count() == 1
        assert spy.at(0)[0] is True

    def test_alt_generic_release_clears_flag_and_emits(
        self, manager: HotkeyManager, mock_key
    ) -> None:
        manager._alt_pressed = True
        spy = QSignalSpy(manager.alt_state_changed)
        _release(manager, mock_key("alt"))
        assert manager._alt_pressed is False
        assert spy.count() == 1
        assert spy.at(0)[0] is False

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

    # -- Ctrl+Shift+RightClick → move_overlay_to_cursor ------------------------

    def test_ctrl_shift_rightclick_emits_move_signal(
        self, manager: HotkeyManager, mock_button
    ) -> None:
        """Ctrl+Shift+RightClick emits move_overlay_to_cursor with coords."""
        spy = QSignalSpy(manager.move_overlay_to_cursor)
        manager._ctrl_pressed = True
        manager._shift_pressed = True
        _click(manager, mock_button("right"), x=123, y=456)
        assert spy.count() == 1
        assert spy.at(0) == [123, 456]

    def test_rightclick_without_modifiers_no_move_emit(
        self, manager: HotkeyManager, mock_button
    ) -> None:
        """RightClick without Ctrl+Shift does not emit move signal."""
        spy = QSignalSpy(manager.move_overlay_to_cursor)
        _click(manager, mock_button("right"))
        assert spy.count() == 0

    def test_rightclick_with_only_ctrl_no_move_emit(
        self, manager: HotkeyManager, mock_button
    ) -> None:
        """RightClick with only Ctrl does not emit move signal."""
        spy = QSignalSpy(manager.move_overlay_to_cursor)
        manager._ctrl_pressed = True
        _click(manager, mock_button("right"))
        assert spy.count() == 0

    def test_rightclick_with_only_shift_no_move_emit(
        self, manager: HotkeyManager, mock_button
    ) -> None:
        """RightClick with only Shift does not emit move signal."""
        spy = QSignalSpy(manager.move_overlay_to_cursor)
        manager._shift_pressed = True
        _click(manager, mock_button("right"))
        assert spy.count() == 0

    def test_ctrl_shift_rightclick_does_not_emit_screenshot(
        self, manager: HotkeyManager, mock_button
    ) -> None:
        """Ctrl+Shift+RightClick does NOT emit screenshot_requested."""
        screenshot_spy = QSignalSpy(manager.screenshot_requested)
        move_spy = QSignalSpy(manager.move_overlay_to_cursor)
        manager._ctrl_pressed = True
        manager._shift_pressed = True
        _click(manager, mock_button("right"))
        assert screenshot_spy.count() == 0
        assert move_spy.count() == 1


# ---------------------------------------------------------------------------
# Test: toggle_overlay_requested signal (Ctrl+Alt+A)
# ---------------------------------------------------------------------------


class TestToggleOverlayHotkey:
    """Tests for the Ctrl+Alt+A → toggle_overlay_requested hotkey."""

    def test_ctrl_alt_a_emits_signal(
        self, manager: HotkeyManager, mock_key, mock_char_key
    ) -> None:
        spy = QSignalSpy(manager.toggle_overlay_requested)
        _press(manager, mock_key("ctrl_l"))
        _press(manager, mock_key("alt_l"))
        _press(manager, mock_char_key("a"))
        assert spy.count() == 1

    def test_generic_ctrl_alt_a_emits_signal(
        self, manager: HotkeyManager, mock_key, mock_char_key
    ) -> None:
        """Key.ctrl (generic VK_CONTROL) + Alt + A must also emit."""
        spy = QSignalSpy(manager.toggle_overlay_requested)
        _press(manager, mock_key("ctrl"))
        _press(manager, mock_key("alt"))
        _press(manager, mock_char_key("a"))
        assert spy.count() == 1

    def test_uppercase_a_still_emits(
        self, manager: HotkeyManager, mock_key, mock_char_key
    ) -> None:
        """'A' (uppercase) key should also trigger (char is lowercased)."""
        spy = QSignalSpy(manager.toggle_overlay_requested)
        manager._ctrl_pressed = True
        manager._alt_pressed = True
        _press(manager, mock_char_key("A"))
        assert spy.count() == 1

    def test_a_without_modifiers_no_emit(
        self, manager: HotkeyManager, mock_char_key
    ) -> None:
        spy = QSignalSpy(manager.toggle_overlay_requested)
        _press(manager, mock_char_key("a"))
        assert spy.count() == 0

    def test_a_with_only_ctrl_no_emit(
        self, manager: HotkeyManager, mock_key, mock_char_key
    ) -> None:
        spy = QSignalSpy(manager.toggle_overlay_requested)
        _press(manager, mock_key("ctrl_l"))
        _press(manager, mock_char_key("a"))
        assert spy.count() == 0

    def test_a_with_only_alt_no_emit(
        self, manager: HotkeyManager, mock_key, mock_char_key
    ) -> None:
        spy = QSignalSpy(manager.toggle_overlay_requested)
        _press(manager, mock_key("alt_l"))
        _press(manager, mock_char_key("a"))
        assert spy.count() == 0

    def test_other_key_with_modifiers_no_emit(
        self, manager: HotkeyManager, mock_key, mock_char_key
    ) -> None:
        spy = QSignalSpy(manager.toggle_overlay_requested)
        _press(manager, mock_key("ctrl_l"))
        _press(manager, mock_key("alt_l"))
        _press(manager, mock_char_key("x"))  # not 'a'
        assert spy.count() == 0

    def test_modifier_keys_dont_trigger_toggle(
        self, manager: HotkeyManager, mock_key
    ) -> None:
        """Pressing Ctrl itself (no Z) should not emit toggle."""
        spy = QSignalSpy(manager.toggle_overlay_requested)
        _press(manager, mock_key("ctrl_l"))
        _press(manager, mock_key("alt_l"))
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
        manager._alt_pressed = True

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
        assert manager._alt_pressed is False

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

    def test_alt_signal_connectable(self, manager: HotkeyManager) -> None:
        """alt_state_changed signal can be connected to a bool slot."""
        received: list[bool] = []

        def slot(held: bool) -> None:
            received.append(held)

        manager.alt_state_changed.connect(slot)
        manager.alt_state_changed.emit(True)
        manager.alt_state_changed.emit(False)
        assert received == [True, False]


# ---------------------------------------------------------------------------
# Test: parse_hotkey()
# ---------------------------------------------------------------------------


class TestParseHotkey:
    """Tests for the parse_hotkey() helper."""

    def test_ctrl_alt_a(self) -> None:
        modifiers, trigger, vk = parse_hotkey("ctrl+alt+a")
        assert modifiers == ["ctrl", "alt"]
        assert trigger == "a"
        assert vk == 0x41

    def test_ctrl_shift_z(self) -> None:
        modifiers, trigger, vk = parse_hotkey("ctrl+shift+z")
        assert modifiers == ["ctrl", "shift"]
        assert trigger == "z"
        assert vk == 0x5A

    def test_single_modifier(self) -> None:
        modifiers, trigger, vk = parse_hotkey("ctrl+f1")
        assert modifiers == ["ctrl"]
        assert trigger == "f1"
        assert vk is None

    def test_digit_trigger(self) -> None:
        modifiers, trigger, vk = parse_hotkey("alt+1")
        assert modifiers == ["alt"]
        assert trigger == "1"
        assert vk == 0x31

    def test_case_insensitive(self) -> None:
        modifiers, trigger, vk = parse_hotkey("CTRL+ALT+A")
        assert modifiers == ["ctrl", "alt"]
        assert trigger == "a"
        assert vk == 0x41

    def test_spaces_ignored(self) -> None:
        modifiers, trigger, vk = parse_hotkey("ctrl + alt + a")
        assert modifiers == ["ctrl", "alt"]
        assert trigger == "a"
        assert vk == 0x41

    def test_modifier_only(self) -> None:
        """A string with only modifiers has empty trigger and None vk."""
        modifiers, trigger, vk = parse_hotkey("ctrl+alt")
        assert modifiers == ["ctrl", "alt"]
        assert trigger == ""
        assert vk is None


# ---------------------------------------------------------------------------
# Test: configurable toggle hotkey
# ---------------------------------------------------------------------------


class TestConfigurableToggleHotkey:
    """Tests for set_toggle_hotkey() and configurable hotkey triggering."""

    def test_default_hotkey_is_ctrl_alt_a(self, manager: HotkeyManager) -> None:
        """Default toggle hotkey is Ctrl+Alt+A."""
        assert manager._toggle_trigger_key == "a"
        assert manager._toggle_modifiers == ["ctrl", "alt"]
        assert manager._toggle_trigger_vk == 0x41

    def test_set_toggle_hotkey_updates_config(self, manager: HotkeyManager) -> None:
        """set_toggle_hotkey() updates the internal configuration."""
        manager.set_toggle_hotkey("ctrl+shift+z")
        assert manager._toggle_trigger_key == "z"
        assert manager._toggle_modifiers == ["ctrl", "shift"]
        assert manager._toggle_trigger_vk == 0x5A

    def test_custom_hotkey_emits_signal(
        self, manager: HotkeyManager, mock_key, mock_char_key
    ) -> None:
        """Custom hotkey (Ctrl+Shift+Z) emits toggle_overlay_requested."""
        manager.set_toggle_hotkey("ctrl+shift+z")
        spy = QSignalSpy(manager.toggle_overlay_requested)
        _press(manager, mock_key("ctrl_l"))
        _press(manager, mock_key("shift_l"))
        _press(manager, mock_char_key("z"))
        assert spy.count() == 1

    def test_custom_hotkey_wrong_key_no_emit(
        self, manager: HotkeyManager, mock_key, mock_char_key
    ) -> None:
        """Pressing wrong key with correct modifiers does not emit."""
        manager.set_toggle_hotkey("ctrl+shift+z")
        spy = QSignalSpy(manager.toggle_overlay_requested)
        _press(manager, mock_key("ctrl_l"))
        _press(manager, mock_key("shift_l"))
        _press(manager, mock_char_key("a"))  # wrong key
        assert spy.count() == 0

    def test_custom_hotkey_wrong_modifiers_no_emit(
        self, manager: HotkeyManager, mock_key, mock_char_key
    ) -> None:
        """Correct key with wrong modifiers does not emit."""
        manager.set_toggle_hotkey("ctrl+shift+z")
        spy = QSignalSpy(manager.toggle_overlay_requested)
        _press(manager, mock_key("ctrl_l"))
        _press(manager, mock_char_key("z"))  # missing shift
        assert spy.count() == 0

    def test_vk_fallback_when_char_is_none(
        self, manager: HotkeyManager, mock_key
    ) -> None:
        """When Alt is held and key.char is None, VK code fallback triggers."""
        spy = QSignalSpy(manager.toggle_overlay_requested)
        _press(manager, mock_key("ctrl_l"))
        _press(manager, mock_key("alt_l"))
        # Simulate Alt+key: key has no .name, no .char, but has .vk=0x41
        key_with_vk = MagicMock(spec=["vk"])
        key_with_vk.vk = 0x41
        _press(manager, key_with_vk)
        assert spy.count() == 1

    def test_vk_fallback_wrong_code_no_emit(
        self, manager: HotkeyManager, mock_key
    ) -> None:
        """VK code that doesn't match the trigger key does not emit."""
        spy = QSignalSpy(manager.toggle_overlay_requested)
        _press(manager, mock_key("ctrl_l"))
        _press(manager, mock_key("alt_l"))
        key_with_vk = MagicMock(spec=["vk"])
        key_with_vk.vk = 0x42  # 'B', not 'A'
        _press(manager, key_with_vk)
        assert spy.count() == 0

    def test_alt_generic_key_with_vk_fallback(
        self, manager: HotkeyManager, mock_key
    ) -> None:
        """Generic Key.alt (alt) + VK code triggers the toggle."""
        spy = QSignalSpy(manager.toggle_overlay_requested)
        _press(manager, mock_key("ctrl"))
        _press(manager, mock_key("alt"))
        key_with_vk = MagicMock(spec=["vk"])
        key_with_vk.vk = 0x41
        _press(manager, key_with_vk)
        assert spy.count() == 1

    def test_single_modifier_hotkey(
        self, manager: HotkeyManager, mock_key, mock_char_key
    ) -> None:
        """A single-modifier hotkey like Ctrl+F1 works."""
        manager.set_toggle_hotkey("ctrl+f1")
        spy = QSignalSpy(manager.toggle_overlay_requested)
        _press(manager, mock_key("ctrl_l"))
        f1_key = MagicMock()
        f1_key.name = "f1"
        type(f1_key).name = "f1"
        _press(manager, f1_key)
        assert spy.count() == 1
