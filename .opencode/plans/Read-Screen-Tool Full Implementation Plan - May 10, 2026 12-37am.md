---
created: 2026-05-09T16:37:18.270Z
source: plannotator
tags: [plannotator, read-screen-tool, full]
---

[[Plannotator Plans]]


# Read-Screen-Tool: Full Implementation Plan

## Context

Greenfield Python desktop app: Ctrl+Shift+LeftClick triggers screenshot selection, sends to LLM (with PaddleOCR fallback for non-vision models), streams response to a transparent floating overlay window. Knowledge base grep tool for function calling. Session management with 70% context compression.

**Existing artifacts**: skeleton `main.py` (6 lines), sample `config.yaml` (2 providers, 1 model), empty `pyproject.toml`, populated `knowledge/` directory, `.gitignore` with `config.yaml` excluded.

**Key constraint**: `.gitignore` excludes `config.yaml` — real API keys are already committed. After expanding config, the committed version must be a safe template, and tests must use mock/env-based config.

---

## Task Dependency Graph

| Task | Depends On | Blocks | Reason |
|------|------------|--------|--------|
| T0: Setup pyproject.toml | None | T1-T9 | All modules need deps installed |
| T1: config.py | T0 | T2, T3, T4, T5 | Foundation for all modules |
| T2: knowledge.py | T0 | T5, T9 | Independent grep tool |
| T3: ocr.py | T0, T1 | T6 | Needs config.ocr section |
| T4: session.py | T0, T1 | T5 | Needs config.models for context window size |
| T5: llm.py | T0, T1, T4 | T6, T8 | Needs config + session; tool calling needs knowledge |
| T6: tray.py | T0, T1 | T9 | Needs config.systray |
| T7: screenshot.py | T0 | T8, T9 | Qt overlay, independent |
| T8: overlay.py | T0 | T9 | Qt output window, independent |
| T9: hotkey.py | T0, T5, T6, T7, T8 | T10 | Glue: pynput events → Qt signals → orchestrator |
| T10: main.py | T0, T5, T6, T7, T8, T9 | None | Final orchestrator, wires everything |

---

## Parallel Execution Graph

### Wave 1 (Start immediately — no blocking dependencies)
├── **T0: Setup pyproject.toml** (no deps)
└── **T2: knowledge.py** (only needs T0, but practically independent — deps already known)

### Wave 2 (After T0, T1 complete)
T1 unblocks the rest. T0 unblocks all.
├── **T1: config.py** (depends: T0)
├── **T7: screenshot.py** (depends: T0 — only needs PySide6)
└── **T8: overlay.py** (depends: T0 — only needs PySide6)

### Wave 3 (After T1 + independent modules)
├── **T3: ocr.py** (depends: T0, T1)
├── **T4: session.py** (depends: T0, T1)
└── **T6: tray.py** (depends: T0, T1)

### Wave 4 (After T4)
└── **T5: llm.py** (depends: T0, T1, T4; also references T2 for tool definitions)

### Wave 5 (After T3, T5, T7, T8)
└── **T9: hotkey.py** (depends: T3, T5, T7, T8)

### Wave 6 (After T5, T6, T7, T8, T9)
└── **T10: main.py** (depends: all)

**Critical Path**: T0 → T1 → T4 → T5 → T9 → T10
**Estimated Parallel Speedup**: ~45% vs sequential (GUI modules T7/T8 and knowledge T2 parallelize early)

---

## Tasks

### T0: Setup pyproject.toml and install dependencies
**Description**: Populate pyproject.toml with all dependencies (PySide6>=6.8, pynput>=1.7, mss>=10.0, paddleocr>=3.0, openai>=1.0, tiktoken>=0.8, pystray>=0.19, pillow>=11.0, pytest>=8, pytest-qt>=4, pyyaml>=6). Install deps. Create `tests/` directory with `__init__.py` and `conftest.py` (shared fixtures: temp config, mock Qt app).

**Delegation Recommendation**:
- Category: `quick` — single file edits + package install
- Skills: `[]` — straightforward dependency management

**Skills Evaluation**:
- OMITTED all — no specialized domain needed for dependency management

**Depends On**: None
**Acceptance Criteria**: 
- `pip install -e ".[dev]"` succeeds
- `pytest --collect-only` finds no tests yet but doesn't error
- `.python-version` already set to 3.13

---

### T1: config.py — Configuration loading and validation
**Description**: Create `config.py` with dataclass-based config model. Load from `config.yaml`, validate structure. Expand config.yaml to include: `system_prompt`, `ocr.{language,device}`, `screenshot.hotkey`, `output_window.{position,size,font,shadow}`, `systray.show_icon`, `knowledge.{enabled,directory}`. Default provider: currently active model. Must provide a safe template config (no real API keys) for committed version; tests use temp config files.

Key classes:
- `AppConfig` — root dataclass
- `ProviderConfig`, `ModelConfig`, `OcrConfig`, `ScreenshotConfig`, `OutputWindowConfig`, `SystrayConfig`, `KnowledgeConfig`
- `load_config(path) -> AppConfig` function

**Delegation Recommendation**:
- Category: `quick` — straightforward dataclass modeling
- Skills: `[]` — pure Python data modeling

**Skills Evaluation**:
- OMITTED all — dataclass + YAML parsing needs no domain-specific skills

**Depends On**: T0
**Acceptance Criteria**:
- Tests in `tests/test_config.py`: valid config loads, invalid config raises clear error, defaults applied correctly
- `python -m pytest tests/test_config.py -v` passes
- Config YAML has all required sections with sensible defaults

---

### T2: knowledge.py — Knowledge base grep tool
**Description**: Create `knowledge.py` implementing a grep function for `.txt` files in `knowledge/` directory. Returns matching lines with file name, line number, and surrounding context. Designed as an OpenAI function call tool definition.

Key functions:
- `grep_knowledge(pattern: str, max_results: int = 20, context_lines: int = 2) -> str`
- `get_grep_tool_definition() -> dict` — returns OpenAI-compatible tool spec

**Delegation Recommendation**:
- Category: `quick` — simple file I/O + regex
- Skills: `[]` — no specialized skills needed

**Skills Evaluation**:
- OMITTED all — file I/O and regex are basic

**Depends On**: T0
**Acceptance Criteria**:
- Tests in `tests/test_knowledge.py`: grep finds matches, handles no matches, respects max_results, provides context lines, skips non-.txt files, handles missing directory
- `python -m pytest tests/test_knowledge.py -v` passes

---

### T3: ocr.py — PaddleOCR wrapper
**Description**: Create `ocr.py` wrapping PaddleOCR v3.x. Accepts numpy array (from mss screenshot) or PIL Image, returns extracted text string. Configurable language and device from config. Lazy initialization to avoid loading model at import time.

Key classes/functions:
- `class OcrEngine` — wraps PaddleOCR, `recognize(image: np.ndarray) -> str`

**Delegation Recommendation**:
- Category: `quick` — thin wrapper
- Skills: `[]` — straightforward API wrapping

**Skills Evaluation**:
- OMITTED all — thin wrapper around well-documented PaddleOCR API

**Depends On**: T0, T1
**Acceptance Criteria**:
- Tests in `tests/test_ocr.py`: mock PaddleOCR, verify image → text pipeline, verify lazy init, verify language/device config propagation
- `python -m pytest tests/test_ocr.py -v` passes

---

### T4: session.py — Conversation session and context compression
**Description**: Create `session.py` managing LLM conversation history. Token counting via tiktoken, capacity monitoring at 70% threshold, compression via LLM summarization of oldest messages. Exposes OpenAI-compatible message list.

Key classes:
- `class ConversationSession` — `add_message(role, content)`, `get_messages() -> list[dict]`, `token_count() -> int`, `needs_compression() -> bool`, `compress(llm_client) -> None` (summarize oldest messages into system message)

**Delegation Recommendation**:
- Category: `deep` — involves token counting logic, message truncation strategy, threshold math
- Skills: `[]` — pure logic, no domain-specific skill matches

**Skills Evaluation**:
- OMITTED all — algorithmic logic, no UI/build/domain skill applies

**Depends On**: T0, T1
**Acceptance Criteria**:
- Tests in `tests/test_session.py`: token counting accurate with known strings, needs_compression triggers at 70%, compression reduces token count, older messages summarized, image messages counted reasonably, empty session handles correctly
- `python -m pytest tests/test_session.py -v` passes

---

### T5: llm.py — LLM client with streaming and tool calling
**Description**: Create `llm.py` wrapping OpenAI-compatible client. Supports streaming responses, tool calling with delta accumulation, vision input (base64 images), and knowledge grep integration. Uses PySide6 signals to emit tokens to the Qt main thread. Context window management via session.

Key classes/functions:
- `class LlmClient(QObject)` — `send(user_text, image=None)`, signal `token_received(str)`, signal `response_complete(str)`, signal `error_occurred(str)`, `build_messages(user_text, image)`, `handle_tool_calls(delta)`, `execute_tool(tool_name, args)`

Thread safety: runs HTTP requests in QThread or asyncio event loop, emits signals to main thread.

**Delegation Recommendation**:
- Category: `deep` — streaming delta accumulation, tool call loop management, thread safety with Qt signals, vision image encoding
- Skills: `[]` — complex integration but no matching skill domain

**Skills Evaluation**:
- OMITTED all — OpenAI SDK + PySide6 integration doesn't fit any available skill domain

**Depends On**: T0, T1, T4
**Acceptance Criteria**:
- Tests in `tests/test_llm.py`: mock OpenAI responses, verify streaming token emission, verify tool call handling, verify vision image encoding, verify error handling, verify session messages updated after response
- `python -m pytest tests/test_llm.py -v` passes

---

### T6: tray.py — System tray icon
**Description**: Create `tray.py` using pystray. Configurable visibility. Menu items: Show/Hide, Exit. Must integrate with PySide6's event loop (pystray has its own thread). On exit, clean up all resources.

Key classes:
- `class TrayManager` — `start()`, `stop()`, `toggle_visibility()`, signal `show_requested`, signal `hide_requested`, signal `exit_requested`

**Delegation Recommendation**:
- Category: `quick` — thin pystray wrapper
- Skills: `[]` — straightforward icon + menu setup

**Skills Evaluation**:
- OMITTED all — standard pystray integration

**Depends On**: T0, T1
**Acceptance Criteria**:
- Tests in `tests/test_tray.py`: mock pystray, verify menu creation, verify show_icon config respected, verify exit signal
- `python -m pytest tests/test_tray.py -v` passes

---

### T7: screenshot.py — Screenshot selection overlay
**Description**: Create `screenshot.py` with a full-screen transparent QWidget overlay. Draws selection rectangle as user drags mouse. On release, captures the region via mss and emits the image as signal. Window attributes: `Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool`, `WA_TranslucentBackground`.

Key classes:
- `class ScreenshotOverlay(QWidget)` — `start_selection()`, `paintEvent`, `mousePressEvent/mouseMoveEvent/mouseReleaseEvent`, signal `screenshot_taken(QImage/np.ndarray)`, signal `selection_cancelled()`

**Delegation Recommendation**:
- Category: `visual-engineering` — complex Qt painting, transparent overlay, mouse event handling
- Skills: [`frontend-ui-ux`] — UI/UX quality for selection rectangle aesthetics

**Skills Evaluation**:
- INCLUDED `frontend-ui-ux`: selection overlay UX (thin rectangle, visual feedback during drag, cancel on Esc) benefits from UI design expertise

**Depends On**: T0
**Acceptance Criteria**:
- Tests in `tests/test_screenshot.py`: mock screen capture, verify overlay appears/disappears, verify rectangle drawing, verify mss capture region matches selection, verify signal emission
- `python -m pytest tests/test_screenshot.py -v` passes

---

### T8: overlay.py — Transparent output window
**Description**: Create `overlay.py` with a frameless, transparent, always-on-top floating window. Displays LLM response text with shadow for readability. No taskbar icon. Ctrl+Shift+Z toggles visibility. Alt+Mouse moves/resizes when focused. Supports text selection. Horizontal rules between replies.

Window flags: `Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.NoDropShadowWindowHint`. Attribute: `WA_TranslucentBackground | WA_ShowWithoutActivating`.

Key classes:
- `class OutputOverlay(QWidget)` — `append_text(text)`, `add_separator()`, `clear()`, `toggle_visibility()`, `set_position(x,y)`, `set_size(w,h)`, `paintEvent` (custom text rendering with shadow)

**Delegation Recommendation**:
- Category: `visual-engineering` — complex transparent window rendering, text shadow, frameless move/resize
- Skills: [`frontend-ui-ux`] — transparency, text readability with shadows, Alt+drag UX

**Skills Evaluation**:
- INCLUDED `frontend-ui-ux`: transparent floating window aesthetics, text shadow rendering, draggable frameless window patterns

**Depends On**: T0
**Acceptance Criteria**:
- Tests in `tests/test_overlay.py`: verify text append/display, verify separator rendering, verify visibility toggle, verify window flags, verify no taskbar icon
- `python -m pytest tests/test_overlay.py -v` passes

---

### T9: hotkey.py — Global hotkey management
**Description**: Create `hotkey.py` using pynput keyboard.Listener + mouse.Listener. Tracks Ctrl+Shift state. On Ctrl+Shift+LeftClick: triggers screenshot overlay. On screenshot complete: passes image to LLM client. On Ctrl+Shift+Z: toggles output window visibility. Bridges pynput background threads to Qt main thread via signals.

Key classes:
- `class HotkeyManager(QObject)` — `start()`, `stop()`, signal `screenshot_triggered()`, signal `toggle_overlay_triggered()`

Thread safety critical: pynput listeners run in daemon threads, ALL Qt operations must be signal-bridged.

**Delegation Recommendation**:
- Category: `deep` — multi-thread coordination, pynput threading model, state machine for modifier tracking
- Skills: `[]` — threading logic, no matching domain skill

**Skills Evaluation**:
- OMITTED all — pynput + Qt thread bridging is systems programming, not covered by available skills

**Depends On**: T0, T5, T6, T7, T8
**Acceptance Criteria**:
- Tests in `tests/test_hotkey.py`: mock pynput listeners, verify Ctrl+Shift state tracking, verify screenshot triggered on left click when modifiers held, verify toggle on Ctrl+Shift+Z, verify signals emitted on Qt main thread
- `python -m pytest tests/test_hotkey.py -v` passes

---

### T10: main.py — Application entry point and orchestrator
**Description**: Create `main.py` as the orchestrator. Initialize QApplication, load config, create all module instances, wire signals/slots, start hotkey listeners, start tray manager, enter Qt event loop. Clean shutdown on exit.

Signal wiring:
- HotkeyManager.screenshot_triggered → ScreenshotOverlay.start_selection
- ScreenshotOverlay.screenshot_taken → LlmClient.send
- LlmClient.token_received → OutputOverlay.append_text
- LlmClient.response_complete → OutputOverlay.add_separator
- HotkeyManager.toggle_overlay_triggered → OutputOverlay.toggle_visibility
- TrayManager.exit_requested → QApplication.quit

**Delegation Recommendation**:
- Category: `ultrabrain` — integration of 9 modules, complex signal wiring, correct initialization order
- Skills: `[]` — pure orchestration

**Skills Evaluation**:
- OMITTED all — orchestration logic

**Depends On**: T0, T5, T6, T7, T8, T9
**Acceptance Criteria**:
- Tests in `tests/test_main.py`: integration test with mocked Qt app, verify signal wiring chain end-to-end, verify config loading, verify clean shutdown
- `python -m pytest tests/test_main.py -v` passes
- `python main.py` launches without errors (manual verification)

---

## Commit Strategy

**Atomic commits at each task boundary** — each task produces exactly one commit after tests pass:

| Commit | Task | Message |
|--------|------|---------|
| 1 | T0 | `chore: add project dependencies and test scaffolding` |
| 2 | T1 | `feat: implement config loading with validation` |
| 3 | T2 | `feat: add knowledge base grep tool` |
| 4 | T3 | `feat: add PaddleOCR wrapper` |
| 5 | T4 | `feat: add conversation session with token-aware compression` |
| 6 | T5 | `feat: add LLM client with streaming and tool calling` |
| 7 | T6 | `feat: add system tray manager` |
| 8 | T7 | `feat: add screenshot selection overlay` |
| 9 | T8 | `feat: add transparent floating output window` |
| 10 | T9 | `feat: add global hotkey management` |
| 11 | T10 | `feat: wire orchestrator and complete application` |
| 12 | Final | `chore: final integration polish, lint pass` |

Each commit: `git add <module.py> tests/test_<module>.py` → `pytest tests/test_<module>.py` must pass → commit.

Config template: After T1, commit a `config.yaml.example` with placeholder values while `.gitignore` keeps real config out.

---

## Success Criteria

1. **All 10 module test suites pass**: `python -m pytest tests/ -v`
2. **Config validation**: Invalid config.yaml raises clear, actionable errors
3. **Screenshot flow**: Ctrl+Shift+LeftClick → selection overlay → capture → LLM/OCR → streaming response → overlay display
4. **Overlay behavior**: Transparent, no taskbar icon, Ctrl+Shift+Z toggle, Alt+drag move/resize, text shadow readable
5. **Session compression**: Tokens counted correctly, compression triggers at 70%, history preserved
6. **Knowledge grep**: LLM can call grep tool, results fed back correctly
7. **Tray optional**: Respects `systray.show_icon` config
8. **Thread safety**: No Qt warnings about cross-thread operations
9. **Clean shutdown**: Quit from tray or Ctrl+C cleans up pynput listeners, Qt windows, tray icon
10. **Code style**: Consistent across all modules (type hints, docstrings, naming conventions)

---

## TODO List (ADD THESE)

> CALLER: Add these TODOs using TodoWrite/TaskCreate and execute by wave.

### Wave 1 (Start Immediately — No Dependencies)

- [ ] **T0: Setup pyproject.toml and install dependencies**
  - What: Edit pyproject.toml with all deps (PySide6, pynput, mss, paddleocr, openai, tiktoken, pystray, pillow, pytest, pytest-qt, pyyaml). Create tests/__init__.py, tests/conftest.py with shared fixtures. Run pip install -e ".[dev]".
  - Depends: None
  - Blocks: T1-T9
  - Category: `quick`
  - Skills: `[]`
  - QA: `pip install -e ".[dev]"` succeeds; `pytest --collect-only` runs without error

- [ ] **T2: knowledge.py — Knowledge base grep tool**
  - What: Create knowledge.py with grep_knowledge() and get_grep_tool_definition(). Write tests/test_knowledge.py. Use knowledge/ sample file for integration.
  - Depends: None (deps already known)
  - Blocks: T5, T9
  - Category: `quick`
  - Skills: `[]`
  - QA: `python -m pytest tests/test_knowledge.py -v` passes

### Wave 2 (After T0 Completes)

- [ ] **T1: config.py — Configuration loading and validation**
  - What: Create config.py with AppConfig dataclasses. Expand config.yaml with all sections. Write tests/test_config.py. Create config.yaml.example template.
  - Depends: T0
  - Blocks: T2-T9
  - Category: `quick`
  - Skills: `[]`
  - QA: `python -m pytest tests/test_config.py -v` passes; config loads without error

- [ ] **T7: screenshot.py — Screenshot selection overlay**
  - What: Create screenshot.py with ScreenshotOverlay(QWidget). Full-screen transparent overlay, selection rectangle drawing, mss capture, signal emission. Write tests/test_screenshot.py.
  - Depends: T0
  - Blocks: T9, T10
  - Category: `visual-engineering`
  - Skills: [`frontend-ui-ux`]
  - QA: `python -m pytest tests/test_screenshot.py -v` passes

- [ ] **T8: overlay.py — Transparent output window**
  - What: Create overlay.py with OutputOverlay(QWidget). Frameless transparent window, text shadow rendering, append_text/add_separator, Alt+drag move/resize, visibility toggle. Write tests/test_overlay.py.
  - Depends: T0
  - Blocks: T9, T10
  - Category: `visual-engineering`
  - Skills: [`frontend-ui-ux`]
  - QA: `python -m pytest tests/test_overlay.py -v` passes

### Wave 3 (After T1 Completes)

- [ ] **T3: ocr.py — PaddleOCR wrapper**
  - What: Create ocr.py with OcrEngine class. Lazy init, numpy/PIL input, text output. Write tests/test_ocr.py with mocked PaddleOCR.
  - Depends: T0, T1
  - Blocks: T9
  - Category: `quick`
  - Skills: `[]`
  - QA: `python -m pytest tests/test_ocr.py -v` passes

- [ ] **T4: session.py — Conversation session and compression**
  - What: Create session.py with ConversationSession class. tiktoken counting, 70% threshold, compress() via summarization. Write tests/test_session.py.
  - Depends: T0, T1
  - Blocks: T5
  - Category: `deep`
  - Skills: `[]`
  - QA: `python -m pytest tests/test_session.py -v` passes

- [ ] **T6: tray.py — System tray icon**
  - What: Create tray.py with TrayManager class. pystray integration, menu, visibility toggle, exit signal. Write tests/test_tray.py.
  - Depends: T0, T1
  - Blocks: T9, T10
  - Category: `quick`
  - Skills: `[]`
  - QA: `python -m pytest tests/test_tray.py -v` passes

### Wave 4 (After T4 Completes)

- [ ] **T5: llm.py — LLM client with streaming and tool calling**
  - What: Create llm.py with LlmClient(QObject). OpenAI streaming, token signals, tool call delta accumulation, knowledge grep execution, vision encoding. Write tests/test_llm.py with mocked OpenAI responses.
  - Depends: T0, T1, T4
  - Blocks: T9, T10
  - Category: `deep`
  - Skills: `[]`
  - QA: `python -m pytest tests/test_llm.py -v` passes

### Wave 5 (After T3, T5, T7, T8 Complete)

- [ ] **T9: hotkey.py — Global hotkey management**
  - What: Create hotkey.py with HotkeyManager(QObject). pynput keyboard+ mouse listeners, Ctrl+Shift state tracking, screenshot/toggle triggers, Qt signal bridging. Write tests/test_hotkey.py with mocked pynput.
  - Depends: T0, T5, T7, T8
  - Blocks: T10
  - Category: `deep`
  - Skills: `[]`
  - QA: `python -m pytest tests/test_hotkey.py -v` passes

### Wave 6 (After T5, T6, T7, T8, T9 Complete)

- [ ] **T10: main.py — Application entry point and orchestrator**
  - What: Rewrite main.py as full orchestrator. Init QApplication, load config, create all modules, wire signals, start listeners, enter event loop. Write tests/test_main.py with integration tests.
  - Depends: T0, T5, T6, T7, T8, T9
  - Blocks: None
  - Category: `ultrabrain`
  - Skills: `[]`
  - QA: `python -m pytest tests/test_main.py -v` passes; `python main.py` launches

## Execution Instructions

1. **Wave 1**: Fire T0 + T2 IN PARALLEL
   ```
   task(category="quick", load_skills=[], run_in_background=false, prompt="T0: Setup pyproject.toml ...")
   task(category="quick", load_skills=[], run_in_background=false, prompt="T2: knowledge.py ...")
   ```

2. **Wave 2**: After Wave 1 completes, fire T1 + T7 + T8 IN PARALLEL
   ```
   task(category="quick", load_skills=[], run_in_background=false, prompt="T1: config.py ...")
   task(category="visual-engineering", load_skills=["frontend-ui-ux"], run_in_background=false, prompt="T7: screenshot.py ...")
   task(category="visual-engineering", load_skills=["frontend-ui-ux"], run_in_background=false, prompt="T8: overlay.py ...")
   ```

3. **Wave 3**: After Wave 2, fire T3 + T4 + T6 IN PARALLEL
   ```
   task(category="quick", load_skills=[], run_in_background=false, prompt="T3: ocr.py ...")
   task(category="deep", load_skills=[], run_in_background=false, prompt="T4: session.py ...")
   task(category="quick", load_skills=[], run_in_background=false, prompt="T6: tray.py ...")
   ```

4. **Wave 4**: After T4 completes, fire T5
   ```
   task(category="deep", load_skills=[], run_in_background=false, prompt="T5: llm.py ...")
   ```

5. **Wave 5**: After T3, T5, T7, T8 complete, fire T9
   ```
   task(category="deep", load_skills=[], run_in_background=false, prompt="T9: hotkey.py ...")
   ```

6. **Wave 6**: After T5, T6, T7, T8, T9 complete, fire T10
   ```
   task(category="ultrabrain", load_skills=[], run_in_background=false, prompt="T10: main.py ...")
   ```

7. **Final QA**: `python -m pytest tests/ -v` — all 10 test suites must pass. Git status clean except for config.yaml changes (excluded by .gitignore).
