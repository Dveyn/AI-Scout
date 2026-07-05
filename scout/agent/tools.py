from __future__ import annotations

import json
from typing import Any

from scout.models.contacts import LeadContacts
from scout.models.schemas import AgentResult, RawLead
from scout.tools.maps_reviews import fetch_maps_reviews
from scout.tools.website import fetch_website
from scout.tools.combined_audit import audit_website_full

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "fetch_website",
            "description": "Загрузить текст с сайта компании для поиска конкретных деталей и болей.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL сайта компании",
                    }
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_maps_reviews",
            "description": "Загрузить отзывы с карточки организации на Яндекс.Картах.",
            "parameters": {
                "type": "object",
                "properties": {
                    "maps_url": {
                        "type": "string",
                        "description": "Ссылка на карточку организации",
                    }
                },
                "required": ["maps_url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "audit_website",
            "description": (
                "Технический аудит сайта: HTTPS, скорость, мобильность, SEO, контакты. "
                "Используй для конкретных проблем в КП/письме."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL сайта компании",
                    }
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_lead_result",
            "description": "Завершить работу и вернуть квалификацию и письмо.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fit_score": {"type": "integer", "minimum": 0, "maximum": 100},
                    "is_target": {"type": "boolean"},
                    "reason": {"type": "string"},
                    "pains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 3,
                    },
                    "hook": {"type": "string"},
                    "product_angle": {
                        "type": "string",
                        "description": (
                            "Какую бизнес-выгоду даст доработка сайта/системы: "
                            "больше заявок, доверие, SEO, мобильные клиенты — из fix_values аудита"
                        ),
                    },
                    "subject": {"type": ["string", "null"]},
                    "message": {"type": ["string", "null"]},
                    "channel_hint": {
                        "type": "string",
                        "enum": ["email", "telegram", "vk", "max", "whatsapp", "phone"],
                        "description": "Лучший канал для выхода на ЛПР из найденных контактов",
                    },
                    "lpr_name": {
                        "type": ["string", "null"],
                        "description": "Имя ЛПР, если найдено на сайте",
                    },
                    "reasoning_summary": {"type": "string"},
                    "website_issues": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 5,
                        "description": "Топ проблем сайта из аудита для КП",
                    },
                },
                "required": [
                    "fit_score",
                    "is_target",
                    "reason",
                    "pains",
                    "hook",
                    "product_angle",
                    "channel_hint",
                    "reasoning_summary",
                    "website_issues",
                ],
            },
        },
    },
]


SUBMIT_ONLY_TOOL_DEFINITIONS = [t for t in TOOL_DEFINITIONS if t["function"]["name"] == "submit_lead_result"]


def build_user_message(
    lead: RawLead,
    website_audit: dict | None = None,
    contacts: LeadContacts | None = None,
    website_content: dict | None = None,
    *,
    lite: bool = False,
) -> str:
    import json

    if lite:
        parts = [
            "Все данные уже собраны. НЕ вызывай fetch_website/audit_website — сразу submit_lead_result.",
            "Если подходит — напиши персональное письмо. Проблема сайта → ценность для бизнеса.",
            "",
            f"```json\n{lead.model_dump_json(indent=2, ensure_ascii=False)}\n```",
        ]
    else:
        parts = [
            "Оцени компанию. Если подходит — изучи сайт и напиши сообщение для выхода на ЛПР.",
            "Если email нет — текст под Telegram/VK/Max: короче, живее, без формального subject.",
            "Обязательно: проблема сайта → ценность доработки для их бизнеса.",
            "",
            f"```json\n{lead.model_dump_json(indent=2, ensure_ascii=False)}\n```",
        ]
    if contacts and contacts.has_any_channel():
        parts.extend(
            [
                "",
                "Найденные каналы для выхода на ЛПР (выбери channel_hint):",
                f"```json\n{contacts.model_dump_json(indent=2, ensure_ascii=False)}\n```",
            ]
        )
    if website_content and website_content.get("text"):
        parts.extend(
            [
                "",
                "Текст с сайта (уже загружен):",
                f"Title: {website_content.get('title') or '—'}",
                f"Description: {website_content.get('description') or '—'}",
                website_content.get("text", "")[:1200],
            ]
        )
    if website_audit:
        audit_json = json.dumps(website_audit, ensure_ascii=False, indent=2)
        if len(audit_json) > 4000:
            slim = {
                k: website_audit[k]
                for k in (
                    "quality_score",
                    "issues",
                    "fix_values",
                    "value_pitch_hint",
                    "business_hooks",
                )
                if k in website_audit
            }
            audit_json = json.dumps(slim, ensure_ascii=False, indent=2)
        parts.extend(
            [
                "",
                "Аудит сайта. fix_values — связка «проблема → ценность»:",
                f"```json\n{audit_json}\n```",
            ]
        )
        hooks = website_audit.get("business_hooks") or []
        if hooks:
            parts.append("Бизнес-приоритеты SEO-аудита: " + "; ".join(hooks[:3]))
    return "\n".join(parts)


async def dispatch_tool(name: str, arguments: dict[str, Any]) -> tuple[Any, AgentResult | None]:
    """Run a tool. Returns (result_for_llm, terminal AgentResult if submit)."""
    if name == "fetch_website":
        result = await fetch_website(arguments.get("url", ""))
        return result, None

    if name == "fetch_maps_reviews":
        result = await fetch_maps_reviews(arguments.get("maps_url", ""))
        return result, None

    if name == "audit_website":
        result = await audit_website_full(arguments.get("url", ""))
        return result, None

    if name == "submit_lead_result":
        result = AgentResult.model_validate(arguments)
        return {"status": "submitted"}, result

    return {"error": f"Unknown tool: {name}"}, None


def preview_tool_result(result: Any, max_len: int = 300) -> str:
    text = json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result
    if len(text) > max_len:
        return text[:max_len] + "…"
    return text
