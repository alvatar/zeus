# ⚡ Zeus

TUI dashboard to monitor and manage multiple [pi](https://github.com/mariozechner/pi-coding-agent) coding Hippeis running in [kitty](https://sw.kovidgoyal.net/kitty/) terminal windows on Linux (sway WM).


## Features

- **Live dashboard** — see all tracked Hippeis at a glance: state (working/idle), model, context %, token count, sway workspace, working directory
- **State detection** — reads kitty terminal content to detect pi's spinner (working) or its absence (idle)
- **Usage tracking** — shows Anthropic API usage (session/week/extra) with color-coded progress bars
- **Sway integration** — jump to any Hippeus workspace with Enter, see which monitor/workspace each Hippeus is on
- **Notifications** — `notify-send` alert when a Hippeus transitions from working → idle
- **Aegis automation** — optional per-Hippeus nudge flow (`a`) after `WORKING -> IDLE/WAITING` transitions
- **Deterministic tmux ownership** — sessions are matched by `ZEUS_AGENT_ID` / `@zeus_owner` first, with cwd/screen-text fallback for legacy sessions
- **Hippeus launcher** — `$mod+Return` opens a bemenu prompt: name it to track, or leave empty for a regular terminal
- **Autonomous queue CLI** — `zeus-msg send` lets Polemarch/Hoplite sessions enqueue filesystem-backed messages without Oracle mediation

## Terminology

- **Zeus** — the program itself.
- **The Oracle** — the human operator and final authority.
- **Hippeus / Hippeis** — singular/plural term for tracked workers.
- **Polemarch** — parent/commander role for Phalanx orchestration.
- **Phalanx / Phalanges** — singular/plural term for a Polemarch-led worker group.
- **Hoplite / Hoplites** — AGENT-based subordinate agents initialized by a Polemarch and associated with that Polemarch’s Phalanx; not full Hippeis unless promoted.
- **tmux session** — generic viewer row/session; not a Hoplite and not a Phalanx member.

Canonical naming rules live in `docs/specs/terminology.md`.

Filesystem messaging flow and delivery guarantees are documented in `docs/guides/filesystem-messaging.md`.

## Requirements

- Linux with [sway](https://swaywm.org/) window manager
- [kitty](https://sw.kovidgoyal.net/kitty/) terminal (with remote control enabled)
- Python 3.11+ with [textual](https://textual.textualize.io/) (`pip install textual`)
- [pi coding agent](https://github.com/mariozechner/pi-coding-agent) with the `usage-bars` extension
- [bemenu](https://github.com/Cloudef/bemenu) (for the launcher prompt)
- `inotifywait` from `inotify-tools` (for filesystem message-queue wakeups)
- `tcp_diag` kernel module (for per-process network I/O tracking)

### Kernel module setup

Zeus uses the `tcp_diag` kernel module for accurate per-process network bandwidth
tracking via netlink `SOCK_DIAG`. Without it, the Net column will be blank.

Load it now and enable it on boot:

```bash
sudo modprobe tcp_diag
echo tcp_diag | sudo tee /etc/modules-load.d/tcp_diag.conf
```

## Install

```bash
git clone https://github.com/alvatar/zeus.git
cd zeus
bash install.sh
```

⚠ **NOTICE:** `bash install.sh` alone does **not** install the `pi` wrapper.

Optional (recommended): install a managed `pi` wrapper for deterministic `ZEUS_AGENT_ID` on independent launches:

```bash
bash install.sh --wrap-pi
```

With `--wrap-pi`, the wrapper runs `pi` inside a `bwrap` sandbox by default.
Writable paths are controlled via `~/.config/zeus/sandbox-paths.conf` (auto-created with defaults on first install):

```text
~/code
/tmp
```

Allowlist note: `sandbox-paths.conf` is the writable allowlist for user paths. Each absolute path listed there (after `~` expansion) is mounted read-write if it exists; non-existent paths are skipped with a warning on stderr. The wrapper also keeps a minimal fixed writable set for operation (`~/.pi`, `~/.local/bin`, `~/.local/lib/node_modules`, `~/.npm`, `~/.cargo`, `~/.rustup`, `~/.codex`, `~/.claude`), and exports npm defaults so global installs target user paths (`NPM_CONFIG_PREFIX=~/.local`, `NPM_CONFIG_CACHE=~/.npm`).

To disable sandboxing in the generated wrapper:

```bash
bash install.sh --wrap-pi --no-bwrap
```

The installer:
1. Copies `zeus` and `zeus-launch` to `~/.local/bin/`
2. (Optional `--wrap-pi`) wraps `~/.local/bin/pi` and stores backup at `~/.local/bin/pi.zeus-orig`
3. (Optional sandbox mode) seeds `~/.config/zeus/sandbox-paths.conf` if missing
4. Patches `~/.config/kitty/kitty.conf` to enable remote control
5. Prints instructions for the sway keybinding

After installing, add this to `~/.config/sway/config`:
```
bindsym $mod+Return exec PATH="$HOME/.local/bin:$PATH" zeus-launch
```
Then reload sway (`swaymsg reload`) and restart kitty.

### pi system-prompt appendix copy

To use the Zeus system-prompt appendix in pi, copy this repo file into the pi agent path:

```bash
mkdir -p ~/.pi/agent
cp "$PWD/prompts/APPEND_SYSTEM.md" ~/.pi/agent/APPEND_SYSTEM.md
```

Run the command from the Zeus repo root (where `prompts/APPEND_SYSTEM.md` exists).

## Security model

Zeus uses a **layered model**:

1. **OS-level isolation (enforced)** via `bwrap` in the generated `pi` wrapper.
2. **Agent policy constraints (prompt-level)** via `APPEND_SYSTEM.md`.

The first layer is the hard boundary; the second layer is defense-in-depth.

### 1) OS-level isolation (`bwrap` wrapper)

Enabled when installed with `bash install.sh --wrap-pi` (unless disabled with `--no-bwrap`, or per-run `--no-sandbox`).

Sandbox behavior is **deny-by-default**:
- Zeus creates a dedicated mount namespace for each wrapped `pi` run.
- Only explicitly allowed writable roots are exposed (user-configured paths plus a minimal runtime set required for operation).
- System/runtime dependencies are mounted read-only.
- Home is hardened; sensitive locations (e.g. SSH key material) are not mounted by default.

Git-over-SSH is supported via ssh-agent socket passthrough and wrapper-provided SSH environment, so authentication can work without exposing private key files inside the sandbox.

Implementation details are intentionally centralized in the generated wrapper logic in `install.sh`.

### 2) Prompt-level policy (`APPEND_SYSTEM.md`)

The appended system prompt defines operational rules (path approvals, messaging protocol, sandbox-escape command handling, etc.).
This complements the OS sandbox but does not replace it.

### Escape hatches (explicit)

- Disable sandbox generation in wrapper:
  - `bash install.sh --wrap-pi --no-bwrap`
- Bypass sandbox for one run:
  - `pi --no-sandbox ...`

Use these only when strictly necessary.

## Usage

```bash
# Launch the dashboard
zeus

# CLI commands
zeus ls                              # List tracked Hippeis
zeus new -n "fix-auth" -d ~/project  # Launch a new tracked Hippeus
zeus focus fix-auth                  # Focus a Hippeus window
zeus kill fix-auth                   # Close a Hippeus window
```

### Dashboard keybindings

Use in-app Help (`H`) for the current keybinding list and modal-specific shortcuts.

### Sway launcher (`zeus-launch`)

Bound to `$mod+Return`. Opens a bemenu prompt:
- **Type a name** → launches a tracked Hippeus kitty window (visible in the zeus dashboard)
- **Press Enter empty** → launches a normal untracked kitty

### Independent `pi` windows

Zeus still tracks independently started `pi` windows via cmdline/title heuristics.
For tmux ownership, deterministic matching is ID-first (`@zeus_owner` / `ZEUS_AGENT_ID`) with heuristic fallback.
When Zeus gets a high-confidence match for an unstamped session, it backfills `@zeus_owner` automatically.

If you want independent launches to carry IDs from the start, run `bash install.sh --wrap-pi` (installer-managed wrapper) or provide your own wrapper that exports `ZEUS_AGENT_ID` when missing before `exec`ing the real pi binary.
See `docs/tmux-ownership.md` for full details.

## Development

```bash
# Dev install (symlinks — changes take effect immediately)
bash install.sh --dev

# Run all checks (mypy + pytest)
bash check.sh

# Or individually:
mypy zeus/                    # Type checking
python3 -m pytest tests/ -v  # Tests
```

## How it works

1. **Kitty remote control** — each kitty instance creates a Unix socket at `/tmp/kitty-{pid}`, enabling `kitty @ ls` and `kitty @ get-text` queries
2. **Hippeus discovery** — Zeus scans `/tmp/kitty-*` sockets and identifies windows via `ZEUS_AGENT_NAME` or pi heuristics (cmdline/title)
3. **Hippeus identity** — each tracked window carries a `ZEUS_AGENT_ID` (or gets one persisted in `/tmp/zeus-agent-ids.json`)
4. **tmux ownership** — sessions match by `@zeus_owner` first, then `ZEUS_AGENT_ID` from tmux session env, then cwd/screen heuristics; high-confidence matches are backfilled into `@zeus_owner`
5. **State detection** — `kitty @ get-text` captures terminal content; pi's braille spinner characters (`⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`) indicate WORKING, absence indicates IDLE
6. **Footer parsing** — extracts model name, context %, and token count from pi's usage-bars extension output
7. **Usage data** — reads `/tmp/claude-usage-cache.json` (written by pi's usage-bars extension) for session/week/extra API usage
8. **Sway mapping** — `swaymsg -t get_tree` maps kitty PIDs to workspaces; `swaymsg [pid=N] focus` switches to a Hippeus window

## Configuration

| Environment variable | Default | Description |
|---------------------|---------|-------------|
| `ZEUS_POLL` | `2` | Dashboard poll interval in seconds |

## Color scheme

Dark background with cyan (`#00d7d7`) accent — designed to match a sway setup with similar border colors. Usage bars shift to orange at 80% and red at 90%.

## Uninstall

```bash
bash uninstall.sh
```

If the installer-managed pi wrapper was enabled, uninstall restores `~/.local/bin/pi` from `~/.local/bin/pi.zeus-orig`.

## License

MIT
