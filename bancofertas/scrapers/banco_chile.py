from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from urllib.parse import urljoin

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from bancofertas.models import Benefit
from bancofertas.parsing import (
    extract_addresses,
    extract_conditions,
    extract_offer_title,
    infer_location_status,
    normalize_text,
    parse_card_requirements,
    parse_channel,
    parse_discount,
    parse_promotion_day,
    parse_valid_until,
)


BANK_NAME = "Banco de Chile"
DEFAULT_CATEGORY_URL = "https://sitiospublicos.bancochile.cl/personas/beneficios/categoria?maincat=beneficios/sabores"
DETAIL_PATH = "/personas/beneficios/detalle/"
LOAD_MORE_LABELS = (
    "VER MÁS",
    "VER MAS",
    "CARGAR MÁS",
    "CARGAR MAS",
    "MOSTRAR MÁS",
    "MOSTRAR MAS",
)
NEXT_PAGE_LABELS = (
    "SIGUIENTE",
    "PÁGINA SIGUIENTE",
    "PAGINA SIGUIENTE",
    "NEXT",
)


def rendered_text(page: Page) -> str:
    body_text = page.locator("body").inner_text(timeout=15_000)
    return "\n".join(line.strip() for line in body_text.splitlines() if line.strip())


def progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def finish_progress() -> None:
    return None


def goto_detail_page(page: Page, url: str, attempts: int = 3) -> None:
    last_error: PlaywrightTimeoutError | None = None

    for attempt in range(1, attempts + 1):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=90_000)
            page.wait_for_timeout(1_000)
            return
        except PlaywrightTimeoutError as error:
            last_error = error
            progress(f"Retrying detail page {attempt}/{attempts}: {url}")
            page.wait_for_timeout(attempt * 2_000)

    if last_error:
        raise last_error


def collect_current_detail_urls(page: Page, category_url: str) -> list[str]:
    hrefs = page.locator("a").evaluate_all(
        """links => links
          .map(link => link.getAttribute('href'))
          .filter(Boolean)
        """
    )

    detail_urls: list[str] = []
    for href in hrefs:
        absolute = urljoin(category_url, href)
        if DETAIL_PATH in absolute and absolute not in detail_urls:
            detail_urls.append(absolute)

    return detail_urls


def click_load_more(page: Page) -> bool:
    for label in LOAD_MORE_LABELS:
        control = page.get_by_text(label, exact=False).last
        try:
            if control.count() > 0 and control.is_visible(timeout=500):
                control.click(timeout=2_000)
                page.wait_for_timeout(800)
                return True
        except PlaywrightTimeoutError:
            continue

    return False


def append_new_urls(detail_urls: list[str], next_urls: list[str]) -> None:
    for detail_url in next_urls:
        if detail_url not in detail_urls:
            detail_urls.append(detail_url)


def scroll_for_more_urls(
    page: Page,
    category_url: str,
    detail_urls: list[str],
    limit: int | None = None,
) -> None:
    stale_scrolls = 0
    max_stale_scrolls = 5

    while (limit is None or len(detail_urls) < limit) and stale_scrolls < max_stale_scrolls:
        previous_count = len(detail_urls)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1_200)
        append_new_urls(detail_urls, collect_current_detail_urls(page, category_url))
        progress(f"Found {len(detail_urls)} benefit URLs...")

        if len(detail_urls) == previous_count:
            stale_scrolls += 1
        else:
            stale_scrolls = 0


def click_next_page(page: Page) -> bool:
    candidates = [
        "a[aria-label*='Siguiente' i]",
        "button[aria-label*='Siguiente' i]",
        "a[title*='Siguiente' i]",
        "button[title*='Siguiente' i]",
        "a[rel='next']",
    ]

    for selector in candidates:
        control = page.locator(selector).last
        try:
            if control.count() > 0 and control.is_visible(timeout=500):
                control.click(timeout=2_000)
                page.wait_for_load_state("networkidle", timeout=15_000)
                return True
        except PlaywrightTimeoutError:
            continue

    for label in NEXT_PAGE_LABELS:
        control = page.get_by_text(label, exact=False).last
        try:
            if control.count() > 0 and control.is_visible(timeout=500):
                control.click(timeout=2_000)
                page.wait_for_load_state("networkidle", timeout=15_000)
                return True
        except PlaywrightTimeoutError:
            continue

    return False


def collect_detail_urls(page: Page, category_url: str, limit: int | None = None) -> list[str]:
    page.goto(category_url, wait_until="networkidle", timeout=60_000)
    page.wait_for_load_state("domcontentloaded")

    detail_urls = collect_current_detail_urls(page, category_url)
    progress(f"Found {len(detail_urls)} benefit URLs...")
    scroll_for_more_urls(page, category_url, detail_urls, limit=limit)
    pagination_steps = 0

    while (limit is None or len(detail_urls) < limit) and pagination_steps < 40:
        previous_urls = detail_urls.copy()

        if click_load_more(page):
            next_urls = collect_current_detail_urls(page, category_url)
        elif click_next_page(page):
            next_urls = collect_current_detail_urls(page, category_url)
        else:
            break

        append_new_urls(detail_urls, next_urls)
        progress(f"Found {len(detail_urls)} benefit URLs...")
        scroll_for_more_urls(page, category_url, detail_urls, limit=limit)

        pagination_steps += 1
        if detail_urls == previous_urls:
            break

    return detail_urls[:limit] if limit is not None else detail_urls


def extract_merchant(page: Page, fallback_url: str) -> str:
    heading = page.locator("h1").first
    if heading.count() > 0:
        text = normalize_text(heading.inner_text(timeout=10_000))
        if text:
            return text

    slug = fallback_url.rstrip("/").split("/")[-1]
    return slug.replace("-", " ").title()


def reveal_conditions(page: Page, current_text: str) -> str:
    if extract_conditions(current_text):
        return current_text

    button = page.get_by_text("VER CONDICIONES", exact=True)
    if button.count() == 0:
        return current_text

    button.first.click(timeout=10_000)
    page.wait_for_timeout(300)
    return rendered_text(page)


def extract_card_image_text(page: Page) -> str | None:
    values = page.locator("img").evaluate_all(
        """images => images
          .map((image) => [image.alt, image.title, image.getAttribute('aria-label'), image.src]
            .filter(Boolean)
            .join(' '))
          .filter(Boolean)
        """
    )
    card_terms = ("visa", "mastercard", "american", "infinite", "signature", "platinum", "credito", "debito")
    card_values = [
        normalize_text(value)
        for value in values
        if any(term in value.lower() for term in card_terms)
    ]
    return " ".join(card_values) if card_values else None


def parse_detail_page(page: Page, url: str) -> Benefit:
    goto_detail_page(page, url)

    text = reveal_conditions(page, rendered_text(page))
    merchant = extract_merchant(page, url)
    offer_title = extract_offer_title(merchant, text)
    offer_text = offer_title or text
    conditions = extract_conditions(text)
    card_image_text = extract_card_image_text(page)
    channel_source = conditions or offer_text
    card_source = " ".join(part for part in [conditions, card_image_text] if part)
    addresses = extract_addresses(text)

    return Benefit(
        bank=BANK_NAME,
        source_url=url,
        merchant=merchant,
        discount=parse_discount(offer_text),
        promotion_day=parse_promotion_day(offer_text),
        channel=parse_channel(channel_source),
        valid_until=parse_valid_until(text),
        addresses=addresses,
        location_status=infer_location_status(text, addresses),
        restrictions=None,
        card_requirements=parse_card_requirements(card_source),
        conditions=conditions,
        raw_title=offer_title,
        raw_info=text,
    )


def scrape_banco_chile_benefits(
    category_url: str = DEFAULT_CATEGORY_URL,
    headless: bool = False,
    limit: int | None = None,
) -> list[Benefit]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        try:
            page = browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            )
            detail_urls = collect_detail_urls(page, category_url, limit=limit)
            if not detail_urls:
                raise RuntimeError(
                    "No detail URLs were found. The Banco de Chile widget may have been blocked; "
                    "retry without --headless."
                )
            finish_progress()

            benefits: list[Benefit] = []
            total = len(detail_urls)
            for index, detail_url in enumerate(detail_urls, start=1):
                progress(f"Parsing benefit {index}/{total}: {detail_url}")
                try:
                    benefits.append(parse_detail_page(page, detail_url))
                except PlaywrightTimeoutError:
                    finish_progress()
                    print(
                        f"Skipping benefit after navigation timeout: {detail_url}",
                        file=sys.stderr,
                        flush=True,
                    )
            finish_progress()
            return benefits
        finally:
            browser.close()


def scrape_banco_chile_cafeterias(category_url: str = DEFAULT_CATEGORY_URL, headless: bool = False) -> list[Benefit]:
    return scrape_banco_chile_benefits(category_url=category_url, headless=headless)


def write_json(benefits: list[Benefit], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps([benefit.to_dict() for benefit in benefits], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Banco de Chile benefits.")
    parser.add_argument("--category-url", default=DEFAULT_CATEGORY_URL)
    parser.add_argument("--output", default="data/banco_chile_sabores.json")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of detail pages to scrape.")
    browser_mode = parser.add_mutually_exclusive_group()
    browser_mode.add_argument(
        "--headless",
        action="store_true",
        help="Run Chromium without a visible window. Banco de Chile may block this mode.",
    )
    browser_mode.add_argument(
        "--headed",
        action="store_true",
        help="Deprecated compatibility alias; visible Chromium is already the default.",
    )
    args = parser.parse_args()

    benefits = scrape_banco_chile_benefits(args.category_url, headless=args.headless, limit=args.limit)
    write_json(benefits, Path(args.output))
    print(f"Wrote {len(benefits)} benefits to {args.output}")


if __name__ == "__main__":
    main()
