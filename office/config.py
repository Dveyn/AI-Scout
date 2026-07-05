from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

OFFICE_ROOT = Path(__file__).resolve().parent
SCOUT_ROOT = OFFICE_ROOT.parent / "scout"


class OfficeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(SCOUT_ROOT / ".env", OFFICE_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    gptunnel_api_key: str = ""
    gptunnel_base_url: str = "https://gptunnel.ru/v1"
    gptunnel_model_strategy: str = "gpt-4o"
    gptunnel_model_execution: str = "gpt-4o-mini"
    gptunnel_use_wallet_balance: bool = True

    office_bind_host: str = "127.0.0.1"
    office_bind_port: int = 8090
    office_database_url: str = f"sqlite+aiosqlite:///{OFFICE_ROOT / 'data' / 'office.db'}"

    # hybrid | local | cursor
    office_llm_provider: str = "hybrid"
    office_daily_budget_rub: float = 50.0
    office_dept_budget_rub: float = 15.0

    brand_context_path: str = ""

    cursor_webhook_department_daily: str = ""
    cursor_webhook_office_directive: str = ""
    cursor_webhook_api_key: str = ""

    scout_api_base: str = "http://127.0.0.1:8080"

    def uses_hybrid(self) -> bool:
        return self.office_llm_provider.strip().lower() == "hybrid"

    def uses_cursor(self) -> bool:
        return self.office_llm_provider.strip().lower() == "cursor"

    def uses_gptunnel_local(self) -> bool:
        return self.office_llm_provider.strip().lower() == "local"

    def brand_path(self) -> Path:
        if self.brand_context_path.strip():
            return Path(self.brand_context_path)
        return OFFICE_ROOT.parent / ".agents" / "product-marketing.md"


@lru_cache
def get_office_settings() -> OfficeSettings:
    return OfficeSettings()
