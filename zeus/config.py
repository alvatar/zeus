"""Global configuration, constants, and compiled regexes."""

import os
import re
from pathlib import Path

POLL_INTERVAL = float(os.environ.get("ZEUS_POLL", "2"))
NAMES_FILE = Path("/tmp/zeus-names.json")
USAGE_CACHE = Path("/tmp/claude-usage-cache.json")
OPENAI_USAGE_CACHE = Path("/tmp/openai-usage-cache.json")

# Pi spinner frames (from pi-tui Loader component)
SPINNER_RE = re.compile(r"[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]\s+\S")

# Footer parsing (from usage-bars.ts extension output)
MODEL_RE = re.compile(r"^(\S+)\s*(?:\((\w+)\))?")
CTX_RE = re.compile(r"Ctx\([^)]*\):[█░]+\((\d+\.?\d*)%\)")
TOKENS_RE = re.compile(r"↑([\d.]+[kM]?)\s+↓([\d.]+[kM]?)")

# Pi session storage
AGENT_SESSIONS_DIR = Path.home() / ".pi" / "agent" / "sessions"
