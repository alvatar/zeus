#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="${HOME}/.local/bin"

echo "=== Zeus installer ==="
echo ""

# 1. Copy binaries
mkdir -p "$BIN_DIR"
cp "$SCRIPT_DIR/bin/zeus" "$BIN_DIR/zeus"
chmod +x "$BIN_DIR/zeus"
cp "$SCRIPT_DIR/bin/zeus-launch" "$BIN_DIR/zeus-launch"
chmod +x "$BIN_DIR/zeus-launch"
echo "✓ Copied zeus and zeus-launch to $BIN_DIR"

# 2. Patch kitty.conf (idempotent)
KITTY_CONF="${HOME}/.config/kitty/kitty.conf"
if [ -f "$KITTY_CONF" ]; then
    if grep -q "Zeus agent monitor" "$KITTY_CONF" 2>/dev/null; then
        echo "✓ kitty.conf already patched"
    else
        echo "" >> "$KITTY_CONF"
        cat "$SCRIPT_DIR/config/kitty.conf.snippet" >> "$KITTY_CONF"
        echo "✓ Patched $KITTY_CONF"
    fi
else
    mkdir -p "$(dirname "$KITTY_CONF")"
    cat "$SCRIPT_DIR/config/kitty.conf.snippet" > "$KITTY_CONF"
    echo "✓ Created $KITTY_CONF"
fi

# 3. Sway config (just show instructions — too risky to auto-patch)
echo ""
echo "── Manual step: Sway config ──"
echo "Edit ~/.config/sway/config and change your terminal keybinding:"
echo ""
echo "  # Replace:"
echo "  #   bindsym \$mod+Return exec \$term"
echo "  # With:"
echo "  bindsym \$mod+Return exec zeus-launch"
echo ""
echo "Then reload sway: swaymsg reload"
echo ""

# 4. Verify
echo "── Status ──"
if command -v zeus &>/dev/null; then
    echo "✓ zeus is in PATH"
else
    echo "⚠ zeus not in PATH — make sure $BIN_DIR is in your PATH"
fi

if command -v zeus-launch &>/dev/null; then
    echo "✓ zeus-launch is in PATH"
else
    echo "⚠ zeus-launch not in PATH"
fi

echo ""
echo "⚠ Restart kitty for remote control to take effect."
echo "Done."
