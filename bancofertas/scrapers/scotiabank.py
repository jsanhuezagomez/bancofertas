from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from bancofertas.models import Benefit
from bancofertas.parsing import parse_card_requirements, parse_channel, parse_discount, parse_promotion_day
from bancofertas.scrapers.common import fetch_text, html_to_text, parse_chilean_date, write_json


BANK_NAME = "Scotiabank"
DEFAULT_URL = "https://www.scotiarewards.cl/scclubfront/categoria/platosycomida/rutagourmet"
REGIONS = {
    1: "Región de Tarapacá",
    2: "Región de Antofagasta",
    3: "Región de Atacama",
    4: "Región de Coquimbo",
    5: "Región de Valparaíso",
    6: "Región de O'Higgins",
    7: "Región del Maule",
    8: "Región del Biobío",
    9: "Región de La Araucanía",
    10: "Región de Los Lagos",
    11: "Región de Aysén",
    12: "Región de Magallanes",
    13: "Región Metropolitana",
    14: "Región de Los Ríos",
    15: "Región de Arica y Parinacota",
    16: "Región de Ñuble",
}


def extract_embedded_sites(html: str) -> list[dict[str, object]]:
    decoder = json.JSONDecoder()
    sites: list[dict[str, object]] = []
    for variable in ("sitiosSantiago", "sitiosRegiones"):
        match = re.search(rf"const\s+{variable}\s*=\s*", html)
        if not match:
            continue
        value, _ = decoder.raw_decode(html[match.end():])
        sites.extend(value)
    return sites


def parse_scotiabank_site(site: dict[str, object], category_url: str = DEFAULT_URL) -> Benefit:
    description = html_to_text(str(site.get("descripcion") or ""))
    specialty = str(site.get("especialidad") or "")
    discount_label = str(site.get("telefono") or "")
    source_text = " ".join(part for part in [discount_label, specialty, description] if part)
    address = str(site.get("direccion") or "").strip()
    region = REGIONS.get(int(site.get("id_region") or 0))
    raw_commune = description.split("|")[2].strip() if "|" in description and len(description.split("|")) > 2 else ""
    locations = []
    if address:
        locations.append({
            "address": address,
            "address_lines": [part.strip() for part in address.split("|") if part.strip()],
            "region": region,
            "comuna": raw_commune or None,
            "raw": address,
        })

    site_id = site.get("id_sitio")
    source_url = f"{category_url}?beneficio={site_id}" if site_id else category_url
    return Benefit(
        bank=BANK_NAME,
        source_url=source_url,
        merchant=str(site.get("nombre") or "Restaurante Scotiabank"),
        discount=parse_discount(discount_label or source_text),
        promotion_day=parse_promotion_day(specialty or source_text),
        channel=parse_channel(description) or "presencial",
        valid_until=parse_chilean_date(description),
        addresses=locations,
        location_status="specific" if locations else "missing",
        restrictions=None,
        card_requirements=parse_card_requirements(description + " Banco Scotiabank"),
        conditions=description or None,
        raw_title=" ".join(part for part in [discount_label, specialty] if part),
        raw_info=source_text,
    )


def scrape_scotiabank_benefits(category_url: str = DEFAULT_URL, limit: int | None = None) -> list[Benefit]:
    sites = extract_embedded_sites(fetch_text(category_url))
    if not sites:
        raise RuntimeError("No embedded Ruta Gourmet offers were found.")
    if limit is not None:
        sites = sites[:limit]
    return [parse_scotiabank_site(site, category_url) for site in sites]


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Scotiabank Ruta Gourmet benefits.")
    parser.add_argument("--category-url", default=DEFAULT_URL)
    parser.add_argument("--output", default="data/scotiabank_ruta_gourmet.json")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    benefits = scrape_scotiabank_benefits(args.category_url, limit=args.limit)
    write_json(benefits, Path(args.output))
    print(f"Wrote {len(benefits)} benefits to {args.output}")


if __name__ == "__main__":
    main()
