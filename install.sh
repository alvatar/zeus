#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
LIB_DIR="${HOME}/.local/lib"

DEV_MODE=false
WRAP_PI=false
NO_BWRAP=false

for arg in "$@"; do
    case "$arg" in
        --dev|-d)
            DEV_MODE=true
            ;;
        --wrap-pi)
            WRAP_PI=true
            ;;
        --no-bwrap)
            NO_BWRAP=true
            ;;
        *)
            echo "Unknown option: $arg" >&2
            echo "Usage: $0 [--dev|-d] [--wrap-pi] [--no-bwrap]" >&2
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
    if $NO_BWRAP; then
        echo "pi sandbox: disabled (--no-bwrap)"
    else
        echo "pi sandbox: bubblewrap (bwrap)"
    fi
else
    echo "pi wrapper: disabled"
    echo "⚠⚠⚠ NOTICE: pi wrapper is NOT installed in this run."
    echo "⚠ Independent pi launches won't get deterministic ZEUS_AGENT_ID by default."
    echo "⚠ Run with --wrap-pi to enable it."
    if $NO_BWRAP; then
        echo "⚠ --no-bwrap ignored because --wrap-pi is not enabled."
    fi
fi
echo ""

if $WRAP_PI && ! $NO_BWRAP && ! command -v bwrap &>/dev/null; then
    echo "⚠ bwrap (bubblewrap) not found. Sandbox will be disabled at runtime."
    echo "  Install: pacman -S bubblewrap (Arch) / apt install bubblewrap (Debian)"
    echo "  The wrapper will fall back to running pi without sandboxing."
    echo ""
fi

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

# 3. Install Zeus pi extension bundle (shared runtime sync hooks)
ZEUS_PI_EXTENSION_SRC="$SCRIPT_DIR/pi_extensions/zeus.ts"
ZEUS_PI_EXTENSION_DIR="${HOME}/.pi/agent/extensions"
ZEUS_PI_EXTENSION_DEST="${ZEUS_PI_EXTENSION_DIR}/zeus.ts"

if [ -f "$ZEUS_PI_EXTENSION_SRC" ]; then
    if mkdir -p "$ZEUS_PI_EXTENSION_DIR" 2>/dev/null; then
        if $DEV_MODE; then
            if ln -sf "$ZEUS_PI_EXTENSION_SRC" "$ZEUS_PI_EXTENSION_DEST" 2>/dev/null; then
                echo "✓ Symlinked Zeus pi extension: $ZEUS_PI_EXTENSION_DEST → $ZEUS_PI_EXTENSION_SRC"
            else
                echo "⚠ Could not install Zeus pi extension at $ZEUS_PI_EXTENSION_DEST (permission denied); skipped" >&2
            fi
        else
            if cp "$ZEUS_PI_EXTENSION_SRC" "$ZEUS_PI_EXTENSION_DEST" 2>/dev/null; then
                echo "✓ Installed Zeus pi extension at $ZEUS_PI_EXTENSION_DEST"
            else
                echo "⚠ Could not install Zeus pi extension at $ZEUS_PI_EXTENSION_DEST (permission denied); skipped" >&2
            fi
        fi
    else
        echo "⚠ Could not create $ZEUS_PI_EXTENSION_DIR (permission denied); skipped" >&2
    fi
else
    echo "⚠ Zeus pi extension source missing: $ZEUS_PI_EXTENSION_SRC" >&2
fi

# 4. Optional pi wrapper (deterministic identity + optional bwrap sandbox)
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
            WRAPPER_BWRAP_ENABLED=1
            if $NO_BWRAP; then
                WRAPPER_BWRAP_ENABLED=0
            fi

            if [ "$WRAPPER_BWRAP_ENABLED" = "1" ]; then
                ZEUS_HOME_DIR="${HOME}/.zeus"
                SANDBOX_CONF="${ZEUS_HOME_DIR}/sandbox-paths.conf"
                if mkdir -p "$ZEUS_HOME_DIR" 2>/dev/null; then
                    if [ ! -f "$SANDBOX_CONF" ]; then
                        cat > "$SANDBOX_CONF" <<'SCONF'
# Writable paths for pi sandbox, one per line.
# ~ is expanded to $HOME. Lines starting with # are ignored.
# Each absolute path listed here is mounted read-write if it exists.
# Non-existent paths are skipped with a warning on stderr.
~/code
/tmp
SCONF
                        echo "✓ Created default sandbox config: $SANDBOX_CONF"
                    else
                        echo "✓ Sandbox config already exists: $SANDBOX_CONF (preserved)"
                    fi
                else
                    echo "⚠ Could not create $ZEUS_HOME_DIR; skipping sandbox config seed" >&2
                fi
            fi

            PI_WRAP_TMP="${PI_BIN}.zeus-wrap.tmp.$$"
            cat > "$PI_WRAP_TMP" <<EOF
#!/bin/bash
# --- Zeus pi wrapper ---
set -euo pipefail

PI_REAL="$PI_ORIG"
WRAPPER_BWRAP_ENABLED="$WRAPPER_BWRAP_ENABLED"
SANDBOX_CONF="\${HOME}/.zeus/sandbox-paths.conf"

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

: "\${NPM_CONFIG_PREFIX:=\${HOME}/.local}"
export NPM_CONFIG_PREFIX
export npm_config_prefix="\$NPM_CONFIG_PREFIX"

: "\${NPM_CONFIG_CACHE:=\${HOME}/.npm}"
export NPM_CONFIG_CACHE
export npm_config_cache="\$NPM_CONFIG_CACHE"

tmux set -ga update-environment ZEUS_AGENT_ID >/dev/null 2>&1 || true
tmux set -ga update-environment ZEUS_ROLE >/dev/null 2>&1 || true

if [ ! -e "\$PI_REAL" ] && [ ! -L "\$PI_REAL" ]; then
    echo "Zeus pi wrapper error: original pi not found at \$PI_REAL" >&2
    exit 1
fi

PASSTHROUGH_ARGS=()
NO_SANDBOX=false
for arg in "\$@"; do
    if [ "\$arg" = "--no-sandbox" ]; then
        NO_SANDBOX=true
    else
        PASSTHROUGH_ARGS+=("\$arg")
    fi
done

if \$NO_SANDBOX; then
    exec "\$PI_REAL" "\${PASSTHROUGH_ARGS[@]}"
fi

if [ "\$WRAPPER_BWRAP_ENABLED" != "1" ]; then
    exec "\$PI_REAL" "\${PASSTHROUGH_ARGS[@]}"
fi

if ! command -v bwrap >/dev/null 2>&1; then
    echo "Zeus pi wrapper warning: bwrap not found; running without sandbox" >&2
    exec "\$PI_REAL" "\${PASSTHROUGH_ARGS[@]}"
fi

PI_AGENT_DIR="\${HOME}/.pi/agent"
mkdir -p "\$PI_AGENT_DIR/sessions" \
         "\${HOME}/.npm" \
         "\${HOME}/.local/bin" \
         "\${HOME}/.local/lib/node_modules" \
         "\${HOME}/.cargo" \
         "\${HOME}/.rustup" \
         "\${HOME}/.codex" \
         "\${HOME}/.claude"
for zeus_path in "\${HOME}/.zeus" "\${HOME}/.zeus/messages" "\${HOME}/.zeus/session-map"; do
    mkdir -p "\$zeus_path" 2>/dev/null || true
done
touch "\$PI_AGENT_DIR/auth.json" \
      "\$PI_AGENT_DIR/mcp-cache.json" \
      "\$PI_AGENT_DIR/mcp-npx-cache.json"

BWRAP_ARGS=()
MOUNT_DIRS=()

bwrap_bind() {
    local path="\$1"
    [ -e "\$path" ] || return 0
    BWRAP_ARGS+=("--bind" "\$path" "\$path")
    if [ -d "\$path" ]; then
        MOUNT_DIRS+=("\$path")
    fi
}

bwrap_ro() {
    local path="\$1"
    [ -e "\$path" ] || return 0
    BWRAP_ARGS+=("--ro-bind" "\$path" "\$path")
    if [ -d "\$path" ]; then
        MOUNT_DIRS+=("\$path")
    fi
}

path_is_mounted_dir() {
    local target="\$1"
    for dir in "\${MOUNT_DIRS[@]}"; do
        if [ "\$target" = "\$dir" ] || [[ "\$target" == "\$dir/"* ]]; then
            return 0
        fi
    done
    return 1
}

# Minimal sandbox skeleton under HOME (no broad home visibility).
for d in "\${HOME}" \
         "\${HOME}/code" \
         "\${HOME}/.zeus" \
         "\${HOME}/.zeus/messages" \
         "\${HOME}/.zeus/session-map" \
         "\${HOME}/.pi" \
         "\${HOME}/.pi/agent" \
         "\${HOME}/.pi/agent/sessions" \
         "\${HOME}/.local" \
         "\${HOME}/.local/bin" \
         "\${HOME}/.local/lib" \
         "\${HOME}/.local/lib/node_modules" \
         "\${HOME}/.npm" \
         "\${HOME}/.cargo" \
         "\${HOME}/.rustup" \
         "\${HOME}/.codex" \
         "\${HOME}/.claude"; do
    BWRAP_ARGS+=("--dir" "\$d")
done

# Core system mounts (read-only)
for p in /usr /lib /lib64 /bin /sbin /etc /run; do
    bwrap_ro "\$p"
done

# Pi/runtime support (read-write, fixed)
bwrap_bind "\${HOME}/.zeus"
bwrap_bind "\${HOME}/.pi"
bwrap_bind "\${HOME}/.local/bin"
bwrap_bind "\${HOME}/.local/lib/node_modules"
bwrap_bind "\${HOME}/.npm"
bwrap_bind "\${HOME}/.cargo"
bwrap_bind "\${HOME}/.rustup"
bwrap_bind "\${HOME}/.codex"
bwrap_bind "\${HOME}/.claude"
bwrap_ro "\${HOME}/.gitconfig"

# User writable paths from sandbox-paths.conf allowlist.
if [ -f "\$SANDBOX_CONF" ]; then
    while IFS= read -r line; do
        line="\${line%%#*}"
        line="\$(echo "\$line" | xargs)"
        [ -z "\$line" ] && continue

        expanded="\${line/#\~/\$HOME}"
        if [[ "\$expanded" != /* ]]; then
            continue
        fi
        if [ ! -e "\$expanded" ]; then
            echo "Zeus pi wrapper warning: sandbox path does not exist, skipping: \$expanded" >&2
            continue
        fi
        bwrap_bind "\$expanded"
    done < "\$SANDBOX_CONF"
fi

# Hard-deny home-root reads/writes; only explicit submounts remain usable.
BWRAP_ARGS+=("--chmod" "0111" "\${HOME}")

BWRAP_CHDIR="/"
if path_is_mounted_dir "\$PWD"; then
    BWRAP_CHDIR="\$PWD"
elif path_is_mounted_dir "/tmp"; then
    BWRAP_CHDIR="/tmp"
fi

exec bwrap \
    --die-with-parent \
    --proc /proc \
    --dev /dev \
    --setenv GIT_SSH_COMMAND "ssh -F /dev/null -o StrictHostKeyChecking=no" \
    --setenv SSH_AUTH_SOCK "\${SSH_AUTH_SOCK:-/run/user/\$(id -u)/ssh-agent.socket}" \
    --chdir "\$BWRAP_CHDIR" \
    "\${BWRAP_ARGS[@]}" \
    "\$PI_REAL" "\${PASSTHROUGH_ARGS[@]}"
EOF
            chmod +x "$PI_WRAP_TMP"
            mv -f "$PI_WRAP_TMP" "$PI_BIN"
            echo "✓ Installed Zeus pi wrapper at $PI_BIN"
        fi
    fi
fi

# 5. Patch kitty.conf (idempotent)
KITTY_CONF="${HOME}/.config/kitty/kitty.conf"
KITTY_CONF_DIR="$(dirname "$KITTY_CONF")"
if mkdir -p "$KITTY_CONF_DIR" 2>/dev/null; then
    if [ -f "$KITTY_CONF" ]; then
        if grep -q "Zeus agent monitor" "$KITTY_CONF" 2>/dev/null; then
            echo "✓ kitty.conf already patched"
        else
            if {
                echo "" >> "$KITTY_CONF"
                cat "$SCRIPT_DIR/config/kitty.conf.snippet" >> "$KITTY_CONF"
            } 2>/dev/null; then
                echo "✓ Patched $KITTY_CONF"
            else
                echo "⚠ Could not patch $KITTY_CONF (permission denied); skipped" >&2
            fi
        fi
    else
        if cat "$SCRIPT_DIR/config/kitty.conf.snippet" > "$KITTY_CONF" 2>/dev/null; then
            echo "✓ Created $KITTY_CONF"
        else
            echo "⚠ Could not create $KITTY_CONF (permission denied); skipped" >&2
        fi
    fi
else
    echo "⚠ Could not create $KITTY_CONF_DIR (permission denied); skipped" >&2
fi

# 6. Sway config (just show instructions)
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

# 7. Verify
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
        if $NO_BWRAP; then
            echo "⚠ pi wrapper sandbox disabled (--no-bwrap)"
        elif command -v bwrap &>/dev/null; then
            echo "✓ bwrap detected: sandbox enabled for wrapped pi runs"
        else
            echo "⚠ bwrap missing: wrapped pi will run unsandboxed until installed"
        fi
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
