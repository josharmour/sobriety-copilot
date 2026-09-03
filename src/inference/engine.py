"""Inference engine for locally-hosted LLM via OpenAI-compatible API."""

import os
from collections.abc import Generator
from typing import Any

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
            # The dsv4 alias now serves GLM-5.3-Flash (serve-glm53-blackwell.sh).
            # GLM ALWAYS deliberates: with thinking=false the reasoning is not
            # separated into the reasoning field and leaks inline into the
            # visible content — observed live 2026-08-29 as raw reasoning in
            # the chat bubble and meta-deliberation ("I just need to output 3
            # follow-up questions...") inside the Keep Exploring card. Sending
            # thinking=true + reasoning_effort=low on EVERY call lets the glm45
            # reasoning parser strip the deliberation from content (stream_typed
            # still receives it as "thinking" items for the thinking panel), and
            # low effort keeps latency sane. Helper calls (HyDE, follow-ups)
            # previously got the old enable_thinking=False toggle; under GLM that
            # toggle is exactly what caused the leak, so it is deliberately
            # retired here. CAVEAT: if a real DeepSeek-dialect dsv4 container
            # returns to :8002, revisit — dsv4 slowed badly with thinking=true
            # (2026-07-29 bug); re-gate on the served engine then.
            return {
                "chat_template_kwargs": {
                    "thinking": True,
                    "reasoning_effort": "low",
                }
            }
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
        if "</think>" in content:
            content = content.split("</think>")[-1].strip()
        # Some thinking-model variants emit their answer into a separate
        # `reasoning` field once the visible reply is short or the budget is
        # exhausted. Fall back to that so non-streaming generations actually
        # return text.
        if not content:
            reasoning = getattr(message, "reasoning", "") or getattr(message, "reasoning_content", "") or ""
            if "</think>" in reasoning:
                reasoning = reasoning.split("</think>")[-1].strip()
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
    ) -> Generator[tuple[str, Any], None, None]:
        """Stream both reasoning and content as tagged (kind, text) pairs."""
        messages = self._build_messages(prompt, history, system_message, user_content)
        extra = dict(self._extra_body(enable_thinking))
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
            extra_body=extra if extra else None,
        )
        in_unparsed_think = False
        for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            diffusion = getattr(delta, "diffusion", None)
            if diffusion:
                yield ("diffusion", diffusion)
            stats = getattr(delta, "stats", None)
            if stats:
                yield ("stats", stats)
            raw = getattr(delta, "raw_text", None)
            if raw is not None:
                yield ("raw", raw)
            reasoning = getattr(delta, "reasoning", None) or getattr(delta, "reasoning_content", None)
            if reasoning:
                yield ("thinking", reasoning)
            if delta.content:
                text = delta.content
                if in_unparsed_think:
                    if "</think>" in text:
                        before, after = text.split("</think>", 1)
                        if before:
                            yield ("thinking", before)
                        in_unparsed_think = False
                        if after:
                            yield ("content", after)
                    else:
                        yield ("thinking", text)
                elif "</think>" in text:
                    before, after = text.split("</think>", 1)
                    if before:
                        yield ("thinking", before)
                    if after:
                        yield ("content", after)
                elif text.startswith("<think>"):
                    in_unparsed_think = True
                    rem = text[7:]
                    if "</think>" in rem:
                        before, after = rem.split("</think>", 1)
                        if before:
                            yield ("thinking", before)
                        in_unparsed_think = False
                        if after:
                            yield ("content", after)
                    else:
                        if rem:
                            yield ("thinking", rem)
                else:
                    yield ("content", text)
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
