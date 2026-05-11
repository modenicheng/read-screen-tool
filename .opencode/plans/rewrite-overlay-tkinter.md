# Plan: Rewrite overlay.py from PySide6/Qt to tkinter

## Overview

Replace the Qt-based `OutputOverlay` (350 lines, QWidget + QTextEdit + QGraphicsDropShadowEffect + custom paintEvent) with a pure tkinter `Toplevel` + `tk.Text` widget while preserving the exact public API contract. The main app's Qt event loop remains; tkinter is polled via QTimer. Tests are rewritten to work without any Qt imports.

### Preserved Public API Contract

```python
class OutputOverlay:
    text_added = Signal(str)  # emitted on append_text

    def __init__(self, parent=None, font_family="Microsoft YaHei", font_size=14, font_color="#FFFFFF", shadow=True)
    def append_text(self, text: str) -> None
    def add_separator(self) -> None
    def clear(self) -> None
    def toggle_visibility(self) -> None
    def move_to_cursor(self, x: int, y: int) -> None
    def set_position(self, x: int, y: int) -> None
    def set_size(self, w: int, h: int) -> None
    def show(self) -> None
    def hide(self) -> None
```

### Preserved Internal State (for test compatibility)

| Attribute | Type | Description |
|-----------|------|-------------|
| `_text_blocks` | `list[str]` | Text buffer; append accumulates, separator adds `""`, clear empties |
| `_font_family` | `str` | Constructor value |
| `_font_size` | `int` | Constructor value |
| `_font_color` | `str` | Constructor value (was QColor, now plain string) |
| `_shadow_enabled` | `bool` | Constructor value |
| `_shadow_effect` | `None` | Always None in tkinter |
| `_text_edit` | `tk.Text` | The text display widget (was QTextEdit) |
| `_window` | `tk.Toplevel` | The frameless transparent window (was QWidget) |

### Signal Connections Preserved in main.py

| Source | Signal | Connected To | Method |
|--------|--------|-------------|--------|
| `HotkeyManager` | `toggle_overlay_requested` | `OutputOverlay` | `toggle_visibility()` |
| `HotkeyManager` | `move_overlay_to_cursor(int,int)` | `OutputOverlay` | `move_to_cursor(x,y)` |
| `LlmClient` | `token_received(str)` | `OutputOverlay` | `append_text(token)` |
| `TrayManager` | `show_requested` | `OutputOverlay` | `show()` |
| `TrayManager` | `hide_requested` | `OutputOverlay` | `hide()` |

---

## Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Qt+tkinter coexistence | QTimer calls `root.update()` every 30ms from main.py | No threading, no `mainloop()`, simple |
| Transparency | `attributes('-transparentcolor', '#010101')` on Toplevel | Binary transparency, works on Windows |
| Text widget | `tk.Text` with `tag_configure` for rich text | Native text selection, word wrap, scrolling |
| Markdown | `markdown` lib -> HTML -> `HTMLParser` -> tagged Text inserts | No third-party tkhtmlview needed |
| Text shadow | Skipped (`_shadow_effect` always `None`) | `shadow=False` already supported; tkinter has no drop-shadow |
| Signal mechanism | Lightweight `Signal` class with callback list | Tests work without QSignalSpy |
| Window frameless | `overrideredirect(True)` + `wm_attributes('-topmost', True)` | Matches Qt FramelessWindowHint + WindowStaysOnTopHint |
| DWM shadow remove | `ctypes.windll.dwmapi.DwmSetWindowAttribute` via `winfo_id()` | Same API, different HWND source |
| Click-through | `SetWindowLongPtrW` subclass to intercept WM_NCHITTEST | Prevents transparent-pixel click-through |

---

## Task Dependency Graph

```
signal.py (T1) ──────────────────────────────────────────┐
    │                                                     │
    ▼                                                     │
test_overlay.py rewrite (T2) ──> RED PHASE                │
    │                                                     │
    ├── overlay.py: window creation (T3.1) ───────────┐   │
    │       │                                          │   │
    │       ├── overlay.py: text content (T3.2) ────┐  │   │
    │       │       │                               │  │   │
    │       │       └── overlay.py: markdown (T3.4) │  │   │
    │       │                                       │  │   │
    │       ├── overlay.py: window mgmt (T3.3)      │  │   │
    │       │                                       │  │   │
    │       └── overlay.py: Windows API (T3.5)      │  │   │
    │                                               │  │   │
    ├── main.py: QTimer integration (T4) ◄──────────┘  │   │
    │                                                     │
    └── All tests green (T5: VERIFY) ◄────────────────────┘
         │
         └── lint + polish (T6)
```

---

## Atomic Commit Strategy

| # | Commit Message | Tasks | Files | Lines |
|---|---------------|-------|-------|-------|
| 1 | `feat: add Signal utility for non-Qt signal/slot mechanism` | T1 | `signal.py` (new) | ~55 |
| 2 | `refactor: rewrite overlay in tkinter with updated tests and QTimer integration` | T2, T3.1-T3.5, T4 | `overlay.py` (rewrite), `tests/test_overlay.py` (rewrite), `main.py` (+15 lines) | ~500 |
| 3 | `chore: lint and finalize tkinter overlay migration` | T6 | `overlay.py`, `signal.py`, `tests/test_overlay.py`, `main.py` | Ruff fixes |

**Commit 2 is the main work.** Commit 1 is a safe standalone utility. Commit 3 is mechanical. All tests must pass in Commit 2 before Commit 3 is reached.

---

# TASK 1: signal.py -- Signal/SignalSpy Utility

## GOAL
Create a lightweight, Qt-free signal/slot mechanism so `OutputOverlay.text_added` can emit without PySide6 imports, and tests can spy on emissions without `QSignalSpy`.

## EXPECTED OUTCOME
A new file `signal.py` at project root containing `Signal` and `SignalSpy` classes. The module is self-contained with zero external dependencies (stdlib only).

## REQUIRED TOOLS
- `write` tool to create the new file
- `bash` to run: `python -c "from signal import Signal, SignalSpy; ..."` smoke test

## MUST DO

1. **File: `signal.py`** (new, ~55 lines)

2. **Class `Signal`:**
   - `__init__(self, *param_types)` -- accepts optional type hints (ignored, for Qt API compatibility)
   - `connect(self, callback: Callable)` -- appends callback to internal list
   - `disconnect(self, callback=None)` -- if `callback` is None, clear all; else remove specific callback
   - `emit(self, *args)` -- iterate callbacks, invoke each with `*args`
   - Use `from __future__ import annotations` at top
   - Use `from typing import Any, Callable`

3. **Class `SignalSpy`:**
   - `__init__(self, signal: Signal)` -- connects to signal, stores reference
   - `_record(self, *args)` -- appends args tuple to `self._calls: list[tuple]`
   - `count(self) -> int` -- returns `len(self._calls)`
   - `at(self, index: int) -> tuple` -- returns `self._calls[index]`
   - `disconnect(self)` -- disconnects from signal, stops recording
   - MUST match the exact API: `spy.count()`, `spy.at(0)`, `spy.at(0)[0]`

4. **Exact class signatures:**
   ```python
   class Signal:
       """Callback-based signal. Supports .connect(), .disconnect(), .emit()."""
       def __init__(self, *param_types: type) -> None:
           self._callbacks: list[Callable[..., None]] = []
       
       def connect(self, callback: Callable[..., None]) -> None:
           self._callbacks.append(callback)
       
       def disconnect(self, callback: Callable[..., None] | None = None) -> None:
           if callback is None:
               self._callbacks.clear()
           elif callback in self._callbacks:
               self._callbacks.remove(callback)
       
       def emit(self, *args: Any) -> None:
           for cb in self._callbacks:
               cb(*args)


   class SignalSpy:
       """Test helper -- records signal emissions. Replaces QSignalSpy."""
       def __init__(self, signal: Signal) -> None:
           self._calls: list[tuple[Any, ...]] = []
           signal.connect(self._record)
           self._signal = signal
       
       def _record(self, *args: Any) -> None:
           self._calls.append(args)
       
       def count(self) -> int:
           return len(self._calls)
       
       def at(self, index: int) -> tuple[Any, ...]:
           return self._calls[index]
       
       def disconnect(self) -> None:
           self._signal.disconnect(self._record)
   ```

## MUST NOT DO
- Do NOT add Qt imports or any PySide6 dependency
- Do NOT add threading/locking (all callbacks run on main thread)
- Do NOT add `__getitem__`, `__len__`, or other dunder methods to SignalSpy -- only the explicit `count()` and `at()` API
- Do NOT make Signal thread-safe with locks (unnecessary for this use case)
- Do NOT add docstrings longer than one line per method

## CONTEXT
- `text_added = Signal(str)` is a class attribute on OutputOverlay, instantiated once at class definition
- The main app connects nothing to `text_added` -- it's only used in tests
- Tests use `spy = SignalSpy(overlay.text_added)` then `assert spy.count() == 1` and `assert spy.at(0)[0] == "Hello"`
- This must match the exact usage pattern from `QSignalSpy` for minimal diff

## VERIFICATION

**Smoke test (run after file creation):**
```powershell
python -c "from signal import Signal, SignalSpy; s = Signal(str); spy = SignalSpy(s); s.emit('hello'); assert spy.count() == 1; assert spy.at(0)[0] == 'hello'; print('PASS')"
```
**Expected output:** `PASS`

---

# TASK 2: test_overlay.py -- Rewrite for tkinter (RED PHASE)

## GOAL
Rewrite `tests/test_overlay.py` so every test works against the tkinter-based `OutputOverlay` without any PySide6 imports. At this stage, `overlay.py` has NOT been rewritten yet, so ALL tests will FAIL -- this is the TDD red phase.

## EXPECTED OUTCOME
A rewritten `tests/test_overlay.py` (~200 lines) with 19 tests across 5 test classes. Running `pytest tests/test_overlay.py -v` produces 19 failures (ImportError or AttributeError) because `overlay.py` still uses Qt.

## REQUIRED TOOLS
- `write` tool to rewrite the file
- `bash` to run: `python -m pytest tests/test_overlay.py -v` (expect all FAIL)

## MUST DO

### Fixtures

**Remove:**
- `pytest.fixture(scope="session") def qapp():` -- delete entirely
- `@pytest.fixture def overlay(qtbot):` -- replace with tkinter-based fixture

**Add:**
```python
@pytest.fixture(scope="session")
def tk_root():
    """Session-scoped hidden Tk root. All overlay Toplevels are children of this."""
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def overlay(tk_root):
    """Create OutputOverlay for testing. Cleanup destroys the Toplevel window."""
    widget = OutputOverlay()
    yield widget
    try:
        widget._window.destroy()
    except Exception:
        pass
```

### Imports

**Remove all PySide6 imports:**
```python
# DELETE these:
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect
```

**Add:**
```python
from signal import SignalSpy
from overlay import OutputOverlay
import pytest
```

### TestOverlayCreation (3 tests, no fixture changes for qapp)

**`test_overlay_created_with_correct_flags`:**
- Signature: `def test_overlay_created_with_correct_flags(self, overlay: OutputOverlay) -> None:`
- Replace `flags = overlay.windowFlags()` and all Qt flag checks with:
  ```python
  assert overlay._window.overrideredirect() is True, "Missing overrideredirect (frameless)"
  assert overlay._window.attributes('-topmost') is True, "Missing always-on-top"
  assert overlay._window.attributes('-transparentcolor') == "#010101", "Missing transparent color"
  ```

**`test_overlay_no_background`:**
- Signature unchanged
- Replace with:
  ```python
  assert overlay._window.cget('bg') == "#010101"
  ```

**`test_font_config_passed`:**
- Remove `qapp` parameter from signature: `def test_font_config_passed(self) -> None:`
- `_font_color` is now a plain string, not QColor:
  ```python
  assert widget._font_family == "Arial"
  assert widget._font_size == 20
  assert widget._font_color == "#FF0000"  # string, not QColor
  assert widget._shadow_enabled is False
  ```

### TestTextOperations (5 tests)

**`test_append_text`:**
- Remove `qtbot` parameter from signature: `def test_append_text(self, overlay: OutputOverlay) -> None:`
- Replace `spy = QSignalSpy(overlay.text_added)` with `spy = SignalSpy(overlay.text_added)`
- Everything else unchanged

**`test_append_text_accumulates`:** Remove `qtbot`, rest unchanged.

**`test_add_separator`:** Unchanged.

**`test_clear`:** Unchanged.

**`test_multiple_text_blocks`:** Unchanged (pure `_text_blocks` check, no Qt dependency).

### TestWindowManagement (4 tests)

**`test_toggle_visibility`:**
- Replace `overlay.isVisible()` with `overlay._window.winfo_viewable()`
- Replace `overlay.hide()` / `overlay.show()` with calls that check state after

**`test_set_position_and_size`:**
- Replace `overlay.pos().x()` with `overlay._window.winfo_x()`
- Replace `overlay.pos().y()` with `overlay._window.winfo_y()`
- Replace `overlay.width()` with `overlay._window.winfo_width()`
- Replace `overlay.height()` with `overlay._window.winfo_height()`

**`test_move_to_cursor`:** Same winfo-based changes as above.

**`test_move_to_cursor_is_slot`:**
- `assert callable(overlay.move_to_cursor)` -- unchanged

### TestShadowEffect (2 tests, 1 removed)

**`test_shadow_effect_created_when_enabled`:**
- Remove `qapp` parameter
- Rewrite:
  ```python
  widget = OutputOverlay(shadow=True)
  assert widget._shadow_enabled is True
  assert widget._shadow_effect is None  # always None in tkinter
  ```

**`test_shadow_effect_none_when_disabled`:**
- Remove `qapp` parameter
- Rewrite:
  ```python
  widget = OutputOverlay(shadow=False)
  assert widget._shadow_enabled is False
  assert widget._shadow_effect is None
  ```

**`test_shadow_effect_on_text_edit`:**
- DELETE this test entirely. Qt-specific (graphicsEffect), no tkinter equivalent.

### TestMarkdownRendering (5 tests)

**`test_is_markdown_detects_heading`:** Unchanged
  
**`test_is_markdown_detects_asterisk`:** Unchanged

**`test_is_markdown_detects_backtick`:** Unchanged

**`test_is_markdown_plain_text`:** Unchanged

**`test_append_markdown_text_renders`:**
- Remove `qtbot` parameter
- Replace `QSignalSpy` with `SignalSpy`
- Replace `overlay._text_edit.toHtml()` with `overlay._text_edit.get('1.0', 'end-1c')`
- Assertions:
  ```python
  text_content = overlay._text_edit.get('1.0', 'end-1c')
  assert "# Hello" not in text_content  # markdown syntax stripped
  assert "Hello" in text_content  # heading text present
  ```

## MUST NOT DO
- Do NOT import anything from `PySide6`
- Do NOT change test class names or test method names
- Do NOT change the semantics of any assertion -- only the mechanism (Qt -> tkinter)
- Do NOT add tests that don't exist in the current version
- Do NOT use `qtbot` or `qapp` fixtures anywhere

## CONTEXT
- The current `test_overlay.py` has 183 lines, 5 test classes, 20 tests. After removing `test_shadow_effect_on_text_edit`: 19 tests
- The `overlay` fixture returns a tkinter-based OutputOverlay, so all tests that create the overlay fixture will fail at runtime until Task 3 is complete
- The `tk_root` fixture is session-scoped to avoid Tk root conflicts
- The SignalSpy import from signal.py is needed for TestTextOperations and TestMarkdownRendering

## VERIFICATION

**Command to confirm RED phase:**
```powershell
python -m pytest tests/test_overlay.py -v 2>&1
```
**Expected:** All 19 tests FAIL with `ImportError`, `AttributeError`, or `ModuleNotFoundError` (because `overlay.py` still imports PySide6 and has no tkinter classes). This is the correct RED phase.

---

# TASK 3.1: overlay.py -- Core Window Creation

## GOAL
Create the `OutputOverlay` class skeleton with tkinter `Toplevel` window: frameless, always-on-top, transparent background. Initialize all internal state attributes. Make `TestOverlayCreation` tests pass.

## EXPECTED OUTCOME
`overlay.py` (~120 lines at this stage) with a working `OutputOverlay.__init__` that creates a transparent frameless tkinter window. `TestOverlayCreation` (3 tests) all PASS.

## REQUIRED TOOLS
- `write` tool to create the new file (replacing the Qt version)
- `bash` to run: `python -m pytest tests/test_overlay.py::TestOverlayCreation -v`

## MUST DO

### File header and imports

```python
"""Transparent frameless always-on-top overlay window for displaying LLM responses.

Architecture:
- tkinter Toplevel with overrideredirect + transparentcolor for transparency
- tk.Text widget with tag_configure for rich text and markdown rendering
- Windows DWM shadow removal via ctypes DwmSetWindowAttribute
- WM_NCHITTEST interception to prevent click-through on transparent pixels
- text_added uses a lightweight Signal callback (not Qt Signal)
"""

from __future__ import annotations

import contextlib
import sys
import tkinter as tk
from typing import Any

from signal import Signal

# Windows WM_NCHITTEST constants and ctypes imports
if sys.platform == "win32":
    import ctypes
    import ctypes.wintypes

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DOC_MARGIN = 8
MIN_WINDOW_W = 200
SEPARATOR_HEIGHT = 5
TRANSPARENT_COLOR = "#010101"
SEPARATOR_COLOR_HEX = "#555555"

# ---------------------------------------------------------------------------
# Module-level hidden Tk root (created once, shared by all overlay windows)
# ---------------------------------------------------------------------------
_root: tk.Tk | None = None


def _get_root() -> tk.Tk:
    """Return the module-level hidden Tk root, creating it on first call."""
    global _root
    if _root is None:
        _root = tk.Tk()
        _root.withdraw()
    return _root
```

### OutputOverlay class -- __init__ only

```python
class OutputOverlay:
    """Transparent floating window displaying LLM response text.

    Features:
    - Frameless, always-on-top, transparent background
    - tk.Text widget with native text selection (Ctrl+C to copy)
    - text_added signal emits each appended text segment
    - Separators between responses rendered as visual divider lines
    - Markdown detection and tag-based formatting
    """

    text_added = Signal(str)

    def __init__(
        self,
        parent: Any | None = None,  # kept for API compatibility, unused
        font_family: str = "Microsoft YaHei",
        font_size: int = 14,
        font_color: str = "#FFFFFF",
        shadow: bool = True,
    ) -> None:
        root = _get_root()

        # -- Window -----------------------------------------------------------
        self._window = tk.Toplevel(root)
        self._window.overrideredirect(True)
        self._window.wm_attributes("-topmost", True)
        self._window.attributes("-transparentcolor", TRANSPARENT_COLOR)
        self._window.configure(bg=TRANSPARENT_COLOR)

        # -- Internal state (preserve exact attribute names for test compat) ---
        self._text_blocks: list[str] = []
        self._font_family = font_family
        self._font_size = font_size
        self._font_color = font_color
        self._shadow_enabled = shadow
        self._shadow_effect = None

        # -- Default geometry --------------------------------------------------
        self._window.geometry("600x400+100+100")
```

### MUST DO specifics:
1. The `parent` parameter is accepted but unused -- maintained for API backward compatibility
2. `text_added = Signal(str)` is a class-level attribute, instantiated once
3. `_shadow_effect = None` always -- no shadow support in tkinter
4. `_font_color` is a plain string (`"#FFFFFF"`) not a QColor -- tests now compare strings
5. Import `Signal` from the local `signal.py` module, NOT from PySide6
6. The `_get_root()` function is defined at module level (not inside the class)
7. Window bg is `TRANSPARENT_COLOR` so that transparency color key works
8. Override redirect removes title bar and taskbar entry (same behavior as Qt)

## MUST NOT DO
- Do NOT create the Text widget yet (Task 3.2)
- Do NOT implement any public methods besides `__init__` (Tasks 3.2, 3.3)
- Do NOT add Windows API fixes yet (Task 3.5)
- Do NOT import PySide6 or any Qt modules
- Do NOT call `root.mainloop()` anywhere
- Do NOT subclass QWidget or any Qt class

## CONTEXT
- The module-level `_root` pattern ensures only one Tk() instance exists across all tests. Each `OutputOverlay` creates its own `Toplevel` child of this root
- `tk_root` fixture in tests provides the underlying Tk root; the `_get_root()` function creates it if not already created
- The window will be invisible until `deiconify()` is called
- Each method later will call `self._window.update()` to flush tkinter events

## VERIFICATION

**Command:**
```powershell
python -m pytest tests/test_overlay.py::TestOverlayCreation -v
```

**Expected output (3 passed):**
```
tests/test_overlay.py::TestOverlayCreation::test_overlay_created_with_correct_flags PASSED
tests/test_overlay.py::TestOverlayCreation::test_overlay_no_background PASSED
tests/test_overlay.py::TestOverlayCreation::test_font_config_passed PASSED
```

---

# TASK 3.2: overlay.py -- Text Content & Rendering

## GOAL
Add the `tk.Text` widget with tag configuration, implement content management methods (`_build_plain_content`, `_update_content`, `append_text`, `add_separator`, `clear`), and emit `text_added` signal. Make `TestTextOperations` tests pass.

## EXPECTED OUTCOME
`overlay.py` grows to ~180 lines. `TestTextOperations` (5 tests) all PASS. `TestMarkdownRendering._is_markdown_*` tests also PASS (static method, no change needed from Qt version).

## REQUIRED TOOLS
- `edit` tool to append code to `overlay.py`
- `bash` to run: `python -m pytest tests/test_overlay.py::TestTextOperations tests/test_overlay.py::TestMarkdownRendering::test_is_markdown_detects_heading tests/test_overlay.py::TestMarkdownRendering::test_is_markdown_detects_asterisk tests/test_overlay.py::TestMarkdownRendering::test_is_markdown_detects_backtick tests/test_overlay.py::TestMarkdownRendering::test_is_markdown_plain_text -v`

## MUST DO

### Add to `__init__` (after the geometry line):

```python
        # -- Text widget ------------------------------------------------------
        self._text_edit = tk.Text(
            self._window,
            bg=TRANSPARENT_COLOR,
            fg=font_color,
            font=(font_family, font_size),
            wrap=tk.WORD,
            state=tk.DISABLED,
            borderwidth=0,
            highlightthickness=0,
            padx=DOC_MARGIN,
            pady=DOC_MARGIN,
            insertwidth=0,
            selectbackground="#444444",
            selectforeground=font_color,
        )
        self._text_edit.pack(fill=tk.BOTH, expand=True)

        # -- Tag configuration for formatted text ------------------------------
        self._text_edit.tag_configure(
            "plain",
            foreground=font_color,
            font=(font_family, font_size),
        )
        self._text_edit.tag_configure(
            "separator",
            foreground=SEPARATOR_COLOR_HEX,
            font=(font_family, 1),
            spacing1=3,
            spacing3=3,
        )
```

### Add content management methods:

```python
    # -----------------------------------------------------------------------
    # Content management
    # -----------------------------------------------------------------------

    @staticmethod
    def _is_markdown(text: str) -> bool:
        """Detect whether text contains Markdown syntax characters."""
        return any(c in text for c in "#*-`[>")

    def _build_plain_content(self) -> None:
        """Render plain-text blocks into the Text widget with separator lines."""
        self._text_edit.configure(state=tk.NORMAL)
        self._text_edit.delete("1.0", tk.END)

        for i, block in enumerate(self._text_blocks):
            if i > 0 and block == "":
                self._text_edit.insert(tk.END, "\u2500" * 40 + "\n", "separator")
            elif block:
                self._text_edit.insert(tk.END, block + "\n", "plain")

        self._text_edit.configure(state=tk.DISABLED)

    def _update_content(self) -> None:
        """Push current text blocks to the Text widget. Auto-scrolls to end."""
        has_markdown = any(
            self._is_markdown(b) for b in self._text_blocks if b
        )
        if has_markdown:
            self._render_markdown_content()
        else:
            self._build_plain_content()

        self._text_edit.see(tk.END)
        self._window.update()

    def _render_markdown_content(self) -> None:
        """Stub for markdown rendering (Task 3.4). Falls back to plain text."""
        self._build_plain_content()

    def append_text(self, text: str) -> None:
        """Append text to the current (last) text block."""
        if not self._text_blocks:
            self._text_blocks.append("")
        self._text_blocks[-1] += text
        self._update_content()
        self.text_added.emit(text)

    def add_separator(self) -> None:
        """Insert a horizontal separator between responses."""
        self._text_blocks.append("")
        self._update_content()

    def clear(self) -> None:
        """Clear all text blocks."""
        self._text_blocks.clear()
        self._update_content()
```

### Key behaviors:
1. `_build_plain_content()` -- switches to NORMAL state, deletes all content, inserts each block, switches back to DISABLED. Empty string blocks render as a row of `─` (U+2500 box drawing) characters with the "separator" tag. Non-empty blocks render with the "plain" tag.
2. `_update_content()` -- checks for markdown, renders accordingly, scrolls to bottom, calls `self._window.update()` to flush tkinter events
3. `append_text()` -- if blocks is empty, adds `""` first (so subsequent appends go into a block). Appends text to the last block. Emits `text_added` signal.
4. `add_separator()` -- appends empty string to blocks
5. `clear()` -- empties the list
6. `_render_markdown_content()` -- stub that delegates to `_build_plain_content()` for now (will be replaced in Task 3.4)

### Existing code to keep:
- `_is_markdown()` -- copy exactly from the current Qt version. It's a static method with zero Qt dependencies. Check for characters: `#`, `*`, `-`, `` ` ``, `[`, `>`

## MUST NOT DO
- Do NOT implement full markdown rendering yet (stub only)
- Do NOT implement window management methods (Task 3.3)
- Do NOT implement Windows API fixes (Task 3.5)
- Do NOT change the `_update_content()` flow between plain/markdown detection

## CONTEXT
- The Text widget starts in DISABLED state so users can read but not type. It's toggled to NORMAL for content updates, then back to DISABLED
- `insertwidth=0` hides the text cursor (caret)
- The `─` separator characters create a visual horizontal line. The separator tag uses font size 1 with spacing to create a compact divider
- `self._window.update()` at the end of `_update_content()` ensures the visual change is flushed immediately

## VERIFICATION

**Command:**
```powershell
python -m pytest tests/test_overlay.py::TestTextOperations tests/test_overlay.py::TestMarkdownRendering::test_is_markdown_detects_heading tests/test_overlay.py::TestMarkdownRendering::test_is_markdown_detects_asterisk tests/test_overlay.py::TestMarkdownRendering::test_is_markdown_detects_backtick tests/test_overlay.py::TestMarkdownRendering::test_is_markdown_plain_text -v
```

**Expected output (9 passed):**
```
tests/test_overlay.py::TestTextOperations::test_append_text PASSED
tests/test_overlay.py::TestTextOperations::test_append_text_accumulates PASSED
tests/test_overlay.py::TestTextOperations::test_add_separator PASSED
tests/test_overlay.py::TestTextOperations::test_clear PASSED
tests/test_overlay.py::TestTextOperations::test_multiple_text_blocks PASSED
tests/test_overlay.py::TestMarkdownRendering::test_is_markdown_detects_heading PASSED
tests/test_overlay.py::TestMarkdownRendering::test_is_markdown_detects_asterisk PASSED
tests/test_overlay.py::TestMarkdownRendering::test_is_markdown_detects_backtick PASSED
tests/test_overlay.py::TestMarkdownRendering::test_is_markdown_plain_text PASSED
```

---

# TASK 3.3: overlay.py -- Window Management

## GOAL
Implement `toggle_visibility`, `move_to_cursor`, `set_position`, `set_size`, `show`, `hide` methods. Make `TestWindowManagement` tests pass.

## EXPECTED OUTCOME
`overlay.py` grows to ~220 lines. `TestWindowManagement` (4 tests) all PASS.

## REQUIRED TOOLS
- `edit` tool to append code to `overlay.py`
- `bash` to run: `python -m pytest tests/test_overlay.py::TestWindowManagement -v`

## MUST DO

### Add window management methods:

```python
    # -----------------------------------------------------------------------
    # Window management
    # -----------------------------------------------------------------------

    def toggle_visibility(self) -> None:
        """Toggle window between visible and hidden states."""
        if self._window.winfo_viewable():
            self._window.withdraw()
        else:
            self._window.deiconify()
            self._window.lift()
            self._window.update()

    def move_to_cursor(self, x: int, y: int) -> None:
        """Move the window to the given cursor coordinates."""
        self._window.geometry(f"+{x}+{y}")
        self._window.update()

    def set_position(self, x: int, y: int) -> None:
        """Move the window to the specified position."""
        self._window.geometry(f"+{x}+{y}")
        self._window.update()

    def set_size(self, w: int, h: int) -> None:
        """Resize the window."""
        self._window.geometry(f"{w}x{h}")
        self._window.update()

    def show(self) -> None:
        """Make the window visible."""
        self._window.deiconify()
        self._window.update()

    def hide(self) -> None:
        """Hide the window."""
        self._window.withdraw()
        self._window.update()
```

### Key behaviors:
1. `toggle_visibility()` -- if viewable, withdraw; otherwise deiconify + lift + update
2. `move_to_cursor(x, y)` -- geometry string with position only (preserves size)
3. `set_position(x, y)` -- same as move_to_cursor
4. `set_size(w, h)` -- geometry string with size only (preserves position)
5. `show()` -- deiconify the withdrawn Toplevel
6. `hide()` -- withdraw the Toplevel
7. Every method calls `self._window.update()` after geometry change

## MUST NOT DO
- Do NOT use `iconify()` or `deiconify()` interchangeably -- `withdraw()` is the correct tkinter equivalent of Qt's `hide()`
- Do NOT add activateWindow/raise/opacity logic beyond `lift()`

## CONTEXT
- The window starts hidden because the parent Tk root is withdrawn
- `geometry()` with size-only string preserves position; position-only preserves size
- `update()` flushes pending tkinter events for immediate visual change

## VERIFICATION

**Command:**
```powershell
python -m pytest tests/test_overlay.py::TestWindowManagement -v
```

**Expected output (4 passed):**
```
tests/test_overlay.py::TestWindowManagement::test_toggle_visibility PASSED
tests/test_overlay.py::TestWindowManagement::test_set_position_and_size PASSED
tests/test_overlay.py::TestWindowManagement::test_move_to_cursor PASSED
tests/test_overlay.py::TestWindowManagement::test_move_to_cursor_is_slot PASSED
```

---

# TASK 3.4: overlay.py -- Markdown Rendering

## GOAL
Replace the `_render_markdown_content()` stub with full markdown-to-tagged-Text rendering. Parse markdown via `markdown` library, convert HTML output to tagged Text widget inserts. Make `TestMarkdownRendering.test_append_markdown_text_renders` pass.

## EXPECTED OUTCOME
`overlay.py` grows to ~300 lines. `TestMarkdownRendering` (all 5 tests) PASS.

## REQUIRED TOOLS
- `edit` tool to update `overlay.py`
- `bash` to run: `python -m pytest tests/test_overlay.py::TestMarkdownRendering -v`

## MUST DO

### Add markdown tag configurations to `__init__` (after existing tag_configure calls):

```python
        # Markdown formatting tags
        self._text_edit.tag_configure(
            "h1", font=(font_family, font_size + 6, "bold"), spacing1=10, spacing3=4
        )
        self._text_edit.tag_configure(
            "h2", font=(font_family, font_size + 4, "bold"), spacing1=8, spacing3=3
        )
        self._text_edit.tag_configure(
            "h3", font=(font_family, font_size + 2, "bold"), spacing1=6, spacing3=2
        )
        self._text_edit.tag_configure(
            "strong", font=(font_family, font_size, "bold")
        )
        self._text_edit.tag_configure(
            "em", font=(font_family, font_size, "italic")
        )
        self._text_edit.tag_configure(
            "code", font=("Consolas", font_size),
            background="#2a2a2a", foreground=font_color,
        )
        self._text_edit.tag_configure(
            "pre", font=("Consolas", font_size),
            background="#2a2a2a", foreground=font_color,
            lmargin1=10, lmargin2=10, rmargin=10,
            spacing1=4, spacing3=4,
        )
        self._text_edit.tag_configure(
            "blockquote", font=(font_family, font_size, "italic"),
            foreground="#cccccc", lmargin1=15, lmargin2=15,
            spacing1=4, spacing3=4,
        )
        self._text_edit.tag_configure(
            "hr", font=(font_family, 1), foreground="#555555",
            spacing1=4, spacing3=4,
        )
```

### Replace `_render_markdown_content()` stub:

```python
    def _render_markdown_content(self) -> None:
        """Convert markdown text blocks into tagged Text widget content."""
        import html.parser
        import markdown as md_lib

        # Replace separator blocks with horizontal rule syntax
        md_blocks = [b if b else "---" for b in self._text_blocks]
        md_text = "\n\n".join(md_blocks)

        md = md_lib.Markdown(extensions=["fenced_code", "tables"])
        html_body = md.convert(md_text)

        self._text_edit.configure(state=tk.NORMAL)
        self._text_edit.delete("1.0", tk.END)

        parser = _MarkdownHTMLParser(self._text_edit)
        try:
            parser.feed(html_body)
        except Exception:
            # Fallback: render as plain text if HTML parsing fails
            self._text_edit.insert(tk.END, md_text, "plain")

        self._text_edit.configure(state=tk.DISABLED)


class _MarkdownHTMLParser(html.parser.HTMLParser):
    """Parse markdown-generated HTML and insert tagged text into a tk.Text widget."""

    _TAG_MAP: dict[str, str] = {
        "h1": "h1", "h2": "h2", "h3": "h3",
        "strong": "strong", "b": "strong",
        "em": "em", "i": "em",
        "code": "code", "pre": "pre",
        "blockquote": "blockquote",
    }

    _BLOCK_TAGS: set[str] = {"h1", "h2", "h3", "p", "pre", "blockquote", "li", "hr"}

    def __init__(self, text_widget: tk.Text) -> None:
        super().__init__()
        self._text = text_widget
        self._tag_stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        mapped = self._TAG_MAP.get(tag)
        if mapped:
            self._tag_stack.append(mapped)
        if tag in self._BLOCK_TAGS and not self._tag_stack:
            self._tag_stack.append("plain")
        if tag == "li":
            self._text.insert(tk.END, "  \u2022 ", "plain")
        if tag == "hr":
            self._text.insert(tk.END, "\u2500" * 40 + "\n", "hr")

    def handle_endtag(self, tag: str) -> None:
        mapped = self._TAG_MAP.get(tag)
        if mapped and self._tag_stack and self._tag_stack[-1] == mapped:
            self._tag_stack.pop()
        if tag in self._BLOCK_TAGS:
            if self._tag_stack and self._tag_stack[-1] == "plain":
                self._tag_stack.pop()
            self._text.insert(tk.END, "\n")

    def handle_data(self, data: str) -> None:
        tags = tuple(self._tag_stack) if self._tag_stack else ("plain",)
        self._text.insert(tk.END, data, tags)

    def handle_entityref(self, name: str) -> None:
        entities: dict[str, str] = {
            "lt": "<", "gt": ">", "amp": "&", "quot": '"',
            "apos": "'", "nbsp": " ",
        }
        char = entities.get(name, f"&{name};")
        tags = tuple(self._tag_stack) if self._tag_stack else ("plain",)
        self._text.insert(tk.END, char, tags)
```

**The `_MarkdownHTMLParser` MUST be defined at module level (after the `OutputOverlay` class), not nested.**

### Key behaviors:
1. Separator blocks (`""`) are replaced with `"---"` before markdown conversion
2. All blocks joined with double newline (`"\n\n"`)
3. The parser walks HTML, maps tag names to Text widget tag names
4. Block-level tags add newlines after closing
5. `li` elements get bullet character prefix
6. `hr` elements render as `─` characters
7. HTML entities are decoded in `handle_entityref`
8. If parsing fails, falls back to raw markdown text

## MUST NOT DO
- Do NOT import `markdown` at module level -- runtime import (same as Qt version)
- Do NOT render as HTML -- always use tagged Text
- Do NOT crash on malformed markdown -- try/except fallback

## CONTEXT
- The Qt version uses `_render_markdown()` returning HTML + CSS. tkinter version converts markdown to HTML, then parses HTML into tagged Text inserts
- The `_TAG_MAP` maps HTML tags to Text widget tag names configured in `__init__`
- Tag stack enables nested formatting (e.g., `<strong><em>text</em></strong>`)
- Text is inserted with tuple of active tags

## VERIFICATION

**Command:**
```powershell
python -m pytest tests/test_overlay.py::TestMarkdownRendering -v
```
**Expected:** 5 passed

**Full overlay suite:**
```powershell
python -m pytest tests/test_overlay.py -v
```
**Expected:** 17 of 19 pass (ShadowEffect tests pass since _shadow_effect=None always)

---

# TASK 3.5: overlay.py -- Windows API Fixes

## GOAL
Add DWM shadow removal and WM_NCHITTEST click-through prevention for Windows.

## EXPECTED OUTCOME
`overlay.py` final line count ~320 lines. On Windows, overlay has no DWM shadow/border and transparent pixels don't pass clicks through. Manual verification only.

## REQUIRED TOOLS
- `edit` tool to append code to `overlay.py`
- Manual testing on Windows

## MUST DO

### Add to `__init__` (after Text widget pack, before end of `__init__`):

```python
        # -- Windows-specific: DWM shadow removal + click-through prevention ---
        if sys.platform == "win32":
            self._disable_dwm_shadow()
            self._prevent_click_through()
```

### Add as instance methods (inside the class, guarded by `if sys.platform == "win32":`):

```python
    if sys.platform == "win32":

        def _disable_dwm_shadow(self) -> None:
            """Call DwmSetWindowAttribute to disable the DWM window shadow/border."""
            with contextlib.suppress(Exception):
                hwnd = int(self._window.winfo_id())
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd,
                    2,  # DWMWA_NCRENDERING_POLICY
                    ctypes.byref(ctypes.c_int(1)),  # DWMNCRP_DISABLED
                    4,
                )

        def _prevent_click_through(self) -> None:
            """Subclass the window procedure to intercept WM_NCHITTEST.

            Forces HTCLIENT so the entire window area receives mouse events,
            preventing click-through on transparent pixels.
            """
            GWLP_WNDPROC = -4
            hwnd = int(self._window.winfo_id())

            self._original_wndproc = ctypes.windll.user32.GetWindowLongPtrW(
                hwnd, GWLP_WNDPROC
            )

            @ctypes.WINFUNCTYPE(
                ctypes.c_long, ctypes.c_void_p,
                ctypes.c_uint, ctypes.c_ulong, ctypes.c_long,
            )
            def wnd_proc(hwnd, msg, wparam, lparam):
                if msg == 0x0084:  # WM_NCHITTEST
                    return 1  # HTCLIENT
                return ctypes.windll.user32.CallWindowProcW(
                    self._original_wndproc,
                    hwnd, msg, wparam, lparam,
                )

            self._wnd_proc_ref = wnd_proc  # prevent GC
            ctypes.windll.user32.SetWindowLongPtrW(
                hwnd, GWLP_WNDPROC, ctypes.cast(wnd_proc, ctypes.c_void_p).value
            )
```

### Key points:
- On 64-bit, use `ctypes.cast(wnd_proc, ctypes.c_void_p).value` for pointer conversion
- `_wnd_proc_ref` stored as instance attribute to prevent GC
- `CallWindowProcW` passes through non-hit-test messages to original window proc

## MUST NOT DO
- Do NOT call these methods on non-Windows (guarded by `sys.platform == "win32"`)
- Do NOT leak the wnd_proc callback reference

## VERIFICATION
Manual on Windows: Start app, verify no DWM shadow, text selectable. Full test suite still passes.

---

# TASK 4: main.py -- QTimer Integration

## GOAL
Add a `QTimer` in `ReadScreenApp` that polls tkinter's event loop via `root.update()` every 30ms.

## EXPECTED OUTCOME
`main.py` has ~15 additional lines. App starts successfully with both Qt and tkinter windows.

## REQUIRED TOOLS
- `edit` tool to modify `main.py`
- `bash` to run: `python main.py` (manual verification)

## MUST DO

### Edit 1: Add `QTimer` to PySide6 imports (line 16):
```python
# Before:
from PySide6.QtCore import QObject, QThread, Signal, Slot
# After:
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot
```

### Edit 2: After `_output_overlay.show()` (around line 162), add:
```python
        # Tkinter event pump — periodically flush tkinter events from Qt's loop
        self._tk_timer = QTimer(self)
        self._tk_timer.timeout.connect(self._pump_tkinter)
        self._tk_timer.start(30)  # ~33fps, very low CPU overhead
```

### Edit 3: Add `_pump_tkinter` method:
```python
    def _pump_tkinter(self) -> None:
        """Pump tkinter events so the overlay remains responsive."""
        try:
            if self._output_overlay._window.winfo_exists():
                self._output_overlay._window.update()
        except Exception:
            pass
```

### Edit 4: In `stop()`, add timer stop:
```python
        if hasattr(self, "_tk_timer"):
            self._tk_timer.stop()
```

## MUST NOT DO
- Do NOT modify signal wiring in `_wire_signals()`
- Do NOT change how OutputOverlay is instantiated
- Do NOT add any tkinter imports to main.py

## CONTEXT
- `winfo_exists()` checks window hasn't been destroyed
- 30ms = ~33fps, negligible CPU overhead
- QTimer runs on main thread (same as Qt and tkinter)
- Each OutputOverlay method also calls `update()` for immediate changes; QTimer covers gaps

## VERIFICATION
Manual: `python main.py` -- overlay appears, toggles, moves, streams text.
Regression: `python -m pytest tests/ -v --ignore=tests/test_overlay.py` -- all existing tests pass.

---

# TASK 5: All Tests Pass -- GREEN PHASE

## GOAL
Verify that ALL overlay tests pass. TDD green phase milestone.

## EXPECTED OUTCOME
19 tests, all PASS. No failures, errors, or skips.

## REQUIRED TOOLS
- `bash`: `python -m pytest tests/test_overlay.py -v`

## MUST DO

```powershell
python -m pytest tests/test_overlay.py -v
```

Fix any failing tests by going back to the relevant task.

## MUST NOT DO
- Do NOT change tests or code -- verification only
- Do NOT skip failing tests

## VERIFICATION

**Expected output (19 passed):**
```
TestOverlayCreation::test_overlay_created_with_correct_flags PASSED
TestOverlayCreation::test_overlay_no_background PASSED
TestOverlayCreation::test_font_config_passed PASSED
TestTextOperations::test_append_text PASSED
TestTextOperations::test_append_text_accumulates PASSED
TestTextOperations::test_add_separator PASSED
TestTextOperations::test_clear PASSED
TestTextOperations::test_multiple_text_blocks PASSED
TestWindowManagement::test_toggle_visibility PASSED
TestWindowManagement::test_set_position_and_size PASSED
TestWindowManagement::test_move_to_cursor PASSED
TestWindowManagement::test_move_to_cursor_is_slot PASSED
TestShadowEffect::test_shadow_effect_created_when_enabled PASSED
TestShadowEffect::test_shadow_effect_none_when_disabled PASSED
TestMarkdownRendering::test_is_markdown_detects_heading PASSED
TestMarkdownRendering::test_is_markdown_detects_asterisk PASSED
TestMarkdownRendering::test_is_markdown_detects_backtick PASSED
TestMarkdownRendering::test_is_markdown_plain_text PASSED
TestMarkdownRendering::test_append_markdown_text_renders PASSED
```

---

# TASK 6: Final Polish -- Lint and Regression Tests

## GOAL
Fix all linting issues, run full test suite, verify pyproject.toml.

## EXPECTED OUTCOME
Clean ruff output. Full test suite passes. pyproject.toml unchanged.

## REQUIRED TOOLS
- `bash`: `ruff check .`, `ruff format .`, `python -m pytest tests/ -v`

## MUST DO

### Step 1: Lint
```powershell
ruff check . --select E,F,I,N,W,UP,B,SIM
```
Fix any issues (import ordering, unused imports, line length).

### Step 2: Format
```powershell
ruff format .
```

### Step 3: Full regression
```powershell
python -m pytest tests/ -v
```

### Step 4: Verify pyproject.toml
- PySide6 -- MUST stay (main.py, hotkey, tray, llm, screenshot use it)
- pytest-qt -- MUST stay (test_main, test_hotkey, test_tray, test_llm, test_screenshot use qtbot)
- markdown -- MUST stay
- No removals needed

## MUST NOT DO
- Do NOT remove PySide6 or pytest-qt
- Do NOT modify any file other than the 4 listed files

## VERIFICATION
- `ruff check .` -- no errors
- `ruff format . --check` -- no diff
- `python -m pytest tests/ -v` -- all pass

---

## Files Summary

| File | Action | Final Lines | Changes |
|------|--------|-------------|---------|
| `signal.py` | **NEW** | ~55 | Signal + SignalSpy classes |
| `overlay.py` | **REWRITE** | ~320 (was 350) | Pure tkinter, no PySide6 imports |
| `tests/test_overlay.py` | **REWRITE** | ~200 (was 183) | No PySide6 imports, uses SignalSpy |
| `main.py` | **EDIT** | ~432 (was 417) | +15 lines (QTimer import, _pump_tkinter, timer stop) |
| `pyproject.toml` | No change | 42 | Dependencies unchanged |

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Markdown HTML parser misses edge cases | Medium | Text renders incorrectly | try/except fallback to plain text |
| `attributes('-transparentcolor')` not working on some Windows versions | Low | No transparency | Test on Win10/Win11; document limitation |
| WM_NCHITTEST subclassing crash on destroy | Low | App crash on exit | Strong reference to wnd_proc |
| QTimer + tkinter interaction lag | Low | Slight stutter | 30ms interval is conservative |
| `SetWindowLongPtrW` pointer conversion on 64-bit | Low | Window proc not replaced | `ctypes.cast(wnd_proc, ctypes.c_void_p).value` |
| Multiple Tk roots in tests | Low | Test hangs | Session-scoped tk_root fixture |