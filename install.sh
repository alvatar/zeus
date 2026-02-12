#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
LIB_DIR="${HOME}/.local/lib"

DEV_MODE=false
if [ "${1:-}" = "--dev" ] || [ "${1:-}" = "-d" ]; then
    DEV_MODE=true
fi

echo "=== Zeus installer ==="
if $DEV_MODE; then
    echo "Mode: development (symlinks)"
else
    echo "Mode: install (copy)"
fi
echo ""

# 1. Install zeus binary and package
mkdir -p "$BIN_DIR"
if $DEV_MODE; then
    # Symlink entry point — it auto-detects ../zeus/ in repo
    ln -sf "$SCRIPT_DIR/bin/zeus" "$BIN_DIR/zeus"
    echo "✓ Symlinked $BIN_DIR/zeus → $SCRIPT_DIR/bin/zeus"
else
    # Copy entry point and package
    cp "$SCRIPT_DIR/bin/zeus" "$BIN_DIR/zeus"
    chmod +x "$BIN_DIR/zeus"

    # Copy zeus/ package to ~/.local/lib/zeus/
    rm -rf "$LIB_DIR/zeus"
    cp -r "$SCRIPT_DIR/zeus" "$LIB_DIR/zeus"
    echo "✓ Copied zeus to $BIN_DIR and package to $LIB_DIR/zeus"
fi

# 2. zeus-launch helper
if [ -f "$SCRIPT_DIR/bin/zeus-launch" ]; then
    if $DEV_MODE; then
        ln -sf "$SCRIPT_DIR/bin/zeus-launch" "$BIN_DIR/zeus-launch"
        echo "✓ Symlinked zeus-launch"
    else
        cp "$SCRIPT_DIR/bin/zeus-launch" "$BIN_DIR/zeus-launch"
        chmod +x "$BIN_DIR/zeus-launch"
        echo "✓ Copied zeus-launch to $BIN_DIR"
    fi
fi

# 3. Patch kitty.conf (idempotent)
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

# 4. Sway config (just show instructions)
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

# 5. Verify
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
