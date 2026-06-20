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

Banco de Chile abre Chromium visible por defecto porque normalmente bloquea o no carga correctamente el widget en modo headless. `--headed` sigue aceptándose por compatibilidad, pero ya no es necesario:

```bash
python -m bancofertas.scrapers.banco_chile --limit 20 --output data/banco_chile_sabores_sample.json
```

Para probar explícitamente sin ventana puedes usar `--headless`, aunque esa modalidad puede no encontrar ofertas.

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

## Nuevos bancos

BCI, Santander y Scotiabank consumen las mismas fuentes JSON públicas que usan sus frontends, por lo que no requieren Playwright:

```bash
python -m bancofertas.scrapers.bci --output data/bci_restaurantes.json
python -m bancofertas.scrapers.santander --output data/santander_sabores.json
python -m bancofertas.scrapers.scotiabank --output data/scotiabank_ruta_gourmet.json
```

Santander intenta primero el JSON directamente. Si el servidor rechaza el cliente HTTP, cambia automáticamente a Google Chrome mediante Playwright.

BancoEstado e Itaú usan navegador por sus protecciones adaptativas y/o renderizado. El bloqueo puede depender de la IP, cookies y reputación de la sesión, por lo que no necesariamente aparecerá en un navegador normal:

```bash
python -m bancofertas.scrapers.banco_estado --output data/banco_estado_sabores.json
python -m bancofertas.scrapers.itau --output data/itau_ruta_gourmet.json
```

Si alguno bloquea Chromium headless:

```bash
python -m bancofertas.scrapers.banco_estado --headed --output data/banco_estado_sabores.json
python -m bancofertas.scrapers.itau --headed --output data/itau_ruta_gourmet.json
```

Santander, BancoEstado e Itaú usan Google Chrome instalado en el sistema por defecto, así que no necesitan el Chromium descargado por Playwright. Itaú guarda su perfil en `data/browser-profiles/itau`: si aparece una validación, complétala en la ventana y el scraper continuará, reutilizando esas cookies en las páginas siguientes y futuras corridas. Las pantallas de seguridad y páginas sin descuento se rechazan y no se escriben como ofertas. Para usar el Chromium instalado por Playwright, agrega `--browser-channel ""`.

Todos aceptan `--limit N` para corridas de prueba. La web intenta cargar todos los archivos anteriores desde `/data`; si uno todavía no existe, continúa con los demás.

## Tests

```bash
pytest
```
