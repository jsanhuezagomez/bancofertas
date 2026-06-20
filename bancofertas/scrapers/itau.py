from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
import time
from urllib.parse import urljoin

from playwright.sync_api import BrowserContext, Page, sync_playwright

from bancofertas.models import Benefit
from bancofertas.parsing import (
    extract_addresses,
    infer_location_status,
    normalize_text,
    parse_card_requirements,
    parse_channel,
    parse_discount,
    parse_promotion_day,
    parse_valid_until,
)
from bancofertas.scrapers.common import write_json


BANK_NAME = "Itaú"
DEFAULT_URL = "https://itaubeneficios.cl/beneficios/beneficios-y-descuentos/ruta-gourmet/"
DEFAULT_PROFILE_DIR = Path("data/browser-profiles/itau")
DETAIL_PATH_PATTERN = re.compile(
    r"^/(?:lunes|martes|miercoles|miércoles|jueves|viernes|sabado|sábado|domingo)-gourmet/[^/]+/?$",
    re.IGNORECASE,
)
BLOCKED_TEXT_MARKERS = (
    "just a moment",
    "enable javascript and cookies",
    "access denied",
    "performing security verification",
    "security service to protect against malicious bots",
    "verifies you are not a bot",
    "performance and security by cloudflare",
    "ray id:",
)


def is_access_blocked(text: str) -> bool:
    normalized = text.lower()
    return any(marker in normalized for marker in BLOCKED_TEXT_MARKERS)


def wait_for_site_access(
    page: Page,
    headed: bool,
    timeout_seconds: int = 180,
    require_discount: bool = False,
) -> str:
    deadline = time.monotonic() + (timeout_seconds if headed else 12)
    message_shown = False
    stable_reads = 0

    while True:
        text = page.locator("body").inner_text(timeout=20_000)
        blocked = is_access_blocked(text)
        has_expected_content = not require_discount or parse_discount(text) is not None

        if not blocked and has_expected_content:
            stable_reads += 1
        else:
            stable_reads = 0

        # Cloudflare can replace the real DOM shortly after domcontentloaded.
        # Requiring two consecutive valid reads avoids accepting that transition.
        if stable_reads >= 2:
            return text
        if time.monotonic() >= deadline:
            mode = "headed" if headed else "headless"
            expected = " a valid offer" if require_discount else ""
            raise RuntimeError(
                f"Itaú did not load{expected} in the {mode} browser session. "
                "Retry with --headed and complete any browser validation if it appears."
            )
        if headed and blocked and not message_shown:
            print(
                "Itaú requested browser validation. Complete it in Chrome; "
                "the scraper will continue automatically.",
                file=sys.stderr,
                flush=True,
            )
            message_shown = True
        page.wait_for_timeout(1_500)


def collect_detail_urls(page: Page, category_url: str) -> list[str]:
    links = page.locator("a").evaluate_all(
        """links => links.map(link => ({
            href: link.getAttribute('href') || '',
            text: (link.innerText || '').trim(),
            parentText: (link.closest('article, li, .card, [class*="card"], [class*="beneficio"]')?.innerText || '').trim()
        }))"""
    )
    urls: list[str] = []
    for link in links:
        text = f"{link['text']} {link['parentText']}"
        href = urljoin(category_url, link["href"])
        parsed_path = "/" + href.split("itaubeneficios.cl/", 1)[-1].split("?", 1)[0].lstrip("/")
        if not DETAIL_PATH_PATTERN.match(parsed_path):
            continue
        if "%" in text or "descuento" in text.lower() or "dcto" in text.lower():
            if href.startswith("https://itaubeneficios.cl/") and href not in urls:
                urls.append(href)
    return urls


def extract_merchant(page: Page, url: str) -> str:
    for selector in ("h1", "main h2", "article h2"):
        heading = page.locator(selector).first
        if heading.count():
            text = normalize_text(heading.inner_text(timeout=10_000))
            if text:
                return text
    return url.rstrip("/").split("/")[-1].replace("-", " ").title()


def parse_detail_page(page: Page, url: str, headed: bool = False) -> Benefit:
    page.goto(url, wait_until="domcontentloaded", timeout=90_000)
    text = wait_for_site_access(page, headed=headed, require_discount=True)
    merchant = extract_merchant(page, url)
    addresses = extract_addresses(text)
    conditions = normalize_text(text)
    discount = parse_discount(text)
    if is_access_blocked(text) or merchant.lower() in {"itaubeneficios.cl", "itaú beneficios"}:
        raise RuntimeError(f"Itaú returned a security verification page for {url}.")
    if not discount:
        raise RuntimeError(f"Itaú detail page has no detectable discount and will not be saved: {url}")

    return Benefit(
        bank=BANK_NAME,
        source_url=url,
        merchant=merchant,
        discount=discount,
        promotion_day=parse_promotion_day(text),
        channel=parse_channel(text),
        valid_until=parse_valid_until(text),
        addresses=addresses,
        location_status=infer_location_status(text, addresses),
        restrictions=None,
        card_requirements=parse_card_requirements(text + " Banco Itaú"),
        conditions=conditions,
        raw_title=None,
        raw_info=text,
    )


def scrape_itau_benefits(
    category_url: str = DEFAULT_URL,
    headless: bool = True,
    limit: int | None = None,
    browser_channel: str | None = "chrome",
    profile_dir: Path = DEFAULT_PROFILE_DIR,
) -> list[Benefit]:
    with sync_playwright() as playwright:
        profile_dir.mkdir(parents=True, exist_ok=True)
        launch_options: dict[str, object] = {
            "headless": headless,
            "viewport": {"width": 1440, "height": 1200},
        }
        if browser_channel:
            launch_options["channel"] = browser_channel
        context: BrowserContext = playwright.chromium.launch_persistent_context(
            str(profile_dir),
            **launch_options,
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(category_url, wait_until="domcontentloaded", timeout=90_000)
            wait_for_site_access(page, headed=not headless)
            page.wait_for_timeout(3_000)

            urls = collect_detail_urls(page, category_url)
            if limit is not None:
                urls = urls[:limit]
            if not urls:
                raise RuntimeError("No Itaú Ruta Gourmet detail URLs were found.")
            benefits = [parse_detail_page(page, url, headed=not headless) for url in urls]
            if not benefits:
                raise RuntimeError("Itaú produced no valid benefits; the output file was not changed.")
            return benefits
        finally:
            context.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Itaú Ruta Gourmet benefits.")
    parser.add_argument("--category-url", default=DEFAULT_URL)
    parser.add_argument("--output", default="data/itau_ruta_gourmet.json")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument(
        "--browser-channel",
        default="chrome",
        help="Playwright browser channel. Use an empty value to use bundled Chromium.",
    )
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=DEFAULT_PROFILE_DIR,
        help="Persistent Chrome profile used to retain validation cookies.",
    )
    args = parser.parse_args()
    benefits = scrape_itau_benefits(
        args.category_url,
        headless=not args.headed,
        limit=args.limit,
        browser_channel=args.browser_channel or None,
        profile_dir=args.profile_dir,
    )
    write_json(benefits, Path(args.output))
    print(f"Wrote {len(benefits)} benefits to {args.output}")


if __name__ == "__main__":
    main()
