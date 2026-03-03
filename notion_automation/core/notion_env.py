import os
from pathlib import Path


def _load_env_file(path: Path, override: bool = False) -> None:
    if not path.exists() or not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        value = value.strip().strip('"').strip("'")
        if not key or not value:
            continue
        if override or key not in os.environ:
            os.environ[key] = value


def get_notion_token() -> str:
    root = Path(__file__).resolve().parents[2]
    # Prefer file value over potentially stale system environment variables.
    _load_env_file(root / ".env.notion", override=True)
    _load_env_file(root / "notion_automation" / ".env.notion", override=True)

    token = os.getenv("NOTION_TOKEN", "").strip()
    if token:
        return token

    raise RuntimeError("NOTION_TOKEN is missing. Put it in .env.notion")
