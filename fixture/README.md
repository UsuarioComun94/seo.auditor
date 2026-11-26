# Sitio fixture

Sitio estático ficticio con errores SEO plantados a propósito. Sirve para validar cada detector del auditor y como demo pública sin exponer datos de nadie.

- Código del sitio: [`site/`](site/)
- Lista de errores plantados (contrato de la fase 1): [`EXPECTED_ISSUES.yaml`](EXPECTED_ISSUES.yaml)
- Publicación: el workflow `pages.yml` lo despliega en GitHub Pages.
  URL esperada: https://usuariocomun94.github.io/seo.auditor/

## Qué NO se puede plantar en GitHub Pages

Redirecciones HTTP 301/302 reales, cabeceras `X-Robots-Tag`, bucles de redirección HTTP y cloaking por user-agent. Se cubren en tests con un servidor local (fases 1 y 5).

## Nota sobre robots.txt

GitHub Pages de proyecto sirve el sitio bajo `/seo.auditor/`, así que su `robots.txt` queda en `/seo.auditor/robots.txt` y no en la raíz del dominio, que es donde lo buscan los crawlers por estándar. Para poder probar TECH-010, la config permite indicar `crawl.robots_url`.

## Regla de oro

Nada de lo que hay acá es un error real del proyecto: si cambiás una página, actualizá `EXPECTED_ISSUES.yaml` y corré `pytest`.
