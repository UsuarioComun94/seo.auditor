# Modos de ejecución y reglas para sitios ajenos

No es asesoramiento legal. Antes de uso comercial, revisar los términos de cada sitio y la normativa de datos aplicable (por ejemplo, Ley 25.326 en Argentina).

## Modos

| Modo | Cuándo | Qué habilita |
|---|---|---|
| `own` | Sitio propio | Todo, incluida la comparación con UA de Googlebot y Search Console. |
| `client` | Sitio de un cliente con autorización | Igual que `own`. Requiere `authorized: true` en la config. |
| `competitor` | Sitio ajeno, solo información pública | Solo lo que ve cualquier visitante, con las reglas de abajo. |

## Reglas del modo `competitor` (las valida el código, no solo la documentación)

1. Se respeta `robots.txt`. Si una ruta está bloqueada, no se rastrea. `respect_robots` no puede ser `false`.
2. User-agent propio e identificable, con una URL de contacto. No puede contener "Googlebot" ni imitar otro bot.
3. Espera mínima de 2 segundos entre peticiones.
4. Tope de URLs por corrida (500).
5. Sin login, sin evadir paywalls, sin eludir bloqueos anti-bot.
6. Sin datos personales: se guardan estructura y metadatos, no contenido generado por usuarios.
7. Sin Search Console ni datos privados.
8. Sin scraping de Google.

## Qué se guarda de un competidor

Estructura de URLs, códigos de estado, títulos, metas, H1, canonicals, schema y señales técnicas. No se republica contenido textual ajeno.
