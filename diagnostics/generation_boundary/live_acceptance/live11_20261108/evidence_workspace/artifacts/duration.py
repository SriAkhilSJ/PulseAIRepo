"""Parse human-readable duration strings into total seconds."""

import re

_UNIT_SECONDS = {"h": 3600, "m": 60, "s": 1}

_TOKEN_RE = re.compile(r"(\d+)\s*([hms])")


def parse_duration(value: str) -> int:
    """Parse a duration string (e.g. '1h30m', '2m 15s') into total seconds.

    Supports units h, m, and s in any order with optional spaces between
    components. Raises ValueError for an empty string, unknown units,
    duplicate units, missing numbers, or negative values, and TypeError
    if value is not a string.
    """
    if not isinstance(value, str):
        raise TypeError("value must be a string")
    if not value.strip():
        raise ValueError("empty duration string")
    if "-" in value or "+" in value:
        raise ValueError("negative values are not allowed")

    total = 0
    seen = set()
    pos = 0

    for match in _TOKEN_RE.finditer(value):
        if value[pos:match.start()].strip():
            raise ValueError(f"invalid duration: {value!r}")
        number = int(match.group(1))
        unit = match.group(2)
        if unit in seen:
            raise ValueError(f"duplicate unit: {unit!r}")
        seen.add(unit)
        total += number * _UNIT_SECONDS[unit]
        pos = match.end()

    if value[pos:].strip():
        raise ValueError(f"invalid duration: {value!r}")

    return total