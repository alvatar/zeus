"""Desktop notifications."""

import subprocess


def notify(title: str, body: str, urgency: str = "normal"):
    try:
        subprocess.run(
            ["notify-send", f"--urgency={urgency}",
             "--app-name=zeus", "-i", "utilities-terminal",
             title, body],
            capture_output=True, timeout=5)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
