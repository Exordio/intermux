#!/bin/sh
# Installs InterMux system-wide from this checkout:
#   /opt/intermux                      the code, owned by root
#   /usr/local/bin/intermux            the CLI
#   /usr/local/bin/intermux-gui        the GUI
#   /usr/local/share/applications      the menu entry
#   /usr/local/share/icons/hicolor     the icons
#   /usr/share/polkit-1/actions        the polkit action, which gives the password prompt its message
# Usage: sudo ./install.sh [--uninstall]; PREFIX, TARGET and POLKIT_ACTIONS can be overridden from the environment.
set -eu

PREFIX=${PREFIX:-/usr/local}
TARGET=${TARGET:-/opt/intermux}
POLKIT_ACTIONS=${POLKIT_ACTIONS:-/usr/share/polkit-1/actions}
POLICY=io.github.exordio.intermux.policy
SOURCE=$(cd "$(dirname "$0")" && pwd)
ICON_SIZES="512 256 128 64 48 32"

refresh_caches() {
    if command -v gtk-update-icon-cache >/dev/null; then
        gtk-update-icon-cache -q -t "$PREFIX/share/icons/hicolor" || true
    fi
    if command -v update-desktop-database >/dev/null; then
        update-desktop-database -q "$PREFIX/share/applications" || true
    fi
}

uninstall() {
    rm -rf "$TARGET"
    rm -f "$PREFIX/bin/intermux" "$PREFIX/bin/intermux-gui" "$PREFIX/share/applications/intermux.desktop"
    rm -f "$POLKIT_ACTIONS/$POLICY"
    for size in $ICON_SIZES; do
        rm -f "$PREFIX/share/icons/hicolor/${size}x${size}/apps/intermux.png"
    done
    refresh_caches
}

# A Python script rather than "python3 -m", which would put the current directory first on sys.path
# and could run another copy. The GUI restarts itself as root through this very file, so it must be
# the program itself, not a shell wrapper: the polkit action is matched by its path.
write_launcher() {
    cat > "$PREFIX/bin/$1" <<LAUNCHER
#!/usr/bin/python3
import sys
sys.path.insert(0, "$TARGET")
from $2 import main
sys.exit(main())
LAUNCHER
    chmod 755 "$PREFIX/bin/$1"
}

if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root: sudo $0 [--uninstall]" >&2
    exit 1
fi

if [ "${1:-}" = "--uninstall" ]; then
    uninstall
    echo "InterMux removed. Per-user history and app logs stay in ~/.local/share/intermux."
    exit 0
fi

# The GUI runs as root, so the code it runs must not be writable by a regular user.
rm -rf "$TARGET"
mkdir -p "$TARGET"
cp -r "$SOURCE/intermux" "$TARGET/"
find "$TARGET" -name __pycache__ -type d -prune -exec rm -rf {} +
chown -R root:root "$TARGET"
chmod -R u=rwX,go=rX "$TARGET"

mkdir -p "$PREFIX/bin"
write_launcher intermux intermux.cli
write_launcher intermux-gui intermux.gui.app

install -Dm644 "$SOURCE/packaging/intermux.desktop" "$PREFIX/share/applications/intermux.desktop"
for size in $ICON_SIZES; do
    install -Dm644 "$SOURCE/intermux/gui/icons/intermux-$size.png" \
        "$PREFIX/share/icons/hicolor/${size}x${size}/apps/intermux.png"
done
mkdir -p "$POLKIT_ACTIONS"
sed "s|/usr/bin/intermux-gui|$PREFIX/bin/intermux-gui|" "$SOURCE/packaging/$POLICY" > "$POLKIT_ACTIONS/$POLICY.tmp"
chmod 644 "$POLKIT_ACTIONS/$POLICY.tmp"
mv "$POLKIT_ACTIONS/$POLICY.tmp" "$POLKIT_ACTIONS/$POLICY"
refresh_caches

echo "InterMux installed to $TARGET. Run 'intermux-gui' or find InterMux in the application menu."
