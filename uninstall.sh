#!/usr/bin/env bash
# Quita ClamAV Launcher del usuario actual. No toca ClamAV, ni tus ajustes,
# ni las carpetas de cuarentena e informes.
#
# Uso: bash uninstall.sh

set -euo pipefail

DATOS="${XDG_DATA_HOME:-$HOME/.local/share}"

rm -rf "$DATOS/clamav-launcher"
rm -f "$DATOS/applications/clamav-launcher.desktop"
rm -f "$DATOS/icons/hicolor/scalable/apps/clamav-launcher.svg"
update-desktop-database "$DATOS/applications" >/dev/null 2>&1 || true

echo "ClamAV Launcher se ha quitado del lanzador de aplicaciones."
echo "Se conservan tus ajustes (~/.config/clamav-launcher) y las carpetas de"
echo "cuarentena e informes (por defecto ~/ClamAV). Puedes borrarlos a mano."
