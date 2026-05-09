"""Transparent frameless always-on-top floating output window for LLM responses."""

from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt, QPoint, QRect, Signal
from PySide6.QtGui import QPainter, QColor, QFont, QFontMetrics, QPen, QMouseEvent
from PySide6.QtWidgets import QWidget


class OutputOverlay(QWidget):
    """Transparent floating window displaying LLM response text.

    Features:
    - No background, no title bar, no taskbar icon
    - Text with shadow for readability
    - Alt+mouse drag to move, Alt+right-drag to resize
    - Ctrl+Shift+Z toggles visibility (via external hotkey)
    - Horizontal rule between replies
    - Selectable text
    """

    text_added = Signal(str)  # emits newly added text

    def __init__(
        self,
        parent=None,
        font_family: str = "Microsoft YaHei",
        font_size: int = 14,
        font_color: str = "#FFFFFF",
        shadow: bool = True,
    ):
        super().__init__(parent)

        # Window flags
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        # Text buffer -- list of text blocks (each block = one reply)
        self._text_blocks: List[str] = []

        # Font config
        self._font_family = font_family
        self._font_size = font_size
        self._font_color = QColor(font_color)
        self._shadow_enabled = shadow

        # Drag state
        self._dragging = False
        self._resizing = False
        self._drag_start_pos = QPoint()
        self._alt_held = False

        # Set default size
        self.resize(600, 400)
        self.move(100, 100)

        # Enable mouse tracking for Alt+drag detection
        self.setMouseTracking(True)

    def append_text(self, text: str) -> None:
        """Append text to the current (last) text block."""
        if not self._text_blocks:
            self._text_blocks.append("")
        self._text_blocks[-1] += text
        self.text_added.emit(text)
        self.update()

    def add_separator(self) -> None:
        """Add a horizontal rule separator between replies."""
        self._text_blocks.append("")
        self.update()

    def clear(self) -> None:
        """Clear all text blocks."""
        self._text_blocks.clear()
        self.update()

    def toggle_visibility(self) -> None:
        """Toggle window visibility."""
        if self.isVisible():
            self.hide()
        else:
            self.show()

    def set_position(self, x: int, y: int) -> None:
        """Move window to position."""
        self.move(x, y)

    def set_size(self, w: int, h: int) -> None:
        """Resize window."""
        self.resize(w, h)

    def paintEvent(self, event):  # noqa: N802
        """Paint text blocks with shadow effect."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        font = QFont(self._font_family, self._font_size)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        line_height = metrics.height() + 4

        y = 10
        margin = 10
        max_width = self.width() - 2 * margin

        for i, block in enumerate(self._text_blocks):
            if i > 0 and block == "":
                # Draw separator line
                painter.setPen(QPen(QColor(255, 255, 255, 80), 1))
                painter.drawLine(margin, y + 4, self.width() - margin, y + 4)
                y += 12
                continue

            if not block:
                continue

            # Draw text with shadow
            if self._shadow_enabled:
                painter.setPen(QColor(0, 0, 0, 160))
                self._draw_text_block(painter, block, margin + 1, y + 1, max_width, line_height)

            painter.setPen(self._font_color)
            self._draw_text_block(painter, block, margin, y, max_width, line_height)

            # Calculate vertical advance
            text_rect = metrics.boundingRect(
                QRect(margin, y, max_width, 0),
                Qt.TextWordWrap | Qt.AlignLeft,
                block,
            )
            y += max(text_rect.height(), line_height) + 4

    def _draw_text_block(
        self,
        painter: QPainter,
        text: str,
        x: int,
        y: int,
        max_width: int,
        line_height: int,  # noqa: ARG002
    ) -> None:
        """Draw a single text block with word wrapping."""
        rect = QRect(x, y, max_width, 0)
        painter.drawText(rect, Qt.TextWordWrap | Qt.AlignLeft, text)

    def keyPressEvent(self, event):  # noqa: N802
        """Track Alt key for drag detection."""
        if event.key() == Qt.Key_Alt:
            self._alt_held = True
            event.accept()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):  # noqa: N802
        """Track Alt key release."""
        if event.key() == Qt.Key_Alt:
            self._alt_held = False
            self._dragging = False
            self._resizing = False
            event.accept()
        else:
            super().keyReleaseEvent(event)

    def mousePressEvent(self, event: QMouseEvent):  # noqa: N802
        """Start drag/resize when Alt is held."""
        if self._alt_held:
            if event.button() == Qt.LeftButton:
                self._dragging = True
                self._drag_start_pos = event.globalPos() - self.frameGeometry().topLeft()
                self.setCursor(Qt.ClosedHandCursor)
            elif event.button() == Qt.RightButton:
                self._resizing = True
                self._drag_start_pos = event.globalPos()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):  # noqa: N802
        """Move/resize while dragging."""
        if self._dragging:
            delta = (
                event.globalPos()
                - self._drag_start_pos
                - self.frameGeometry().topLeft()
            )
            self.move(self.pos() + delta)
            self._drag_start_pos = event.globalPos() - self.frameGeometry().topLeft()
        elif self._resizing:
            delta = event.globalPos() - self._drag_start_pos
            new_w = max(200, self.width() + delta.x())
            new_h = max(100, self.height() + delta.y())
            self.resize(new_w, new_h)
            self._drag_start_pos = event.globalPos()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):  # noqa: N802
        """End drag/resize."""
        if self._dragging:
            self._dragging = False
            self.setCursor(Qt.ArrowCursor)
        elif self._resizing:
            self._resizing = False
        else:
            super().mouseReleaseEvent(event)
