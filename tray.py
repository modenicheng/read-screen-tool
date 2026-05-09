"""System tray icon manager using pystray."""

import logging
from typing import Optional

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


def _create_default_icon():
    """Create a simple default icon for the tray.

    Returns a PIL Image icon (16x16 or 32x32).
    """
    from PIL import Image, ImageDraw

    # Create a simple colored square icon
    size = 32
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Draw a rounded rectangle approximation
    margin = 4
    draw.rectangle(
        [margin, margin, size - margin - 1, size - margin - 1],
        fill=(0, 120, 255, 255),
    )

    # Draw an "R" letter for "Read"
    draw.text((size // 2 - 5, size // 2 - 8), "R", fill=(255, 255, 255, 255))

    return img


class TrayManager(QObject):
    """Manages the system tray icon with configurable visibility.

    Provides show/hide/exit menu items and signals for Qt main thread integration.

    Usage:
        tray = TrayManager(show_icon=True)
        tray.show_requested.connect(on_show)
        tray.hide_requested.connect(on_hide)
        tray.exit_requested.connect(app.quit)
        tray.start()
    """

    show_requested = Signal()
    hide_requested = Signal()
    exit_requested = Signal()

    def __init__(
        self,
        show_icon: bool = True,
        icon: Optional[object] = None,
        tooltip: str = "Read Screen Tool",
    ):
        """Initialize tray manager.

        Args:
            show_icon: Whether to show the tray icon
            icon: PIL Image for tray icon (None = use default)
            tooltip: Tooltip text for the tray icon
        """
        super().__init__()
        self._show_icon = show_icon
        self._icon = icon if icon else _create_default_icon()
        self._tooltip = tooltip
        self._tray: Optional[object] = None
        self._running = False

    def start(self):
        """Start the tray icon (if show_icon is True)."""
        if not self._show_icon:
            logger.info("Tray icon disabled by configuration.")
            return

        try:
            import pystray
            import threading

            # Build menu
            menu = pystray.Menu(
                pystray.MenuItem("Show", self._on_show, default=True),
                pystray.MenuItem("Hide", self._on_hide),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Exit", self._on_exit),
            )

            self._tray = pystray.Icon(
                name="read-screen-tool",
                icon=self._icon,
                title=self._tooltip,
                menu=menu,
            )

            # Run pystray in a separate thread
            self._thread = threading.Thread(target=self._tray.run, daemon=True)
            self._thread.start()
            self._running = True

            logger.info("Tray icon started.")
        except ImportError:
            logger.warning("pystray not available.")
        except Exception as e:
            logger.error(f"Failed to start tray icon: {e}")

    def stop(self):
        """Stop and remove the tray icon."""
        if self._tray and self._running:
            try:
                self._tray.stop()
                self._running = False
                logger.info("Tray icon stopped.")
            except Exception as e:
                logger.error(f"Error stopping tray icon: {e}")

    def _on_show(self, icon=None, item=None):
        """Show menu callback."""
        self.show_requested.emit()

    def _on_hide(self, icon=None, item=None):
        """Hide menu callback."""
        self.hide_requested.emit()

    def _on_exit(self, icon=None, item=None):
        """Exit menu callback."""
        self.exit_requested.emit()
        self.stop()

    @property
    def is_running(self) -> bool:
        """Whether the tray icon is currently active."""
        return self._running
