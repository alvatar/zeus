"""Static checks for installer-generated pi wrapper behavior."""

from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (_ROOT / path).read_text()


def test_install_parser_supports_no_bwrap_flag() -> None:
    text = _read("install.sh")

    assert "--no-bwrap" in text
    assert "NO_BWRAP=true" in text
    assert "Usage: $0 [--dev|-d] [--wrap-pi] [--no-bwrap]" in text


def test_install_seeds_sandbox_config_with_defaults() -> None:
    text = _read("install.sh")

    assert "sandbox-paths.conf" in text
    assert "Writable paths for pi sandbox" in text
    assert "Each absolute path listed here is mounted read-write if it exists." in text
    assert "Non-existent paths are skipped with a warning on stderr." in text
    assert "~/code" in text
    assert "/tmp" in text


def test_install_deploys_zeus_pi_extension_bundle() -> None:
    text = _read("install.sh")

    assert 'ZEUS_PI_EXTENSION_SRC="$SCRIPT_DIR/pi_extensions/zeus.ts"' in text
    assert 'ZEUS_PI_EXTENSION_DIR="${HOME}/.pi/agent/extensions"' in text
    assert 'ZEUS_PI_EXTENSION_DEST="${ZEUS_PI_EXTENSION_DIR}/zeus.ts"' in text
    assert 'ln -sf "$ZEUS_PI_EXTENSION_SRC" "$ZEUS_PI_EXTENSION_DEST"' in text
    assert 'cp "$ZEUS_PI_EXTENSION_SRC" "$ZEUS_PI_EXTENSION_DEST"' in text


def test_generated_wrapper_uses_bwrap_and_supports_no_sandbox_flag() -> None:
    text = _read("install.sh")

    assert "--no-sandbox" in text
    assert 'if ! command -v bwrap >/dev/null 2>&1; then' in text
    assert "exec bwrap \\" in text
    assert "--die-with-parent" in text
    assert "--proc /proc" in text
    assert "--dev /dev" in text


def test_wrapper_install_writes_via_temp_file_then_moves_into_place() -> None:
    text = _read("install.sh")

    assert 'PI_WRAP_TMP="${PI_BIN}.zeus-wrap.tmp.$$"' in text
    assert 'cat > "$PI_WRAP_TMP" <<EOF' in text
    assert 'mv -f "$PI_WRAP_TMP" "$PI_BIN"' in text
    assert 'cat > "$PI_BIN" <<EOF' not in text


def test_generated_wrapper_mounts_run_and_sets_git_ssh_env() -> None:
    text = _read("install.sh")

    assert "for p in /usr /lib /lib64 /bin /sbin /etc /run; do" in text
    assert (
        '--setenv GIT_SSH_COMMAND "ssh -F /dev/null -o StrictHostKeyChecking=no"'
        in text
    )
    assert (
        '--setenv SSH_AUTH_SOCK "\\${SSH_AUTH_SOCK:-/run/user/\\$(id -u)/ssh-agent.socket}"'
        in text
    )


def test_generated_wrapper_sets_npm_prefix_and_cache_to_user_paths() -> None:
    text = _read("install.sh")

    assert 'NPM_CONFIG_PREFIX:=\\${HOME}/.local' in text
    assert 'export npm_config_prefix="\\$NPM_CONFIG_PREFIX"' in text
    assert 'NPM_CONFIG_CACHE:=\\${HOME}/.npm' in text
    assert 'export npm_config_cache="\\$NPM_CONFIG_CACHE"' in text


def test_generated_wrapper_mounts_required_pi_rw_paths() -> None:
    text = _read("install.sh")

    assert 'bwrap_bind "\\${HOME}/.pi"' in text
    assert 'bwrap_bind "\\${HOME}/.pi/agent/sessions"' not in text
    assert 'bwrap_bind "\\${HOME}/.pi/agent/auth.json"' not in text
    assert 'bwrap_bind "\\${HOME}/.pi/agent/mcp-cache.json"' not in text
    assert 'bwrap_bind "\\${HOME}/.pi/agent/mcp-npx-cache.json"' not in text
    assert 'bwrap_bind "\\${HOME}/.local/bin"' in text
    assert 'bwrap_bind "\\${HOME}/.local/lib/node_modules"' in text
    assert 'bwrap_bind "\\${HOME}/.npm"' in text
    assert 'bwrap_bind "\\${HOME}/.cargo"' in text
    assert 'bwrap_bind "\\${HOME}/.rustup"' in text
    assert 'bwrap_bind "\\${HOME}/.codex"' in text
    assert 'bwrap_bind "\\${HOME}/.claude"' in text


def test_generated_wrapper_precreates_cargo_rustup_codex_and_claude_dirs() -> None:
    text = _read("install.sh")

    assert '"\\${HOME}/.cargo"' in text
    assert '"\\${HOME}/.rustup"' in text
    assert '"\\${HOME}/.codex"' in text
    assert '"\\${HOME}/.claude"' in text


def test_generated_wrapper_uses_sandbox_config_as_rw_allowlist() -> None:
    text = _read("install.sh")

    assert "is_allowed_rw_path" not in text
    assert '# User writable paths from sandbox-paths.conf allowlist.' in text
    assert 'if [ ! -e "\\$expanded" ]; then' in text
    assert (
        'echo "Zeus pi wrapper warning: sandbox path does not exist, skipping: \\$expanded" >&2'
        in text
    )
    assert 'bwrap_bind "\\${HOME}/code"' not in text
    assert 'bwrap_bind "/tmp"' not in text
    assert 'BWRAP_ARGS+=("--chmod" "0111" "\\${HOME}")' in text


def test_generated_wrapper_avoids_broad_home_mounts() -> None:
    text = _read("install.sh")

    assert 'bwrap_ro "\\${HOME}/.config"' not in text
    assert 'bwrap_ro "\\${HOME}/.npm"' not in text


def test_uninstall_removes_zeus_pi_extension_bundle() -> None:
    text = _read("uninstall.sh")

    assert 'PI_EXTENSION_FILE="${HOME}/.pi/agent/extensions/zeus.ts"' in text
    assert "Removed Zeus pi extension" in text


def test_uninstall_preserves_sandbox_config_notice() -> None:
    text = _read("uninstall.sh")

    assert "sandbox config is preserved" in text
