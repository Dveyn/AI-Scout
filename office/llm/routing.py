from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

from office.config import get_office_settings
from office.llm.brand_context import cached_system_prefix, model_for_tier
from office.llm.budget import can_spend_office, record_office_cost
from office.models import ModelTier

logger = logging.getLogger(__name__)


class OfficeLLMError(RuntimeError):
    """GPTunnel / network failure with a user-readable message."""


def llm_available() -> bool:
    settings = get_office_settings()
    key = (settings.gptunnel_api_key or "").strip()
    return bool(key) and key != "not-set"


@dataclass
class OfficeLLMResponse:
    content: str
    cost_rub: float = 0.0
    model: str = ""


class OfficeLLMClient:
    """GPTunnel client with model tier routing and brand context prefix."""

    def __init__(self) -> None:
        settings = get_office_settings()
        self._client = AsyncOpenAI(
            api_key=settings.gptunnel_api_key or "not-set",
            base_url=settings.gptunnel_base_url,
        )
        self._use_wallet = settings.gptunnel_use_wallet_balance

    def _extra_body(self) -> dict[str, Any] | None:
        if self._use_wallet:
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

    async def complete(
        self,
        role: str,
        user_message: str,
        *,
        tier: ModelTier = ModelTier.EXECUTION,
        department: str = "",
        max_tokens: int = 1500,
    ) -> OfficeLLMResponse:
        if not llm_available():
            raise OfficeLLMError(
                "GPTunnel не настроен: добавьте GPTUNNEL_API_KEY в scout/.env"
            )
        if not await can_spend_office(department=department):
            return OfficeLLMResponse(content="Бюджет LLM исчерпан.", cost_rub=0.0)

        model = model_for_tier(tier)
        messages = [
            {"role": "system", "content": cached_system_prefix(role)},
            {"role": "user", "content": user_message},
        ]
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        extra = self._extra_body()
        if extra:
            kwargs["extra_body"] = extra

        try:
            response = await self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            logger.exception("GPTunnel request failed")
            base = get_office_settings().gptunnel_base_url
            raise OfficeLLMError(
                f"Не удалось связаться с GPTunnel ({base}). "
                f"Проверьте интернет и ключ API. Детали: {exc}"
            ) from exc

        cost = self._extract_cost(response.usage)
        await record_office_cost(cost, department=department)
        content = response.choices[0].message.content or ""
        return OfficeLLMResponse(content=content, cost_rub=cost, model=model)
