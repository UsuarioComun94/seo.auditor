# Privacidad y protección de datos

El repo es **público**. Eso significa que también son públicos los logs de GitHub Actions y los artifacts de cualquier corrida. Los datos reales viven en Drive; el repo solo tiene el motor.

## Qué vive dónde
| Dato | Dónde | Quién lo ve |
|---|---|---|
| Código, reglas, fixture demo | Repo público | Todos |
| Lista de sitios (nombre, dominio, modo, ID de planilla) | Planilla **Panel**, pestaña Clientes | Solo el administrador + service account |
| Comparación entre sitios | Panel, pestaña Comparativa | Solo el administrador |
| Resultados de cada sitio (incl. Crawl) | Una planilla por sitio | Administrador + a quien se la compartas **individualmente** |
| Credenciales | GitHub Secrets (`GOOGLE_SERVICE_ACCOUNT_JSON`, `SEO_PANEL_ID`) | Nadie, nunca en Drive ni en chats |

## Qué hace el motor para no filtrar
- En modo `--panel` oculta con `::add-mask::` nombres, dominios, hosts, IDs de planillas/carpetas, el ID del Panel y el mail del service account **antes** de imprimir nada.
- Fuerza `--quiet` (no imprime cada URL) y no sube artifacts ni CSV a Drive; todo va a las pestañas.
- Si una fila del Panel es inválida, el error menciona la fila y el motivo, no datos del cliente.
- Verifica que el dominio resuelva a una IP pública (anti-SSRF) antes de rastrear: una fila no puede apuntar al runner a redes internas ni al endpoint de metadatos de la nube.
- Escribe a Sheets con `RAW`: el contenido rastreado nunca se interpreta como fórmula.

## Límites honestos
- El enmascarado de GitHub es por coincidencia de texto: protege los valores listados, no cualquier derivado. Por eso los mensajes no incluyen URLs ni títulos del sitio.
- Quien tenga la clave del service account puede editar **todo** lo que compartiste con ese mail. Mitigación: 2FA en tu cuenta Google, rotar la clave si hay duda, compartir solo la carpeta del proyecto y, para clientes sensibles, un service account propio.
- Compartí **cada planilla de cliente por separado**, nunca la carpeta (los permisos se heredan).
- La comparación entre clientes existe solo en el Panel. No copies la Comparativa a planillas de clientes.
