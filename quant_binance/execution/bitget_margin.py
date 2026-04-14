from __future__ import annotations

import os
from pathlib import Path

_VALID_BITGET_MARGIN_MODES = {"crossed", "isolated"}
_DEFAULT_BITGET_MARGIN_MODE = "crossed"


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists() or not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _resolve_env_value(name: str) -> str:
    direct = os.environ.get(name, "").strip()
    if direct:
        return direct
    repo_root = Path(__file__).resolve().parents[2]
    for candidate in (repo_root / ".env", repo_root / ".env.local"):
        file_values = _load_env_file(candidate)
        value = file_values.get(name, "").strip()
        if value:
            return value
    return ""


def resolve_bitget_margin_mode() -> str:
    raw = _resolve_env_value("BITGET_MARGIN_MODE").strip().lower()
    if not raw:
        return _DEFAULT_BITGET_MARGIN_MODE
    if raw in _VALID_BITGET_MARGIN_MODES:
        return raw
    return _DEFAULT_BITGET_MARGIN_MODE
