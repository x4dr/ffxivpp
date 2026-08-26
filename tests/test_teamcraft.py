"""Tests for core.teamcraft (Teamcraft import-string parsing)."""

import base64

import pytest

from core.teamcraft import TeamcraftEntry, parse_import_string, try_decode_base64


def _to_plain(entries: list[TeamcraftEntry]) -> str:
    parts: list[str] = []
    for entry in entries:
        recipe = "null" if entry.recipe_id is None else str(entry.recipe_id)
        parts.append(f"{entry.item_id},{recipe},{entry.quantity}")
    return ";".join(parts)


def _to_base64(entries: list[TeamcraftEntry]) -> str:
    return base64.b64encode(_to_plain(entries).encode("utf-8")).decode("ascii")


def test_round_trip_through_base64() -> None:
    entries = [
        TeamcraftEntry(item_id=10345, recipe_id=None, quantity=1),
        TeamcraftEntry(item_id=4879, recipe_id=12345, quantity=99),
        TeamcraftEntry(item_id=2, recipe_id=3, quantity=47),
    ]

    assert parse_import_string(_to_base64(entries)) == entries


def test_raw_semicolon_form_parses() -> None:
    raw = "10345,null,1;4879,12345,2"

    assert parse_import_string(raw) == [
        TeamcraftEntry(item_id=10345, recipe_id=None, quantity=1),
        TeamcraftEntry(item_id=4879, recipe_id=12345, quantity=2),
    ]


def test_mixed_recipe_ids_numeric_and_null() -> None:
    entries = parse_import_string("3603,null,5;1975,1088,1;42,9001,12")

    assert entries == [
        TeamcraftEntry(item_id=3603, recipe_id=None, quantity=5),
        TeamcraftEntry(item_id=1975, recipe_id=1088, quantity=1),
        TeamcraftEntry(item_id=42, recipe_id=9001, quantity=12),
    ]


def test_missing_base64_padding_accepted() -> None:
    padded = _to_base64([TeamcraftEntry(item_id=1234, recipe_id=None, quantity=2)])
    unpadded = padded.rstrip("=")
    assert unpadded != padded  # the fixture really lost its padding

    assert parse_import_string(unpadded) == [
        TeamcraftEntry(item_id=1234, recipe_id=None, quantity=2)
    ]


def test_try_decode_base64_returns_decoded_text_for_valid_payload() -> None:
    payload = "1234,null,2"

    assert try_decode_base64(_to_base64([TeamcraftEntry(1234, None, 2)])) == payload


def test_try_decode_base64_returns_raw_unchanged_for_non_base64() -> None:
    raw = "1234,null,2;987,654,1"

    assert try_decode_base64(raw) == raw


def test_detection_no_false_positive_on_base64_charset_raw() -> None:
    # Every payload character here (digits) is in the base64 alphabet; only
    # the structural ',' / ';' separators distinguish this from base64, so
    # detection must take the raw path and yield the exact entries.
    raw = "123456,789,1;246813,null,10"

    assert try_decode_base64(raw) == raw
    assert parse_import_string(raw) == [
        TeamcraftEntry(item_id=123456, recipe_id=789, quantity=1),
        TeamcraftEntry(item_id=246813, recipe_id=None, quantity=10),
    ]


def test_surrounding_whitespace_is_tolerated() -> None:
    assert parse_import_string("  1234,null,2  ") == [
        TeamcraftEntry(item_id=1234, recipe_id=None, quantity=2)
    ]


def test_garbage_after_decode_raises_value_error() -> None:
    encoded = base64.b64encode(b"this is not a teamcraft list").decode("ascii")

    with pytest.raises(ValueError, match="3 comma-separated"):
        parse_import_string(encoded)


@pytest.mark.parametrize(
    ("bad_input", "match"),
    [
        ("", "empty"),
        ("   ", "empty"),
        ("abc,null,1", "itemId"),
        ("1234,notanid,1", "recipeId"),
        ("1234,null,x", "quantity"),
        ("1234,null,-1", "negative"),
        ("1234,null,0", "at least 1"),
        ("1234,null", "3 comma-separated"),
        ("1234,null,1,2", "3 comma-separated"),
        ("1234,null,1;", "is empty"),
    ],
)
def test_invalid_inputs_raise_value_error(bad_input: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        parse_import_string(bad_input)
