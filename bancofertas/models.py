from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Benefit:
    bank: str
    source_url: str
    merchant: str
    discount: str | None = None
    promotion_day: str | None = None
    channel: str | None = None
    valid_until: str | None = None
    addresses: list[dict[str, object]] = field(default_factory=list)
    location_status: str | None = None
    restrictions: str | None = None
    card_requirements: dict[str, object] | None = None
    conditions: str | None = None
    raw_title: str | None = None
    raw_info: str | None = None

    def to_dict(self) -> dict[str, object | None]:
        return {
            "bank": self.bank,
            "source_url": self.source_url,
            "merchant": self.merchant,
            "discount": self.discount,
            "promotion_day": self.promotion_day,
            "channel": self.channel,
            "valid_until": self.valid_until,
            "addresses": self.addresses,
            "location_status": self.location_status,
            "restrictions": self.restrictions,
            "card_requirements": self.card_requirements,
            "conditions": self.conditions,
            "raw_title": self.raw_title,
            "raw_info": self.raw_info,
        }
