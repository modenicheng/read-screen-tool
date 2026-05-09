from __future__ import annotations

import numpy as np
import mss
from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget


class ScreenshotOverlay(QWidget):
    """Full-screen transparent overlay for rectangular screenshot selection.

    Usage:
        overlay = ScreenshotOverlay()
        overlay.screenshot_taken.connect(handle_screenshot)
        overlay.start_selection()
    """

    screenshot_taken = Signal(object)  # emits np.ndarray (BGR format from mss)
    selection_cancelled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Window flags: frameless, stay on top, no taskbar, transparent
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        # State
        self._selecting = False
        self._start_point = QPoint()
        self._end_point = QPoint()

        # Style
        self._border_color = QColor(0, 120, 255)
        self._border_width = 2
        self._overlay_color = QColor(0, 0, 0, 80)  # semi-transparent dark

    def start_selection(self) -> None:
        """Show overlay full-screen and begin selection mode."""
        screen = QApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())
        self.showFullScreen()
        self.setCursor(Qt.CrossCursor)
        self._selecting = False
        self._start_point = QPoint()
        self._end_point = QPoint()
        self.update()

    def _get_selection_rect(self) -> QRect:
        """Get normalized selection rectangle (width/height always positive)."""
        return QRect(
            min(self._start_point.x(), self._end_point.x()),
            min(self._start_point.y(), self._end_point.y()),
            abs(self._end_point.x() - self._start_point.x()),
            abs(self._end_point.y() - self._start_point.y()),
        )

    def _capture_screen_region(self, rect: QRect) -> np.ndarray:
        """Capture the selected region using mss. Returns numpy array."""
        monitor = {
            "left": rect.x(),
            "top": rect.y(),
            "width": rect.width(),
            "height": rect.height(),
        }
        with mss.mss() as sct:
            img = sct.grab(monitor)
            # Convert to numpy array (BGRA -> BGR)
            arr: np.ndarray = np.array(img)
            return arr[:, :, :3]  # drop alpha channel

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        """Draw the overlay: semi-transparent background with clear selection rectangle."""
        painter = QPainter(self)

        if not self._selecting or self._start_point.isNull():
            # No selection yet: draw full semi-transparent overlay
            painter.fillRect(self.rect(), QColor(0, 0, 0, 40))
            return

        # Draw semi-transparent overlay
        painter.fillRect(self.rect(), self._overlay_color)

        # Get selection rect
        sel_rect = self._get_selection_rect()

        # Clear the selection area (make it fully transparent)
        painter.setCompositionMode(QPainter.CompositionMode_Clear)
        painter.fillRect(sel_rect, Qt.transparent)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

        # Draw selection border
        pen = QPen(self._border_color, self._border_width)
        painter.setPen(pen)
        painter.drawRect(sel_rect)

        # Draw size label
        if sel_rect.width() > 50 and sel_rect.height() > 20:
            label = f"{sel_rect.width()} x {sel_rect.height()}"
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(
                sel_rect.adjusted(4, 4, -4, -4),
                Qt.AlignLeft | Qt.AlignTop,
                label,
            )

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.button() == Qt.LeftButton:
            self._selecting = True
            self._start_point = event.position().toPoint()
            self._end_point = event.position().toPoint()
            self.update()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._selecting:
            self._end_point = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.button() == Qt.LeftButton and self._selecting:
            self._selecting = False
            sel_rect = self._get_selection_rect()

            if sel_rect.width() > 10 and sel_rect.height() > 10:
                # Valid selection: capture and emit
                img = self._capture_screen_region(sel_rect)
                self.hide()
                self.screenshot_taken.emit(img)
            else:
                # Selection too small: cancel
                self.hide()
                self.selection_cancelled.emit()

    def keyPressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.key() == Qt.Key_Escape:
            self._selecting = False
            self.hide()
            self.selection_cancelled.emit()
