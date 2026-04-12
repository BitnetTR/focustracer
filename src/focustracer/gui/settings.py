"""FocusTracer GUI — persistent settings management."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_SETTINGS_DIR = Path.home() / ".focustracer"
_SETTINGS_FILE = _SETTINGS_DIR / "settings.json"

_DEFAULTS: dict[str, Any] = {
    "agent": "ollama",
    "model": "qwen2.5:3b",
    "ollama_url": "http://localhost:11434",
    "opencode_cmd": "opencode",
    "recent_projects": [],
}


def load_settings() -> dict[str, Any]:
    """Load settings from disk, filling in defaults for missing keys."""
    settings = dict(_DEFAULTS)
    if _SETTINGS_FILE.exists():
        try:
            data = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                settings.update(data)
        except Exception:
            pass
    return settings


def save_settings(updates: dict[str, Any]) -> dict[str, Any]:
    """Merge *updates* into stored settings and persist."""
    settings = load_settings()
    settings.update(updates)
    _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    _SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    return settings


def add_recent_project(path: str) -> None:
    settings = load_settings()
    recents: list[str] = settings.get("recent_projects", [])
    if path in recents:
        recents.remove(path)
    recents.insert(0, path)
    settings["recent_projects"] = recents[:10]
    save_settings(settings)
