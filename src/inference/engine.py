"""Inference engine for locally-hosted LLM via OpenAI-compatible API."""

import os
from collections.abc import Generator

from openai import OpenAI

from src.prompts.templates import SYSTEM_MESSAGE


class InferenceEngine:
    """Connects to a locally-hosted LLM exposed via an OpenAI-compatible API.

    Works with Ollama, vLLM, or any OpenAI-compatible endpoint.
    Default configuration targets vLLM serving DeepSeek V4.
    """

    def __init__(
        self,
        base_url: str = "http://10.0.0.10:8002/v1",
        model: str = "dsv4",
        api_key: str = "",
    ):
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        keep_alive = os.environ.get("OLLAMA_KEEP_ALIVE", "-1").strip()
        try:
            self.keep_alive = int(keep_alive)
        except ValueError:
            self.keep_alive = keep_alive
        # Ollama defaults num_ctx to 2048, which silently truncates long RAG
        # prompts. Set to 32K for headroom without blowing up VRAM.
        # On vLLM this is set at server start, not per-request.
        try:
            self.num_ctx = int(os.environ.get("OLLAMA_NUM_CTX", "32768"))
        except ValueError:
            self.num_ctx = 32768
        # Backend detection — Ollama-specific knobs (keep_alive, options.num_ctx)
        # are rejected by stricter OpenAI servers like vLLM. Heuristic on URL,
        # overridable via INFERENCE_BACKEND={ollama|vllm|other}.
        backend = os.environ.get("INFERENCE_BACKEND", "").strip().lower()
        if not backend:
            backend = "ollama" if ":11434" in str(base_url) else "vllm"
        self.backend = backend

    def _thinking_default(self) -> bool:
        """Whether thinking is on by default (env-driven). Overridable per call."""
        return os.environ.get("VLLM_ENABLE_THINKING", "1").strip().lower() not in ("0", "false", "no", "off")

    def _extra_body(self, enable_thinking: bool | None = None) -> dict:
        if self.backend == "ollama":
            return {"keep_alive": self.keep_alive, "options": {"num_ctx": self.num_ctx}}
        if self.backend == "vllm":
            # vLLM reasoning models emit ` thinking... response`
            # when the chat template is invoked with
            # `enable_thinking=True`. We ALWAYS send the kwarg explicitly:
            # omitting it lets the server's --default-chat-template-kwargs win,
            # so a server defaulting to thinking-on can't be turned off and
            # VLLM_ENABLE_THINKING=0 becomes a no-op. Helper calls (HyDE,
            # follow-ups) pass enable_thinking=False so their reasoning doesn't
            # leak into the returned text; the chat answer keeps the env default
            # so the UI's thinking panel still receives reasoning.
            if enable_thinking is None:
                enable_thinking = self._thinking_default()
            return {"chat_template_kwargs": {"enable_thinking": bool(enable_thinking)}}
        # Other OpenAI-compatible servers: send nothing extra.
        return {}

    def generate(
        self,
        prompt: str,
        history: list[dict] | None = None,
        max_tokens: int = 4096,
        system_message: str | None = None,
        enable_thinking: bool | None = None,
    ) -> str:
        messages = self._build_messages(prompt, history, system_message)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.7,
            extra_body=self._extra_body(enable_thinking),
        )
        message = response.choices[0].message
        content = message.content or ""
        # Some thinking-model variants emit their answer into a separate
        # `reasoning` field once the visible reply is short or the budget is
        # exhausted. Fall back to that so non-streaming generations actually
        # return text.
        if not content:
            reasoning = getattr(message, "reasoning", "") or ""
            return reasoning
        return content

    def stream(
        self,
        prompt: str,
        history: list[dict] | None = None,
        max_tokens: int = 4096,
        system_message: str | None = None,
        enable_thinking: bool | None = None,
    ) -> Generator[str, None, None]:
        # Backwards-compatible: yields content tokens as plain strings.
        for kind, text in self.stream_typed(prompt, history, max_tokens, system_message, enable_thinking):
            if kind == "content":
                yield text

    def stream_typed(
        self,
        prompt: str,
        history: list[dict] | None = None,
        max_tokens: int = 4096,
        system_message: str | None = None,
        enable_thinking: bool | None = None,
        continue_text: str | None = None,
        n_blocks: int | None = None,
        user_content: list[dict] | None = None,
    ) -> Generator[tuple[str, str], None, None]:
        """Stream both reasoning and content as tagged (kind, text) pairs.

        Multimodal: pass `user_content` (an OpenAI content-parts list, e.g.
        [{"type":"text",...}, {"type":"image_url",...}, {"type":"input_audio",...}])
        to replace the plain-string user turn — used to attach photos/audio. When
        None the user turn is the plain `prompt` string (text-only path).

        For thinking-model variants, reasoning is emitted on
        `delta.reasoning` before the visible content. Callers can choose to
        forward the reasoning to the user or discard it.
        """
        messages = self._build_messages(prompt, history, system_message, user_content)
        extra = self._extra_body(enable_thinking)
        if continue_text:
            extra["continue_text"] = continue_text
        if n_blocks:
            extra["n_blocks"] = n_blocks
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.7,
            stream=True,
            extra_body=extra,
        )
        for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            diffusion = getattr(delta, "diffusion", None)
            if diffusion:
                yield ("diffusion", diffusion)
            # generation throughput {completion_tokens, elapsed_ms, tok_per_sec},
            # updated on each committed block
            stats = getattr(delta, "stats", None)
            if stats:
                yield ("stats", stats)
            raw = getattr(delta, "raw_text", None)
            if raw is not None:
                yield ("raw", raw)
            reasoning = getattr(delta, "reasoning", None)
            if reasoning:
                yield ("thinking", reasoning)
            if delta.content:
                yield ("content", delta.content)
            finish = chunk.choices[0].finish_reason
            if finish:
                yield ("finish", finish)

    def warmup(self) -> None:
        """Issue a tiny completion to verify the endpoint is reachable.

        Harmless on vLLM (which keeps weights loaded indefinitely).
        """
        self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": "ok"}],
            max_tokens=1,
            temperature=0,
            extra_body=self._extra_body(),
        )

    def _build_messages(
        self,
        prompt: str,
        history: list[dict] | None,
        system_message: str | None = None,
        user_content: list[dict] | None = None,
    ) -> list[dict]:
        messages = [{"role": "system", "content": system_message or SYSTEM_MESSAGE}]
        if history:
            messages.extend(history)
        # Multimodal user turn (image/audio parts) overrides the plain-string prompt.
        messages.append({"role": "user", "content": user_content if user_content is not None else prompt})
        return messages
