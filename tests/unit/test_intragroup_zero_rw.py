"""
Unit tests for the CRR Art. 113(6) core-UK-group 0% RW final override.

``apply_intragroup_zero_rw`` assigns the pack's cited 0% risk weight to
SA-routed rows whose own ``intragroup_zero_rw_eligible`` carrier is True, and
leaves every other row — ineligible, null-carrier, IRB-routed, or an exposure
giving rise to an own-funds item (proxied by ``seniority == "subordinated"``) —
untouched. The Feature (enabled under both regimes) gates the whole step.

References:
- CRR Art. 113(6) / PS1/26 Art. 113(6): core-UK-group 0% risk weight (individual
  basis), "With the exception of exposures giving rise to Common Equity Tier 1,
  Additional Tier 1 or Tier 2 items".
- docs/plans/multi-entity-reporting.md: Wave 4 design record.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType, ReportingBasis
from rwa_calc.engine.sa.rw_adjustments import apply_intragroup_zero_rw
from rwa_calc.rulebook import RulepackV0
from rwa_calc.rulebook.model import Citation, Feature


@pytest.fixture
def crr_config() -> CalculationConfig:
    """Scoped individual-basis config — the only run on which the override fires."""
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        reporting_entity="BANK_A",
        reporting_basis=ReportingBasis.INDIVIDUAL,
    )


@pytest.fixture
def b31_config() -> CalculationConfig:
    """Scoped individual-basis Basel 3.1 config (PS1/26 retains the permission)."""
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30),
        reporting_entity="BANK_A",
        reporting_basis=ReportingBasis.INDIVIDUAL,
    )


@pytest.fixture
def unscoped_config() -> CalculationConfig:
    """No reporting scope — the override must never fire (bypass closure)."""
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


def _pack(config: CalculationConfig):
    return RulepackV0.from_config(config).pack


def _frame(
    *,
    risk_weights: list[float],
    eligible: list[bool | None] | None = None,
    approach: list[str] | None = None,
    include_carrier: bool = True,
    seniority: list[str | None] | None = None,
) -> pl.LazyFrame:
    """Minimal SA frame with the risk_weight, carrier, seniority and approach columns.

    ``seniority`` is always present — every sealed edge reaching the SA
    calculator declares it (``HIERARCHY_RESOLVED_EDGE``), and the own-funds
    carve-out reads it.
    """
    n = len(risk_weights)
    data: dict[str, list[Any]] = {
        "exposure_reference": [f"EXP_{i:03d}" for i in range(n)],
        "risk_weight": risk_weights,
        "seniority": seniority if seniority is not None else ["senior"] * n,
    }
    if include_carrier:
        data["intragroup_zero_rw_eligible"] = eligible if eligible is not None else [False] * n
    if approach is not None:
        data["approach"] = approach
    return pl.DataFrame(data).lazy()


def _rws(lf: pl.LazyFrame) -> list[float]:
    return lf.collect()["risk_weight"].to_list()


def test_eligible_sa_row_gets_zero_risk_weight(crr_config: CalculationConfig):
    lf = _frame(
        risk_weights=[1.0, 1.0],
        eligible=[True, False],
        approach=[ApproachType.SA.value, ApproachType.SA.value],
    )

    out = apply_intragroup_zero_rw(lf, crr_config, pack=_pack(crr_config))

    # Eligible row -> 0%; ineligible row untouched.
    assert _rws(out) == [0.0, 1.0]


def test_null_carrier_is_treated_as_not_eligible(crr_config: CalculationConfig):
    lf = _frame(
        risk_weights=[1.0],
        eligible=[None],
        approach=[ApproachType.SA.value],
    )

    out = apply_intragroup_zero_rw(lf, crr_config, pack=_pack(crr_config))

    assert _rws(out) == [1.0]


def test_irb_row_is_untouched_even_when_carrier_true(crr_config: CalculationConfig):
    """IRB rows are out of scope — the SA-equivalent RW on the unified frame is preserved."""
    lf = _frame(
        risk_weights=[1.25, 1.0],
        eligible=[True, True],
        approach=[ApproachType.FIRB.value, ApproachType.SA.value],
    )

    out = apply_intragroup_zero_rw(lf, crr_config, pack=_pack(crr_config))

    # FIRB row keeps its RW; only the SA row is zeroed.
    assert _rws(out) == [1.25, 0.0]


def test_frame_without_approach_column_applies_to_eligible(crr_config: CalculationConfig):
    """calculate_branch pre-filters SA rows and may drop `approach` — still applies 0%."""
    lf = _frame(risk_weights=[1.0], eligible=[True], approach=None)

    out = apply_intragroup_zero_rw(lf, crr_config, pack=_pack(crr_config))

    assert _rws(out) == [0.0]


def test_no_op_when_carrier_column_absent(crr_config: CalculationConfig):
    lf = _frame(risk_weights=[0.5, 1.0], include_carrier=False)

    out = apply_intragroup_zero_rw(lf, crr_config, pack=_pack(crr_config))

    assert _rws(out) == [0.5, 1.0]


def test_no_op_when_feature_disabled(crr_config: CalculationConfig):
    """A pack with the Feature flipped off never zeroes an otherwise-eligible row."""
    disabled = _pack(crr_config).with_overrides(
        intragroup_zero_rw=Feature(
            name="intragroup_zero_rw",
            enabled=False,
            citation=Citation("CRR", "113", "disabled for test"),
        )
    )
    lf = _frame(
        risk_weights=[1.0],
        eligible=[True],
        approach=[ApproachType.SA.value],
    )

    out = apply_intragroup_zero_rw(lf, crr_config, pack=disabled)

    assert _rws(out) == [1.0]


def test_all_false_carrier_is_byte_identical_no_op(crr_config: CalculationConfig):
    """The unscoped shape (carrier all-False) leaves every risk weight unchanged."""
    lf = _frame(
        risk_weights=[0.2, 0.5, 1.5],
        eligible=[False, False, False],
        approach=[ApproachType.SA.value] * 3,
    )

    out = apply_intragroup_zero_rw(lf, crr_config, pack=_pack(crr_config))

    assert _rws(out) == [0.2, 0.5, 1.5]


def test_unscoped_run_never_applies_even_with_stray_true(unscoped_config: CalculationConfig):
    """Bypass closure: a user-loaded stray True on an UNSCOPED run must not zero the RW.

    ``intragroup_zero_rw_eligible`` is a declared schema column, so an input file
    could ship it True; on an unscoped run the scope resolver no-ops, so the
    override itself must refuse to fire without a scoped individual basis.
    """
    lf = _frame(
        risk_weights=[1.0],
        eligible=[True],
        approach=[ApproachType.SA.value],
    )

    out = apply_intragroup_zero_rw(lf, unscoped_config, pack=_pack(unscoped_config))

    assert _rws(out) == [1.0]


def test_consolidated_run_never_applies_even_with_stray_true():
    """A stray True on a consolidated-basis run must not zero the RW either."""
    consolidated = CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        reporting_entity="GRP",
        reporting_basis=ReportingBasis.CONSOLIDATED,
    )
    lf = _frame(
        risk_weights=[1.0],
        eligible=[True],
        approach=[ApproachType.SA.value],
    )

    out = apply_intragroup_zero_rw(lf, consolidated, pack=_pack(consolidated))

    assert _rws(out) == [1.0]


# ---------------------------------------------------------------------------
# The own-funds carve-out (P1.364): "With the exception of exposures giving rise
# to Common Equity Tier 1, Additional Tier 1 or Tier 2 items" — both regimes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("config_fixture", ["crr_config", "b31_config"])
def test_subordinated_row_keeps_its_risk_weight(
    config_fixture: str, request: pytest.FixtureRequest
):
    """A subordinated SA row is never zero-weighted, however its carrier is set.

    ``seniority == "subordinated"`` is the engine's (owner-approved, conservative)
    stand-in for "an exposure giving rise to a Tier 2 item": the 150% / class
    weight already assigned upstream must survive the override that runs last.
    """
    # Arrange
    config: CalculationConfig = request.getfixturevalue(config_fixture)
    lf = _frame(
        risk_weights=[1.5, 1.0],
        eligible=[True, True],
        approach=[ApproachType.SA.value, ApproachType.SA.value],
        seniority=["subordinated", "senior"],
    )

    # Act
    out = apply_intragroup_zero_rw(lf, config, pack=_pack(config))

    # Assert — the subordinated row keeps 150%; the senior control takes 0%
    assert _rws(out) == [1.5, 0.0]


def test_null_seniority_reads_as_senior(crr_config: CalculationConfig):
    """An unstated seniority is senior (the engine-wide convention) and stays eligible."""
    lf = _frame(
        risk_weights=[1.0],
        eligible=[True],
        approach=[ApproachType.SA.value],
        seniority=[None],
    )

    out = apply_intragroup_zero_rw(lf, crr_config, pack=_pack(crr_config))

    assert _rws(out) == [0.0]
