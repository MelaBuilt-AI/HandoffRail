"""HandoffRail CLI — Config file support (~/.handoffrail.toml).

Provides ``load_config`` to read TOML config for server URL and API key.
Config file values are used as fallbacks when CLI flags and env vars are not set.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

CONFIG_PATH = Path.home() / ".handoffrail.toml"


def load_config() -> dict[str, str]:
    """Load configuration from ~/.handoffrail.toml.

    Returns a dict with keys ``server_url`` and ``api_key`` if present.
    Returns an empty dict if the file doesn't exist or can't be parsed.
    """
    if not CONFIG_PATH.exists():
        return {}

    try:
        with open(CONFIG_PATH, "rb") as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError):
        return {}

    hr_cfg = data.get("handoffrail", {})
    if not isinstance(hr_cfg, dict):
        return {}

    result: dict[str, str] = {}
    if "server_url" in hr_cfg:
        result["server_url"] = str(hr_cfg["server_url"])
    if "api_key" in hr_cfg:
        result["api_key"] = str(hr_cfg["api_key"])
    return result
