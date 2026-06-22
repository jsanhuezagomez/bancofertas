from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from bancofertas.models import Benefit
from bancofertas.parsing import MONTHS, normalize_text, strip_accents


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def progress_line(label: str, current: int | None = None, total: int | None = None) -> None:
    if current is not None and total is not None:
        message = f"[{label}] {current}/{total}"
    else:
        message = f"[{label}]"
    print(message, file=sys.stderr, flush=True)


def fetch_text(url: str, headers: dict[str, str] | None = None, timeout: int = 60) -> str:
    request_headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/json"}
    request_headers.update(headers or {})
    request = Request(url, headers=request_headers)
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")


def fetch_json(url: str, headers: dict[str, str] | None = None) -> dict[str, object]:
    return json.loads(fetch_text(url, headers=headers))


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    return normalize_text(BeautifulSoup(value, "html.parser").get_text(" ", strip=True))


def parse_chilean_date(value: str | None) -> str | None:
    if not value:
        return None

    normalized = strip_accents(normalize_text(value)).lower()
    match = re.search(
        r"(?P<day>\d{1,2})\s+(?:de\s+)?(?P<month>[a-z]+)\s+(?:de\s+)?(?P<year>\d{4})",
        normalized,
    )
    if not match:
        return None

    month = MONTHS.get(match.group("month"))
    if not month:
        return None
    return f"{match.group('year')}-{month}-{int(match.group('day')):02d}"


def iso_datetime_to_chile_date(value: str | None) -> str | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(ZoneInfo("America/Santiago")).date().isoformat()


def write_json(benefits: list[Benefit], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps([benefit.to_dict() for benefit in benefits], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

