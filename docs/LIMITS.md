# Qué puede y qué no puede hacer el auditor

Este documento fija el alcance. Si algo no está acá como "puede", no se promete.

## Puede hacerse sin costo y de forma autónoma

- Crawl por sitemap y enlaces internos.
- Códigos de estado, redirecciones (HTTP y meta refresh), canonicals, meta robots.
- Títulos, metas y H1 faltantes, duplicados o múltiples.
- Enlaces rotos internos y externos.
- URLs huérfanas (sitemap contra enlaces internos).
- Sitemap con URLs que no devuelven 200 o están en `noindex`.
- Hreflang, JSON-LD (solo validación sintáctica), imágenes sin alt, contenido mixto.
- Comparación contra la corrida anterior.

## Puede hacerse con limitaciones

| Capacidad | Limitación |
|---|---|
| Renderizado de JavaScript | Requiere navegador headless (Playwright). Más lento, solo si el sitio lo necesita. |
| Cloaking | Solo en modo `own`/`client`: se compara la respuesta con UA de usuario contra UA de Googlebot. No verifica la IP real de Googlebot. |
| Core Web Vitals | PageSpeed Insights y CrUX, con cuota gratuita (verificar límites vigentes en la documentación oficial). |
| Search Console | Solo sitios con acceso verificado (`own`/`client`). |

## No puede hacerse sin APIs de pago (y no se promete)

- Tráfico real de un sitio ajeno.
- Keywords posicionadas de un competidor.
- Backlinks completos.
- Rankings en SERP (scrapear Google viola sus términos).

## No puede hacerse nunca

- Evaluar calidad de contenido, autoridad o intención de búsqueda de forma objetiva. Se calculan proxies; la interpretación es humana.
- Garantizar el comportamiento del algoritmo de Google. Se trabaja con buenas prácticas documentadas y evidencia observada.
- Auditar logs de servidor sin acceso a ellos.

## Límites del sitio fixture en GitHub Pages

GitHub Pages solo sirve archivos estáticos: no permite redirecciones HTTP 301/302 arbitrarias ni cabeceras `X-Robots-Tag` personalizadas. Por eso el fixture planta redirecciones con meta refresh. Las redirecciones HTTP reales y las cabeceras se prueban en la fase 1 con un servidor local de tests.

## Grey / black hat

El auditor **detecta** señales de riesgo (texto oculto, enlaces ocultos, cloaking, patrones de doorway, spam de enlaces salientes). **No ejecuta** esas tácticas. Cada señal se reporta con nivel de riesgo, evidencia y referencia a las políticas de spam de Google.
