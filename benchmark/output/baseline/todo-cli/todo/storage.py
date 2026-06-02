from __future__ import annotations

import json
from pathlib import Path

from .models import Todo


class Storage:
    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    def load(self) -> list[Todo]:
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text())
        except json.JSONDecodeError as exc:
            raise ValueError(f"Todo file is corrupt: {self._path}") from exc
        return [Todo.from_dict(item) for item in raw]

    def save(self, todos: list[Todo]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps([t.to_dict() for t in todos], indent=2))
