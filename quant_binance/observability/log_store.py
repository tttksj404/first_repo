from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


def _json_ready(value: Any) -> Any:
    if is_dataclass(value):
        return _json_ready(asdict(value))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


class JsonlLogStore:
    def __init__(self, root: str | Path, *, max_bytes_per_stream: int | None = None) -> None:
        self.root = Path(root)
        self.max_bytes_per_stream = max_bytes_per_stream
        self.root.mkdir(parents=True, exist_ok=True)

    def append(self, stream: str, payload: dict[str, Any]) -> Path:
        path = self.root / f"{stream}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_json_ready(payload), sort_keys=True) + "\n")
        self._compact_if_needed(path)
        return path

    def read(self, stream: str) -> list[dict[str, Any]]:
        path = self.root / f"{stream}.jsonl"
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
        return rows

    def _compact_if_needed(self, path: Path) -> None:
        if self.max_bytes_per_stream is None or self.max_bytes_per_stream <= 0:
            return
        if not path.exists() or path.stat().st_size <= self.max_bytes_per_stream:
            return
        keep_bytes = max(self.max_bytes_per_stream // 2, 4096)
        with path.open("rb") as handle:
            handle.seek(max(path.stat().st_size - keep_bytes, 0))
            chunk = handle.read()
        newline_index = chunk.find(b"\n")
        if newline_index != -1:
            chunk = chunk[newline_index + 1 :]
        path.write_bytes(chunk)
