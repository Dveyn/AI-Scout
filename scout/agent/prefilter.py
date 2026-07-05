from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from scout.models.schemas import RawLead

# Явный B2C — не ICP B2B-порталов, LLM не тратим
B2C_KEYWORDS = (
    "стоматолог",
    "стоматология",
    "клиника",
    "медицин",
    "аптек",
    "салон красот",
    "парикмахер",
    "барбер",
    "маникюр",
    "спа",
    "фитнес",
    "спортзал",
    "йога",
    "автомойк",
    "шиномонтаж",
    "гостиниц",
    "отель",
    "хостел",
    "турист",
    "аттракцион",
)

# Для пресета «доставка еды» — наоборот, это целевые ниши
FOOD_DELIVERY_KEYWORDS = (
    "доставк",
    "суши",
    "пицц",
    "ролл",
    "wok",
    "вок",
    "бургер",
    "паназиат",
    "фастфуд",
    "ресторан",
    "кафе",
    "пиццер",
    "суши-бар",
    "food",
    "kitchen",
)

# B2B-сигналы — повышают приоритет (пресет b2b)
B2B_KEYWORDS = (
    "производ",
    "завод",
    "опт",
    "дистриб",
    "логист",
    "склад",
    "металл",
    "стройматериал",
    "оборудован",
    "комплектующ",
    "упаков",
    "перевоз",
    "груз",
    "постав",
    "торгов",
    "b2b",
    "оптов",
)


class PrefilterProfile(str, Enum):
    B2B = "b2b"
    FOOD_DELIVERY = "food_delivery"


class PrefilterAction(str, Enum):
    SKIP = "skip"
    LITE = "lite"
    FULL = "full"


@dataclass
class PrefilterResult:
    action: PrefilterAction
    score: int
    reason: str


def _text_blob(lead: RawLead) -> str:
    parts = [lead.name or "", lead.category or "", lead.snippet or ""]
    return " ".join(parts).lower()


def _has_outreach_channel(lead: RawLead) -> bool:
    return bool(lead.email or lead.phone or lead.website)


def _profile_from_name(name: str | None) -> PrefilterProfile:
    if not name:
        return PrefilterProfile.B2B
    key = name.strip().lower().replace("-", "_")
    if key in ("food_delivery", "food-delivery", "delivery"):
        return PrefilterProfile.FOOD_DELIVERY
    return PrefilterProfile.B2B


def prefilter_lead(lead: RawLead, profile: PrefilterProfile | str | None = None) -> PrefilterResult:
    """Правила до LLM: отсекаем мусор, экономим токены."""
    prof = profile if isinstance(profile, PrefilterProfile) else _profile_from_name(
        str(profile) if profile else None
    )
    blob = _text_blob(lead)
    score = 50

    if prof == PrefilterProfile.FOOD_DELIVERY:
        food_hits = sum(1 for kw in FOOD_DELIVERY_KEYWORDS if kw in blob)
        if not food_hits:
            return PrefilterResult(
                action=PrefilterAction.SKIP,
                score=15,
                reason="Не похоже на доставку еды / ресторан — не ICP",
            )
        score += min(30, food_hits * 10)
    else:
        for kw in B2C_KEYWORDS:
            if kw in blob:
                return PrefilterResult(
                    action=PrefilterAction.SKIP,
                    score=10,
                    reason=f"B2C-ниша («{kw}») — не ICP",
                )
        # рестораны/доставка — не B2B-порталы
        for kw in ("ресторан", "кафе", "пиццер", "суши", "фастфуд", "бар "):
            if kw in blob:
                return PrefilterResult(
                    action=PrefilterAction.SKIP,
                    score=12,
                    reason=f"HoReCa («{kw}») — не ICP B2B-порталов",
                )

    if not _has_outreach_channel(lead):
        return PrefilterResult(
            action=PrefilterAction.SKIP,
            score=5,
            reason="Нет сайта, email и телефона — некуда писать",
        )

    if lead.rating is not None and lead.rating < 3.5:
        return PrefilterResult(
            action=PrefilterAction.SKIP,
            score=15,
            reason=f"Низкий рейтинг {lead.rating} — риск для репутации",
        )

    if lead.reviews_count is not None and lead.reviews_count < 3 and not lead.website:
        return PrefilterResult(
            action=PrefilterAction.SKIP,
            score=20,
            reason="Мало отзывов и нет сайта — слабый сигнал",
        )

    if prof == PrefilterProfile.B2B:
        b2b_hits = sum(1 for kw in B2B_KEYWORDS if kw in blob)
        if b2b_hits:
            score += min(25, b2b_hits * 8)

    if lead.website:
        score += 15
    if lead.email:
        score += 10
    if lead.phone:
        score += 5
    if lead.rating and lead.rating >= 4.0:
        score += 10
    if lead.reviews_count and lead.reviews_count >= 20:
        score += 5

    if not lead.website and lead.maps_url:
        return PrefilterResult(
            action=PrefilterAction.FULL,
            score=score,
            reason="Нет сайта — нужен полный анализ карточки/отзывов",
        )

    return PrefilterResult(
        action=PrefilterAction.LITE,
        score=min(score, 100),
        reason="Сигналы ICP + контакты — достаточно данных для lite-режима",
    )
