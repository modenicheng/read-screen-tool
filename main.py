"""Read Screen Tool - LLM-powered screenshot reader with transparent overlay.

Application orchestrator that wires together hotkey capture, screenshot
selection, OCR/vision processing, LLM streaming, tool calling, and the
transparent output overlay.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from config import AppConfig, load_config
from knowledge import get_grep_tool_definition, grep_knowledge
from llm import LlmClient
from ocr import OcrEngine
from overlay import OutputOverlay
from screenshot import ScreenshotOverlay
from session import ConversationSession

if TYPE_CHECKING:
    import numpy as np

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


class ReadScreenApp(QObject):
    """Orchestrates all application modules.

    Signal flow:
        HotkeyManager.screenshot_requested → ScreenshotOverlay.start_selection
        ScreenshotOverlay.screenshot_taken → _process_screenshot → LlmClient.send
        LlmClient.token_received → OutputOverlay.append_text
        LlmClient.response_complete → OutputOverlay.add_separator (+ compression check)
        LlmClient.tool_call_requested → _on_tool_call_requested → grep_knowledge
        LlmClient.error_occurred → OutputOverlay error display
        HotkeyManager.toggle_overlay_requested → OutputOverlay.toggle_visibility
        TrayManager.show_requested → OutputOverlay.show
        TrayManager.hide_requested → OutputOverlay.hide
        TrayManager.exit_requested → QApplication.quit
    """

    def __init__(self, config: AppConfig, parent: QObject | None = None) -> None:
        """Initialize the application with a validated configuration.

        Args:
            config: Fully-loaded AppConfig instance.
            parent: Parent QObject.
        """
        super().__init__(parent)
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
        self._llm_client.configure(
            provider_config=self._provider,
            system_prompt=config.system_prompt,
            model=self._model.name,
            session=self._session,
            tools=tools,
        )

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

        # Hotkey manager (may not exist yet if built in parallel)
        self._hotkey: Any = None
        try:
            from hotkey import HotkeyManager  # noqa: PLC0415

            self._hotkey = HotkeyManager()
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

    # -----------------------------------------------------------------------
    # Signal wiring
    # -----------------------------------------------------------------------

    def _wire_signals(self) -> None:
        """Connect signals between all components."""
        # Hotkey → screenshot selection
        if self._hotkey:
            self._hotkey.screenshot_requested.connect(self._screenshot_overlay.start_selection)
            self._hotkey.toggle_overlay_requested.connect(self._output_overlay.toggle_visibility)

        # Screenshot taken → process
        self._screenshot_overlay.screenshot_taken.connect(self._process_screenshot)

        # LLM streaming → output overlay
        self._llm_client.token_received.connect(self._output_overlay.append_text)
        self._llm_client.response_complete.connect(self._on_response_complete)
        self._llm_client.error_occurred.connect(self._on_llm_error)
        self._llm_client.tool_call_requested.connect(self._on_tool_call_requested)

        # Tray signals → show/hide/exit
        if self._tray:
            self._tray.show_requested.connect(self._output_overlay.show)
            self._tray.hide_requested.connect(self._output_overlay.hide)
            self._tray.exit_requested.connect(self._handle_exit)

    # -----------------------------------------------------------------------
    # Pipeline: screenshot → OCR/vision → LLM
    # -----------------------------------------------------------------------

    def _process_screenshot(self, image: np.ndarray) -> None:
        """Process a captured screenshot.

        If the active model supports vision, the image is sent directly.
        Otherwise OCR is run first and the extracted text is wrapped in a
        prompt template.

        Args:
            image: numpy array (H, W, 3) of the captured region.
        """
        if self._model.vision:
            self._llm_client.send(_VISION_PROMPT, image=image)
        else:
            ocr_text = self._ocr_engine.recognize(image) if self._ocr_engine else ""

            if ocr_text.strip():
                prompt = _OCR_PROMPT_TEMPLATE.format(ocr_text=ocr_text)
            else:
                prompt = _NO_OCR_PROMPT

            self._llm_client.send(prompt)

    # -----------------------------------------------------------------------
    # LLM response handling
    # -----------------------------------------------------------------------

    def _on_response_complete(self, text: str) -> None:
        """Handle a completed LLM response.

        Adds a separator for visual distinction between replies and checks
        whether the conversation needs compression.

        Args:
            text: The full accumulated response text.
        """
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

    def _on_llm_error(self, error_msg: str) -> None:
        """Display LLM errors in the output overlay.

        Args:
            error_msg: The error message string.
        """
        self._output_overlay.append_text(f"[Error: {error_msg}]")
        self._output_overlay.add_separator()

    # -----------------------------------------------------------------------
    # Tool calling
    # -----------------------------------------------------------------------

    def _on_tool_call_requested(self, tool_call: dict[str, Any]) -> None:
        """Dispatch tool calls from the LLM.

        Only ``grep_knowledge`` is supported.  The tool result is submitted
        back to the LLM client, which continues the conversation.

        Args:
            tool_call: Dict with ``id``, ``name``, and ``arguments`` keys.
        """
        name = tool_call.get("name", "")
        tc_id = tool_call.get("id", "")
        args: dict[str, Any] = tool_call.get("arguments", {})

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
            self._llm_client.continue_after_tool()
        else:
            logger.warning("Unknown tool call: %s", name)
            self._llm_client.submit_tool_result(
                tc_id,
                f"Tool '{name}' is not available.",
            )
            self._llm_client.continue_after_tool()

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    def start(self) -> None:
        """Start all runtime components (hotkey listener, tray icon)."""
        if self._hotkey:
            self._hotkey.start()
        if self._tray:
            self._tray.start()
        logger.info("ReadScreenApp started.")

    def stop(self) -> None:
        """Stop all runtime components."""
        if self._hotkey:
            self._hotkey.stop()
        if self._tray:
            self._tray.stop()
        logger.info("ReadScreenApp stopped.")

    def _handle_exit(self) -> None:
        """Handle tray exit request."""
        self.stop()
        QApplication.quit()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Application entry point.

    Parses an optional config file path from ``sys.argv``, creates the Qt
    application, loads configuration, instantiates ``ReadScreenApp``, and
    enters the Qt event loop.
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

    # Qt application (must exist before any QWidget)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # Create and start the app orchestrator
    screen_app = ReadScreenApp(config)
    screen_app.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
