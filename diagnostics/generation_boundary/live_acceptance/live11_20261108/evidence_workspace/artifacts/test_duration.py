"""Tests for duration parsing (REQ-003)."""

import pytest

from src.duration import parse_duration


@pytest.mark.parametrize(
    "value, expected",
    [
        ("1h30m", 5400),
        ("2m 15s", 135),
        ("45s", 45),
        ("1h 30m 15s", 5415),
    ],
)
def test_parse_duration_valid(value: str, expected: int) -> None:
    assert parse_duration(value) == expected


def test_parse_duration_returns_int() -> None:
    result = parse_duration("45s")
    assert isinstance(result, int)


def test_duplicate_units_raise_value_error() -> None:
    with pytest.raises(ValueError):
        parse_duration("1h1h")


def test_unknown_unit_raises_value_error() -> None:
    with pytest.raises(ValueError):
        parse_duration("1d")


def test_empty_string_raises_value_error() -> None:
    with pytest.raises(ValueError):
        parse_duration("")


def test_missing_number_raises_value_error() -> None:
    with pytest.raises(ValueError):
        parse_duration("h")


def test_negative_value_raises_value_error() -> None:
    with pytest.raises(ValueError):
        parse_duration("-1h")


@pytest.mark.parametrize("value", [None, 123, 45.6, ["1h"], True])
def test_non_string_raises_type_error(value: object) -> None:
    with pytest.raises(TypeError):
        parse_duration(value)  # type: ignore[arg-type]