from __future__ import annotations

import re
import unicodedata


DAY_PATTERN = re.compile(
    r"\b(lunes|martes|miercoles|miércoles|jueves|viernes|sabado|sábado|domingo|"
    r"lun(?:es)?|mar(?:tes)?|mie(?:rcoles)?|mié(?:rcoles)?|jue(?:ves)?|vie(?:rnes)?|"
    r"sab(?:ado)?|sáb(?:ado)?|dom(?:ingo)?)\b",
    re.IGNORECASE,
)

DISCOUNT_PATTERN = re.compile(
    r"(?:(?:hasta|desde)\s+)?\d{1,3}\s*%\s*(?:dcto|dto|descuento)?",
    re.IGNORECASE,
)

VALID_UNTIL_PATTERN = re.compile(
    r"Promoci[oó]n v[aá]lida hasta el\s+([^.\n]+)",
    re.IGNORECASE,
)


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def strip_accents(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFD", value)
        if unicodedata.category(char) != "Mn"
    )


def parse_discount(text: str) -> str | None:
    match = DISCOUNT_PATTERN.search(text)
    return normalize_text(match.group(0)) if match else None


def parse_promotion_day(text: str) -> str | None:
    matches = [normalize_text(match.group(0)).lower() for match in DAY_PATTERN.finditer(text)]
    if not matches:
        return None

    seen: list[str] = []
    for day in matches:
        normalized = strip_accents(day)
        canonical = {
            "lun": "lunes",
            "mar": "martes",
            "mie": "miercoles",
            "jue": "jueves",
            "vie": "viernes",
            "sab": "sabado",
            "dom": "domingo",
        }.get(normalized[:3], normalized)

        if canonical not in seen:
            seen.append(canonical)

    return ", ".join(seen)


def parse_channel(text: str) -> str | None:
    normalized = strip_accents(text).lower()
    has_delivery = any(term in normalized for term in ["delivery", "online", "web", "app"])
    has_presencial = any(term in normalized for term in ["presencial", "local", "tienda", "salon"])

    if has_delivery and has_presencial:
        return "ambos"
    if has_delivery:
        return "delivery"
    if has_presencial:
        return "presencial"
    return None


def parse_valid_until(text: str) -> str | None:
    match = VALID_UNTIL_PATTERN.search(text)
    return normalize_text(match.group(1)) if match else None


def extract_offer_title(merchant: str, text: str) -> str | None:
    normalized = normalize_text(text)
    merchant_index = normalized.lower().find(merchant.lower())

    if merchant_index == -1:
        match = DISCOUNT_PATTERN.search(normalized)
        if not match:
            return None
        start = max(0, match.start() - 80)
        end = min(len(normalized), match.end() + 80)
        return normalize_text(normalized[start:end])

    after_merchant = normalized[merchant_index + len(merchant):]
    valid_index = after_merchant.lower().find("promoción válida")
    candidate = after_merchant[:valid_index] if valid_index != -1 else after_merchant[:160]
    candidate = normalize_text(candidate)
    return candidate or None


def extract_addresses(text: str) -> list[dict[str, object]]:
    lines = [normalize_text(line) for line in text.splitlines()]
    candidates = [
        line for line in lines
        if re.search(r"\b(av\.?|avenida|calle|pasaje|local|mall|strip center|ruta)\b", line, re.IGNORECASE)
    ]

    deduped: list[str] = []
    for candidate in candidates:
        if candidate not in deduped:
            deduped.append(candidate)

    return deduped if len(deduped) <= 2 else []


def parse_card_requirements(text: str) -> dict[str, object] | None:
    cleaned = normalize_text(text)
    normalized = strip_accents(cleaned).lower()

    brand_tokens = {
        "visa": "Visa",
        "mastercard": "Mastercard",
        "american express": "American Express",
        "amex": "American Express",
    }
    product_tokens = {
        "cmr": "CMR",
    }

    brands = [label for token, label in brand_tokens.items() if token in normalized]
    products = [label for token, label in product_tokens.items() if token in normalized]
    tiers = [label for token, label in CARD_TIERS.items() if token in normalized]
    card_types = [label for token, label in CARD_TYPES.items() if token in normalized]

    if products and "crédito" not in card_types:
        card_types.insert(0, "crédito")

    if not brands and not products and not tiers and not card_types:
        return None

    banks: list[str] = []
    if "banco de chile" in normalized:
        banks.append("Banco de Chile")
    if "banco edwards" in normalized:
        banks.append("Banco Edwards")
    if "banco falabella" in normalized:
        banks.append("Banco Falabella")

    terms = [*brand_tokens, *product_tokens, *CARD_TIERS, "credito", "debito"]
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", cleaned)
        if any(term in strip_accents(sentence).lower() for term in terms)
    ]

    return {
        "brands": brands,
        "products": products,
        "tiers": tiers,
        "types": card_types,
        "banks": banks,
        "raw": " ".join(sentences) if sentences else cleaned,
    }


def parse_promotion_day(text: str) -> str | None:
    normalized_text = strip_accents(normalize_text(text)).lower()
    all_days = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

    if "todos los dias" in normalized_text:
        return ", ".join(all_days)

    token_map = {
        "lu": "lunes",
        "lun": "lunes",
        "lunes": "lunes",
        "ma": "martes",
        "mar": "martes",
        "martes": "martes",
        "mi": "miércoles",
        "mie": "miércoles",
        "miercoles": "miércoles",
        "ju": "jueves",
        "jue": "jueves",
        "jueves": "jueves",
        "vi": "viernes",
        "vie": "viernes",
        "viernes": "viernes",
        "sa": "sábado",
        "sab": "sábado",
        "sabado": "sábado",
        "do": "domingo",
        "dom": "domingo",
        "domingo": "domingo",
    }

    matches = re.findall(
        r"\b(lunes|martes|miercoles|jueves|viernes|sabado|domingo|lun|mar|mie|jue|vie|sab|dom|lu|ma|mi|ju|vi|sa|do)\b",
        normalized_text,
    )
    if not matches:
        return None

    seen: list[str] = []
    for match in matches:
        canonical = token_map[match]
        if canonical not in seen:
            seen.append(canonical)

    return ", ".join(seen)


def parse_promotion_day(text: str) -> str | None:
    normalized_text = strip_accents(normalize_text(text)).lower()
    all_days = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

    if "todos los dias" in normalized_text:
        return ", ".join(all_days)

    token_map = {
        "lu": "lunes",
        "lun": "lunes",
        "lunes": "lunes",
        "ma": "martes",
        "mar": "martes",
        "martes": "martes",
        "mi": "miércoles",
        "mie": "miércoles",
        "miercoles": "miércoles",
        "ju": "jueves",
        "jue": "jueves",
        "jueves": "jueves",
        "vi": "viernes",
        "vie": "viernes",
        "viernes": "viernes",
        "sa": "sábado",
        "sab": "sábado",
        "sabado": "sábado",
        "do": "domingo",
        "dom": "domingo",
        "domingo": "domingo",
    }

    matches = re.findall(
        r"\b(lunes|martes|miercoles|jueves|viernes|sabado|domingo|lun|mar|mie|jue|vie|sab|dom|lu|ma|mi|ju|vi|sa|do)\b",
        normalized_text,
    )
    if not matches:
        return None

    seen: list[str] = []
    for match in matches:
        canonical = token_map[match]
        if canonical not in seen:
            seen.append(canonical)

    return ", ".join(seen)


def parse_promotion_day(text: str) -> str | None:
    normalized_text = strip_accents(normalize_text(text)).lower()
    all_days = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

    if "todos los dias" in normalized_text:
        return ", ".join(all_days)

    token_map = {
        "lu": "lunes",
        "lun": "lunes",
        "lunes": "lunes",
        "ma": "martes",
        "mar": "martes",
        "martes": "martes",
        "mi": "miércoles",
        "mie": "miércoles",
        "miercoles": "miércoles",
        "ju": "jueves",
        "jue": "jueves",
        "jueves": "jueves",
        "vi": "viernes",
        "vie": "viernes",
        "viernes": "viernes",
        "sa": "sábado",
        "sab": "sábado",
        "sabado": "sábado",
        "do": "domingo",
        "dom": "domingo",
        "domingo": "domingo",
    }

    matches = re.findall(
        r"\b(lunes|martes|miercoles|jueves|viernes|sabado|domingo|lun|mar|mie|jue|vie|sab|dom|lu|ma|mi|ju|vi|sa|do)\b",
        normalized_text,
    )
    if not matches:
        return None

    seen: list[str] = []
    for match in matches:
        canonical = token_map[match]
        if canonical not in seen:
            seen.append(canonical)

    return ", ".join(seen)


def parse_promotion_day(text: str) -> str | None:
    normalized_text = strip_accents(normalize_text(text)).lower()
    all_days = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

    if "todos los dias" in normalized_text or "todos los días" in normalize_text(text).lower():
        return ", ".join(all_days)

    token_map = {
        "lu": "lunes",
        "lun": "lunes",
        "lunes": "lunes",
        "ma": "martes",
        "mar": "martes",
        "martes": "martes",
        "mi": "miércoles",
        "mie": "miércoles",
        "miercoles": "miércoles",
        "ju": "jueves",
        "jue": "jueves",
        "jueves": "jueves",
        "vi": "viernes",
        "vie": "viernes",
        "viernes": "viernes",
        "sa": "sábado",
        "sab": "sábado",
        "sabado": "sábado",
        "do": "domingo",
        "dom": "domingo",
        "domingo": "domingo",
    }

    matches = re.findall(
        r"\b(lunes|martes|miercoles|jueves|viernes|sabado|domingo|lun|mar|mie|jue|vie|sab|dom|lu|ma|mi|ju|vi|sa|do)\b",
        normalized_text,
    )
    if not matches:
        return None

    seen: list[str] = []
    for match in matches:
        canonical = token_map[match]
        if canonical not in seen:
            seen.append(canonical)

    return ", ".join(seen)


def parse_card_requirements(text: str) -> dict[str, object] | None:
    cleaned = normalize_text(text)
    normalized = strip_accents(cleaned).lower()

    brand_tokens = {
        "visa": "Visa",
        "mastercard": "Mastercard",
        "american express": "American Express",
        "amex": "American Express",
    }
    product_tokens = {
        "cmr": "CMR",
    }

    brands = [label for token, label in brand_tokens.items() if token in normalized]
    products = [label for token, label in product_tokens.items() if token in normalized]
    tiers = [label for token, label in CARD_TIERS.items() if token in normalized]
    card_types = [label for token, label in CARD_TYPES.items() if token in normalized]

    if products and "crédito" not in card_types:
        card_types.insert(0, "crédito")

    if not brands and not products and not tiers and not card_types:
        return None

    banks: list[str] = []
    if "banco de chile" in normalized:
        banks.append("Banco de Chile")
    if "banco edwards" in normalized:
        banks.append("Banco Edwards")
    if "banco falabella" in normalized:
        banks.append("Banco Falabella")

    terms = [*brand_tokens, *product_tokens, *CARD_TIERS, "credito", "debito"]
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", cleaned)
        if any(term in strip_accents(sentence).lower() for term in terms)
    ]

    return {
        "brands": brands,
        "products": products,
        "tiers": tiers,
        "types": card_types,
        "banks": banks,
        "raw": " ".join(sentences) if sentences else cleaned,
    }


# Final normalized overrides used by all scrapers. These keep card products like
# CMR separate from network brands like Visa or Mastercard.
def repair_text(value: str) -> str:
    value = value.translate(INVISIBLE_CHARS).replace("\xa0", " ")
    if not any(marker in value for marker in ["Ã", "Â"]):
        return value

    try:
        return value.encode("latin1").decode("utf-8")
    except UnicodeError:
        return value


def parse_card_requirements(text: str) -> dict[str, object] | None:
    cleaned = normalize_text(text)
    normalized = strip_accents(cleaned).lower()

    brand_tokens = {
        "visa": "Visa",
        "mastercard": "Mastercard",
        "american express": "American Express",
        "amex": "American Express",
    }
    product_tokens = {
        "cmr": "CMR",
    }

    brands = [label for token, label in brand_tokens.items() if token in normalized]
    products = [label for token, label in product_tokens.items() if token in normalized]
    tiers = [label for token, label in CARD_TIERS.items() if token in normalized]
    card_types = [label for token, label in CARD_TYPES.items() if token in normalized]

    if products and "crédito" not in card_types:
        card_types.insert(0, "crédito")

    if not brands and not products and not tiers and not card_types:
        return None

    banks: list[str] = []
    if "banco de chile" in normalized:
        banks.append("Banco de Chile")
    if "banco edwards" in normalized:
        banks.append("Banco Edwards")
    if "banco falabella" in normalized:
        banks.append("Banco Falabella")

    terms = [*brand_tokens, *product_tokens, *CARD_TIERS, "credito", "debito"]
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", cleaned)
        if any(term in strip_accents(sentence).lower() for term in terms)
    ]

    return {
        "brands": brands,
        "products": products,
        "tiers": tiers,
        "types": card_types,
        "banks": banks,
        "raw": " ".join(sentences) if sentences else cleaned,
    }


# Normalized parser versions. They intentionally shadow the first implementation above:
# keeping them together here avoids carrying fragile mojibake regexes while this scraper
# grows to support more banks.
INVISIBLE_CHARS = str.maketrans("", "", "\u200b\u200c\u200d\ufeff")

DAY_CANONICAL = {
    "lun": "lunes",
    "lunes": "lunes",
    "mar": "martes",
    "martes": "martes",
    "mie": "miércoles",
    "miercoles": "miércoles",
    "jue": "jueves",
    "jueves": "jueves",
    "vie": "viernes",
    "viernes": "viernes",
    "sab": "sábado",
    "sabado": "sábado",
    "dom": "domingo",
    "domingo": "domingo",
}

MONTHS = {
    "enero": "01",
    "febrero": "02",
    "marzo": "03",
    "abril": "04",
    "mayo": "05",
    "junio": "06",
    "julio": "07",
    "agosto": "08",
    "septiembre": "09",
    "setiembre": "09",
    "octubre": "10",
    "noviembre": "11",
    "diciembre": "12",
}

CARD_BRANDS = {
    "cmr": "CMR",
    "visa": "Visa",
    "mastercard": "Mastercard",
    "american express": "American Express",
    "amex": "American Express",
}

CARD_TIERS = {
    "elite": "Elite",
    "infinite": "Infinite",
    "signature": "Signature",
    "platinum": "Platinum",
    "gold": "Gold",
    "black": "Black",
}

CARD_TYPES = {
    "credito": "crédito",
    "debito": "débito",
}

NORMALIZED_DAY_PATTERN = re.compile(
    r"\b(lunes|martes|miercoles|jueves|viernes|sabado|domingo|lun|mar|mie|jue|vie|sab|dom)\b"
)

NORMALIZED_DISCOUNT_PATTERN = re.compile(
    r"\b(?P<prefix>hasta|desde)?\s*(?P<amount>\d{1,3})\s*%\s*(?:dcto|dto|descuento)?(?=\W|$)",
    re.IGNORECASE,
)

NORMALIZED_VALID_UNTIL_PATTERN = re.compile(
    r"(?:promocion valida|valido|valida)(?:[^.\n]{0,120}?)\bhasta\s+(?:el\s+)?"
    r"(?P<day>\d{1,2})\s+(?:de\s+)?(?P<month>[a-z]+)\s+(?:de\s+)?(?P<year>\d{4})",
    re.IGNORECASE,
)

NORMALIZED_VALID_RANGE_PATTERN = re.compile(
    r"(?:promocion valida|valido|valida)(?:[^.\n]{0,80}?)\bdesde\s+(?:el\s+)?"
    r"\d{1,2}\s+(?:de\s+[a-z]+\s+)?(?:de\s+\d{4}\s+)?"
    r"(?:al|hasta)\s+(?:el\s+)?"
    r"(?P<day>\d{1,2})\s+(?:de\s+)?(?P<month>[a-z]+)\s+(?:de\s+)?(?P<year>\d{4})",
    re.IGNORECASE,
)


def repair_text(value: str) -> str:
    value = value.translate(INVISIBLE_CHARS).replace("\xa0", " ")
    if "Ã" not in value and "Â" not in value:
        return value

    try:
        return value.encode("latin1").decode("utf-8")
    except UnicodeError:
        return value


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", repair_text(value)).strip()


def repair_text(value: str) -> str:
    value = value.translate(INVISIBLE_CHARS).replace("\xa0", " ")
    if not any(marker in value for marker in ["Ã", "Â"]):
        return value

    try:
        return value.encode("latin1").decode("utf-8")
    except UnicodeError:
        return value


def parse_discount(text: str) -> str | None:
    match = NORMALIZED_DISCOUNT_PATTERN.search(normalize_text(text))
    if not match:
        return None

    prefix = normalize_text(match.group("prefix") or "").lower()
    amount = match.group("amount")
    return f"{prefix} {amount}%" if prefix else f"{amount}%"


def parse_promotion_day(text: str) -> str | None:
    normalized_text = strip_accents(normalize_text(text)).lower()
    matches = [match.group(0) for match in NORMALIZED_DAY_PATTERN.finditer(normalized_text)]
    if not matches:
        return None

    seen: list[str] = []
    for day in matches:
        canonical = DAY_CANONICAL[day]
        if canonical not in seen:
            seen.append(canonical)

    return ", ".join(seen)


def parse_channel(text: str) -> str | None:
    normalized = strip_accents(normalize_text(text)).lower()
    has_delivery = any(term in normalized for term in ["delivery", "despacho", "online", "web", "app"])
    has_presencial = any(term in normalized for term in ["presencial", "local", "tienda", "salon", "forma presencial"])

    if has_delivery and has_presencial:
        return "ambos"
    if has_delivery:
        return "delivery"
    if has_presencial:
        return "presencial"
    return None


def parse_card_requirements(text: str) -> dict[str, object] | None:
    cleaned = normalize_text(text)
    normalized = strip_accents(cleaned).lower()

    brands = [
        label
        for token, label in CARD_BRANDS.items()
        if token in normalized
    ]
    tiers = [
        label
        for token, label in CARD_TIERS.items()
        if token in normalized
    ]
    card_types = [
        label
        for token, label in CARD_TYPES.items()
        if token in normalized
    ]

    if not brands and not tiers and not card_types:
        return None

    banks: list[str] = []
    if "banco de chile" in normalized:
        banks.append("Banco de Chile")
    if "banco edwards" in normalized:
        banks.append("Banco Edwards")
    if "banco falabella" in normalized:
        banks.append("Banco Falabella")

    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", cleaned)
        if any(term in strip_accents(sentence).lower() for term in [*CARD_BRANDS, *CARD_TIERS, "credito", "debito"])
    ]

    return {
        "brands": brands,
        "tiers": tiers,
        "types": card_types,
        "banks": banks,
        "raw": " ".join(sentences) if sentences else cleaned,
    }


def parse_valid_until(text: str) -> str | None:
    normalized = strip_accents(normalize_text(text)).lower()
    match = NORMALIZED_VALID_UNTIL_PATTERN.search(normalized)
    if not match:
        match = NORMALIZED_VALID_RANGE_PATTERN.search(normalized)
    if not match:
        return None

    month = MONTHS.get(match.group("month"))
    if not month:
        return None

    return f"{match.group('year')}-{month}-{int(match.group('day')):02d}"


def extract_offer_title(merchant: str, text: str) -> str | None:
    normalized = normalize_text(text)
    searchable = strip_accents(normalized).lower()
    merchant_index = searchable.find(strip_accents(normalize_text(merchant)).lower())

    if merchant_index == -1:
        match = NORMALIZED_DISCOUNT_PATTERN.search(normalized)
        if not match:
            return None
        start = max(0, match.start() - 80)
        end = min(len(normalized), match.end() + 80)
        return normalize_text(normalized[start:end])

    after_merchant = normalized[merchant_index + len(merchant):]
    valid_index = strip_accents(after_merchant).lower().find("promocion valida")
    candidate = after_merchant[:valid_index] if valid_index != -1 else after_merchant[:160]
    candidate = normalize_text(candidate)
    return candidate or None


def extract_conditions(text: str) -> str | None:
    lines = [normalize_text(line) for line in repair_text(text).splitlines()]
    lines = [line for line in lines if line]

    try:
        start = next(
            index + 1
            for index, line in enumerate(lines)
            if (
                strip_accents(line).lower() == "terminos y condiciones"
                or strip_accents(line).lower().endswith(" y condiciones")
            )
        )
    except StopIteration:
        return None

    stop_prefixes = (
        "volver",
        "beneficio exclusivo",
        "lo bueno se comparte",
        "encuentra donde canjear",
    )
    condition_lines: list[str] = []
    for line in lines[start:]:
        normalized = strip_accents(line).lower()
        if normalized.startswith(stop_prefixes):
            break
        condition_lines.append(line)

    conditions = normalize_text(" ".join(condition_lines))
    return conditions or None


def _extract_address_locations(text: str) -> list[dict[str, object]]:
    lines = [normalize_text(line) for line in repair_text(text).splitlines()]
    lines = [line for line in lines if line]

    try:
        start = next(index + 1 for index, line in enumerate(lines) if strip_accents(line).lower() == "buscar")
    except StopIteration:
        return []

    stop_prefixes = (
        "beneficios relacionados",
        "ver todos los beneficios",
        "sobre nosotros",
        "informate",
    )
    ignored_lines = {"region", "comuna"}
    current: list[str] = []
    locations: list[dict[str, object]] = []
    region_aliases = {
        "rm": "Región Metropolitana",
    }

    for line in lines[start:]:
        normalized = strip_accents(line).lower()
        if normalized.startswith(stop_prefixes):
            break
        if normalized in ignored_lines:
            continue

        if " - " in line and current:
            region, comuna = [part.strip() for part in line.split(" - ", 1)]
            region = region_aliases.get(strip_accents(region).lower(), region)
            address = "\n".join(current)
            locations.append({
                "address": address,
                "address_lines": current.copy(),
                "region": region,
                "comuna": comuna,
                "raw": "\n".join([*current, line]),
            })
            current = []
            continue

        if normalized.startswith("region ") and " - " in line:
            if current:
                region, comuna = [part.strip() for part in line.split(" - ", 1)]
                address = "\n".join(current)
                locations.append({
                    "address": address,
                    "address_lines": current.copy(),
                    "region": region,
                    "comuna": comuna,
                    "raw": "\n".join([*current, line]),
                })
            current = []
            continue

        current.append(line)

    deduped: list[dict[str, object]] = []
    seen: set[str] = set()
    for location in locations:
        key = str(location["raw"])
        if key not in seen:
            seen.add(key)
            deduped.append(location)

    return deduped


def extract_addresses(text: str) -> list[dict[str, object]]:
    locations = _extract_address_locations(text)
    return locations if len(locations) <= 2 else []


def infer_location_status(text: str, addresses: list[dict[str, object]] | None = None) -> str:
    if addresses:
        return "specific"

    locations = _extract_address_locations(text)
    if len(locations) > 2:
        return "multiple"
    if locations:
        return "specific"
    return "missing"


def parse_card_requirements(text: str) -> dict[str, object] | None:
    cleaned = normalize_text(text)
    normalized = strip_accents(cleaned).lower()

    brand_tokens = {
        "visa": "Visa",
        "mastercard": "Mastercard",
        "american express": "American Express",
        "amex": "American Express",
    }
    product_tokens = {
        "cmr": "CMR",
    }

    brands = [label for token, label in brand_tokens.items() if token in normalized]
    products = [label for token, label in product_tokens.items() if token in normalized]
    tiers = [label for token, label in CARD_TIERS.items() if token in normalized]
    card_types = [label for token, label in CARD_TYPES.items() if token in normalized]

    if products and "crédito" not in card_types:
        card_types.insert(0, "crédito")

    if not brands and not products and not tiers and not card_types:
        return None

    banks: list[str] = []
    if "banco de chile" in normalized:
        banks.append("Banco de Chile")
    if "banco edwards" in normalized:
        banks.append("Banco Edwards")
    if "banco falabella" in normalized:
        banks.append("Banco Falabella")

    terms = [*brand_tokens, *product_tokens, *CARD_TIERS, "credito", "debito"]
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", cleaned)
        if any(term in strip_accents(sentence).lower() for term in terms)
    ]

    return {
        "brands": brands,
        "products": products,
        "tiers": tiers,
        "types": card_types,
        "banks": banks,
        "raw": " ".join(sentences) if sentences else cleaned,
    }


def parse_promotion_day(text: str) -> str | None:
    normalized_text = strip_accents(normalize_text(text)).lower()
    all_days = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

    if "todos los dias" in normalized_text:
        return ", ".join(all_days)

    token_map = {
        "lu": "lunes",
        "lun": "lunes",
        "lunes": "lunes",
        "ma": "martes",
        "mar": "martes",
        "martes": "martes",
        "mi": "miércoles",
        "mie": "miércoles",
        "miercoles": "miércoles",
        "ju": "jueves",
        "jue": "jueves",
        "jueves": "jueves",
        "vi": "viernes",
        "vie": "viernes",
        "viernes": "viernes",
        "sa": "sábado",
        "sab": "sábado",
        "sabado": "sábado",
        "do": "domingo",
        "dom": "domingo",
        "domingo": "domingo",
    }

    matches = re.findall(
        r"\b(lunes|martes|miercoles|jueves|viernes|sabado|domingo|lun|mar|mie|jue|vie|sab|dom|lu|ma|mi|ju|vi|sa|do)\b",
        normalized_text,
    )
    if not matches:
        return None

    seen: list[str] = []
    for match in matches:
        canonical = token_map[match]
        if canonical not in seen:
            seen.append(canonical)

    return ", ".join(seen)
