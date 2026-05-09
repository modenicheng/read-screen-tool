"""Global hotkey management using pynput, bridged to Qt via pyqtSignal.

Provides a ``HotkeyManager`` that listens for global keyboard and mouse events
in background threads and emits Qt signals on the main thread when hotkey
combinations are detected.

Hotkeys:
    - **Ctrl+Shift+LeftClick** → ``screenshot_requested``
    - **Ctrl+Shift+Z** → ``toggle_overlay_requested``
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
_CTRL_KEYS: tuple[str, ...] = ("ctrl_l", "ctrl_r")
_SHIFT_KEYS: tuple[str, ...] = ("shift", "shift_l", "shift_r")
_Z_KEY: str = "z"
_LEFT_BUTTON: str = "left"


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
    """Emitted when Ctrl+Shift+Z is pressed."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

        # -- Modifier state -------------------------------------------------
        self._ctrl_pressed: bool = False
        self._shift_pressed: bool = False

        # -- Listener handles -----------------------------------------------
        self._keyboard_listener: object | None = None
        self._mouse_listener: object | None = None
        self._running: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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
            self._running = False
            logger.info("全局热键监听已停止")

    # ------------------------------------------------------------------
    # pynput callbacks (executed on background threads)
    # ------------------------------------------------------------------

    def _on_key_press(self, key: Key | KeyCode | None) -> None:
        """Handle keyboard press events."""
        if key is None:
            return

        key_name: str = self._key_to_name(key)

        # Track modifier state
        if key_name in _CTRL_KEYS:
            self._ctrl_pressed = True
        elif key_name in _SHIFT_KEYS:
            self._shift_pressed = True

        # Ctrl+Shift+Z → toggle overlay
        if key_name == _Z_KEY and self._ctrl_pressed and self._shift_pressed:
            self.toggle_overlay_requested.emit()

    def _on_key_release(self, key: Key | KeyCode | None) -> None:
        """Handle keyboard release events."""
        if key is None:
            return

        key_name: str = self._key_to_name(key)

        if key_name in _CTRL_KEYS:
            self._ctrl_pressed = False
        elif key_name in _SHIFT_KEYS:
            self._shift_pressed = False

    def _on_mouse_click(self, x: int, y: int, button: Button, pressed: bool) -> None:
        """Handle mouse click events."""
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
        return str(key).lower()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """Whether hotkey listeners are currently active."""
        return self._running
