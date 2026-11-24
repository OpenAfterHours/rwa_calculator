"""
P1.208 — the SA exposure value and the Art. 127 default test net SPECIFIC CRA only.

Rule text (read verbatim before this change):

- CRR Art. 111(1): "The exposure value of an asset item shall be its accounting
  value remaining after specific credit risk adjustments in accordance with
  Article 110 ... The exposure value of an off-balance sheet item listed in
  Annex I shall be the following percentage of its nominal value after
  reduction of specific credit risk adjustments".
  PS1/26 Art. 111(1)(a) / (b)(i) say the same ("after specific credit risk
  adjustments"; "its nominal value after reduction of specific credit risk
  adjustments").
- CRR Art. 110(1) / PS1/26 Art. 110(1): "An institution applying the
  Standardised Approach shall treat general credit risk adjustments in
  accordance with point (c) of ... Article 62" — Tier 2, not the exposure value.
- CRR Art. 127(1): 150% "where the sum of specific credit risk adjustments ...
  is less than 20 % of the unsecured part of the exposure value if those
  specific credit risk adjustments and deductions were not applied".
  PS1/26 Art. 127(1)(a): 150% "where the amount of specific credit risk
  adjustments ... is less than 20% of the outstanding amount of the item or
  facility".
- PS1/26 Art. 159(1) 'B' includes "(i) general credit risk adjustments" — so the
  IRB / slotting expected-loss comparison keeps the TOTAL (``provision_allocated``).

Before the fix ``engine/crm/provisions.py`` summed every provision row with no
``provision_type`` filter and deducted that total from SA drawn / nominal, and
``engine/sa/risk_weights.py`` used the same total as the Art. 127 numerator.

Hand calculations (large unrated GB corporate, SA, both regimes):

- Deduction: drawn 1,000,000; SCRA 20,000 + GCRA 10,000.
  provision_deducted = 20,000; ead_final = 980,000 (pre-fix 30,000 / 970,000).
- Off-balance-sheet limb (Art. 111(1) second sentence / PS1/26 (b)(i)): drawn
  10,000, nominal 100,000; SCRA 20,000 + GCRA 10,000. 10,000 on drawn, the
  remaining 10,000 specific on nominal -> nominal_after_provision 90,000
  (pre-fix 80,000). A contingent of nominal 100,000 at CCF 100% with the same
  provisions -> EAD 80,000 (pre-fix 70,000).
- Art. 127: defaulted, drawn 100,000; SCRA 15,000 + GCRA 10,000.
  ead_final = 100,000 - 15,000 = 85,000. Coverage 15,000 / 100,000 = 15% < 20%
  -> 150%; RWA = 127,500. Pre-fix: deducted 25,000, coverage 25% -> 100% on
  75,000 = 75,000 RWA.
- Allocation levels (general CRA are portfolio provisions, normally attached
  to a facility or counterparty). Counterparty CP1 with SA loans drawn
  600,000 / 400,000; SCRA 20,000 on L1 + GCRA 10,000 on CP1 -> deducted
  20,000 / 0, allocated 26,000 / 4,000, EAD 580,000 / 400,000 (pre-fix
  deducted 26,000 / 4,000). Facility F1 over L1 drawn 500,000 and an undrawn
  leg of 500,000 (MR, 50%), SCRA 30,000 + GCRA 20,000 on F1 -> deducted
  20,000 / 10,000, undrawn nominal 490,000 after (pre-fix 33,333.33 /
  16,666.67).
- Untyped provision (production injects a typed NULL ``provision_type`` when
  the column is omitted): counted as specific, the status quo. Drawn 1,000,000
  with 20,000 untyped -> deducted 20,000; defaulted drawn 100,000 with 25,000
  untyped -> 25% >= 20% -> 100% on 75,000.

The provision_type match is case-insensitive: the validator lower-cases
(``contracts/validation.py``) and the fixtures write ``SCRA`` / ``GCRA``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest
from tests.unit.crm import _pipeline_harness as harness

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType, PermissionMode
from rwa_calc.engine.crm.provisions import resolve_provisions

_REGIMES = ("crr", "b31")

#: Both ids take the DIRECT level only: ``beneficiary_type='loan'`` goes through
#: ``allocate_multi_level``'s direct join, the untyped frame through the
#: direct-only fallback. The facility and counterparty levels have their own
#: tests (``TestResolveProvisionsAllocationLevels``).
_DIRECT_JOIN_IDS = ["multi_level_direct_join", "fallback_direct_join"]


def _config(regime: str) -> CalculationConfig:
    reporting_date = harness.REPORTING_DATES[regime]
    if regime == "crr":
        return CalculationConfig.crr(
            reporting_date=reporting_date, permission_mode=PermissionMode.STANDARDISED
        )
    return CalculationConfig.basel_3_1(
        reporting_date=reporting_date, permission_mode=PermissionMode.STANDARDISED
    )


def _exposures(
    *, drawn: float = 1_000_000.0, nominal: float = 0.0, risk_type: str = "FR"
) -> pl.LazyFrame:
    """One SA and one IRB exposure with the same drawn / nominal and no interest.

    The default is a loan drawn 1,000,000 with no nominal.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["SA1", "IRB1"],
            "counterparty_reference": ["CP1", "CP2"],
            "parent_facility_reference": ["FAC1", "FAC2"],
            "drawn_amount": [drawn, drawn],
            "interest": [0.0, 0.0],
            "nominal_amount": [nominal, nominal],
            "approach": [ApproachType.SA.value, ApproachType.FIRB.value],
            "risk_type": [risk_type, risk_type],
        }
    )


def _provisions(*, gcra_label: str, with_beneficiary_type: bool) -> pl.LazyFrame:
    """SCRA 20,000 plus GCRA 10,000 on each loan.

    ``with_beneficiary_type=False`` takes the direct-join fallback path, which
    only a direct caller reaches (the loader requires ``beneficiary_type``).
    """
    frame = pl.LazyFrame(
        [
            {
                "provision_reference": f"{kind}_{ref}",
                "beneficiary_reference": ref,
                "amount": amount,
                "provision_type": label,
            }
            for ref in ("SA1", "IRB1")
            for kind, amount, label in (("S", 20_000.0, "SCRA"), ("G", 10_000.0, gcra_label))
        ]
    )
    if not with_beneficiary_type:
        return frame
    return frame.with_columns(pl.lit("loan").alias("beneficiary_type"))


def _row(frame: pl.DataFrame, reference: str) -> dict[str, Any]:
    picked = frame.filter(pl.col("exposure_reference") == reference)
    assert picked.height == 1
    return picked.row(0, named=True)


class TestResolveProvisionsDeductsSpecificOnly:
    """``resolve_provisions``: SA deduction is specific-only; the total is kept."""

    @pytest.mark.parametrize("with_beneficiary_type", [True, False], ids=_DIRECT_JOIN_IDS)
    @pytest.mark.parametrize("gcra_label", ["GCRA", "gcra"])
    @pytest.mark.parametrize("regime", _REGIMES)
    def test_sa_deduction_excludes_general_cra(
        self, regime: str, gcra_label: str, with_beneficiary_type: bool
    ) -> None:
        # Arrange
        provisions = _provisions(gcra_label=gcra_label, with_beneficiary_type=with_beneficiary_type)

        # Act
        result = resolve_provisions(_exposures(), provisions, _config(regime)).collect()

        # Assert: Art. 111(1) nets the 20,000 SCRA only; the 10,000 GCRA is Tier 2.
        sa = _row(result, "SA1")
        assert sa["provision_deducted"] == pytest.approx(20_000.0)
        assert sa["provision_on_drawn"] == pytest.approx(20_000.0)

    @pytest.mark.parametrize("with_beneficiary_type", [True, False], ids=_DIRECT_JOIN_IDS)
    @pytest.mark.parametrize("regime", _REGIMES)
    def test_nominal_deduction_excludes_general_cra(
        self, regime: str, with_beneficiary_type: bool
    ) -> None:
        """Off-balance-sheet limb: nominal is reduced by SPECIFIC CRA only.

        CRR Art. 111(1) second sentence / PS1/26 Art. 111(1)(b)(i): "nominal
        value after reduction of specific credit risk adjustments". Drawn
        10,000, nominal 100,000 (MR); SCRA 20,000 + GCRA 10,000. Drawn first:
        10,000 on drawn, the remaining 10,000 SPECIFIC on nominal ->
        nominal_after_provision 90,000, deducted 20,000.

        Detects a fix that nets drawn from the specific amount but still takes
        the nominal remainder from the total (``provision_allocated -
        provision_on_drawn``): 20,000 on nominal, 80,000 after, 30,000 deducted
        — the pre-fix figures.
        """
        # Arrange
        exposures = _exposures(drawn=10_000.0, nominal=100_000.0, risk_type="MR")
        provisions = _provisions(gcra_label="GCRA", with_beneficiary_type=with_beneficiary_type)

        # Act
        result = resolve_provisions(exposures, provisions, _config(regime)).collect()

        # Assert
        sa = _row(result, "SA1")
        assert sa["provision_on_drawn"] == pytest.approx(10_000.0)
        assert sa["provision_on_nominal"] == pytest.approx(10_000.0)
        assert sa["provision_deducted"] == pytest.approx(20_000.0)
        assert sa["nominal_after_provision"] == pytest.approx(90_000.0)

    @pytest.mark.parametrize("with_beneficiary_type", [True, False], ids=_DIRECT_JOIN_IDS)
    @pytest.mark.parametrize("regime", _REGIMES)
    def test_specific_carrier_sums_specific_rows_only(
        self, regime: str, with_beneficiary_type: bool
    ) -> None:
        # Arrange
        provisions = _provisions(gcra_label="GCRA", with_beneficiary_type=with_beneficiary_type)

        # Act
        result = resolve_provisions(_exposures(), provisions, _config(regime)).collect()

        # Assert: the specific carrier is approach-independent (it is the Art. 127
        # numerator, which also sets a defaulted IRB row's SA-equivalent RW).
        assert _row(result, "SA1")["provision_specific_allocated"] == pytest.approx(20_000.0)
        assert _row(result, "IRB1")["provision_specific_allocated"] == pytest.approx(20_000.0)

    @pytest.mark.parametrize("regime", _REGIMES)
    def test_total_is_kept_for_expected_loss(self, regime: str) -> None:
        """Guard: Art. 159 'B'(i) needs general CRA in the IRB EL comparison.

        Detects redefining ``provision_allocated`` as specific-only (it would
        read 20,000 here).
        """
        # Arrange
        provisions = _provisions(gcra_label="GCRA", with_beneficiary_type=True)

        # Act
        result = resolve_provisions(_exposures(), provisions, _config(regime)).collect()

        # Assert
        irb = _row(result, "IRB1")
        assert irb["provision_allocated"] == pytest.approx(30_000.0)
        assert irb["provision_deducted"] == pytest.approx(0.0)
        assert _row(result, "SA1")["provision_allocated"] == pytest.approx(30_000.0)

    def test_untyped_rows_count_as_specific(self) -> None:
        """A typed-NULL ``provision_type`` is specific; ``gcra`` and an unknown label are not.

        Detects an ``is_null() | lower != 'gcra'`` filter, which would still
        deduct the 7,000 ``stage3`` row (27,000). The validator reports that
        label as a DQ006 warning and keeps the row; it is kept out of the
        exposure value, the conservative reading.
        """
        # Arrange
        provisions = pl.LazyFrame(
            {
                "provision_reference": ["P_NULL", "P_SCRA", "P_GCRA", "P_BAD"],
                "beneficiary_reference": ["SA1", "SA1", "SA1", "SA1"],
                "beneficiary_type": ["loan", "loan", "loan", "loan"],
                "amount": [5_000.0, 15_000.0, 10_000.0, 7_000.0],
                "provision_type": [None, "Scra", "GCRA", "stage3"],
            },
            schema_overrides={"provision_type": pl.String},
        )

        # Act
        result = resolve_provisions(_exposures(), provisions, _config("crr")).collect()

        # Assert: 5,000 untyped + 15,000 SCRA; the 10,000 GCRA and 7,000 stage3 stay out.
        sa = _row(result, "SA1")
        assert sa["provision_deducted"] == pytest.approx(20_000.0)
        assert sa["provision_specific_allocated"] == pytest.approx(20_000.0)
        assert sa["provision_allocated"] == pytest.approx(37_000.0)

    def test_absent_provision_type_column_is_all_specific(self) -> None:
        """Guard: a direct caller with no ``provision_type`` column keeps the status quo."""
        # Arrange
        provisions = pl.LazyFrame(
            {
                "provision_reference": ["P1", "P2"],
                "beneficiary_reference": ["SA1", "SA1"],
                "beneficiary_type": ["loan", "loan"],
                "amount": [20_000.0, 10_000.0],
            }
        )

        # Act
        result = resolve_provisions(_exposures(), provisions, _config("crr")).collect()

        # Assert
        sa = _row(result, "SA1")
        assert sa["provision_deducted"] == pytest.approx(30_000.0)
        assert sa["provision_specific_allocated"] == pytest.approx(30_000.0)


def _provision_rows(rows: list[tuple[str, str, str, float, str | None]]) -> pl.DataFrame:
    """Provisions as ``(reference, beneficiary, beneficiary_type, amount, provision_type)``."""
    return pl.DataFrame(
        [
            {
                "provision_reference": ref,
                "beneficiary_reference": beneficiary,
                "beneficiary_type": beneficiary_type,
                "amount": amount,
                "provision_type": provision_type,
            }
            for ref, beneficiary, beneficiary_type, amount, provision_type in rows
        ],
        schema_overrides={"provision_type": pl.String},
    )


def _sa_exposures(
    rows: list[tuple[str, str, str, float, float]],
) -> pl.LazyFrame:
    """SA rows as ``(reference, counterparty, parent_facility, drawn, nominal)``; MR, no interest.

    ``MR`` is the 50% SA CCF in both regimes on the provision-weighting basis
    (``sa_ccf_expression`` with ``commitment_col=None``), so a nominal of N
    weighs N / 2 in the facility / counterparty pro-rata split.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": [r[0] for r in rows],
            "counterparty_reference": [r[1] for r in rows],
            "parent_facility_reference": [r[2] for r in rows],
            "drawn_amount": [r[3] for r in rows],
            "interest": [0.0] * len(rows),
            "nominal_amount": [r[4] for r in rows],
            "approach": [ApproachType.SA.value] * len(rows),
            "risk_type": ["MR"] * len(rows),
        }
    )


#: Counterparty-level cases on CP1 (two SA loans drawn 600,000 / 400,000 under
#: different facilities, so only the counterparty level splits them 60:40):
#: ``(provisions, provision_deducted L1/L2, provision_allocated L1/L2)``.
#:
#: - ``loan_scra_counterparty_gcra``: SCRA 20,000 on L1 (direct) + GCRA 10,000
#:   on CP1. Specific: 20,000 / 0. Total: 20,000 + 6,000 / 4,000. Pre-fix (and
#:   a fix that honours the specific filter at the direct level only): deducted
#:   26,000 / 4,000.
#: - ``counterparty_scra_and_gcra``: SCRA 10,000 + GCRA 5,000, both on CP1.
#:   Specific 6,000 / 4,000; total 9,000 / 6,000. Pre-fix: deducted 9,000 /
#:   6,000. A fix that joins the specific carrier at the direct level only
#:   deducts 0 / 0.
_COUNTERPARTY_CASES = [
    pytest.param(
        [
            ("S1", "L1", "loan", 20_000.0, "SCRA"),
            ("G1", "CP1", "counterparty", 10_000.0, "GCRA"),
        ],
        (20_000.0, 0.0),
        (26_000.0, 4_000.0),
        id="loan_scra_counterparty_gcra",
    ),
    pytest.param(
        [
            ("S1", "CP1", "counterparty", 10_000.0, "SCRA"),
            ("G1", "CP1", "counterparty", 5_000.0, "GCRA"),
        ],
        (6_000.0, 4_000.0),
        (9_000.0, 6_000.0),
        id="counterparty_scra_and_gcra",
    ),
]

#: Facility-level provisions on F1: SCRA 30,000 + GCRA 20,000.
_FACILITY_PROVISIONS = [
    ("S1", "F1", "facility", 30_000.0, "SCRA"),
    ("G1", "F1", "facility", 20_000.0, "GCRA"),
]


class TestResolveProvisionsAllocationLevels:
    """``resolve_provisions``: the specific filter holds at the facility and counterparty levels.

    General CRA are portfolio-level provisions, so they are normally attached
    to a facility or a counterparty, not to a loan. Every
    ``TestResolveProvisionsDeductsSpecificOnly`` case attaches at the direct
    level; these detect a fix that filters ``provision_type`` only there.
    """

    @pytest.mark.parametrize(
        ("rows", "expected_deducted", "expected_allocated"), _COUNTERPARTY_CASES
    )
    @pytest.mark.parametrize("regime", _REGIMES)
    def test_counterparty_level_general_cra_is_not_deducted(
        self,
        regime: str,
        rows: list[tuple[str, str, str, float, str | None]],
        expected_deducted: tuple[float, float],
        expected_allocated: tuple[float, float],
    ) -> None:
        # Arrange
        exposures = _sa_exposures(
            [("L1", "CP1", "FAC1", 600_000.0, 0.0), ("L2", "CP1", "FAC2", 400_000.0, 0.0)]
        )
        provisions = _provision_rows(rows).lazy()

        # Act
        result = resolve_provisions(exposures, provisions, _config(regime)).collect()

        # Assert
        l1, l2 = _row(result, "L1"), _row(result, "L2")
        assert l2["provision_allocated"] == pytest.approx(expected_allocated[1]), (
            "adequacy: L2 has no direct provision, so its allocation proves the "
            "counterparty-level rows reached the split"
        )
        assert l1["provision_allocated"] == pytest.approx(expected_allocated[0])
        assert l1["provision_specific_allocated"] == pytest.approx(expected_deducted[0])
        assert l2["provision_specific_allocated"] == pytest.approx(expected_deducted[1])
        assert l1["provision_deducted"] == pytest.approx(expected_deducted[0])
        assert l2["provision_deducted"] == pytest.approx(expected_deducted[1])

    @pytest.mark.parametrize("regime", _REGIMES)
    def test_facility_level_general_cra_is_not_deducted(self, regime: str) -> None:
        """F1: L1 drawn 500,000 and its undrawn leg nominal 500,000 (MR, 50%).

        Weights 500,000 : 250,000 = 2/3 : 1/3. Specific 30,000 -> 20,000 on
        L1's drawn and 10,000 on the undrawn nominal (490,000 after). Total
        50,000 -> 33,333.33 / 16,666.67, which is also what a fix that honours
        the specific filter at the direct level only would deduct (nominal
        483,333.33 after). A fix that joins the specific carrier at the direct
        level only deducts nothing.
        """
        # Arrange
        exposures = _sa_exposures(
            [("L1", "CP1", "F1", 500_000.0, 0.0), ("F1_UNDRAWN", "CP1", "F1", 0.0, 500_000.0)]
        )
        provisions = _provision_rows(_FACILITY_PROVISIONS).lazy()

        # Act
        result = resolve_provisions(exposures, provisions, _config(regime)).collect()

        # Assert
        drawn, undrawn = _row(result, "L1"), _row(result, "F1_UNDRAWN")
        assert undrawn["provision_allocated"] == pytest.approx(50_000.0 / 3), (
            "adequacy: the facility-level rows must reach the undrawn leg pro rata"
        )
        assert drawn["provision_allocated"] == pytest.approx(100_000.0 / 3)
        assert drawn["provision_specific_allocated"] == pytest.approx(20_000.0)
        assert undrawn["provision_specific_allocated"] == pytest.approx(10_000.0)
        assert drawn["provision_deducted"] == pytest.approx(20_000.0)
        assert undrawn["provision_on_nominal"] == pytest.approx(10_000.0)
        assert undrawn["provision_deducted"] == pytest.approx(10_000.0)
        assert undrawn["nominal_after_provision"] == pytest.approx(490_000.0)


def _pipeline_provisions(
    rows: list[tuple[str, float, str | None]],
    *,
    beneficiary: str = "L1",
    beneficiary_type: str = "loan",
) -> pl.DataFrame:
    """Direct provisions on one exposure: ``(reference, amount, provision_type)``."""
    return pl.DataFrame(
        [
            {
                "provision_reference": ref,
                "beneficiary_reference": beneficiary,
                "beneficiary_type": beneficiary_type,
                "amount": amount,
                "provision_type": provision_type,
            }
            for ref, amount, provision_type in rows
        ],
        schema_overrides={"provision_type": pl.String},
    )


def _run_one_loan(
    regime: str, *, drawn: float, provisions: pl.DataFrame, defaulted: bool
) -> dict[str, Any]:
    loan = {
        "loan_reference": "L1",
        "counterparty_reference": "CP1",
        "drawn_amount": drawn,
        "is_defaulted": defaulted,
    }
    results, _errors = harness.run(
        regime, loans=harness.loans([loan]), provisions=provisions.lazy()
    )
    result = harness.row(results, "L1")
    assert result["approach_applied"] == ApproachType.SA.value
    return result


class TestPipelineExposureValueNetsSpecificOnly:
    """Production path (``PipelineOrchestrator``): CRR Art. 111(1) / PS1/26 Art. 111(1)."""

    @pytest.mark.parametrize("regime", _REGIMES)
    def test_general_cra_does_not_reduce_sa_exposure_value(self, regime: str) -> None:
        # Arrange
        provisions = _pipeline_provisions([("S1", 20_000.0, "SCRA"), ("G1", 10_000.0, "GCRA")])

        # Act
        result = _run_one_loan(regime, drawn=1_000_000.0, provisions=provisions, defaulted=False)

        # Assert
        assert result["provision_deducted"] == pytest.approx(20_000.0)
        assert result["ead_final"] == pytest.approx(980_000.0)

    @pytest.mark.parametrize("omit_column", [True, False], ids=["column_omitted", "explicit_null"])
    @pytest.mark.parametrize("regime", _REGIMES)
    def test_untyped_provision_is_deducted_as_specific(
        self, regime: str, omit_column: bool
    ) -> None:
        """Guard: the loader injects a typed NULL; NULL stays specific (status quo).

        Detects a ``lower(provision_type) == 'scra'`` filter with no null limb,
        which would leave the 20,000 undeducted (EAD 1,000,000).
        """
        # Arrange
        provisions = _pipeline_provisions([("U1", 20_000.0, None)])
        if omit_column:
            provisions = provisions.drop("provision_type")

        # Act
        result = _run_one_loan(regime, drawn=1_000_000.0, provisions=provisions, defaulted=False)

        # Assert
        assert result["provision_deducted"] == pytest.approx(20_000.0)
        assert result["ead_final"] == pytest.approx(980_000.0)

    @pytest.mark.parametrize("regime", _REGIMES)
    def test_general_cra_does_not_reduce_off_balance_sheet_nominal(self, regime: str) -> None:
        """Off-balance-sheet item: "nominal value after reduction of specific CRA", x CCF.

        CRR Art. 111(1) second sentence / PS1/26 Art. 111(1)(b). A contingent
        (full-risk guarantee, CCF 100% in both regimes) of nominal 100,000 on
        the unrated corporate (100%); SCRA 20,000 + GCRA 10,000 on it. Nominal
        after provision 80,000 -> EAD 80,000 -> RWA 80,000. Pre-fix (and a fix
        that keeps the nominal remainder on the total): 70,000.
        """
        # Arrange
        contingent = {
            "contingent_reference": "C1",
            "counterparty_reference": "CP1",
            "product_type": "FINANCIAL_GUARANTEE",
            "book_code": "BANK",
            "value_date": date(2025, 1, 1),
            "maturity_date": date(2030, 1, 1),
            "currency": "GBP",
            "seniority": "senior",
            "nominal_amount": 100_000.0,
            "risk_type": "FR",
        }
        provisions = _pipeline_provisions(
            [("S1", 20_000.0, "SCRA"), ("G1", 10_000.0, "GCRA")],
            beneficiary="C1",
            beneficiary_type="contingent",
        )

        # Act
        results, _errors = harness.run(
            regime, contingents=pl.DataFrame([contingent]), provisions=provisions.lazy()
        )
        result = harness.row(results, "C1")

        # Assert
        assert result["approach_applied"] == ApproachType.SA.value
        assert result["provision_deducted"] == pytest.approx(20_000.0)
        assert result["nominal_after_provision"] == pytest.approx(80_000.0)
        assert result["ead_final"] == pytest.approx(80_000.0)
        assert result["rwa_final"] == pytest.approx(80_000.0)


class TestPipelineAllocationLevelsNetSpecificOnly:
    """Production path at the facility and counterparty levels, where GCRA normally sit."""

    @pytest.mark.parametrize(
        ("rows", "expected_deducted", "expected_allocated"), _COUNTERPARTY_CASES
    )
    @pytest.mark.parametrize("regime", _REGIMES)
    def test_counterparty_level_general_cra_does_not_reduce_exposure_value(
        self,
        regime: str,
        rows: list[tuple[str, str, str, float, str | None]],
        expected_deducted: tuple[float, float],
        expected_allocated: tuple[float, float],
    ) -> None:
        """Two SA loans on CP1, drawn 600,000 / 400,000; EAD = drawn - specific share."""
        # Arrange
        loans = harness.loans(
            [
                {
                    "loan_reference": "L1",
                    "counterparty_reference": "CP1",
                    "drawn_amount": 600_000.0,
                },
                {
                    "loan_reference": "L2",
                    "counterparty_reference": "CP1",
                    "drawn_amount": 400_000.0,
                },
            ]
        )

        # Act
        results, _errors = harness.run(regime, loans=loans, provisions=_provision_rows(rows).lazy())

        # Assert
        l1, l2 = harness.row(results, "L1"), harness.row(results, "L2")
        assert l1["approach_applied"] == l2["approach_applied"] == ApproachType.SA.value
        assert l2["provision_allocated"] == pytest.approx(expected_allocated[1]), (
            "adequacy: L2 has no direct provision, so its allocation proves the "
            "counterparty-level rows reached the split"
        )
        assert l1["provision_allocated"] == pytest.approx(expected_allocated[0])
        assert l1["provision_deducted"] == pytest.approx(expected_deducted[0])
        assert l2["provision_deducted"] == pytest.approx(expected_deducted[1])
        assert l1["ead_final"] == pytest.approx(600_000.0 - expected_deducted[0])
        assert l2["ead_final"] == pytest.approx(400_000.0 - expected_deducted[1])

    @pytest.mark.parametrize("regime", _REGIMES)
    def test_facility_level_general_cra_does_not_reduce_either_leg(self, regime: str) -> None:
        """F1 limit 1,000,000 (MR) over L1 drawn 500,000: the hierarchy adds F1_UNDRAWN.

        SCRA 30,000 + GCRA 20,000 on F1, split 2/3 : 1/3 (500,000 drawn :
        500,000 x 50%). Specific only: 20,000 off L1 (EAD 480,000) and 10,000
        off the undrawn nominal (490,000 after). Pre-fix: 33,333.33 /
        16,666.67. The undrawn leg's EAD is not asserted: it is that nominal
        times the regime's CCF for the leg, which this item does not touch.
        """
        # Arrange
        facility = {
            "facility_reference": "F1",
            "counterparty_reference": "CP1",
            "product_type": "RCF",
            "book_code": "BANK",
            "value_date": date(2025, 1, 1),
            "maturity_date": date(2030, 1, 1),
            "currency": "GBP",
            "limit": 1_000_000.0,
            "committed": True,
            "seniority": "senior",
            "risk_type": "MR",
        }
        mapping = {"parent_facility_reference": "F1", "child_reference": "L1", "child_type": "loan"}
        loans = harness.loans(
            [{"loan_reference": "L1", "counterparty_reference": "CP1", "drawn_amount": 500_000.0}]
        )

        # Act
        results, _errors = harness.run(
            regime,
            loans=loans,
            facilities=pl.DataFrame([facility]),
            facility_mappings=pl.DataFrame([mapping]),
            provisions=_provision_rows(_FACILITY_PROVISIONS).lazy(),
        )

        # Assert
        drawn, undrawn = harness.row(results, "L1"), harness.row(results, "F1_UNDRAWN")
        assert undrawn["nominal_amount"] == pytest.approx(500_000.0), (
            "adequacy: the facility must generate a 500,000 undrawn leg"
        )
        assert drawn["approach_applied"] == undrawn["approach_applied"] == ApproachType.SA.value
        assert undrawn["provision_allocated"] == pytest.approx(50_000.0 / 3)
        assert drawn["provision_allocated"] == pytest.approx(100_000.0 / 3)
        assert drawn["provision_deducted"] == pytest.approx(20_000.0)
        assert undrawn["provision_deducted"] == pytest.approx(10_000.0)
        assert undrawn["nominal_after_provision"] == pytest.approx(490_000.0)
        assert drawn["ead_final"] == pytest.approx(480_000.0)


class TestPipelineDefaultCoverageCountsSpecificOnly:
    """Production path: CRR Art. 127(1) / PS1/26 Art. 127(1) numerator."""

    @pytest.mark.parametrize("regime", _REGIMES)
    def test_general_cra_does_not_buy_the_100_percent_weight(self, regime: str) -> None:
        # Arrange
        provisions = _pipeline_provisions([("S1", 15_000.0, "SCRA"), ("G1", 10_000.0, "GCRA")])

        # Act
        result = _run_one_loan(regime, drawn=100_000.0, provisions=provisions, defaulted=True)

        # Assert: 15,000 / 100,000 = 15% < 20% -> 150%.
        assert result["risk_weight"] == pytest.approx(1.5)

    @pytest.mark.parametrize("regime", _REGIMES)
    def test_defaulted_exposure_value_and_rwa(self, regime: str) -> None:
        # Arrange
        provisions = _pipeline_provisions([("S1", 15_000.0, "SCRA"), ("G1", 10_000.0, "GCRA")])

        # Act
        result = _run_one_loan(regime, drawn=100_000.0, provisions=provisions, defaulted=True)

        # Assert: 85,000 x 150%.
        assert result["ead_final"] == pytest.approx(85_000.0)
        assert result["rwa_final"] == pytest.approx(127_500.0)

    @pytest.mark.parametrize("regime", _REGIMES)
    def test_untyped_provision_counts_towards_coverage(self, regime: str) -> None:
        """Guard: 25,000 untyped on 100,000 is 25% >= 20% -> 100% on 75,000."""
        # Arrange
        provisions = _pipeline_provisions([("U1", 25_000.0, None)])

        # Act
        result = _run_one_loan(regime, drawn=100_000.0, provisions=provisions, defaulted=True)

        # Assert
        assert result["risk_weight"] == pytest.approx(1.0)
        assert result["ead_final"] == pytest.approx(75_000.0)


class TestOutputFloorDefaultCoverageCountsSpecificOnly:
    """Basel 3.1 only (CRR has no output floor): PS1/26 Art. 127(1) on the floor path.

    ``_apply_defaulted_risk_weight`` runs on every row of the unified frame, so
    it also sets the SA-equivalent weight of a defaulted IRB row, which the
    output floor reads (LESSONS D1).

    The assertion is on that WEIGHT, not on ``sa_rwa``. An IRB row's
    ``risk_weight`` is overwritten by the IRB step; the Basel 3.1 SA step's
    snapshot ``risk_weight_pre_currency_mismatch`` keeps the SA-equivalent
    weight (the Art. 123B multiplier never applies to a corporate, so the two
    are the same). ``sa_rwa`` is that weight times the SA-equivalent exposure,
    which today is the IRB row's undeducted 100,000: pre-existing behaviour,
    not a requirement. PS1/26 Art. 92(3A) computes S-TREA under the SA, whose
    exposure value nets specific CRA (Art. 111(1)), so a later fix could make
    it 85,000 / 75,000 — that must not collide with this test. At HEAD the two
    cases give sa_rwa 150,000 / floor_rwa 90,000 and sa_rwa 100,000 /
    floor_rwa 60,000 (floor 60% at 2027-06-30).
    """

    @pytest.mark.parametrize(
        ("rows", "expected_weight"),
        [
            pytest.param(
                [("S1", 15_000.0, "SCRA"), ("G1", 10_000.0, "GCRA")],
                1.5,
                id="general_cra_excluded",
            ),
            pytest.param(
                [("S1", 25_000.0, "SCRA"), ("G1", 10_000.0, "GCRA")],
                1.0,
                id="specific_cra_counted",
            ),
        ],
    )
    def test_defaulted_irb_loan_sa_equivalent_weight_counts_specific_cra(
        self, rows: list[tuple[str, float, str | None]], expected_weight: float
    ) -> None:
        """F-IRB, defaulted, drawn 100,000, 2027-06-30; IRB deducts no provision.

        - ``general_cra_excluded``: SCRA 15,000 + GCRA 10,000. Specific coverage
          15,000 / 100,000 = 15% < 20% -> 150%. Pre-fix the 25,000 total gave
          25% -> 100%. Detects gating the specific numerator to SA rows only (an
          IRB row would fall back to the 25,000 total).
        - ``specific_cra_counted``: SCRA 25,000 + GCRA 10,000. 25% >= 20% ->
          100%. Detects using ``provision_deducted`` as the numerator: it is 0
          on an IRB row, which would always give 150%.
        """
        # Arrange
        provisions = _pipeline_provisions(rows)
        loan = {
            "loan_reference": "L1",
            "counterparty_reference": "CP1",
            "drawn_amount": 100_000.0,
            "is_defaulted": True,
        }

        # Act
        results, _errors = harness.run(
            "b31", firb=True, loans=harness.loans([loan]), provisions=provisions.lazy()
        )
        result = harness.row(results, "L1")

        # Assert
        assert result["approach_applied"] == ApproachType.FIRB.value
        assert result["provision_deducted"] == pytest.approx(0.0)
        assert result["risk_weight_pre_currency_mismatch"] == pytest.approx(expected_weight)


def test_reporting_dates_sit_in_their_regimes() -> None:
    """Adequacy: each regime parametrisation really runs that regime."""
    assert harness.REPORTING_DATES["crr"] < date(2027, 1, 1) <= harness.REPORTING_DATES["b31"]
