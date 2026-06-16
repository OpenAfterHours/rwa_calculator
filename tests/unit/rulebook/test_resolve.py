"""Unit tests for rulebook resolution (``rulebook/resolve.py``)."""

from __future__ import annotations

import dataclasses
from datetime import date
from decimal import Decimal

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from rwa_calc.engine.crm.haircut_tables import get_haircut_table
from rwa_calc.rulebook.compile import decision_table_df
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


def test_fcsm_floors_resolve_from_common_pack() -> None:
    # Arrange
    pack = resolve("crr", date(2026, 1, 1))
    # Act / Assert — the five Art. 222 FCSM scalars pinned to their canonical
    # values (the former data/tables/crr_simple_method constants, now deleted).
    assert pack.scalar("fcsm_rw_floor") == Decimal("0.20")
    assert pack.scalar("fcsm_sovereign_bond_discount") == Decimal("0.20")
    assert pack.scalar("fcsm_sft_cmp_floor") == Decimal("0.00")
    assert pack.scalar("fcsm_sft_non_cmp_floor") == Decimal("0.10")
    assert pack.scalar("fcsm_equity_collateral_rw") == Decimal("1.00")


def test_fcsm_floors_regime_invariant() -> None:
    # Act / Assert — Art. 222 is retained unchanged under Basel 3.1 (common pack)
    crr = resolve("crr", date(2026, 1, 1))
    b31 = resolve("b31", date(2027, 1, 1))
    assert crr.scalar("fcsm_rw_floor") == b31.scalar("fcsm_rw_floor") == Decimal("0.20")


def test_scalar_param_returns_typed_entry() -> None:
    # Act — the entry-returning accessor (sibling of ``scalar``)
    entry = resolve("crr", date(2026, 1, 1)).scalar_param("fcsm_rw_floor")
    # Assert
    assert isinstance(entry, ScalarParam)
    assert entry.value == Decimal("0.20")
    assert entry.name == "fcsm_rw_floor"


def test_overcollateralisation_ratios_resolve_byte_identical() -> None:
    # Act / Assert — the common-pack lookup reproduces the canonical floats
    # (literal pin of the former data/tables OVERCOLLATERALISATION_RATIOS).
    expected = {
        "financial": 1.0,
        "receivables": 1.25,
        "real_estate": 1.40,
        "other_physical": 1.40,
        "life_insurance": 1.0,
    }
    entries = resolve("crr", date(2026, 1, 1)).lookup("overcollateralisation_ratios").entries
    for category, ratio in expected.items():
        assert float(entries[category]) == ratio


def test_min_collateralisation_thresholds_resolve_byte_identical() -> None:
    # Act / Assert — literal pin of the former data/tables
    # MIN_COLLATERALISATION_THRESHOLDS.
    expected = {
        "financial": 0.0,
        "receivables": 0.0,
        "real_estate": 0.30,
        "other_physical": 0.30,
        "life_insurance": 0.0,
    }
    entries = resolve("crr", date(2026, 1, 1)).lookup("min_collateralisation_thresholds").entries
    for category, threshold in expected.items():
        assert float(entries[category]) == threshold


def test_firb_collateral_step_features_are_regime_specific() -> None:
    # Act
    crr = resolve("crr", date(2026, 1, 1))
    b31 = resolve("b31", date(2027, 1, 1))
    # Assert — CRR applies the Art. 230 divisor + 30% gate; Basel 3.1 removes both
    assert crr.feature("firb_overcollateralisation_divisor_applies") is True
    assert crr.feature("firb_min_collateralisation_threshold_applies") is True
    assert b31.feature("firb_overcollateralisation_divisor_applies") is False
    assert b31.feature("firb_min_collateralisation_threshold_applies") is False


@pytest.mark.parametrize(
    ("regime_id", "reporting_date", "is_basel_3_1"),
    [("crr", date(2026, 1, 1), False), ("b31", date(2027, 1, 1), True)],
)
def test_collateral_haircuts_render_byte_identical(
    regime_id: str, reporting_date: date, is_basel_3_1: bool
) -> None:
    # Arrange
    pack = resolve(regime_id, reporting_date)

    # Act — render the pack DecisionTable to the engine join schema
    rendered = decision_table_df(
        pack.decision("collateral_haircuts"),
        value_name="haircut",
        key_dtypes={"cqs": pl.Int8},
    )

    # Assert — frame-equal to the data/tables view the engine joins against.
    # Row/column order is not load-bearing for the keyed left join in
    # engine/crm/haircuts.py, so the comparison is order-insensitive.
    assert_frame_equal(
        rendered,
        get_haircut_table(is_basel_3_1=is_basel_3_1),
        check_column_order=False,
        check_row_order=False,
    )


def test_restructuring_exclusion_haircut_resolves_byte_identical() -> None:
    # Act / Assert — regime-invariant CDS restructuring-exclusion haircut
    crr = resolve("crr", date(2026, 1, 1)).scalar("restructuring_exclusion_haircut")
    b31 = resolve("b31", date(2027, 1, 1)).scalar("restructuring_exclusion_haircut")
    assert crr == b31 == Decimal("0.40")


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


# ---------------------------------------------------------------------------
# with_overrides — entry substitution for overlays / tests
# ---------------------------------------------------------------------------


def test_with_overrides_replaces_entry_value() -> None:
    # Arrange
    base = resolve("crr", date(2026, 1, 1))
    bumped = dataclasses.replace(base.scalar_param("fx_haircut"), value=Decimal("0.20"))

    # Act
    overridden = base.with_overrides(fx_haircut=bumped)

    # Assert
    assert overridden.scalar("fx_haircut") == Decimal("0.20")


def test_with_overrides_recomputes_content_hash() -> None:
    # Arrange
    base = resolve("crr", date(2026, 1, 1))
    bumped = dataclasses.replace(base.scalar_param("fx_haircut"), value=Decimal("0.20"))

    # Act / Assert — overridden pack never carries the pre-override digest
    assert base.with_overrides(fx_haircut=bumped).content_hash != base.content_hash


def test_with_overrides_leaves_base_pack_untouched() -> None:
    # Arrange
    base = resolve("crr", date(2026, 1, 1))
    bumped = dataclasses.replace(base.scalar_param("fx_haircut"), value=Decimal("0.20"))

    # Act
    base.with_overrides(fx_haircut=bumped)

    # Assert — the source pack is immutable
    assert base.scalar("fx_haircut") == Decimal("0.08")
