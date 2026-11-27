# seo.auditor

Auditor SEO autónomo, multicliente y de costo $0. Rastrea un sitio, detecta problemas técnicos y on-page, marca señales de riesgo (grey/black hat) y reporta a una planilla de Google Sheets. Corre en GitHub Actions, sin servidores propios.

> Estado: **fase 2** (19 reglas técnicas, on-page, datos estructurados e internacional; puntaje; diff entre corridas; detección de plataforma; fixture con recall del 100%). Faltan: modo competidor completo (3), PageSpeed/Search Console (4) y señales de riesgo (5).

## Cómo funciona

```
clients/*.yaml  ──►  GitHub Actions (cron / manual)  ──►  crawler Python
                                                              │
                         ┌────────────────────────────────────┤
                         ▼                                    ▼
              Google Sheets (resumen,                CSV completo del crawl
              issues, histórico, riesgo)             en Google Drive
```

- **Autónomo:** corre por cron y por ejecución manual, sin intervención.
- **Multicliente:** una config YAML por cliente; las reglas son modulares (`rules/rules.yaml`).
- **Sin APIs de pago.** Los límites reales están en [`docs/LIMITS.md`](docs/LIMITS.md).
- **Auditoría de competencia sin infringir normas:** modo `competitor` con reglas validadas por código ([`docs/ETHICS.md`](docs/ETHICS.md)).
- **Grey/black hat:** solo detección con evidencia y nivel de riesgo. No se ejecutan esas tácticas.

## Estructura

| Ruta | Contenido |
|---|---|
| `src/seo_auditor/` | Motor: config validada, crawler, reglas, reporte y publicación a Sheets. |
| `rules/rules.yaml` | Catálogo de reglas: id, severidad, categoría, modos, fase. |
| `rules/platforms.yaml` | Límites conocidos por plataforma (solo los de alta confianza). |
| `schema/sheet_schema.json` | Contrato de las pestañas de la planilla. |
| `clients/` | Una config por cliente. `_template.yaml` es la plantilla. |
| `fixture/` | Sitio de prueba con errores plantados y `EXPECTED_ISSUES.yaml`. |
| `.github/workflows/` | `audit.yml` (auditoría) y `pages.yml` (publica el fixture). |
| `tests/` | Tests con pytest. |

## Uso

```bash
pip install -r requirements.txt && pip install -e .
pytest                                                    # 80 tests, sin red (servidores locales)
python -m seo_auditor --config clients/fixture.yaml --validate-only
python -m seo_auditor --config clients/fixture.yaml --expected fixture/EXPECTED_ISSUES.yaml
python -m seo_auditor --config clients/<cliente>.yaml --publish   # requiere GOOGLE_SERVICE_ACCOUNT_JSON
```

Códigos de salida: 0 ok · 2 config inválida · 3 faltan issues esperados · 4 falló la publicación · 5 crawl abortado.

## Reglas implementadas (fases 1 y 2)

TECH-001/002/003/004/005/006/007/008/009/010/011 · ONP-001/002/003/004/005/006 · SCH-001 · INT-001.
El resto del catálogo (`rules/rules.yaml`, señales de riesgo) está definido pero se activa en su fase;
el motor no reporta reglas que no implementa.

## Puntaje

`puntaje = 100 · exp(-densidad / 2)`, con `densidad = (suma de pesos por severidad) / (URLs rastreadas)`.
Pesos: crítico 10, alto 5, medio 2, bajo 1. No depende del tamaño del sitio, está acotado entre 0 y 100 y
excluye las señales de riesgo. La escala (`score_scale`) es la perilla de calibración y vive en
`schema/sheet_schema.json`: cambiarla cambia el significado del histórico, así que se versiona ahí.

## Diff entre corridas

Antes de escribir, el motor lee `Issues` e `Historico` de la propia planilla. Cada issue lleva una clave
estable (`issue_key`) y queda como **nuevo**, **recurrente** (conserva `primera_vez_visto`) o **resuelto**
(aparece una sola vez). Con un crawl truncado por `max_urls` no se marca nada como resuelto: un issue
ausente no prueba que se haya arreglado. Si la lectura falla, la publicación aborta en vez de escribir
con estado vacío.

## Privacidad

Este repo es público. **No se versionan** configs reales de clientes ni resultados: las credenciales van en GitHub Secrets y los datos en Sheets y Drive. Las configs reales se guardan fuera del repo (o en un repo privado de configuración).

## Plan por fases

| Fase | Entregable |
|---|---|
| 0 | Repo, reglas, esquema de planilla, fixture, workflows base (hecha) |
| 1 | Crawler base y salida a Sheets; el fixture detecta el 100% de los errores plantados (hecha) |
| 2 | Huérfanas, JSON-LD, hreflang, plataforma, puntaje y diff entre corridas (hecha) |
| 3 | Modo competidor y benchmark |
| 4 | PageSpeed/CrUX y Search Console (solo sitios autorizados) |
| 5 | Módulo de señales de riesgo |
| 6 | Empaquetado: demo anonimizada y caso de estudio |


## Modo Panel (varios sitios, datos en Drive)

Las configs reales no van al repo: viven en la planilla **Panel** (pestaña `Clientes`, una fila por sitio; se leen por nombre de columna y solo corren las filas con `activo = TRUE`). Cada fila pasa por la misma validación que un YAML (modo `client` exige `autorizado`; `competitor` fuerza robots.txt, pausa ≥ 2 s y máx. 500 URLs).

```
python -m seo_auditor --panel --panel-id <ID> [--site all|<nombre>] [--validate-only]
```
En GitHub: secret `SEO_PANEL_ID`; el job `sitios` corre en el cron semanal o con `site` en el dispatch. Un sitio que falla no frena a los demás.

- Pestaña **Crawl** en cada planilla de sitio: una fila por URL (status, indexable, title, canonical, inlinks, profundidad…), tope 10.000 filas.
- Pestaña **Comparativa** del Panel: puntaje y conteos por sitio. `puntaje_comparable` usa solo reglas válidas en los tres modos, para comparar propio vs. competencia sin sesgo.
- Pestaña **Benchmark** del Panel (fase 3): porcentajes y promedios por sitio (title, meta, H1 único, canonical, JSON-LD, alt en imágenes, indexables, en sitemap, profundidad, tiempos de respuesta, % de errores). Son relativos, así que sitios de distinto tamaño se comparan; celda vacía = no medible. Se calcula solo con lo público, igual para propio, cliente y competencia.
- Privacidad: ver [docs/PRIVACY.md](docs/PRIVACY.md).

### Renderizado de JavaScript (`render_js`)
Para sitios que arman el HTML en el navegador (Google Sites, SPAs): poné `render_js = TRUE` en la fila del Panel (o `crawl.render_js: true` en el YAML). El crawler abre cada página en Chromium (Playwright), lee el DOM final y descubre enlaces que el HTML crudo no tiene.
- Mismo user-agent identificable; cada render cuenta como un pedido más y respeta la pausa configurada; imágenes, fuentes y media no se descargan.
- Anti-SSRF: los pedidos del navegador a hosts no públicos se abortan.
- Si Chromium no está disponible, el crawl sigue con el HTML crudo y deja una nota.
- Se activa solo en plataformas que arman el contenido con JavaScript (hoy: Google Sites), aunque la fila no lo pida.
- Es más lento: en el resto, usalo solo en los sitios que lo necesitan.
