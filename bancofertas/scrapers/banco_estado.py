from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from bancofertas.models import Benefit
from bancofertas.parsing import (
    normalize_text,
    parse_card_requirements,
    parse_channel,
    parse_discount,
    parse_promotion_day,
    parse_valid_until,
)
from bancofertas.scrapers.common import USER_AGENT, progress_line, write_json


BANK_NAME = "BancoEstado"
DEFAULT_URL = (
    "https://www.bancoestado.cl/content/bancoestado-public/cl/es/home/home/"
    "todosuma---bancoestado-personas/un-mes-de-sabores---bancoestado-personas.html#/sabores"
)
ADDRESS_PATTERN = re.compile(
    r"\b(?:av\.?|avenida|calle|camino|ruta|pasaje|pje\.?|local|mall|strip center)\b.*\d"
    r"|^[A-ZÁÉÍÓÚÑ][^,\n]{2,80}\s+\d{1,6}(?:\s|,|$)",
    re.IGNORECASE,
)


def parse_listing_text(text: str, source_url: str = DEFAULT_URL) -> list[Benefit]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    benefits: list[Benefit] = []
    seen: set[tuple[str, str, str, str]] = set()

    for index, line in enumerate(lines):
        if "conoce más" not in line.lower() and "conoce mas" not in line.lower():
            continue
        if index < 4:
            continue
        region, day, discount_text, merchant = lines[index - 4:index]
        discount = parse_discount(discount_text)
        promotion_day = parse_promotion_day(day)
        if not discount or not promotion_day:
            continue
        key = (region, day, discount_text, merchant)
        if key in seen:
            continue
        seen.add(key)

        benefits.append(Benefit(
            bank=BANK_NAME,
            source_url=source_url,
            merchant=merchant,
            discount=discount,
            promotion_day=promotion_day,
            channel=parse_channel(text),
            valid_until=None,
            addresses=[],
            location_status="missing",
            restrictions=None,
            card_requirements={
                "brands": ["Visa"] if "visa" in text.lower() else [],
                "products": ["CuentaRUT"] if "cuentarut" in text.lower() else [],
                "tiers": [],
                "types": [],
                "banks": [BANK_NAME],
                "raw": "Tarjetas BancoEstado",
            },
            conditions=None,
            raw_title=" ".join([discount_text, day, line]),
            raw_info="\n".join([region, day, discount_text, merchant, line]),
        ))

    return benefits


def collect_listing_benefits(page: Page, source_url: str = DEFAULT_URL) -> list[Benefit]:
    cards = page.locator(".card-beneficios").evaluate_all(
        """cards => cards
            .filter(card => card.offsetParent !== null && card.dataset.name)
            .map(card => ({
                id: card.dataset.cardId || card.id || "",
                name: card.dataset.name || "",
                offer: card.dataset.oferta || "",
                description: card.dataset.descripcion || "",
                filters: card.dataset.subfiltros || "{}",
                pretitle: card.querySelector("[class*='pretitle']")?.innerText?.trim() || "",
                text: card.innerText?.trim() || ""
            }))"""
    )
    benefits: list[Benefit] = []
    occurrences: dict[str, int] = {}

    for card in cards:
        card_id = card["id"]
        merchant = normalize_text(card["name"])
        if not merchant:
            continue
        occurrence = occurrences.get(card_id, 0)
        occurrences[card_id] = occurrence + 1

        try:
            filters = json.loads(card["filters"])
        except json.JSONDecodeError:
            filters = {}
        days = " ".join(filters.get("dia") or [])
        modalities = " ".join(filters.get("modalidad") or [])
        regions = filters.get("zona") or []
        card_types = " ".join(filters.get("tarjeta") or [])
        description = normalize_text(card["description"])
        offer = normalize_text(card["offer"])
        pretitle = normalize_text(card["pretitle"])
        raw_text = normalize_text(card["text"])
        source_text = " ".join(part for part in [offer, description, days, modalities] if part)
        source_with_id = (
            f"{source_url}#beneficio={card_id}&indice={occurrence}"
            if card_id
            else source_url
        )

        benefits.append(Benefit(
            bank=BANK_NAME,
            source_url=source_with_id,
            merchant=merchant,
            discount=parse_discount(raw_text) or parse_discount(offer or source_text),
            promotion_day=parse_promotion_day(days or raw_text or description),
            channel=parse_channel(" ".join([modalities, description])),
            valid_until=None,
            addresses=[],
            location_status="missing",
            restrictions=None,
            card_requirements=parse_card_requirements(
                " ".join([pretitle, card_types, "BancoEstado"])
            ) or {
                "brands": [],
                "products": ["CuentaRUT"] if "cuentarut" in card_types.lower() else [],
                "tiers": [],
                "types": [],
                "banks": [BANK_NAME],
                "raw": pretitle or card_types or "Tarjetas BancoEstado",
            },
            conditions=None,
            raw_title=raw_text,
            raw_info=raw_text,
        ))

    return benefits


def expand_listing(page: Page) -> None:
    stale_rounds = 0
    previous_count = 0

    while stale_rounds < 5:
        controls = page.get_by_text(
            re.compile(r"^(?:ver|cargar|mostrar)\s+m[aá]s$", re.IGNORECASE)
        )
        clicked = False
        for index in range(controls.count()):
            control = controls.nth(index)
            try:
                if control.is_visible(timeout=300):
                    control.click(timeout=3_000)
                    page.wait_for_timeout(800)
                    clicked = True
                    break
            except PlaywrightTimeoutError:
                continue

        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1_000)
        current_count = page.get_by_text(
            re.compile(r"^conoce\s+m[aá]s$", re.IGNORECASE)
        ).count()

        if current_count > previous_count or clicked:
            stale_rounds = 0
        else:
            stale_rounds += 1
        previous_count = max(previous_count, current_count)


def extract_detail_addresses(text: str, region: str | None = None) -> list[dict[str, object]]:
    lines = [normalize_text(line) for line in text.splitlines() if normalize_text(line)]
    location_headers = {"locales disponibles", "direcciones", "dirección", "direccion", "ubicación", "ubicacion"}
    stop_prefixes = ("más información", "mas informacion", "términos", "terminos", "condiciones")

    location_block: list[str] = []
    for index, line in enumerate(lines):
        if line.lower().rstrip(":") not in location_headers:
            continue
        for candidate in lines[index + 1:]:
            if candidate.lower().startswith(stop_prefixes):
                break
            location_block.append(candidate)
        break

    lines_to_scan = location_block or lines
    candidates: list[str] = []
    ignored_prefixes = (
        "sólo con",
        "solo con",
        "tope ",
        "válido ",
        "valido ",
        "promoción ",
        "promocion ",
        "descuento ",
    )
    for index, line in enumerate(lines_to_scan):
        normalized = line.lower().rstrip(":")
        if normalized.startswith(ignored_prefixes):
            continue
        if normalized in {"dirección", "direccion", "ubicación", "ubicacion"} and index + 1 < len(lines_to_scan):
            candidates.append(lines_to_scan[index + 1])
        elif ADDRESS_PATTERN.search(line):
            candidates.append(line)

    locations: list[dict[str, object]] = []
    seen: set[str] = set()
    for candidate in candidates:
        cleaned = re.sub(
            r"^(?:direcci[oó]n|ubicaci[oó]n)\s*:\s*",
            "",
            candidate,
            flags=re.IGNORECASE,
        ).strip(" .")
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        commune = cleaned.rsplit(",", 1)[-1].strip() if "," in cleaned else None
        locations.append({
            "address": cleaned,
            "address_lines": [cleaned],
            "region": region,
            "comuna": commune,
            "raw": cleaned,
        })
    return locations


def visible_detail_text(page: Page, listing_text: str) -> str:
    candidates = page.locator(
        "[role='dialog']:visible, dialog[open], .modal:visible, "
        "[class*='modal']:visible, [class*='detalle']:visible, [class*='detail']:visible"
    )
    texts: list[str] = []
    for index in range(candidates.count()):
        try:
            text = candidates.nth(index).inner_text(timeout=1_000)
        except PlaywrightTimeoutError:
            continue
        if len(normalize_text(text)) > 40:
            texts.append(text)
    if texts:
        return max(texts, key=len)

    body_text = page.locator("body").inner_text(timeout=20_000)
    return body_text if body_text != listing_text else ""


def close_detail(page: Page) -> None:
    for selector in (
        "button[aria-label*='cerrar' i]:visible",
        "button[title*='cerrar' i]:visible",
        ".modal:visible button.close",
        "[class*='modal']:visible [class*='close']",
    ):
        control = page.locator(selector).last
        try:
            if control.count() and control.is_visible(timeout=300):
                control.click(timeout=2_000)
                page.wait_for_timeout(300)
                return
        except PlaywrightTimeoutError:
            pass
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)


def enrich_from_detail(benefit: Benefit, detail_text: str) -> None:
    if not detail_text:
        return
    region = benefit.raw_info.splitlines()[0].strip() if benefit.raw_info else None
    detected_addresses = extract_detail_addresses(detail_text, region=region)
    addresses = detected_addresses if len(detected_addresses) <= 2 else []
    card_requirements = parse_card_requirements(detail_text + " BancoEstado")
    if card_requirements:
        banks = list(card_requirements.get("banks") or [])
        if BANK_NAME not in banks:
            banks.append(BANK_NAME)
        card_requirements["banks"] = banks

    benefit.addresses = addresses
    if len(detected_addresses) > 2:
        benefit.location_status = "multiple"
    elif addresses:
        benefit.location_status = "specific"
    else:
        benefit.location_status = "missing"
    benefit.valid_until = parse_valid_until(detail_text)
    benefit.channel = parse_channel(detail_text) or benefit.channel
    benefit.card_requirements = card_requirements or benefit.card_requirements
    benefit.conditions = normalize_text(detail_text)
    benefit.raw_info = detail_text


def open_benefit_details(page: Page, benefits: list[Benefit], listing_text: str) -> None:
    total = len(benefits)
    for index, benefit in enumerate(benefits, start=1):
        progress_line(f"BancoEstado: {benefit.merchant}", index, total)
        listing_url = page.url
        fragment = benefit.source_url.split("#beneficio=", 1)[-1] if "#beneficio=" in benefit.source_url else ""
        card_id = fragment.split("&indice=", 1)[0]
        occurrence = int(fragment.split("&indice=", 1)[1]) if "&indice=" in fragment else 0
        try:
            card = (
                page.locator(f'[data-card-id="{card_id}"]').nth(occurrence)
                if card_id
                else page.locator("body")
            )
            if not card.count():
                continue
            button = card.get_by_text(re.compile(r"conoce\s+m[aá]s", re.IGNORECASE)).last
            button.click(timeout=5_000)
            page.wait_for_timeout(700)
            enrich_from_detail(benefit, visible_detail_text(page, listing_text))
            if page.url != listing_url:
                page.go_back(wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(700)
            else:
                close_detail(page)
        except PlaywrightTimeoutError:
            continue


def scrape_banco_estado_benefits(
    category_url: str = DEFAULT_URL,
    headless: bool = True,
    limit: int | None = None,
    browser_channel: str | None = "chrome",
) -> list[Benefit]:
    with sync_playwright() as playwright:
        launch_options: dict[str, object] = {"headless": headless}
        if browser_channel:
            launch_options["channel"] = browser_channel
        browser = playwright.chromium.launch(**launch_options)
        try:
            page = browser.new_page(user_agent=USER_AGENT, viewport={"width": 1440, "height": 1200})
            page.goto(category_url, wait_until="domcontentloaded", timeout=90_000)
            page.wait_for_timeout(5_000)
            expand_listing(page)
            text = page.locator("body").inner_text(timeout=20_000)
            if "política de seguridad" in text or "politica de seguridad" in text.lower():
                raise RuntimeError("BancoEstado blocked the browser session; retry with --headed or another network.")
            benefits = collect_listing_benefits(page, category_url)
            if not benefits:
                raise RuntimeError("No BancoEstado food benefits were found in the rendered listing.")
            if limit is not None:
                benefits = benefits[:limit]
            progress_line(f"BancoEstado: found {len(benefits)} benefits")
            open_benefit_details(page, benefits, text)
            return benefits
        finally:
            browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape BancoEstado Un mes de Sabores benefits.")
    parser.add_argument("--category-url", default=DEFAULT_URL)
    parser.add_argument("--output", default="data/banco_estado_sabores.json")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--browser-channel", default="chrome")
    args = parser.parse_args()
    benefits = scrape_banco_estado_benefits(
        args.category_url,
        headless=not args.headed,
        limit=args.limit,
        browser_channel=args.browser_channel or None,
    )
    write_json(benefits, Path(args.output))
    print(f"Wrote {len(benefits)} benefits to {args.output}")


if __name__ == "__main__":
    main()
