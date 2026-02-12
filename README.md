# ⚡ Zeus

TUI dashboard to monitor and manage multiple [pi](https://github.com/mariozechner/pi-coding-agent) coding agents running in [kitty](https://sw.kovidgoyal.net/kitty/) terminal windows on Linux (sway WM).


## Features

- **Live dashboard** — see all tracked agents at a glance: state (working/idle), model, context %, token count, sway workspace, working directory
- **State detection** — reads kitty terminal content to detect pi's spinner (working) or its absence (idle)
- **Usage tracking** — shows Anthropic API usage (session/week/extra) with color-coded progress bars
- **Sway integration** — jump to any agent's workspace with Enter, see which monitor/workspace each agent is on
- **Notifications** — `notify-send` alert when an agent transitions from working → idle
- **Agent launcher** — `$mod+Return` opens a bemenu prompt: name it to track, or leave empty for a regular terminal

## Requirements

- Linux with [sway](https://swaywm.org/) window manager
- [kitty](https://sw.kovidgoyal.net/kitty/) terminal (with remote control enabled)
- Python 3.11+ with [textual](https://textual.textualize.io/) (`pip install textual`)
- [pi coding agent](https://github.com/mariozechner/pi-coding-agent) with the `usage-bars` extension
- [bemenu](https://github.com/Cloudef/bemenu) (for the launcher prompt)

## Install

```bash
git clone https://github.com/alvatar/zeus.git
cd zeus
bash install.sh
```

The installer:
1. Copies `zeus` and `zeus-launch` to `~/.local/bin/`
2. Patches `~/.config/kitty/kitty.conf` to enable remote control
3. Prints instructions for the sway keybinding

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
| `Enter` | Focus selected agent (switches sway workspace) |
| `k` | Kill selected agent (with confirmation) |
| `n` | Launch new tracked agent |
| `q` / `Esc` | Quit dashboard |
| `r` | Force refresh |

### Sway launcher (`zeus-launch`)

Bound to `$mod+Return`. Opens a bemenu prompt:
- **Type a name** → launches a tracked kitty window (visible in the zeus dashboard)
- **Press Enter empty** → launches a normal untracked kitty

## How it works

1. **Kitty remote control** — each kitty instance creates a Unix socket at `/tmp/kitty-{pid}`, enabling `kitty @ ls` and `kitty @ get-text` queries
2. **Agent discovery** — Zeus scans `/tmp/kitty-*` sockets, queries each, and filters windows by the `AGENTMON_NAME` environment variable
3. **State detection** — `kitty @ get-text` captures terminal content; pi's braille spinner characters (`⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`) indicate WORKING, absence indicates IDLE
4. **Footer parsing** — extracts model name, context %, and token count from pi's usage-bars extension output
5. **Usage data** — reads `/tmp/claude-usage-cache.json` (written by pi's usage-bars extension) for session/week/extra API usage
6. **Sway mapping** — `swaymsg -t get_tree` maps kitty PIDs to workspaces; `swaymsg [pid=N] focus` switches to an agent's window

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

## License

MIT
