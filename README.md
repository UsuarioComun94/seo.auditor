# seo.auditor

Auditor SEO autónomo, multicliente y de costo $0. Rastrea un sitio, detecta problemas técnicos y on-page, marca señales de riesgo (grey/black hat) y reporta a una planilla de Google Sheets. Corre en GitHub Actions, sin servidores propios.

> Estado: **fase 0** (estructura, reglas, esquema de planilla, sitio fixture). El crawler llega en la fase 1.

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
| `src/seo_auditor/` | Motor: configuración validada y CLI (el crawler entra en la fase 1). |
| `rules/rules.yaml` | Catálogo de reglas: id, severidad, categoría, modos, fase. |
| `schema/sheet_schema.json` | Contrato de las pestañas de la planilla. |
| `clients/` | Una config por cliente. `_template.yaml` es la plantilla. |
| `fixture/` | Sitio de prueba con errores plantados y `EXPECTED_ISSUES.yaml`. |
| `.github/workflows/` | `audit.yml` (auditoría) y `pages.yml` (publica el fixture). |
| `tests/` | Tests con pytest. |

## Uso (fase 0)

```bash
pip install -r requirements.txt
python -m seo_auditor --config clients/fixture.yaml --validate-only
pytest
```

## Privacidad

Este repo es público. **No se versionan** configs reales de clientes ni resultados: las credenciales van en GitHub Secrets y los datos en Sheets y Drive. Las configs reales se guardan fuera del repo (o en un repo privado de configuración).

## Plan por fases

| Fase | Entregable |
|---|---|
| 0 | Repo, reglas, esquema de planilla, fixture, workflows base |
| 1 | Crawler base y salida a Sheets; el fixture debe detectar el 100% de los errores plantados |
| 2 | Reglas completas, detección de plataforma, histórico y diff entre corridas |
| 3 | Modo competidor y benchmark |
| 4 | PageSpeed/CrUX y Search Console (solo sitios autorizados) |
| 5 | Módulo de señales de riesgo |
| 6 | Empaquetado: demo anonimizada y caso de estudio |
