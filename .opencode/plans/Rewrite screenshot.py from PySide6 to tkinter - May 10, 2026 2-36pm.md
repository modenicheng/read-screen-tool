---
created: 2026-05-10T06:36:09.103Z
source: plannotator
tags: [plannotator, read-screen-tool, rewrite, screenshot, pyside6]
---

[[Plannotator Plans]]

# Plan: Rewrite screenshot.py from PySide6 to tkinter

## Context

**User Request**: Rewrite `screenshot.py` (172 lines) from PySide6/Qt to tkinter. Remove ALL PySide6 imports from screenshot.py. Update tests and main.py accordingly.

**Key Architecture Facts**:
- Signal class already exists in `signals.py` as a non-Qt callback-based replacement
- `overlay.py` already uses tkinter Toplevel with `overrideredirect(True)`, alpha transparency, and the `signals.Signal` class
- `_get_root()` in overlay.py provides a singleton hidden `tk.Tk()` — must be shared
- `main.py` uses PySide6 for QApplication/QTimer, but that stays — only screenshot.py loses PySide6
- `hotkey.py` emits Qt Signals → connected to `start_selection()` method (runs on main thread, compatible with tkinter)
- Tests currently use qtbot/QApplication → need complete rewrite
- `selection_cancelled` Signal exists but is NOT connected in main.py (tested but not wired)

**Design Decision**: Option A — Fresh Toplevel per `start_selection()` call. Simpler, no show/hide issues with `overrideredirect(True)` windows on Windows.

## Task Dependency Graph

| Task | Depends On | Reason |
|------|------------|--------|
| T1: Rewrite screenshot.py | None | Starting point — new module with zero PySide6 |
| T2: Rewrite tests/test_screenshot.py | T1 | Tests verify T1 implementation |
| T3: Update main.py imports/connections | T1 | Must match new ScreenshotOverlay API |
| T4: Final verification (lint + test) | T2, T3 | Must pass all checks before commit |

## Parallel Execution Graph

**Wave 1** (Start immediately):
└── T1: Rewrite screenshot.py (no dependencies)

**Wave 2** (After Wave 1 completes):
├── T2: Rewrite tests/test_screenshot.py (depends: T1)
└── T3: Update main.py (depends: T1)

**Wave 3** (After Wave 2 completes):
└── T4: Final verification — lint + run tests (depends: T2, T3)

**Critical Path**: T1 → T2 → T4
**Estimated Parallel Speedup**: ~25% (T2 and T3 can run in parallel in Wave 2)

## Tasks

### Task 1: Rewrite screenshot.py

**Description**: Replace entire `screenshot.py` (172 lines) with a tkinter + ctypes implementation. The class `ScreenshotOverlay` retains the same public API: `screenshot_taken` Signal, `selection_cancelled` Signal, `start_selection()` method. Each `start_selection()` call creates a fresh `tk.Toplevel` covering the monitor where the cursor is, handles mouse selection via Canvas, captures via mss, then destroys the window.

**Implementation Details**:
- Import `_get_root` from `overlay` (shared singleton tk root)
- Use `signals.Signal` for `screenshot_taken` and `selection_cancelled`
- Use `ctypes.windll.user32.GetCursorPos`, `MonitorFromPoint`, `GetMonitorInfoW` for accurate per-monitor geometry
- Create `tk.Toplevel` with `overrideredirect(True)`, `wm_attributes('-topmost', True)`, `wm_attributes('-alpha', 0.92)`, `bg='black'`
- Use `tk.Canvas` for drawing: 4 filled rectangles for dark overlay, 1 outline rectangle for selection border, 1 text for size label
- Bind `<Button-1>`, `<B1-Motion>`, `<ButtonRelease-1>`, `<Escape>` for mouse/keyboard handling
- `_capture_screen_region()` uses mss with screen-relative coordinates (monitor offset added from `GetMonitorInfoW`)
- After capture or cancel, destroy the Toplevel window
- Same minimum selection threshold (10x10 pixels) as current code

**Delegation Recommendation**:
- Category: `deep` — requires careful multi-component integration (tkinter, ctypes, mss), accurate coordinate math across multi-monitor
- Skills: [`frontend-ui-ux`] — tkinter Canvas drawing with dithered stipple overlays, visual accuracy

**Skills Evaluation**:
- INCLUDED `frontend-ui-ux`: tkinter Canvas overlay rendering with semi-transparency and visual polish
- OMITTED `git-master`: Not needed for code writing
- OMITTED `review-work`: Separate task after implementation
- OMITTED `ai-slop-remover`: Will apply after if needed

**Depends On**: None
**Acceptance Criteria**:
1. Zero PySide6 imports in screenshot.py
2. `ScreenshotOverlay()` instantiates without errors
3. `screenshot_taken` and `selection_cancelled` are `signals.Signal` instances
4. `start_selection()` creates and shows a Toplevel window
5. Mouse drag draws selection rectangle on Canvas
6. Release with selection > 10x10 emits `screenshot_taken` with np.ndarray
7. Escape key emits `selection_cancelled`
8. Window destroyed after capture or cancel

### Task 2: Rewrite tests/test_screenshot.py

**Description**: Replace all qtbot/PySide6-based tests (107 lines) with tkinter-compatible tests. Follow the pattern in `test_overlay.py`: no qtbot fixture, use `signals.SignalSpy` for signal assertions, manual cleanup via `.close()` or auto-destroy.

**Tests to implement** (matching existing coverage):
1. `test_creates_toplevel_window` — verify tkinter window type
2. `test_start_selection_shows_window` — call start_selection(), verify window exists + visible
3. `test_mouse_drag_draws_selection` — simulate mouse events on Canvas, verify internal state
4. `test_small_selection_cancels` — drag < 10px, verify `selection_cancelled` emitted
5. `test_escape_cancels` — simulate Escape, verify `selection_cancelled` emitted
6. `test_get_selection_rect_normalizes` — set start > end, verify normalized rect
7. `test_screenshot_taken_signal` — mock `_capture_screen_region`, simulate valid drag, verify signal + ndarray shape
8. `test_window_destroyed_after_capture` — verify Toplevel destroyed after capture

**Mocking strategy**:
- Mock `ctypes.windll.user32.GetCursorPos` and `GetMonitorInfoW` to control cursor/monitor position
- Mock `mss.mss().grab()` to avoid actual screen capture
- Use `tkinter` event generation: `window.event_generate('<Button-1>', x=100, y=100)`

**Delegation Recommendation**:
- Category: `deep` — requires test infrastructure design for tkinter event simulation, ctypes mocking
- Skills: [] — standard pytest patterns, no specialized skills needed

**Skills Evaluation**:
- OMITTED `frontend-ui-ux`: Testing, not UI design
- OMITTED `git-master`: Not a git operation
- OMITTED `review-work`: Separate review phase
- OMITTED all others: Domain doesn't match

**Depends On**: T1
**Acceptance Criteria**:
1. All 8 tests pass with pytest
2. No PySide6 imports in test file
3. Each test creates and cleans up its own tkinter window
4. Tests run without `pytest-qt` dependency

### Task 3: Update main.py

**Description**: Verify and update main.py connections for the new ScreenshotOverlay. The new class uses `signals.Signal` instead of PySide6 `Signal`, so the `.connect()` call pattern is identical and should work without changes. Also verify `start_selection()` is called correctly from the hotkey signal handler.

**Changes needed** (minimal):
1. Verify `self._screenshot_overlay = ScreenshotOverlay()` line 147 — new `__init__` takes no `parent` argument (accept or ignore it)
2. Verify `self._screenshot_overlay.screenshot_taken.connect(self._queue_screenshot)` line 207 — `signals.Signal.connect()` takes a callable, which `self._queue_screenshot` (bound method) is
3. Verify `self._hotkey.screenshot_requested.connect(self._screenshot_overlay.start_selection)` line 202 — Qt Signal connects to method reference, still valid

**Likely changes**: None, or at most a minor adjustment if the new `__init__` signature differs. The old one had `def __init__(self, parent: QWidget | None = None)` — we keep `def __init__(self)` and ignore parent.

**Delegation Recommendation**:
- Category: `quick` — trivial verification, 0-3 line changes expected
- Skills: [] — no specialized skills needed

**Skills Evaluation**:
- All OMITTED: Simple verification task, no domain overlap

**Depends On**: T1
**Acceptance Criteria**:
1. `main.py` imports work with new ScreenshotOverlay
2. Signal connections compile and connect correctly
3. No type errors from PySide6 → Signal mismatch

### Task 4: Final Verification

**Description**: Run lint (ruff), type-check, and full test suite to ensure everything passes.

**Delegation Recommendation**:
- Category: `quick` — verification only, no code changes
- Skills: [] — running commands

**Depends On**: T2, T3
**Acceptance Criteria**:
1. `ruff check` passes with zero errors
2. All tests in `tests/test_screenshot.py` pass
3. No regressions in other test files
4. `screenshot.py` contains zero `PySide6` or `Qt` imports

## Commit Strategy

**Single atomic commit** containing:
- `screenshot.py` — rewritten (172 → ~200 lines)
- `tests/test_screenshot.py` — rewritten (107 → ~150 lines)
- `main.py` — minimal connection updates if any

**Commit message**:
```
refactor: rewrite screenshot overlay from PySide6 to tkinter

Replace Qt-based ScreenshotOverlay with tkinter + ctypes implementation.
Uses per-monitor geometry via GetMonitorInfoW, Canvas-based drawing with
dithered overlay effect, and signals.Signal for callback emission.
Tests rewritten to use tkinter event simulation instead of qtbot.
```

## Success Criteria

1. `screenshot.py` has zero PySide6 imports (`grep PySide6 screenshot.py` returns nothing)
2. All 8 screenshot tests pass: `pytest tests/test_screenshot.py -v`
3. Full test suite passes: `pytest tests/ -v`
4. Ruff lint passes: `ruff check screenshot.py tests/test_screenshot.py main.py`
5. `ScreenshotOverlay` API unchanged: `screenshot_taken` Signal, `selection_cancelled` Signal, `start_selection()` method
6. Main.py connections work without modification
