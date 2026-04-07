"""Inference engine for locally-hosted Gemma 4 via OpenAI-compatible API."""

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
        model: str = "gemma4",
        api_key: str = "ollama",
    ):
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model

    def generate(
        self, prompt: str, history: list[dict] | None = None, max_tokens: int = 4096
    ) -> str:
        messages = self._build_messages(prompt, history)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.7,
            extra_body={"keep_alive": -1},
        )
        return response.choices[0].message.content or ""

    def stream(
        self, prompt: str, history: list[dict] | None = None, max_tokens: int = 4096
    ) -> Generator[str, None, None]:
        messages = self._build_messages(prompt, history)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.7,
            stream=True,
            extra_body={"keep_alive": -1},
        )
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def _build_messages(self, prompt: str, history: list[dict] | None) -> list[dict]:
        messages = [{"role": "system", "content": SYSTEM_MESSAGE}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})
        return messages
