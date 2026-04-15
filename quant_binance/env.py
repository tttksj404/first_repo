from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

_RUNTIME_OPTION_ENV_KEYS = (
    "UNIVERSE_SYMBOLS",
    "STRATEGY_PROFILE",
    "STRATEGY_OVERRIDE_PATH",
)
_INITIAL_RUNTIME_OPTION_ENV = {
    key: os.environ.get(key, "")
    for key in _RUNTIME_OPTION_ENV_KEYS
}


@dataclass(frozen=True)
class RuntimeReadiness:
    has_api_key: bool
    has_api_secret: bool

    @property
    def is_ready(self) -> bool:
        return self.has_api_key and self.has_api_secret


@dataclass(frozen=True)
class LoadedBinanceCredentials:
    api_key: str
    api_secret: str


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


def _resolve_env_value(name: str, *, allow_file_fallback: bool = True) -> str:
    direct = os.environ.get(name, "").strip()
    if direct:
        return direct
    if not allow_file_fallback:
        return ""
    repo_root = Path(__file__).resolve().parents[1]
    for candidate in (repo_root / ".env", repo_root / ".env.local"):
        file_values = _load_env_file(candidate)
        value = file_values.get(name, "").strip()
        if value:
            return value
    return ""


def _allow_file_runtime_overrides() -> bool:
    explicit = os.environ.get("QUANT_BINANCE_ALLOW_FILE_RUNTIME_OVERRIDES", "").strip().lower()
    if explicit:
        return explicit not in {"0", "false", "no", "off"}
    # Unit tests should be deterministic and must not inherit local runtime tuning
    # from repository .env files unless explicitly opted in.
    if "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules:
        return False
    return True


def _resolve_runtime_option_env_value(name: str) -> str:
    direct = os.environ.get(name, "").strip()
    if not direct:
        return ""
    if "PYTEST_CURRENT_TEST" not in os.environ and "pytest" not in sys.modules:
        return direct
    # Ignore ambient process-level runtime tuning during tests unless a test
    # explicitly changed the value after module import.
    initial = (_INITIAL_RUNTIME_OPTION_ENV.get(name) or "").strip()
    if direct == initial:
        return ""
    return direct


def resolve_universe_symbols(
    *,
    env_var: str = "UNIVERSE_SYMBOLS",
) -> tuple[str, ...]:
    raw = _resolve_runtime_option_env_value(env_var)
    if not raw and _allow_file_runtime_overrides():
        raw = _resolve_env_value(env_var, allow_file_fallback=True)
    if not raw:
        return ()
    symbols = []
    for item in raw.replace("\n", ",").split(","):
        symbol = item.strip().upper()
        if symbol:
            symbols.append(symbol)
    deduped: list[str] = []
    seen: set[str] = set()
    for symbol in symbols:
        if symbol not in seen:
            deduped.append(symbol)
            seen.add(symbol)
    return tuple(deduped)


def resolve_strategy_profile(
    *,
    env_var: str = "STRATEGY_PROFILE",
) -> str:
    raw = _resolve_runtime_option_env_value(env_var)
    if not raw and _allow_file_runtime_overrides():
        raw = _resolve_env_value(env_var, allow_file_fallback=True)
    return raw.strip().lower()


def resolve_strategy_override_path(
    *,
    env_var: str = "STRATEGY_OVERRIDE_PATH",
) -> str:
    raw = _resolve_runtime_option_env_value(env_var)
    if not raw and _allow_file_runtime_overrides():
        raw = _resolve_env_value(env_var, allow_file_fallback=True)
    return raw.strip()


def load_binance_credentials_from_env(
    *,
    api_key_var: str = "BINANCE_API_KEY",
    api_secret_var: str = "BINANCE_API_SECRET",
) -> LoadedBinanceCredentials:
    api_key = _resolve_env_value(api_key_var, allow_file_fallback=True)
    api_secret = _resolve_env_value(api_secret_var, allow_file_fallback=True)
    if not api_key or not api_secret:
        missing = [
            name
            for name, value in ((api_key_var, api_key), (api_secret_var, api_secret))
            if not value
        ]
        raise RuntimeError(f"missing required environment variables: {', '.join(missing)}")
    return LoadedBinanceCredentials(api_key=api_key, api_secret=api_secret)


def runtime_readiness(
    *,
    api_key_var: str = "BINANCE_API_KEY",
    api_secret_var: str = "BINANCE_API_SECRET",
) -> RuntimeReadiness:
    return RuntimeReadiness(
        has_api_key=bool(_resolve_env_value(api_key_var, allow_file_fallback=True)),
        has_api_secret=bool(_resolve_env_value(api_secret_var, allow_file_fallback=True)),
    )
