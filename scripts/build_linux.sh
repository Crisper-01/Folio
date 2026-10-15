#!/usr/bin/env bash
# Build the Linux bundle. Run inside a container (see build_linux_docker.sh)
# or directly on a Linux machine with Python 3.11+.
set -euo pipefail
SRC="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
OUT="$SRC/dist-linux"
WORK=/tmp/folio-build

PY="${PYTHON:-python3}"
if command -v dnf >/dev/null && [ "$(id -u)" = 0 ]; then
  # EPEL provides xcb-util-cursor, required by Qt's xcb plugin and bundled into the build
  dnf install -y -q epel-release >/dev/null
  dnf install -y -q python3.12 binutils mesa-libGL mesa-libEGL libxkbcommon libxkbcommon-x11 fontconfig dbus-libs \
    xcb-util-cursor xcb-util-image xcb-util-keysyms xcb-util-renderutil xcb-util-wm glib2 >/dev/null
elif command -v apt-get >/dev/null && [ "$(id -u)" = 0 ]; then
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends \
    binutils libgl1 libegl1 libxkbcommon0 libxkbcommon-x11-0 libfontconfig1 libdbus-1-3 \
    libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 \
    libxcb-shape0 libxcb-xinerama0 libxcb-xkb1 libglib2.0-0 >/dev/null
fi

rm -rf "$WORK" && mkdir -p "$WORK" && cp -r "$SRC/folio" "$SRC/tests" "$SRC/run_folio.py" "$SRC/folio.spec" "$SRC/pyproject.toml" "$WORK/"
cd "$WORK"
find . -name "__pycache__" -prune -exec rm -rf {} +
"$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q PySide6 pymupdf pymupdf-fonts pyinstaller pytest pytest-qt

QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests
.venv/bin/pyinstaller folio.spec --noconfirm --log-level WARN
./dist/Folio/folio --selftest

VERSION=$(.venv/bin/python -c "import folio; print(folio.__version__)")
PKG="folio-$VERSION-linux-x86_64"
mkdir -p "$PKG"
cp -r dist/Folio "$PKG/folio"
cp folio/assets/folio.png "$PKG/folio.png"
cat > "$PKG/install.sh" <<'INSTALL'
#!/usr/bin/env bash
# Install Folio for the current user (no root needed).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.local/opt/folio"
rm -rf "$DEST" && mkdir -p "$DEST" "$HOME/.local/bin" "$HOME/.local/share/applications" "$HOME/.local/share/icons/hicolor/256x256/apps"
cp -r "$HERE/folio/." "$DEST/"
ln -sf "$DEST/folio" "$HOME/.local/bin/folio"
cp "$HERE/folio.png" "$HOME/.local/share/icons/hicolor/256x256/apps/folio.png"
cat > "$HOME/.local/share/applications/folio.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Folio
GenericName=Éditeur PDF
Comment=Compresser, annoter, signer et réorganiser vos PDF en local
Exec=$DEST/folio %F
Icon=folio
Terminal=false
Categories=Office;Viewer;Graphics;
MimeType=application/pdf;image/png;image/jpeg;
StartupWMClass=folio
DESKTOP
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
echo "Folio est installé. Lancez-le depuis le menu des applications ou avec la commande : folio"
INSTALL
cat > "$PKG/uninstall.sh" <<'UNINSTALL'
#!/usr/bin/env bash
rm -rf "$HOME/.local/opt/folio" "$HOME/.local/bin/folio" "$HOME/.local/share/applications/folio.desktop" \
  "$HOME/.local/share/icons/hicolor/256x256/apps/folio.png"
echo "Folio a été désinstallé."
UNINSTALL
chmod +x "$PKG/install.sh" "$PKG/uninstall.sh"
mkdir -p "$OUT"
tar -czf "$OUT/$PKG.tar.gz" "$PKG"
echo "Built $OUT/$PKG.tar.gz"
