"""Conversation session management with token counting and compression."""

import json
import logging

import tiktoken

logger = logging.getLogger(__name__)

# Default: use cl100k_base encoding (GPT-4/DeepSeek compatible)
DEFAULT_ENCODING = "cl100k_base"


class ConversationSession:
    """Manages LLM conversation history with token-aware compression.

    Maintains a message list following OpenAI chat format.
    Tracks token count and compresses old messages when at 70% of context window.
    """

    def __init__(self, context_size: int = 1048576, encoding_name: str = DEFAULT_ENCODING):
        """Initialize conversation session.

        Args:
            context_size: Maximum context window in tokens (default: 1M for DeepSeek V4)
            encoding_name: tiktoken encoding name
        """
        self._context_size = context_size
        self._messages: list[dict[str, object]] = []
        self._encoding = tiktoken.get_encoding(encoding_name)
        self._system_message: dict[str, object] | None = None
        self._compression_threshold = 0.7  # 70% threshold
        # Store the summary of compressed messages
        self._compressed_summary: str | None = None

    def set_system_message(self, content: str):
        """Set the system message (always kept at start of conversation)."""
        self._system_message = {"role": "system", "content": content}

    def add_message(
        self,
        role: str,
        content: str | list,
        tool_calls: list | None = None,
        tool_call_id: str | None = None,
        reasoning_content: str | None = None,
    ):
        """Add a message to the conversation.

        Args:
            role: Message role ("user", "assistant", "tool")
            content: Message content (string or list for vision messages)
            tool_calls: Tool calls from assistant (list of dicts)
            tool_call_id: Tool call ID for tool role messages
            reasoning_content: Thinking content (DeepSeek V4 reasoning mode)
        """
        message: dict[str, object] = {"role": role}

        if content:
            message["content"] = content

        if tool_calls:
            message["tool_calls"] = tool_calls

        if tool_call_id:
            message["tool_call_id"] = tool_call_id

        if reasoning_content:
            # Store reasoning content as a custom field
            # DeepSeek requires this for tool call round-tripping
            message["reasoning_content"] = reasoning_content

        self._messages.append(message)

    def get_messages(self) -> list[dict]:
        """Get the full message list for API call.

        Returns system message (if set) followed by conversation messages.
        If compression has occurred, a summary system message is prepended.
        """
        messages = []

        # Add original system message if present
        if self._system_message:
            if self._compressed_summary:
                # Append compressed summary to system message
                system_msg = dict(self._system_message)
                system_msg["content"] = (
                    f"{system_msg['content']}\n\n[Previous conversation summary: "
                    f"{self._compressed_summary}]"
                )
                messages.append(system_msg)
            else:
                messages.append(dict(self._system_message))
        elif self._compressed_summary:
            # No system message but we have compressed summary
            messages.append(
                {
                    "role": "system",
                    "content": f"[Previous conversation summary: {self._compressed_summary}]",
                }
            )

        messages.extend(self._messages)
        return messages

    def token_count(self) -> int:
        """Count total tokens in all messages (approximate).

        Uses tiktoken encoding. For multimodal content, only text parts are counted.
        Each message has ~4 tokens overhead for role formatting.
        """
        total = 0
        all_messages = self.get_messages()

        for msg in all_messages:
            # Message formatting overhead (~4 tokens per message)
            total += 4

            for key, value in msg.items():
                if key == "content":
                    if isinstance(value, str):
                        total += len(self._encoding.encode(value))
                    elif isinstance(value, list):
                        # Vision message: content is a list of parts
                        for part in value:
                            if isinstance(part, dict) and part.get("type") == "text":
                                total += len(self._encoding.encode(part.get("text", "")))
                            # image_url parts: approximate token cost
                            elif isinstance(part, dict) and part.get("type") == "image_url":
                                total += 185  # approximate overhead per image
                elif key == "tool_calls":
                    # Tool calls contribute to token count via JSON serialization
                    text = json.dumps(value, ensure_ascii=False)
                    total += len(self._encoding.encode(text))
                elif key == "reasoning_content" and isinstance(value, str):
                    total += len(self._encoding.encode(value))

        return total

    def needs_compression(self) -> bool:
        """Check if token count exceeds 70% of context window."""
        return self.token_count() > int(self._context_size * self._compression_threshold)

    def compress(self) -> str:
        """Compress oldest messages into a summary.

        Returns a summary string of compressed messages.
        This does NOT call the LLM — it creates a text summary by extracting
        key information from older messages. The actual LLM-based compression
        is handled externally (the caller provides the summary).

        Strategy:
        1. Keep the most recent messages (last ~30% of context)
        2. Summarize older messages into a compressed block
        3. Store summary in _compressed_summary
        """
        if not self._messages:
            return ""

        # Calculate how many messages to keep (aim for ~30% of context)
        target_tokens = int(self._context_size * 0.3)
        kept_messages = []
        kept_tokens = 0

        # Keep messages from newest to oldest until we hit the target
        for msg in reversed(self._messages):
            msg_tokens = self._estimate_message_tokens(msg)
            if kept_tokens + msg_tokens > target_tokens and kept_messages:
                break
            kept_messages.insert(0, msg)
            kept_tokens += msg_tokens

        # Oldest messages are what we compress
        oldest_count = len(self._messages) - len(kept_messages)
        if oldest_count == 0:
            return ""

        # Create a text summary of compressed messages
        summary_parts = []
        for msg in self._messages[:oldest_count]:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, list):
                # Extract text from vision message parts
                text_parts = [
                    p.get("text", "")
                    for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                ]
                content = " ".join(text_parts)
            if isinstance(content, str) and content:
                summary_parts.append(f"[{role}]: {content[:200]}")

        summary = " | ".join(summary_parts) if summary_parts else ""

        # Replace messages with kept subset
        self._messages = kept_messages
        self._compressed_summary = summary

        logger.info(
            f"Compressed {oldest_count} messages, kept {len(kept_messages)}. "
            f"New token count: {self.token_count()}"
        )

        return summary

    def _estimate_message_tokens(self, msg: dict) -> int:
        """Quick token estimate for a single message."""
        content = msg.get("content", "")
        if isinstance(content, str):
            return len(self._encoding.encode(content)) + 4
        elif isinstance(content, list):
            total = 4
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    total += len(self._encoding.encode(part.get("text", "")))
                elif isinstance(part, dict) and part.get("type") == "image_url":
                    total += 185
            return total
        return 4

    def clear(self):
        """Clear all messages and compression state."""
        self._messages.clear()
        self._compressed_summary = None

    @property
    def message_count(self) -> int:
        """Number of messages in the session (excluding system)."""
        return len(self._messages)

    @property
    def context_size(self) -> int:
        """Maximum context window size."""
        return self._context_size

    @property
    def is_compressed(self) -> bool:
        """Whether compression has been performed."""
        return self._compressed_summary is not None
