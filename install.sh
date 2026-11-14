#!/usr/bin/env bash
# Instala ClamAV Launcher para el usuario actual y lo anade al lanzador de
# aplicaciones. Solo pide la contrasena (sudo) si falta algun componente del
# sistema, y antes de instalarlo pregunta.
#
# Uso: bash install.sh

set -euo pipefail

cd "$(dirname "$0")"
DATOS="${XDG_DATA_HOME:-$HOME/.local/share}"
CARPETA_APP="$DATOS/clamav-launcher"
ARCHIVO_DESKTOP="$DATOS/applications/clamav-launcher.desktop"
ARCHIVO_ICONO="$DATOS/icons/hicolor/scalable/apps/clamav-launcher.svg"

faltan_componentes() {
    ! python3 -c "import gi, cairo; gi.require_version('Gtk', '3.0'); gi.require_version('Vte', '2.91'); from gi.repository import Gtk, Vte" >/dev/null 2>&1 \
        || ! command -v clamscan >/dev/null 2>&1 \
        || ! command -v freshclam >/dev/null 2>&1
}

comando_instalacion() {
    # Nunca se instala el demonio clamd: clamscan no lo necesita
    if command -v apt >/dev/null 2>&1; then
        echo "sudo apt install --no-install-recommends python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-vte-2.91 clamav clamav-freshclam"
    elif command -v dnf >/dev/null 2>&1; then
        echo "sudo dnf install --setopt=install_weak_deps=False python3-gobject gtk3 vte291 clamav clamav-freshclam"
    elif command -v pacman >/dev/null 2>&1; then
        echo "sudo pacman -S --needed python-gobject python-cairo gtk3 vte3 clamav"
    elif command -v zypper >/dev/null 2>&1; then
        echo "sudo zypper install --no-recommends python3-gobject python3-gobject-cairo typelib-1_0-Gtk-3_0 typelib-1_0-Vte-2_91 clamav"
    fi
}

echo "== Instalación de ClamAV Launcher =="

if ! command -v python3 >/dev/null 2>&1; then
    echo "Falta Python 3. Instálalo con el gestor de software de tu sistema y vuelve a ejecutar este instalador."
    exit 1
fi

if faltan_componentes; then
    comando="$(comando_instalacion)"
    if [ -z "$comando" ]; then
        echo "Faltan componentes y no se ha detectado un gestor de paquetes compatible."
        echo "Instala con el gestor de tu sistema: Python 3 con PyGObject y Cairo, GTK 3, VTE 2.91 y ClamAV (clamscan y freshclam)."
        exit 1
    fi
    echo "Faltan componentes del sistema. Se instalarán con este comando:"
    echo
    echo "    $comando"
    echo
    read -r -p "¿Instalarlos ahora? Te pedirá tu contraseña. [s/N] " respuesta
    case "$respuesta" in
        s|S|si|SI|sí|Sí) $comando ;;
        *) echo "Instalación cancelada. No se ha cambiado nada."; exit 1 ;;
    esac
    if faltan_componentes; then
        echo "Siguen faltando componentes. Revisa los mensajes anteriores."
        exit 1
    fi
fi

# Archivos de la app, icono y entrada del lanzador (todo dentro de tu carpeta personal).
# La carpeta de la app se vacia antes, para no dejar restos de versiones anteriores.
rm -rf "$CARPETA_APP"
mkdir -p "$CARPETA_APP" "$(dirname "$ARCHIVO_DESKTOP")" "$(dirname "$ARCHIVO_ICONO")"
cp clamav_launcher.py "$CARPETA_APP/"
cp uninstall.sh "$CARPETA_APP/"  # para desinstalar aunque se borre la descarga
cp clamav-launcher.svg "$ARCHIVO_ICONO"

cat > "$ARCHIVO_DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=ClamAV Launcher
GenericName=Revisión de virus
Comment=Terminal con botones para revisar USB y archivos con ClamAV
Exec=python3 "$CARPETA_APP/clamav_launcher.py"
Icon=clamav-launcher
Terminal=false
Categories=Utility;Security;
Keywords=antivirus;virus;clamav;clamscan;usb;escanear;
StartupNotify=true
StartupWMClass=clamav-launcher
EOF

# Avisa al escritorio de la nueva entrada (si la utilidad existe). No se crea
# cache de iconos: una cache de usuario puede ocultar iconos de otras apps.
update-desktop-database "$(dirname "$ARCHIVO_DESKTOP")" >/dev/null 2>&1 || true

echo
echo "Listo. Busca «ClamAV Launcher» en tu lanzador de aplicaciones."
echo "Antes del primer escaneo, pulsa «Actualizar firmas» dentro de la app."
