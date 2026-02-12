#!/bin/bash
set -euo pipefail

BIN_DIR="${HOME}/.local/bin"
KITTY_CONF="${HOME}/.config/kitty/kitty.conf"

echo "=== Zeus uninstaller ==="

# Remove binaries
rm -f "$BIN_DIR/zeus" "$BIN_DIR/zeus-launch"
echo "✓ Removed zeus and zeus-launch from $BIN_DIR"

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
echo "Done."
