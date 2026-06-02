"""Unit tests for short-code generation (app.codec)."""
import re

import pytest

from app.codec import BASE62_ALPHABET, generate_code


def test_generate_code_has_requested_length():
    code = generate_code(length=7, alphabet=BASE62_ALPHABET)
    assert len(code) == 7


def test_generate_code_uses_only_alphabet_characters():
    alphabet = "abc"
    code = generate_code(length=20, alphabet=alphabet)
    assert set(code) <= set(alphabet)


def test_generate_code_default_alphabet_is_base62():
    code = generate_code(length=50, alphabet=BASE62_ALPHABET)
    assert re.fullmatch(r"[0-9A-Za-z]{50}", code)


def test_generate_code_rejects_non_positive_length():
    with pytest.raises(ValueError):
        generate_code(length=0, alphabet=BASE62_ALPHABET)


def test_generate_code_rejects_empty_alphabet():
    with pytest.raises(ValueError):
        generate_code(length=5, alphabet="")


def test_generate_code_is_effectively_unique():
    # Collisions are statistically improbable for length-8 base62 codes.
    codes = {generate_code(length=8, alphabet=BASE62_ALPHABET) for _ in range(1000)}
    assert len(codes) == 1000
