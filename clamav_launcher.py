#!/usr/bin/env python3
# ClamAV Launcher: terminal real con una barra lateral de botones para ClamAV.
#
# Regla central: los botones NO ejecutan nada. Solo escriben el comando en la
# terminal; el usuario lo revisa y pulsa Ejecutar (Enter) o Parar (Ctrl+C).
#
# La app detecta si hay un comando en curso (para bloquear la barra lateral) y
# reconstruye el progreso de clamscan leyendo su salida en la terminal, porque
# clamscan no informa del porcentaje ni del tiempo restante.
#
# Uso: python3 clamav_launcher.py

import collections
import math
import os
import shlex
import shutil
import sys
import time


# ---------------------------------------------------------------------------
# Componentes del sistema: se comprueban antes de importar GTK, para que la
# version portable explique que falta en lugar de fallar con un error tecnico
# ---------------------------------------------------------------------------

# Los mismos paquetes que instala install.sh (nunca el demonio clamd)
PAQUETES_SISTEMA = (
    ("apt", "sudo apt install --no-install-recommends python3-gi python3-gi-cairo "
            "gir1.2-gtk-3.0 gir1.2-vte-2.91 clamav clamav-freshclam"),
    ("dnf", "sudo dnf install --setopt=install_weak_deps=False python3-gobject gtk3 "
            "vte291 clamav clamav-freshclam"),
    ("pacman", "sudo pacman -S --needed python-gobject python-cairo gtk3 vte3 clamav"),
    ("zypper", "sudo zypper install --no-recommends python3-gobject python3-gobject-cairo "
               "typelib-1_0-Gtk-3_0 typelib-1_0-Vte-2_91 clamav"),
)


def componentes_que_faltan():
    """Nombres (para el usuario) de los componentes imprescindibles que faltan.

    ClamAV no esta aqui: sin el, la app arranca y ofrece instalarlo.
    """
    try:
        import gi as modulo_gi
    except ImportError:
        return ["PyGObject (Python con GTK)", "GTK 3", "VTE 2.91 (la terminal)"]
    import importlib

    faltan = []
    for nombre, version, texto in (("Gtk", "3.0", "GTK 3"),
                                   ("Vte", "2.91", "VTE 2.91 (la terminal)")):
        try:
            modulo_gi.require_version(nombre, version)
            importlib.import_module("gi.repository." + nombre)
        except (ImportError, ValueError):
            faltan.append(texto)
    try:
        import cairo  # noqa: F401
        modulo_gi.require_foreign("cairo")
    except (ImportError, AttributeError):
        faltan.append("Soporte de Cairo para PyGObject")
    return faltan


def avisar_componentes_que_faltan(faltan):
    comando = next((orden for gestor, orden in PAQUETES_SISTEMA if shutil.which(gestor)), None)
    lineas = ["Faltan estos componentes del sistema:", ""]
    lineas += ["  - " + nombre for nombre in faltan]
    lineas.append("")
    if comando:
        lineas += ["Para instalarlos, ejecuta en una terminal:", "", "    " + comando, ""]
        lineas.append("También puedes usar el instalador de la app: bash install.sh")
    else:
        lineas.append("Instálalos con el gestor de software de tu sistema.")
    cuerpo = "\n".join(lineas)
    print("ClamAV Launcher no puede arrancar.\n\n" + cuerpo, file=sys.stderr)
    # Sin terminal (abierta desde el lanzador) el texto no se veria: si GTK
    # esta disponible, se muestra tambien en una ventana
    if not sys.stderr.isatty():
        try:
            import gi as modulo_gi
            modulo_gi.require_version("Gtk", "3.0")
            from gi.repository import Gtk as modulo_gtk
        except (ImportError, ValueError):
            return
        dialogo = modulo_gtk.MessageDialog(
            message_type=modulo_gtk.MessageType.ERROR, buttons=modulo_gtk.ButtonsType.CLOSE,
            text="ClamAV Launcher no puede arrancar")
        dialogo.format_secondary_text(cuerpo)
        dialogo.run()


_FALTAN = componentes_que_faltan()
if _FALTAN:
    avisar_componentes_que_faltan(_FALTAN)
    sys.exit(1)

import cairo  # noqa: E402
import gi  # noqa: E402

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("PangoCairo", "1.0")
gi.require_version("Vte", "2.91")
from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo, Vte  # noqa: E402


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

NOMBRE_APP = "ClamAV Launcher"
CARPETA_CUARENTENA_DEFECTO = "~/ClamAV/cuarentena"
CARPETA_INFORMES_DEFECTO = "~/ClamAV/informes"
LINEAS_SCROLLBACK = 5000
# Separacion vertical entre botones del Paso 3 y Utilidades (el diseno usa 4 px;
# se amplia para que las tarjetas con fila de destino se lean como un solo boton)
ESPACIO_BOTONES = 10
# Separacion entre secciones de la barra lateral (diseno: 14 px), mayor que la
# de los botones para que cada titulo quede unido a su grupo
ESPACIO_SECCIONES = 22

# Gestores de paquetes soportados, por orden de deteccion. Nunca se instala el
# demonio clamd: clamscan no lo necesita y deja las firmas en RAM de forma
# permanente.
GESTORES_PAQUETES = (
    ("apt", "sudo apt install --no-install-recommends clamav clamav-freshclam"),
    ("dnf", "sudo dnf install --setopt=install_weak_deps=False clamav clamav-freshclam"),
    ("pacman", "sudo pacman -S --needed clamav"),
    ("zypper", "sudo zypper install clamav"),
)

# Secuencias de control que se envian a la terminal
TECLA_FIN_DE_LINEA = b"\x05"   # Ctrl+E: cursor al final de la linea
TECLA_BORRAR_LINEA = b"\x15"   # Ctrl+U: borra la linea hasta el cursor
TECLA_ENTER = b"\r"            # lo mismo que envia la tecla Enter real
TECLA_INTERRUMPIR = b"\x03"    # Ctrl+C

# Temporizadores: solo existen mientras hacen falta (nada en reposo)
INTERVALO_SONDEO_MS = 300      # comprobar si sigue habiendo un comando en curso
SONDEOS_PARA_TERMINAR = 2      # veces seguidas con la shell en primer plano
INTERVALO_LECTURA_MS = 250     # lectura de la salida de clamscan
INTERVALO_ANIMACION_MS = 100   # barra indeterminada a 10 fotogramas por segundo
VENTANA_VELOCIDAD_S = 15       # media movil de la velocidad
SEGUNDOS_MINIMOS_RESTANTE = 5  # datos minimos antes de estimar el tiempo restante
MAXIMO_LINEAS_FOUND = 200      # lineas FOUND recordadas para pintarlas en ambar

# Textos de la barra inferior
MENSAJE_INICIAL = "Pulsa un botón para escribir su comando en la terminal."
MENSAJE_COMANDO_ESCRITO = "Comando escrito. Revísalo y pulsa Ejecutar."

# Tooltips: (plantilla del comando, explicacion)
TOOLTIPS = {
    "freshclam": (
        "sudo freshclam",
        "Descarga las definiciones de virus más recientes. Sin esto, ClamAV no "
        "reconoce las amenazas nuevas. Hazlo antes de cada escaneo.",
    ),
    "freshclam_servicio": (
        "sudo systemctl stop clamav-freshclam && sudo freshclam; "
        "sudo systemctl start clamav-freshclam",
        "Descarga las definiciones de virus más recientes. El servicio de "
        "actualización automática está activo y bloquea la actualización "
        "manual, así que se detiene, se actualiza y se vuelve a iniciar.",
    ),
    "escanear": (
        "clamscan -r RUTA",
        "Analiza lo que hayas elegido en el Paso 2. -r : entra en todas las "
        "subcarpetas; solo se añade si es una carpeta o un USB. Al terminar "
        "muestra un resumen con el número de archivos infectados.",
    ),
    "cuarentena": (
        "clamscan -r --move=CARPETA RUTA",
        "--move : mueve cada archivo infectado a la carpeta indicada en lugar "
        "de borrarlo. Si no existe, la app la crea. Puedes cambiar la carpeta "
        "en el campo de abajo; el último botón la abre. -r solo se añade si "
        "analizas una carpeta o un USB.",
    ),
    "informe": (
        "clamscan -r --log=CARPETA/informe-AAAAMMDD-HHMMSS.txt RUTA",
        "--log : guarda el informe en un archivo con fecha y hora en el "
        "nombre, para no sobrescribir el anterior. -r solo se añade si "
        "analizas una carpeta o un USB.",
    ),
    "ver_informe": (
        "cat INFORME_MÁS_RECIENTE",
        "Muestra aquí el informe más reciente de la carpeta de informes. Si "
        "todavía no hay ninguno, la app lo avisa.",
    ),
    "version": (
        "clamscan --version",
        "Muestra la versión de ClamAV y de las firmas instaladas.",
    ),
    "ayuda": (
        "clamscan --help",
        "Lista de todas las opciones de clamscan.",
    ),
    "instalar": (
        "sudo GESTOR install clamav",
        "Instala ClamAV. Te pedirá la contraseña en la terminal.",
    ),
}


# ---------------------------------------------------------------------------
# Funciones puras (sin GTK): rutas y construccion de comandos
# ---------------------------------------------------------------------------

def normalizar_ruta(texto):
    """Expande ~ y devuelve una ruta absoluta. Cadena vacia si no hay texto."""
    texto = (texto or "").strip()
    if not texto:
        return ""
    return os.path.abspath(os.path.expanduser(texto))


def comando_freshclam(servicio_activo):
    # Si el servicio esta activo bloquea el log de freshclam. Se reinicia con
    # ';' para que vuelva a arrancar aunque la descarga falle.
    if servicio_activo:
        return TOOLTIPS["freshclam_servicio"][0]
    return "sudo freshclam"


def inicio_clamscan(recursivo):
    # -r solo tiene sentido con carpetas; con un archivo suelto se omite para
    # que el comando visible sea el justo
    return "clamscan -r" if recursivo else "clamscan"


def comando_escanear(ruta, recursivo):
    return "{} {}".format(inicio_clamscan(recursivo), shlex.quote(ruta))


def comando_cuarentena(ruta, carpeta_cuarentena, recursivo):
    return "{} --move={} {}".format(
        inicio_clamscan(recursivo), shlex.quote(carpeta_cuarentena), shlex.quote(ruta))


def nombre_informe(momento):
    return momento.strftime("informe-%Y%m%d-%H%M%S.txt")


def comando_informe(ruta, carpeta_informes, momento, recursivo):
    archivo = os.path.join(carpeta_informes, nombre_informe(momento))
    return "{} --log={} {}".format(
        inicio_clamscan(recursivo), shlex.quote(archivo), shlex.quote(ruta))


def comando_ver_informe(archivo_informe):
    return "cat " + shlex.quote(archivo_informe)


def informe_mas_reciente(carpeta_informes):
    """Ruta del .txt modificado mas recientemente, o None si no hay."""
    mas_reciente = None
    fecha_mas_reciente = -1.0
    try:
        with os.scandir(carpeta_informes) as entradas:
            for entrada in entradas:
                if not entrada.name.endswith(".txt"):
                    continue
                try:
                    if not entrada.is_file():
                        continue
                    fecha = entrada.stat().st_mtime
                except OSError:
                    continue
                if fecha > fecha_mas_reciente:
                    fecha_mas_reciente = fecha
                    mas_reciente = entrada.path
    except OSError:
        return None
    return mas_reciente


def comando_instalacion(buscar=shutil.which):
    """Comando de instalacion del primer gestor de paquetes detectado."""
    for gestor, comando in GESTORES_PAQUETES:
        if buscar(gestor):
            return comando
    return None


def unidades_usb_desde_lsblk(datos):
    """Lista de (etiqueta, punto_de_montaje) de unidades extraibles montadas."""
    resultado = []

    def recorrer(dispositivos, extraible_padre):
        for disp in dispositivos or []:
            extraible = disp.get("rm") in (True, 1, "1") or extraible_padre
            punto = disp.get("mountpoint")
            if not punto:
                punto = next((p for p in disp.get("mountpoints") or [] if p), None)
            if extraible and punto and punto.startswith("/"):
                etiqueta = disp.get("label") or os.path.basename(punto) or disp.get("name")
                resultado.append((etiqueta, punto))
            recorrer(disp.get("children"), extraible)

    recorrer(datos.get("blockdevices"), False)
    return resultado


def unidades_usb_en_media(usuario):
    """Respaldo: puntos de montaje bajo /media/USUARIO y /run/media/USUARIO."""
    resultado = []
    for base in (os.path.join("/media", usuario), os.path.join("/run/media", usuario)):
        try:
            nombres = sorted(os.listdir(base))
        except OSError:
            continue
        for nombre in nombres:
            punto = os.path.join(base, nombre)
            if os.path.ismount(punto):
                resultado.append((nombre, punto))
    return resultado


def detectar_unidades_usb():
    import json
    import subprocess

    unidades = []
    if shutil.which("lsblk"):
        try:
            salida = subprocess.run(
                ["lsblk", "-J", "-o", "NAME,RM,MOUNTPOINT,LABEL"],
                capture_output=True, text=True, timeout=3, check=False)
            unidades = unidades_usb_desde_lsblk(json.loads(salida.stdout or "{}"))
        except (OSError, subprocess.SubprocessError, ValueError):
            unidades = []
    usuario = os.environ.get("USER") or os.path.basename(os.path.expanduser("~"))
    vistos = {punto for _, punto in unidades}
    for etiqueta, punto in unidades_usb_en_media(usuario):
        if punto not in vistos:
            unidades.append((etiqueta, punto))
            vistos.add(punto)
    return unidades


def servicio_freshclam_activo():
    import subprocess

    if not shutil.which("systemctl"):
        return False
    try:
        salida = subprocess.run(
            ["systemctl", "is-active", "clamav-freshclam"],
            capture_output=True, text=True, timeout=2, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return salida.stdout.strip() == "active"


def ruta_config():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "clamav-launcher", "config.json")


def cargar_config(ruta=None):
    """Ajustes guardados (rutas de destino y ultima ruta analizada), o {}."""
    import json

    try:
        with open(ruta or ruta_config(), encoding="utf-8") as archivo:
            datos = json.load(archivo)
    except (OSError, ValueError):
        return {}
    if not isinstance(datos, dict):
        return {}
    return {clave: valor for clave, valor in datos.items() if isinstance(valor, str)}


def guardar_config(datos, ruta=None):
    """Escritura atomica: un archivo temporal que sustituye al anterior."""
    import json

    ruta = ruta or ruta_config()
    try:
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        temporal = ruta + ".tmp"
        with open(temporal, "w", encoding="utf-8") as archivo:
            json.dump(datos, archivo, ensure_ascii=False, indent=2)
        os.replace(temporal, ruta)
        return True
    except OSError:
        return False


def shell_del_usuario():
    shell = os.environ.get("SHELL", "")
    if shell and os.access(shell, os.X_OK):
        return shell
    return shutil.which("bash") or "/bin/sh"


# ---------------------------------------------------------------------------
# Funciones puras: salida de clamscan y calculo del progreso
# ---------------------------------------------------------------------------

def analizar_linea_clamscan(linea, raiz):
    """Interpreta una linea de clamscan con el resultado de un archivo.

    Devuelve (ruta, tipo) con tipo 'ok', 'infectado', 'error' u 'otro', o None
    si la linea no es de un archivo bajo 'raiz' (prompt, avisos, resumen...).
    Los enlaces simbolicos no se cuentan: tampoco entran en el recuento previo.
    """
    if not raiz or not linea.startswith(raiz):
        return None
    ruta, separador, resultado = linea.rpartition(": ")
    if not separador or not ruta:
        return None
    if resultado == "OK":
        return ruta, "ok"
    if resultado.endswith(" FOUND"):
        return ruta, "infectado"
    if resultado.endswith("ERROR") or resultado == "Access denied":
        return ruta, "error"
    if resultado in ("Empty file", "Excluded"):
        return ruta, "otro"
    return None


def valor_resumen(linea, clave):
    """Numero de una linea del resumen ('Infected files: 1'), o None."""
    prefijo = clave + ": "
    if not linea.startswith(prefijo):
        return None
    try:
        return int(linea[len(prefijo):].strip())
    except ValueError:
        return None


def formatear_miles(numero):
    return "{:,}".format(numero).replace(",", ".")


def cantidad(numero, singular, plural):
    """'1 infectado', '3 infectados', '12.480 archivos analizados'."""
    return "{} {}".format(formatear_miles(numero), singular if numero == 1 else plural)


def formatear_velocidad(bytes_por_segundo):
    if bytes_por_segundo is None:
        return "--"
    megas = bytes_por_segundo / 1e6
    if megas >= 10:
        return "{:.0f} MB/s".format(megas)
    if megas >= 1:
        return "{:.1f} MB/s".format(megas).replace(".", ",")
    return "{:.0f} KB/s".format(bytes_por_segundo / 1e3)


def formatear_restante(segundos):
    if segundos is None:
        return "--"
    segundos = max(0, int(math.ceil(segundos)))
    if segundos < 60:
        return "~{} s".format(segundos)
    minutos = int(math.ceil(segundos / 60))
    if minutos < 60:
        return "~{} min".format(minutos)
    horas, minutos = divmod(minutos, 60)
    return "~{} h {} min".format(horas, minutos) if minutos else "~{} h".format(horas)


class Progreso:
    """Contadores de un escaneo. Sin listas por archivo: memoria acotada."""

    def __init__(self, archivos_total=None, bytes_total=None):
        self.archivos_total = archivos_total
        self.bytes_total = bytes_total
        self.archivos = 0
        self.bytes = 0
        self.infectados = 0
        self.inicio = None                    # instante del primer archivo
        self.muestras = collections.deque()   # (instante, bytes) de los ultimos 15 s

    def registrar(self, instante, tamano, infectado):
        if self.inicio is None:
            self.inicio = instante
        self.archivos += 1
        self.bytes += tamano
        if infectado:
            self.infectados += 1

    def anotar_muestra(self, instante):
        if self.inicio is None:
            return
        self.muestras.append((instante, self.bytes))
        while len(self.muestras) > 2 and instante - self.muestras[0][0] > VENTANA_VELOCIDAD_S:
            self.muestras.popleft()

    def fraccion(self):
        """Avance de 0 a 0,99 (el 100 % solo al terminar), o None sin recuento."""
        if self.bytes_total:
            valor = self.bytes / self.bytes_total
        elif self.archivos_total:
            valor = self.archivos / self.archivos_total
        else:
            return None
        return min(valor, 0.99)

    def velocidad(self):
        if len(self.muestras) < 2:
            return None
        (t0, b0), (t1, b1) = self.muestras[0], self.muestras[-1]
        if t1 - t0 <= 0:
            return None
        return (b1 - b0) / (t1 - t0)

    def restante(self, instante):
        fraccion = self.fraccion()
        velocidad = self.velocidad()
        if (self.inicio is None or fraccion is None or not self.bytes_total
                or instante - self.inicio < SEGUNDOS_MINIMOS_RESTANTE
                or fraccion < 0.01 or not velocidad):
            return None
        return max(0, self.bytes_total - self.bytes) / velocidad


def contar_ruta(ruta, cancelado):
    """Archivos regulares y bytes bajo 'ruta' (como clamscan -r: sin seguir
    enlaces). Solo guarda contadores. Devuelve None si se cancela."""
    import stat

    archivos = 0
    total = 0
    for raiz, _carpetas, nombres in os.walk(ruta):
        if cancelado.is_set():
            return None
        for nombre in nombres:
            try:
                datos = os.lstat(os.path.join(raiz, nombre))
            except OSError:
                continue
            if stat.S_ISREG(datos.st_mode):
                archivos += 1
                total += datos.st_size
    return archivos, total



# ---------------------------------------------------------------------------
# Estilo: colores, CSS e iconos
# ---------------------------------------------------------------------------

COLOR_ROJO = "#cf433c"
COLOR_BORDE_SUAVE = "#232a2f"

# Paleta ANSI de la terminal (16 colores). Con bold_is_bright, el prompt en
# verde negrita sale en lima y la ruta en azul.
COLOR_TERMINAL_TEXTO = "#e6eaec"
COLOR_TERMINAL_FONDO = "#0f1113"
COLOR_TERMINAL_CURSOR = "#d4ff3f"
PALETA_TERMINAL = (
    "#232a2f", "#f0645c", "#a8cf3a", "#ffb224",
    "#7aa2ff", "#c792ea", "#5fc8c8", "#e6eaec",
    "#55606a", "#ff7b73", "#d4ff3f", "#ffc857",
    "#7aa2ff", "#d7a8ff", "#87e0e0", "#ffffff",
)

FUENTE_INTERFAZ = '"Space Grotesk", Sans'
FUENTE_MONO = '"JetBrains Mono", Monospace'

# Un unico proveedor CSS pequeno. Sin transiciones, sombras con desenfoque,
# degradados ni transparencias (equipos antiguos y renderizado por software).
CSS = """
* { transition: none; border-radius: 0; -gtk-outline-radius: 0; text-shadow: none; -gtk-icon-shadow: none; }
window, window.background { background-color: #121517; color: #e6eaec; font-family: FUENTE_INTERFAZ; font-size: 13px; }
decoration { border-radius: 0; box-shadow: 0 0 0 1px #313a40; }

headerbar { background-image: none; background-color: #201a1b; min-height: 40px; padding: 0 0 0 16px; border: none; border-bottom: 1px solid #2e2426; box-shadow: none; }
headerbar .icono-escudo { color: #f0645c; }
headerbar .titulo-app { font-size: 13px; font-weight: 700; letter-spacing: 0.14em; color: #e6eaec; }
headerbar .boton-ventana { background-color: transparent; border: none; min-width: 46px; min-height: 40px; padding: 0; margin: 0; }
headerbar .boton-ventana .icono { color: #8b969c; }
headerbar .boton-ventana:hover { background-color: #2c2224; }
headerbar .boton-ventana:hover .icono { color: #e6eaec; }
headerbar .boton-cerrar:hover { background-color: #cf433c; }
headerbar .boton-cerrar:hover .icono { color: #ffffff; }

.franja { background-color: #181c1f; }
.franja-contenido { padding: 0 20px; }
.insignia { padding: 3px 8px; font-family: FUENTE_MONO; font-size: 11px; font-weight: 700; letter-spacing: 0.1em; background-color: #232a2f; color: #8b969c; }
.insignia.escaneando, .insignia.ejecutando { background-color: #cf433c; color: #ffffff; }
.insignia.terminado { background-color: #d4ff3f; color: #0f1113; }
.franja-detalle { color: #8b969c; }
.franja-detalle.ruta { font-family: FUENTE_MONO; color: #e6eaec; }
.metrica-titulo { font-size: 11px; letter-spacing: 0.1em; color: #8b969c; }
.metrica-valor { font-family: FUENTE_MONO; font-size: 13px; color: #e6eaec; }
.metrica-valor.ambar { color: #ffb224; }
.separador { background-color: #313a40; min-width: 1px; min-height: 20px; }
.porcentaje { font-family: FUENTE_MONO; font-size: 16px; font-weight: 700; color: #6b7780; }
.porcentaje.activo { color: #f0645c; }

.barra-lateral, .barra-lateral viewport { background-color: #15181b; }
.barra-lateral { border-right: 1px solid #232a2f; }
.seccion { font-family: FUENTE_MONO; font-size: 11px; font-weight: 700; letter-spacing: 0.12em; color: #8b969c; }
.seccion.paso1 { color: #f0645c; }
.nota { font-size: 12px; color: #8b969c; }
.nota:disabled { color: #55606a; }

button { background-image: none; box-shadow: none; outline-color: #f0645c; outline-offset: -3px; }
.boton-accion { min-height: 34px; padding: 0 10px; border: 1px solid #313a40; background-color: #1b2024; color: #e6eaec; font-weight: 500; }
.boton-accion:hover { background-color: #22282c; }
.boton-accion:active { background-color: #301714; }
.boton-accion:disabled { border-color: #232a2f; background-color: #15181b; color: #55606a; }
.boton-accion .icono { color: #8b969c; }
.icono:disabled { color: #3f4a52; }
.boton-accion.seleccionado, .boton-accion.destacado { border-color: #cf433c; background-color: #301714; box-shadow: inset 3px 0 0 #cf433c; }
.boton-accion.seleccionado .icono, .boton-accion.destacado .icono { color: #f0645c; }

.boton-paso1 { min-height: 58px; padding: 0 12px; border: 1px solid #7a2e29; background-color: #241513; box-shadow: inset 4px 0 0 #cf433c; color: #e6eaec; }
.boton-paso1:hover { background-color: #301a16; }
.boton-paso1.seleccionado, .boton-paso1:active { border-color: #cf433c; background-color: #401b17; }
.boton-paso1:disabled { border-color: #232a2f; background-color: #15181b; box-shadow: inset 4px 0 0 #401b17; color: #55606a; }
.boton-paso1 .icono { color: #f0645c; }
.boton-paso1 .icono:disabled, .boton-accion .icono:disabled { color: #3f4a52; }
.paso1-titulo { font-size: 15px; font-weight: 700; }
.paso1-sub { font-size: 12px; color: #c4ccd0; }
.paso1-sub:disabled { color: #55606a; }

.tarjeta { border: 1px solid #313a40; background-color: #1b2024; }
.tarjeta .boton-accion { border: none; background-color: transparent; }
.tarjeta .boton-accion:hover { background-color: #22282c; }
.tarjeta .boton-accion:disabled { background-color: transparent; }
.tarjeta.seleccionado { border-color: #cf433c; background-color: #301714; box-shadow: inset 3px 0 0 #cf433c; }
.tarjeta.seleccionado .boton-accion .icono { color: #f0645c; }
.tarjeta.bloqueada { border-color: #232a2f; background-color: #15181b; }

entry { min-height: 34px; padding: 0 8px; border: 1px solid #313a40; background-image: none; background-color: #0f1113; color: #e6eaec; box-shadow: none; caret-color: #d4ff3f; }
entry:focus { border-color: #cf433c; }
entry:disabled { border-color: #232a2f; color: #55606a; background-color: #15181b; }
entry selection { background-color: #cf433c; color: #ffffff; }
.entrada-ruta { font-family: FUENTE_MONO; font-size: 12px; }
.campo-destino { min-height: 26px; border: 1px solid #313a40; background-color: #0f1113; }
.campo-destino:disabled { border-color: #232a2f; }
.flecha-destino { min-width: 24px; background-color: #232a2f; }
.flecha-destino .icono { color: #8b969c; }
.tarjeta.seleccionado .flecha-destino .icono { color: #f0645c; }
.entrada-destino, .entrada-destino:focus, .entrada-destino:disabled { min-height: 26px; padding: 0 6px; border: none; background-color: transparent; font-family: FUENTE_MONO; font-size: 11px; }

.boton-cuadrado { min-width: 34px; min-height: 34px; padding: 0; border: 1px solid #313a40; background-color: #1b2024; }
.boton-mini { min-width: 26px; min-height: 26px; padding: 0; border: 1px solid #313a40; background-color: #1b2024; }
.boton-cuadrado:hover, .boton-mini:hover { background-color: #262c31; }
.boton-cuadrado .icono, .boton-mini .icono { color: #e6eaec; }
.boton-cuadrado:disabled, .boton-mini:disabled { border-color: #232a2f; background-color: #15181b; }

.boton-usb { min-height: 30px; padding: 0 10px; border: 1px solid #313a40; background-color: #1b2024; color: #e6eaec; font-size: 12px; }
.boton-usb:hover { background-color: #22282c; }
.boton-usb:disabled { opacity: 0.45; background-color: #1b2024; color: #e6eaec; }
.boton-usb .icono, .boton-usb .icono:disabled { color: #8b969c; }
.etiqueta-usb { font-family: FUENTE_MONO; font-size: 10px; font-weight: 700; letter-spacing: 0.06em; color: #d4ff3f; }
.etiqueta-usb.ninguno { color: #8b969c; }
menu, .menu { background-color: #1b2024; border: 1px solid #313a40; padding: 2px 0; }
menuitem { padding: 6px 10px; color: #e6eaec; }
menuitem:hover { background-color: #301714; color: #ffffff; }
.menu-usb-nombre { font-size: 13px; font-weight: 500; }
.menu-usb-ruta { font-family: FUENTE_MONO; font-size: 11px; color: #8b969c; }

.etiqueta-instalado { font-family: FUENTE_MONO; font-size: 10px; font-weight: 700; letter-spacing: 0.06em; color: #d4ff3f; }
.etiqueta-instalado.no-instalado { color: #f0645c; }
.etiqueta-instalado:disabled { color: #55606a; }

.cabecera-terminal { min-height: 31px; padding: 0 16px; background-color: #181c1f; border-bottom: 1px solid #232a2f; }
.titulo-terminal { font-family: FUENTE_MONO; font-size: 12px; font-weight: 700; letter-spacing: 0.08em; }
.pista { font-size: 12px; color: #8b969c; }
.fondo-terminal { background-color: #0f1113; }

.barra-inferior { min-height: 59px; padding: 0 20px; background-color: #181c1f; border-top: 1px solid #232a2f; }
.mensaje { color: #8b969c; }
.boton-parar { min-height: 38px; padding: 0 22px; border: 1px solid #e6eaec; background-color: transparent; color: #e6eaec; font-weight: 600; letter-spacing: 0.1em; }
.boton-parar:hover { background-color: #22282c; }
.boton-parar:disabled { border-color: #313a40; color: #6b7780; }
.boton-ejecutar { min-height: 40px; padding: 0 36px; border: none; background-color: #cf433c; color: #ffffff; font-weight: 700; letter-spacing: 0.12em; }
.boton-ejecutar:hover { background-color: #dc4b43; }
.boton-ejecutar:active { background-color: #b53a34; }
.boton-ejecutar:disabled { background-color: #232a2f; color: #3f4a52; }

tooltip, tooltip.background { background-image: none; background-color: #1b2024; border: 1px solid #414c53; box-shadow: inset 3px 0 0 #cf433c; padding: 0; color: #e6eaec; }
tooltip decoration { background-color: transparent; box-shadow: none; }
tooltip > box { padding: 8px 10px 8px 13px; }
.tooltip-contenido { padding: 4px 4px 4px 4px; }
.tooltip-titulo { font-size: 11px; font-weight: 700; letter-spacing: 0.12em; color: #8b969c; }
.tooltip-comando { font-family: FUENTE_MONO; font-size: 12px; color: #d4ff3f; }
.tooltip-texto { font-size: 13px; color: #b7c0c5; }

scrollbar { background-color: transparent; border: none; }
scrollbar slider { min-width: 6px; min-height: 6px; border: none; background-color: #313a40; }
""".replace("FUENTE_INTERFAZ", FUENTE_INTERFAZ).replace("FUENTE_MONO", FUENTE_MONO)

# Iconos de trazo cuadrado, en una rejilla de 24x24 (copiados del diseno).
# Cada forma es una lista de (cerrada, puntos).
FORMAS_ICONO = {
    "escudo": [
        (True, [(12, 3), (20, 6), (20, 12), (12, 21), (4, 12), (4, 6)]),
        (False, [(8.5, 12), (11, 14.5), (15.5, 9.5)]),
    ],
    "firmas": [
        (False, [(4, 8), (17, 8), (14, 5)]),
        (False, [(20, 16), (7, 16), (10, 19)]),
    ],
    "carpeta": [
        (True, [(3, 6), (10, 6), (12, 8), (21, 8), (21, 19), (3, 19)]),
    ],
    "usb": [
        (True, [(9, 3), (15, 3), (15, 9), (9, 9)]),
        (True, [(7, 9), (17, 9), (17, 21), (7, 21)]),
        (False, [(11, 5.5), (11, 6.5)]),
        (False, [(13, 5.5), (13, 6.5)]),
    ],
    "abajo": [
        (False, [(6, 9), (12, 15), (18, 9)]),
    ],
    "buscar": [
        (True, [(4, 4), (15, 4), (15, 15), (4, 15)]),
        (False, [(15, 15), (20, 20)]),
    ],
    "archivo": [
        (True, [(6, 3), (14, 3), (18, 7), (18, 21), (6, 21)]),
        (False, [(14, 3), (14, 7), (18, 7)]),
    ],
    "cuarentena": [
        (True, [(3, 8), (12, 3), (21, 8), (21, 17), (12, 22), (3, 17)]),
        (False, [(3, 8), (12, 13), (21, 8)]),
        (False, [(12, 13), (12, 22)]),
    ],
    "informe": [
        (True, [(6, 3), (18, 3), (18, 21), (6, 21)]),
        (False, [(9, 8), (15, 8)]),
        (False, [(9, 12), (15, 12)]),
        (False, [(9, 16), (13, 16)]),
    ],
    "ojo": [
        (True, [(2, 12), (7, 6), (17, 6), (22, 12), (17, 18), (7, 18)]),
        (True, [(10, 10), (14, 10), (14, 14), (10, 14)]),
    ],
    "version": [
        (True, [(4, 4), (20, 4), (20, 20), (4, 20)]),
        (False, [(12, 11), (12, 17)]),
        (False, [(12, 7), (12, 8)]),
    ],
    "ayuda": [
        (True, [(4, 4), (20, 4), (20, 20), (4, 20)]),
        (False, [(9, 9.5), (14, 9.5), (14, 12.5), (12, 12.5), (12, 14.5)]),
        (False, [(12, 17), (12, 18)]),
    ],
    "instalar": [
        (False, [(12, 4), (12, 15)]),
        (False, [(7, 11), (12, 16), (17, 11)]),
        (False, [(5, 20), (19, 20)]),
    ],
    "flecha": [
        (False, [(4, 12), (19, 12)]),
        (False, [(13, 6), (19, 12), (13, 18)]),
    ],
    "minimizar": [
        (False, [(4, 19), (20, 19)]),
    ],
    "maximizar": [
        (True, [(4, 4), (20, 4), (20, 20), (4, 20)]),
    ],
    "cerrar": [
        (False, [(5, 5), (19, 19)]),
        (False, [(19, 5), (5, 19)]),
    ],
    "abrir": [
        (False, [(14, 4), (20, 4), (20, 10)]),
        (False, [(20, 4), (11, 13)]),
        (False, [(18, 14), (18, 20), (4, 20), (4, 6), (10, 6)]),
    ],
}


def color_rgba(texto):
    color = Gdk.RGBA()
    color.parse(texto)
    return color


class Icono(Gtk.DrawingArea):
    """Icono vectorial dibujado con Cairo. El color sale del CSS (.icono)."""

    def __init__(self, forma, tamano=15, grosor=2.0):
        super().__init__()
        self.forma = forma
        self.tamano = tamano
        self.grosor = grosor
        self.set_size_request(tamano, tamano)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        self.get_style_context().add_class("icono")

    def do_draw(self, cr):
        color = self.get_style_context().get_color(self.get_state_flags())
        escala = self.tamano / 24.0
        cr.scale(escala, escala)
        cr.set_source_rgba(color.red, color.green, color.blue, color.alpha)
        cr.set_line_width(self.grosor)
        cr.set_line_cap(cairo.LINE_CAP_SQUARE)
        cr.set_line_join(cairo.LINE_JOIN_MITER)
        for cerrada, puntos in FORMAS_ICONO[self.forma]:
            cr.move_to(*puntos[0])
            for punto in puntos[1:]:
                cr.line_to(*punto)
            if cerrada:
                cr.close_path()
        cr.stroke()
        return False


class BarraProgreso(Gtk.DrawingArea):
    """Barra de 3 px con el extremo inclinado. Solo se redibuja al cambiar.

    En modo indeterminado un bloque recorre la barra a 10 fotogramas por
    segundo; el temporizador solo existe mientras dura ese modo.
    """

    def __init__(self):
        super().__init__()
        self.fraccion = 0.0
        self.posicion = 0.0
        self.temporizador = None
        self.set_size_request(-1, 3)
        self.color_fondo = color_rgba(COLOR_BORDE_SUAVE)
        self.color_relleno = color_rgba(COLOR_ROJO)

    def poner_fraccion(self, fraccion):
        self.poner_indeterminada(False)
        fraccion = max(0.0, min(1.0, fraccion))
        if fraccion != self.fraccion:
            self.fraccion = fraccion
            self.queue_draw()

    def poner_indeterminada(self, activa):
        if activa and self.temporizador is None:
            self.posicion = 0.0
            self.temporizador = GLib.timeout_add(INTERVALO_ANIMACION_MS, self.al_animar)
            self.queue_draw()
        elif not activa and self.temporizador is not None:
            GLib.source_remove(self.temporizador)
            self.temporizador = None
            self.queue_draw()

    def al_animar(self):
        self.posicion = (self.posicion + 0.025) % 1.0
        self.queue_draw()
        return True

    def do_draw(self, cr):
        ancho = self.get_allocated_width()
        alto = self.get_allocated_height()
        Gdk.cairo_set_source_rgba(cr, self.color_fondo)
        cr.rectangle(0, 0, ancho, alto)
        cr.fill()
        if self.temporizador is not None:
            # Bloque del 25 % que entra por la izquierda y sale por la derecha
            bloque = ancho * 0.25
            fin = self.posicion * (ancho + bloque)
            Gdk.cairo_set_source_rgba(cr, self.color_relleno)
            cr.move_to(max(0, fin - bloque), 0)
            cr.line_to(min(ancho, fin), 0)
            cr.line_to(min(ancho, max(0, fin - 6)), alto)
            cr.line_to(max(0, fin - bloque - 6), alto)
            cr.close_path()
            cr.fill()
            return False
        if self.fraccion <= 0:
            return False
        fin = ancho * self.fraccion
        Gdk.cairo_set_source_rgba(cr, self.color_relleno)
        cr.move_to(0, 0)
        cr.line_to(fin, 0)
        # Extremo inclinado de 6 px, salvo con la barra completa
        cr.line_to(fin if self.fraccion >= 1 else max(0, fin - 6), alto)
        cr.line_to(0, alto)
        cr.close_path()
        cr.fill()
        return False


def recortar_esquinas(widget, cr, corte=12):
    """Esquinas cortadas en diagonal (superior derecha e inferior izquierda).

    Se conecta a 'draw' antes del dibujo propio del boton: solo recorta la
    zona de dibujo, asi que no anade redibujados ni temporizadores.
    """
    ancho = widget.get_allocated_width()
    alto = widget.get_allocated_height()
    cr.move_to(0, 0)
    cr.line_to(ancho - corte, 0)
    cr.line_to(ancho, corte)
    cr.line_to(ancho, alto)
    cr.line_to(corte, alto)
    cr.line_to(0, alto - corte)
    cr.close_path()
    cr.clip()
    return False


def anadir_clases(widget, *clases):
    contexto = widget.get_style_context()
    for clase in clases:
        contexto.add_class(clase)
    return widget


def etiqueta(texto, *clases, xalign=0.0):
    return anadir_clases(Gtk.Label(label=texto, xalign=xalign), *clases)


# ---------------------------------------------------------------------------
# Ventana principal
# ---------------------------------------------------------------------------

class VentanaLauncher(Gtk.Window):

    def __init__(self):
        super().__init__(title=NOMBRE_APP)
        self.set_icon_name("clamav-launcher")  # lo instala install.sh
        self.set_default_size(1200, 800)
        self.set_size_request(1000, 640)

        self.pid_shell = None
        self.clamscan_instalado = shutil.which("clamscan") is not None
        self.botones_comando = []    # se deshabilitan si falta clamscan
        self.cache_tooltips = {}     # contenido de los tooltips, creado al vuelo
        self.pulsado = None          # widget a resaltar si se escribe el comando
        self.seleccionado = None     # widget resaltado ahora mismo
        self.temporizador_usb = None
        self.usb_actuales = None     # tupla de (nombre, punto); None = sin mirar
        self.menu_usb = None

        # Estado de ejecucion
        self.bloqueables = []        # controles de la barra lateral que se bloquean
        self.tarjetas = []
        self.bloqueada = False
        self.comando_pendiente = None  # escrito por un boton y aun sin ejecutar
        self.ejecucion = None          # comando en curso (dict) o None
        self.estado = "espera"
        self.temporizador_sondeo = None
        self.sondeos_con_shell = 0
        self.temporizador_lectura = None
        self.fila_leida = None         # primera fila de la terminal aun sin leer
        self.progreso = None
        self.recuento = None           # recuento previo de archivos y bytes
        self.lineas_found = []         # (fila, texto) para pintarlas en ambar
        self.columnas_found = None

        self.construir_barra_titulo()

        raiz = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        raiz.pack_start(self.construir_franja_progreso(), False, False, 0)
        cuerpo = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        cuerpo.pack_start(self.construir_barra_lateral(), False, False, 0)
        cuerpo.pack_start(self.construir_panel_terminal(), True, True, 0)
        raiz.pack_start(cuerpo, True, True, 0)
        self.add(raiz)

        self.config_guardada = cargar_config()
        self.aplicar_config(self.config_guardada)
        self.aplicar_estado_instalacion()
        self.refrescar_usb()
        self.poner_estado("espera")
        self.connect("notify::is-active", self.al_cambiar_foco)
        self.connect("delete-event", self.al_cerrar)
        self.connect("destroy", Gtk.main_quit)
        self.lanzar_shell()

    # --- Construccion de la interfaz ---------------------------------------

    def construir_barra_titulo(self):
        # Botones de ventana propios para usar los iconos de trazo cuadrado
        barra = Gtk.HeaderBar()
        barra.set_show_close_button(False)
        for forma, tooltip, accion, clase in (
                ("cerrar", "Cerrar", lambda *_: self.close(), "boton-cerrar"),
                ("maximizar", "Maximizar", self.al_pulsar_maximizar, None),
                ("minimizar", "Minimizar", lambda *_: self.iconify(), None)):
            boton = self.boton_icono(forma, tooltip, "boton-ventana", 12)
            if clase:
                anadir_clases(boton, clase)
            boton.set_can_focus(False)
            boton.connect("clicked", accion)
            barra.pack_end(boton)
        titulo = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        titulo.pack_start(anadir_clases(Icono("escudo", 18), "icono-escudo"), False, False, 0)
        titulo.pack_start(etiqueta("CLAMAV LAUNCHER", "titulo-app"), False, False, 0)
        barra.pack_start(titulo)
        barra.set_custom_title(Gtk.Box())  # sin titulo centrado
        self.set_titlebar(barra)

    def al_pulsar_maximizar(self, *_):
        if self.is_maximized():
            self.unmaximize()
        else:
            self.maximize()

    def construir_franja_progreso(self):
        franja = anadir_clases(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "franja")
        contenido = anadir_clases(
            Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14), "franja-contenido")
        contenido.set_size_request(-1, 41)

        self.etiqueta_estado = etiqueta("EN ESPERA", "insignia")
        self.etiqueta_estado.set_valign(Gtk.Align.CENTER)
        self.etiqueta_detalle = etiqueta(
            "Nada se ejecuta hasta que pulses Ejecutar", "franja-detalle")
        self.etiqueta_detalle.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        contenido.pack_start(self.etiqueta_estado, False, False, 0)
        contenido.pack_start(self.etiqueta_detalle, True, True, 0)

        metricas = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=22)
        self.valores_progreso = {}
        for clave, titulo, inicial in (
                ("archivos", "ARCHIVOS", "-- / --"),
                ("restante", "RESTANTE", "--"),
                ("velocidad", "VELOCIDAD", "--"),
                ("infectados", "INFECTADOS", "0")):
            caja = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            caja.set_baseline_position(Gtk.BaselinePosition.CENTER)
            titulo_metrica = etiqueta(titulo, "metrica-titulo")
            valor = etiqueta(inicial, "metrica-valor")
            titulo_metrica.set_valign(Gtk.Align.BASELINE)
            valor.set_valign(Gtk.Align.BASELINE)
            caja.pack_start(titulo_metrica, False, False, 0)
            caja.pack_start(valor, False, False, 0)
            metricas.pack_start(caja, False, False, 0)
            self.valores_progreso[clave] = valor
        separador = anadir_clases(Gtk.Box(), "separador")
        separador.set_valign(Gtk.Align.CENTER)
        metricas.pack_start(separador, False, False, 0)
        self.valor_porcentaje = etiqueta("0%", "porcentaje", xalign=1.0)
        self.valor_porcentaje.set_size_request(40, -1)
        metricas.pack_start(self.valor_porcentaje, False, False, 0)
        contenido.pack_end(metricas, False, False, 0)

        self.barra_progreso = BarraProgreso()
        franja.pack_start(contenido, True, True, 0)
        franja.pack_start(self.barra_progreso, False, False, 0)
        return franja

    def construir_barra_lateral(self):
        caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=ESPACIO_SECCIONES)
        caja.set_border_width(12)

        # PASO 1
        paso1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        paso1.pack_start(etiqueta("PASO 1 / SIEMPRE PRIMERO", "seccion", "paso1"), False, False, 0)
        self.boton_freshclam = anadir_clases(Gtk.Button(), "boton-paso1")
        contenido = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        contenido.pack_start(Icono("firmas", 22), False, False, 0)
        textos = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        textos.set_valign(Gtk.Align.CENTER)
        textos.pack_start(etiqueta("Actualizar firmas", "paso1-titulo"), False, False, 0)
        textos.pack_start(etiqueta("Hazlo antes de cada escaneo", "paso1-sub"), False, False, 0)
        contenido.pack_start(textos, True, True, 0)
        self.boton_freshclam.add(contenido)
        self.clave_freshclam = "freshclam_servicio" if servicio_freshclam_activo() else "freshclam"
        self.poner_tooltip(self.boton_freshclam, lambda: self.clave_freshclam)
        self.boton_freshclam.connect("clicked", self.registrar_pulsado, self.boton_freshclam)
        self.boton_freshclam.connect("clicked", self.al_pulsar_freshclam)
        self.botones_comando.append(self.boton_freshclam)
        paso1.pack_start(self.boton_freshclam, False, False, 0)
        self.nota_paso1 = etiqueta("Te pedirá tu contraseña en la terminal.", "nota")
        paso1.pack_start(self.nota_paso1, False, False, 0)
        caja.pack_start(paso1, False, False, 0)

        # PASO 2
        paso2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        paso2.pack_start(etiqueta("PASO 2 / QUÉ ANALIZAR", "seccion"), False, False, 0)
        fila_ruta = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.entrada_ruta = anadir_clases(Gtk.Entry(), "entrada-ruta")
        self.entrada_ruta.set_placeholder_text("Carpeta, USB o archivo")
        self.entrada_ruta.set_text(os.path.expanduser("~"))
        self.entrada_ruta.set_width_chars(8)
        # El Paso 2 es el unico sitio donde se decide que analizar
        self.boton_elegir_carpeta = self.boton_icono(
            "carpeta", "Elegir carpeta…", "boton-cuadrado", 16)
        self.boton_elegir_carpeta.connect(
            "clicked", self.al_examinar_ruta, Gtk.FileChooserAction.SELECT_FOLDER)
        self.boton_elegir_archivo = self.boton_icono(
            "archivo", "Elegir archivo…", "boton-cuadrado", 16)
        self.boton_elegir_archivo.connect(
            "clicked", self.al_examinar_ruta, Gtk.FileChooserAction.OPEN)
        fila_ruta.pack_start(self.entrada_ruta, True, True, 0)
        fila_ruta.pack_start(self.boton_elegir_carpeta, False, False, 0)
        fila_ruta.pack_start(self.boton_elegir_archivo, False, False, 0)
        paso2.pack_start(fila_ruta, False, False, 0)
        # Boton de USB: atenuado si no hay ninguno; con USB abre un menu
        self.boton_usb = anadir_clases(Gtk.Button(), "boton-usb")
        fila_usb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        fila_usb.pack_start(Icono("usb"), False, False, 0)
        fila_usb.pack_start(etiqueta("Elegir USB"), True, True, 0)
        self.etiqueta_usb = etiqueta("", "etiqueta-usb", xalign=1.0)
        fila_usb.pack_start(self.etiqueta_usb, False, False, 0)
        self.flecha_usb = Icono("abajo", 12)
        self.flecha_usb.set_no_show_all(True)
        fila_usb.pack_start(self.flecha_usb, False, False, 0)
        self.boton_usb.add(fila_usb)
        self.boton_usb.set_tooltip_text(
            "Elige un USB conectado para analizarlo. Solo está disponible "
            "cuando hay algún USB conectado.")
        self.boton_usb.connect("clicked", self.al_pulsar_usb)
        paso2.pack_start(self.boton_usb, False, False, 0)
        caja.pack_start(paso2, False, False, 0)
        self.bloqueables += [self.nota_paso1, self.entrada_ruta, self.boton_elegir_carpeta,
                             self.boton_elegir_archivo]

        # PASO 3
        paso3 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=ESPACIO_BOTONES)
        titulo = etiqueta("PASO 3 / ESCANEAR", "seccion")
        titulo.set_margin_bottom(0)
        paso3.pack_start(titulo, False, False, 0)
        paso3.pack_start(self.boton_accion(
            "Escanear", "buscar", "escanear",
            self.al_pulsar_escanear), False, False, 0)
        tarjeta, self.entrada_cuarentena = self.tarjeta_destino(
            "Escanear y mover a cuarentena", "cuarentena", "cuarentena",
            self.al_pulsar_cuarentena, CARPETA_CUARENTENA_DEFECTO)
        paso3.pack_start(tarjeta, False, False, 0)
        tarjeta, self.entrada_informes = self.tarjeta_destino(
            "Escanear y guardar informe", "informe", "informe",
            self.al_pulsar_informe, CARPETA_INFORMES_DEFECTO)
        paso3.pack_start(tarjeta, False, False, 0)
        paso3.pack_start(self.boton_accion(
            "Ver último informe", "ojo", "ver_informe",
            self.al_pulsar_ver_informe), False, False, 0)
        caja.pack_start(paso3, False, False, 0)

        # UTILIDADES
        utilidades = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=ESPACIO_BOTONES)
        titulo = etiqueta("UTILIDADES", "seccion")
        titulo.set_margin_bottom(0)
        utilidades.pack_start(titulo, False, False, 0)
        utilidades.pack_start(self.boton_accion(
            "Ver versión", "version", "version",
            lambda *_: self.escribir_comando("clamscan --version")), False, False, 0)
        utilidades.pack_start(self.boton_accion(
            "Ayuda de clamscan", "ayuda", "ayuda",
            lambda *_: self.escribir_comando("clamscan --help")), False, False, 0)
        self.etiqueta_instalado = etiqueta("", "etiqueta-instalado", xalign=1.0)
        self.boton_instalar = self.boton_accion(
            "Instalar ClamAV", "instalar", "instalar", self.al_pulsar_instalar,
            extra=self.etiqueta_instalado, es_comando=False)
        utilidades.pack_start(self.boton_instalar, False, False, 0)
        caja.pack_start(utilidades, False, False, 0)

        # Con ventanas bajas (minimo 640 px) la barra lateral necesita scroll
        desplazable = anadir_clases(Gtk.ScrolledWindow(), "barra-lateral")
        desplazable.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        desplazable.set_size_request(280, -1)
        desplazable.add(caja)
        return desplazable

    def construir_panel_terminal(self):
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        cabecera = anadir_clases(
            Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL), "cabecera-terminal")
        nombre_shell = os.path.basename(shell_del_usuario()).upper()
        cabecera.pack_start(etiqueta("TERMINAL / " + nombre_shell, "titulo-terminal"),
                            False, False, 0)
        self.etiqueta_pista = etiqueta("Puedes editar el comando antes de ejecutar", "pista")
        cabecera.pack_end(self.etiqueta_pista, False, False, 0)
        panel.pack_start(cabecera, False, False, 0)

        self.terminal = Vte.Terminal()
        self.configurar_terminal()
        fondo = anadir_clases(Gtk.Box(), "fondo-terminal")
        self.terminal.set_margin_top(18)
        self.terminal.set_margin_bottom(18)
        self.terminal.set_margin_start(24)
        self.terminal.set_margin_end(24)
        fondo.pack_start(self.terminal, True, True, 0)
        panel.pack_start(fondo, True, True, 0)

        barra = anadir_clases(
            Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12), "barra-inferior")
        self.etiqueta_mensaje = etiqueta("", "mensaje")
        self.etiqueta_mensaje.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.mostrar_mensaje(MENSAJE_INICIAL)
        barra.pack_start(self.etiqueta_mensaje, True, True, 0)

        self.boton_ejecutar = anadir_clases(Gtk.Button(label="EJECUTAR"), "boton-ejecutar")
        self.boton_ejecutar.set_valign(Gtk.Align.CENTER)
        self.boton_ejecutar.connect("clicked", self.al_pulsar_ejecutar)
        self.boton_ejecutar.connect("draw", recortar_esquinas)
        self.boton_parar = anadir_clases(Gtk.Button(label="PARAR"), "boton-parar")
        self.boton_parar.set_valign(Gtk.Align.CENTER)
        self.boton_parar.connect("clicked", self.al_pulsar_parar)
        barra.pack_end(self.boton_ejecutar, False, False, 0)
        barra.pack_end(self.boton_parar, False, False, 0)
        panel.pack_start(barra, False, False, 0)
        return panel

    def configurar_terminal(self):
        self.terminal.set_scrollback_lines(LINEAS_SCROLLBACK)
        fuente = Pango.FontDescription.from_string("JetBrains Mono, Monospace")
        fuente.set_absolute_size(14 * Pango.SCALE)
        self.terminal.set_font(fuente)
        self.terminal.set_cell_height_scale(1.7)
        self.terminal.set_bold_is_bright(True)
        self.terminal.set_colors(
            color_rgba(COLOR_TERMINAL_TEXTO), color_rgba(COLOR_TERMINAL_FONDO),
            [color_rgba(c) for c in PALETA_TERMINAL])
        self.terminal.set_color_cursor(color_rgba(COLOR_TERMINAL_CURSOR))
        self.terminal.set_color_cursor_foreground(color_rgba(COLOR_TERMINAL_FONDO))
        self.terminal.set_cursor_blink_mode(Vte.CursorBlinkMode.OFF)  # sin redibujos en reposo
        self.terminal.connect("child-exited", self.al_salir_shell)
        # 'commit' llega con todo lo que se envia a la shell (teclado y botones)
        self.terminal.connect("commit", self.al_enviar_a_terminal)
        self.terminal.connect("contents-changed", self.al_cambiar_contenido)
        self.terminal.connect_after("draw", self.al_dibujar_terminal)
        self.color_found = color_rgba("#ffb224")
        self.color_fondo_terminal = color_rgba(COLOR_TERMINAL_FONDO)

    # --- Utilidades de construccion -----------------------------------------

    def boton_icono(self, forma, tooltip, clase, tamano):
        boton = anadir_clases(Gtk.Button(), clase)
        boton.add(Icono(forma, tamano))
        boton.set_tooltip_text(tooltip)
        return boton

    def boton_accion(self, texto, forma, clave_tooltip, al_pulsar, extra=None,
                     objetivo=None, es_comando=True):
        """Boton de la barra lateral: icono, texto y (opcional) etiqueta a la derecha."""
        boton = anadir_clases(Gtk.Button(), "boton-accion")
        fila = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        fila.pack_start(Icono(forma), False, False, 0)
        fila.pack_start(etiqueta(texto), True, True, 0)
        if extra is not None:
            fila.pack_end(extra, False, False, 0)
        boton.add(fila)
        self.poner_tooltip(boton, lambda: clave_tooltip)
        boton.connect("clicked", self.registrar_pulsado, objetivo or boton)
        boton.connect("clicked", al_pulsar)
        if es_comando:
            self.botones_comando.append(boton)
        return boton

    def tarjeta_destino(self, texto, forma, clave_tooltip, al_pulsar, ruta_defecto):
        """Boton de escaneo con una fila de destino editable debajo."""
        tarjeta = anadir_clases(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "tarjeta")
        tarjeta.pack_start(self.boton_accion(
            texto, forma, clave_tooltip, al_pulsar, objetivo=tarjeta), False, False, 0)

        fila = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        fila.set_margin_start(6)
        fila.set_margin_end(6)
        fila.set_margin_bottom(6)
        campo = anadir_clases(Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL), "campo-destino")
        flecha = anadir_clases(Gtk.Box(), "flecha-destino")
        flecha.pack_start(Icono("flecha", 12, 2.5), True, True, 0)
        campo.pack_start(flecha, False, False, 0)
        entrada = anadir_clases(Gtk.Entry(), "entrada-destino")
        entrada.set_text(ruta_defecto)
        entrada.set_width_chars(6)
        campo.pack_start(entrada, True, True, 0)
        fila.pack_start(campo, True, True, 0)
        boton_elegir = self.boton_icono("carpeta", "Elegir carpeta", "boton-mini", 14)
        boton_elegir.connect("clicked", lambda *_: self.elegir_carpeta_destino(entrada))
        boton_abrir = self.boton_icono("abrir", "Abrir carpeta", "boton-mini", 14)
        boton_abrir.connect("clicked", lambda *_: self.abrir_carpeta(entrada))
        fila.pack_start(boton_elegir, False, False, 0)
        fila.pack_start(boton_abrir, False, False, 0)
        tarjeta.pack_start(fila, False, False, 0)
        # Durante un escaneo solo queda activo el boton de abrir la carpeta
        self.bloqueables += [entrada, boton_elegir]
        self.tarjetas.append(tarjeta)
        return tarjeta, entrada

    # --- Tooltips y seleccion -------------------------------------------------

    def poner_tooltip(self, widget, obtener_clave):
        """Tooltip propio: titulo, comando de plantilla en lima y explicacion."""
        widget.set_has_tooltip(True)
        widget.connect("query-tooltip", self.al_pedir_tooltip, obtener_clave)

    def al_pedir_tooltip(self, _widget, _x, _y, _teclado, tooltip, obtener_clave):
        clave = obtener_clave()
        contenido = self.cache_tooltips.get(clave)
        if contenido is None:
            plantilla, explicacion = TOOLTIPS[clave]
            contenido = anadir_clases(
                Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6), "tooltip-contenido")
            contenido.pack_start(etiqueta("QUÉ HACE ESTE BOTÓN", "tooltip-titulo"), False, False, 0)
            comando = etiqueta(plantilla, "tooltip-comando")
            texto = etiqueta(explicacion, "tooltip-texto")
            for parte in (comando, texto):
                parte.set_line_wrap(True)
                parte.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
                parte.set_max_width_chars(40)
                contenido.pack_start(parte, False, False, 0)
            contenido.show_all()
            self.cache_tooltips[clave] = contenido
        tooltip.set_custom(contenido)
        return True

    def registrar_pulsado(self, _boton, objetivo):
        self.pulsado = objetivo

    def marcar_seleccionado(self, widget):
        if self.seleccionado is not None:
            self.seleccionado.get_style_context().remove_class("seleccionado")
        self.seleccionado = widget
        if widget is not None:
            widget.get_style_context().add_class("seleccionado")

    # --- Terminal -------------------------------------------------------------

    def lanzar_shell(self):
        self.terminal.spawn_async(
            Vte.PtyFlags.DEFAULT, os.path.expanduser("~"), [shell_del_usuario()],
            None, GLib.SpawnFlags.DEFAULT, None, None, -1, None,
            self.al_lanzar_shell)

    def al_lanzar_shell(self, _terminal, pid, error, *_):
        if error is not None:
            self.mostrar_mensaje("No se ha podido iniciar la terminal: " + error.message)
            return
        self.pid_shell = pid

    def al_salir_shell(self, *_):
        # Si el usuario escribe 'exit', se abre una shell nueva y se limpia el estado
        self.pid_shell = None
        self.comando_pendiente = None
        if self.temporizador_sondeo is not None:
            GLib.source_remove(self.temporizador_sondeo)
            self.temporizador_sondeo = None
        if self.ejecucion is not None:
            self.terminar_ejecucion()
        self.lanzar_shell()

    # --- Ajustes y cierre -----------------------------------------------------

    def aplicar_config(self, config):
        for clave, entrada in (("ruta_analizar", self.entrada_ruta),
                               ("carpeta_cuarentena", self.entrada_cuarentena),
                               ("carpeta_informes", self.entrada_informes)):
            if config.get(clave):
                entrada.set_text(config[clave])

    def guardar_si_cambia(self):
        """Solo escribe en disco si alguna ruta ha cambiado desde la ultima vez."""
        actual = {
            "ruta_analizar": self.entrada_ruta.get_text().strip(),
            "carpeta_cuarentena": self.entrada_cuarentena.get_text().strip(),
            "carpeta_informes": self.entrada_informes.get_text().strip(),
        }
        if actual != self.config_guardada and guardar_config(actual):
            self.config_guardada = actual

    def al_cerrar(self, *_):
        if self.hay_comando_en_curso():
            dialogo = Gtk.MessageDialog(
                transient_for=self, modal=True, message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.NONE, text="Hay un comando en curso")
            dialogo.format_secondary_text(
                "Si cierras la ventana, el comando se detendrá. "
                "¿Quieres cerrarla de todos modos?")
            dialogo.add_buttons("Cancelar", Gtk.ResponseType.CANCEL,
                                "Cerrar", Gtk.ResponseType.ACCEPT)
            respuesta = dialogo.run()
            dialogo.destroy()
            if respuesta != Gtk.ResponseType.ACCEPT:
                return True  # no se cierra
        self.cancelar_recuento()
        self.guardar_si_cambia()
        return False

    def escribir_comando(self, comando, mensaje=MENSAJE_COMANDO_ESCRITO, ruta=None,
                         escaneo=None):
        """Sustituye la linea actual de la terminal por el comando, sin Enter.

        'escaneo' = {"ruta", "recursivo"} si el comando es un escaneo de clamscan.
        """
        if self.hay_comando_en_curso():
            # Nunca se escribe sobre un programa en marcha (podria leerlo como respuesta)
            self.mostrar_mensaje("Hay un comando en curso. Espera a que termine o pulsa Parar.")
            return
        if self.estado == "terminado":
            self.poner_estado("espera")
        self.cancelar_recuento()
        self.terminal.feed_child(TECLA_FIN_DE_LINEA + TECLA_BORRAR_LINEA + comando.encode("utf-8"))
        self.terminal.grab_focus()
        self.marcar_seleccionado(self.pulsado)
        self.mostrar_mensaje(mensaje, ruta)
        self.comando_pendiente = {"texto": comando, "escaneo": escaneo}
        self.guardar_si_cambia()
        if escaneo and escaneo["recursivo"]:
            # Se cuenta en segundo plano desde ya, para tener el total al ejecutar
            self.iniciar_recuento(escaneo["ruta"])

    def mostrar_mensaje(self, texto, ruta=None):
        """Texto de la barra inferior; la ruta, si la hay, va en monoespaciada."""
        marcado = GLib.markup_escape_text(texto)
        if ruta:
            marcado += ' <span font_family="JetBrains Mono, Monospace" foreground="#e6eaec">{}</span>'.format(
                GLib.markup_escape_text(ruta))
        self.etiqueta_mensaje.set_markup(marcado)

    def al_pulsar_ejecutar(self, *_):
        # El Enter llega tambien por 'commit', que arranca el seguimiento
        self.terminal.feed_child(TECLA_ENTER)
        self.terminal.grab_focus()

    def al_pulsar_parar(self, *_):
        self.terminal.feed_child(TECLA_INTERRUMPIR)
        self.terminal.grab_focus()
        if self.ejecucion is not None:
            self.ejecucion["detenido"] = True
        self.cancelar_recuento()

    # --- Deteccion del comando en curso -----------------------------------------

    def hay_comando_en_curso(self):
        """True si el grupo de procesos en primer plano de la pty no es la shell."""
        pty = self.terminal.get_pty()
        if pty is None or self.pid_shell is None:
            return False
        try:
            return os.tcgetpgrp(pty.get_fd()) != self.pid_shell
        except OSError:
            return False

    def al_enviar_a_terminal(self, _terminal, texto, _tamano):
        if "\r" in texto or "\n" in texto:
            self.al_pulsar_enter()

    def al_pulsar_enter(self):
        if self.ejecucion is not None:
            return  # Enter dentro de un comando en curso (p. ej. la contrasena de sudo)
        pendiente, self.comando_pendiente = self.comando_pendiente, None
        if pendiente is not None:
            self.empezar_ejecucion(pendiente)
        # Tambien se vigilan los comandos tecleados a mano: si duran, se bloquea
        self.sondeos_con_shell = 0
        if self.temporizador_sondeo is None:
            self.temporizador_sondeo = GLib.timeout_add(INTERVALO_SONDEO_MS, self.al_sondear)

    def al_sondear(self):
        if self.hay_comando_en_curso():
            self.sondeos_con_shell = 0
            if self.ejecucion is None:
                self.empezar_ejecucion(None)
            return True
        # La shell vuelve a primer plano entre los comandos de 'a && b'; se
        # espera a verla varias veces seguidas antes de dar el comando por acabado
        self.sondeos_con_shell += 1
        if self.sondeos_con_shell < SONDEOS_PARA_TERMINAR:
            return True
        self.temporizador_sondeo = None
        if self.ejecucion is not None:
            self.terminar_ejecucion()
        return False

    def empezar_ejecucion(self, pendiente):
        escaneo = pendiente["escaneo"] if pendiente else None
        self.ejecucion = {
            "texto": pendiente["texto"] if pendiente else None,
            "escaneo": escaneo,
            "detenido": False,
        }
        self.bloquear_barra(True)
        if escaneo is None:
            self.poner_estado("ejecutando")
            return
        archivos_total = bytes_total = None
        if (escaneo["recursivo"] and self.recuento is not None
                and self.recuento["ruta"] == escaneo["ruta"]):
            archivos_total = self.recuento["archivos"]
            bytes_total = self.recuento["bytes"]
        elif not escaneo["recursivo"]:
            archivos_total = 1
        self.progreso = Progreso(archivos_total, bytes_total)
        # La salida empieza en la fila siguiente a la del comando
        self.fila_leida = self.terminal.get_cursor_position()[1] + 1
        self.poner_estado("cargando")

    def terminar_ejecucion(self):
        ejecucion, self.ejecucion = self.ejecucion, None
        if self.temporizador_lectura is not None:
            GLib.source_remove(self.temporizador_lectura)
            self.temporizador_lectura = None
        self.cancelar_recuento()
        if ejecucion["escaneo"] is not None:
            self.procesar_salida(ejecucion)
        self.bloquear_barra(False)
        self.marcar_seleccionado(None)
        self.poner_estado("terminado", ejecucion)

    def bloquear_barra(self, bloquear):
        """Atenua la barra lateral mientras hay un comando en curso, salvo los
        botones de abrir carpeta."""
        self.bloqueada = bloquear
        for widget in self.bloqueables + self.botones_comando + [self.boton_instalar]:
            widget.set_sensitive(not bloquear)
        for tarjeta in self.tarjetas:
            contexto = tarjeta.get_style_context()
            if bloquear:
                contexto.add_class("bloqueada")
            else:
                contexto.remove_class("bloqueada")
        self.boton_usb.set_sensitive(not bloquear and bool(self.usb_actuales))
        if not bloquear:
            self.aplicar_estado_instalacion()

    # --- Franja de progreso ---------------------------------------------------

    def poner_estado(self, estado, ejecucion=None):
        self.estado = estado
        insignia = self.etiqueta_estado.get_style_context()
        for clase in ("escaneando", "ejecutando", "terminado"):
            insignia.remove_class(clase)
        en_curso = estado in ("cargando", "escaneando", "ejecutando")
        self.boton_parar.set_sensitive(en_curso)
        self.boton_ejecutar.set_sensitive(not en_curso)
        self.valor_porcentaje.get_style_context().remove_class("activo")
        detalle = self.etiqueta_detalle.get_style_context()
        detalle.remove_class("ruta")
        escaneo = self.ejecucion["escaneo"] if self.ejecucion else None

        if estado == "espera":
            self.etiqueta_estado.set_text("EN ESPERA")
            self.etiqueta_detalle.set_text("Nada se ejecuta hasta que pulses Ejecutar")
            self.etiqueta_pista.set_text("Puedes editar el comando antes de ejecutar")
            self.progreso = None
            self.actualizar_metricas()
            self.barra_progreso.poner_fraccion(0)
            return

        if en_curso:
            insignia.add_class("escaneando" if estado == "escaneando" else "ejecutando")
            if escaneo is not None:
                self.etiqueta_estado.set_text(
                    "CARGANDO FIRMAS" if estado == "cargando" else "ESCANEANDO")
                self.etiqueta_detalle.set_text(escaneo["ruta"])
                detalle.add_class("ruta")
                self.etiqueta_pista.set_text("Escaneo en curso")
                self.mostrar_mensaje("Escaneo en curso. Parar envía Ctrl+C a la terminal.")
            else:
                self.etiqueta_estado.set_text("EJECUTANDO")
                texto = self.ejecucion["texto"] if self.ejecucion else None
                self.etiqueta_detalle.set_text(texto or "Comando escrito en la terminal")
                if texto:
                    detalle.add_class("ruta")
                self.etiqueta_pista.set_text("Comando en curso")
                self.mostrar_mensaje("Comando en curso. Parar envía Ctrl+C a la terminal.")
            # Barra con porcentaje solo en escaneos de carpeta ya iniciados
            con_porcentaje = (estado == "escaneando" and escaneo["recursivo"]
                              and self.progreso.fraccion() is not None)
            if con_porcentaje:
                self.valor_porcentaje.get_style_context().add_class("activo")
                self.actualizar_metricas()
            else:
                self.barra_progreso.poner_indeterminada(True)
            return

        # Terminado
        insignia.add_class("terminado")
        self.etiqueta_estado.set_text("TERMINADO")
        self.etiqueta_pista.set_text("Puedes editar el comando antes de ejecutar")
        self.barra_progreso.poner_fraccion(1)
        if ejecucion is not None and ejecucion["escaneo"] is not None and self.progreso is not None:
            progreso = self.progreso
            if not ejecucion["detenido"] and ejecucion["escaneo"]["recursivo"]:
                self.valor_porcentaje.set_text("100%")
            self.valores_progreso["restante"].set_text("--")
            self.etiqueta_detalle.set_text(ejecucion["escaneo"]["ruta"])
            detalle.add_class("ruta")
            inicio = "Escaneo detenido" if ejecucion["detenido"] else "Escaneo terminado"
            texto = "{}: {}, {}.".format(
                inicio,
                cantidad(progreso.archivos, "archivo analizado", "archivos analizados"),
                cantidad(progreso.infectados, "infectado", "infectados"))
            if progreso.infectados:
                texto += " Revisa las líneas en ámbar."
            self.mostrar_mensaje(texto)
        else:
            detenido = ejecucion is not None and ejecucion["detenido"]
            self.etiqueta_detalle.set_text(
                "Comando detenido" if detenido else "Comando terminado")
            self.mostrar_mensaje("Terminado. Revisa el resultado en la terminal.")

    def actualizar_metricas(self):
        progreso = self.progreso
        valores = self.valores_progreso
        if progreso is None:
            valores["archivos"].set_text("-- / --")
            valores["restante"].set_text("--")
            valores["velocidad"].set_text("--")
            valores["infectados"].set_text("0")
            valores["infectados"].get_style_context().remove_class("ambar")
            self.valor_porcentaje.set_text("0%")
            return
        instante = time.monotonic()
        total = progreso.archivos_total
        valores["archivos"].set_text("{} / {}".format(
            formatear_miles(progreso.archivos),
            formatear_miles(total) if total is not None else "--"))
        valores["infectados"].set_text(formatear_miles(progreso.infectados))
        if progreso.infectados:
            valores["infectados"].get_style_context().add_class("ambar")
        escaneo = self.ejecucion["escaneo"] if self.ejecucion else None
        if escaneo is not None and escaneo["recursivo"]:
            valores["velocidad"].set_text(formatear_velocidad(progreso.velocidad()))
            valores["restante"].set_text(formatear_restante(progreso.restante(instante)))
            fraccion = progreso.fraccion()
            if fraccion is not None:
                self.valor_porcentaje.set_text("{}%".format(int(fraccion * 100)))
                self.barra_progreso.poner_fraccion(fraccion)

    # --- Recuento previo (hilo secundario) --------------------------------------

    def iniciar_recuento(self, ruta):
        import threading

        cancelado = threading.Event()
        recuento = {"ruta": ruta, "archivos": None, "bytes": None, "cancelado": cancelado}
        self.recuento = recuento

        def contar():
            try:
                os.nice(10)  # en Linux afecta solo a este hilo
            except OSError:
                pass
            resultado = contar_ruta(ruta, cancelado)
            if resultado is not None:
                # Los widgets solo se tocan desde el hilo principal
                GLib.idle_add(self.al_terminar_recuento, recuento, resultado)

        threading.Thread(target=contar, daemon=True).start()

    def al_terminar_recuento(self, recuento, resultado):
        if recuento is not self.recuento or recuento["cancelado"].is_set():
            return False
        recuento["archivos"], recuento["bytes"] = resultado
        escaneo = self.ejecucion["escaneo"] if self.ejecucion else None
        if self.progreso is not None and escaneo is not None and escaneo["ruta"] == recuento["ruta"]:
            self.progreso.archivos_total, self.progreso.bytes_total = resultado
            if self.estado == "escaneando":
                self.poner_estado("escaneando")
        return False

    def cancelar_recuento(self):
        if self.recuento is not None:
            self.recuento["cancelado"].set()
            self.recuento = None

    # --- Lectura de la salida de clamscan -------------------------------------

    def al_cambiar_contenido(self, _terminal):
        # Se lee como maximo cada 250 ms, y solo durante un escaneo
        if (self.ejecucion is not None and self.ejecucion["escaneo"] is not None
                and self.temporizador_lectura is None):
            self.temporizador_lectura = GLib.timeout_add(
                INTERVALO_LECTURA_MS, self.al_temporizador_lectura)

    def al_temporizador_lectura(self):
        self.temporizador_lectura = None
        if self.ejecucion is not None:
            self.procesar_salida(self.ejecucion)
        return False

    def texto_filas(self, desde, hasta):
        """Texto de las filas [desde, hasta] (las lineas partidas salen enteras)."""
        # La columna final es exclusiva: con 'columnas - 1' se perderia el
        # ultimo caracter de las filas llenas
        columnas = self.terminal.get_column_count()
        if hasattr(self.terminal, "get_text_range_format"):
            texto = self.terminal.get_text_range_format(
                Vte.Format.TEXT, desde, 0, hasta, columnas)[0]
        else:  # VTE anteriores a 0.72
            texto = self.terminal.get_text_range(desde, 0, hasta, columnas, None)[0]
        return texto or ""

    def procesar_salida(self, ejecucion):
        """Lee solo las filas nuevas y completas (antes de la del cursor)."""
        escaneo = ejecucion["escaneo"]
        progreso = self.progreso
        fila_cursor = self.terminal.get_cursor_position()[1]
        if self.fila_leida is None or progreso is None or fila_cursor <= self.fila_leida:
            return
        columnas = self.terminal.get_column_count()
        if ejecucion.setdefault("columnas", columnas) != columnas:
            # Al cambiar el ancho VTE reparte de nuevo las filas: se sigue desde
            # el cursor (el resumen final corrige los totales)
            ejecucion["columnas"] = columnas
            self.fila_leida = fila_cursor
            return
        lineas = self.texto_filas(self.fila_leida, fila_cursor - 1).split("\n")
        if lineas and lineas[-1] == "":
            lineas.pop()
        instante = time.monotonic()
        fila = self.fila_leida
        resumen = {}
        for linea in lineas:
            resultado = analizar_linea_clamscan(linea, escaneo["ruta"])
            if resultado is not None:
                ruta, tipo = resultado
                try:
                    tamano = os.stat(ruta).st_size
                except OSError:
                    tamano = 0
                progreso.registrar(instante, tamano, tipo == "infectado")
                if tipo == "infectado":
                    self.recordar_found(fila, linea, columnas)
            else:
                for clave in ("Scanned files", "Infected files"):
                    valor = valor_resumen(linea, clave)
                    if valor is not None:
                        resumen[clave] = valor
            fila += max(1, math.ceil(len(linea) / columnas))
        self.fila_leida = fila_cursor
        # El resumen final manda sobre lo contado linea a linea
        if "Infected files" in resumen:
            progreso.infectados = resumen["Infected files"]
        if "Scanned files" in resumen:
            progreso.archivos = max(progreso.archivos, resumen["Scanned files"])
        progreso.anotar_muestra(instante)
        if self.estado == "cargando" and progreso.inicio is not None and self.ejecucion is not None:
            self.poner_estado("escaneando")
        self.actualizar_metricas()

    # --- Lineas FOUND en ambar ------------------------------------------------
    # clamscan no colorea su salida. En lugar de reescribir la terminal (feed()
    # es asincrono y podria caer en otra fila), se pinta encima en 'draw',
    # comprobando antes que la fila sigue teniendo ese texto.

    def recordar_found(self, fila, linea, columnas):
        if self.columnas_found != columnas:
            self.lineas_found = []
            self.columnas_found = columnas
        self.lineas_found.append((fila, linea))
        del self.lineas_found[:-MAXIMO_LINEAS_FOUND]
        self.terminal.queue_draw()

    def al_dibujar_terminal(self, terminal, cr):
        if not self.lineas_found:
            return False
        columnas = terminal.get_column_count()
        if columnas != self.columnas_found:
            # Al cambiar el ancho VTE reparte de nuevo las lineas: se descartan
            self.lineas_found = []
            return False
        arriba = int(terminal.get_vadjustment().get_value())
        filas_visibles = terminal.get_row_count()
        ancho = terminal.get_char_width()
        alto = terminal.get_char_height()
        relleno = terminal.get_style_context().get_padding(terminal.get_state_flags())
        disposicion = None
        for fila_inicio, linea in self.lineas_found:
            for indice in range(max(1, math.ceil(len(linea) / columnas))):
                fila = fila_inicio + indice
                if not arriba <= fila < arriba + filas_visibles:
                    continue
                trozo = linea[indice * columnas:(indice + 1) * columnas]
                # Solo si la fila sigue mostrando ese texto
                if self.texto_filas(fila, fila).rstrip("\n").rstrip() != trozo.rstrip():
                    continue
                if disposicion is None:
                    disposicion = terminal.create_pango_layout("")
                    disposicion.set_font_description(terminal.get_font())
                x = relleno.left
                y = relleno.top + (fila - arriba) * alto
                Gdk.cairo_set_source_rgba(cr, self.color_fondo_terminal)
                cr.rectangle(x, y, len(trozo) * ancho, alto)
                cr.fill()
                Gdk.cairo_set_source_rgba(cr, self.color_found)
                for columna, caracter in enumerate(trozo):
                    if caracter == " ":
                        continue
                    disposicion.set_text(caracter, -1)
                    alto_texto = disposicion.get_pixel_extents()[1].height
                    cr.move_to(x + columna * ancho, y + (alto - alto_texto) / 2)
                    PangoCairo.show_layout(cr, disposicion)
        return False

    # --- Rutas ----------------------------------------------------------------

    def ruta_a_analizar(self):
        """Ruta absoluta del Paso 2, o None (con aviso) si no es valida."""
        ruta = normalizar_ruta(self.entrada_ruta.get_text())
        if not ruta:
            self.mostrar_mensaje("Indica qué analizar en el Paso 2.")
            return None
        if not os.path.exists(ruta):
            self.mostrar_mensaje("La ruta no existe:", ruta)
            return None
        return ruta

    def carpeta_destino(self, entrada, ruta_defecto):
        """Ruta absoluta del campo de destino, creando la carpeta si falta."""
        ruta = normalizar_ruta(entrada.get_text()) or normalizar_ruta(ruta_defecto)
        try:
            os.makedirs(ruta, exist_ok=True)
        except OSError as error:
            self.mostrar_mensaje("No se ha podido crear la carpeta ({}):".format(
                error.strerror), ruta)
            return None
        return ruta

    def elegir_ruta(self, titulo, accion, carpeta_inicial):
        dialogo = Gtk.FileChooserDialog(title=titulo, transient_for=self, action=accion)
        dialogo.add_buttons("Cancelar", Gtk.ResponseType.CANCEL,
                            "Seleccionar", Gtk.ResponseType.ACCEPT)
        if carpeta_inicial and os.path.isdir(carpeta_inicial):
            dialogo.set_current_folder(carpeta_inicial)
        ruta = None
        if dialogo.run() == Gtk.ResponseType.ACCEPT:
            ruta = dialogo.get_filename()
        dialogo.destroy()
        return ruta

    def al_examinar_ruta(self, _boton, accion):
        actual = normalizar_ruta(self.entrada_ruta.get_text())
        inicial = actual if os.path.isdir(actual) else os.path.dirname(actual)
        if accion == Gtk.FileChooserAction.OPEN:
            titulo = "Elegir archivo a analizar"
        else:
            titulo = "Elegir carpeta a analizar"
        ruta = self.elegir_ruta(titulo, accion, inicial)
        if ruta:
            self.entrada_ruta.set_text(ruta)

    def elegir_carpeta_destino(self, entrada):
        ruta = self.elegir_ruta("Elegir carpeta", Gtk.FileChooserAction.SELECT_FOLDER,
                                normalizar_ruta(entrada.get_text()))
        if ruta:
            entrada.set_text(ruta)

    def abrir_carpeta(self, entrada):
        import subprocess

        ruta = self.carpeta_destino(entrada, "")
        if not ruta:
            return
        try:
            subprocess.Popen(["xdg-open", ruta], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except OSError:
            self.mostrar_mensaje("No se ha podido abrir la carpeta", ruta)

    # --- USB ------------------------------------------------------------------

    def al_cambiar_foco(self, *_):
        # Refresco de USB cada 5 s solo con la ventana visible y activa
        if self.is_active() and self.get_visible():
            self.refrescar_usb()
            if self.temporizador_usb is None:
                self.temporizador_usb = GLib.timeout_add_seconds(5, self.al_temporizador_usb)
        elif self.temporizador_usb is not None:
            GLib.source_remove(self.temporizador_usb)
            self.temporizador_usb = None

    def al_temporizador_usb(self):
        # No se toca nada mientras el menu de USB esta abierto
        if not (self.menu_usb is not None and self.menu_usb.get_visible()):
            self.refrescar_usb()
        return True

    def refrescar_usb(self):
        """Activa el boton de USB solo si hay alguno conectado."""
        unidades = tuple(detectar_unidades_usb())
        if unidades == self.usb_actuales:
            return  # sin cambios: no se toca la interfaz
        self.usb_actuales = unidades
        hay_usb = bool(unidades)
        self.boton_usb.set_sensitive(hay_usb and not self.bloqueada)
        self.flecha_usb.set_visible(hay_usb)
        contexto = self.etiqueta_usb.get_style_context()
        if not hay_usb:
            self.etiqueta_usb.set_text("NINGUNO CONECTADO")
            contexto.add_class("ninguno")
        else:
            cantidad = len(unidades)
            self.etiqueta_usb.set_text(
                "1 CONECTADO" if cantidad == 1 else "{} CONECTADOS".format(cantidad))
            contexto.remove_class("ninguno")

    def al_pulsar_usb(self, boton):
        # Se vuelve a mirar al pulsar por si el USB se ha retirado hace poco
        self.refrescar_usb()
        if not self.usb_actuales:
            return
        if self.menu_usb is not None:
            self.menu_usb.destroy()
        self.menu_usb = anadir_clases(Gtk.Menu(), "menu-usb")
        self.menu_usb.set_size_request(boton.get_allocated_width(), -1)
        for nombre, punto in self.usb_actuales:
            elemento = Gtk.MenuItem()
            textos = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            textos.pack_start(etiqueta(nombre, "menu-usb-nombre"), False, False, 0)
            ruta = etiqueta(punto, "menu-usb-ruta")
            ruta.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            textos.pack_start(ruta, False, False, 0)
            elemento.add(textos)
            elemento.connect("activate", self.al_elegir_usb, nombre, punto)
            self.menu_usb.append(elemento)
        self.menu_usb.show_all()
        self.menu_usb.popup_at_widget(
            boton, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)

    def al_elegir_usb(self, _elemento, nombre, punto):
        self.entrada_ruta.set_text(punto)
        self.mostrar_mensaje("USB elegido: {}. Ahora elige cómo escanearlo en el Paso 3.".format(nombre))

    # --- Estado de instalacion ------------------------------------------------

    def aplicar_estado_instalacion(self):
        if not self.clamscan_instalado:
            self.marcar_seleccionado(None)
        for boton in self.botones_comando:
            boton.set_sensitive(self.clamscan_instalado)
        contexto = self.etiqueta_instalado.get_style_context()
        if self.clamscan_instalado:
            self.etiqueta_instalado.set_text("INSTALADO")
            contexto.remove_class("no-instalado")
            self.boton_instalar.get_style_context().remove_class("destacado")
        else:
            self.etiqueta_instalado.set_text("NO INSTALADO")
            contexto.add_class("no-instalado")
            self.boton_instalar.get_style_context().add_class("destacado")
        self.nota_paso1.set_sensitive(self.clamscan_instalado)

    # --- Botones de comandos --------------------------------------------------

    def al_pulsar_freshclam(self, *_):
        activo = servicio_freshclam_activo()
        self.clave_freshclam = "freshclam_servicio" if activo else "freshclam"
        self.escribir_comando(comando_freshclam(activo))

    def al_pulsar_escanear(self, *_):
        ruta = self.ruta_a_analizar()
        if ruta:
            recursivo = os.path.isdir(ruta)
            self.escribir_comando(comando_escanear(ruta, recursivo),
                                  escaneo={"ruta": ruta, "recursivo": recursivo})

    def al_pulsar_cuarentena(self, *_):
        ruta = self.ruta_a_analizar()
        if not ruta:
            return
        destino = self.carpeta_destino(self.entrada_cuarentena, CARPETA_CUARENTENA_DEFECTO)
        if destino:
            recursivo = os.path.isdir(ruta)
            self.escribir_comando(
                comando_cuarentena(ruta, destino, recursivo),
                "Los infectados se mueven (no se borran) a", destino,
                escaneo={"ruta": ruta, "recursivo": recursivo})

    def al_pulsar_informe(self, *_):
        import datetime

        ruta = self.ruta_a_analizar()
        if not ruta:
            return
        destino = self.carpeta_destino(self.entrada_informes, CARPETA_INFORMES_DEFECTO)
        if destino:
            recursivo = os.path.isdir(ruta)
            self.escribir_comando(
                comando_informe(ruta, destino, datetime.datetime.now(), recursivo),
                "El informe se guardará en", destino,
                escaneo={"ruta": ruta, "recursivo": recursivo})

    def al_pulsar_ver_informe(self, *_):
        carpeta = normalizar_ruta(self.entrada_informes.get_text()) \
            or normalizar_ruta(CARPETA_INFORMES_DEFECTO)
        informe = informe_mas_reciente(carpeta)
        if not informe:
            self.mostrar_mensaje("Todavía no hay informes en", carpeta)
            return
        self.escribir_comando(
            comando_ver_informe(informe),
            "Mostrará el informe más reciente de", carpeta)

    def al_pulsar_instalar(self, *_):
        comando = comando_instalacion()
        if not comando:
            self.mostrar_mensaje(
                "No se ha detectado un gestor de paquetes compatible. "
                "Instala ClamAV con el gestor de tu sistema.")
            return
        self.escribir_comando(comando, "Comando escrito. Te pedirá la contraseña al ejecutarlo.")


def cargar_css():
    proveedor = Gtk.CssProvider()
    proveedor.load_from_data(CSS.encode("utf-8"))
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), proveedor, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


def main():
    # El nombre coincide con clamav-launcher.desktop: el panel muestra su icono
    GLib.set_prgname("clamav-launcher")
    GLib.set_application_name(NOMBRE_APP)
    ajustes = Gtk.Settings.get_default()
    if ajustes is not None:
        ajustes.set_property("gtk-application-prefer-dark-theme", True)
    cargar_css()
    ventana = VentanaLauncher()
    ventana.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
