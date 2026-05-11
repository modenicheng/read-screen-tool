"""Transparent frameless always-on-top overlay, reimplemented with tkinter."""

import logging
import re
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
# Inline markdown parser
# ---------------------------------------------------------------------------

# Match priority: code > bold > italic (code prevents * and _ inside)
_CODE_RE = re.compile(r"`([^`]+?)`")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)|(?<!_)_(?!_)(.+?)(?<!_)_(?!_)")


def _parse_inline(text: str) -> list[tuple[str, tuple[str, ...]]]:
    """Parse inline markdown formatting (*bold*, *italic*, ``code``).

    Returns a list of ``(segment_text, tags)`` tuples where *tags* is a
    (possibly empty) tuple of tk.Text tag names.  Unmatched delimiters
    are rendered as plain text so partial streaming output looks natural.
    """
    if not text:
        return [("", ())]

    segments: list[tuple[str, tuple[str, ...]]] = []

    # Phase 1 — code spans (highest priority, prevents inner formatting)
    code_map: dict[str, str] = {}
    _placeholder_id = 0

    def _replace_code(m: re.Match[str]) -> str:
        nonlocal _placeholder_id
        content = m.group(1)
        placeholder = f"\x00CODE{_placeholder_id}\x00"
        code_map[placeholder] = content
        _placeholder_id += 1
        return placeholder

    protected = _CODE_RE.sub(_replace_code, text)

    # Phase 2 — bold spans on protected text
    bold_map: dict[str, str] = {}

    def _replace_bold(m: re.Match[str]) -> str:
        nonlocal _placeholder_id
        content = m.group(1) or m.group(2)
        placeholder = f"\x00BOLD{_placeholder_id}\x00"
        bold_map[placeholder] = content
        _placeholder_id += 1
        return placeholder

    protected = _BOLD_RE.sub(_replace_bold, protected)

    # Phase 3 — italic spans
    italic_map: dict[str, str] = {}

    def _replace_italic(m: re.Match[str]) -> str:
        nonlocal _placeholder_id
        content = m.group(1) or m.group(2)
        if content is None:
            return m.group(0)
        placeholder = f"\x00ITALIC{_placeholder_id}\x00"
        italic_map[placeholder] = content
        _placeholder_id += 1
        return placeholder

    protected = _ITALIC_RE.sub(_replace_italic, protected)

    # Build segments from protected text
    tag_pattern = re.compile(r"\x00(CODE|BOLD|ITALIC)(\d+)\x00")
    pos = 0
    for m in tag_pattern.finditer(protected):
        if m.start() > pos:
            segments.append((protected[pos : m.start()], ()))
        kind = m.group(1)
        placeholder = m.group(0)
        if kind == "CODE":
            segments.append((code_map[placeholder], ("code",)))
        elif kind == "BOLD":
            segments.append((bold_map[placeholder], ("bold",)))
        elif kind == "ITALIC":
            segments.append((italic_map[placeholder], ("italic",)))
        pos = m.end()

    if pos < len(protected):
        segments.append((protected[pos:], ()))

    return segments or [("", ())]


# ---------------------------------------------------------------------------
# OutputOverlay — transparent frameless always-on-top text overlay
# ---------------------------------------------------------------------------

# Regex patterns for block-level markdown detection
_H1_RE = re.compile(r"^#\s+(.+)$")
_H2_RE = re.compile(r"^##\s+(.+)$")
_H3_RE = re.compile(r"^###\s+(.+)$")
_UL_RE = re.compile(r"^[\-\*\+]\s+(.+)$")
_OL_RE = re.compile(r"^(\d+)\.\s+(.+)$")
_BLOCKQUOTE_RE = re.compile(r"^>\s?(.+)$")


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
        self._shadow_effect = None

        # Plain text widget — fills entire window, read-only to user
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
            state=tk.DISABLED,
        )
        self._text_widget.pack(fill=tk.BOTH, expand=True)

        # --- Tag configurations for markdown styles ---
        self._text_widget.tag_configure(
            "h1", font=(font_family, int(font_size * 1.5), "bold"),
            spacing1=8, spacing3=4,
        )
        self._text_widget.tag_configure(
            "h2", font=(font_family, int(font_size * 1.3), "bold"),
            spacing1=6, spacing3=3,
        )
        self._text_widget.tag_configure(
            "h3", font=(font_family, int(font_size * 1.1), "bold"),
            spacing1=4, spacing3=2,
        )
        self._text_widget.tag_configure(
            "bold", font=(font_family, font_size, "bold"),
        )
        self._text_widget.tag_configure(
            "italic", font=(font_family, font_size, "italic"),
        )
        self._text_widget.tag_configure(
            "code", font=("Consolas", font_size - 1),
            background="#2d2d2d", foreground=font_color,
        )
        self._text_widget.tag_configure(
            "code_block", font=("Consolas", font_size - 1),
            background="#2d2d2d", foreground=font_color,
            lmargin1=4, lmargin2=4, rmargin=4,
            spacing1=2, spacing2=2,
        )
        self._text_widget.tag_configure(
            "blockquote", font=(font_family, font_size, "italic"),
            foreground="#aaaaaa", lmargin1=16, lmargin2=16,
        )
        self._text_widget.tag_configure(
            "ul_bullet", font=(font_family, font_size),
            lmargin1=16, lmargin2=16,
        )
        self._text_widget.tag_configure(
            "ol_bullet", font=(font_family, font_size),
            lmargin1=16, lmargin2=16,
        )
        self._text_widget.tag_configure(
            "hr", font=(font_family, font_size),
            foreground="#555555",
        )

        # Buffer for streaming text (backward compat)
        self._text_blocks: list[str] = [""]

        # Debounce timer for markdown rendering
        self._render_timer: str | None = None

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
        """Show the overlay window."""
        self._visible = True
        self._window.wm_attributes("-alpha", 0.82)
        self._root.update_idletasks()

    def hide(self) -> None:
        """Hide the overlay window."""
        self._visible = False
        self._window.wm_attributes("-alpha", 0.0)
        self._root.update_idletasks()

    def isVisible(self) -> bool:  # noqa: N802
        """Return whether the overlay window is currently visible."""
        return self._visible

    def toggle_visibility(self) -> None:
        """Toggle the overlay window between visible and hidden."""
        if self.isVisible():
            self.hide()
        else:
            self.show()

    def close(self) -> None:
        """Destroy the overlay window."""
        if self._render_timer is not None:
            self._root.after_cancel(self._render_timer)
            self._render_timer = None
        self._window.destroy()

    # -----------------------------------------------------------------------
    # Text content
    # -----------------------------------------------------------------------

    def append_text(self, text: str) -> None:
        """Append text with immediate display and debounced markdown re-render.

        The raw text chunk is inserted into the widget *immediately* so
        the user sees real-time streaming output.  A 150 ms debounce
        then re-renders the full content with markdown formatting once
        the stream pauses.
        """
        if not self._text_blocks:
            self._text_blocks = [""]
        self._text_blocks[-1] += text

        # Immediate raw-text insert for real-time feedback
        self._text_widget.config(state=tk.NORMAL)
        self._text_widget.insert(tk.END, text)
        self._text_widget.see(tk.END)
        self._text_widget.config(state=tk.DISABLED)

        # Schedule debounced markdown re-render
        self._schedule_render()
        self.text_added.emit(text)

    def add_separator(self) -> None:
        """Start a new text block with an immediate separator line."""
        self._text_blocks.append("")

        # Immediate separator line
        self._text_widget.config(state=tk.NORMAL)
        self._text_widget.insert(tk.END, "\n" + "─" * 40 + "\n\n")
        self._text_widget.see(tk.END)
        self._text_widget.config(state=tk.DISABLED)

        self._schedule_render()

    def clear(self) -> None:
        """Clear all text blocks and reset the widget."""
        if self._render_timer is not None:
            self._root.after_cancel(self._render_timer)
            self._render_timer = None
        self._text_blocks.clear()

        self._text_widget.config(state=tk.NORMAL)
        self._text_widget.delete("1.0", tk.END)
        self._text_widget.config(state=tk.DISABLED)

    # -----------------------------------------------------------------------
    # Markdown rendering
    # -----------------------------------------------------------------------

    def _schedule_render(self) -> None:
        """Debounce rendering (150 ms) to coalesce rapid streaming updates."""
        if self._render_timer is not None:
            self._root.after_cancel(self._render_timer)
        self._render_timer = self._root.after(150, self._render)

    def _render(self) -> None:
        """Render all text blocks as markdown into the tk.Text widget."""
        self._render_timer = None

        widget = self._text_widget
        widget.config(state=tk.NORMAL)
        widget.delete("1.0", tk.END)

        in_code_block = False
        needs_newline = False

        for block_idx, block in enumerate(self._text_blocks):
            if not block:
                continue

            # Separator between conversation rounds
            if block_idx > 0:
                widget.insert(tk.END, "\n───\n\n", ())

            lines = block.split("\n")

            for line in lines:
                stripped = line.rstrip()

                # --- Code block toggle ---
                if stripped.startswith("```"):
                    if needs_newline:
                        widget.insert(tk.END, "\n", ())
                        needs_newline = False
                    if in_code_block:
                        widget.insert(tk.END, "\n", ())
                        in_code_block = False
                    else:
                        in_code_block = True
                    continue

                # --- Code block content ---
                if in_code_block:
                    if needs_newline:
                        widget.insert(tk.END, "\n", ())
                    widget.insert(tk.END, stripped + "\n", "code_block")
                    needs_newline = False
                    continue

                # --- Horizontal rule ---
                if stripped in ("---", "***", "___"):
                    if needs_newline:
                        widget.insert(tk.END, "\n", ())
                    widget.insert(tk.END, "─" * 40 + "\n\n", "hr")
                    needs_newline = False
                    continue

                # --- Headings ---
                m = _H3_RE.match(stripped)
                if m:
                    if needs_newline:
                        widget.insert(tk.END, "\n", ())
                    widget.insert(tk.END, m.group(1) + "\n", "h3")
                    needs_newline = False
                    continue
                m = _H2_RE.match(stripped)
                if m:
                    if needs_newline:
                        widget.insert(tk.END, "\n", ())
                    widget.insert(tk.END, m.group(1) + "\n", "h2")
                    needs_newline = False
                    continue
                m = _H1_RE.match(stripped)
                if m:
                    if needs_newline:
                        widget.insert(tk.END, "\n", ())
                    widget.insert(tk.END, m.group(1) + "\n", "h1")
                    needs_newline = False
                    continue

                # --- Unordered list ---
                m = _UL_RE.match(stripped)
                if m:
                    if needs_newline:
                        widget.insert(tk.END, "\n", ())
                    widget.insert(tk.END, "  \u2022 ", "ul_bullet")
                    self._insert_inline(widget, m.group(1))
                    widget.insert(tk.END, "\n", "ul_bullet")
                    needs_newline = False
                    continue

                # --- Ordered list ---
                m = _OL_RE.match(stripped)
                if m:
                    if needs_newline:
                        widget.insert(tk.END, "\n", ())
                    widget.insert(tk.END, f"  {m.group(1)}. ", "ol_bullet")
                    self._insert_inline(widget, m.group(2))
                    widget.insert(tk.END, "\n", "ol_bullet")
                    needs_newline = False
                    continue

                # --- Blockquote ---
                m = _BLOCKQUOTE_RE.match(stripped)
                if m:
                    if needs_newline:
                        widget.insert(tk.END, "\n", ())
                    self._insert_inline(widget, m.group(1), base_tag="blockquote")
                    widget.insert(tk.END, "\n", "blockquote")
                    needs_newline = False
                    continue

                # --- Plain text with inline formatting ---
                if needs_newline:
                    widget.insert(tk.END, "\n", ())
                self._insert_inline(widget, stripped)
                widget.insert(tk.END, "\n", ())
                needs_newline = False

        # Auto-scroll to bottom
        widget.see(tk.END)
        widget.config(state=tk.DISABLED)

    @staticmethod
    def _insert_inline(
        widget: tk.Text,
        text: str,
        base_tag: str | None = None,
    ) -> None:
        """Insert *text* with inline markdown formatting applied.

        Uses :func:`_parse_inline` to split *text* into formatted segments
        and inserts each with the appropriate tk.Text tags.  If *base_tag*
        is provided, it is merged with the inline tags.
        """
        segments = _parse_inline(text)
        for segment_text, inline_tags in segments:
            if not segment_text:
                continue
            tags = (base_tag,) + inline_tags if base_tag else inline_tags or ()
            widget.insert(tk.END, segment_text, tags)

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
