"""Read Screen Tool - LLM-powered screenshot reader with transparent overlay.

Application orchestrator that wires together hotkey capture, screenshot
selection, OCR/vision processing, LLM streaming, tool calling, and the
transparent output overlay.
"""

from __future__ import annotations

import contextlib
import logging
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from config import AppConfig, load_config
from knowledge import (
    get_grep_tool_definition,
    get_read_file_tool_definition,
    get_write_file_tool_definition,
    grep_knowledge,
    read_file,
    write_file,
)
from llm import LlmClient
from ocr import OcrEngine
from overlay import OutputOverlay, _get_root
from screenshot import ScreenshotOverlay
from session import ConversationSession

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_VISION_PROMPT = "Please analyze the content of this screenshot and provide a helpful response."

_OCR_PROMPT_TEMPLATE = (
    "The following text was extracted from the screen:\n\n"
    "{ocr_text}\n\n"
    "Please respond based on this content."
)

_NO_OCR_PROMPT = "No text was detected in the selected region."


# ---------------------------------------------------------------------------
# OCR worker — runs in a daemon thread to keep the main thread free
# ---------------------------------------------------------------------------


class _OcrWorker:
    """Runs OCR in a daemon thread to keep the main thread free."""

    def __init__(self, ocr_engine: OcrEngine) -> None:
        self._ocr_engine = ocr_engine

    def process(self, image: np.ndarray,
                on_completed: Callable[[str], None],
                on_failed: Callable[[str], None]) -> None:
        """Run OCR in a daemon thread, callback on tkinter main thread."""
        def _do_ocr() -> None:
            try:
                logger.info(
                    "[OCR] process() — start image shape=%s, dtype=%s",
                    image.shape,
                    image.dtype,
                )
                text = self._ocr_engine.recognize(image)
                logger.info("[OCR] process() — completed text_len=%d", len(text))
                _get_root().after_idle(lambda: on_completed(text))
            except Exception as exc:
                err_msg = str(exc)
                _get_root().after_idle(lambda: on_failed(err_msg))
        threading.Thread(target=_do_ocr, daemon=True).start()


class ReadScreenApp:
    """Orchestrates all application modules.

    Signal flow:
        HotkeyManager.screenshot_requested → ScreenshotOverlay.start_selection
        ScreenshotOverlay.screenshot_taken → _queue_screenshot
        _queue_screenshot → _OcrWorker.process (daemon thread) if OCR needed
        _OcrWorker → _on_ocr_completed → LlmClient.send
        LlmClient.token_received → OutputOverlay.append_text
        LlmClient.response_complete → _on_response_complete (+ queue dequeue)
        LlmClient.tool_call_requested → _on_tool_call_requested → grep_knowledge
        LlmClient.error_occurred → _on_llm_error (+ queue dequeue)
        HotkeyManager.toggle_overlay_requested → OutputOverlay.toggle_visibility
        TrayManager.show_requested → OutputOverlay.show
        TrayManager.hide_requested → OutputOverlay.hide
        TrayManager.exit_requested → _handle_exit
    """

    def __init__(self, config: AppConfig) -> None:
        """Initialize the application with a validated configuration."""
        self._config = config

        # Active model and provider
        self._model, self._provider = config.get_active_model()

        # Conversation session
        self._session = ConversationSession(context_size=self._model.context)
        self._session.set_system_message(config.system_prompt)

        # OCR engine (only needed for non-vision models)
        self._ocr_engine: OcrEngine | None = None
        if not self._model.vision:
            self._ocr_engine = OcrEngine(
                language=config.ocr.language,
                device=config.ocr.device,
            )

        # LLM client
        self._llm_client = LlmClient()
        tools: list[dict[str, Any]] = []
        if config.knowledge.enabled:
            tools.append(get_grep_tool_definition())
            tools.append(get_read_file_tool_definition())
            tools.append(get_write_file_tool_definition())
        self._llm_client.configure(
            provider_config=self._provider,
            system_prompt=config.system_prompt,
            model=self._model.name,
            session=self._session,
            tools=tools,
        )

        # Screenshot processing queue — serializes OCR → LLM, capacity 1
        self._pending_screenshot: np.ndarray | None = None
        self._processing = False
        self._pending_responses = 0  # counts expected response_complete signals
        self._tool_calls_pending = 0  # counts unhandled tool calls in current response
        self._pending_tool_info: list[dict[str, Any]] = []

        # OCR worker (daemon threads, only for non-vision models)
        self._ocr_worker: _OcrWorker | None = None
        if self._ocr_engine is not None:
            self._ocr_worker = _OcrWorker(self._ocr_engine)

        # Screenshot overlay
        self._screenshot_overlay = ScreenshotOverlay()

        # Output overlay
        self._output_overlay = OutputOverlay(
            font_family=config.output_window.font.family,
            font_size=config.output_window.font.size,
            font_color=config.output_window.font.color,
            shadow=config.output_window.shadow,
        )
        self._output_overlay.set_position(
            config.output_window.position.x,
            config.output_window.position.y,
        )
        self._output_overlay.set_size(
            config.output_window.size.width,
            config.output_window.size.height,
        )
        self._output_overlay.show()

        # Hotkey manager (may not exist yet if built in parallel)
        self._hotkey: Any = None
        try:
            from hotkey import HotkeyManager  # noqa: PLC0415

            self._hotkey = HotkeyManager()
            self._hotkey.set_toggle_hotkey(config.hotkeys.toggle_overlay)
            self._hotkey.set_screenshot_hotkey(config.hotkeys.screenshot)
            self._hotkey.set_move_overlay_hotkey(config.hotkeys.move_overlay)
        except ImportError:
            logger.warning("hotkey module not available — hotkeys disabled.")

        # System tray manager
        self._tray: Any = None
        try:
            from tray import TrayManager  # noqa: PLC0415

            self._tray = TrayManager(
                show_icon=config.systray.show_icon,
                tooltip="Read Screen Tool",
            )
        except ImportError:
            logger.warning("tray module not available — system tray disabled.")

        # Wire all signals
        self._wire_signals()

        # tkinter pump loop state
        self._tk_pump_id: str | None = None

    # -----------------------------------------------------------------------
    # Signal wiring
    # -----------------------------------------------------------------------

    def _wire_signals(self) -> None:
        """Connect signals between all components."""
        # Hotkey → screenshot selection
        if self._hotkey:
            self._hotkey.screenshot_requested.connect(self._screenshot_overlay.start_selection)
            self._hotkey.toggle_overlay_requested.connect(self._toggle_overlay)
            self._hotkey.move_overlay_to_cursor.connect(self._move_overlay_to_cursor)

        # Screenshot taken → enqueue for async processing
        self._screenshot_overlay.screenshot_taken.connect(self._queue_screenshot)

        # LLM streaming → output overlay + console
        self._llm_client.token_received.connect(self._output_overlay.append_text)
        self._llm_client.token_received.connect(lambda t: print(t, end="", flush=True))
        self._llm_client.response_complete.connect(self._on_response_complete)
        self._llm_client.response_complete.connect(lambda _: print())  # newline after reply
        self._llm_client.error_occurred.connect(self._on_llm_error)
        self._llm_client.tool_call_requested.connect(self._on_tool_call_requested)

        # Tray signals → show/hide/exit
        if self._tray:
            self._tray.show_requested.connect(self._output_overlay.show)
            self._tray.hide_requested.connect(self._output_overlay.hide)
            self._tray.exit_requested.connect(self._handle_exit)

    # -----------------------------------------------------------------------
    # Overlay toggle — bridge for thread-safe tkinter calls
    # -----------------------------------------------------------------------

    def _toggle_overlay(self) -> None:
        logger.info("[MAIN] _toggle_overlay() called")
        self._output_overlay.toggle_visibility()

    def _move_overlay_to_cursor(self, x: int, y: int) -> None:
        """Bridge: hotkey signal → tkinter move_to_cursor."""
        logger.info("[MAIN] _move_overlay_to_cursor(%d, %d)", x, y)
        self._output_overlay.move_to_cursor(x, y)

    # -----------------------------------------------------------------------
    # Screenshot queue — serializes OCR → LLM, one at a time
    # -----------------------------------------------------------------------

    def _queue_screenshot(self, image: np.ndarray) -> None:
        """Enqueue a screenshot. Replaces any pending screenshot.

        Only the latest screenshot is kept in the queue.  If no processing
        is in flight, starts immediately; otherwise the pending screenshot
        waits until the current work completes.
        """
        logger.info(
            "[MAIN] _queue_screenshot() — shape=%s, dtype=%s, processing=%s",
            image.shape, image.dtype, self._processing,
        )

        # Save screenshot backup to temp directory
        try:
            from PIL import Image  # noqa: PLC0415

            ts = time.strftime("%Y%m%d_%H%M%S")
            path = Path(tempfile.gettempdir()) / f"readscreen_{ts}.png"
            img_rgb = image[:, :, ::-1]  # BGR → RGB
            Image.fromarray(img_rgb).save(str(path))
            logger.info("[MAIN] Screenshot backup saved: %s", path)
        except Exception as e:
            logger.warning("[MAIN] Failed to save screenshot backup: %s", e)

        self._pending_screenshot = image
        self._try_process_next()

    def _try_process_next(self) -> None:
        """Dequeue and start processing the next screenshot if possible."""
        if self._processing or self._pending_screenshot is None:
            logger.debug(
                "[MAIN] _try_process_next() — skipped (processing=%s, pending=%s)",
                self._processing, self._pending_screenshot is not None,
            )
            return
        self._processing = True
        image = self._pending_screenshot
        self._pending_screenshot = None
        self._pending_responses = 1  # expect one response_complete

        logger.info(
            "[MAIN] _try_process_next() — processing image shape=%s, vision=%s, ocr_worker=%s",
            image.shape, self._model.vision, self._ocr_worker is not None,
        )

        # Show "Thinking..." status while waiting for LLM/OCR
        self._pending_tool_info = []
        self._output_overlay.set_status("Thinking...")

        if self._model.vision:
            self._llm_client.send(_VISION_PROMPT, image=image)
        elif self._ocr_worker is not None:
            # Run OCR in daemon thread, callback on completion
            self._ocr_worker.process(image, self._on_ocr_completed, self._on_ocr_failed)
        else:
            logger.warning("No OCR engine available for non-vision model.")
            self._finish_processing()

    def _on_ocr_completed(self, ocr_text: str) -> None:
        """OCR finished successfully — send the extracted text to the LLM."""
        preview = ocr_text[:100] if ocr_text else ""
        logger.info("[MAIN] _on_ocr_completed() — text_len=%d, preview=%r", len(ocr_text), preview)
        if ocr_text.strip():
            prompt = _OCR_PROMPT_TEMPLATE.format(ocr_text=ocr_text)
        else:
            prompt = _NO_OCR_PROMPT
        self._llm_client.send(prompt)

    def _on_ocr_failed(self, error_msg: str) -> None:
        """OCR encountered an error — display it and release the queue."""
        logger.error("OCR failed: %s", error_msg)
        self._output_overlay.append_text(f"[OCR Error: {error_msg}]")
        self._output_overlay.add_separator()
        self._finish_processing()

    def _finish_processing(self) -> None:
        """Release the queue lock and dequeue the next screenshot if pending."""
        self._processing = False
        self._try_process_next()

    # -----------------------------------------------------------------------
    # LLM response handling
    # -----------------------------------------------------------------------

    def _on_response_complete(self, text: str) -> None:
        """Handle a completed LLM response.

        Adds a separator, checks session compression, and releases the
        queue lock when the final response of the current request completes.
        """
        logger.info(
            "[MAIN] _on_response_complete() — text_len=%d, pending_responses=%d",
            len(text), self._pending_responses,
        )
        self._output_overlay.clear_status()
        self._pending_tool_info = []
        if text.strip():
            self._output_overlay.add_separator()

        # Check token count: compress at 70% of context window
        if self._session.needs_compression():
            logger.info(
                "Token count at %d/%d (%.0f%%). Compressing session...",
                self._session.token_count(),
                self._session.context_size,
                self._session.token_count() / self._session.context_size * 100,
            )
            self._session.compress()

        # If tool calls were collected during the just-finished response,
        # submit them all at once with a single continue_after_tool call.
        # This avoids 400 errors when the LLM makes multiple tool calls in
        # a single response (all results must be submitted together).
        if self._tool_calls_pending > 0:
            self._pending_responses += 1  # expect continuation response
            self._tool_calls_pending = 0
            self._llm_client.continue_after_tool()
            self._output_overlay.set_status("Thinking...")

        # Dequeue counter: each response_complete decrements.
        # Tool calls increment the counter so _finish_processing only fires
        # after the *final* response (including tool continuations).
        if self._pending_responses > 0:
            self._pending_responses -= 1
            if self._pending_responses == 0:
                self._finish_processing()

    def _on_llm_error(self, error_msg: str) -> None:
        """Display LLM errors in the output overlay and release the queue."""
        logger.error("[MAIN] _on_llm_error() — %s", error_msg)
        self._output_overlay.clear_status()
        self._output_overlay.append_text(f"[Error: {error_msg}]")
        self._output_overlay.add_separator()
        if self._pending_responses > 0:
            self._pending_responses = 0
            self._tool_calls_pending = 0
            self._pending_tool_info = []
            self._finish_processing()

    # -----------------------------------------------------------------------
    # Tool calling
    # -----------------------------------------------------------------------

    def _update_agent_status(self) -> None:
        """Build and display the agent status from pending tool calls.

        Grep tools show "搜索<pattern>...". Multiple grep patterns are
        joined with "|". If the combined string exceeds ~40 characters,
        shows "搜索<n>个关键词中...". Other tools just show their name.
        """
        grep_patterns: list[str] = []
        other_tools: list[str] = []

        for t in self._pending_tool_info:
            name = t.get("name", "")
            if name == "grep_knowledge":
                pattern = str(t.get("arguments", {}).get("pattern", ""))
                if pattern:
                    grep_patterns.append(pattern)
            else:
                other_tools.append(name)

        parts: list[str] = []
        if grep_patterns:
            combined = "|".join(grep_patterns)
            if len(combined) > 40:
                parts.append(f"搜索{len(grep_patterns)}个关键词中...")
            else:
                parts.append(f"搜索{combined}...")
        if other_tools:
            parts.append(", ".join(other_tools))

        status = " | ".join(parts) if parts else ""
        if status:
            self._output_overlay.set_status(status)

    def _on_tool_call_requested(self, tool_call: dict[str, Any]) -> None:
        """Dispatch tool calls from the LLM.

        Supported tools:
        - ``grep_knowledge``: Search text files in the knowledge base.
        - ``read_file``: Read a file from knowledge/ or memory/ directories.
        - ``write_file``: Write a file to knowledge/ or memory/ directories.

        Tool results are submitted to the session but NOT immediately
        continued.  When multiple tool calls arrive in a single LLM response,
        all results are batched and ``continue_after_tool`` is called once
        from ``_on_response_complete``, avoiding 400 errors from the API.
        """
        name = tool_call.get("name", "")
        tc_id = tool_call.get("id", "")
        args: dict[str, Any] = tool_call.get("arguments", {})
        logger.info("[MAIN] _on_tool_call_requested() — tool=%s, id=%s, args=%s", name, tc_id, args)

        allowed_dirs = [self._config.knowledge.directory, self._config.knowledge.memory_directory]

        if name == "grep_knowledge":
            pattern = str(args.get("pattern", ""))
            max_results = int(args.get("max_results", 20))
            context_lines = int(args.get("context_lines", 2))
            knowledge_dir = self._config.knowledge.directory

            result = grep_knowledge(
                pattern=pattern,
                max_results=max_results,
                context_lines=context_lines,
                knowledge_dir=knowledge_dir,
            )

            self._llm_client.submit_tool_result(tc_id, result)
            self._tool_calls_pending += 1
            self._pending_tool_info.append(tool_call)
            self._update_agent_status()

        elif name == "read_file":
            file_path = str(args.get("file_path", ""))
            result = read_file(file_path=file_path, allowed_dirs=allowed_dirs)

            self._llm_client.submit_tool_result(tc_id, result)
            self._tool_calls_pending += 1
            self._pending_tool_info.append(tool_call)
            self._update_agent_status()

        elif name == "write_file":
            file_path = str(args.get("file_path", ""))
            content = str(args.get("content", ""))
            result = write_file(file_path=file_path, content=content, allowed_dirs=allowed_dirs)

            self._llm_client.submit_tool_result(tc_id, result)
            self._tool_calls_pending += 1
            self._pending_tool_info.append(tool_call)
            self._update_agent_status()

        else:
            logger.warning("Unknown tool call: %s", name)
            self._llm_client.submit_tool_result(
                tc_id,
                f"Tool '{name}' is not available.",
            )
            self._tool_calls_pending += 1
            self._pending_tool_info.append(tool_call)
            self._update_agent_status()

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    def _tk_pump_loop(self) -> None:
        """Pump the tkinter event loop periodically (~30ms)."""
        with contextlib.suppress(Exception):
            self._output_overlay.pump()
        self._tk_pump_id = _get_root().after(30, self._tk_pump_loop)

    def start(self) -> None:
        """Start all runtime components (hotkey listener, tray icon)."""
        self._tk_pump_id = _get_root().after(30, self._tk_pump_loop)
        if self._hotkey:
            self._hotkey.start()
        if self._tray:
            self._tray.start()
        logger.info("ReadScreenApp started.")

    def stop(self) -> None:
        """Stop all runtime components."""
        if self._tk_pump_id is not None:
            _get_root().after_cancel(self._tk_pump_id)
            self._tk_pump_id = None
        if self._hotkey:
            self._hotkey.stop()
        if self._tray:
            self._tray.stop()
        self._llm_client.stop()
        logger.info("ReadScreenApp stopped.")

    def _handle_exit(self) -> None:
        """Handle tray exit request."""
        self.stop()
        _get_root().quit()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Application entry point.

    Parses an optional config file path from ``sys.argv``, creates the
    tkinter root, loads configuration, instantiates ``ReadScreenApp``,
    and enters the tkinter event loop.
    """
    # Config path from command line or default
    config_path: str | Path = "config.yaml"
    if len(sys.argv) > 1:
        config_path = sys.argv[1]

    # Logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    # Load configuration
    config = load_config(config_path)

    # Initialize tkinter root (must come first — OutputOverlay uses it)
    root = _get_root()

    # Create and start the app orchestrator
    screen_app = ReadScreenApp(config)
    screen_app.start()

    # Run tkinter event loop
    root.mainloop()


if __name__ == "__main__":
    main()
