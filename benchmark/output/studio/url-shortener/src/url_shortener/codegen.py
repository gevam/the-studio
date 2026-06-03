"""Short-code generation (CodeGenerator injection point, design v3 ShortenService).

Random base62 codes per the threat model (random, not sequential, to resist
code enumeration). Kept as a Protocol + one implementation so the encoding
strategy is an injectable seam.
"""

from __future__ import annotations

import secrets
from typing import Protocol

_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_DEFAULT_LENGTH = 7


class CodeGenerator(Protocol):
    def generate(self) -> str: ...


class RandomBase62Generator:
    """Generates random base62 codes (default 7 chars, per design)."""

    def __init__(self, length: int = _DEFAULT_LENGTH) -> None:
        self._length = length

    def generate(self) -> str:
        return "".join(secrets.choice(_ALPHABET) for _ in range(self._length))
