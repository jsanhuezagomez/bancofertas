from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from bancofertas.models import Benefit
from bancofertas.parsing import (
    extract_offer_title,
    normalize_text,
    parse_card_requirements,
    parse_channel,
    parse_discount,
    parse_promotion_day,
    parse_valid_until,
    repair_text,
    strip_accents,
)


BANK_NAME = "Banco Falabella"
DEFAULT_CATEGORY_URLS = (
    "https://www.bancofalabella.cl/descuentos/restaurantes",
    "https://www.bancofalabella.cl/descuentos/antojos",
)
DETAIL_PATH = "/descuentos/detalle/"
CARD_SELECTOR = "div[class*='NewCardBenefits_container']:visible"
EMBEDDED_DETAIL_LINK_PATTERN = re.compile(
    r'\\"(?:text|word)\\":\\"(?P<label>[^"]+?)\\"'
    r'.{0,280}?'
    r'\\"url\\":\\"(?P<url>https://www\.bancofalabella\.cl/descuentos/detalle/[a-z0-9-]+)\\"',
    re.IGNORECASE,
)
MERCHANT_ALIASES = {
    "anima cocktail lab": ("anima",),
    "el japones": ("japones",),
    "esquina tropera": ("restaurante esquina tropera",),
    "miscelaneo": ("miscelaneo", "miscelaneo restaurante"),
    "poga heladeria": ("poga", "poga helados"),
}
SKIP_TITLE_TERMS = (
    "dia del padre",
    "día del padre",
    "descuentos en restaurantes",
    "descuentos del mes",
    "beneficios del mes",
)


def progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def finish_progress() -> None:
    return None


def rendered_text(page: Page) -> str:
    body_text = page.locator("body").inner_text(timeout=15_000)
    ignored_lines = {
        "En estos momentos no lo podemos atender, por favor inténtelo más tarde.",
        "Entendido",
        "Usamos cookies para mejorar tu experiencia. Consulta más aquí.",
    }
    lines = []
    for line in repair_text(body_text).splitlines():
        cleaned = normalize_text(line)
        if cleaned and cleaned not in ignored_lines:
            lines.append(cleaned)
    return "\n".join(lines)


def falabella_card_requirements(text: str) -> dict[str, object] | None:
    requirements = parse_card_requirements(text)
    if not requirements:
        return None

    banks = list(requirements.get("banks") or [])
    if BANK_NAME not in banks:
        banks.append(BANK_NAME)
    requirements["banks"] = banks
    return requirements


def normalize_match_text(value: str) -> str:
    normalized = strip_accents(repair_text(value)).lower()
    return re.sub(r"[^a-z0-9]+", " ", normalized).strip()


def compact_match_text(value: str) -> str:
    return normalize_match_text(value).replace(" ", "")


def merchant_from_card_title(title: str) -> str:
    normalized = normalize_match_text(title)
    prefixes = (
        "descuento en restaurante ",
        "descuentos en restaurante ",
        "descuento en chocolateria ",
        "descuento en heladeria ",
        "descuento en cafe ",
        "descuento en ",
        "descuentos en ",
        "restaurante ",
        "chocolateria ",
        "heladeria ",
        "cafe ",
        "canje ",
    )
    for prefix in prefixes:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
            break

    normalized = re.sub(r"\b(exclusivo|presencial|online|delivery|nuevo)\b", " ", normalized)
    return normalize_text(normalized)


def should_skip_card_title(title: str) -> bool:
    normalized = normalize_match_text(title)
    return any(normalize_match_text(term) in normalized for term in SKIP_TITLE_TERMS)


def visible_card_titles(page: Page) -> list[str]:
    titles = page.locator(CARD_SELECTOR).evaluate_all(
        """
        cards => cards
            .map(card => card.querySelector("h2")?.innerText?.trim() || "")
            .filter(Boolean)
        """
    )
    return [normalize_text(title) for title in titles if normalize_text(title)]


def collect_category_card_titles(page: Page, category_url: str, limit: int | None = None) -> list[str]:
    page.goto(category_url, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(5_000)

    titles: list[str] = []
    seen: set[str] = set()
    stale_rounds = 0

    while stale_rounds < 6:
        added = 0
        for title in visible_card_titles(page):
            key = normalize_match_text(title)
            if not key or key in seen or should_skip_card_title(title):
                continue

            seen.add(key)
            titles.append(title)
            added += 1
            if limit is not None and len(titles) >= limit:
                return titles

        previous_scroll_y = page.evaluate("window.scrollY")
        page.evaluate("window.scrollBy(0, Math.floor(window.innerHeight * 0.85))")
        page.wait_for_timeout(1_200)
        current_scroll_y = page.evaluate("window.scrollY")

        stale_rounds = stale_rounds + 1 if added == 0 and current_scroll_y == previous_scroll_y else 0

    return titles


def extract_embedded_detail_links(page: Page) -> list[tuple[str, str]]:
    html = page.content()
    links: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for match in EMBEDDED_DETAIL_LINK_PATTERN.finditer(html):
        label = normalize_text(match.group("label").replace("\\u0026", "&"))
        url = match.group("url").replace("\\/", "/")
        key = (label, url)
        if key not in seen:
            seen.add(key)
            links.append(key)

    return links


def match_card_titles_to_detail_urls(card_titles: list[str], embedded_links: list[tuple[str, str]]) -> list[str]:
    urls: list[str] = []
    normalized_links = [
        (
            normalize_match_text(label),
            compact_match_text(label),
            compact_match_text(url.rsplit("/", 1)[-1].replace("-", " ")),
            url,
        )
        for label, url in embedded_links
    ]

    for title in card_titles:
        merchant = merchant_from_card_title(title)
        merchant_key = normalize_match_text(merchant)
        merchant_keys = [merchant_key, *MERCHANT_ALIASES.get(merchant_key, ())]
        merchant_compacts = [compact_match_text(key) for key in merchant_keys]
        if not merchant_key:
            continue

        match_url = None
        for label_key, label_compact, slug_compact, url in normalized_links:
            if any(
                key
                and (
                    key in label_key
                    or label_key in key
                    or compact in label_compact
                    or label_compact in compact
                    or compact in slug_compact
                    or slug_compact in compact
                )
                for key, compact in zip(merchant_keys, merchant_compacts)
            ):
                match_url = url
                break

        if match_url and match_url not in urls:
            urls.append(match_url)

    return urls


def collect_detail_urls(page: Page, category_url: str, limit: int | None = None) -> list[str]:
    card_titles = collect_category_card_titles(page, category_url, limit=limit)
    embedded_links = extract_embedded_detail_links(page)
    urls = match_card_titles_to_detail_urls(card_titles, embedded_links)
    return urls[:limit] if limit is not None else urls


def extract_merchant(page: Page, fallback_url: str) -> str:
    headings = page.locator("h1,h2").evaluate_all("els => els.map(el => el.innerText).filter(Boolean)")
    for heading_text in headings:
        text = normalize_text(heading_text)
        normalized = strip_accents(text).lower()
        if (
            text
            and normalized not in {"beneficios", "conoce el detalle"}
            and not normalized.startswith("disfruta de tu beneficio")
            and not normalized.startswith("beneficios relacionados")
        ):
            return text

    slug = fallback_url.rstrip("/").split("/")[-1]
    return slug.replace("-", " ").title()


def extract_section(text: str, title: str, stop_titles: tuple[str, ...]) -> str | None:
    lines = [normalize_text(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    normalized_title = strip_accents(title).lower()

    try:
        start = next(
            index + 1
            for index, line in enumerate(lines)
            if strip_accents(line).lower().rstrip(":") == normalized_title.rstrip(":")
        )
    except StopIteration:
        return None

    normalized_stops = tuple(strip_accents(stop).lower().rstrip(":") for stop in stop_titles)
    section_lines: list[str] = []
    for line in lines[start:]:
        normalized = strip_accents(line).lower().rstrip(":")
        if normalized in normalized_stops or any(normalized.startswith(stop) for stop in normalized_stops):
            break
        section_lines.append(line)

    section = normalize_text(" ".join(section_lines))
    return section or None


def extract_conditions(text: str) -> str | None:
    return extract_section(
        text,
        "Condiciones",
        (
            "¿Sabes qué es",
            "Sabes que es",
            "¿Te gusta este beneficio?",
            "Te gusta este beneficio",
            "Beneficios Relacionados",
            "Ver todos los Beneficios",
        ),
    )


def extract_details(text: str) -> str | None:
    return extract_section(
        text,
        "Conoce el detalle",
        (
            "Condiciones",
            "¿Sabes qué es",
            "Sabes que es",
            "¿Te gusta este beneficio?",
            "Te gusta este beneficio",
            "Beneficios Relacionados",
        ),
    )


def parse_falabella_discount(details: str | None, fallback_text: str) -> str | None:
    def normalize_percent(discount: str | None) -> str | None:
        if discount and discount.lower().startswith("hasta "):
            return discount[6:]
        return discount

    if details:
        detail_match = re.search(r"Descuento:\s*([^.\n]+)", details, re.IGNORECASE)
        if detail_match:
            return normalize_percent(parse_discount(detail_match.group(1)))

    return normalize_percent(parse_discount(fallback_text))


def extract_modality(text: str) -> str | None:
    return extract_section(
        text,
        "Modalidad",
        (
            "Ubicación",
            "Ubicacion",
            "Exclusivo con",
            "Conoce el detalle",
        ),
    )


def extract_valid_local_lines(text: str) -> list[str]:
    lines = [normalize_text(line) for line in text.splitlines()]
    lines = [line for line in lines if line]

    try:
        start = next(
            index + 1
            for index, line in enumerate(lines)
            if strip_accents(line).lower().rstrip(":") == "valido en locales"
        )
    except StopIteration:
        return []

    stop_prefixes = (
        "condiciones",
        "sabes que es",
        "¿sabes que es",
        "te gusta este beneficio",
        "¿te gusta este beneficio",
        "beneficios relacionados",
        "ver todos",
    )
    local_lines: list[str] = []
    for line in lines[start:]:
        normalized = strip_accents(line).lower().rstrip(":")
        if any(normalized.startswith(stop) for stop in stop_prefixes):
            break
        local_lines.append(line)

    return local_lines


def extract_locations(text: str) -> list[dict[str, object]]:
    candidates = extract_valid_local_lines(text)
    if not candidates:
        conditions = extract_conditions(text) or ""
        address_match = re.search(r"Direcci[oó]n:\s*([^.?]+)", conditions, re.IGNORECASE)
        candidates = [address_match.group(1).strip()] if address_match else []
    if not candidates:
        return []

    locations: list[dict[str, object]] = []
    for candidate in candidates:
        candidate = candidate.strip(" .")
        if not candidate:
            continue
        parts = [part.strip() for part in candidate.split(",") if part.strip()]
        region = next((part for part in parts if strip_accents(part).lower().startswith("region ")), None)
        comuna = None
        if region and parts.index(region) > 0:
            comuna = parts[parts.index(region) - 1]

        locations.append({
            "address": candidate,
            "address_lines": [candidate],
            "region": region,
            "comuna": comuna,
            "raw": candidate,
        })

    return locations if len(locations) <= 2 else []


def infer_falabella_location_status(text: str, locations: list[dict[str, object]]) -> str:
    if locations:
        return "specific"

    local_lines = extract_valid_local_lines(text)
    if len(local_lines) > 2:
        return "multiple"

    normalized = strip_accents(normalize_text(text)).lower()
    if "valido en locales" in normalized:
        return "multiple"
    return "missing"


def is_direct_restaurant_offer(merchant: str, text: str, url: str) -> bool:
    normalized_merchant = strip_accents(merchant).lower()
    normalized_text = strip_accents(text).lower()
    normalized_url = strip_accents(url).lower()

    if any(term in normalized_merchant or term in normalized_url for term in SKIP_TITLE_TERMS):
        return False

    has_channel = "modalidad:" in normalized_text or "valido en locales:" in normalized_text
    has_valid_until = "valido hasta" in normalized_text
    has_discount = bool(parse_discount(text))
    return has_channel and has_valid_until and has_discount


def parse_detail_page(page: Page, url: str) -> Benefit | None:
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(2_500)

    text = rendered_text(page)
    merchant = extract_merchant(page, url)
    if not is_direct_restaurant_offer(merchant, text, url):
        return None

    offer_title = extract_offer_title(merchant, text)
    conditions = extract_conditions(text)
    details = extract_details(text)
    modality = extract_modality(text)
    locations = extract_locations(text)
    source_text = " ".join(part for part in [offer_title, details, conditions, modality] if part)

    return Benefit(
        bank=BANK_NAME,
        source_url=url,
        merchant=merchant,
        discount=parse_falabella_discount(details, source_text),
        promotion_day=parse_promotion_day(source_text),
        channel=parse_channel(" ".join(part for part in [modality, conditions, details] if part)),
        valid_until=parse_valid_until(text),
        addresses=locations,
        location_status=infer_falabella_location_status(text, locations),
        restrictions=None,
        card_requirements=falabella_card_requirements(" ".join(part for part in [details, conditions] if part)),
        conditions=conditions,
        raw_title=details or offer_title,
        raw_info=text,
    )


def scrape_banco_falabella_benefits(
    category_urls: tuple[str, ...] = DEFAULT_CATEGORY_URLS,
    headless: bool = True,
    limit: int | None = None,
) -> list[Benefit]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        try:
            page = browser.new_page(
                viewport={"width": 1440, "height": 1200},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )

            detail_urls: list[str] = []
            for category_url in category_urls:
                remaining = None if limit is None else max(limit - len(detail_urls), 0)
                if remaining == 0:
                    break
                progress(f"Collecting Banco Falabella URLs from {category_url}")
                for detail_url in collect_detail_urls(page, category_url, limit=remaining):
                    if detail_url not in detail_urls:
                        detail_urls.append(detail_url)
                progress(f"Found {len(detail_urls)} Banco Falabella benefit URLs...")

            if not detail_urls:
                raise RuntimeError("No Banco Falabella detail URLs were found.")
            finish_progress()

            benefits: list[Benefit] = []
            total = len(detail_urls)
            for index, detail_url in enumerate(detail_urls, start=1):
                progress(f"Parsing Banco Falabella benefit {index}/{total}: {detail_url}")
                benefit = parse_detail_page(page, detail_url)
                if benefit:
                    benefits.append(benefit)
            finish_progress()
            return benefits
        finally:
            browser.close()


def write_json(benefits: list[Benefit], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps([benefit.to_dict() for benefit in benefits], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Banco Falabella restaurant and antojos benefits.")
    parser.add_argument("--category-url", action="append", dest="category_urls")
    parser.add_argument("--output", default="data/banco_falabella_restaurantes_antojos.json")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of detail pages to scrape.")
    parser.add_argument("--headed", action="store_true", help="Run Chromium with a visible window.")
    args = parser.parse_args()

    category_urls = tuple(args.category_urls) if args.category_urls else DEFAULT_CATEGORY_URLS
    benefits = scrape_banco_falabella_benefits(category_urls, headless=not args.headed, limit=args.limit)
    write_json(benefits, Path(args.output))
    print(f"Wrote {len(benefits)} benefits to {args.output}")


if __name__ == "__main__":
    main()
