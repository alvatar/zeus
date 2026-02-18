#!/bin/bash
set -euo pipefail

BIN_DIR="${HOME}/.local/bin"
KITTY_CONF="${HOME}/.config/kitty/kitty.conf"
PI_BIN="$BIN_DIR/pi"
PI_ORIG="$BIN_DIR/pi.zeus-orig"
PI_EXTENSION_FILE="${HOME}/.pi/agent/extensions/zeus.ts"

echo "=== Zeus uninstaller ==="

# Remove binaries
rm -f "$BIN_DIR/zeus" "$BIN_DIR/zeus-msg" "$BIN_DIR/zeus-launch"
echo "✓ Removed zeus, zeus-msg and zeus-launch from $BIN_DIR"

# Remove Zeus pi extension bundle
if [ -e "$PI_EXTENSION_FILE" ] || [ -L "$PI_EXTENSION_FILE" ]; then
    if rm -f "$PI_EXTENSION_FILE" 2>/dev/null; then
        echo "✓ Removed Zeus pi extension from $PI_EXTENSION_FILE"
    else
        echo "⚠ Could not remove Zeus pi extension at $PI_EXTENSION_FILE" >&2
    fi
fi

# Restore pi if Zeus wrapper is present
if [ -f "$PI_BIN" ] && grep -q "Zeus pi wrapper" "$PI_BIN" 2>/dev/null; then
    rm -f "$PI_BIN"
    if [ -e "$PI_ORIG" ] || [ -L "$PI_ORIG" ]; then
        mv "$PI_ORIG" "$PI_BIN"
        echo "✓ Restored original pi binary to $PI_BIN"
    else
        echo "⚠ Removed Zeus pi wrapper, but no backup found at $PI_ORIG"
    fi
elif [ ! -e "$PI_BIN" ] && ([ -e "$PI_ORIG" ] || [ -L "$PI_ORIG" ]); then
    mv "$PI_ORIG" "$PI_BIN"
    echo "✓ Restored original pi binary to $PI_BIN"
fi

# Remove kitty.conf patch
if [ -f "$KITTY_CONF" ]; then
    sed -i '/# --- Zeus agent monitor ---/,/# --- End Zeus ---/d' "$KITTY_CONF"
    echo "✓ Removed zeus config from $KITTY_CONF"
fi

echo ""
echo "── Manual step ──"
echo "Revert your sway keybinding back to:"
echo "  bindsym \$mod+Return exec \$term"
echo ""
echo "Note: sandbox config is preserved at ~/.config/zeus/sandbox-paths.conf"
echo "Done."
