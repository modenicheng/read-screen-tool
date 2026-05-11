"""Tests for the application orchestrator (main.py)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from config import AppConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def create_minimal_config() -> AppConfig:
    """Build a minimal valid AppConfig for testing."""
    from config import (
        FontConfig,
        HotkeyConfig,
        KnowledgeConfig,
        ModelConfig,
        OcrConfig,
        OutputWindowConfig,
        PositionConfig,
        ProviderConfig,
        SizeConfig,
        SystrayConfig,
    )

    return AppConfig(
        providers=[
            ProviderConfig(name="test-prov", api_key="sk-test", base_url="https://test.com")
        ],
        models=[
            ModelConfig(name="test-model", provider="test-prov", context=1048576, vision=False)
        ],
        system_prompt="You are a test assistant.",
        default_model="test-model",
        ocr=OcrConfig(language="ch", device="cpu"),
        hotkeys=HotkeyConfig(
            screenshot="ctrl+shift+left",
            toggle_overlay="ctrl+alt+a",
            move_overlay="ctrl+shift+right",
        ),
        output_window=OutputWindowConfig(
            position=PositionConfig(x=0, y=0),
            size=SizeConfig(width=400, height=300),
            font=FontConfig(family="Arial", size=12, color="#FFF"),
            shadow=True,
        ),
        systray=SystrayConfig(show_icon=False),
        knowledge=KnowledgeConfig(enabled=True, directory="knowledge"),
    )


def create_vision_config() -> AppConfig:
    """Build a config with a vision-capable model."""
    cfg = create_minimal_config()
    cfg.models[0].vision = True
    return cfg


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app_config() -> AppConfig:
    """Return a minimal config with vision=False."""
    return create_minimal_config()


@pytest.fixture
def vision_config() -> AppConfig:
    """Return a config with vision=True."""
    return create_vision_config()


@pytest.fixture
def mock_lib_imports():
    """Mock all heavy / potentially-missing components.

    Uses plain MagicMock (no autospec) so that Qt Signal attributes
    resolve to MagicMock instances that support ``.connect()``.
    The hotkey module does not exist yet, so we inject a fake module
    into sys.modules.
    """
    import sys

    fake_hotkey = MagicMock()
    fake_hotkey.HotkeyManager = MagicMock()

    with (
        patch.dict(sys.modules, {"hotkey": fake_hotkey}),
        patch("tray.TrayManager", create=True),
        patch("main.ScreenshotOverlay"),
        patch("main.OutputOverlay"),
        patch("main.LlmClient"),
        patch("main.OcrEngine"),
        patch("main.ConversationSession"),
    ):
        yield


@pytest.fixture
def orchestrator(qtbot, app_config, mock_lib_imports):
    """Create a ReadScreenApp with all external components mocked."""
    from main import ReadScreenApp

    app = ReadScreenApp(app_config)
    return app


@pytest.fixture
def orchestrator_vision(qtbot, vision_config, mock_lib_imports):
    """Create a ReadScreenApp with vision model."""
    from main import ReadScreenApp

    app = ReadScreenApp(vision_config)
    return app


# ---------------------------------------------------------------------------
# 1. Initialization
# ---------------------------------------------------------------------------


class TestInitialization:
    """Tests for ReadScreenApp creation and component setup."""

    def test_creates_app_with_valid_config(self, orchestrator, app_config):
        """App initializes without errors and stores config."""
        assert orchestrator._config is app_config

    def test_model_and_provider_extracted(self, orchestrator):
        """Active model and provider are resolved from config."""
        assert orchestrator._model.name == "test-model"
        assert orchestrator._provider.name == "test-prov"

    def test_session_initialized_with_system_prompt(self, orchestrator):
        """Conversation session is created with system prompt set."""
        assert orchestrator._session is not None
        orchestrator._session.set_system_message.assert_called_once_with(
            "You are a test assistant."
        )

    def test_ocr_engine_created_for_non_vision_model(self, orchestrator):
        """OCR engine is initialized when model.vision is False."""
        assert orchestrator._ocr_engine is not None

    def test_ocr_engine_not_created_for_vision_model(self, orchestrator_vision):
        """OCR engine is NOT initialized when model.vision is True."""
        assert orchestrator_vision._ocr_engine is None

    def test_llm_client_configured(self, orchestrator):
        """LLM client is created and configured with correct params."""
        orchestrator._llm_client.configure.assert_called_once()
        call_kwargs = orchestrator._llm_client.configure.call_args[1]
        assert call_kwargs["model"] == "test-model"
        assert call_kwargs["system_prompt"] == "You are a test assistant."
        assert call_kwargs["session"] is orchestrator._session
        assert len(call_kwargs["tools"]) == 1

    def test_llm_client_configured_without_tools(self, qtbot, app_config, mock_lib_imports):
        """When knowledge is disabled, no tools are configured."""
        from main import ReadScreenApp

        app_config.knowledge.enabled = False
        app = ReadScreenApp(app_config)
        call_kwargs = app._llm_client.configure.call_args[1]
        assert call_kwargs["tools"] == []

    def test_screenshot_overlay_created(self, orchestrator):
        """ScreenshotOverlay is instantiated."""
        assert orchestrator._screenshot_overlay is not None

    def test_output_overlay_positioned(self, orchestrator):
        """OutputOverlay is created and positioned from config."""
        orchestrator._output_overlay.set_position.assert_called_with(0, 0)
        orchestrator._output_overlay.set_size.assert_called_with(400, 300)

    def test_tray_created_with_config(self, orchestrator):
        """TrayManager is created."""
        assert orchestrator._tray is not None

    def test_hotkey_import_failure_is_handled(self, qtbot, app_config):
        """When hotkey module is missing, _hotkey is None (no crash)."""
        import sys

        with (
            patch.dict(sys.modules, {"hotkey": None}),
            patch("tray.TrayManager", create=True),
            patch("main.ScreenshotOverlay"),
            patch("main.OutputOverlay"),
            patch("main.LlmClient"),
            patch("main.OcrEngine"),
            patch("main.ConversationSession"),
        ):
            from main import ReadScreenApp

            app = ReadScreenApp(app_config)
            assert app._hotkey is None


# ---------------------------------------------------------------------------
# 2. Signal Wiring
# ---------------------------------------------------------------------------


class TestSignalWiring:
    """Tests for signal connections between components."""

    def test_screenshot_requested_connected_to_start_selection(self, orchestrator):
        """HotkeyManager.screenshot_requested → ScreenshotOverlay.start_selection."""
        orchestrator._hotkey.screenshot_requested.connect.assert_called_with(
            orchestrator._screenshot_overlay.start_selection
        )

    def test_toggle_overlay_connected(self, orchestrator):
        """HotkeyManager.toggle_overlay_requested → ReadScreenApp._toggle_overlay (bridge)."""
        orchestrator._hotkey.toggle_overlay_requested.connect.assert_called_with(
            orchestrator._toggle_overlay
        )

    def test_move_overlay_connected(self, orchestrator):
        """HotkeyManager.move_overlay_to_cursor → ReadScreenApp._move_overlay_to_cursor (bridge)."""
        orchestrator._hotkey.move_overlay_to_cursor.connect.assert_called_with(
            orchestrator._move_overlay_to_cursor
        )

    def test_screenshot_taken_connected_to_queue(self, orchestrator):
        """ScreenshotOverlay.screenshot_taken → _queue_screenshot."""
        orchestrator._screenshot_overlay.screenshot_taken.connect.assert_called_with(
            orchestrator._queue_screenshot
        )

    def test_token_received_connected_to_append_text(self, orchestrator):
        """LlmClient.token_received → OutputOverlay.append_text."""
        orchestrator._llm_client.token_received.connect.assert_called_with(
            orchestrator._output_overlay.append_text
        )

    def test_response_complete_connected(self, orchestrator):
        """LlmClient.response_complete → _on_response_complete."""
        orchestrator._llm_client.response_complete.connect.assert_called_with(
            orchestrator._on_response_complete
        )

    def test_error_occurred_connected(self, orchestrator):
        """LlmClient.error_occurred → _on_llm_error."""
        orchestrator._llm_client.error_occurred.connect.assert_called_with(
            orchestrator._on_llm_error
        )

    def test_tool_call_connected(self, orchestrator):
        """LlmClient.tool_call_requested → _on_tool_call_requested."""
        orchestrator._llm_client.tool_call_requested.connect.assert_called_with(
            orchestrator._on_tool_call_requested
        )

    def test_tray_show_connected(self, orchestrator):
        """TrayManager.show_requested → OutputOverlay.show."""
        orchestrator._tray.show_requested.connect.assert_called_with(
            orchestrator._output_overlay.show
        )

    def test_tray_hide_connected(self, orchestrator):
        """TrayManager.hide_requested → OutputOverlay.hide."""
        orchestrator._tray.hide_requested.connect.assert_called_with(
            orchestrator._output_overlay.hide
        )

    def test_tray_exit_connected(self, orchestrator):
        """TrayManager.exit_requested → exit handler."""
        orchestrator._tray.exit_requested.connect.assert_called_with(orchestrator._handle_exit)

    def test_no_crash_when_hotkey_missing(self, qtbot, app_config):
        """Signal wiring does not crash when hotkey is None."""
        import sys

        with (
            patch.dict(sys.modules, {"hotkey": None}),
            patch("main.ScreenshotOverlay"),
            patch("main.OutputOverlay"),
            patch("main.LlmClient"),
            patch("main.OcrEngine"),
            patch("main.ConversationSession"),
            patch("tray.TrayManager", create=True),
        ):
            from main import ReadScreenApp

            app = ReadScreenApp(app_config)
            # Should not crash; screenshot_taken wiring still works
            app._screenshot_overlay.screenshot_taken.connect.assert_called_with(
                app._queue_screenshot
            )


# ---------------------------------------------------------------------------
# 3. Screenshot Processing Pipeline
# ---------------------------------------------------------------------------


class TestScreenshotProcessing:
    """Tests for _queue_screenshot / async OCR pipeline logic."""

    def test_vision_model_sends_image_directly(self, orchestrator_vision):
        """When model has vision, image is sent directly with a prompt."""
        image = np.zeros((100, 100, 3), dtype=np.uint8)
        orchestrator_vision._queue_screenshot(image)

        orchestrator_vision._llm_client.send.assert_called_once()
        call_args = orchestrator_vision._llm_client.send.call_args
        assert call_args[0][0]  # prompt non-empty
        assert call_args[1]["image"] is image

    def test_non_vision_model_runs_ocr(self, orchestrator):
        """When model lacks vision, OCR runs async, then LLM is called."""
        ocr_text = "Hello from OCR"
        image = np.zeros((100, 100, 3), dtype=np.uint8)

        # Enqueue — OCR runs in worker thread; LLM NOT called yet
        orchestrator._queue_screenshot(image)
        orchestrator._llm_client.send.assert_not_called()

        # Simulate OCR worker completion via signal
        orchestrator._on_ocr_completed(ocr_text)

        # LLM was called with OCR text in prompt
        orchestrator._llm_client.send.assert_called_once()
        prompt = orchestrator._llm_client.send.call_args[0][0]
        assert ocr_text in prompt

    def test_non_vision_ocr_returns_empty_string(self, orchestrator):
        """When OCR returns empty, a fallback prompt is used."""
        image = np.zeros((100, 100, 3), dtype=np.uint8)
        orchestrator._queue_screenshot(image)
        orchestrator._on_ocr_completed("")

        orchestrator._llm_client.send.assert_called_once()
        prompt = orchestrator._llm_client.send.call_args[0][0]
        assert "No text was detected" in prompt

    def test_non_vision_ocr_returns_whitespace_only(self, orchestrator):
        """When OCR returns only whitespace, fallback prompt is used."""
        image = np.zeros((100, 100, 3), dtype=np.uint8)
        orchestrator._queue_screenshot(image)
        orchestrator._on_ocr_completed("   \n  \t  ")

        prompt = orchestrator._llm_client.send.call_args[0][0]
        assert "No text was detected" in prompt

    def test_non_vision_without_ocr_worker(self, orchestrator_vision):
        """When _ocr_worker is None and vision=False, finish without LLM call."""
        orchestrator_vision._model.vision = False
        orchestrator_vision._ocr_worker = None

        image = np.zeros((100, 100, 3), dtype=np.uint8)
        orchestrator_vision._queue_screenshot(image)

        # No OCR worker → no LLM call, queue is finished immediately
        orchestrator_vision._llm_client.send.assert_not_called()
        assert orchestrator_vision._processing is False


# ---------------------------------------------------------------------------
# 4. Response Completion and Compression
# ---------------------------------------------------------------------------


class TestResponseCompletion:
    """Tests for _on_response_complete and memory compression."""

    def test_adds_separator_on_non_empty_response(self, orchestrator):
        """When response is non-empty, add_separator is called."""
        orchestrator._on_response_complete("Here is the answer.")
        orchestrator._output_overlay.add_separator.assert_called_once()

    def test_no_separator_on_empty_response(self, orchestrator):
        """When response is empty/whitespace, no separator is added."""
        orchestrator._on_response_complete("")
        orchestrator._output_overlay.add_separator.assert_not_called()

    def test_compression_triggered_when_needed(self, orchestrator):
        """When needs_compression() is True, compress() is called."""
        orchestrator._session.needs_compression.return_value = True

        orchestrator._on_response_complete("Some reply.")

        orchestrator._session.compress.assert_called_once()

    def test_compression_not_triggered_when_not_needed(self, orchestrator):
        """When needs_compression() is False, compress() is NOT called."""
        orchestrator._session.needs_compression.return_value = False

        orchestrator._on_response_complete("Some reply.")

        orchestrator._session.compress.assert_not_called()


# ---------------------------------------------------------------------------
# 5. LLM Error Handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Tests for _on_llm_error."""

    def test_error_displayed_in_overlay(self, orchestrator):
        """LLM errors are shown in the output overlay."""
        orchestrator._on_llm_error("Connection timeout")

        orchestrator._output_overlay.append_text.assert_called_with("[Error: Connection timeout]")
        orchestrator._output_overlay.add_separator.assert_called_once()

    def test_error_with_empty_message(self, orchestrator):
        """Error with empty message still displayed."""
        orchestrator._on_llm_error("")
        orchestrator._output_overlay.append_text.assert_called_with("[Error: ]")


# ---------------------------------------------------------------------------
# 6. Tool Calling Dispatch
# ---------------------------------------------------------------------------


class TestToolCalling:
    """Tests for _on_tool_call_requested and tool dispatch."""

    def test_grep_knowledge_tool_dispatched(self, orchestrator):
        """When LLM requests grep_knowledge, it is executed and result submitted."""
        tool_call = {
            "id": "call_abc",
            "name": "grep_knowledge",
            "arguments": {"pattern": "test", "max_results": 5, "context_lines": 1},
        }

        with patch("main.grep_knowledge", return_value="Found: test line") as mock_grep:
            orchestrator._on_tool_call_requested(tool_call)

        mock_grep.assert_called_once_with(
            pattern="test",
            max_results=5,
            context_lines=1,
            knowledge_dir="knowledge",
        )
        orchestrator._llm_client.submit_tool_result.assert_called_once_with(
            "call_abc", "Found: test line"
        )
        orchestrator._llm_client.continue_after_tool.assert_called_once()

    def test_grep_knowledge_default_args(self, orchestrator):
        """When grep args are missing, defaults are used."""
        tool_call = {
            "id": "call_def",
            "name": "grep_knowledge",
            "arguments": {},
        }

        with patch("main.grep_knowledge", return_value="No matches found.") as mock_grep:
            orchestrator._on_tool_call_requested(tool_call)

        mock_grep.assert_called_once_with(
            pattern="",
            max_results=20,
            context_lines=2,
            knowledge_dir="knowledge",
        )
        orchestrator._llm_client.submit_tool_result.assert_called_once_with(
            "call_def", "No matches found."
        )
        orchestrator._llm_client.continue_after_tool.assert_called_once()

    def test_unknown_tool_returns_error_result(self, orchestrator):
        """Unknown tool calls return an error string as result."""
        tool_call = {
            "id": "call_unk",
            "name": "unknown_tool",
            "arguments": {"x": 1},
        }

        orchestrator._on_tool_call_requested(tool_call)

        orchestrator._llm_client.submit_tool_result.assert_called_once_with(
            "call_unk", "Tool 'unknown_tool' is not available."
        )
        orchestrator._llm_client.continue_after_tool.assert_called_once()

    def test_tool_call_with_string_max_results(self, orchestrator):
        """String-type max_results is coerced to int."""
        tool_call = {
            "id": "call_str",
            "name": "grep_knowledge",
            "arguments": {"pattern": "hello", "max_results": "10"},
        }

        with patch("main.grep_knowledge", return_value="result") as mock_grep:
            orchestrator._on_tool_call_requested(tool_call)

        mock_grep.assert_called_once_with(
            pattern="hello",
            max_results=10,
            context_lines=2,
            knowledge_dir="knowledge",
        )


# ---------------------------------------------------------------------------
# 7. Lifecycle (start/stop)
# ---------------------------------------------------------------------------


class TestLifecycle:
    """Tests for start() and stop() methods."""

    def test_start_starts_hotkey_and_tray(self, orchestrator):
        """start() calls start on hotkey and tray managers."""
        orchestrator.start()
        orchestrator._hotkey.start.assert_called_once()
        orchestrator._tray.start.assert_called_once()

    def test_stop_stops_hotkey_and_tray(self, orchestrator):
        """stop() calls stop on hotkey, tray, and llm_client."""
        orchestrator.stop()
        orchestrator._hotkey.stop.assert_called_once()
        orchestrator._tray.stop.assert_called_once()
        orchestrator._llm_client.stop.assert_called_once()

    def test_start_without_hotkey(self, qtbot, app_config):
        """start() does not crash when hotkey is None."""
        import sys

        with (
            patch.dict(sys.modules, {"hotkey": None}),
            patch("main.ScreenshotOverlay"),
            patch("main.OutputOverlay"),
            patch("main.LlmClient"),
            patch("main.OcrEngine"),
            patch("main.ConversationSession"),
            patch("tray.TrayManager", create=True),
        ):
            from main import ReadScreenApp

            app = ReadScreenApp(app_config)
            app.start()  # Should not raise

    def test_stop_without_hotkey(self, qtbot, app_config):
        """stop() does not crash when hotkey is None."""
        import sys

        with (
            patch.dict(sys.modules, {"hotkey": None}),
            patch("main.ScreenshotOverlay"),
            patch("main.OutputOverlay"),
            patch("main.LlmClient"),
            patch("main.OcrEngine"),
            patch("main.ConversationSession"),
            patch("tray.TrayManager", create=True),
        ):
            from main import ReadScreenApp

            app = ReadScreenApp(app_config)
            app.stop()  # Should not raise


# ---------------------------------------------------------------------------
# 8. main() Entry Point
# ---------------------------------------------------------------------------


class TestMainFunction:
    """Tests for the main() entry point."""

    def test_main_loads_config_and_starts(self, qtbot, sample_config_path):
        """main() loads config from file, creates QApp, starts app."""
        with (
            patch("main.QApplication") as mock_qapp_cls,
            patch("main.ReadScreenApp") as mock_app_cls,
            patch("main.sys.exit") as mock_exit,
        ):
            mock_qapp = MagicMock()
            mock_qapp.exec.return_value = 0
            mock_qapp_cls.return_value = mock_qapp

            mock_app = MagicMock()
            mock_app_cls.return_value = mock_app

            with patch("sys.argv", ["main.py", str(sample_config_path)]):
                from main import main

                main()

            mock_qapp_cls.assert_called_once()
            mock_qapp.setQuitOnLastWindowClosed.assert_called_with(False)
            mock_app_cls.assert_called_once()
            config_arg = mock_app_cls.call_args[0][0]
            assert config_arg.default_model == "deepseek-v4-pro"
            mock_app.start.assert_called_once()
            mock_qapp.exec.assert_called_once()
            mock_exit.assert_called_once_with(0)

    def test_main_default_config_path(self, qtbot):
        """main() uses 'config.yaml' when no argv provided."""
        with (
            patch("main.load_config") as mock_load,
            patch("main.QApplication") as mock_qapp_cls,
            patch("main.ReadScreenApp") as mock_app_cls,
            patch("main.sys.exit"),
        ):
            mock_qapp = MagicMock()
            mock_qapp.exec.return_value = 0
            mock_qapp_cls.return_value = mock_qapp
            mock_app = MagicMock()
            mock_app_cls.return_value = mock_app

            with patch("sys.argv", ["main.py"]):
                from main import main

                main()

            mock_load.assert_called_once_with("config.yaml")

    def test_main_custom_config_path(self, qtbot, sample_config_path):
        """main() uses the config path provided in sys.argv[1]."""
        with (
            patch("main.QApplication") as mock_qapp_cls,
            patch("main.ReadScreenApp") as mock_app_cls,
            patch("main.sys.exit"),
        ):
            mock_qapp = MagicMock()
            mock_qapp.exec.return_value = 0
            mock_qapp_cls.return_value = mock_qapp
            mock_app = MagicMock()
            mock_app_cls.return_value = mock_app

            custom_path = str(sample_config_path)
            with patch("sys.argv", ["main.py", custom_path]):
                from main import main

                main()

            mock_qapp_cls.assert_called_once()
            mock_qapp.setQuitOnLastWindowClosed.assert_called_with(False)

            mock_app_cls.assert_called_once()
            config_arg = mock_app_cls.call_args[0][0]
            assert config_arg.default_model == "deepseek-v4-pro"

            mock_app.start.assert_called_once()
            mock_qapp.exec.assert_called_once()


# ---------------------------------------------------------------------------
# 9. End-to-End Integration Scenarios
# ---------------------------------------------------------------------------


class TestIntegrationScenarios:
    """High-level integration tests for the full pipeline."""

    def test_full_ocr_pipeline(self, orchestrator):
        """Simulate screenshot → OCR → LLM → separator flow."""
        image = np.zeros((50, 50, 3), dtype=np.uint8)
        orchestrator._queue_screenshot(image)

        # OCR runs async — simulate completion
        orchestrator._on_ocr_completed("Screen text content.")

        sent_prompt = orchestrator._llm_client.send.call_args[0][0]
        assert "Screen text content." in sent_prompt
        assert "extracted from the screen" in sent_prompt

    def test_full_vision_pipeline(self, orchestrator_vision):
        """Simulate screenshot → vision → LLM flow."""
        image = np.zeros((50, 50, 3), dtype=np.uint8)
        orchestrator_vision._queue_screenshot(image)

        call_kwargs = orchestrator_vision._llm_client.send.call_args
        assert call_kwargs[0][0]  # prompt non-empty
        assert call_kwargs[1]["image"] is image

    def test_tool_call_completes_full_cycle(self, orchestrator):
        """Tool call: grep executed, result submitted, conversation continues."""
        tool_call = {
            "id": "call_cycle",
            "name": "grep_knowledge",
            "arguments": {"pattern": "needle"},
        }

        with patch("main.grep_knowledge", return_value="Found needle in haystack.txt"):
            orchestrator._on_tool_call_requested(tool_call)

        assert orchestrator._llm_client.submit_tool_result.called
        assert orchestrator._llm_client.continue_after_tool.called

    def test_response_triggers_compression(self, orchestrator):
        """When at 70% threshold, compression is forced after response."""
        orchestrator._session.needs_compression.return_value = True

        orchestrator._on_response_complete("A very long response...")

        orchestrator._session.compress.assert_called_once()
        orchestrator._output_overlay.add_separator.assert_called_once()

    def test_multiple_screenshots_accumulate_in_session(self, orchestrator):
        """Each screenshot call updates the same session (no clearing)."""
        image = np.zeros((10, 10, 3), dtype=np.uint8)

        # First screenshot → OCR → LLM
        orchestrator._queue_screenshot(image)
        orchestrator._on_ocr_completed("First capture")
        # Finish processing to release the queue
        orchestrator._on_response_complete("")
        assert orchestrator._processing is False

        # Second screenshot → OCR → LLM
        orchestrator._queue_screenshot(image)
        orchestrator._on_ocr_completed("Second capture")

        assert orchestrator._llm_client.send.call_count == 2

    def test_knowledge_directory_from_config(self, orchestrator, app_config):
        """grep_knowledge uses the directory from config."""
        app_config.knowledge.directory = "custom_knowledge"

        tool_call = {
            "id": "call_dir",
            "name": "grep_knowledge",
            "arguments": {"pattern": "search"},
        }

        with patch("main.grep_knowledge", return_value="result") as mock_grep:
            orchestrator._on_tool_call_requested(tool_call)

        mock_grep.assert_called_once()
        assert mock_grep.call_args[1]["knowledge_dir"] == "custom_knowledge"
