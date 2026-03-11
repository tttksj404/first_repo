from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


ExchangeId = Literal["bitget", "binance"]
DEFAULT_EXCHANGE: ExchangeId = "bitget"
SUPPORTED_EXCHANGES: tuple[ExchangeId, ...] = ("bitget", "binance")


@dataclass(frozen=True)
class ExchangeEnvSpec:
    exchange_id: ExchangeId
    api_key_var: str
    api_secret_var: str
    api_passphrase_var: str | None = None

    @property
    def required_env_vars(self) -> tuple[str, ...]:
        vars_required = [self.api_key_var, self.api_secret_var]
        if self.api_passphrase_var:
            vars_required.append(self.api_passphrase_var)
        return tuple(vars_required)


@dataclass(frozen=True)
class ExchangeRuntimeReadiness:
    exchange_id: ExchangeId
    has_api_key: bool
    has_api_secret: bool
    has_api_passphrase: bool
    required_env_vars: tuple[str, ...]
    requires_passphrase: bool

    @property
    def is_ready(self) -> bool:
        return self.has_api_key and self.has_api_secret and (self.has_api_passphrase or not self.requires_passphrase)


@dataclass(frozen=True)
class ExchangeCredentials:
    exchange_id: ExchangeId
    api_key: str
    api_secret: str
    api_passphrase: str = ""


ENV_SPECS: dict[ExchangeId, ExchangeEnvSpec] = {
    "bitget": ExchangeEnvSpec(
        exchange_id="bitget",
        api_key_var="BITGET_API_KEY",
        api_secret_var="BITGET_API_SECRET",
        api_passphrase_var="BITGET_API_PASSPHRASE",
    ),
    "binance": ExchangeEnvSpec(
        exchange_id="binance",
        api_key_var="BINANCE_API_KEY",
        api_secret_var="BINANCE_API_SECRET",
    ),
}


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
    repo_root = Path(__file__).resolve().parents[1]
    for candidate in (repo_root / ".env", repo_root / ".env.local"):
        file_values = _load_env_file(candidate)
        value = file_values.get(name, "").strip()
        if value:
            return value
    return ""


def resolve_exchange_id(exchange: str | None = None) -> ExchangeId:
    candidate = (exchange or _resolve_env_value("EXCHANGE") or DEFAULT_EXCHANGE).strip().lower()
    if candidate not in SUPPORTED_EXCHANGES:
        supported = ", ".join(SUPPORTED_EXCHANGES)
        raise RuntimeError(f"unsupported exchange '{candidate}'. supported exchanges: {supported}")
    return candidate  # type: ignore[return-value]


def runtime_readiness(exchange: str | None = None) -> ExchangeRuntimeReadiness:
    exchange_id = resolve_exchange_id(exchange)
    spec = ENV_SPECS[exchange_id]
    passphrase_required = spec.api_passphrase_var is not None
    passphrase_value = _resolve_env_value(spec.api_passphrase_var) if spec.api_passphrase_var else ""
    return ExchangeRuntimeReadiness(
        exchange_id=exchange_id,
        has_api_key=bool(_resolve_env_value(spec.api_key_var)),
        has_api_secret=bool(_resolve_env_value(spec.api_secret_var)),
        has_api_passphrase=bool(passphrase_value) if passphrase_required else True,
        required_env_vars=spec.required_env_vars,
        requires_passphrase=passphrase_required,
    )


def load_exchange_credentials_from_env(
    exchange: str | None = None,
    *,
    allow_missing: bool = False,
) -> ExchangeCredentials:
    exchange_id = resolve_exchange_id(exchange)
    spec = ENV_SPECS[exchange_id]
    api_key = _resolve_env_value(spec.api_key_var)
    api_secret = _resolve_env_value(spec.api_secret_var)
    api_passphrase = _resolve_env_value(spec.api_passphrase_var) if spec.api_passphrase_var else ""
    missing = [
        name
        for name, value in (
            (spec.api_key_var, api_key),
            (spec.api_secret_var, api_secret),
            (spec.api_passphrase_var or "", api_passphrase if spec.api_passphrase_var else "ok"),
        )
        if name and not value
    ]
    if missing and not allow_missing:
        raise RuntimeError(f"missing required environment variables: {', '.join(missing)}")
    return ExchangeCredentials(
        exchange_id=exchange_id,
        api_key=api_key,
        api_secret=api_secret,
        api_passphrase=api_passphrase,
    )
