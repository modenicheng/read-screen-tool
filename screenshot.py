from __future__ import annotations

import ctypes
import logging
import tkinter as tk
from ctypes import wintypes

import mss
import numpy as np

from overlay import _get_root
from signals import Signal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Windows API helpers
# ---------------------------------------------------------------------------

MONITOR_DEFAULTTONEAREST = 2
_GWL_EXSTYLE = -20
_WS_EX_TRANSPARENT = 0x00000020
_TRANSPARENT_COLOR = "#010101"


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
    ]


# ---------------------------------------------------------------------------
# ScreenshotOverlay — tkinter-based rectangular screenshot selection
# ---------------------------------------------------------------------------


class ScreenshotOverlay:
    """Full-screen transparent overlay for rectangular screenshot selection.

    Uses a two-window approach for true per-pixel transparency:

    * **Capture window** — nearly invisible (alpha ≈ 0), covers the full
      monitor and receives all mouse / keyboard events.
    * **Overlay window** — uses ``-transparentcolor`` so its background is
      completely transparent while the selection border and size label
      remain fully opaque.  ``WS_EX_TRANSPARENT`` ensures all input events
      pass through to the capture window beneath.

    Usage::

        overlay = ScreenshotOverlay()
        overlay.screenshot_taken.connect(handle_screenshot)
        overlay.start_selection()
    """

    screenshot_taken = Signal(object)  # emits np.ndarray (BGR format from mss)
    selection_cancelled = Signal()

    def __init__(self) -> None:
        # State
        self._selecting = False
        self._start_point: tuple[int, int] = (0, 0)
        self._end_point: tuple[int, int] = (0, 0)

        # Per-selection window references (cleared after destroy)
        self._capture_win: tk.Toplevel | None = None
        self._overlay_win: tk.Toplevel | None = None
        self._canvas: tk.Canvas | None = None
        self._mon_left: int = 0
        self._mon_top: int = 0
        self._mon_w: int = 0
        self._mon_h: int = 0

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def start_selection(self) -> None:
        """Show overlay full-screen on the cursor's monitor and begin selection.

        The mouse button is already pressed when the hotkey triggers,
        so the cursor position is auto-captured as the selection origin.
        """
        # Destroy any previous windows (safety)
        self._cleanup()

        # ── Get cursor position ────────────────────────────────────────
        pt = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        cursor_x, cursor_y = pt.x, pt.y

        # ── Get monitor geometry ───────────────────────────────────────
        hmonitor = ctypes.windll.user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST)
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        ctypes.windll.user32.GetMonitorInfoW(hmonitor, ctypes.byref(mi))

        mon_left = int(mi.rcMonitor.left)
        mon_top = int(mi.rcMonitor.top)
        mon_w = int(mi.rcMonitor.right) - mon_left
        mon_h = int(mi.rcMonitor.bottom) - mon_top

        logger.info(
            "[SCREENSHOT] start_selection() — cursor=(%d,%d), monitor=(%d,%d,%d,%d)",
            cursor_x, cursor_y, mon_left, mon_top, mi.rcMonitor.right, mi.rcMonitor.bottom,
        )

        root = _get_root()

        # ── Capture window (invisible, handles all input) ──────────────
        cap = tk.Toplevel(root)
        cap.overrideredirect(True)
        cap.wm_attributes("-topmost", True)
        cap.wm_attributes("-alpha", 0.01)  # nearly invisible
        cap.configure(bg="black")
        cap.geometry(f"{mon_w}x{mon_h}+{mon_left}+{mon_top}")

        # ── Overlay window (transparent bg, visible border) ────────────
        ovl = tk.Toplevel(root)
        ovl.overrideredirect(True)
        ovl.wm_attributes("-topmost", True)
        ovl.wm_attributes("-alpha", 1.0)
        ovl.wm_attributes("-transparentcolor", _TRANSPARENT_COLOR)
        ovl.configure(bg=_TRANSPARENT_COLOR)
        ovl.geometry(f"{mon_w}x{mon_h}+{mon_left}+{mon_top}")

        # Make overlay transparent to mouse events (WS_EX_TRANSPARENT)
        # so all input passes through to the capture window.
        ovl.update_idletasks()
        hwnd = ovl.winfo_id()
        ex_style = ctypes.windll.user32.GetWindowLongPtrW(hwnd, _GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongPtrW(
            hwnd, _GWL_EXSTYLE, ex_style | _WS_EX_TRANSPARENT,
        )

        # Canvas on overlay (bg matches transparent color → invisible)
        canvas = tk.Canvas(ovl, bg=_TRANSPARENT_COLOR, highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True)

        # ── Store references ───────────────────────────────────────────
        self._capture_win = cap
        self._overlay_win = ovl
        self._canvas = canvas
        self._mon_left = mon_left
        self._mon_top = mon_top
        self._mon_w = mon_w
        self._mon_h = mon_h

        # ── Initial selection state ────────────────────────────────────
        self._selecting = True
        # Window-local coords = screen coords − monitor origin
        self._start_point = (cursor_x - mon_left, cursor_y - mon_top)
        self._end_point = self._start_point

        # ── Cursor + focus ─────────────────────────────────────────────
        cap.config(cursor="crosshair")
        cap.focus_force()

        # ── Bind events on capture window ──────────────────────────────
        cap.bind("<Button-1>", self._on_mouse_press)
        cap.bind("<B1-Motion>", self._on_mouse_drag)
        cap.bind("<ButtonRelease-1>", self._on_mouse_release)
        cap.bind("<Escape>", self._on_escape)

        # ── Initial draw ───────────────────────────────────────────────
        self._redraw()

    # -----------------------------------------------------------------------
    # Drawing (Canvas)
    # -----------------------------------------------------------------------

    def _redraw(self) -> None:
        """Redraw the selection border and size label.

        Only the border and label are visible — the canvas background
        matches ``-transparentcolor`` so everything else is fully
        transparent.
        """
        canvas = self._canvas
        if canvas is None:
            return

        canvas.delete("all")

        sel_x, sel_y, sel_w, sel_h = self._get_selection_rect()

        # Selection border — fully opaque blue
        canvas.create_rectangle(
            sel_x, sel_y, sel_x + sel_w, sel_y + sel_h,
            outline="#0078FF", width=2, fill="",
        )

        # Size label (top-left inside selection)
        canvas.create_text(
            sel_x + 6, sel_y + 2,
            text=f"{sel_w} x {sel_h}",
            anchor="nw",
            fill="white",
            font=("Microsoft YaHei", 10),
        )

    # -----------------------------------------------------------------------
    # Event handlers
    # -----------------------------------------------------------------------

    def _on_mouse_press(self, event: tk.Event) -> None:
        """Handle mouse button press — start new selection."""
        self._selecting = True
        self._start_point = (event.x, event.y)
        self._end_point = (event.x, event.y)
        self._redraw()

    def _on_mouse_drag(self, event: tk.Event) -> None:
        """Handle mouse drag — update selection endpoint."""
        if self._selecting:
            self._end_point = (event.x, event.y)
            self._redraw()

    def _on_mouse_release(self, event: tk.Event) -> None:
        """Handle mouse button release — capture or cancel."""
        if not self._selecting:
            return

        self._selecting = False

        sel_x, sel_y, sel_w, sel_h = self._get_selection_rect()
        logger.info(
            "[SCREENSHOT] mouseRelease — rect=(%d,%d,%d,%d), w=%d, h=%d",
            sel_x, sel_y, sel_w, sel_h, sel_w, sel_h,
        )

        if sel_w > 10 and sel_h > 10:
            img = self._capture_screen_region(sel_x, sel_y, sel_w, sel_h)
            logger.info(
                "[SCREENSHOT] captured image shape=%s, dtype=%s",
                img.shape, img.dtype,
            )
            self._cleanup()
            self.screenshot_taken.emit(img)
        else:
            logger.info(
                "[SCREENSHOT] selection too small (%dx%d), cancelled",
                sel_w, sel_h,
            )
            self._cleanup()
            self.selection_cancelled.emit()

    def _on_escape(self, event: tk.Event) -> None:
        """Handle Escape key — cancel selection."""
        self._selecting = False
        self._cleanup()
        self.selection_cancelled.emit()

    def _cleanup(self) -> None:
        """Destroy both overlay windows and clear references."""
        if self._capture_win is not None:
            self._capture_win.destroy()
        if self._overlay_win is not None:
            self._overlay_win.destroy()
        self._capture_win = None
        self._overlay_win = None
        self._canvas = None

    # -----------------------------------------------------------------------
    # Coordinate helpers
    # -----------------------------------------------------------------------

    def _get_selection_rect(self) -> tuple[int, int, int, int]:
        """Return normalized (x, y, w, h) — width/height always positive."""
        x1, y1 = self._start_point
        x2, y2 = self._end_point
        x = min(x1, x2)
        y = min(y1, y2)
        w = abs(x2 - x1)
        h = abs(y2 - y1)
        return (x, y, w, h)

    def _capture_screen_region(self, x: int, y: int, w: int, h: int) -> np.ndarray:
        """Capture the selected region using mss.

        Converts window-local coordinates to global screen coordinates
        by adding the monitor origin offset, so capture works correctly
        on multi-monitor setups where the screen origin is not (0, 0).
        """
        monitor = {
            "left": x + self._mon_left,
            "top": y + self._mon_top,
            "width": w,
            "height": h,
        }
        with mss.mss() as sct:
            img = sct.grab(monitor)
            # Convert to numpy array (BGRA -> BGR)
            arr: np.ndarray = np.array(img)
            return arr[:, :, :3]  # drop alpha channel
