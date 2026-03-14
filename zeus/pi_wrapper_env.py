"""Resolve missing Pi provider auth env vars for the Zeus pi wrapper."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
import json
import os
from pathlib import Path
import pwd
import shlex
import subprocess

PI_PROVIDER_ENV_VARS: tuple[str, ...] = (
    "AI_GATEWAY_API_KEY",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_OAUTH_TOKEN",
    "AZURE_OPENAI_API_KEY",
    "CEREBRAS_API_KEY",
    "GEMINI_API_KEY",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GROQ_API_KEY",
    "HF_TOKEN",
    "KIMI_API_KEY",
    "MINIMAX_API_KEY",
    "MINIMAX_CN_API_KEY",
    "MISTRAL_API_KEY",
    "OPENCODE_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "XAI_API_KEY",
    "ZAI_API_KEY",
)

_OUTPUT_PREFIX = "__ZEUS_PI_WRAPPER_ENV__"
_DEFAULT_SHELL = "/bin/sh"


def resolve_user_shell(env: Mapping[str, str] | None = None) -> str:
    source = env if env is not None else os.environ

    try:
        passwd_shell = (pwd.getpwuid(os.getuid()).pw_shell or "").strip()
    except (KeyError, OSError):
        passwd_shell = ""
    if passwd_shell:
        path = Path(passwd_shell).expanduser()
        if path.is_absolute() and path.exists():
            return str(path)

    candidate = str(source.get("SHELL") or "").strip()
    if candidate:
        path = Path(candidate).expanduser()
        if path.is_absolute() and path.exists():
            return str(path)

    return _DEFAULT_SHELL


def shell_login_argv(command: str, *, env: Mapping[str, str] | None = None) -> list[str]:
    shell = resolve_user_shell(env)
    shell_name = Path(shell).name
    if shell_name == "fish":
        return [shell, "-i", "-l", "-c", command]
    return [shell, "-ilc", command]


def missing_provider_env_vars(env: Mapping[str, str] | None = None) -> list[str]:
    source = env if env is not None else os.environ
    return [key for key in PI_PROVIDER_ENV_VARS if not str(source.get(key) or "").strip()]


def _read_proc_environ(pid: int) -> dict[str, str]:
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return {}

    result: dict[str, str] = {}
    for item in raw.split(b"\0"):
        if not item or b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        result[key.decode("utf-8", "replace")] = value.decode("utf-8", "replace")
    return result


def _read_parent_pid(pid: int) -> int:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("PPid:"):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return 0
    return 0


def fetch_provider_env_from_process_tree(
    missing_keys: Iterable[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    start_pid: int | None = None,
    environ_reader: Callable[[int], Mapping[str, str]] = _read_proc_environ,
    parent_reader: Callable[[int], int] = _read_parent_pid,
) -> dict[str, str]:
    source = dict(env if env is not None else os.environ)
    pending = [key for key in (missing_keys if missing_keys is not None else missing_provider_env_vars(source))]
    if not pending:
        return {}

    result: dict[str, str] = {}
    pid = os.getppid() if start_pid is None else start_pid
    seen: set[int] = set()
    while pid > 1 and pid not in seen and pending:
        seen.add(pid)
        proc_env = environ_reader(pid)
        for key in list(pending):
            value = str(proc_env.get(key) or "").strip()
            if value:
                result[key] = value
                pending.remove(key)
        pid = parent_reader(pid)
    return result


def _dump_command(keys: Sequence[str]) -> str:
    encoded = json.dumps(list(keys))
    return f"""python3 - <<'PY'
import json
import os
keys = json.loads({encoded!r})
payload = {{k: os.environ[k] for k in keys if os.environ.get(k)}}
print({_OUTPUT_PREFIX!r} + json.dumps(payload, separators=(',', ':')))
PY"""


def fetch_provider_env_from_shell(
    missing_keys: Iterable[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    runner=subprocess.run,
) -> dict[str, str]:
    source = dict(env if env is not None else os.environ)
    keys = [key for key in (missing_keys if missing_keys is not None else missing_provider_env_vars(source))]
    if not keys:
        return {}

    argv = shell_login_argv(_dump_command(keys), env=source)
    resolved_shell = resolve_user_shell(source)
    child_env = source.copy()
    child_env["SHELL"] = resolved_shell
    child_env["ZEUS_PI_WRAPPER_ENV_SYNC"] = "1"
    try:
        result = runner(
            argv,
            capture_output=True,
            text=True,
            timeout=5,
            env=child_env,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return {}

    if result.returncode != 0:
        return {}

    for line in result.stdout.splitlines():
        if _OUTPUT_PREFIX not in line:
            continue
        payload = line.split(_OUTPUT_PREFIX, 1)[1].strip()
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        return {
            str(key): str(value)
            for key, value in parsed.items()
            if isinstance(key, str) and isinstance(value, str) and value
        }
    return {}


def shell_export_lines(env_updates: Mapping[str, str]) -> str:
    lines = [f"export {key}={shlex.quote(value)}" for key, value in sorted(env_updates.items())]
    return "\n".join(lines)


def main() -> int:
    updates = fetch_provider_env_from_process_tree()
    remaining = [key for key in missing_provider_env_vars() if key not in updates]
    if remaining:
        merged_env = dict(os.environ)
        merged_env.update(updates)
        updates.update(fetch_provider_env_from_shell(remaining, env=merged_env))
    output = shell_export_lines(updates)
    if output:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
