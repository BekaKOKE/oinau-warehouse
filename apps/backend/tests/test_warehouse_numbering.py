"""Номер складского документа (без БД)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.modules.warehouse.service import build_document_number

MOMENT = datetime(2026, 10, 13, 10, 0, tzinfo=UTC)


def test_number_has_prefix_year_and_padded_value() -> None:
    assert build_document_number(123, MOMENT) == "WH-2026-000123"


def test_first_number_is_padded_to_six_digits() -> None:
    assert build_document_number(1, MOMENT) == "WH-2026-000001"


def test_long_number_is_never_cut() -> None:
    assert build_document_number(1234567, MOMENT) == "WH-2026-1234567"


def test_year_after_almaty_midnight_is_the_new_year() -> None:
    # 20:00 UTC 31 декабря — уже 1 января в Алматы и при UTC+5, и при UTC+6
    moment = datetime(2026, 12, 31, 20, 0, tzinfo=UTC)
    assert build_document_number(42, moment) == "WH-2027-000042"


def test_year_before_almaty_midnight_is_the_old_year() -> None:
    # 17:00 UTC 31 декабря — ещё 31 декабря в Алматы и при UTC+5, и при UTC+6
    moment = datetime(2026, 12, 31, 17, 0, tzinfo=UTC)
    assert build_document_number(42, moment) == "WH-2026-000042"


@pytest.mark.parametrize("value", [0, -5])
def test_value_below_one_is_rejected(value: int) -> None:
    with pytest.raises(ValueError):
        build_document_number(value, MOMENT)


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError):
        build_document_number(1, datetime(2026, 10, 13, 10, 0))
