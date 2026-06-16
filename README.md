# BancOfertas

Crawler para descuentos bancarios en restaurantes/cafeterias.

## Setup local

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
```

## Banco de Chile - sabores

```bash
python -m bancofertas.scrapers.banco_chile --limit 20 --output data/banco_chile_sabores_sample.json
```

Si Banco de Chile bloquea el widget en Chromium headless, prueba la misma corrida con navegador visible:

```bash
python -m bancofertas.scrapers.banco_chile --limit 20 --headed --output data/banco_chile_sabores_sample.json
```

El scraper intenta recorrer resultados con botones tipo `VER MAS` y paginacion tipo `Siguiente`. `--limit 20` corta la muestra despues de juntar 20 URLs de detalle.

Para una subcategoria especifica, por ejemplo cafeterias:

```bash
python -m bancofertas.scrapers.banco_chile --category-url "https://sitiospublicos.bancochile.cl/personas/beneficios/sabores/cafeterias" --output data/banco_chile_cafeterias.json
```

El scraper usa Playwright porque el sitio puede bloquear requests simples y parte del contenido se renderiza con JavaScript.

## Banco Falabella - restaurantes y antojos

```bash
python -m bancofertas.scrapers.banco_falabella --limit 20 --output data/banco_falabella_sample.json
```

Para la corrida completa de restaurantes y antojos:

```bash
python -m bancofertas.scrapers.banco_falabella --output data/banco_falabella_restaurantes_antojos.json
```

El scraper descarta banners o paginas agregadoras que no tengan una oferta directa con modalidad, descuento y fecha de vigencia.

## Tests

```bash
pytest
```
