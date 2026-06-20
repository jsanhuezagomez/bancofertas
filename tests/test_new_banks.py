import json

from bancofertas.scrapers.banco_estado import extract_detail_addresses, parse_listing_text
from bancofertas.scrapers.bci import is_restaurant_offer, parse_bci_offer
from bancofertas.scrapers.itau import is_access_blocked
from bancofertas.scrapers.santander import extract_feature_locations, parse_santander_promotion
from bancofertas.scrapers.scotiabank import extract_embedded_sites, parse_scotiabank_site


def test_parse_bci_restaurant_offer():
    offer = {
        "titulo": "30% de descuento",
        "subtitulo": "Con tus Tarjetas de Crédito o Débito Bci",
        "descripcion": "Válido solo para compras presenciales.",
        "legal": "No acumulable con otras promociones.",
        "fechaTermino": "2026-07-01T03:59:00.000Z",
        "slug": "majestic",
        "categorias": [{"titulo": "Restaurantes"}],
        "comercio": {"nombre": "Majestic"},
        "beneficio": {"discount": {"porcentajeDescuento": 30}},
        "deal": {"discount": {"percentage": 30}},
        "scheduling": {"dayRecurrence": ["LUNES", "MARTES"]},
    }

    assert is_restaurant_offer(offer)
    benefit = parse_bci_offer(offer)
    assert benefit.merchant == "Majestic"
    assert benefit.discount == "30%"
    assert benefit.promotion_day == "lunes, martes"
    assert benefit.valid_until == "2026-06-30"


def test_parse_santander_sabores_promotion():
    promotion = {
        "title": "Ré",
        "url": "https://banco.santander.cl/beneficios/promociones/re",
        "description": "<ul><li>Exclusivo con Tarjetas de Crédito Santander.</li><li>Válido en local.</li></ul>",
        "conditions": "No acumulable.",
        "tags": ["cat-sabores", "todos-los-domingos"],
        "custom_fields": {
            "Bajada externa": {"value": "40% dcto. todos los domingos"},
            "Bajada interna": {"value": "40% dcto. todos los domingos"},
            "Vigencia": {"value": "Hasta el 30 de junio de 2026"},
            "Región cobertura": {"value": "Región Metropolitana"},
            "Comuna cobertura": {"value": "Las Condes"},
        },
    }

    benefit = parse_santander_promotion(promotion)
    assert benefit.discount == "40%"
    assert benefit.promotion_day == "domingo"
    assert benefit.valid_until == "2026-06-30"
    assert benefit.addresses[0]["comuna"] == "Las Condes"


def test_extract_santander_location_from_feature_after_valid_local():
    description = """
    <ul>
      <li>Exclusivo con tus Tarjetas de Crédito Santander.</li>
      <li>Válido en local.</li>
      <li>AV. Manquehue norte 656, Las Condes</li>
      <li>No acumulable con otras promociones.</li>
    </ul>
    """

    assert extract_feature_locations(description) == [{
        "address": "AV. Manquehue norte 656, Las Condes",
        "address_lines": ["AV. Manquehue norte 656, Las Condes"],
        "region": None,
        "comuna": "Las Condes",
        "raw": "AV. Manquehue norte 656, Las Condes",
    }]


def test_parse_scotiabank_embedded_json():
    site = {
        "nombre": "The Loft",
        "direccion": "MUT, Las Condes",
        "telefono": "50% Dcto.",
        "especialidad": "Todos los lunes",
        "descripcion": "<p>Válido hasta el 30 de junio de 2026.|50% Dcto.|Las Condes</p>"
        "<p>Válido sólo para consumo presencial con Tarjetas de Crédito Visa Scotiabank Signature.</p>",
        "id_sitio": 638,
        "id_region": 13,
    }
    html = f"<script>const sitiosSantiago = {json.dumps([site])}; const sitiosRegiones = [];</script>"

    sites = extract_embedded_sites(html)
    benefit = parse_scotiabank_site(sites[0])
    assert benefit.merchant == "The Loft"
    assert benefit.discount == "50%"
    assert benefit.promotion_day == "lunes"
    assert benefit.valid_until == "2026-06-30"
    assert benefit.addresses[0]["region"] == "Región Metropolitana"


def test_parse_banco_estado_listing():
    text = """
    Región Metropolitana
    Martes
    50% dto.
    Cappri Pizzería
    Conoce más
    """
    benefits = parse_listing_text(text)
    assert len(benefits) == 1
    assert benefits[0].merchant == "Cappri Pizzería"
    assert benefits[0].promotion_day == "martes"
    assert benefits[0].location_status == "missing"


def test_parse_banco_estado_accepts_named_regions():
    text = """
    Región de Los Lagos
    Viernes
    40% dto.
    Restaurante Austral
    Conoce más
    """

    benefits = parse_listing_text(text)
    assert len(benefits) == 1
    assert benefits[0].merchant == "Restaurante Austral"


def test_extract_banco_estado_address_from_detail():
    text = """
    Otra Cozza
    Dirección:
    Av. Borgoño 14950, Reñaca
    Promoción válida hasta el 30 de junio de 2026.
    """

    assert extract_detail_addresses(text, "V Región")[0] == {
        "address": "Av. Borgoño 14950, Reñaca",
        "address_lines": ["Av. Borgoño 14950, Reñaca"],
        "region": "V Región",
        "comuna": "Reñaca",
        "raw": "Av. Borgoño 14950, Reñaca",
    }


def test_extract_banco_estado_keeps_all_addresses_for_chain_detection():
    text = """
    Direcciones:
    Av. Uno 100, Santiago
    Av. Dos 200, Providencia
    Av. Tres 300, Las Condes
    """

    assert len(extract_detail_addresses(text, "Región Metropolitana")) == 3


def test_extract_banco_estado_ignores_caps_and_dates_before_location_block():
    text = """
    Sólo con las Tarjetas de Crédito VISA BancoEstado. Tope $40.000.
    Válido desde 01 de junio al 31 de julio 2026.
    Locales disponibles:
    El rodeo 13052, Lo Barnechea
    Gerónimo de Alderete 1423, Vitacura.
    Más Información
    """

    addresses = extract_detail_addresses(text, "Región Metropolitana")
    assert [address["address"] for address in addresses] == [
        "El rodeo 13052, Lo Barnechea",
        "Gerónimo de Alderete 1423, Vitacura",
    ]


def test_itau_detects_cloudflare_security_verification():
    text = """
    itaubeneficios.cl
    Performing security verification
    This website uses a security service to protect against malicious bots.
    Ray ID: abc123
    Performance and Security by Cloudflare
    """

    assert is_access_blocked(text)
