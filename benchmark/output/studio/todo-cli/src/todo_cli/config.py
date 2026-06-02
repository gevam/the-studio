import os
from pathlib import Path


def get_data_path() -> Path:
    env = os.environ.get("TODO_FILE")
    if env:
        return Path(env)
    return Path.home() / ".todos.json"
