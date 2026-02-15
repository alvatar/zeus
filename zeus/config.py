"""Global configuration, constants, and compiled regexes."""

import re
from pathlib import Path

NAMES_FILE = Path("/tmp/zeus-names.json")
AGENT_IDS_FILE = Path("/tmp/zeus-agent-ids.json")
INPUT_HISTORY_DIR = Path("/tmp/zeus-input-history")
PRIORITIES_FILE = Path("/tmp/zeus-priorities.json")
PANEL_VISIBILITY_FILE = Path("/tmp/zeus-panel-visibility.json")
AGENT_NOTES_FILE = Path("/tmp/zeus-agent-notes.json")
AGENT_DEPENDENCIES_FILE = Path("/tmp/zeus-agent-dependencies.json")
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

