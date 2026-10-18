"""Login should be able to return to the trainer, but only on this site."""

from __future__ import annotations

import pytest

from app.auth import _safe_next


@pytest.mark.parametrize(
    "value,expected",
    [
        ("/trainer/", "/trainer/"),
        ("/trainer/train?x=1", "/trainer/train?x=1"),
        ("//evil.example/trainer", None),
        ("/\\evil.example", None),
        ("https://evil.example/trainer", None),
        ("trainer/", None),
        ("", None),
        (None, None),
    ],
)
def test_only_same_site_paths_survive(value: str | None, expected: str | None) -> None:
    assert _safe_next(value) == expected
