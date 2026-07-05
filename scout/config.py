from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from scout.company import DEFAULT_OFFER as COMPANY_DEFAULT_OFFER
from scout.company import DEFAULT_ICP as COMPANY_DEFAULT_ICP
from scout.company import DEFAULT_PRESET as COMPANY_DEFAULT_PRESET
from scout.company import DEFAULT_PRODUCT as COMPANY_DEFAULT_PRODUCT
from scout.company import COMPANY_BRAND

SCOUT_ROOT = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=SCOUT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    gptunnel_api_key: str = ""
    gptunnel_base_url: str = "https://gptunnel.ru/v1"
    gptunnel_model: str = "gpt-4o-mini"
    gptunnel_use_wallet_balance: bool = True

    agent_max_rounds: int = 3
    agent_max_tool_calls: int = 2
    agent_lite_mode: bool = True
    fit_score_threshold: int = 65
    agent_skill: str = "outreach-writer"
    generate_followups: bool = True
    followup_count: int = 1
    followup_min_fit_score: int = 75

    indexlift_enabled: bool = True
    indexlift_only_below_score: int = 70
    indexlift_min_issues: int = 2
    indexlift_skill_path: str = ""
    indexlift_tier: str = "basic"
    indexlift_mode: str = "single-page"
    indexlift_engines: str = "google,yandex"
    indexlift_timeout_sec: int = 90

    database_url: str = f"sqlite+aiosqlite:///{SCOUT_ROOT / 'data' / 'scout.db'}"
    playwright_headless: bool = True

    # Источник лидов: yandex (Playwright) | 2gis (официальный API) | auto (2GIS если есть ключ)
    maps_collector: str = "yandex"
    twogis_api_key: str = ""

    # DaData — жёсткий фильтр по выручке (finance.revenue, ₽/год)
    dadata_api_key: str = ""
    revenue_filter_enabled: bool = False
    icp_min_monthly_revenue_rub: float = 500_000.0
    revenue_filter_strict: bool = False  # true = отсекать если нет данных в DaData

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_email: str = Field(
        default="",
        validation_alias=AliasChoices("SMTP_FROM_EMAIL", "SMTP_FROM_ADDRESS"),
    )
    smtp_from_name: str = COMPANY_BRAND
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    smtp_tls_reject_unauthorized: bool = Field(
        default=True,
        validation_alias=AliasChoices("SMTP_TLS_REJECT_UNAUTHORIZED", "SMTP_USE_TLS_VERIFY"),
    )

    auto_send_email: bool = False
    auto_send_min_fit_score: int = 70
    default_offer: str = COMPANY_DEFAULT_OFFER
    default_icp: str = COMPANY_DEFAULT_ICP
    default_product: str = COMPANY_DEFAULT_PRODUCT
    default_preset: str = COMPANY_DEFAULT_PRESET

    # Бюджет LLM (₽/день, 0 = без лимита)
    llm_daily_budget_rub: float = 50.0

    # Антиспам: лимиты и паузы между письмами
    max_emails_per_day: int = 20
    max_emails_per_hour: int = 6
    max_emails_per_domain_per_day: int = 1
    send_delay_sec_min: int = 60
    send_delay_sec_max: int = 180

    # Автопилот — очередь кампаний и follow-up без ручного запуска
    autopilot_enabled: bool = False
    autopilot_max_runs_per_day: int = 1
    followup_delay_days: int = 3
    followup_delay_days_touch3: int = 7

    # Telegram: дайджест + ответы с почты
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # IMAP — проверка ответов на исходящие
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    imap_use_ssl: bool = True
    imap_check_enabled: bool = False

    # Сервер / безопасность
    scout_bind_host: str = "127.0.0.1"
    scout_bind_port: int = 8080
    scout_auth_user: str = "admin"
    scout_auth_password: str = ""
    scout_secret_key: str = ""
    scout_require_auth: bool = False
    scout_allowed_ips: str = ""

    # AI Marketing Department
    department_enabled: bool = True
    department_test_mode: bool = False
    department_local_interval_min: int = 60
    # cursor = department agents run in Cursor Automations (no GPTunnel spend)
    # local = all agents use GPTunnel
    department_llm_provider: str = "cursor"
    # Outreach on Yandex Maps still uses GPTunnel when true
    scout_outreach_llm_enabled: bool = True
    cmo_mode: str = "auto"
    cmo_auto_approve_smm: bool = True
    cmo_auto_approve_seo: bool = True
    cmo_auto_approve_ads: bool = False

    vk_access_token: str = ""
    vk_group_id: str = ""
    telegram_channel_id: str = ""

    monthly_ad_budget_rub: float = 0.0
    monthly_revenue_rub: float = 0.0

    cursor_webhook_ads_approval: str = ""
    cursor_webhook_sales_reply: str = ""
    cursor_webhook_cmo_review: str = ""
    cursor_webhook_department_daily: str = ""
    cursor_webhook_office_directive: str = ""
    cursor_webhook_api_key: str = ""

    def department_uses_cursor_llm(self) -> bool:
        return self.department_llm_provider.strip().lower() == "cursor"

    def auth_is_required(self) -> bool:
        if self.scout_require_auth:
            return True
        return bool(self.scout_auth_password)

    def allowed_ip_list(self) -> list[str]:
        if not self.scout_allowed_ips.strip():
            return []
        return [p.strip() for p in self.scout_allowed_ips.split(",") if p.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
