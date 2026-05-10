"""Tests for the conversation session module."""

from session import ConversationSession


class TestInitialState:
    """Tests for session initialization and default state."""

    def test_initial_state(self) -> None:
        """Verify context_size, empty messages, no compression after init."""
        session = ConversationSession(context_size=1048576)
        assert session.context_size == 1048576
        assert session.message_count == 0
        assert not session.is_compressed
        assert session.get_messages() == []

    def test_custom_context_size(self) -> None:
        """Verify custom context_size is stored."""
        session = ConversationSession(context_size=8192)
        assert session.context_size == 8192


class TestAddMessage:
    """Tests for adding messages to the session."""

    def test_add_user_message(self) -> None:
        """Add a user message and verify it is stored in _messages."""
        session = ConversationSession()
        session.add_message("user", "Hello, world!")
        assert session.message_count == 1
        msgs = session.get_messages()
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "Hello, world!"

    def test_add_multiple_messages(self) -> None:
        """Add user + assistant + tool messages, verify all present."""
        session = ConversationSession()
        session.add_message("user", "What is 2+2?")
        session.add_message("assistant", "The answer is 4.")
        session.add_message("tool", "result: 4", tool_call_id="call_1")
        assert session.message_count == 3
        msgs = session.get_messages()
        assert len(msgs) == 3
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "What is 2+2?"
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["content"] == "The answer is 4."
        assert msgs[2]["role"] == "tool"
        assert msgs[2]["content"] == "result: 4"
        assert msgs[2]["tool_call_id"] == "call_1"

    def test_add_message_empty_content(self) -> None:
        """Adding a message with empty content should still store the role."""
        session = ConversationSession()
        session.add_message("assistant", "", tool_calls=[{"name": "do_stuff"}])
        assert session.message_count == 1
        msgs = session.get_messages()
        assert msgs[0]["role"] == "assistant"
        assert "content" not in msgs[0]
        assert msgs[0]["tool_calls"] == [{"name": "do_stuff"}]


class TestSystemMessage:
    """Tests for system message handling."""

    def test_set_system_message(self) -> None:
        """Set system message, verify it appears in get_messages() at start."""
        session = ConversationSession()
        session.set_system_message("You are a helpful assistant.")
        msgs = session.get_messages()
        assert len(msgs) == 1
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == "You are a helpful assistant."
        # System message should NOT count in message_count
        assert session.message_count == 0

    def test_get_messages_includes_system(self) -> None:
        """System message first, then conversation messages."""
        session = ConversationSession()
        session.set_system_message("System prompt here.")
        session.add_message("user", "User message here.")
        session.add_message("assistant", "Assistant reply here.")
        msgs = session.get_messages()
        assert len(msgs) == 3
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == "System prompt here."
        assert msgs[1]["role"] == "user"
        assert msgs[1]["content"] == "User message here."
        assert msgs[2]["role"] == "assistant"
        assert msgs[2]["content"] == "Assistant reply here."


class TestTokenCount:
    """Tests for token counting."""

    def test_token_count_positive(self) -> None:
        """Add text message, verify token_count() > 0."""
        session = ConversationSession()
        session.add_message("user", "Hello, this is a test message.")
        count = session.token_count()
        assert count > 0

    def test_token_count_increases(self) -> None:
        """Add messages, verify token count grows."""
        session = ConversationSession()
        session.add_message("user", "First message.")
        count1 = session.token_count()
        session.add_message("assistant", "Second message with more text content.")
        count2 = session.token_count()
        assert count2 > count1
        session.add_message("user", "A third message for good measure.")
        count3 = session.token_count()
        assert count3 > count2

    def test_token_count_overhead_per_message(self) -> None:
        """Each message adds ~4 tokens overhead."""
        session = ConversationSession()
        # An empty message should still have overhead
        session.add_message("user", "a")  # 1 token + 4 overhead
        count = session.token_count()
        assert count >= 4

    def test_token_count_with_tool_calls(self) -> None:
        """Tool calls contribute to token count via JSON serialization."""
        session = ConversationSession()
        session.add_message(
            "assistant",
            "Let me check.",
            tool_calls=[
                {"id": "call_1", "function": {"name": "search", "arguments": '{"q":"test"}'}}
            ],
        )
        count = session.token_count()
        assert count > 0

    def test_token_count_with_reasoning_content(self) -> None:
        """Reasoning content contributes to token count."""
        session = ConversationSession()
        session.add_message(
            "assistant",
            "The answer is 4.",
            reasoning_content="Let me think about this step by step...",
        )
        count = session.token_count()
        assert count > 0

    def test_token_count_with_system_message(self) -> None:
        """System message tokens are included in count."""
        session = ConversationSession()
        session.set_system_message("You are a helpful assistant who provides detailed answers.")
        session.add_message("user", "Hello!")
        count = session.token_count()
        assert count > 0


class TestNeedsCompression:
    """Tests for the compression threshold check."""

    def test_needs_compression_below_threshold(self) -> None:
        """With small messages, should return False."""
        session = ConversationSession(context_size=1048576)
        session.add_message("user", "Hello, world!")
        assert not session.needs_compression()

    def test_needs_compression_with_small_context(self) -> None:
        """Create session with tiny context (100 tokens), add enough text to
        exceed 70%, verify needs_compression() returns True."""
        session = ConversationSession(context_size=100)
        # 70% of 100 = 70 tokens threshold
        # Add enough text to exceed that
        session.add_message("user", "The quick brown fox jumps over the lazy dog. " * 10)
        assert session.needs_compression()

    def test_needs_compression_empty_session(self) -> None:
        """Empty session should not need compression."""
        session = ConversationSession(context_size=100)
        assert not session.needs_compression()


class TestCompress:
    """Tests for the compress() method."""

    def test_compress_reduces_message_count(self) -> None:
        """Add many messages, compress(), verify fewer messages remain."""
        session = ConversationSession(context_size=200)
        # Add many messages to fill up context
        for i in range(20):
            session.add_message(
                "user",
                f"Message number {i} with some extra text to fill tokens. " * 3,
            )
        original_count = session.message_count
        summary = session.compress()
        assert session.message_count < original_count
        assert summary != ""

    def test_compress_generates_summary(self) -> None:
        """compress(), verify _compressed_summary is set and is_compressed is True."""
        session = ConversationSession(context_size=200)
        for i in range(15):
            session.add_message("user", f"Message {i} with content. " * 5)
        session.compress()
        assert session.is_compressed

    def test_compress_no_messages(self) -> None:
        """Compress empty session returns empty string."""
        session = ConversationSession()
        result = session.compress()
        assert result == ""
        assert not session.is_compressed

    def test_compress_preserves_recent_messages(self) -> None:
        """After compression, the most recent messages should still be present."""
        session = ConversationSession(context_size=200)
        session.add_message("user", "old message 1 " * 10)
        session.add_message("assistant", "old message 2 " * 10)
        session.add_message("user", "old message 3 " * 10)
        session.add_message("assistant", "recent message " * 10)
        session.compress()
        msgs = session.get_messages()
        # The recent message should be among the kept ones
        contents = [m.get("content", "") for m in msgs]
        assert any("recent message" in str(c) for c in contents)

    def test_compress_all_messages_kept_when_under_target(self) -> None:
        """When total tokens are under the keep target, no messages are compressed."""
        session = ConversationSession(context_size=1048576)
        session.add_message("user", "Tiny message.")
        result = session.compress()
        assert result == ""
        assert session.message_count == 1

    def test_compression_summary_in_get_messages(self) -> None:
        """Compress, then get_messages() should include summary prefix."""
        session = ConversationSession(context_size=200)
        session.add_message("user", "First message with enough content to trigger compress. " * 10)
        session.add_message("assistant", "Second message also has content. " * 10)
        session.compress()
        msgs = session.get_messages()
        # With no system message, the first message should be a system message with the summary
        assert msgs[0]["role"] == "system"
        assert "Previous conversation summary" in msgs[0]["content"]

    def test_compression_summary_with_existing_system_message(self) -> None:
        """When a system message exists, compression appends summary to it."""
        session = ConversationSession(context_size=200)
        session.set_system_message("You are a helpful assistant.")
        session.add_message("user", "Enough content to need compression. " * 15)
        session.add_message("assistant", "More content here. " * 15)
        session.compress()
        msgs = session.get_messages()
        assert msgs[0]["role"] == "system"
        assert "You are a helpful assistant." in msgs[0]["content"]
        assert "Previous conversation summary" in msgs[0]["content"]


class TestToolCalls:
    """Tests for tool calls storage and retrieval."""

    def test_tool_calls_stored(self) -> None:
        """Add assistant message with tool_calls, verify stored and retrievable."""
        session = ConversationSession()
        tool_calls = [
            {
                "id": "call_abc123",
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "arguments": '{"location": "Beijing"}',
                },
            }
        ]
        session.add_message("assistant", "", tool_calls=tool_calls)
        msgs = session.get_messages()
        assert msgs[0]["tool_calls"] == tool_calls

    def test_tool_message_with_call_id(self) -> None:
        """Tool message with tool_call_id is stored correctly."""
        session = ConversationSession()
        session.add_message("tool", '{"temperature": 22}', tool_call_id="call_abc123")
        msgs = session.get_messages()
        assert msgs[0]["role"] == "tool"
        assert msgs[0]["tool_call_id"] == "call_abc123"
        assert msgs[0]["content"] == '{"temperature": 22}'

    def test_multiple_tool_calls(self) -> None:
        """Multiple tool calls in one message are all stored."""
        session = ConversationSession()
        tool_calls = [
            {"id": "call_1", "function": {"name": "search", "arguments": '{"q":"weather"}'}},
            {"id": "call_2", "function": {"name": "search", "arguments": '{"q":"time"}'}},
        ]
        session.add_message("assistant", "Using tools.", tool_calls=tool_calls)
        msgs = session.get_messages()
        assert len(msgs[0]["tool_calls"]) == 2


class TestReasoningContent:
    """Tests for DeepSeek V4 reasoning_content field."""

    def test_reasoning_content_stored(self) -> None:
        """Add message with reasoning_content (DeepSeek V4 mode)."""
        session = ConversationSession()
        reasoning = "Let me analyze this step by step. First, I need to..."
        session.add_message("assistant", "The answer is Paris.", reasoning_content=reasoning)
        msgs = session.get_messages()
        assert msgs[0]["reasoning_content"] == reasoning
        assert msgs[0]["content"] == "The answer is Paris."
        assert msgs[0]["role"] == "assistant"

    def test_reasoning_content_none_not_stored(self) -> None:
        """When reasoning_content is None, it should not be in the message dict."""
        session = ConversationSession()
        session.add_message("assistant", "Simple reply.")
        msgs = session.get_messages()
        assert "reasoning_content" not in msgs[0]


class TestVisionContent:
    """Tests for vision/multimodal message handling."""

    def test_vision_content_token_count(self) -> None:
        """Add message with image_url content, verify token count handles it."""
        session = ConversationSession()
        vision_content = [
            {"type": "text", "text": "What is in this image?"},
            {
                "type": "image_url",
                "image_url": {"url": "https://example.com/image.jpg"},
            },
        ]
        session.add_message("user", vision_content)
        count = session.token_count()
        # Should include text tokens + image overhead
        assert count > 0

    def test_vision_text_only_parts_counted(self) -> None:
        """Only text parts are fully tokenized; image_url parts get fixed overhead."""
        session = ConversationSession()
        vision_content = [
            {"type": "text", "text": "Describe this: "},
            {"type": "image_url", "image_url": {"url": "https://example.com/img.jpg"}},
        ]
        session.add_message("user", vision_content)
        count1 = session.token_count()

        # Adding more images should increase count
        vision_content2 = [
            {"type": "text", "text": "Describe this: "},
            {"type": "image_url", "image_url": {"url": "https://example.com/img1.jpg"}},
            {"type": "image_url", "image_url": {"url": "https://example.com/img2.jpg"}},
        ]
        session2 = ConversationSession()
        session2.add_message("user", vision_content2)
        count2 = session2.token_count()
        # More images = higher token count
        assert count2 > count1


class TestClear:
    """Tests for the clear() method."""

    def test_clear_resets_everything(self) -> None:
        """Add messages, clear(), verify empty."""
        session = ConversationSession()
        session.set_system_message("System prompt.")
        session.add_message("user", "Message 1")
        session.add_message("assistant", "Message 2")
        # Force compression so _compressed_summary is set
        session._compressed_summary = "Some summary"
        assert session.message_count == 2
        assert session.is_compressed

        session.clear()
        assert session.message_count == 0
        assert not session.is_compressed
        # System message is NOT cleared by clear()
        msgs = session.get_messages()
        assert len(msgs) == 1
        assert msgs[0]["role"] == "system"
        assert "Previous conversation summary" not in msgs[0]["content"]

    def test_clear_empty_session(self) -> None:
        """Clearing an already empty session is a no-op."""
        session = ConversationSession()
        session.clear()
        assert session.message_count == 0
        assert not session.is_compressed


class TestMessageCount:
    """Tests for the message_count property."""

    def test_message_count_zero_initially(self) -> None:
        """New session has zero messages."""
        session = ConversationSession()
        assert session.message_count == 0

    def test_message_count_excludes_system(self) -> None:
        """System message does not count toward message_count."""
        session = ConversationSession()
        session.set_system_message("System prompt.")
        assert session.message_count == 0
        session.add_message("user", "Hello.")
        assert session.message_count == 1

    def test_message_count_after_clear(self) -> None:
        """After clear(), message_count is zero."""
        session = ConversationSession()
        session.add_message("user", "Msg 1")
        session.add_message("assistant", "Msg 2")
        session.clear()
        assert session.message_count == 0
