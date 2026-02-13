# ⚡ Zeus

TUI dashboard to monitor and manage multiple [pi](https://github.com/mariozechner/pi-coding-agent) coding agents running in [kitty](https://sw.kovidgoyal.net/kitty/) terminal windows on Linux (sway WM).


## Features

- **Live dashboard** — see all tracked agents at a glance: state (working/idle), model, context %, token count, sway workspace, working directory
- **State detection** — reads kitty terminal content to detect pi's spinner (working) or its absence (idle)
- **Usage tracking** — shows Anthropic API usage (session/week/extra) with color-coded progress bars
- **Sway integration** — jump to any agent's workspace with Enter, see which monitor/workspace each agent is on
- **Notifications** — `notify-send` alert when an agent transitions from working → idle
- **Deterministic tmux ownership** — sessions are matched by `ZEUS_AGENT_ID` / `@zeus_owner` first, with cwd/screen-text fallback for legacy sessions
- **Agent launcher** — `$mod+Return` opens a bemenu prompt: name it to track, or leave empty for a regular terminal

## Requirements

- Linux with [sway](https://swaywm.org/) window manager
- [kitty](https://sw.kovidgoyal.net/kitty/) terminal (with remote control enabled)
- Python 3.11+ with [textual](https://textual.textualize.io/) (`pip install textual`)
- [pi coding agent](https://github.com/mariozechner/pi-coding-agent) with the `usage-bars` extension
- [bemenu](https://github.com/Cloudef/bemenu) (for the launcher prompt)
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

The installer:
1. Copies `zeus` and `zeus-launch` to `~/.local/bin/`
2. (Optional `--wrap-pi`) wraps `~/.local/bin/pi` and stores backup at `~/.local/bin/pi.zeus-orig`
3. Patches `~/.config/kitty/kitty.conf` to enable remote control
4. Prints instructions for the sway keybinding

After installing, add this to `~/.config/sway/config`:
```
bindsym $mod+Return exec PATH="$HOME/.local/bin:$PATH" zeus-launch
```
Then reload sway (`swaymsg reload`) and restart kitty.

## Usage

```bash
# Launch the dashboard
zeus

# CLI commands
zeus ls                              # List tracked agents
zeus new -n "fix-auth" -d ~/project  # Launch a new tracked agent
zeus focus fix-auth                  # Focus an agent's window
zeus kill fix-auth                   # Close an agent's window
```

### Dashboard keybindings

| Key | Action |
|-----|--------|
| `↑` `↓` | Navigate agents |
| `Enter` | Focus interact input |
| `Esc` | Return focus to agent table |
| `Ctrl+Enter` | Teleport to selected agent / open tmux client |
| `Ctrl+S` | Send interact input |
| `Ctrl+W` | Queue interact input (Alt+Enter in pi) |
| `Ctrl+Y` | Paste clipboard text; if image, save temp file and insert path |
| `q` | Stop selected agent (send ESC) |
| `Ctrl+Q` | Stop selected agent from any focus (including input) |
| `k` | Kill selected agent / tmux session (with confirmation) |
| `n` | Launch new tracked agent |
| `r` | Rename selected agent / tmux session |
| `F4` | Toggle sort |
| `F5` | Force refresh |
| `F6` | Toggle split layout |
| `F7` | Toggle AI summaries |
| `F8` | Toggle interact panel |
| `F10` | Quit dashboard |

### Sway launcher (`zeus-launch`)

Bound to `$mod+Return`. Opens a bemenu prompt:
- **Type a name** → launches a tracked kitty window (visible in the zeus dashboard)
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
2. **Agent discovery** — Zeus scans `/tmp/kitty-*` sockets and identifies windows via `AGENTMON_NAME` or pi heuristics (cmdline/title)
3. **Agent identity** — each tracked window carries a `ZEUS_AGENT_ID` (or gets one persisted in `/tmp/zeus-agent-ids.json`)
4. **tmux ownership** — sessions match by `@zeus_owner` first, then `ZEUS_AGENT_ID` from tmux session env, then cwd/screen heuristics; high-confidence matches are backfilled into `@zeus_owner`
5. **State detection** — `kitty @ get-text` captures terminal content; pi's braille spinner characters (`⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`) indicate WORKING, absence indicates IDLE
6. **Footer parsing** — extracts model name, context %, and token count from pi's usage-bars extension output
7. **Usage data** — reads `/tmp/claude-usage-cache.json` (written by pi's usage-bars extension) for session/week/extra API usage
8. **Sway mapping** — `swaymsg -t get_tree` maps kitty PIDs to workspaces; `swaymsg [pid=N] focus` switches to an agent's window

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
