# Caso de estudio: un auditor SEO autónomo con costo $0

## El problema
Auditar SEO a mano no escala cuando se manejan varios sitios propios, clientes y competencia: cada auditoría consume horas, los resultados quedan dispersos y nadie sabe si un problema es nuevo o ya estaba. Las herramientas pagas resuelven parte, pero cuestan por proyecto y no dejan los datos en tu propio Drive.

## Requisitos que definieron el diseño
1. Autónomo: tiene que correr solo, sin que nadie lo dispare.
2. Costo $0 y sin APIs de pago.
3. Multicliente, con datos de cada cliente separados y una vista comparativa solo para el administrador.
4. Auditar competencia sin infringir normas.
5. Detectar grey/black hat sin practicarlo.
6. Repo público (portfolio) sin exponer ningún sitio ni cliente real.

## Decisiones y por qué
| Decisión | Motivo |
|---|---|
| GitHub Actions en vez de Apps Script | Apps Script tiene límites de tiempo y de volumen que no se saben de antemano; un runner de Actions rastrea miles de URLs |
| Planillas de Google como salida | Lo que el cliente ya sabe leer; el historial queda en su propio Drive |
| Configs de sitios en un Panel privado en Drive | El repo es público: ninguna URL real ni dato de cliente puede vivir ahí |
| Sitio de prueba con errores plantados y archivo de esperados | Permite medir recall con una verdad conocida en vez de "confiar en que funciona" |
| Reglas del modo competidor validadas por código | Una norma que depende de la buena voluntad se rompe; una validación que falla al cargar la config, no |
| Señales de riesgo como pestaña aparte y fuera del puntaje | Son indicios para revisar a mano, no veredictos; mezclarlas inflaría o desinflaría el puntaje |
| Estados nuevo / recurrente / resuelto | Un auditor que no distingue "esto es nuevo" de "esto sigue roto" no sirve para seguimiento |

## Errores reales que aparecieron (y cómo se resolvieron)
- **Planilla sin permiso para el service account:** el primer publicado falló con 403. Se pidió compartir la carpeta del proyecto y se documentó la regla de compartir cada planilla de cliente por separado.
- **El service account no tiene cuota de Drive:** subir CSV falla con 403. En lugar de forzarlo, los datos completos del crawl pasaron a una pestaña de la propia planilla.
- **Doble conteo de `/` y `/index.html`:** el mismo problema aparecía dos veces. Se resolvió con detección de alias por canonical (de 25 a 21 issues en el fixture).
- **Bucle puro de redirecciones (A ↔ B) no detectado:** todos sus miembros eran destino de otra redirección. Se agregó una segunda pasada.
- **Fuga en logs públicos:** una nota de sitemap dejaba ver la ruta de un sitio real aunque el host estaba enmascarado. Se ocultan todas las URLs de las notas en Actions.
- **Cuota de PageSpeed agotada desde runners:** sin clave, la API compartida devuelve 429. El motor lo detecta, no inventa datos y conserva los issues anteriores; con clave gratuita se resuelve.
- **Google Sites:** arma el contenido con JavaScript; el crawler lo detecta y activa Chromium solo para esas plataformas.

## Resultado
- 156 tests automatizados sin red (servidores locales que simulan redirecciones, cloaking, JavaScript y APIs).
- 24 de 24 issues plantados detectados en el sitio de prueba publicado, sin falsos positivos de riesgo en las páginas limpias.
- Auditorías semanales automáticas de sitios reales, con comparativa y benchmark en el Panel.
- Revisión de seguridad propia: sin secretos en el historial, sin vulnerabilidades conocidas en dependencias, protecciones anti-SSRF en el crawler, el navegador y los sitemaps.

## Qué haría después
- Calibrar el puntaje con una muestra amplia de sitios reales (hoy la escala es una estimación).
- Ampliar la tabla de límites por plataforma con casos verificados.
- Evaluar CSS externo en la detección de texto oculto (con el navegador ya integrado).
- Alertas por email o chat cuando aparece un issue crítico nuevo.
