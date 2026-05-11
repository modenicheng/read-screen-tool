"""Transparent frameless always-on-top overlay, reimplemented with tkinter."""

import logging
import tkinter as tk

from signals import Signal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level shared Tk root
# ---------------------------------------------------------------------------

_root: tk.Tk | None = None


def _get_root() -> tk.Tk:
    """Return the singleton hidden Tk root, creating it on first call."""
    global _root
    if _root is None:
        _root = tk.Tk()
        _root.withdraw()  # Never show the root window
    return _root


# ---------------------------------------------------------------------------
# OutputOverlay — transparent frameless always-on-top text overlay
# ---------------------------------------------------------------------------


class OutputOverlay:
    """Transparent frameless always-on-top text overlay."""

    text_added = Signal(str)

    def __init__(
        self,
        parent=None,
        font_family: str = "Microsoft YaHei",
        font_size: int = 14,
        font_color: str = "#FFFFFF",
        shadow: bool = True,
    ):
        self._root = _get_root()
        self._window = tk.Toplevel(self._root)

        # Frameless, always-on-top
        self._window.overrideredirect(True)
        self._window.wm_attributes("-topmost", True)

        # Overall window transparency (0.0 = invisible, 1.0 = opaque)
        self._window.configure(bg="#1e1e1e")
        self._window.wm_attributes("-alpha", 0.12)

        # Font / color config (exposed for tests)
        self._font_family = font_family
        self._font_size = font_size
        self._font_color = font_color
        self._shadow_enabled = shadow
        self._shadow_effect = None  # tkinter has no QGraphicsDropShadow equivalent

        # Plain text widget — fills entire window
        self._text_widget = tk.Text(
            self._window,
            bg="#1e1e1e",
            fg=font_color,
            font=(font_family, font_size),
            relief=tk.FLAT,
            wrap=tk.WORD,
            highlightthickness=0,
            insertbackground=font_color,
            padx=8,
            pady=8,
        )
        self._text_widget.pack(fill=tk.BOTH, expand=True)

        # Buffer for streaming text (backward compat)
        self._text_blocks: list[str] = [""]

        # Default geometry
        self._window.geometry("600x400+100+100")

        # Show by default (matches Qt original behavior)
        self._visible = True
        self._window.deiconify()
        self._root.update_idletasks()

    # -----------------------------------------------------------------------
    # Visibility
    # -----------------------------------------------------------------------

    def show(self) -> None:
        """Show the overlay window.

        Uses alpha instead of withdraw/deiconify because on Windows,
        ``deiconify()`` cannot restore ``overrideredirect(True)`` windows
        after ``withdraw()`` (the WM doesn't track them).
        """
        self._visible = True
        self._window.wm_attributes("-alpha", 0.82)
        self._root.update_idletasks()
        logger.info("[OVERLAY] show() — alpha=%.2f, visible=%s", 0.82, self._visible)

    def hide(self) -> None:
        """Hide the overlay window.

        Sets alpha to 0 instead of ``withdraw()`` — see :meth:`show`.
        """
        self._visible = False
        self._window.wm_attributes("-alpha", 0.0)
        self._root.update_idletasks()
        logger.info("[OVERLAY] hide() — alpha=%.2f, visible=%s", 0.0, self._visible)

    def isVisible(self) -> bool:  # noqa: N802
        """Return whether the overlay window is currently visible."""
        return self._visible

    def toggle_visibility(self) -> None:
        """Toggle the overlay window between visible and hidden."""
        logger.info("[OVERLAY] toggle_visibility() — current visible=%s", self._visible)
        if self.isVisible():
            self.hide()
        else:
            self.show()

    def close(self) -> None:
        """Destroy the overlay window."""
        self._window.destroy()

    # -----------------------------------------------------------------------
    # Text content
    # -----------------------------------------------------------------------

    def append_text(self, text: str) -> None:
        """Append text to the output widget.

        Streaming-friendly: each call inserts at the end and auto-scrolls.
        """
        self._text_widget.insert(tk.END, text)
        self._text_widget.see(tk.END)

        # Buffer management (backward compat — tests depend on _text_blocks)
        if not self._text_blocks:
            self._text_blocks = [""]
        self._text_blocks[-1] += text

        self._root.update_idletasks()
        self.text_added.emit(text)

    def add_separator(self) -> None:
        """Add a horizontal separator line between text blocks."""
        self._text_widget.insert(tk.END, "\n" + "─" * 40 + "\n\n")
        self._text_widget.see(tk.END)
        self._text_blocks.append("")

    def clear(self) -> None:
        """Clear all text blocks and reset the widget."""
        self._text_widget.delete("1.0", tk.END)
        self._text_blocks.clear()

    # -----------------------------------------------------------------------
    # Window geometry
    # -----------------------------------------------------------------------

    def set_position(self, x: int, y: int) -> None:
        """Move the overlay window to (*x*, *y*) screen coordinates."""
        geo = self._window.geometry()
        size_part = geo.split("+")[0] if "+" in geo else "600x400"
        self._window.geometry(f"{size_part}+{x}+{y}")
        self._root.update_idletasks()

    def set_size(self, w: int, h: int) -> None:
        """Resize the overlay window to *w* × *h* pixels, preserving position."""
        current = self._window.geometry()
        parts = current.split("+")
        x = parts[1] if len(parts) > 1 else "100"
        y = parts[2] if len(parts) > 2 else "100"
        self._window.geometry(f"{w}x{h}+{x}+{y}")
        self._root.update_idletasks()

    def move_to_cursor(self, x: int, y: int) -> None:
        """Move the overlay window to the cursor position (*x*, *y*)."""
        self.set_position(x, y)

    def pump(self) -> None:
        """Process pending tkinter events. Call from Qt timer (~30ms)."""
        self._root.update()
