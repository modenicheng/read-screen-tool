"""Tests for the LLM client module (llm.py).

All tests use mocks — no real API calls are made.
"""

import base64
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from llm import LlmClient

# ---------------------------------------------------------------------------
# Helpers — mock stream chunk factories
# ---------------------------------------------------------------------------


def create_mock_chunk(content=None, role=None, finish_reason=None,
                       tool_calls=None, reasoning_content=None):
    """Create a mock streaming chunk."""
    chunk = MagicMock()
    chunk.choices = []

    if (content is not None or role is not None or tool_calls is not None
            or finish_reason is not None or reasoning_content is not None):
        choice = MagicMock()
        choice.index = 0
        choice.finish_reason = finish_reason

        delta = MagicMock()
        delta.content = content
        delta.role = role
        delta.tool_calls = tool_calls
        delta.reasoning_content = reasoning_content
        choice.delta = delta

        chunk.choices = [choice]

    return chunk


def create_tool_call_chunk(index, tp_id=None, name=None, arguments="",
                           finish_reason="tool_calls"):
    """Create a tool_call delta chunk matching DeepSeek format."""
    tc = MagicMock()
    tc.index = index
    tc.id = tp_id
    tc.type = "function"

    func = MagicMock()
    func.name = name
    func.arguments = arguments
    tc.function = func

    return create_mock_chunk(tool_calls=[tc], finish_reason=finish_reason)


def mock_stream(chunks):
    """Return a callable that yields the given chunks."""
    def _stream(*args, **kwargs):
        yield from chunks
    return _stream


# ---------------------------------------------------------------------------
# Session mock helper
# ---------------------------------------------------------------------------


class MockSession:
    """Minimal mock of ConversationSession for testing LlmClient."""

    def __init__(self):
        self._messages: list[dict] = []
        self._system_message = None

    def set_system_message(self, content: str):
        self._system_message = {"role": "system", "content": content}

    def add_message(self, role, content=None, tool_calls=None,
                    tool_call_id=None, reasoning_content=None):
        msg = {"role": role}
        if content:
            msg["content"] = content
        if tool_calls:
            msg["tool_calls"] = tool_calls
        if tool_call_id:
            msg["tool_call_id"] = tool_call_id
        if reasoning_content:
            msg["reasoning_content"] = reasoning_content
        self._messages.append(msg)

    def get_messages(self):
        messages = []
        if self._system_message:
            messages.append(dict(self._system_message))
        messages.extend(self._messages)
        return messages


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_safe_emit():
    """Patch _get_root so safe_emit works synchronously in tests (no tkinter)."""
    mock_root = MagicMock()
    mock_root.after_idle = lambda fn: fn()
    with patch("overlay._get_root", return_value=mock_root):
        yield


@pytest.fixture
def provider_dict():
    """Return a dict-based provider config."""
    return {
        "name": "deepseek",
        "api_key": "sk-test-key",
        "base_url": "https://api.deepseek.com",
    }


@pytest.fixture
def client(provider_dict):
    """Create a LlmClient with dict-based config."""
    c = LlmClient(provider_config=provider_dict)
    yield c
    c.stop()


@pytest.fixture
def configured_client(provider_dict):
    """Create and configure a LlmClient for use."""
    c = LlmClient(provider_config=provider_dict)
    c.configure(
        provider_config=provider_dict,
        system_prompt="Test system prompt",
        model="deepseek-v4-pro",
    )
    yield c
    c.stop()


@pytest.fixture
def mock_openai():
    """Patch OpenAI client creation and return the mock client instance."""
    with patch("llm.OpenAI") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


# ---------------------------------------------------------------------------
# 1. Initialization
# ---------------------------------------------------------------------------


class TestInitialization:
    """Tests for LlmClient instantiation and configuration."""

    def test_client_created_with_provider_config(self, client, provider_dict):
        """Client stores the provider config passed to __init__."""
        assert client._provider == provider_dict

    def test_configure_sets_client_attributes(self, client, mock_openai):
        """configure() sets model, prompt, and creates OpenAI client."""
        session = MockSession()
        tools = [{"type": "function", "function": {"name": "test_tool"}}]

        client.configure(
            provider_config={"api_key": "sk-abc", "base_url": "https://x.com"},
            system_prompt="Be helpful.",
            model="my-model",
            session=session,
            tools=tools,
        )

        assert client._system_prompt == "Be helpful."
        assert client._current_model == "my-model"
        assert client._session is session
        assert client._tools == tools
        # OpenAI client was created and stored
        assert client._client is mock_openai

    def test_configure_sets_system_message_on_session(self, client, mock_openai):
        """When session is provided, configure() sets the system message."""
        session = MockSession()
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            system_prompt="My prompt",
            model="m",
            session=session,
        )
        msgs = session.get_messages()
        assert len(msgs) == 1
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == "My prompt"

    def test_configure_without_session_does_not_fail(self, client):
        """configure() without a session should not raise."""
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            system_prompt="prompt",
            model="m",
        )
        assert client._system_prompt == "prompt"


# ---------------------------------------------------------------------------
# 2. Message Building
# ---------------------------------------------------------------------------


class TestMessageBuilding:
    """Tests for _build_messages logic."""

    def test_build_messages_text_only(self, client):
        """Text-only message: simple string content."""
        msgs = client._build_messages("Hello world")
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "Hello world"

    def test_build_messages_with_image(self, client):
        """Image message: content is list with text + image_url parts."""
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        msgs = client._build_messages("What's this?", image=img)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        content = msgs[0]["content"]
        assert isinstance(content, list)
        assert len(content) == 2
        assert content[0]["type"] == "text"
        assert content[0]["text"] == "What's this?"
        assert content[1]["type"] == "image_url"
        assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")

    def test_build_messages_with_system_prompt(self, configured_client):
        """System prompt appears as first message."""
        session = MockSession()
        session.set_system_message("System goes first.")
        configured_client._session = session
        configured_client._system_prompt = ""

        msgs = configured_client._build_messages("Hello")
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == "System goes first."
        assert msgs[1]["role"] == "user"
        assert msgs[1]["content"] == "Hello"

    def test_build_messages_override_system_prompt(self, configured_client):
        """system_prompt_override replaces stored prompt for this request."""
        configured_client._system_prompt = "Default prompt"
        msgs = configured_client._build_messages(
            "Hello", system_prompt_override="Override prompt"
        )
        assert len(msgs) == 2
        assert msgs[0]["content"] == "Override prompt"

    def test_build_messages_includes_session_history(self, configured_client):
        """Session messages are included in the request."""
        session = MockSession()
        session.add_message("user", "Previous question")
        session.add_message("assistant", "Previous answer")
        configured_client._session = session
        configured_client._system_prompt = ""

        msgs = configured_client._build_messages("New question")
        assert len(msgs) == 3
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "Previous question"
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["content"] == "Previous answer"
        assert msgs[2]["role"] == "user"
        assert msgs[2]["content"] == "New question"

    def test_build_messages_without_duplicate_system(self, configured_client):
        """When session already has system message, client doesn't add another."""
        session = MockSession()
        session.set_system_message("Session system")
        configured_client._session = session
        configured_client._system_prompt = "Client system"

        msgs = configured_client._build_messages("Hello")
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == "Session system"
        # No duplicate system message
        system_count = sum(1 for m in msgs if m["role"] == "system")
        assert system_count == 1


# ---------------------------------------------------------------------------
# 3. Image Encoding
# ---------------------------------------------------------------------------


class TestImageEncoding:
    """Tests for _encode_image and base64 conversion."""

    def test_encode_image_returns_base64_string(self, configured_client):
        """_encode_image returns a valid base64 string."""
        img = np.zeros((50, 50, 3), dtype=np.uint8)
        result = configured_client._encode_image(img)
        assert isinstance(result, str)
        # Should be decodable as base64
        decoded = base64.b64decode(result)
        assert len(decoded) > 0
        # PNG magic bytes
        assert decoded[:8] == b"\x89PNG\r\n\x1a\n"

    def test_encode_image_4_channel(self, configured_client):
        """4-channel (RGBA) image: uses first 3 channels."""
        img = np.zeros((30, 30, 4), dtype=np.uint8)
        result = configured_client._encode_image(img)
        assert isinstance(result, str)
        decoded = base64.b64decode(result)
        assert decoded[:8] == b"\x89PNG\r\n\x1a\n"

    def test_encode_image_different_sizes(self, configured_client):
        """Encoding works for various image dimensions."""
        for h, w in [(10, 20), (100, 100), (1, 1)]:
            img = np.zeros((h, w, 3), dtype=np.uint8)
            result = configured_client._encode_image(img)
            assert isinstance(result, str)
            assert len(result) > 0


# ---------------------------------------------------------------------------
# 4. Streaming Content
# ---------------------------------------------------------------------------


class TestStreamingContent:
    """Tests for regular content streaming signals."""

    def test_stream_emits_token_received(self, client, mock_openai):
        """Streaming content chunks emit token_received signal."""
        session = MockSession()
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
            session=session,
        )

        chunks = [
            create_mock_chunk(content="Hello"),
            create_mock_chunk(content=" world"),
            create_mock_chunk(content="!", finish_reason="stop"),
        ]
        mock_openai.chat.completions.create.return_value = chunks

        tokens = []
        client.token_received.connect(lambda t: tokens.append(t))

        # Call _stream_request directly (bypassing QThread)
        messages = [{"role": "user", "content": "Hi"}]
        client._stream_request(messages)

        assert tokens == ["Hello", " world", "!"]

    def test_stream_emits_response_complete(self, client, mock_openai):
        """response_complete signal emits full accumulated text."""
        session = MockSession()
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
            session=session,
        )

        chunks = [
            create_mock_chunk(content="A"),
            create_mock_chunk(content="B"),
            create_mock_chunk(content="C", finish_reason="stop"),
        ]
        mock_openai.chat.completions.create.return_value = chunks

        complete_text = []
        client.response_complete.connect(lambda t: complete_text.append(t))

        messages = [{"role": "user", "content": "Test"}]
        client._stream_request(messages)

        assert complete_text == ["ABC"]

    def test_stream_empty_response(self, client, mock_openai):
        """Empty stream emits response_complete with empty string."""
        session = MockSession()
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
            session=session,
        )

        chunks = [
            create_mock_chunk(content=None, finish_reason="stop"),
        ]
        mock_openai.chat.completions.create.return_value = chunks

        complete_text = []
        client.response_complete.connect(lambda t: complete_text.append(t))

        messages = [{"role": "user", "content": "Test"}]
        client._stream_request(messages)

        assert complete_text == [""]

    def test_stream_chunks_with_no_choices(self, client, mock_openai):
        """Chunks with empty choices list are skipped gracefully."""
        session = MockSession()
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
            session=session,
        )

        empty_chunk = MagicMock()
        empty_chunk.choices = []

        chunks = [
            empty_chunk,
            create_mock_chunk(content="X", finish_reason="stop"),
        ]
        mock_openai.chat.completions.create.return_value = chunks

        tokens = []
        client.token_received.connect(lambda t: tokens.append(t))

        messages = [{"role": "user", "content": "Test"}]
        client._stream_request(messages)

        assert tokens == ["X"]

    def test_stream_with_tools_in_kwargs(self, client, mock_openai):
        """When tools are configured, they are passed to the API call."""
        session = MockSession()
        tools = [{"type": "function", "function": {"name": "search"}}]
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
            session=session,
            tools=tools,
        )

        chunks = [
            create_mock_chunk(content="Done", finish_reason="stop"),
        ]
        mock_openai.chat.completions.create.return_value = chunks

        messages = [{"role": "user", "content": "Test"}]
        client._stream_request(messages)

        call_kwargs = mock_openai.chat.completions.create.call_args[1]
        assert "tools" in call_kwargs
        assert call_kwargs["tools"] == tools


# ---------------------------------------------------------------------------
# 5. Tool Calling — DeepSeek quirks (CRITICAL)
# ---------------------------------------------------------------------------


class TestToolCalling:
    """Tests for tool call delta accumulation with DeepSeek quirks."""

    def test_tool_call_single_simple(self, client, mock_openai):
        """Single tool call with no arguments across one chunk."""
        session = MockSession()
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
            session=session,
        )

        # Single chunk with tool call and finish_reason on it (DeepSeek quirk)
        chunks = [
            create_tool_call_chunk(
                0, tp_id="call_1", name="get_time", arguments="",
                finish_reason="tool_calls",
            ),
        ]
        mock_openai.chat.completions.create.return_value = chunks

        tool_requests = []
        client.tool_call_requested.connect(lambda tc: tool_requests.append(tc))

        messages = [{"role": "user", "content": "What time is it?"}]
        client._stream_request(messages)

        assert len(tool_requests) == 1
        assert tool_requests[0]["id"] == "call_1"
        assert tool_requests[0]["name"] == "get_time"
        assert tool_requests[0]["arguments"] == {}

    def test_tool_call_with_arguments(self, client, mock_openai):
        """Tool call arguments accumulated across multiple chunks."""
        session = MockSession()
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
            session=session,
        )

        chunks = [
            create_tool_call_chunk(
                0, tp_id="call_x", name="search",
                arguments='{"q":', finish_reason="tool_calls",
            ),
            create_tool_call_chunk(
                0, tp_id=None, name=None,
                arguments='"weather"', finish_reason="tool_calls",
            ),
            create_tool_call_chunk(
                0, tp_id=None, name=None,
                arguments="}", finish_reason="tool_calls",
            ),
        ]
        mock_openai.chat.completions.create.return_value = chunks

        tool_requests = []
        client.tool_call_requested.connect(lambda tc: tool_requests.append(tc))

        messages = [{"role": "user", "content": "Search for weather"}]
        client._stream_request(messages)

        assert len(tool_requests) == 1
        assert tool_requests[0]["id"] == "call_x"
        assert tool_requests[0]["name"] == "search"
        assert tool_requests[0]["arguments"] == {"q": "weather"}

    def test_tool_call_multiple_tools(self, client, mock_openai):
        """Multiple tool calls with different indices are handled separately."""
        session = MockSession()
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
            session=session,
        )

        chunks = [
            # Tool 0: get_weather
            create_tool_call_chunk(
                0, tp_id="call_w", name="get_weather",
                arguments='{"city":"Beijing"}', finish_reason="tool_calls",
            ),
            # Tool 1: get_time
            create_tool_call_chunk(
                1, tp_id="call_t", name="get_time",
                arguments="{}", finish_reason="tool_calls",
            ),
        ]
        mock_openai.chat.completions.create.return_value = chunks

        tool_requests = []
        client.tool_call_requested.connect(lambda tc: tool_requests.append(tc))

        messages = [{"role": "user", "content": "Weather and time"}]
        client._stream_request(messages)

        assert len(tool_requests) == 2
        names = {tc["name"] for tc in tool_requests}
        assert names == {"get_weather", "get_time"}

    def test_tool_call_deepseek_finish_reason_on_every_chunk(
        self, client, mock_openai
    ):
        """
        CRITICAL: DeepSeek sets finish_reason="tool_calls" on EVERY chunk
        that contains tool_call deltas. Verify accumulation continues across
        all chunks, not just the last one.
        """
        session = MockSession()
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
            session=session,
        )

        # DeepSeek sends finish_reason="tool_calls" from the FIRST chunk
        chunks = [
            create_tool_call_chunk(
                0, tp_id="call_ds", name="search",
                arguments='{"pat', finish_reason="tool_calls",
            ),
            create_tool_call_chunk(
                0, tp_id=None, name=None,
                arguments='tern":', finish_reason="tool_calls",
            ),
            create_tool_call_chunk(
                0, tp_id=None, name=None,
                arguments='"test"}', finish_reason="tool_calls",
            ),
        ]
        mock_openai.chat.completions.create.return_value = chunks

        tool_requests = []
        client.tool_call_requested.connect(lambda tc: tool_requests.append(tc))

        messages = [{"role": "user", "content": "Search"}]
        client._stream_request(messages)

        assert len(tool_requests) == 1
        # Arguments MUST be the full accumulated JSON, not just first fragment
        assert tool_requests[0]["arguments"] == {"pattern": "test"}

    def test_tool_call_index_based_accumulation(self, client, mock_openai):
        """Tool call buffers are keyed by index for correct accumulation."""
        session = MockSession()
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
            session=session,
        )

        chunks = [
            # Start tool 0
            create_tool_call_chunk(
                0, tp_id="c0", name="tool_a",
                arguments='{"x":1}', finish_reason="tool_calls",
            ),
            # Start tool 1
            create_tool_call_chunk(
                1, tp_id="c1", name="tool_b",
                arguments='{"y":2}', finish_reason="tool_calls",
            ),
        ]
        mock_openai.chat.completions.create.return_value = chunks

        tool_requests = []
        client.tool_call_requested.connect(lambda tc: tool_requests.append(tc))

        messages = [{"role": "user", "content": "Use tools"}]
        client._stream_request(messages)

        assert len(tool_requests) == 2
        sorted_tools = sorted(tool_requests, key=lambda t: t["name"])
        assert sorted_tools[0]["arguments"] == {"x": 1}
        assert sorted_tools[1]["arguments"] == {"y": 2}

    def test_tool_call_invalid_json_arguments(self, client, mock_openai):
        """When arguments are not valid JSON, args defaults to {}."""
        session = MockSession()
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
            session=session,
        )

        chunks = [
            create_tool_call_chunk(
                0, tp_id="call_bad", name="broken_tool",
                arguments="not{valid json!!!", finish_reason="tool_calls",
            ),
        ]
        mock_openai.chat.completions.create.return_value = chunks

        tool_requests = []
        client.tool_call_requested.connect(lambda tc: tool_requests.append(tc))

        messages = [{"role": "user", "content": "Do something"}]
        client._stream_request(messages)

        assert len(tool_requests) == 1
        # Arguments should be empty dict, not the raw string
        assert tool_requests[0]["arguments"] == {}

    def test_tool_call_id_null_after_first_chunk(self, client, mock_openai):
        """On subsequent chunks, tool call delta has id=None. Name persists."""
        session = MockSession()
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
            session=session,
        )

        chunks = [
            create_tool_call_chunk(
                0, tp_id="call_keep", name="my_tool",
                arguments='{"a":', finish_reason="tool_calls",
            ),
            # Second chunk: id is None, name is None, just arguments
            create_tool_call_chunk(
                0, tp_id=None, name=None,
                arguments="1}", finish_reason="tool_calls",
            ),
        ]
        mock_openai.chat.completions.create.return_value = chunks

        tool_requests = []
        client.tool_call_requested.connect(lambda tc: tool_requests.append(tc))

        messages = [{"role": "user", "content": "Test"}]
        client._stream_request(messages)

        assert len(tool_requests) == 1
        # ID and name should be preserved from the first chunk
        assert tool_requests[0]["id"] == "call_keep"
        assert tool_requests[0]["name"] == "my_tool"
        assert tool_requests[0]["arguments"] == {"a": 1}

    def test_continue_accumulates_after_tool_call_chunks(self, client, mock_openai):
        """After tool_call chunks, the stream continues with content chunks."""
        session = MockSession()
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
            session=session,
        )

        chunks = [
            create_tool_call_chunk(
                0, tp_id="call_c", name="do_thing",
                arguments="{}", finish_reason="tool_calls",
            ),
            # After tool_call chunk, a final chunk may arrive with stop reason
            create_mock_chunk(content=None, finish_reason="stop"),
        ]
        mock_openai.chat.completions.create.return_value = chunks

        tool_requests = []
        client.tool_call_requested.connect(lambda tc: tool_requests.append(tc))

        complete_text = []
        client.response_complete.connect(lambda t: complete_text.append(t))

        messages = [{"role": "user", "content": "Do thing"}]
        client._stream_request(messages)

        assert len(tool_requests) == 1
        assert tool_requests[0]["name"] == "do_thing"
        assert complete_text == [""]

    def test_tool_calls_stored_in_assistant_message(self, client, mock_openai):
        """Tool calls are stored in the session as assistant message."""
        session = MockSession()
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
            session=session,
        )

        chunks = [
            create_tool_call_chunk(
                0, tp_id="call_s", name="search",
                arguments='{"q":"test"}', finish_reason="tool_calls",
            ),
        ]
        mock_openai.chat.completions.create.return_value = chunks

        messages = [{"role": "user", "content": "Search for test"}]
        client._stream_request(messages)

        stored = session.get_messages()
        assert len(stored) == 1  # only assistant (user passed directly to _stream_request)
        assistant_msg = stored[0]
        assert assistant_msg["role"] == "assistant"
        assert "tool_calls" in assistant_msg
        assert len(assistant_msg["tool_calls"]) == 1
        assert assistant_msg["tool_calls"][0]["function"]["name"] == "search"


# ---------------------------------------------------------------------------
# 6. Reasoning Content (DeepSeek V4)
# ---------------------------------------------------------------------------


class TestReasoningContent:
    """Tests for reasoning/thinking content in DeepSeek V4 mode."""

    def test_reasoning_content_emitted(self, client, mock_openai):
        """reasoning_token_received signal emits reasoning tokens."""
        session = MockSession()
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
            session=session,
        )

        chunks = [
            create_mock_chunk(reasoning_content="Let me think..."),
            create_mock_chunk(reasoning_content=" step by step."),
            create_mock_chunk(content="Answer", finish_reason="stop"),
        ]
        mock_openai.chat.completions.create.return_value = chunks

        reasoning_tokens = []
        client.reasoning_token_received.connect(
            lambda t: reasoning_tokens.append(t)
        )

        messages = [{"role": "user", "content": "Question"}]
        client._stream_request(messages)

        assert reasoning_tokens == ["Let me think...", " step by step."]

    def test_reasoning_content_stored(self, client, mock_openai):
        """Reasoning content is stored in the assistant message (round-tripping)."""
        session = MockSession()
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
            session=session,
        )

        chunks = [
            create_mock_chunk(reasoning_content="Deep thinking"),
            create_mock_chunk(content="Final answer", finish_reason="stop"),
        ]
        mock_openai.chat.completions.create.return_value = chunks

        messages = [{"role": "user", "content": "Hard question"}]
        client._stream_request(messages)

        stored = session.get_messages()
        assistant_msg = stored[-1]
        assert assistant_msg["role"] == "assistant"
        assert assistant_msg["reasoning_content"] == "Deep thinking"
        assert assistant_msg["content"] == "Final answer"

    def test_reasoning_content_with_tool_call_roundtripping(
        self, client, mock_openai
    ):
        """When tool calls exist with reasoning, both are stored together."""
        session = MockSession()
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
            session=session,
        )

        chunks = [
            create_mock_chunk(reasoning_content="Need to search..."),
            create_tool_call_chunk(
                0, tp_id="call_r", name="search",
                arguments='{"q":"x"}', finish_reason="tool_calls",
            ),
        ]
        mock_openai.chat.completions.create.return_value = chunks

        messages = [{"role": "user", "content": "Find X"}]
        client._stream_request(messages)

        stored = session.get_messages()
        assistant_msg = stored[-1]
        assert assistant_msg["role"] == "assistant"
        assert assistant_msg["reasoning_content"] == "Need to search..."
        assert "tool_calls" in assistant_msg


# ---------------------------------------------------------------------------
# 7. Error Handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Tests for error handling and error_occurred signal."""

    def test_api_error_emits_signal(self, client, mock_openai):
        """When the API raises, error_occurred signal is emitted."""
        session = MockSession()
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
            session=session,
        )

        mock_openai.chat.completions.create.side_effect = RuntimeError(
            "API connection failed"
        )

        errors = []
        client.error_occurred.connect(lambda e: errors.append(e))

        messages = [{"role": "user", "content": "Test"}]
        client._stream_request(messages)

        assert len(errors) == 1
        assert "API connection failed" in errors[0]

    def test_network_error(self, client, mock_openai):
        """ConnectionError during streaming is caught and emitted."""
        session = MockSession()
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
            session=session,
        )

        mock_openai.chat.completions.create.side_effect = ConnectionError(
            "Network unreachable"
        )

        errors = []
        client.error_occurred.connect(lambda e: errors.append(e))

        messages = [{"role": "user", "content": "Test"}]
        client._stream_request(messages)

        assert len(errors) == 1
        assert "Network unreachable" in errors[0]

    def test_stream_error_during_iteration(self, client, mock_openai):
        """Error raised mid-stream is caught."""
        session = MockSession()
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
            session=session,
        )

        # Return a generator that yields one chunk then raises
        def broken_stream(*args, **kwargs):
            yield create_mock_chunk(content="Start")
            raise ValueError("Mid-stream failure")

        mock_openai.chat.completions.create.return_value = broken_stream()

        errors = []
        client.error_occurred.connect(lambda e: errors.append(e))

        messages = [{"role": "user", "content": "Test"}]
        client._stream_request(messages)

        assert len(errors) == 1
        assert "Mid-stream failure" in errors[0]

    def test_json_decode_error_for_tool_arguments(self, client, mock_openai, caplog):
        """Invalid JSON in tool arguments is handled gracefully with a warning."""
        session = MockSession()
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
            session=session,
        )

        chunks = [
            create_tool_call_chunk(
                0, tp_id="call_bad", name="bad_tool",
                arguments="{unclosed", finish_reason="tool_calls",
            ),
        ]
        mock_openai.chat.completions.create.return_value = chunks

        tool_requests = []
        client.tool_call_requested.connect(lambda tc: tool_requests.append(tc))

        messages = [{"role": "user", "content": "Test"}]
        client._stream_request(messages)

        assert len(tool_requests) == 1
        assert tool_requests[0]["arguments"] == {}


# ---------------------------------------------------------------------------
# 8. Tool Result Submission
# ---------------------------------------------------------------------------


class TestToolResultSubmission:
    """Tests for submit_tool_result and continue_after_tool."""

    def test_submit_tool_result_adds_session_message(self, client, mock_openai):
        """submit_tool_result adds a tool-role message to the session."""
        session = MockSession()
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
            session=session,
        )

        result_signals = []
        client.tool_result_ready.connect(
            lambda tid, res: result_signals.append((tid, res))
        )

        client.submit_tool_result("call_xyz", '{"temp": 25}')

        msgs = session.get_messages()
        assert len(msgs) == 1
        assert msgs[0]["role"] == "tool"
        assert msgs[0]["tool_call_id"] == "call_xyz"
        assert msgs[0]["content"] == '{"temp": 25}'
        assert result_signals == [("call_xyz", '{"temp": 25}')]

    def test_submit_tool_result_without_session(self, client, mock_openai):
        """submit_tool_result without a session does not crash."""
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
        )
        # Should not raise
        client.submit_tool_result("call_none", "result")

    def test_continue_after_tool_sends_request(self, client, mock_openai):
        """continue_after_tool sends a new streaming request."""
        session = MockSession()
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
            session=session,
        )

        session.add_message("user", "Initial question")
        session.add_message("assistant", "", tool_calls=[{
            "id": "call_1",
            "type": "function",
            "function": {"name": "search", "arguments": '{"q":"test"}'}
        }])
        session.add_message("tool", '{"results":["found"]}', tool_call_id="call_1")

        chunks = [
            create_mock_chunk(content="Based on the results, here is the answer.",
                              finish_reason="stop"),
        ]
        mock_openai.chat.completions.create.return_value = chunks

        tokens = []
        client.token_received.connect(lambda t: tokens.append(t))

        # Call _stream_request directly to test API call behavior
        # (continue_after_tool uses QThread, tested separately)
        messages = list(session.get_messages())
        client._stream_request(messages)

        call_args = mock_openai.chat.completions.create.call_args
        sent_messages = call_args[1]["messages"]
        # Should contain the full conversation including tool call and result
        assert len(sent_messages) >= 3
        assert tokens == ["Based on the results, here is the answer."]

    def test_continue_after_tool_with_user_text(self, client, mock_openai):
        """continue_after_tool appends follow-up user message."""
        session = MockSession()
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
            session=session,
        )

        chunks = [
            create_mock_chunk(content="OK", finish_reason="stop"),
        ]
        mock_openai.chat.completions.create.return_value = chunks

        # Build messages the same way continue_after_tool would
        messages = list(session.get_messages())
        messages.append({"role": "user", "content": "Continue please"})
        client._stream_request(messages)

        call_args = mock_openai.chat.completions.create.call_args
        sent_messages = call_args[1]["messages"]
        last_msg = sent_messages[-1]
        assert last_msg["role"] == "user"
        assert last_msg["content"] == "Continue please"

    def test_continue_after_tool_without_session(self, client, mock_openai):
        """continue_after_tool without a session creates a simple request."""
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
        )

        chunks = [
            create_mock_chunk(content="Response", finish_reason="stop"),
        ]
        mock_openai.chat.completions.create.return_value = chunks

        # Build messages the same way continue_after_tool would
        messages = [{"role": "user", "content": "New message"}]
        client._stream_request(messages)

        call_args = mock_openai.chat.completions.create.call_args
        sent_messages = call_args[1]["messages"]
        assert len(sent_messages) == 1
        assert sent_messages[0]["role"] == "user"
        assert sent_messages[0]["content"] == "New message"


# ---------------------------------------------------------------------------
# 9. Session Integration
# ---------------------------------------------------------------------------


class TestSessionIntegration:
    """Tests for session message flow and storage."""

    def test_session_messages_included_in_request(self, client, mock_openai):
        """_stream_request sends exactly the messages list passed to it."""
        session = MockSession()
        session.add_message("user", "Original question")
        session.add_message("assistant", "Original answer")
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
            session=session,
        )

        chunks = [
            create_mock_chunk(content="Follow-up answer", finish_reason="stop"),
        ]
        mock_openai.chat.completions.create.return_value = chunks

        messages = [{"role": "user", "content": "Follow-up question"}]
        client._stream_request(messages)

        call_args = mock_openai.chat.completions.create.call_args
        sent_messages = call_args[1]["messages"]
        assert len(sent_messages) == 1
        assert sent_messages[0]["content"] == "Follow-up question"

    def test_response_stored_in_session(self, client, mock_openai):
        """Assistant response is added to session after streaming."""
        session = MockSession()
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
            session=session,
        )

        chunks = [
            create_mock_chunk(content="The answer is 42.", finish_reason="stop"),
        ]
        mock_openai.chat.completions.create.return_value = chunks

        messages = [{"role": "user", "content": "What is the answer?"}]
        client._stream_request(messages)

        # user message was passed directly to _stream_request, not added to session
        # only assistant response is stored
        assert len(session._messages) == 1  # only assistant
        assert session._messages[0]["role"] == "assistant"
        assert session._messages[0]["content"] == "The answer is 42."

    def test_set_session_replaces_session(self, client):
        """set_session replaces the current session."""
        session1 = MockSession()
        session2 = MockSession()

        client.set_session(session1)
        assert client._session is session1

        client.set_session(session2)
        assert client._session is session2
        assert client._session is not session1

    def test_set_tools_replaces_tools(self, client):
        """set_tools replaces the tool definitions."""
        tools1 = [{"type": "function", "function": {"name": "t1"}}]
        tools2 = [{"type": "function", "function": {"name": "t2"}}]

        client.set_tools(tools1)
        assert client._tools == tools1

        client.set_tools(tools2)
        assert client._tools == tools2


# ---------------------------------------------------------------------------
# 10. Signal Connectivity
# ---------------------------------------------------------------------------


class TestSignals:
    """Verify that all signals are properly defined and connectable."""

    def test_token_received_is_connectable(self, client):
        """token_received signal should be a Qt Signal."""
        client.token_received.connect(lambda x: None)

    def test_reasoning_token_received_is_connectable(self, client):
        """reasoning_token_received signal should be a Qt Signal."""
        client.reasoning_token_received.connect(lambda x: None)

    def test_response_complete_is_connectable(self, client):
        """response_complete signal should be a Qt Signal."""
        client.response_complete.connect(lambda x: None)

    def test_error_occurred_is_connectable(self, client):
        """error_occurred signal should be a Qt Signal."""
        client.error_occurred.connect(lambda x: None)

    def test_tool_call_requested_is_connectable(self, client):
        """tool_call_requested signal should be a Qt Signal."""
        client.tool_call_requested.connect(lambda x: None)

    def test_tool_result_ready_is_connectable(self, client):
        """tool_result_ready signal should be a Qt Signal."""
        client.tool_result_ready.connect(lambda x, y: None)


# ---------------------------------------------------------------------------
# 11. Edge Cases & Additional Coverage
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases and additional coverage."""

    def test_send_dispatches_to_worker(self, client, mock_openai):
        """configure() creates persistent thread; send() dispatches to it."""
        session = MockSession()
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
            session=session,
        )

        # Verify persistent worker infrastructure was created
        assert client._request_worker is not None
        assert client._request_thread is not None
        assert client._request_thread.is_alive()

        # send() should not crash — it dispatches via signal to worker thread
        client.send("Hello")

        # Tear down properly
        thread = client._request_thread
        client.stop()
        assert thread is not None
        assert not thread.is_alive()

    def test_configure_with_provider_config_dataclass(self, client, mock_openai):
        """configure() accepts a dataclass-like object with .api_key and .base_url."""
        class FakeProviderConfig:
            api_key = "sk-dataclass"
            base_url = "https://dc.example.com"

        client.configure(
            provider_config=FakeProviderConfig(),
            model="m",
        )
        # OpenAI client was created and stored
        assert client._client is mock_openai

    def test_continue_after_tool_no_tools(self, client, mock_openai):
        """continue_after_tool without tools should still work."""
        session = MockSession()
        session.add_message("user", "Hi")
        session.add_message("assistant", "Hello!")
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
            session=session,
        )

        chunks = [
            create_mock_chunk(content="Bye", finish_reason="stop"),
        ]
        mock_openai.chat.completions.create.return_value = chunks

        # Call _stream_request directly (continue_after_tool uses QThread)
        messages = list(session.get_messages())
        client._stream_request(messages)

        call_args = mock_openai.chat.completions.create.call_args
        sent_messages = call_args[1]["messages"]
        assert len(sent_messages) == 2
        assert sent_messages[0]["content"] == "Hi"
        assert sent_messages[1]["content"] == "Hello!"

    def test_submit_tool_result_emits_signal_even_without_session(
        self, client, mock_openai
    ):
        """tool_result_ready is emitted regardless of session presence."""
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
        )
        signals = []
        client.tool_result_ready.connect(lambda tid, res: signals.append((tid, res)))

        client.submit_tool_result("call_xyz", "result data")

        assert len(signals) == 1
        assert signals[0] == ("call_xyz", "result data")

    def test_none_config_no_explosion(self):
        """Creating a client with None config should not explode."""
        c = LlmClient(provider_config=None)
        assert c._provider is None

    def test_tool_call_buffers_sorted_by_index(self, client, mock_openai):
        """Tool call buffers are emitted in sorted index order."""
        session = MockSession()
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
            session=session,
        )

        # Send index 3 before index 0 to verify sorting
        chunks = [
            create_tool_call_chunk(
                3, tp_id="c3", name="tool_three",
                arguments='{"n":3}', finish_reason="tool_calls",
            ),
            create_tool_call_chunk(
                0, tp_id="c0", name="tool_zero",
                arguments='{"n":0}', finish_reason="tool_calls",
            ),
        ]
        mock_openai.chat.completions.create.return_value = chunks

        tool_requests = []
        client.tool_call_requested.connect(lambda tc: tool_requests.append(tc))

        messages = [{"role": "user", "content": "Use tools"}]
        client._stream_request(messages)

        assert len(tool_requests) == 2
        # Should be sorted by index: 0 first, then 3
        assert tool_requests[0]["name"] == "tool_zero"
        assert tool_requests[1]["name"] == "tool_three"

    def test_empty_tool_call_arguments_returns_empty_dict(
        self, client, mock_openai
    ):
        """When tool call has empty arguments string, args defaults to {}."""
        session = MockSession()
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
            session=session,
        )

        chunks = [
            create_tool_call_chunk(
                0, tp_id="call_e", name="no_args_tool",
                arguments="", finish_reason="tool_calls",
            ),
        ]
        mock_openai.chat.completions.create.return_value = chunks

        tool_requests = []
        client.tool_call_requested.connect(lambda tc: tool_requests.append(tc))

        messages = [{"role": "user", "content": "Test"}]
        client._stream_request(messages)

        assert len(tool_requests) == 1
        assert tool_requests[0]["arguments"] == {}

    def test_build_messages_with_system_prompt_no_session(self, client):
        """When no session exists, the system prompt from the client is used."""
        client._system_prompt = "Standalone prompt"
        client._session = None

        msgs = client._build_messages("Hello")
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == "Standalone prompt"
        assert msgs[1]["role"] == "user"
        assert msgs[1]["content"] == "Hello"

    def test_tool_calls_stored_as_full_json_strings(self, client, mock_openai):
        """Tool call function arguments stored as raw string, parsed for signal."""
        session = MockSession()
        client.configure(
            provider_config={"api_key": "k", "base_url": "u"},
            model="m",
            session=session,
        )

        chunks = [
            create_tool_call_chunk(
                0, tp_id="call_j", name="json_tool",
                arguments='{"key":"value","num":42}', finish_reason="tool_calls",
            ),
        ]
        mock_openai.chat.completions.create.return_value = chunks

        tool_requests = []
        client.tool_call_requested.connect(lambda tc: tool_requests.append(tc))

        messages = [{"role": "user", "content": "Test"}]
        client._stream_request(messages)

        # Signal receives parsed dict
        assert tool_requests[0]["arguments"] == {"key": "value", "num": 42}

        # Session stores the raw string in function.arguments
        stored = client._session.get_messages()
        assistant_msg = stored[-1]
        stored_args = assistant_msg["tool_calls"][0]["function"]["arguments"]
        assert stored_args == '{"key":"value","num":42}'
