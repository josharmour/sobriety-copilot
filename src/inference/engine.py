"""Inference engine for locally-hosted Gemma 4 via OpenAI-compatible API."""

import os
from collections.abc import Generator

from openai import OpenAI

from src.prompts.templates import SYSTEM_MESSAGE


class InferenceEngine:
    """Connects to a locally-hosted LLM exposed via an OpenAI-compatible API.

    Works with Ollama, vLLM, llama.cpp server, or any OpenAI-compatible endpoint.
    Default configuration targets Ollama running Gemma 4.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",
        model: str = "gemma4:e2b",
        api_key: str = "ollama",
    ):
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        keep_alive = os.environ.get("OLLAMA_KEEP_ALIVE", "-1").strip()
        try:
            self.keep_alive = int(keep_alive)
        except ValueError:
            self.keep_alive = keep_alive
        # Ollama defaults num_ctx to 2048, which silently truncates long RAG
        # prompts. Gemma 4 supports 128K; 32K is a safe headroom for our
        # context window without blowing up VRAM. Override via env if needed.
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

    def _extra_body(self) -> dict:
        if self.backend == "ollama":
            return {"keep_alive": self.keep_alive, "options": {"num_ctx": self.num_ctx}}
        # vLLM / other OpenAI servers: send nothing extra. vLLM ignores unknown
        # keys but rejects entire-payload extras like `options`.
        return {}

    def generate(
        self,
        prompt: str,
        history: list[dict] | None = None,
        max_tokens: int = 4096,
        system_message: str | None = None,
    ) -> str:
        messages = self._build_messages(prompt, history, system_message)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.7,
            extra_body=self._extra_body(),
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
    ) -> Generator[str, None, None]:
        # Backwards-compatible: yields content tokens as plain strings.
        for kind, text in self.stream_typed(prompt, history, max_tokens, system_message):
            if kind == "content":
                yield text

    def stream_typed(
        self,
        prompt: str,
        history: list[dict] | None = None,
        max_tokens: int = 4096,
        system_message: str | None = None,
    ) -> Generator[tuple[str, str], None, None]:
        """Stream both reasoning and content as tagged (kind, text) pairs.

        For thinking-model variants (e.g. gemma4:e2b), reasoning is emitted on
        `delta.reasoning` before the visible content. Callers can choose to
        forward the reasoning to the user or discard it.
        """
        messages = self._build_messages(prompt, history, system_message)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.7,
            stream=True,
            extra_body=self._extra_body(),
        )
        for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            reasoning = getattr(delta, "reasoning", None)
            if reasoning:
                yield ("thinking", reasoning)
            if delta.content:
                yield ("content", delta.content)

    def warmup(self) -> None:
        """Issue a tiny completion so Ollama loads and pins the chat model.

        Harmless on vLLM (which keeps weights loaded indefinitely) — just
        verifies the endpoint is reachable.
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
    ) -> list[dict]:
        messages = [{"role": "system", "content": system_message or SYSTEM_MESSAGE}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})
        return messages
