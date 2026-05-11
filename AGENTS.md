# AGENTS.md — read-screen-tool

## What This Is

Windows-only desktop app: screenshot → OCR/vision → LLM streaming → transparent overlay.
Python 3.13, tkinter UI, pynput hotkeys, OpenAI-compatible API (DeepSeek/Qwen).

## Commands

```bash
# Install dependencies (uv preferred)
uv sync

# Run the app
uv run python main.py

# Lint + format check
uv run ruff check .
uv run ruff format --check .

# Auto-fix lint + format
uv run ruff check --fix .
uv run ruff format .

# Type check
uv run pyright

# Tests
uv run pytest                        # all tests
uv run pytest tests/test_config.py   # single file
uv run pytest -k test_name           # single test by name
uv run pytest -v --tb=short          # verbose with short tracebacks
```

**Command order matters**: `ruff check` → `ruff format` → `pyright` → `pytest`

## Architecture

Signal-based modular design. All inter-module communication uses `signals.Signal` (callback list, not Qt).

```
main.py (ReadScreenApp) — orchestrator, wires all signals
├── hotkey.py (HotkeyManager) — pynput global hotkeys
├── screenshot.py (ScreenshotOverlay) — tkinter fullscreen selection
├── ocr.py (OcrEngine) — EasyOCR wrapper, lazy-loaded
├── llm.py (LlmClient) — OpenAI API streaming + tool calling
├── session.py (ConversationSession) — message history + token counting
├── overlay.py (OutputOverlay) — transparent tkinter text overlay
├── tray.py (TrayManager) — pystray system tray
├── knowledge.py — tool definitions for LLM (grep/read/write)
├── config.py — YAML config loading + dataclass validation
└── signals.py — Signal/SignalSpy primitives
```

**Signal flow**: `HotkeyManager.screenshot_requested` → `ScreenshotOverlay.start_selection` → `screenshot_taken` → OCR (if needed) → `LlmClient.send` → `token_received` → `OutputOverlay.append_text`

## Critical Quirks

### Thread Safety
- **tkinter is single-threaded.** Use `Signal.safe_emit()` from ANY background thread (pynput, OCR, LLM worker). `safe_emit()` marshals via `root.after_idle()`.
- `Signal.emit()` is synchronous — only safe from the tkinter main thread.
- OCR runs in a daemon thread (`_OcrWorker`).
- LLM streaming runs on a persistent worker thread (`_LlmWorker`).

### DeepSeek API Quirks
- `finish_reason="tool_calls"` appears on EVERY tool_call chunk, not just the last one. Do NOT break early on this.
- Stream may have `finish_reason` set while `delta` still has content. Only break when `finish_reason` is set AND `delta.tool_calls` is empty.
- `reasoning_content` is a custom field on assistant messages (not standard OpenAI). Must round-trip it for tool call continuations.

### Tool Call Batching
When the LLM makes multiple tool calls in one response, ALL results must be submitted together before calling `continue_after_tool()`. The code batches them: `_on_tool_call_requested` accumulates results, and `_on_response_complete` calls `continue_after_tool()` once all are ready.

### Session Compression
- Compresses at 70% of context window (`_compression_threshold = 0.7`).
- Keeps newest ~30% of context, summarizes older messages.
- Compression is text-only (truncates to 200 chars per message). No LLM call for summary.

### tkinter Overlay
- `OutputOverlay` uses a singleton `tk.Tk` root via `overlay._get_root()`.
- Markdown rendering is debounced (150ms) for streaming. Raw text inserts immediately; formatted re-render follows.
- Window alpha controls visibility: 0.82 = visible, 0.0 = hidden.

### Config
- `config.yaml` is gitignored (contains API keys). Use `config.yaml.example` as template.
- YAML key `provider` maps to field `providers` (plural). See `_YAML_TO_FIELD` in config.py.
- `default_model` is optional — defaults to first model in list if unset.

### OCR Language Mapping
- `"ch"`, `"cn"`, `"zh"`, `"zh-cn"` all map to EasyOCR's `"ch_sim"`.
- `"ch_sim"` automatically includes `"en"` as well.

### Screenshot Format
- mss captures BGRA → drop alpha → BGR numpy array.
- EasyOCR accepts BGR directly.
- Vision models get RGB (converted in `_encode_image` via PIL).

## Testing

- Fixtures in `tests/conftest.py`: `temp_dir`, `sample_config_dict`, `sample_config_path`.
- Tests mock pynput/EasyOCR imports to avoid hardware dependencies.
- `config.yaml` is not needed for tests — fixtures create temp configs.

## Style

- **Ruff rules**: E, F, I, N, W, UP, B, SIM
- **Line length**: 100
- **Quote style**: double quotes
- **Python target**: 3.13 (use modern syntax: `X | Y` unions, `type` statements)
- **Docstrings**: Google style
