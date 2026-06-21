from __future__ import annotations

import argparse
import json
from json import JSONDecodeError
from pathlib import Path
import re
import subprocess
from urllib.error import HTTPError

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from bancofertas.models import Benefit
from bancofertas.parsing import (
    extract_addresses,
    infer_location_status,
    parse_card_requirements,
    parse_channel,
    parse_discount,
    parse_promotion_day,
)
from bancofertas.scrapers.common import fetch_json, html_to_text, parse_chilean_date, write_json


BANK_NAME = "Santander"
PROMOTIONS_URL = (
    "https://banco.santander.cl/beneficios/promociones.json"
    "?per_page=9999&tags=home-disfrutadores&custom_fields=true&order_by=updated_at&desc=true"
)
GASTRONOMY_TAG = "cat-sabores"
NON_ADDRESS_PREFIXES = (
    "no acumulable",
    "tope ",
    "descuento ",
    "exclusivo ",
    "válido ",
    "valido ",
    "se excluyen",
    "recuerda ",
)


def custom_field(promotion: dict[str, object], name: str) -> str:
    return str((((promotion.get("custom_fields") or {}).get(name) or {}).get("value")) or "")


def extract_feature_locations(
    description_html: str | None,
    region: str = "",
    commune: str = "",
) -> list[dict[str, object]]:
    soup = BeautifulSoup(description_html or "", "html.parser")
    items = [item.get_text(" ", strip=True) for item in soup.select("li")]
    candidates: list[str] = []

    for index, item in enumerate(items):
        normalized = item.lower()
        if ("válido en local" in normalized or "valido en local" in normalized) and index + 1 < len(items):
            candidates.append(items[index + 1])

    if not candidates and len(items) >= 3:
        candidates.append(items[2])

    locations: list[dict[str, object]] = []
    for candidate in candidates:
        cleaned = candidate.strip(" .")
        normalized = cleaned.lower()
        if not cleaned or normalized.startswith(NON_ADDRESS_PREFIXES):
            continue
        if not re.search(r"\d", cleaned):
            continue

        inferred_commune = commune
        if not inferred_commune and "," in cleaned:
            inferred_commune = cleaned.rsplit(",", 1)[-1].strip()
        locations.append({
            "address": cleaned,
            "address_lines": [cleaned],
            "region": region or None,
            "comuna": inferred_commune or None,
            "raw": cleaned,
        })

    return locations


def parse_santander_promotion(promotion: dict[str, object]) -> Benefit:
    description_html = promotion.get("description")
    description = html_to_text(description_html)
    conditions = html_to_text(promotion.get("conditions"))
    external_summary = custom_field(promotion, "Bajada externa")
    internal_summary = custom_field(promotion, "Bajada interna")
    validity = custom_field(promotion, "Vigencia")
    source_text = " ".join(
        part for part in [str(promotion.get("title") or ""), external_summary, internal_summary, description, conditions]
        if part
    )
    region = custom_field(promotion, "Región cobertura")
    commune = custom_field(promotion, "Comuna cobertura")
    addresses = extract_feature_locations(description_html, region, commune)
    if not addresses:
        addresses = extract_addresses(description)
    if not addresses and (region or commune):
        addresses = [{
            "address": commune or region,
            "address_lines": [commune or region],
            "region": region or None,
            "comuna": commune or None,
            "raw": " - ".join(part for part in [region, commune] if part),
        }]

    return Benefit(
        bank=BANK_NAME,
        source_url=str(promotion.get("url") or "https://banco.santander.cl/beneficios"),
        merchant=str(promotion.get("title") or "Comercio Santander").strip(),
        discount=parse_discount(" ".join([external_summary, internal_summary, description])),
        promotion_day=parse_promotion_day(" ".join([external_summary, internal_summary, " ".join(promotion.get("tags") or [])])),
        channel=parse_channel(description),
        valid_until=parse_chilean_date(validity) or parse_chilean_date(source_text),
        addresses=addresses,
        location_status=infer_location_status(description, addresses) if addresses else ("multiple" if region else "missing"),
        restrictions=None,
        card_requirements=parse_card_requirements(" ".join([description, conditions, "Banco Santander"])),
        conditions=conditions or description or None,
        raw_title=internal_summary or external_summary or None,
        raw_info=source_text,
    )


def fetch_promotions_payload(headless: bool = True, browser_channel: str | None = "chrome") -> dict[str, object]:
    try:
        return fetch_json(PROMOTIONS_URL)
    except (HTTPError, JSONDecodeError):
        pass

    curl_result = subprocess.run(
        ["curl", "--fail", "--location", "--compressed", "--silent", "--show-error", PROMOTIONS_URL],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    if curl_result.returncode == 0:
        try:
            return json.loads(curl_result.stdout)
        except JSONDecodeError:
            pass

    with sync_playwright() as playwright:
        launch_options: dict[str, object] = {"headless": headless}
        if browser_channel:
            launch_options["channel"] = browser_channel
        browser = playwright.chromium.launch(**launch_options)
        try:
            page = browser.new_page()
            response = page.goto(PROMOTIONS_URL, wait_until="domcontentloaded", timeout=90_000)
            if response is None or not response.ok:
                status = response.status if response else "unknown"
                raise RuntimeError(f"Santander promotions feed returned HTTP {status}.")
            return response.json()
        finally:
            browser.close()


def scrape_santander_benefits(
    limit: int | None = None,
    headless: bool = True,
    browser_channel: str | None = "chrome",
) -> list[Benefit]:
    payload = fetch_promotions_payload(headless=headless, browser_channel=browser_channel)
    promotions = [
        promotion
        for promotion in payload.get("promociones") or []
        if GASTRONOMY_TAG in (promotion.get("tags") or [])
    ]
    if limit is not None:
        promotions = promotions[:limit]
    return [parse_santander_promotion(promotion) for promotion in promotions]


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Santander Sabores benefits from its public JSON feed.")
    parser.add_argument("--output", default="data/santander_sabores.json")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--headed", action="store_true", help="Show Chrome if Santander blocks the background request.")
    parser.add_argument("--browser-channel", default="chrome")
    args = parser.parse_args()
    benefits = scrape_santander_benefits(
        limit=args.limit,
        headless=not args.headed,
        browser_channel=args.browser_channel or None,
    )
    write_json(benefits, Path(args.output))
    print(f"Wrote {len(benefits)} benefits to {args.output}")


if __name__ == "__main__":
    main()
