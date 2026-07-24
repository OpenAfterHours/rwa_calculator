"""
Unit pins — P1.253: CRR non-named MDB *guarantors* take the institution treatment.

Pipeline position:
    engine/sa/guarantor_rw.py::build_guarantor_rw_expr — compiled by both live
    guarantee-substitution paths (engine/sa/rw_adjustments.py for the SA branch,
    engine/irb/guarantee.py for the IRB SA-RWSM fallback).

Key assertion:
    CRR Art. 117(1) (crr.pdf p.116, verbatim): "Exposures to multilateral
    development banks that are not referred to in paragraph 2 shall be treated in
    the same manner as exposures to institutions. The preferential treatment for
    short-term exposures as specified in Articles 119(2), 120(2) and 121(3) shall
    not be applied."

    There is no MDB risk-weight table in CRR. A non-named MDB guarantor therefore
    prices from the institution tables — Art. 120 Table 3 when rated, the Art. 121
    unrated institution fallback (100%) otherwise — and never from the short-term
    Table 4. The dedicated MDB Table 2B (CQS2 30%, unrated 50%) is PRA PS1/26
    Art. 117(1)(a)/(b) only.

    Pre-fix, ``build_guarantor_rw_expr`` priced non-named MDB guarantors from
    Table 2B under BOTH regimes, so a CRR MDB guarantor was anti-conservative at
    CQS2 (30% vs 50%) and unrated (50% vs 100%).

    The already-correct direct (non-guarantor) CRR path is
    ``sa/risk_weights.py::_apply_crr_risk_weight_overrides`` (rated -> Art. 120
    Table 3, unrated -> Art. 121 sovereign-derived with a 100% fallback); this
    module pins the guarantor path to the same regulatory conclusion.

    All expectations are hand-derived from the rulepack tables, never from
    running the engine.

References:
    - CRR Art. 117(1): non-named MDBs treated as institutions; short-term
      preferential (Art. 119(2)/120(2)/121(3)) excluded
    - CRR Art. 117(2): named MDBs — 0% unconditional (both regimes)
    - CRR Art. 120 Table 3 (institution_rw_crr): CQS1 20%, CQS2 50%, CQS3 50%,
      CQS6 150%, unrated 100%
    - CRR Art. 120(2) Table 4 (institution_short_term_rw_crr): CQS2 20% — the
      value that must NOT appear for an MDB
    - PRA PS1/26 Art. 117(1)(a)/(b) (mdb_risk_weights_table_2b): CQS2 30%,
      unrated 50% — retained under Basel 3.1
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.sa.guarantor_rw import build_guarantor_rw_expr
from rwa_calc.engine.sa.rw_adjustments import apply_guarantee_substitution

# ---------------------------------------------------------------------------
# Hand-pinned expectations (from the rulepack tables, NOT from the engine)
# ---------------------------------------------------------------------------

# CRR Art. 120 Table 3 — institution_rw_crr
CRR_INSTITUTION_CQS1_RW: float = 0.20
CRR_INSTITUTION_CQS2_RW: float = 0.50
CRR_INSTITUTION_CQS3_RW: float = 0.50
CRR_INSTITUTION_CQS6_RW: float = 1.50
CRR_INSTITUTION_UNRATED_RW: float = 1.00

# CRR Art. 120(2) Table 4 — institution_short_term_rw_crr[CQS2]; excluded for MDBs
CRR_INSTITUTION_SHORT_TERM_CQS2_RW: float = 0.20

# PRA PS1/26 Art. 117(1)(a)/(b) — mdb_risk_weights_table_2b
B31_MDB_TABLE_2B_CQS2_RW: float = 0.30
B31_MDB_TABLE_2B_UNRATED_RW: float = 0.50

# CRR Art. 117(2) / PS1/26 Art. 117(2) — mdb_named_zero_rw
MDB_NAMED_ZERO_RW: float = 0.0

EAD: float = 1_000_000.0
BORROWER_RW: float = 1.00  # 100% — above every guarantor RW below, so RWSM binds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _evaluate_guarantor_rw(
    *,
    entity_type: str,
    cqs: int | None,
    is_basel_3_1: bool,
    short_term: bool = False,
) -> float:
    """Evaluate ``build_guarantor_rw_expr`` for one MDB-class guarantor row."""
    frame = pl.LazyFrame(
        {
            "guarantor_exposure_class": ["mdb"],
            "guarantor_entity_type": [entity_type],
            "guarantor_cqs": [cqs],
            "guarantor_country_code": ["US"],
            "guarantor_is_ccp_client_cleared": [None],
            "guarantor_scra_grade": [None],
            "guarantor_is_short_term": [short_term],
        },
        schema_overrides={
            "guarantor_cqs": pl.Int8,
            "guarantor_is_ccp_client_cleared": pl.Boolean,
            "guarantor_scra_grade": pl.String,
        },
    )
    expr = build_guarantor_rw_expr(
        exposure_class_col="guarantor_exposure_class",
        entity_type_col="guarantor_entity_type",
        cqs_col="guarantor_cqs",
        country_code_col="guarantor_country_code",
        ccp_client_cleared_col="guarantor_is_ccp_client_cleared",
        scra_grade_col="guarantor_scra_grade",
        is_basel_3_1=is_basel_3_1,
        short_term_flag_col="guarantor_is_short_term",
    )
    return frame.select(expr.alias("guarantor_rw")).collect()["guarantor_rw"][0]


def _sa_substitution_result(
    *,
    entity_type: str,
    cqs: int | None,
    config: CalculationConfig,
) -> dict:
    """Run the SA guarantee-substitution path for a fully-guaranteed exposure."""
    frame = pl.DataFrame(
        {
            "exposure_reference": ["P1253-EXP"],
            "ead_final": [EAD],
            "risk_weight": [BORROWER_RW],
            "guaranteed_portion": [EAD],
            "unguaranteed_portion": [0.0],
            "guarantor_entity_type": [entity_type],
            "guarantor_exposure_class": ["mdb"],
            "guarantor_cqs": [cqs],
            "guarantor_country_code": ["US"],
            "exposure_class": ["CORPORATE"],
            "currency": ["GBP"],
        },
        schema_overrides={"guarantor_cqs": pl.Int8},
    ).lazy()
    return apply_guarantee_substitution(frame, config).collect().to_dicts()[0]


# ---------------------------------------------------------------------------
# CRR — the P1.253 defect
# ---------------------------------------------------------------------------


class TestCRRNonNamedMDBGuarantorUsesInstitutionTables:
    """CRR Art. 117(1): non-named MDB guarantors price as institutions."""

    def test_crr_rated_mdb_cqs2_uses_institution_table_3(self) -> None:
        """CRR CQS2 MDB guarantor -> 50% (Art. 120 Table 3), not Table 2B's 30%.

        Arrange: non-named MDB guarantor, CQS 2, CRR arm.
        Act:     build_guarantor_rw_expr.
        Assert:  RW == 0.50.

        Pre-fix failure: 0.30 (PS1/26 Table 2B applied under CRR) — a 20pp
        anti-conservative understatement.
        """
        # Arrange / Act
        rw = _evaluate_guarantor_rw(entity_type="mdb", cqs=2, is_basel_3_1=False)

        # Assert
        assert rw == pytest.approx(CRR_INSTITUTION_CQS2_RW), (
            "CRR Art. 117(1) treats non-named MDBs as institutions (Art. 120 "
            f"Table 3 CQS2 = 50%); got {rw:.4f}. There is no MDB table in CRR — "
            "Table 2B's 30% is PS1/26 Art. 117(1)(a) only."
        )

    def test_crr_unrated_mdb_uses_art_121_institution_fallback(self) -> None:
        """CRR unrated MDB guarantor -> 100% (Art. 121 fallback), not Table 2B's 50%.

        Arrange: non-named MDB guarantor, CQS null, CRR arm.
        Act:     build_guarantor_rw_expr.
        Assert:  RW == 1.00.

        Pre-fix failure: 0.50 (Table 2B unrated row) — a 50pp anti-conservative
        understatement. No guarantor sovereign-CQS join exists in the CRM column
        production, so the conservative Art. 121 unrated institution weight
        stands (the documented SA-side approximation, as for PSE / RGLA).
        """
        # Arrange / Act
        rw = _evaluate_guarantor_rw(entity_type="mdb", cqs=None, is_basel_3_1=False)

        # Assert
        assert rw == pytest.approx(CRR_INSTITUTION_UNRATED_RW), (
            f"expected the Art. 121 unrated institution weight 1.00, got {rw:.4f}"
        )

    def test_crr_short_term_mdb_does_not_get_table_4_preferential(self) -> None:
        """CRR CQS2 MDB guarantor flagged short-term still gets 50%, not 20%.

        Art. 117(1) final sentence: "The preferential treatment for short-term
        exposures as specified in Articles 119(2), 120(2) and 121(3) shall not be
        applied."

        Arrange: non-named MDB guarantor, CQS 2, short-term flag True, CRR arm.
        Act:     build_guarantor_rw_expr with short_term_flag_col supplied.
        Assert:  RW == 0.50 (long-term Table 3), NOT 0.20 (Table 4).
        """
        # Arrange / Act
        rw = _evaluate_guarantor_rw(entity_type="mdb", cqs=2, is_basel_3_1=False, short_term=True)

        # Assert
        assert rw == pytest.approx(CRR_INSTITUTION_CQS2_RW), (
            "Art. 117(1) excludes the Art. 120(2) short-term preferential for "
            f"MDBs, so the Table 4 20% must not apply; got {rw:.4f}."
        )

    @pytest.mark.parametrize(
        ("cqs", "expected"),
        [
            (1, CRR_INSTITUTION_CQS1_RW),
            (3, CRR_INSTITUTION_CQS3_RW),
            (6, CRR_INSTITUTION_CQS6_RW),
        ],
    )
    def test_crr_mdb_other_cqs_bands(self, cqs: int, expected: float) -> None:
        """CRR MDB guarantor CQS 1 / 3 / 6 price from Art. 120 Table 3.

        CQS1 (20%), CQS3 (50%) and CQS6 (150%) coincide between Table 2B and
        Table 3, so these bands are unmoved by the fix — regression guards that
        the reroute did not disturb the rest of the ladder.
        """
        # Arrange / Act
        rw = _evaluate_guarantor_rw(entity_type="mdb", cqs=cqs, is_basel_3_1=False)

        # Assert
        assert rw == pytest.approx(expected)

    def test_crr_capital_effect_on_guaranteed_exposure(self) -> None:
        """CRR: a CQS2 MDB-guaranteed GBP 1m exposure carries RWA 500,000.

        Arrange: EAD 1,000,000 fully guaranteed by a CQS2 non-named MDB,
                 borrower RW 100%, CRR config.
        Act:     SA guarantee substitution (RWSM, Art. 235).
        Assert:  substituted RW == 0.50 and RWA == 500,000.

        Pre-fix failure: RW 0.30 -> RWA 300,000, i.e. 200,000 of RWA relief that
        CRR Art. 117(1) does not permit.
        """
        # Arrange
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))

        # Act
        row = _sa_substitution_result(entity_type="mdb", cqs=2, config=config)

        # Assert
        assert row["guarantor_rw"] == pytest.approx(CRR_INSTITUTION_CQS2_RW)
        assert row["risk_weight"] == pytest.approx(CRR_INSTITUTION_CQS2_RW)
        assert row["risk_weight"] * EAD == pytest.approx(500_000.0), (
            "expected RWA 500,000 (1,000,000 x Art. 120 Table 3 CQS2 50%), got "
            f"{row['risk_weight'] * EAD:,.2f}"
        )


# ---------------------------------------------------------------------------
# Basel 3.1 — Table 2B must be preserved
# ---------------------------------------------------------------------------


class TestBasel31NonNamedMDBGuarantorKeepsTable2B:
    """PS1/26 Art. 117(1)(a)/(b): the dedicated MDB Table 2B survives the fix."""

    def test_b31_unrated_mdb_keeps_table_2b_50_pct(self) -> None:
        """B31 unrated MDB guarantor -> 50% (Table 2B), not the institution path.

        This is the discriminating B31 band: routing an unrated MDB through the
        institution builder would hand it the ECRA unrated / SCRA dispatch
        (Grade-C fallback 150%), not 50%.

        Arrange: non-named MDB guarantor, CQS null, B31 arm.
        Act:     build_guarantor_rw_expr.
        Assert:  RW == 0.50.
        """
        # Arrange / Act
        rw = _evaluate_guarantor_rw(entity_type="mdb", cqs=None, is_basel_3_1=True)

        # Assert
        assert rw == pytest.approx(B31_MDB_TABLE_2B_UNRATED_RW), (
            f"PS1/26 Table 2B unrated row is 50%; got {rw:.4f}"
        )

    def test_b31_rated_mdb_cqs2_keeps_table_2b_30_pct(self) -> None:
        """B31 CQS2 MDB guarantor -> 30% (Table 2B).

        Arrange: non-named MDB guarantor, CQS 2, B31 arm.
        Act:     build_guarantor_rw_expr.
        Assert:  RW == 0.30 (unchanged by the CRR-only reroute).
        """
        # Arrange / Act
        rw = _evaluate_guarantor_rw(entity_type="mdb", cqs=2, is_basel_3_1=True)

        # Assert
        assert rw == pytest.approx(B31_MDB_TABLE_2B_CQS2_RW)


# ---------------------------------------------------------------------------
# Art. 117(2) named MDBs — 0% under both regimes
# ---------------------------------------------------------------------------


class TestNamedMDBZeroRiskWeightUnaffected:
    """Art. 117(2): the named-MDB 0% carve-out is untouched in either regime."""

    @pytest.mark.parametrize("is_basel_3_1", [False, True])
    @pytest.mark.parametrize("cqs", [None, 2, 6])
    def test_named_mdb_guarantor_stays_zero(self, is_basel_3_1: bool, cqs: int | None) -> None:
        """A ``mdb_named`` guarantor is 0% regardless of CQS and regime.

        The named-MDB branch is evaluated ahead of the non-named branch, so the
        CRR reroute must not capture it — including for the unrated case, where
        the institution fallback would otherwise give 100%.
        """
        # Arrange / Act
        rw = _evaluate_guarantor_rw(entity_type="mdb_named", cqs=cqs, is_basel_3_1=is_basel_3_1)

        # Assert
        assert rw == pytest.approx(MDB_NAMED_ZERO_RW)
