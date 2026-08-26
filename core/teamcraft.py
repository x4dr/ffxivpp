"""Parser for FFXIV Teamcraft list import strings.

Teamcraft (see https://wiki.ffxivteamcraft.com/dev-stuff) serialises a
crafting list as items separated by ``;``, where every item has the form::

    itemId,recipeId|null,quantity

* ``itemId`` -- the game item id, a non-negative integer;
* ``recipeId`` -- either the literal string ``null`` (the item is bought,
  gathered, or otherwise not crafted) or a numeric recipe id;
* ``quantity`` -- how many are needed, an integer >= 1.

Example plain form::

    10345,null,1;4879,12345,2

The whole string is usually standard base64 of the above plain form.
:func:`parse_import_string` accepts BOTH the raw semicolon form and its
base64 encoding; :func:`try_decode_base64` auto-detects base64 input
(base64 charset, successful decode, and the decoded text must itself parse
as an import string), tolerating missing ``=`` padding, and returns any
input that is not base64-of-a-valid-list unchanged so it can be parsed as
the raw form.
"""

import base64
import binascii
from dataclasses import dataclass

__all__ = ["TeamcraftEntry", "parse_import_string", "try_decode_base64"]

_DECIMAL_DIGITS = frozenset("0123456789")
_BASE64_ALPHABET = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
)


@dataclass(frozen=True)
class TeamcraftEntry:
    """A single item row of a Teamcraft import string."""

    item_id: int
    recipe_id: int | None
    quantity: int


def _is_decimal(text: str) -> bool:
    """Return True if *text* is a non-empty run of ASCII digits."""
    return bool(text) and all(char in _DECIMAL_DIGITS for char in text)


def _split_item_fields(item: str) -> tuple[str, str, str] | None:
    """Split one ``;``-separated item into its three stripped fields.

    Returns None when the item does not have exactly three comma-separated
    fields.
    """
    parts = item.split(",")
    if len(parts) != 3:
        return None
    return parts[0].strip(), parts[1].strip(), parts[2].strip()


def _fields_match_format(fields: tuple[str, str, str]) -> bool:
    """Return True if the raw fields look like ``itemId,recipeId|null,qty``."""
    item_text, recipe_text, quantity_text = fields
    if not _is_decimal(item_text) or not _is_decimal(quantity_text):
        return False
    return recipe_text == "null" or _is_decimal(recipe_text)


def _parses_as_import_string(text: str) -> bool:
    """Return True if *text* is a syntactically valid plain import string."""
    stripped = text.strip()
    if not stripped:
        return False
    items = stripped.split(";")
    if any(not item.strip() for item in items):
        return False
    split_items = (_split_item_fields(item) for item in items)
    return all(
        fields is not None and _fields_match_format(fields) for fields in split_items
    )


def try_decode_base64(raw: str) -> str:
    """Return the base64-decoded text if *raw* looks like base64 of a valid
    import string, otherwise return *raw* unchanged.

    Detection requires all three of: only base64-alphabet characters in the
    payload, a successful standard-base64 decode (missing ``=`` padding is
    tolerated), and decoded content that parses as an import string.  The
    last condition prevents false positives on raw import strings, whose
    ``,``/``;`` separators are never valid base64 payloads.
    """
    candidate = raw.strip()
    body = candidate.rstrip("=")
    if not body or any(char not in _BASE64_ALPHABET for char in body):
        return raw
    padded = body + "=" * (-len(body) % 4)
    try:
        decoded = base64.b64decode(padded, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return raw
    if not _parses_as_import_string(decoded):
        return raw
    return decoded


def _parse_count(text: str, label: str) -> int:
    """Parse a non-negative decimal integer field, raising ValueError."""
    stripped = text.strip()
    if stripped.startswith("-"):
        raise ValueError(f"{label} must not be negative, got {stripped!r}")
    unsigned = stripped.removeprefix("+")
    if not _is_decimal(unsigned):
        raise ValueError(f"{label} must be an integer, got {stripped!r}")
    return int(unsigned)


def _parse_item(chunk: str, position: int) -> TeamcraftEntry:
    """Parse one ``itemId,recipeId|null,quantity`` item."""
    label = f"Item {position}"
    fields = _split_item_fields(chunk)
    if fields is None:
        raise ValueError(
            f"{label}: expected 3 comma-separated fields "
            f"'itemId,recipeId|null,quantity', got {chunk!r}"
        )
    item_text, recipe_text, quantity_text = fields
    item_id = _parse_count(item_text, f"{label}: itemId")
    recipe_id: int | None = None
    if recipe_text != "null":
        recipe_id = _parse_count(recipe_text, f"{label}: recipeId")
    quantity = _parse_count(quantity_text, f"{label}: quantity")
    if quantity < 1:
        raise ValueError(f"{label}: quantity must be at least 1, got {quantity}")
    return TeamcraftEntry(item_id=item_id, recipe_id=recipe_id, quantity=quantity)


def parse_import_string(raw: str) -> list[TeamcraftEntry]:
    """Parse a Teamcraft import string into :class:`TeamcraftEntry` rows.

    *raw* may be the plain semicolon form or its standard base64 encoding
    (with or without padding); the two forms are auto-detected.

    Raises:
        ValueError: If the string is empty, is neither valid raw form nor
            base64 of a valid form, or contains malformed items (wrong
            field count, non-integer or negative ids, quantity below 1).
    """
    if not raw or not raw.strip():
        raise ValueError("Import string is empty.")
    text = try_decode_base64(raw).strip()
    entries: list[TeamcraftEntry] = []
    for position, chunk in enumerate(text.split(";"), start=1):
        if not chunk.strip():
            raise ValueError(f"Item {position} in import string is empty.")
        entries.append(_parse_item(chunk, position))
    return entries
