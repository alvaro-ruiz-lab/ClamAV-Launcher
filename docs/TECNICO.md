# ClamAV Launcher · Detalles técnicos

Para quien quiera saber cómo está hecha la app o modificarla. Para instalarla y usarla basta con el [README](../README.md).

## Estructura

| Archivo | Para qué sirve |
|---|---|
| `clamav_launcher.py` | La aplicación entera (Python 3 + GTK 3 + VTE 2.91, sin dependencias de pip). |
| `instalar.sh` | Comprueba los componentes del sistema (y ofrece instalarlos) y copia la app a la carpeta personal del usuario. |
| `desinstalar.sh` | Quita lo que instaló `instalar.sh`. |
| `clamav-launcher.svg` | Icono del lanzador de aplicaciones. |
| `LICENSE` | Licencia MIT. |

`instalar.sh` no necesita permisos de administrador para la app. Instala estos archivos dentro de `~/.local/share` (o de `$XDG_DATA_HOME`):

- `clamav-launcher/clamav_launcher.py` y `clamav-launcher/desinstalar.sh` (para desinstalar aunque se haya borrado la descarga)
- `applications/clamav-launcher.desktop`: la entrada del lanzador de aplicaciones, con la ruta de la app.
- `icons/hicolor/scalable/apps/clamav-launcher.svg`

Solo usa `sudo` si faltan componentes del sistema, y antes pregunta.

## Ejecutar sin instalar

```bash
python3 clamav_launcher.py
```

Los componentes del sistema que hacen falta, con nombres orientativos según el gestor de paquetes:

| Gestor | Comando |
|---|---|
| apt | `sudo apt install --no-install-recommends python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-vte-2.91 clamav clamav-freshclam` |
| dnf | `sudo dnf install --setopt=install_weak_deps=False python3-gobject gtk3 vte291 clamav clamav-freshclam` |
| pacman | `sudo pacman -S --needed python-gobject python-cairo gtk3 vte3 clamav` |
| zypper | `sudo zypper install --no-recommends python3-gobject python3-gobject-cairo typelib-1_0-Gtk-3_0 typelib-1_0-Vte-2_91 clamav` |

No se instala el demonio `clamd` (`clamav-daemon` o equivalente): `clamscan` no lo necesita y el demonio mantiene en memoria más de 1 GB de firmas de forma permanente.

Fuentes recomendadas: Space Grotesk (interfaz) y JetBrains Mono (terminal). Si no están instaladas, se usan Sans y Monospace.

Los ajustes (rutas de destino y última ruta analizada) se guardan en `~/.config/clamav-launcher/config.json`, o en `$XDG_CONFIG_HOME`.

## Decisiones

- **Los botones solo escriben**: nunca ejecutan nada. Antes de escribir, la app envía Ctrl+E y Ctrl+U para sustituir la línea entera. Ejecutar envía `\r` (lo mismo que la tecla Enter) y Parar envía Ctrl+C. La app solo lanza por su cuenta `xdg-open`, `lsblk` y `systemctl is-active`.
- **Progreso**: `clamscan` no da porcentaje ni estimación de tiempo. Antes de empezar, la app cuenta archivos y bytes en un hilo de baja prioridad (solo contadores) y después lee las líneas `ruta: OK`, `ruta: … FOUND`, etc. de la terminal. El porcentaje va por bytes, la velocidad es una media de los últimos 15 s y el tiempo restante aparece tras 5 s y un 1 % de avance. Al terminar, los totales se toman del resumen de `clamscan`.
- **Lectura de la terminal en lugar de `--log`**: se comprobó con una carpeta de 404 archivos (incluidos un EICAR, un archivo vacío, uno sin permisos, enlaces y una ruta de 336 caracteres) que leer la salida de VTE da una línea por archivo de forma fiable: 401 de 401 líneas `OK`, y las rutas largas que ocupan varias filas se recuperan enteras. Así el comando visible no lleva opciones extra.
- **Líneas `FOUND` en ámbar**: `clamscan` no colorea su salida. La app pinta encima de la terminal esas líneas, y antes comprueba que la fila sigue teniendo ese texto. No reescribe la terminal, porque `feed()` es asíncrono y podría caer en otra fila si llega salida a la vez.
- **Comando en curso**: se compara el grupo de procesos en primer plano de la terminal con el de la shell, cada 300 ms y solo mientras hay algo ejecutándose. Durante la ejecución, la barra lateral se bloquea salvo los botones de abrir carpeta, y la app nunca escribe sobre un programa en marcha.
- **`-r` solo con carpetas**: los escaneos (normal, cuarentena e informe) añaden `-r` únicamente cuando la ruta es una carpeta.
- **Actualizar firmas**: si el servicio `clamav-freshclam` está activo (bloquea la actualización manual), el botón escribe `sudo systemctl stop clamav-freshclam && sudo freshclam; sudo systemctl start clamav-freshclam`. El `;` hace que el servicio vuelva a arrancar aunque la descarga falle.
- **Un solo botón «Escanear»**: lo que se analiza (carpeta, archivo o USB) se decide en el Paso 2, y el comando se adapta a ello.

## Rendimiento

Medido en un portátil con Intel Core i5-6300U (4 hilos) y 8 GB de RAM:

| Medida | Resultado |
|---|---|
| Arranque hasta la ventana dibujada | ~0,6 s |
| Reposo: CPU / memoria (RSS) de la app | 0,0 % / ~76 MB, sin temporizadores activos |
| Escaneo: CPU de la app | ~33 % de un núcleo (ver nota) |
| Código propio de la app durante un escaneo de 50 s | ~0,5 s de CPU en total |
| `clamscan` (memoria al cargar las firmas) | ~990 MB |

**Nota sobre el escaneo**: casi todo ese 33 % lo gasta VTE al dibujar las líneas `OK` que imprime `clamscan` (unas 35 por segundo en la prueba). Una terminal VTE sola, sin nada de la app, gasta lo mismo (32-40 %) con la misma salida. Imprimir solo los infectados (`clamscan -i`) lo evitaría, pero se perdería la lista de archivos y el progreso fiable, así que se descartó.

**Memoria de ClamAV**: `clamscan` necesita cargar todas las firmas en memoria (del orden de 1 GB) cada vez que se ejecuta. Es un requisito de ClamAV, no de la app.
