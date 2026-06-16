from bancofertas.scrapers.banco_falabella import (
    extract_locations,
    infer_falabella_location_status,
    match_card_titles_to_detail_urls,
    parse_falabella_discount,
)


def test_parse_falabella_discount_prefers_detail_discount_line():
    details = "Descuento: 40% dcto sin tope con CMR Elite los martes presencial"
    fallback = "Hasta 40% DESCUENTO"

    assert parse_falabella_discount(details, fallback) == "40%"


def test_parse_falabella_discount_falls_back_to_card_text():
    assert parse_falabella_discount(None, "Hasta 20% DESCUENTO") == "20%"


def test_match_card_titles_only_keeps_visible_category_cards():
    card_titles = [
        "Descuento en Restaurante Romaria",
        "Descuento en Restaurante Holy Moly",
    ]
    embedded_links = [
        ("Romaria - Lunes", "https://www.bancofalabella.cl/descuentos/detalle/romaria"),
        ("Holy Moly", "https://www.bancofalabella.cl/descuentos/detalle/holy-moly"),
        ("Lipigas CMR Puntos", "https://www.bancofalabella.cl/descuentos/detalle/lipigas-cmrpuntos"),
        ("5aSec", "https://www.bancofalabella.cl/descuentos/detalle/5asec"),
    ]

    assert match_card_titles_to_detail_urls(card_titles, embedded_links) == [
        "https://www.bancofalabella.cl/descuentos/detalle/romaria",
        "https://www.bancofalabella.cl/descuentos/detalle/holy-moly",
    ]


def test_extract_falabella_single_valid_local():
    text = """
    Conoce el detalle
    Válido en locales:
    Parque Arauco
    ¿Sabes qué es Badass?
    """

    locations = extract_locations(text)

    assert locations == [
        {
            "address": "Parque Arauco",
            "address_lines": ["Parque Arauco"],
            "region": None,
            "comuna": None,
            "raw": "Parque Arauco",
        }
    ]
    assert infer_falabella_location_status(text, locations) == "specific"


def test_extract_falabella_multiple_valid_local_lines_as_chain():
    text = """
    Conoce el detalle
    Válido en locales:
    Mall Plaza Egaña: lunes a viernes
    Mall Alto Las Condes: lunes a jueves
    Mall Plaza norte: lunes a viernes
    ¿Sabes qué es Barra Chalaca?
    """

    locations = extract_locations(text)

    assert locations == []
    assert infer_falabella_location_status(text, locations) == "multiple"


def test_falabella_generic_location_without_valid_local_lines_is_missing():
    text = """
    Modalidad:
    Online
    Delivery
    Ubicación:
    Región Metropolitana de Santiago, 13+
    Condiciones:
    Válido solo para clientes nuevos Rappi
    """

    locations = extract_locations(text)

    assert locations == []
    assert infer_falabella_location_status(text, locations) == "missing"
