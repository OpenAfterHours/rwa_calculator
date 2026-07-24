"""
Unit pins — IRB SA-fallback guarantor RW: IO / named-MDB / MDB Table 2B closures.

Pipeline position:
    CRMProcessor → IRB branch → engine/irb/guarantee.py::apply_guarantee_substitution

Key assertion:
    ``_compute_guarantor_rw_sa`` (engine/irb/guarantee.py) prices an SA guarantor's
    risk weight by ``guarantor_exposure_class``. Besides the headline PSE/RGLA gap
    (pinned by the acceptance suite), the same when/then chain also mishandles:

    (a) international organisation guarantors (Art. 118: 0% unconditional) —
        "international_organisation" falls to ``.otherwise(null)`` → guarantee
        silently dropped (guarantor_rw = None);
    (b) named-MDB guarantors (Art. 117(2): 0% unconditional) — entity_type
        "mdb_named" maps to class "mdb", which today routes through the
        INSTITUTION branch (unrated CRR fallback = 100%, not 0%);
    (c) non-named MDB guarantors — class "mdb" also routes through the
        INSTITUTION branch, bypassing the regime-specific Art. 117(1) treatment
        (PS1/26 Table 2B under Basel 3.1).

    The SA-side twin (engine/sa/namespace.py::_build_guarantor_rw_expr) already
    has all three branches (IO 0% → named MDB 0% → non-named MDB, ahead of the
    institution branch); the shared guarantor RW expression closes them on the
    IRB path. Each test pins the post-fix value and FAILS pre-fix.

    NOTE on framework arms (revised by P1.253): the two regimes diverge for
    non-named MDBs. CRR Art. 117(1) says they "shall be treated in the same
    manner as exposures to institutions" and CRR has no MDB table, so the CRR arm
    pins Art. 120 Table 3 (CQS 2 = 50%). Table-2B adoption is pinned on the B31
    arm using an UNRATED MDB — Table 2B's 50% versus the institution ECRA/SCRA
    dispatch's Grade-C 150% — because at CQS 2 the B31 ECRA weight (30%)
    coincides with Table 2B and would not discriminate.

References:
    - CRR Art. 118 / PRA PS1/26 Art. 118: international organisations — 0%
    - CRR Art. 117(2): named MDBs — 0% unconditional
    - CRR Art. 117(1): non-named MDBs treated as institutions (Art. 120 Table 3
      rated / Art. 121 unrated), short-term preferential excluded
    - PRA PS1/26 Art. 117(1)(a)/(b) (MDB_RISK_WEIGHTS_TABLE_2B): the Basel 3.1
      MDB table — CQS 2 = 30%, unrated = 50%
    - engine/irb/guarantee.py::_compute_guarantor_rw_sa: bug site (.otherwise(null)
      for IO; mdb routed via the institution branch)
    - engine/sa/namespace.py::_build_guarantor_rw_expr: SA-side reference branches
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import CQS
from rwa_calc.engine.irb.guarantee import apply_guarantee_substitution
from rwa_calc.engine.sa.crr_risk_weight_tables import (
    INSTITUTION_RISK_WEIGHTS_CRR,
    MDB_RISK_WEIGHTS_TABLE_2B,
)

# ---------------------------------------------------------------------------
# Frame constants
# ---------------------------------------------------------------------------

EAD: float = 1_000_000.0
BORROWER_RW: float = 0.80  # above every post-fix guarantor RW below → beneficial
BORROWER_RWA: float = BORROWER_RW * EAD

# Post-fix expected guarantor risk weights (hand-pinned from the data tables)
EXPECTED_IO_RW: float = 0.0  # Art. 118: international organisations 0%
EXPECTED_NAMED_MDB_RW: float = 0.0  # Art. 117(2): named MDBs 0% (MDB_NAMED_ZERO_RW)
# CRR Art. 117(1) routes non-named MDBs to the institution tables: Art. 120
# Table 3 CQS 2 = 50%. B31 keeps the dedicated Table 2B (unrated row = 50%).
EXPECTED_CRR_MDB_CQS2_RW: float = float(INSTITUTION_RISK_WEIGHTS_CRR[CQS.CQS2])  # 0.50
EXPECTED_B31_MDB_UNRATED_RW: float = float(MDB_RISK_WEIGHTS_TABLE_2B[CQS.UNRATED])  # 0.50


@pytest.fixture
def crr_config() -> CalculationConfig:
    """CRR configuration (the SA RWSM fallback path under test)."""
    return CalculationConfig.crr(reporting_date=date(2025, 12, 31))


@pytest.fixture
def b31_config() -> CalculationConfig:
    """Basel 3.1 configuration (IO 0% is framework-identical)."""
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


def _guaranteed_irb_frame(
    *,
    guarantor_entity_type: str,
    guarantor_cqs: int | None,
) -> pl.LazyFrame:
    """Build the minimal fully-guaranteed FIRB exposure frame for the RWSM path.

    Mirrors the frame-construction conventions of
    tests/unit/irb/test_irb_parameter_substitution.py: a single CORPORATE
    borrower row with a 100%-covered guarantee and an SA guarantor
    (guarantor_approach="sa", guarantor_pd=None → SA RW substitution).
    ``guarantor_exposure_class`` is intentionally omitted —
    ``_compute_guarantor_rw_sa`` derives it from ``guarantor_entity_type`` via
    ENTITY_TYPE_TO_SA_CLASS, exactly as the CRM processor does.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["EXP001"],
            "pd": [0.05],
            "lgd": [0.45],
            "ead_final": [EAD],
            "maturity": [2.5],
            "exposure_class": ["CORPORATE"],
            "rwa": [BORROWER_RWA],
            "risk_weight": [BORROWER_RW],
            "guaranteed_portion": [EAD],
            "unguaranteed_portion": [0.0],
            "guarantor_entity_type": [guarantor_entity_type],
            "guarantor_cqs": [guarantor_cqs],
            "guarantor_approach": ["sa"],
            "guarantor_pd": [None],
        },
        schema_overrides={
            "guarantor_cqs": pl.Int8,
            "guarantor_pd": pl.Float64,
        },
    )


class TestInternationalOrganisationGuarantor:
    """(a) IO guarantor → 0% (Art. 118). Pre-fix: null guarantor_rw (otherwise-branch)."""

    def test_io_guarantor_substitutes_at_zero_rw_crr(self, crr_config: CalculationConfig) -> None:
        """CRR: an international-organisation guarantor substitutes at 0% RW.

        entity_type "international_org" → guarantor_exposure_class
        "international_organisation", which today falls to ``.otherwise(null)``
        in _compute_guarantor_rw_sa → guarantee silently dropped.

        Arrange: fully-guaranteed FIRB corporate exposure (borrower RW 0.80),
                 IO guarantor, no CQS, guarantor_approach="sa".
        Act:     apply_guarantee_substitution under CRR.
        Assert:  guarantor_rw = 0.0 (Art. 118), rwa = 0.0,
                 guarantee_status = "SA_RW_SUBSTITUTION".

        PRE-FIX: guarantor_rw = None, rwa = 800,000 (borrower RWA),
        status GUARANTEE_NOT_APPLIED_NON_BENEFICIAL → FAILS.
        """
        lf = _guaranteed_irb_frame(guarantor_entity_type="international_org", guarantor_cqs=None)

        result = apply_guarantee_substitution(lf, crr_config).collect()

        actual_rw = result["guarantor_rw"][0]
        assert actual_rw == pytest.approx(EXPECTED_IO_RW, abs=1e-12), (
            f"IO guarantor (CRR) should substitute at 0% (Art. 118). Got {actual_rw!r} "
            f"— None means 'international_organisation' still falls to "
            f".otherwise(null) in _compute_guarantor_rw_sa."
        )
        assert result["rwa"][0] == pytest.approx(0.0, abs=1e-9)
        assert result["guarantee_status"][0] == "SA_RW_SUBSTITUTION"

    def test_io_guarantor_substitutes_at_zero_rw_b31(self, b31_config: CalculationConfig) -> None:
        """B31: the IO 0% closure is framework-identical (PS1/26 Art. 118).

        Arrange: same frame as the CRR arm.
        Act:     apply_guarantee_substitution under Basel 3.1.
        Assert:  guarantor_rw = 0.0, rwa = 0.0.

        PRE-FIX: guarantor_rw = None (same otherwise-branch) → FAILS.
        """
        lf = _guaranteed_irb_frame(guarantor_entity_type="international_org", guarantor_cqs=None)

        result = apply_guarantee_substitution(lf, b31_config).collect()

        actual_rw = result["guarantor_rw"][0]
        assert actual_rw == pytest.approx(EXPECTED_IO_RW, abs=1e-12), (
            f"IO guarantor (B31) should substitute at 0% (PS1/26 Art. 118). Got {actual_rw!r}."
        )
        assert result["rwa"][0] == pytest.approx(0.0, abs=1e-9)


class TestNamedMdbGuarantor:
    """(b) Named-MDB guarantor → 0% (Art. 117(2)). Pre-fix: institution misroute."""

    def test_named_mdb_guarantor_substitutes_at_zero_rw(
        self, crr_config: CalculationConfig
    ) -> None:
        """CRR: a named-MDB guarantor substitutes at 0% RW (Art. 117(2)).

        The named-MDB designation is carried by entity_type="mdb_named" (the
        engine convention — see ENTITY_TYPE_TO_SA_CLASS and the SA-side branch
        ``(gec == "mdb") & (guarantor_entity_type == "mdb_named")``), which maps
        to class "mdb". Today the IRB chain routes class "mdb" through the
        INSTITUTION branch, so an unrated named MDB lands on the CRR unrated
        institution fallback (100%) instead of 0%.

        Arrange: fully-guaranteed FIRB corporate exposure (borrower RW 0.80),
                 guarantor entity_type="mdb_named", no CQS.
        Act:     apply_guarantee_substitution under CRR.
        Assert:  guarantor_rw = 0.0 (MDB_NAMED_ZERO_RW), rwa = 0.0,
                 guarantee_status = "SA_RW_SUBSTITUTION".

        PRE-FIX: guarantor_rw = 1.00 (INSTITUTION_RISK_WEIGHTS_CRR[UNRATED]
        via the institution misroute) ≥ borrower RW 0.80 → non-beneficial,
        rwa = 800,000, status GUARANTEE_NOT_APPLIED_NON_BENEFICIAL → FAILS.
        """
        lf = _guaranteed_irb_frame(guarantor_entity_type="mdb_named", guarantor_cqs=None)

        result = apply_guarantee_substitution(lf, crr_config).collect()

        actual_rw = result["guarantor_rw"][0]
        assert actual_rw == pytest.approx(EXPECTED_NAMED_MDB_RW, abs=1e-12), (
            f"Named-MDB guarantor should substitute at 0% (Art. 117(2), "
            f"MDB_NAMED_ZERO_RW). Got {actual_rw!r} — 1.00 means class 'mdb' is "
            f"still routed through the institution branch (unrated CRR fallback) "
            f"with no named-MDB carve-out."
        )
        assert result["rwa"][0] == pytest.approx(0.0, abs=1e-9)
        assert result["guarantee_status"][0] == "SA_RW_SUBSTITUTION"


class TestNonNamedMdbGuarantorRegimeSplit:
    """(c) Non-named MDB guarantor — Table 2B under B31, institutions under CRR.

    Revised by P1.253. The original version of this class pinned the CRR arm at
    Table 2B CQS 2 = 30%, which CRR Art. 117(1) refutes: a non-named MDB "shall
    be treated in the same manner as exposures to institutions" and CRR has no
    MDB table, so the CRR arm belongs on Art. 120 Table 3 (CQS 2 = 50%). The
    Table-2B adoption that this class exists to pin is now asserted on the B31
    arm, where an unrated MDB discriminates cleanly: Table 2B's 50% unrated row
    versus the institution ECRA/SCRA dispatch (Grade-C fallback 150%).
    """

    def test_rated_mdb_cqs2_guarantor_crr_substitutes_at_institution_table_3(
        self, crr_config: CalculationConfig
    ) -> None:
        """CRR: a rated non-named MDB guarantor (CQS 2) substitutes at 50%.

        CRR Art. 117(1): non-named MDBs take the institution treatment — Art. 120
        Table 3 CQS 2 = 50%. The PS1/26 Table 2B 30% does not apply under CRR.

        Arrange: fully-guaranteed FIRB corporate exposure (borrower RW 0.80),
                 guarantor entity_type="mdb", CQS 2.
        Act:     apply_guarantee_substitution under CRR.
        Assert:  guarantor_rw = 0.50, rwa = 500,000,
                 guarantee_status = "SA_RW_SUBSTITUTION".

        Pre-P1.253: guarantor_rw = 0.30 → rwa = 300,000 (200,000 of RWA relief
        Art. 117(1) does not permit).
        """
        lf = _guaranteed_irb_frame(guarantor_entity_type="mdb", guarantor_cqs=2)

        result = apply_guarantee_substitution(lf, crr_config).collect()

        actual_rw = result["guarantor_rw"][0]
        assert actual_rw == pytest.approx(EXPECTED_CRR_MDB_CQS2_RW, rel=1e-9), (
            f"Rated non-named MDB guarantor CQS 2 should substitute at "
            f"{EXPECTED_CRR_MDB_CQS2_RW:.2f} under CRR (Art. 117(1) institution "
            f"treatment → Art. 120 Table 3). Got {actual_rw!r} — 0.30 means the "
            f"PS1/26-only Table 2B is still applied under CRR."
        )
        assert result["rwa"][0] == pytest.approx(EAD * EXPECTED_CRR_MDB_CQS2_RW, rel=1e-9)
        assert result["guarantee_status"][0] == "SA_RW_SUBSTITUTION"

    def test_unrated_mdb_guarantor_b31_substitutes_at_table_2b_value(
        self, b31_config: CalculationConfig
    ) -> None:
        """B31: an unrated non-named MDB guarantor substitutes at Table 2B's 50%.

        PS1/26 Art. 117(1)(b): the dedicated MDB Table 2B unrated row is 50%.
        This is the band that proves the MDB branch (not the institution branch)
        prices the row: the institution ECRA path would send a null-CQS guarantor
        to the SCRA dispatch, whose Grade-C fallback is 150% — above the 0.80
        borrower RW, so the guarantee would be dropped as non-beneficial.

        Arrange: fully-guaranteed FIRB corporate exposure (borrower RW 0.80),
                 guarantor entity_type="mdb", no CQS, no SCRA grade.
        Act:     apply_guarantee_substitution under Basel 3.1.
        Assert:  guarantor_rw = 0.50, rwa = 500,000,
                 guarantee_status = "SA_RW_SUBSTITUTION".
        """
        lf = _guaranteed_irb_frame(guarantor_entity_type="mdb", guarantor_cqs=None)

        result = apply_guarantee_substitution(lf, b31_config).collect()

        actual_rw = result["guarantor_rw"][0]
        assert actual_rw == pytest.approx(EXPECTED_B31_MDB_UNRATED_RW, rel=1e-9), (
            f"Unrated non-named MDB guarantor should substitute at "
            f"{EXPECTED_B31_MDB_UNRATED_RW:.2f} under B31 (PS1/26 Table 2B unrated "
            f"row). Got {actual_rw!r} — 1.50 means the row was priced by the "
            f"institution SCRA dispatch instead of Table 2B."
        )
        assert result["rwa"][0] == pytest.approx(EAD * EXPECTED_B31_MDB_UNRATED_RW, rel=1e-9)
        assert result["guarantee_status"][0] == "SA_RW_SUBSTITUTION"
