from __future__ import annotations

from pydantic import BaseModel, Field


class LeadContacts(BaseModel):
    emails: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    telegram: list[str] = Field(default_factory=list)
    vk: list[str] = Field(default_factory=list)
    max_links: list[str] = Field(default_factory=list)
    whatsapp: list[str] = Field(default_factory=list)
    other_links: list[str] = Field(default_factory=list)
    lpr_name: str | None = None
    lpr_role: str | None = None
    best_channel: str | None = None
    source_notes: list[str] = Field(default_factory=list)

    def has_any_channel(self) -> bool:
        return bool(
            self.emails
            or self.phones
            or self.telegram
            or self.vk
            or self.max_links
            or self.whatsapp
        )

    def merge(self, other: LeadContacts) -> LeadContacts:
        def uniq(items: list[str]) -> list[str]:
            seen: set[str] = set()
            out: list[str] = []
            for item in items:
                key = item.strip().lower()
                if key and key not in seen:
                    seen.add(key)
                    out.append(item.strip())
            return out

        return LeadContacts(
            emails=uniq(self.emails + other.emails),
            phones=uniq(self.phones + other.phones),
            telegram=uniq(self.telegram + other.telegram),
            vk=uniq(self.vk + other.vk),
            max_links=uniq(self.max_links + other.max_links),
            whatsapp=uniq(self.whatsapp + other.whatsapp),
            other_links=uniq(self.other_links + other.other_links),
            lpr_name=self.lpr_name or other.lpr_name,
            lpr_role=self.lpr_role or other.lpr_role,
            source_notes=uniq(self.source_notes + other.source_notes),
        )


class OutreachChannel(BaseModel):
    channel: str
    label: str
    url: str
    contact_value: str
    message: str
    auto: bool = False
