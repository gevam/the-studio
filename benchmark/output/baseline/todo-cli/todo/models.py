from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TodoStatus(str, Enum):
    PENDING = "pending"
    DONE = "done"


@dataclass
class Todo:
    id: int
    text: str
    status: TodoStatus = field(default=TodoStatus.PENDING)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Todo):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    def to_dict(self) -> dict:
        return {"id": self.id, "text": self.text, "status": self.status.value}

    @classmethod
    def from_dict(cls, data: dict) -> Todo:
        try:
            status = TodoStatus(data["status"])
        except ValueError:
            raise ValueError(f"Invalid status: {data['status']!r}")
        return cls(id=data["id"], text=data["text"], status=status)
