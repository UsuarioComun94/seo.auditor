# App de escritorio: guía paso a paso

## Qué hace (y qué no)
- **Hace:** lanza una auditoría de uno o todos los sitios de tu Panel, y muestra las últimas ejecuciones (en curso, terminó bien, terminó con errores). Abre el detalle en GitHub y tu planilla Panel.
- **No hace:** no rastrea en tu compu ni guarda claves de Google. Los resultados se leen en tus planillas, como siempre.

## Instalación
1. Descargá el archivo de tu sistema desde [Releases](https://github.com/UsuarioComun94/seo.auditor/releases): `seo-auditor-windows.zip` o `seo-auditor-macos.zip`. Descomprimilo.
2. **Windows:** doble clic en `seo-auditor.exe`. Como no está firmado, SmartScreen avisa «Windows protegió su PC»: tocá *Más información* → *Ejecutar de todas formas*.
3. **macOS:** la primera vez, clic derecho sobre la app → *Abrir* → *Abrir*. Si no abre, andá a Ajustes del Sistema → Privacidad y seguridad → *Abrir de todas formas*.

Las advertencias aparecen porque firmar apps cuesta dinero (certificados de Apple y Microsoft). El código es público y el instalador lo arma GitHub a la vista de todos.

## Primer uso (una sola vez)
1. En la app tocá **Cómo conseguir el token**. Se abre GitHub.
2. Creá un *fine-grained token*: **Only select repositories** → este repositorio; en **Permissions → Repository → Actions: Read and write**. Poné una fecha de vencimiento.
3. Copiá el token, pegalo en el campo **Token de GitHub** y tocá **Guardar**. La app prueba la conexión.
4. Opcional: pegá el enlace de tu planilla Panel para abrirla con un botón.

El token se guarda en el almacén seguro de tu sistema (Credential Manager en Windows, Llavero en macOS) o, si no está disponible, en un archivo de tu usuario que solo vos podés leer.

## Uso diario
1. Escribí el nombre del sitio tal como figura en la pestaña *Clientes* del Panel, o `all`.
2. Tocá **Auditar ahora**. Tarda entre 3 y 10 minutos; la lista se actualiza sola.
3. Leé los resultados en la planilla del sitio y en *Comparativa* / *Benchmark* del Panel.

## Si algo falla
| Mensaje | Qué significa |
|---|---|
| «El token no es válido o venció» | Creá uno nuevo y pegalo de nuevo |
| «El token no tiene permiso» | Tiene que ser de este repositorio con *Actions: Read and write* |
| «No encuentro el repositorio…» | Revisá el nombre (`usuario/nombre`) y que el token tenga acceso |
| «Terminó con errores» | Puede ser un sitio del Panel con un problema (dominio que no resuelve, planilla sin permiso). Tocá *Ver detalle en GitHub* |

## Para quien arma una versión nueva
En GitHub: Actions → *Construir la app de escritorio* → *Run workflow* (genera los archivos como artifacts). Para publicar un Release con descargas: crear una etiqueta `app-vX.Y.Z`.
