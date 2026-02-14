"""Typed settings loaded from TOML config with env-var overrides."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path


USER_CONFIG_PATH = Path.home() / ".config" / "zeus" / "config.toml"


def _load_default_toml() -> dict:
    """Load the built-in default_config.toml shipped with the package."""
    ref = resources.files("zeus").joinpath("default_config.toml")
    return tomllib.loads(ref.read_text(encoding="utf-8"))


def _load_user_toml() -> dict:
    """Load user config if it exists, otherwise empty dict."""
    if USER_CONFIG_PATH.is_file():
        return tomllib.loads(USER_CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base (override wins)."""
    merged = dict(base)
    for key, val in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(val, dict):
            merged[key] = _deep_merge(merged[key], val)
        else:
            merged[key] = val
    return merged


# ── Dataclasses ──────────────────────────────────────────────────────


@dataclass
class ColumnLayout:
    order: tuple[str, ...]
    widths: dict[str, int]


@dataclass
class ColumnsConfig:
    fixed: int
    split: ColumnLayout
    wide: ColumnLayout


@dataclass
class MinimapConfig:
    max_name_length: int
    max_sub_name_length: int


@dataclass
class SparklineConfig:
    width: int
    max_samples: int
    name_width: int


@dataclass
class Settings:
    poll_interval: float
    summary_model: str
    input_history_max: int
    columns: ColumnsConfig
    minimap: MinimapConfig
    sparkline: SparklineConfig

    # Raw merged dict kept for potential future use
    _raw: dict = field(default_factory=dict, repr=False)


def _parse_column_layout(data: dict) -> ColumnLayout:
    return ColumnLayout(
        order=tuple(data.get("order", [])),
        widths={k: int(v) for k, v in data.get("widths", {}).items()},
    )


def load_settings() -> Settings:
    """Load settings: defaults ← user TOML ← env vars."""
    defaults = _load_default_toml()
    user = _load_user_toml()
    raw = _deep_merge(defaults, user)

    dash = raw.get("dashboard", {})
    cols = raw.get("columns", {})
    mm = raw.get("minimap", {})

    poll = float(os.environ.get("ZEUS_POLL", dash.get("poll_interval", 2.0)))
    summary_model = os.environ.get(
        "ZEUS_SUMMARY_MODEL",
        dash.get("summary", {}).get("model", "anthropic/claude-3-5-haiku-latest"),
    )
    history_max = int(os.environ.get(
        "ZEUS_INPUT_HISTORY_MAX",
        dash.get("history", {}).get("max_entries", 10),
    ))

    columns = ColumnsConfig(
        fixed=int(cols.get("fixed", 2)),
        split=_parse_column_layout(cols.get("split", {})),
        wide=_parse_column_layout(cols.get("wide", {})),
    )

    minimap = MinimapConfig(
        max_name_length=int(mm.get("max_name_length", 10)),
        max_sub_name_length=int(mm.get("max_sub_name_length", 8)),
    )

    sp = raw.get("sparkline", {})
    sparkline = SparklineConfig(
        width=int(sp.get("width", 25)),
        max_samples=int(sp.get("max_samples", 120)),
        name_width=int(sp.get("name_width", 12)),
    )

    return Settings(
        poll_interval=poll,
        summary_model=summary_model,
        input_history_max=history_max,
        columns=columns,
        minimap=minimap,
        sparkline=sparkline,
        _raw=raw,
    )


# Module-level singleton — loaded once on import.
SETTINGS = load_settings()
