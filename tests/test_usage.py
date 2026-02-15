"""Tests for usage tracking helpers."""

import json
import os
import time

from zeus.usage import (
    time_left,
    read_usage,
    read_openai_usage,
    fetch_claude_usage,
)
from zeus.models import UsageData, OpenAIUsageData


def test_time_left_duration_minutes():
    assert time_left("5m") == "5m"
    assert time_left("30m") == "30m"


def test_time_left_duration_hours():
    assert time_left("2h") == "2h00m"
    assert time_left("1h") == "1h00m"


def test_time_left_duration_days():
    assert time_left("24h") == "1d00h"
    assert time_left("111h") == "4d15h"


def test_time_left_duration_seconds():
    assert time_left("45s") == "45s"
    assert time_left("0s") == "now"


def test_time_left_duration_ms():
    assert time_left("500ms") == "now"  # 500ms rounds to 0s
    assert time_left("1500ms") == "2s"  # 1500ms rounds to 2s
    assert time_left("0ms") == "now"


def test_time_left_iso_future():
    from datetime import datetime, timezone, timedelta
    future = datetime.now(timezone.utc) + timedelta(hours=2, minutes=30)
    result = time_left(future.isoformat())
    assert "2h" in result


def test_time_left_iso_past():
    from datetime import datetime, timezone, timedelta
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    assert time_left(past.isoformat()) == "now"


def test_time_left_empty():
    assert time_left("") == ""
    assert time_left("   ") == ""


def test_read_usage_missing_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("zeus.usage.USAGE_CACHE", tmp_path / "missing.json")
    monkeypatch.setattr("zeus.usage._last_claude_fetch_attempt", 0.0)

    fetches: list[str] = []
    monkeypatch.setattr(
        "zeus.usage._spawn_claude_fetch",
        lambda: fetches.append("fetch"),
    )

    result = read_usage()

    assert isinstance(result, UsageData)
    assert result.available is False
    assert fetches == ["fetch"]


def test_read_usage_valid_cache(tmp_path, monkeypatch):
    cache = tmp_path / "claude.json"
    cache.write_text(json.dumps({
        "five_hour": {"utilization": 42.0, "resets_at": ""},
        "seven_day": {"utilization": 10.0, "resets_at": ""},
        "extra_usage": {"utilization": 5.0, "used_credits": 100, "monthly_limit": 5000},
    }))
    monkeypatch.setattr("zeus.usage.USAGE_CACHE", cache)
    monkeypatch.setattr("zeus.usage._last_claude_fetch_attempt", 0.0)

    fetches: list[str] = []
    monkeypatch.setattr(
        "zeus.usage._spawn_claude_fetch",
        lambda: fetches.append("fetch"),
    )

    result = read_usage()

    assert result.available is True
    assert result.session_pct == 42.0
    assert result.week_pct == 10.0
    assert fetches == []


def test_read_usage_missing_cache_is_throttled(tmp_path, monkeypatch):
    monkeypatch.setattr("zeus.usage.USAGE_CACHE", tmp_path / "missing.json")
    monkeypatch.setattr("zeus.usage._last_claude_fetch_attempt", 0.0)

    fetches: list[str] = []
    monkeypatch.setattr(
        "zeus.usage._spawn_claude_fetch",
        lambda: fetches.append("fetch"),
    )

    read_usage()
    read_usage()

    assert fetches == ["fetch"]


def test_read_usage_stale_cache_triggers_background_refresh(tmp_path, monkeypatch):
    cache = tmp_path / "claude.json"
    cache.write_text(json.dumps({
        "five_hour": {"utilization": 12.0, "resets_at": ""},
        "seven_day": {"utilization": 34.0, "resets_at": ""},
    }))
    old = time.time() - 120
    os.utime(cache, (old, old))

    monkeypatch.setattr("zeus.usage.USAGE_CACHE", cache)
    monkeypatch.setattr("zeus.usage._last_claude_fetch_attempt", 0.0)

    fetches: list[str] = []
    monkeypatch.setattr(
        "zeus.usage._spawn_claude_fetch",
        lambda: fetches.append("fetch"),
    )

    result = read_usage()

    assert result.available is True
    assert result.session_pct == 12.0
    assert result.week_pct == 34.0
    assert fetches == ["fetch"]


def test_fetch_claude_usage_writes_cache(tmp_path, monkeypatch):
    cache = tmp_path / "claude.json"
    monkeypatch.setattr("zeus.usage.USAGE_CACHE", cache)
    monkeypatch.setattr(
        "zeus.usage._load_claude_oauth_info",
        lambda: ("tok", False),
    )
    monkeypatch.setattr(
        "zeus.usage._fetch_claude_usage_once",
        lambda _token: (
            200,
            json.dumps(
                {
                    "five_hour": {"utilization": 11.0, "resets_at": ""},
                    "seven_day": {"utilization": 22.0, "resets_at": ""},
                }
            ),
        ),
    )

    fetch_claude_usage()

    payload = json.loads(cache.read_text())
    assert payload["five_hour"]["utilization"] == 11.0
    assert payload["seven_day"]["utilization"] == 22.0


def test_read_openai_usage_missing_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("zeus.usage.OPENAI_USAGE_CACHE", tmp_path / "missing.json")
    monkeypatch.setattr("zeus.usage._spawn_openai_fetch", lambda: None)
    monkeypatch.setattr("zeus.usage._last_openai_fetch_attempt", 0.0)
    result = read_openai_usage()
    assert isinstance(result, OpenAIUsageData)
    assert result.available is False


def test_read_openai_usage_valid_cache(tmp_path, monkeypatch):
    cache = tmp_path / "openai.json"
    cache.write_text(json.dumps({
        "requests_limit": 100,
        "requests_remaining": 60,
        "tokens_limit": 50000,
        "tokens_remaining": 30000,
        "requests_pct": 40.0,
        "tokens_pct": 40.0,
        "requests_resets_at": "",
        "tokens_resets_at": "",
        "timestamp": time.time(),
    }))
    monkeypatch.setattr("zeus.usage.OPENAI_USAGE_CACHE", cache)
    result = read_openai_usage()
    assert result.available is True
    assert result.requests_pct == 40.0
    assert result.tokens_pct == 40.0
