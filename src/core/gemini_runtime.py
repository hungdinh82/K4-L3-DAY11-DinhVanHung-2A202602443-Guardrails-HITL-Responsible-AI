"""Small Gemini runtime with deterministic pre/post-model hooks.

Google ADK's plugin callback surface varies between releases.  The lab needs a
stable security boundary, so this adapter runs the same hooks explicitly before
and after the Gemini call.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from core.config import get_red_model


@dataclass
class GeminiAgent:
    name: str
    instruction: str
    provider: str = "gemini"


@dataclass
class GeminiRunner:
    app_name: str
    model: str
    temperature: float = 0.4
    provider: str = "gemini"
    input_hooks: list[Callable[[str], str | None]] = field(default_factory=list)
    output_hooks: list[Callable[[str], str]] = field(default_factory=list)

    async def chat(self, agent: GeminiAgent, user_message: str) -> str:
        for hook in self.input_hooks:
            blocked = hook(user_message)
            if blocked:
                return blocked

        from google import genai

        client = genai.Client()
        response = await client.aio.models.generate_content(
            model=self.model,
            contents=user_message,
            config={
                "system_instruction": agent.instruction,
                "temperature": self.temperature,
            },
        )
        text = (response.text or "").strip()
        for hook in self.output_hooks:
            text = hook(text)
        return text


def create_gemini_pair(
    *,
    name: str,
    instruction: str,
    app_name: str,
    input_hooks: list[Callable[[str], str | None]] | None = None,
    output_hooks: list[Callable[[str], str]] | None = None,
    temperature: float = 0.4,
    model: str | None = None,
) -> tuple[GeminiAgent, GeminiRunner]:
    agent = GeminiAgent(name=name, instruction=instruction)
    runner = GeminiRunner(
        app_name=app_name,
        model=model or get_red_model(),
        temperature=temperature,
        input_hooks=list(input_hooks or []),
        output_hooks=list(output_hooks or []),
    )
    return agent, runner
