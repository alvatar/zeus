# Zeus Refactoring Plan

## Completed

### Phase 1–3: Package structure ✅
Refactored from single 2240-line `bin/zeus` into:

```
zeus/
├── bin/zeus                  # Thin entry point (sys.path, imports zeus.main)
├── zeus/
│   ├── __init__.py
│   ├── main.py               # CLI argument parsing, main()
│   ├── models.py             # Dataclasses: State, TmuxSession, ProcessMetrics, AgentWindow, UsageData, OpenAIUsageData
│   ├── config.py             # Constants, regexes, paths
│   ├── process.py            # Process metrics (/proc, nvidia-smi)
│   ├── sessions.py           # Claude session forking/detection
│   ├── kitty.py              # Kitty remote control, agent discovery
│   ├── sway.py               # Sway workspace helpers
│   ├── tmux.py               # Tmux discovery & agent matching
│   ├── state.py              # State detection & footer parsing
│   ├── usage.py              # Claude & OpenAI usage tracking
│   ├── notify.py             # Desktop notifications
│   ├── commands.py           # CLI subcommands (new, ls, focus, kill)
│   └── dashboard/
│       ├── __init__.py
│       ├── app.py            # ZeusApp class
│       ├── widgets.py        # UsageBar, ZeusDataTable
│       ├── css.py            # All CSS strings
│       └── screens.py        # Modal screens
├── tests/                    # 46 tests, all passing
│   ├── test_config.py
│   ├── test_models.py
│   ├── test_process.py
│   ├── test_state.py
│   ├── test_usage.py
│   ├── test_tmux.py
│   └── test_sessions.py
├── install.sh                # --dev for symlinks, default copies package
└── TODO.md
```

### Phase 4: Tests ✅
- 41 tests covering: config regexes, models, _fmt_bytes, state detection,
  footer parsing, time_left, usage cache reading, tmux matching, session encoding

### Install modes ✅
- `install.sh` — copies bin/zeus + zeus/ package to ~/.local/{bin,lib}
- `install.sh --dev` — symlinks bin/zeus (auto-detects repo ../zeus/)

## Future ideas
- [ ] Textual snapshot tests for dashboard rendering
- [ ] `pyproject.toml` for pip-installable package
- [ ] Async subprocess calls in dashboard for lower latency
