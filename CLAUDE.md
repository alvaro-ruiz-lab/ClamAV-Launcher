# ClamAV Launcher

Aplicación de escritorio para Linux (Python 3 + GTK3 + VTE 2.91, sin dependencias de pip): una terminal real con una barra lateral de botones que **solo escriben** comandos de ClamAV en la terminal. Nunca ejecutan nada por su cuenta; el usuario pulsa Ejecutar (Enter) o Parar (Ctrl+C).

- Toda la app está en `clamav_launcher.py`. Se instala con `install.sh` (copia la app a `~/.local/share` y genera la entrada del lanzador) y se quita con `uninstall.sh`.
- `README.md` es para usuarios sin conocimientos técnicos: corto y sencillo. Lo técnico (decisiones, rendimiento, paquetes) va en `docs/TECNICO.md`.
- `docs/captura.png` es la captura del README: con datos neutros (`usuario@equipo`, `/media/usuario/...`), nunca datos personales.

## Diseño
- Modo oscuro siempre, esquinas rectas (radio 0), bordes de 1 px, estética angular y técnica. Los colores vigentes son los del CSS de `clamav_launcher.py`.
- Acento principal rojo (`#cf433c` / `#f0645c`); verde lima (`#d4ff3f`) como subacento puntual; ámbar (`#ffb224`) para infectados y líneas FOUND (el rojo es la marca, no el peligro).
- Barra de título algo más clara que el fondo y con un leve tono rojizo.
- Iconos de trazo cuadrado dibujados con Cairo (`FORMAS_ICONO`), sin imágenes externas.
- Fuentes: Space Grotesk (interfaz) y JetBrains Mono (terminal y etiquetas), con Sans y Monospace como respaldo.
- Pasos de la barra lateral: 1) Actualizar firmas; 2) qué analizar (ruta, elegir carpeta, elegir archivo y botón «Elegir USB», activo solo con USB conectados); 3) Escanear, cuarentena, informe y ver último informe; Utilidades. Los escaneos añaden `-r` solo si la ruta es una carpeta.

## Reglas de código (obligatorias)

### A. Código
Nombres de variables, funciones, clases, constantes, comentarios, nombres de archivo, mensajes de log y cualquier texto que el usuario no vea:
- **Sin tildes, sin la letra ene con virgulilla y sin emojis.**
- Comentarios y nombres en español, `snake_case` (se admite inglés para términos técnicos de GTK/VTE). Mantener la coherencia.
- Si se modifica código existente que tenga texto o código comentado, **mantenerlo** (no borrarlo).

### B. Interfaz
Todo texto visible para el usuario (botones, etiquetas, tooltips, avisos, diálogos, barra inferior, mensajes de los instaladores, README):
- **Ortografía y gramática correctas en español: con tildes, eñes y signos de apertura (¿ ¡).**
- Sin emojis.
- Archivos en UTF-8.

### Además
- Tono profesional y objetivo en los mensajes al usuario.
- Código simple y legible. Proyecto pequeño: sin sobreingeniería, clases innecesarias ni frameworks extra.
- Independiente de la distribución: no nombrar ninguna distro en código, interfaz ni documentación; detectar en tiempo de ejecución lo que dependa del sistema.
- Ligera: todo dirigido por eventos, sin temporizadores ni animaciones en reposo.

## Seguridad
- La app nunca ejecuta comandos de ClamAV: solo escribe texto en la terminal.
- Procesos permitidos de forma directa: `xdg-open`, `lsblk`, `systemctl is-active` y `shutil.which(...)`.
- Nunca `--remove`; cuarentena = `--move`.
- Nunca pedir ni guardar contraseñas (sudo las pide en la terminal).
- Rutas siempre con `os.path.expanduser` + `shlex.quote`; `--move=` y `--log=` con rutas absolutas.
- Nunca instalar el demonio `clamd`.
