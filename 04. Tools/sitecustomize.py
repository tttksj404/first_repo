import os
from pathlib import Path


def _load_env_file(path: Path) -> None:
    if not path.exists() or not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def _bootstrap() -> None:
    root = Path(__file__).resolve().parent
    _load_env_file(root / ".env.notion")
    _load_env_file(root / "notion_automation" / ".env.notion")


_bootstrap()

