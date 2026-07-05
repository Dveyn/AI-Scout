"""Русские подписи для UI маркетингового отдела."""

from __future__ import annotations

AGENT_LABELS: dict[str, str] = {
    "cmo": "CMO — стратегия",
    "sales": "Продажи",
    "smm": "SMM — соцсети",
    "ads": "Реклама",
    "seo": "SEO — статьи",
    "analytics": "Аналитика",
}

DEAL_STATUS_LABELS: dict[str, str] = {
    "new": "Новая",
    "in_progress": "В переписке",
    "meeting": "Созвон назначен",
    "won": "Сделка закрыта",
    "lost": "Отказ",
}

TASK_STATUS_LABELS: dict[str, str] = {
    "pending": "Ожидает",
    "pending_cmo_approval": "Ждёт вашего OK",
    "approved": "Одобрено",
    "in_progress": "Выполняется",
    "done": "Готово",
    "rejected": "Отклонено",
    "failed": "Ошибка",
}

CONTENT_STATUS_LABELS: dict[str, str] = {
    "draft": "Черновик",
    "scheduled": "К публикации",
    "published": "Опубликовано",
    "failed": "Не опубликовано",
}

AD_STATUS_LABELS: dict[str, str] = {
    "draft": "Черновик",
    "pending_approval": "Ждёт утверждения",
    "approved": "Одобрено",
    "rejected": "Отклонено",
}

PLATFORM_LABELS: dict[str, str] = {
    "vk": "ВКонтакте",
    "telegram": "Telegram",
    "tenchat": "TenChat",
    "seo": "Статья на сайте",
}

# Типы задач от CMO / Cursor (ключ — как в БД, со _ или -)
TASK_TYPE_LABELS: dict[str, str] = {
    "content_plan": "План публикаций",
    "content": "Пост",
    "content_creation": "Создание постов",
    "seo_article": "SEO-статья",
    "seo_content": "SEO-контент",
    "ad_creatives": "Рекламные объявления",
    "strategy": "Стратегия",
    "inbox_reply": "Ответ клиенту",
    "proposal": "Коммерческое предложение",
    "offer": "Оффер / предложение",
    "offer_review": "Обзор офферов",
    "audience_analysis": "Анализ аудитории",
    "ab_testing": "A/B-тестирование",
    "discussion": "Обсуждение с командой",
    "team_meeting": "Совещание команды",
    "lead_magnet": "Лид-магнит",
    "lead_magnet_creation": "Создание лид-магнита",
    "email_optimization": "Оптимизация писем",
    "funnel_review": "Разбор воронки",
    "kpi_review": "Разбор KPI",
    "competitor_analysis": "Анализ конкурентов",
    "landing_review": "Разбор посадочной",
    "social_plan": "План соцсетей",
    "retargeting": "Ретаргетинг",
    "cold_outreach": "Холодные письма",
    "follow_up": "Повторное касание",
    "crm_update": "Обновление CRM",
    "report": "Отчёт",
    "review": "Проверка",
    "analysis": "Анализ",
    "planning": "Планирование",
    "brainstorm": "Мозговой штурм",
}

# Подписи отдельных английских слов (если тип задачи не в словаре)
_TASK_WORD_RU: dict[str, str] = {
    "offer": "оффер",
    "review": "обзор",
    "audience": "аудитория",
    "analysis": "анализ",
    "ab": "A/B",
    "testing": "тестирование",
    "test": "тест",
    "discussion": "обсуждение",
    "team": "команда",
    "meeting": "встреча",
    "content": "контент",
    "creation": "создание",
    "lead": "лид",
    "magnet": "магнит",
    "email": "письма",
    "social": "соцсети",
    "media": "медиа",
    "plan": "план",
    "strategy": "стратегия",
    "seo": "SEO",
    "ads": "реклама",
    "ad": "реклама",
    "creative": "креатив",
    "creatives": "креативы",
    "campaign": "кампания",
    "funnel": "воронка",
    "kpi": "KPI",
    "competitor": "конкурент",
    "competitors": "конкуренты",
    "landing": "посадочная",
    "page": "страница",
    "retargeting": "ретаргетинг",
    "outreach": "аутрич",
    "cold": "холодный",
    "follow": "повтор",
    "up": "касание",
    "crm": "CRM",
    "report": "отчёт",
    "brainstorm": "мозговой штурм",
    "optimization": "оптимизация",
    "optimize": "оптимизация",
    "post": "пост",
    "posts": "посты",
    "article": "статья",
    "proposal": "КП",
    "sales": "продажи",
    "marketing": "маркетинг",
    "daily": "ежедневный",
    "weekly": "еженедельный",
}


ACTION_LABELS: dict[str, str] = {
    "inbox_reply": "Ответ на письмо",
    "generate_proposal": "Коммерческое предложение",
    "ad_creatives": "Рекламные креативы",
    "seo_content": "SEO-контент",
    "review_and_plan": "План от CMO",
    "daily_report": "Дневной отчёт",
    "content_plan": "Контент-план",
    "publish_content": "Публикация",
    "apply_verdict": "Ответ Cursor",
}


def _normalize_task_key(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def label_action(value: str) -> str:
    return ACTION_LABELS.get(_normalize_task_key(value), value)


def label_agent(value: str) -> str:
    return AGENT_LABELS.get(value, value)


def label_deal_status(value: str) -> str:
    return DEAL_STATUS_LABELS.get(value, value)


def label_task_status(value: str) -> str:
    return TASK_STATUS_LABELS.get(value, value)


def label_content_status(value: str) -> str:
    return CONTENT_STATUS_LABELS.get(value, value)


def label_ad_status(value: str) -> str:
    return AD_STATUS_LABELS.get(value, value)


def label_platform(value: str) -> str:
    return PLATFORM_LABELS.get(value.lower(), value)


def label_task_type(value: str) -> str:
    key = _normalize_task_key(value)
    if key in TASK_TYPE_LABELS:
        return TASK_TYPE_LABELS[key]
    # Составной ключ: offer_review → обзор офферов по словам
    parts = key.split("_")
    if len(parts) > 1:
        translated = [_TASK_WORD_RU.get(p, p) for p in parts if p]
        if any(p in _TASK_WORD_RU for p in parts):
            return " ".join(translated).capitalize()
    # Одно слово или пробелы в исходнике
    for sep in (" ", "_", "-"):
        if sep in value:
            words = [w for w in value.lower().replace("_", " ").replace("-", " ").split() if w]
            return " ".join(_TASK_WORD_RU.get(w, w) for w in words).capitalize()
    return value


def deal_status_options() -> list[tuple[str, str]]:
    return [(k, v) for k, v in DEAL_STATUS_LABELS.items()]
