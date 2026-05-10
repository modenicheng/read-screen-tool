"""Global hotkey management using pynput, bridged to Qt via pyqtSignal.

Provides a ``HotkeyManager`` that listens for global keyboard and mouse events
in background threads and emits Qt signals on the main thread when hotkey
combinations are detected.

Hotkeys:
    - **Ctrl+Shift+LeftClick** → ``screenshot_requested``
    - **Ctrl+Alt+A** → ``toggle_overlay_requested``
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    from pynput.keyboard import Key, KeyCode
    from pynput.mouse import Button

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# pynput key-name constants (imports postponed for test-mock friendliness)
# ---------------------------------------------------------------------------
_CTRL_KEYS: tuple[str, ...] = ("ctrl", "ctrl_l", "ctrl_r")
_SHIFT_KEYS: tuple[str, ...] = ("shift", "shift_l", "shift_r")
_ALT_KEYS: tuple[str, ...] = ("alt", "alt_l", "alt_r", "alt_gr")
_MODIFIER_KEYS: frozenset[str] = frozenset(_CTRL_KEYS + _SHIFT_KEYS + _ALT_KEYS)
_LEFT_BUTTON: str = "left"
_RIGHT_BUTTON: str = "right"
_DEFAULT_TOGGLE_HOTKEY: str = "ctrl+alt+a"


def _name_to_vk(name: str) -> int | None:
    """Convert a single-letter key name to its Windows virtual-key code.

    Only handles ASCII letters (a-z → 0x41-0x5A) and digits (0-9 → 0x30-0x39).
    Returns ``None`` for modifiers or unsupported names.
    """
    if len(name) != 1:
        return None
    if "a" <= name <= "z":
        return ord(name.upper())
    if "0" <= name <= "9":
        return ord(name)
    return None


def parse_hotkey(config_str: str) -> tuple[list[str], str, int | None]:
    """Parse a ``+``-separated hotkey string into its components.

    Returns:
        ``(modifiers, trigger_key, trigger_vk)`` — modifiers are lowercase
        pynput names, trigger_key is the non-modifier key name, and
        trigger_vk is the Windows virtual-key code (``None`` if not
        applicable).
    """
    parts = [p.strip().lower() for p in config_str.split("+")]
    modifiers: list[str] = []
    trigger_key = ""
    for part in parts:
        if part in _MODIFIER_KEYS:
            modifiers.append(part)
        else:
            trigger_key = part
    return modifiers, trigger_key, _name_to_vk(trigger_key)


class HotkeyManager(QObject):
    """Listens for global hotkeys via *pynput* and emits Qt signals.

    All pynput callbacks execute on background threads.  Signal emission is
    thread-safe — Qt automatically queues the emission on the receiver's
    event-loop thread.

    Usage:
        manager = HotkeyManager()
        manager.screenshot_requested.connect(on_screenshot_hotkey)
        manager.toggle_overlay_requested.connect(on_toggle_hotkey)
        manager.start()
    """

    screenshot_requested = Signal()
    """Emitted when Ctrl+Shift+LeftClick is detected globally."""

    toggle_overlay_requested = Signal()
    """Emitted when Ctrl+Alt+A is pressed."""

    move_overlay_to_cursor = Signal(int, int)
    """Emitted when Ctrl+Shift+RightClick is detected — (x, y) cursor position."""

    alt_state_changed = Signal(bool)
    """Emitted when the Alt key is pressed (True) or released (False) globally."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

        # -- Modifier state -------------------------------------------------
        self._ctrl_pressed: bool = False
        self._shift_pressed: bool = False
        self._alt_pressed: bool = False

        # -- Configurable toggle hotkey ------------------------------------
        self._toggle_modifiers: list[str] = []
        self._toggle_trigger_key: str = ""
        self._toggle_trigger_vk: int | None = None
        self.set_toggle_hotkey(_DEFAULT_TOGGLE_HOTKEY)

        # -- Listener handles -----------------------------------------------
        self._keyboard_listener: object | None = None
        self._mouse_listener: object | None = None
        self._running: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_toggle_hotkey(self, config_str: str) -> None:
        """Configure the toggle-overlay hotkey from a ``+``-separated string.

        Example: ``"ctrl+alt+a"``.  Automatically converts the trigger key
        to its Windows virtual-key code for reliable Alt+key detection.
        """
        self._toggle_modifiers, self._toggle_trigger_key, self._toggle_trigger_vk = (
            parse_hotkey(config_str)
        )
        logger.info(
            "[HOTKEY] toggle hotkey configured: modifiers=%s, trigger=%s, vk=%s",
            self._toggle_modifiers, self._toggle_trigger_key, self._toggle_trigger_vk,
        )

    def start(self) -> None:
        """Start global hotkey listeners.

        Spawns *pynput* ``keyboard.Listener`` and ``mouse.Listener`` in
        daemon background threads.  Safe to call multiple times — subsequent
        calls are no-ops if already running.
        """
        if self._running:
            return

        try:
            import pynput.keyboard  # noqa: F811
            import pynput.mouse

            self._keyboard_listener = pynput.keyboard.Listener(
                on_press=self._on_key_press,
                on_release=self._on_key_release,
            )
            self._mouse_listener = pynput.mouse.Listener(
                on_click=self._on_mouse_click,
            )

            self._keyboard_listener.start()  # type: ignore[union-attr]
            self._mouse_listener.start()  # type: ignore[union-attr]
            self._running = True

            logger.info("全局热键监听已启动")
        except Exception:
            logger.exception("启动全局热键监听失败")
            self._running = False

    def stop(self) -> None:
        """Stop all listeners and reset internal state.

        Safe to call when not running (no-op).
        """
        if not self._running:
            return

        try:
            if self._keyboard_listener is not None:
                self._keyboard_listener.stop()  # type: ignore[union-attr]
                self._keyboard_listener = None
            if self._mouse_listener is not None:
                self._mouse_listener.stop()  # type: ignore[union-attr]
                self._mouse_listener = None
        except Exception:
            logger.exception("停止热键监听时发生异常")
        finally:
            self._ctrl_pressed = False
            self._shift_pressed = False
            self._alt_pressed = False
            self._running = False
            logger.info("全局热键监听已停止")

    # ------------------------------------------------------------------
    # pynput callbacks (executed on background threads)
    # ------------------------------------------------------------------

    def _on_key_press(self, key: Key | KeyCode | None) -> None:
        """Handle keyboard press events."""
        try:
            self._handle_key_press(key)
        except Exception:
            logger.exception("[HOTKEY] _on_key_press raised — listener may die")

    def _handle_key_press(self, key: Key | KeyCode | None) -> None:
        """Actual key-press logic (isolated for exception safety)."""
        if key is None:
            return

        key_name: str = self._key_to_name(key)

        # Track modifier state
        if key_name in _CTRL_KEYS:
            if not self._ctrl_pressed:
                logger.info("[HOTKEY] ctrl pressed")
            self._ctrl_pressed = True
        elif key_name in _SHIFT_KEYS:
            if not self._shift_pressed:
                logger.info("[HOTKEY] shift pressed")
            self._shift_pressed = True
        elif key_name in _ALT_KEYS:
            if not self._alt_pressed:
                self._alt_pressed = True
                self.alt_state_changed.emit(True)
                logger.info("[HOTKEY] alt pressed — _alt_pressed=True")
        else:
            # Non-modifier key — log when modifiers are active
            if self._ctrl_pressed or self._alt_pressed or self._shift_pressed:
                logger.info(
                    "[HOTKEY] key=%s, ctrl=%s, alt=%s, shift=%s",
                    key_name, self._ctrl_pressed,
                    self._alt_pressed, self._shift_pressed,
                )

        # Configurable toggle hotkey check
        if self._toggle_trigger_key and self._toggle_modifiers:
            # Match by name or by VK code (Windows Alt+key fallback)
            trigger_match = key_name == self._toggle_trigger_key
            if not trigger_match and self._toggle_trigger_vk is not None:
                vk = getattr(key, "vk", None)
                if vk is not None and vk == self._toggle_trigger_vk:
                    trigger_match = True

            if trigger_match:
                # Check all required modifiers are pressed
                all_mods = all(
                    getattr(self, f"_{m.replace('_l', '').replace('_r', '')}_pressed", False)
                    for m in self._toggle_modifiers
                )
                if all_mods:
                    logger.info(
                        "[HOTKEY] toggle hotkey detected → toggle_overlay_requested.emit()"
                    )
                    self.toggle_overlay_requested.emit()

    def _on_key_release(self, key: Key | KeyCode | None) -> None:
        """Handle keyboard release events."""
        try:
            self._handle_key_release(key)
        except Exception:
            logger.exception("[HOTKEY] _on_key_release raised — listener may die")

    def _handle_key_release(self, key: Key | KeyCode | None) -> None:
        """Actual key-release logic (isolated for exception safety)."""
        if key is None:
            return

        key_name: str = self._key_to_name(key)

        if key_name in _CTRL_KEYS:
            self._ctrl_pressed = False
        elif key_name in _SHIFT_KEYS:
            self._shift_pressed = False
        elif key_name in _ALT_KEYS and self._alt_pressed:
            self._alt_pressed = False
            self.alt_state_changed.emit(False)

    def _on_mouse_click(self, x: int, y: int, button: Button, pressed: bool) -> None:
        """Handle mouse click events."""
        try:
            self._handle_mouse_click(x, y, button, pressed)
        except Exception:
            logger.exception("[HOTKEY] _on_mouse_click raised — listener may die")

    def _handle_mouse_click(self, x: int, y: int, button: Button, pressed: bool) -> None:
        """Actual mouse-click logic (isolated for exception safety)."""
        if not pressed:
            return

        button_name: str = button.name if hasattr(button, "name") else str(button)

        # Ctrl+Shift+LeftClick → screenshot
        if (
            button_name == _LEFT_BUTTON
            and self._ctrl_pressed
            and self._shift_pressed
        ):
            self.screenshot_requested.emit()

        # Ctrl+Shift+RightClick → move overlay to cursor
        if (
            button_name == _RIGHT_BUTTON
            and self._ctrl_pressed
            and self._shift_pressed
        ):
            self.move_overlay_to_cursor.emit(x, y)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _key_to_name(key: Key | KeyCode | None) -> str:
        """Convert a pynput key object to its lowercase string name."""
        if key is None:
            return ""
        if hasattr(key, "name"):
            return key.name.lower()  # type: ignore[union-attr]
        # KeyCode — has a .char attribute
        char = getattr(key, "char", None)
        if char is not None:
            return char.lower()
        # On Windows, Alt+key strips .char — fall back to virtual-key code
        vk = getattr(key, "vk", None)
        if vk is not None and 0x30 <= vk <= 0x5A:
            return chr(vk).lower()
        return str(key).lower()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """Whether hotkey listeners are currently active."""
        return self._running
