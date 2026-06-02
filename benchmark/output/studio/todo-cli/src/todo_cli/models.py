from dataclasses import dataclass


@dataclass
class Todo:
    id: str
    title: str
    completed: bool
    created_at: str
