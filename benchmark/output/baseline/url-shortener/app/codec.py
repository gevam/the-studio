"""Short-code generation.

Codes are drawn from a cryptographically-strong RNG so they are not
guessable or sequential. base62 keeps codes short and URL-safe.
"""
from __future__ import annotations

import secrets
import string

BASE62_ALPHABET = string.digits + string.ascii_uppercase + string.ascii_lowercase


def generate_code(length: int, alphabet: str = BASE62_ALPHABET) -> str:
    """Return a random code of ``length`` characters drawn from ``alphabet``.

    Raises:
        ValueError: if ``length`` is not positive or ``alphabet`` is empty.
    """
    if length <= 0:
        raise ValueError("length must be positive")
    if not alphabet:
        raise ValueError("alphabet must not be empty")
    return "".join(secrets.choice(alphabet) for _ in range(length))
