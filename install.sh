#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
LIB_DIR="${HOME}/.local/lib"

DEV_MODE=false
WRAP_PI=false

for arg in "$@"; do
    case "$arg" in
        --dev|-d)
            DEV_MODE=true
            ;;
        --wrap-pi)
            WRAP_PI=true
            ;;
        *)
            echo "Unknown option: $arg" >&2
            echo "Usage: $0 [--dev|-d] [--wrap-pi]" >&2
            exit 1
            ;;
    esac
done

echo "=== Zeus installer ==="
if $DEV_MODE; then
    echo "Mode: development (symlinks)"
else
    echo "Mode: install (copy)"
fi
if $WRAP_PI; then
    echo "pi wrapper: enabled"
else
    echo "pi wrapper: disabled"
    echo "⚠⚠⚠ NOTICE: pi wrapper is NOT installed in this run."
    echo "⚠ Independent pi launches won't get deterministic ZEUS_AGENT_ID by default."
    echo "⚠ Run with --wrap-pi to enable it."
fi
echo ""

# 1. Install zeus binary and package
mkdir -p "$BIN_DIR"
if $DEV_MODE; then
    # Symlink entry points — they auto-detect ../zeus/ in repo
    ln -sf "$SCRIPT_DIR/bin/zeus" "$BIN_DIR/zeus"
    ln -sf "$SCRIPT_DIR/bin/zeus-msg" "$BIN_DIR/zeus-msg"
    echo "✓ Symlinked $BIN_DIR/zeus → $SCRIPT_DIR/bin/zeus"
    echo "✓ Symlinked $BIN_DIR/zeus-msg → $SCRIPT_DIR/bin/zeus-msg"
else
    # Copy entry points and package
    cp "$SCRIPT_DIR/bin/zeus" "$BIN_DIR/zeus"
    cp "$SCRIPT_DIR/bin/zeus-msg" "$BIN_DIR/zeus-msg"
    chmod +x "$BIN_DIR/zeus" "$BIN_DIR/zeus-msg"

    # Copy zeus/ package to ~/.local/lib/zeus/
    rm -rf "$LIB_DIR/zeus"
    cp -r "$SCRIPT_DIR/zeus" "$LIB_DIR/zeus"
    echo "✓ Copied zeus/zeus-msg to $BIN_DIR and package to $LIB_DIR/zeus"
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

# 3. Optional pi wrapper for deterministic ZEUS_AGENT_ID on independent pi launches
if $WRAP_PI; then
    PI_BIN="$BIN_DIR/pi"
    PI_ORIG="$BIN_DIR/pi.zeus-orig"
    WRAP_READY=false

    if [ ! -e "$PI_BIN" ] && [ ! -L "$PI_BIN" ]; then
        echo "⚠ $PI_BIN not found; skipping pi wrapper"
    else
        if grep -q "Zeus pi wrapper" "$PI_BIN" 2>/dev/null; then
            echo "✓ pi already wrapped by Zeus (refreshing wrapper)"
            WRAP_READY=true
        else
            if [ -e "$PI_ORIG" ] || [ -L "$PI_ORIG" ]; then
                echo "✓ Backup already exists at $PI_ORIG (reusing)"
                WRAP_READY=true
            else
                mv "$PI_BIN" "$PI_ORIG"
                echo "✓ Backed up original pi to $PI_ORIG"
                WRAP_READY=true
            fi
        fi

        if $WRAP_READY; then
            cat > "$PI_BIN" <<EOF
#!/bin/bash
# --- Zeus pi wrapper ---
set -euo pipefail

PI_REAL="$PI_ORIG"

if [ -z "\${ZEUS_AGENT_ID:-}" ]; then
    ZEUS_AGENT_ID=\$(python3 - <<'PY'
import uuid
print(uuid.uuid4().hex)
PY
)
    export ZEUS_AGENT_ID
fi

if [ -z "\${ZEUS_ROLE:-}" ]; then
    export ZEUS_ROLE="hippeus"
fi

tmux set -ga update-environment ZEUS_AGENT_ID >/dev/null 2>&1 || true
tmux set -ga update-environment ZEUS_ROLE >/dev/null 2>&1 || true

if [ ! -e "\$PI_REAL" ] && [ ! -L "\$PI_REAL" ]; then
    echo "Zeus pi wrapper error: original pi not found at \$PI_REAL" >&2
    exit 1
fi

exec "\$PI_REAL" "\$@"
EOF
            chmod +x "$PI_BIN"
            echo "✓ Installed Zeus pi wrapper at $PI_BIN"
        fi
    fi
fi

# 4. Patch kitty.conf (idempotent)
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

# 5. Sway config (just show instructions)
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

# 6. Verify
echo "── Status ──"
if command -v zeus &>/dev/null; then
    echo "✓ zeus is in PATH"
else
    echo "⚠ zeus not in PATH — make sure $BIN_DIR is in your PATH"
fi

if command -v zeus-msg &>/dev/null; then
    echo "✓ zeus-msg is in PATH"
else
    echo "⚠ zeus-msg not in PATH"
fi

if command -v zeus-launch &>/dev/null; then
    echo "✓ zeus-launch is in PATH"
else
    echo "⚠ zeus-launch not in PATH"
fi

if $WRAP_PI; then
    if [ -f "$BIN_DIR/pi" ] && grep -q "Zeus pi wrapper" "$BIN_DIR/pi" 2>/dev/null; then
        echo "✓ pi wrapper installed at $BIN_DIR/pi"
    else
        echo "⚠ pi wrapper requested but not installed"
    fi
else
    echo "⚠⚠⚠ NOTICE: pi wrapper was NOT installed."
    echo "⚠ To enable deterministic IDs for independent pi launches:"
    echo "⚠   bash install.sh --wrap-pi"
fi

echo ""
echo "⚠ Restart kitty for remote control to take effect."
echo "Done."
