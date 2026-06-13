"""Unit tests for rulebook resolution (``rulebook/resolve.py``)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from rwa_calc.rulebook.model import LookupTable, ScalarParam
from rwa_calc.rulebook.resolve import resolve

# ---------------------------------------------------------------------------
# Scalar resolution + regime override
# ---------------------------------------------------------------------------


def test_crr_irb_scaling_factor() -> None:
    # Act / Assert — CRR keeps the 1.06 IRB scaling factor
    assert resolve("crr", date(2026, 1, 1)).scalar("irb_scaling_factor") == Decimal("1.06")


def test_b31_irb_scaling_factor_overrides_to_one() -> None:
    # Act / Assert — Basel 3.1 removes the scaling factor (overrides common/crr)
    assert resolve("b31", date(2027, 1, 1)).scalar("irb_scaling_factor") == Decimal("1.0")


def test_common_pack_entry_visible_in_regime() -> None:
    # Act / Assert — regime-invariant scalar from the common pack
    assert resolve("crr", date(2026, 1, 1)).scalar("fx_haircut") == Decimal("0.08")


# ---------------------------------------------------------------------------
# Feature + lookup + schedule accessors
# ---------------------------------------------------------------------------


def test_b31_feature_flag() -> None:
    # Act / Assert
    assert resolve("b31", date(2027, 1, 1)).feature("airb_lgd_floor") is True


def test_crr_lookup_table_accessor() -> None:
    # Act
    table = resolve("crr", date(2026, 1, 1)).lookup("corporate_cqs_rw")

    # Assert
    assert isinstance(table, LookupTable)
    assert table.entries[1] == Decimal("0.20")


@pytest.mark.parametrize(
    ("reporting_date", "expected"),
    [
        (date(2026, 6, 1), Decimal("0.0")),
        (date(2027, 1, 1), Decimal("0.60")),
        (date(2030, 1, 1), Decimal("0.725")),
    ],
)
def test_b31_schedule_value_resolves_at_reporting_date(
    reporting_date: date, expected: Decimal
) -> None:
    # Act / Assert
    assert resolve("b31", reporting_date).schedule_value("output_floor_pct") == expected


# ---------------------------------------------------------------------------
# Identity + accessor errors
# ---------------------------------------------------------------------------


def test_id_property() -> None:
    # Act / Assert
    assert resolve("b31", date(2027, 1, 1)).id == "b31@2027-01-01"


def test_missing_entry_raises_keyerror() -> None:
    # Act / Assert
    with pytest.raises(KeyError, match="no entry 'nope'"):
        resolve("crr", date(2026, 1, 1)).scalar("nope")


def test_wrong_shape_raises_typeerror() -> None:
    # Act / Assert — supporting_factors is a Feature, not a ScalarParam
    with pytest.raises(TypeError, match="expected ScalarParam"):
        resolve("crr", date(2026, 1, 1)).scalar("supporting_factors")


def test_unknown_regime_raises_valueerror() -> None:
    # Act / Assert
    with pytest.raises(ValueError, match="unknown regime_id 'xxx'"):
        resolve("xxx", date(2027, 1, 1))


# ---------------------------------------------------------------------------
# Content hash — determinism + regime distinctness
# ---------------------------------------------------------------------------


def test_content_hash_deterministic_across_calls() -> None:
    # Act
    first = resolve("b31", date(2027, 1, 1)).content_hash
    second = resolve("b31", date(2027, 1, 1)).content_hash

    # Assert
    assert first == second


def test_content_hash_differs_between_regimes() -> None:
    # Act
    crr_hash = resolve("crr", date(2027, 1, 1)).content_hash
    b31_hash = resolve("b31", date(2027, 1, 1)).content_hash

    # Assert
    assert crr_hash != b31_hash


def test_content_hash_differs_by_reporting_date() -> None:
    # Act / Assert — the reporting date is part of the canonical payload
    assert (
        resolve("b31", date(2027, 1, 1)).content_hash
        != resolve("b31", date(2028, 1, 1)).content_hash
    )


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def test_manifest_carries_identity_and_hash() -> None:
    # Arrange
    rulepack = resolve("b31", date(2027, 1, 1))

    # Act
    manifest = rulepack.as_manifest()

    # Assert
    assert manifest["id"] == "b31@2027-01-01"
    assert manifest["content_hash"] == rulepack.content_hash


def test_manifest_entries_sorted_with_citations() -> None:
    # Arrange
    manifest = resolve("crr", date(2026, 1, 1)).as_manifest()

    # Act
    entries = manifest["entries"]
    assert isinstance(entries, list)
    names = [entry["name"] for entry in entries]

    # Assert — sorted by name, each entry carries a citation string
    assert names == sorted(names)
    scaling = next(e for e in entries if e["name"] == "irb_scaling_factor")
    assert scaling["citation"] == "CRR Art. 153(1)"
    assert scaling["value"] == "1.06"


def test_scalarparam_round_trips_through_resolve() -> None:
    # Arrange — guards against a regime pack accidentally dropping its type
    entry = resolve("crr", date(2026, 1, 1)).entry("fx_haircut")

    # Assert
    assert isinstance(entry, ScalarParam)
    assert entry.value == Decimal("0.08")
