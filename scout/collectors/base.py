from __future__ import annotations

from typing import Protocol

from scout.models.schemas import RawLead


class Collector(Protocol):
    async def collect(self, query: str, city: str, limit: int) -> list[RawLead]: ...
