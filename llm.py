"""LLM client with streaming, tool calling, and vision support."""

import base64
import io
import json
import logging
import queue
import threading

import numpy as np
from openai import OpenAI
from PIL import Image

from signals import Signal

logger = logging.getLogger(__name__)


class _LlmWorker:
    """Worker that executes streaming requests on a persistent thread.

    Runs on a dedicated background thread.  Receives message lists via an
    internal ``queue.Queue`` and calls ``LlmClient._stream_request()``
    synchronously on that thread.
    """

    def __init__(self, client: "LlmClient") -> None:
        self._client = client
        self._request_queue: queue.Queue = queue.Queue()

    def enqueue(self, messages: list[dict]) -> None:
        """Put a message batch into the request queue."""
        self._request_queue.put(messages)

    def run(self) -> None:
        """Block on the request queue forever; call _stream_request for each batch.

        A ``None`` sentinel signals clean shutdown.
        """
        while True:
            messages = self._request_queue.get()
            if messages is None:  # sentinel for shutdown
                break
            try:
                self._client._stream_request(messages)
            except Exception as e:
                logging.getLogger(__name__).error(
                    "LLM worker error: %s", e, exc_info=True
                )


class LlmClient:
    """LLM client for OpenAI-compatible APIs.

    Handles streaming responses, tool calling with delta accumulation,
    vision input (base64 images), and knowledge grep integration.

    Signals use :class:`~signals.Signal` and are thread-safe for cross-thread
    emission via ``safe_emit()``.

    Usage:
        client = LlmClient(config)
        client.token_received.connect(on_token)
        client.response_complete.connect(on_complete)
        client.error_occurred.connect(on_error)
        client.tool_call_requested.connect(on_tool_call)
        client.send("Hello", image=numpy_array)
    """

    def __init__(self, provider_config=None):
        """Initialize LLM client.

        Args:
            provider_config: ProviderConfig from config.py, or dict with
                           {name, api_key, base_url}
        """
        self._provider = provider_config
        self._client: OpenAI | None = None
        self._session = None  # ConversationSession, set externally
        self._system_prompt = ""
        self._current_model = ""
        self._tools: list[dict] = []

        # Streaming signals (instance-level, thread-safe via safe_emit)
        self.token_received = Signal()
        self.reasoning_token_received = Signal()
        self.response_complete = Signal()
        self.error_occurred = Signal()
        self.tool_call_requested = Signal()
        self.tool_result_ready = Signal()

        # Persistent worker thread (created in configure())
        self._request_thread: threading.Thread | None = None
        self._request_worker: _LlmWorker | None = None

    def configure(
        self,
        provider_config,
        system_prompt: str = "",
        model: str = "",
        session=None,
        tools: list[dict] | None = None,
    ):
        """Configure or reconfigure the client.

        Args:
            provider_config: ProviderConfig or dict with api_key, base_url
            system_prompt: System prompt string
            model: Model name to use
            session: ConversationSession instance
            tools: List of tool definitions (OpenAI format)
        """
        self._provider = provider_config
        self._system_prompt = system_prompt
        self._current_model = model

        if session is not None:
            self._session = session
            if system_prompt:
                self._session.set_system_message(system_prompt)

        if tools is not None:
            self._tools = tools

        # Create OpenAI client
        api_key = (
            provider_config.api_key
            if hasattr(provider_config, "api_key")
            else provider_config.get("api_key", "")
        )
        base_url = (
            provider_config.base_url
            if hasattr(provider_config, "base_url")
            else provider_config.get("base_url", "")
        )

        self._client = OpenAI(api_key=api_key, base_url=base_url)

        # --- Persistent worker thread ---------------------------------------
        # A single thread processes all requests sequentially, avoiding the
        # "QThread: Destroyed while thread is still running" crash that occurs
        # when ad-hoc threads are overwritten without cleanup.
        self._request_worker = _LlmWorker(self)
        self._request_thread = threading.Thread(
            target=self._request_worker.run, daemon=True
        )
        self._request_thread.start()

    def send(
        self,
        user_text: str,
        image: np.ndarray | None = None,
        system_prompt_override: str | None = None,
    ):
        """Send a message to the LLM.

        Dispatches to the persistent worker thread via queue.

        Args:
            user_text: User's text input
            image: Optional numpy array (H,W,3) of screenshot for vision
            system_prompt_override: Override system prompt for this request
        """
        messages = self._build_messages(user_text, image, system_prompt_override)

        # Save user message to session so tool-call continuations
        # (``continue_after_tool``) include the original user prompt.
        if self._session:
            if image is not None:
                img_b64 = self._encode_image(image)
                self._session.add_message(
                    role="user",
                    content=[
                        {"type": "text", "text": user_text},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                        },
                    ],
                )
            else:
                self._session.add_message(role="user", content=user_text)

        if self._request_worker is not None:
            self._request_worker.enqueue(messages)

    def _build_messages(
        self,
        user_text: str,
        image: np.ndarray | None = None,
        system_prompt_override: str | None = None,
    ) -> list[dict]:
        """Build message list for API request.

        Combines session history with current user input.
        """
        messages: list[dict] = []

        # Add system prompt
        sp = system_prompt_override or self._system_prompt
        if sp and (not self._session or not self._session._system_message):
            messages.append({"role": "system", "content": sp})

        # Add session history
        if self._session:
            messages.extend(self._session.get_messages())

        # Build user content
        if image is not None:
            # Vision message: text + image
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{self._encode_image(image)}"},
                    },
                ],
            })
        else:
            messages.append({"role": "user", "content": user_text})

        return messages

    def _encode_image(self, image: np.ndarray) -> str:
        """Encode numpy image array to base64 PNG string.

        Args:
            image: numpy array (H, W, 3) in RGB format

        Returns:
            Base64-encoded PNG string
        """
        # Convert numpy to PIL
        if image.shape[2] == 3:
            pil_img = Image.fromarray(image)
        else:
            pil_img = Image.fromarray(image[:, :, :3])

        # Encode to PNG base64
        buffer = io.BytesIO()
        pil_img.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("utf-8")

    def _stream_request(self, messages: list[dict]):
        """Execute streaming API request (called on worker thread).

        Handles:
        - Regular content streaming
        - Thinking/reasoning content streaming (DeepSeek V4)
        - Tool call delta accumulation (with DeepSeek quirks)
        """
        try:
            tool_call_buffers: dict[int, dict] = {}
            tool_calls: list[dict] = []
            accumulated_content = ""
            accumulated_reasoning = ""
            finish_reason = None
            assistant_message: dict = {"role": "assistant", "content": None}

            kwargs: dict = {
                "model": self._current_model,
                "messages": messages,
                "stream": True,
            }

            if self._client is None:
                self.error_occurred.safe_emit("LLM client not configured. Call configure() first.")
                return

            if self._tools:
                kwargs["tools"] = self._tools

            stream = self._client.chat.completions.create(**kwargs)

            for chunk in stream:
                if not chunk.choices:
                    continue

                choice = chunk.choices[0]
                delta = choice.delta
                finish_reason = choice.finish_reason

                # Handle reasoning content (thinking mode)
                if getattr(delta, "reasoning_content", None):
                    accumulated_reasoning += delta.reasoning_content
                    self.reasoning_token_received.safe_emit(delta.reasoning_content)

                # Handle tool calls (with DeepSeek quirk handling)
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index if hasattr(tc, "index") else 0
                        if idx not in tool_call_buffers:
                            tool_call_buffers[idx] = {"id": None, "name": None, "arguments": ""}
                        if hasattr(tc, "id") and tc.id:
                            tool_call_buffers[idx]["id"] = tc.id
                        if hasattr(tc, "function"):
                            if tc.function.name:
                                tool_call_buffers[idx]["name"] = tc.function.name
                            if tc.function.arguments:
                                tool_call_buffers[idx]["arguments"] += tc.function.arguments

                    # IMPORTANT: DeepSeek sets finish_reason="tool_calls" on EVERY
                    # tool_call chunk. Do NOT stop here. Continue accumulating.
                    continue

                # Handle regular content
                if delta.content:
                    accumulated_content += delta.content
                    self.token_received.safe_emit(delta.content)

                # Check for stream end.
                # DeepSeek quirk: finish_reason may be "tool_calls" even when delta
                # has content (not tool_calls). The stream is effectively done when
                # delta has no tool_calls AND finish_reason is set.
                if finish_reason and not delta.tool_calls:
                    break

            # Process any accumulated tool calls
            if tool_call_buffers:
                for idx in sorted(tool_call_buffers.keys()):
                    buf = tool_call_buffers[idx]
                    if buf["name"]:
                        try:
                            args = json.loads(buf["arguments"]) if buf["arguments"] else {}
                        except json.JSONDecodeError:
                            logger.warning(
                                f"Tool call arguments not valid JSON: {buf['arguments']}"
                            )
                            args = {}

                        tool_call = {
                            "id": buf["id"],
                            "type": "function",
                            "function": {"name": buf["name"], "arguments": buf["arguments"]},
                        }
                        tool_calls.append(tool_call)

                        # Emit signal for each tool call
                        self.tool_call_requested.safe_emit(
                            {
                                "id": buf["id"],
                                "name": buf["name"],
                                "arguments": args,
                            }
                        )

                if tool_calls:
                    assistant_message["tool_calls"] = tool_calls

            # Store assistant response in session
            if accumulated_content:
                assistant_message["content"] = accumulated_content

            if accumulated_reasoning:
                assistant_message["reasoning_content"] = accumulated_reasoning

            if self._session and (accumulated_content or tool_calls):
                self._session.add_message(
                    role="assistant",
                    content=assistant_message.get("content"),
                    tool_calls=assistant_message.get("tool_calls"),
                    reasoning_content=assistant_message.get("reasoning_content"),
                )

            # Emit completion signal
            self.response_complete.safe_emit(accumulated_content)

        except Exception as e:
            logger.error(f"LLM request error: {e}", exc_info=True)
            self.error_occurred.safe_emit(str(e))

    def submit_tool_result(self, tool_call_id: str, result: str):
        """Submit a tool execution result back to the conversation.

        Args:
            tool_call_id: The tool call ID from the model
            result: String result of the tool execution
        """
        if self._session:
            self._session.add_message(
                role="tool",
                content=result,
                tool_call_id=tool_call_id,
            )

        self.tool_result_ready.emit(tool_call_id, result)

    def continue_after_tool(self, user_text: str = ""):
        """Continue the conversation after tool results have been submitted.

        Sends another request to let the model process tool results.
        Dispatched to the persistent worker thread.
        """
        if self._session:
            messages: list[dict] = list(self._session.get_messages())
        else:
            messages = []

        # Add a follow-up user message if provided
        if user_text:
            messages.append({"role": "user", "content": user_text})

        if self._request_worker:
            self._request_worker.enqueue(messages)

    def stop(self) -> None:
        """Stop the persistent worker thread and clean up."""
        if self._request_thread is not None and self._request_thread.is_alive():
            if self._request_worker is not None:
                self._request_worker._request_queue.put(None)  # sentinel
            self._request_thread.join(timeout=5)
            self._request_worker = None
            self._request_thread = None

    def set_session(self, session):
        """Set the conversation session."""
        self._session = session

    def set_tools(self, tools: list[dict]):
        """Set available tool definitions."""
        self._tools = tools
