from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urlencode

from bancofertas.models import Benefit
from bancofertas.parsing import parse_card_requirements, parse_channel, parse_discount, parse_promotion_day
from bancofertas.scrapers.common import fetch_json, iso_datetime_to_chile_date, progress_line, write_json


BANK_NAME = "BCI"
BASE_API_URL = "https://api.bciplus.cl/bff-loyalty-beneficios/v1/offers"
DETAIL_BASE_URL = "https://www.bci.cl/beneficios/beneficios-bci/detalle"
API_KEY = "fa981752762743668413b68821a43840"
RESTAURANT_CATEGORY = "Restaurantes"


def is_restaurant_offer(offer: dict[str, object]) -> bool:
    categories = offer.get("categorias") or []
    return any(category.get("titulo") == RESTAURANT_CATEGORY for category in categories)


def parse_bci_offer(offer: dict[str, object]) -> Benefit:
    merchant = (offer.get("comercio") or {}).get("nombre") or offer.get("titulo") or "Comercio BCI"
    description = str(offer.get("descripcion") or "")
    legal = str(offer.get("legal") or "")
    subtitle = str(offer.get("subtitulo") or "")
    scheduling = offer.get("scheduling") or {}
    recurrence = ", ".join(scheduling.get("dayRecurrence") or [])
    source_text = " ".join(part for part in [str(offer.get("titulo") or ""), subtitle, description, legal, recurrence] if part)
    percentage = (
        ((offer.get("beneficio") or {}).get("discount") or {}).get("porcentajeDescuento")
        or ((offer.get("deal") or {}).get("discount") or {}).get("percentage")
    )
    discount = f"{percentage}%" if percentage else parse_discount(source_text)
    slug = offer.get("slug")

    return Benefit(
        bank=BANK_NAME,
        source_url=f"{DETAIL_BASE_URL}/{slug}" if slug else DETAIL_BASE_URL,
        merchant=str(merchant),
        discount=discount,
        promotion_day=parse_promotion_day(recurrence or source_text),
        channel=parse_channel(source_text),
        valid_until=iso_datetime_to_chile_date(offer.get("fechaTermino")),
        addresses=[],
        location_status="multiple",
        restrictions=None,
        card_requirements=parse_card_requirements(" ".join([subtitle, description, legal, "Banco BCI"])),
        conditions=legal or description or None,
        raw_title=" ".join(part for part in [str(offer.get("titulo") or ""), subtitle] if part),
        raw_info=source_text,
    )


def scrape_bci_benefits(limit: int | None = None) -> list[Benefit]:
    page = 1
    offers: list[dict[str, object]] = []
    headers = {"Ocp-Apim-Subscription-Key": API_KEY}

    while True:
        query = urlencode({"itemsPorPagina": 100, "pagina": page})
        payload = fetch_json(f"{BASE_API_URL}?{query}", headers=headers)
        offers.extend(payload.get("ofertas") or [])
        total_pages = int((payload.get("paginado") or {}).get("totalPaginas") or page)
        progress_line(f"BCI: API page {page}/{total_pages}, {len(offers)} offers")
        if page >= total_pages or (limit is not None and len(offers) >= limit):
            break
        page += 1

    restaurant_offers = [offer for offer in offers if is_restaurant_offer(offer)]
    if limit is not None:
        restaurant_offers = restaurant_offers[:limit]
    total = len(restaurant_offers)
    progress_line(f"BCI: found {total} restaurant benefits")
    benefits: list[Benefit] = []
    for index, offer in enumerate(restaurant_offers, start=1):
        merchant = str((offer.get("comercio") or {}).get("nombre") or offer.get("titulo") or "Comercio")
        progress_line(f"BCI: {merchant}", index, total)
        benefits.append(parse_bci_offer(offer))
    return benefits


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape BCI restaurant benefits from its public frontend API.")
    parser.add_argument("--output", default="data/bci_restaurantes.json")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    benefits = scrape_bci_benefits(limit=args.limit)
    write_json(benefits, Path(args.output))
    print(f"Wrote {len(benefits)} benefits to {args.output}")


if __name__ == "__main__":
    main()

