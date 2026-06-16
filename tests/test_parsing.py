from bancofertas.parsing import (
    extract_addresses,
    extract_conditions,
    extract_offer_title,
    infer_location_status,
    parse_card_requirements,
    parse_channel,
    parse_discount,
    parse_promotion_day,
    parse_valid_until,
)


def test_parse_starbucks_title_parts():
    title = "30% dto. viernes presencial"

    assert parse_discount(title) == "30%"
    assert parse_promotion_day(title) == "viernes"
    assert parse_channel(title) == "presencial"


def test_parse_valid_until_banco_chile_format():
    text = "Promoción válida hasta el 31 de diciembre de 2026. Beneficio es válido en locales..."

    assert parse_valid_until(text) == "2026-12-31"


def test_parse_valid_until_with_weekday_and_hidden_chars():
    text = "Promoción válida todos los martes hasta el 30 de junio de 20\u200d26."

    assert parse_valid_until(text) == "2026-06-30"


def test_parse_valid_until_falabella_format():
    assert parse_valid_until("Válido hasta 30 de junio de 2026") == "2026-06-30"


def test_extract_offer_title_after_merchant():
    text = """
    Starbucks
    30% dto. viernes presencial
    Promoción válida hasta el 31 de diciembre de 2026.
    """

    assert extract_offer_title("Starbucks", text) == "30% dto. viernes presencial"


def test_parse_channel_both():
    assert parse_channel("30% dto. viernes presencial y delivery") == "ambos"


def test_parse_discount_variants():
    assert parse_discount("20%") == "20%"
    assert parse_discount("20% dto") == "20%"
    assert parse_discount("20% dcto") == "20%"
    assert parse_discount("Hasta 30% descuento") == "hasta 30%"


def test_parse_promotion_day_canonical_accents():
    assert parse_promotion_day("35% dcto. miércoles presencial") == "miércoles"


def test_parse_promotion_day_falabella_abbreviations():
    assert parse_promotion_day("LU MA MI JU VI SA DO") == "lunes, martes, miércoles, jueves, viernes, sábado, domingo"


def test_parse_promotion_day_all_days():
    assert parse_promotion_day("Todos los días") == "lunes, martes, miércoles, jueves, viernes, sábado, domingo"


def test_extract_addresses_from_location_blocks():
    text = """
    Encuentra dónde canjear tu beneficio
    Región
    Región Metropolitana
    Comuna
    San Bernardo
    BUSCAR
    America 449
    local 1
    Región Metropolitana - San Bernardo
    Beneficios relacionados
    """

    assert extract_addresses(text) == [
        {
            "address": "America 449\nlocal 1",
            "address_lines": ["America 449", "local 1"],
            "region": "Región Metropolitana",
            "comuna": "San Bernardo",
            "raw": "America 449\nlocal 1\nRegión Metropolitana - San Bernardo",
        }
    ]


def test_extract_conditions_and_channel_from_terms():
    text = """
    VER CONDICIONES
    Términos y Condiciones
    Promoción válida hasta el 30 de octubre de 2026. Clientes deben solicitar el descuento al momento de pagar en forma presencial.
    Volver
    Beneficio exclusivo con tus tarjetas:
    """

    conditions = extract_conditions(text)

    assert conditions == "Promoción válida hasta el 30 de octubre de 2026. Clientes deben solicitar el descuento al momento de pagar en forma presencial."
    assert parse_channel(conditions) == "presencial"


def test_parse_card_requirements_for_visa_infinite():
    text = (
        "Pagando con Tarjetas de Credito y Debito VISA INFINITE del Banco de Chile "
        "y Banco Edwards. Tope de descuento maximo $65.000 por mesa."
    )

    assert parse_card_requirements(text) == {
        "brands": ["Visa"],
        "products": [],
        "tiers": ["Infinite"],
        "types": ["crédito", "débito"],
        "banks": ["Banco de Chile", "Banco Edwards"],
        "raw": "Pagando con Tarjetas de Credito y Debito VISA INFINITE del Banco de Chile y Banco Edwards.",
    }


def test_parse_card_requirements_for_cmr_and_falabella_debit():
    text = "40% dcto sin tope con CMR y 30% dcto sin tope con Debito Banco Falabella."

    assert parse_card_requirements(text) == {
        "brands": [],
        "products": ["CMR"],
        "tiers": [],
        "types": ["crédito", "débito"],
        "banks": ["Banco Falabella"],
        "raw": text,
    }


def test_parse_valid_until_banco_chile_range_format():
    text = "Promocion valida desde el 01 al 30 de junio de 2026. pagando con Tarjetas de Credito y Debito VISA."

    assert parse_valid_until(text) == "2026-06-30"


def test_extract_addresses_with_rm_abbreviation():
    text = """
    Encuentra donde canjear tu beneficio
    Region
    RM
    Comuna
    Providencia
    BUSCAR
    Av. Pedro de Valdivia 440
    RM - Providencia
    Beneficios relacionados
    """

    assert extract_addresses(text) == [
        {
            "address": "Av. Pedro de Valdivia 440",
            "address_lines": ["Av. Pedro de Valdivia 440"],
            "region": "Región Metropolitana",
            "comuna": "Providencia",
            "raw": "Av. Pedro de Valdivia 440\nRM - Providencia",
        }
    ]


def test_infer_location_status_multiple_when_more_than_two_addresses():
    text = """
    BUSCAR
    Av. Uno 1
    RM - Providencia
    Av. Dos 2
    RM - Las Condes
    Av. Tres 3
    RM - Santiago
    Beneficios relacionados
    """

    assert extract_addresses(text) == []
    assert infer_location_status(text) == "multiple"
