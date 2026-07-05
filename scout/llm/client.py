from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

from scout.config import get_settings


@dataclass
class ChatResponse:
    content: str | None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    cost_rub: float = 0.0


class GPTunnelClient:
    """OpenAI-compatible client for GPTunnel API."""

    def __init__(self) -> None:
        settings = get_settings()
        self.model = settings.gptunnel_model
        self.use_wallet = settings.gptunnel_use_wallet_balance
        self._client = AsyncOpenAI(
            api_key=settings.gptunnel_api_key,
            base_url=settings.gptunnel_base_url,
        )

    def _extra_body(self) -> dict[str, Any] | None:
        if self.use_wallet:
            return {"useWalletBalance": True}
        return None

    def _extract_cost(self, usage: Any) -> float:
        if not usage:
            return 0.0
        total_cost = getattr(usage, "total_cost", None)
        if total_cost is not None:
            return float(total_cost)
        extra = getattr(usage, "model_extra", None) or {}
        if "total_cost" in extra:
            return float(extra["total_cost"])
        return 0.0

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> ChatResponse:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        extra = self._extra_body()
        if extra:
            kwargs["extra_body"] = extra
        if tools:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice

        response = await self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        message = choice.message

        tool_calls: list[dict[str, Any]] = []
        if message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append(
                    {
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                )

        return ChatResponse(
            content=message.content,
            tool_calls=tool_calls,
            cost_rub=self._extract_cost(response.usage),
        )
