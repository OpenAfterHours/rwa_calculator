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
    (c) rated non-named MDB guarantors — class "mdb" also routes through the
        INSTITUTION branch (CRR Art. 120 Table 3: CQS 2 = 50%) instead of the
        MDB Table 2B value adopted by the SA-side reference implementation
        (MDB_RISK_WEIGHTS_TABLE_2B: CQS 2 = 30%).

    The SA-side twin (engine/sa/namespace.py::_build_guarantor_rw_expr) already
    has all three branches (IO 0% → named MDB 0% → MDB Table 2B, ahead of the
    institution branch); the shared guarantor RW expression closes them on the
    IRB path. Each test pins the post-fix value and FAILS pre-fix.

    NOTE on framework arm: (c) is pinned on the CRR arm deliberately — under B31
    the institution-ECRA CQS 2 weight (30%) coincides with Table 2B CQS 2 (30%),
    so a B31 arm would not discriminate the misroute. The Table 2B dict is
    framework-shared, so the CRR pin covers the adoption of the table itself.

References:
    - CRR Art. 118 / PRA PS1/26 Art. 118: international organisations — 0%
    - CRR Art. 117(2): named MDBs — 0% unconditional
    - CRR Art. 117(1) Table 2B (MDB_RISK_WEIGHTS_TABLE_2B): rated MDB CQS 2 = 30%
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
from rwa_calc.engine.sa.crr_risk_weight_tables import MDB_RISK_WEIGHTS_TABLE_2B

# ---------------------------------------------------------------------------
# Frame constants
# ---------------------------------------------------------------------------

EAD: float = 1_000_000.0
BORROWER_RW: float = 0.80  # above every post-fix guarantor RW below → beneficial
BORROWER_RWA: float = BORROWER_RW * EAD

# Post-fix expected guarantor risk weights (hand-pinned from the data tables)
EXPECTED_IO_RW: float = 0.0  # Art. 118: international organisations 0%
EXPECTED_NAMED_MDB_RW: float = 0.0  # Art. 117(2): named MDBs 0% (MDB_NAMED_ZERO_RW)
EXPECTED_MDB_CQS2_RW: float = float(MDB_RISK_WEIGHTS_TABLE_2B[CQS.CQS2])  # 0.30


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


class TestRatedMdbGuarantorTable2B:
    """(c) Rated non-named MDB guarantor → Table 2B. Pre-fix: institution misroute."""

    def test_rated_mdb_cqs2_guarantor_substitutes_at_table_2b_value(
        self, crr_config: CalculationConfig
    ) -> None:
        """CRR: a rated non-named MDB guarantor (CQS 2) substitutes at the
        MDB Table 2B value — 30% (MDB_RISK_WEIGHTS_TABLE_2B[CQS2]).

        Today class "mdb" routes through the INSTITUTION branch: CRR Art. 120
        Table 3 CQS 2 = 50%. The SA-side reference implementation prices MDB
        guarantors from Table 2B ahead of the institution branch; the shared
        expression must do the same on the IRB path.

        (CRR arm only — under B31 the institution-ECRA CQS 2 weight coincides
        with Table 2B CQS 2 at 30%, so a B31 arm would not discriminate.)

        Arrange: fully-guaranteed FIRB corporate exposure (borrower RW 0.80),
                 guarantor entity_type="mdb", CQS 2.
        Act:     apply_guarantee_substitution under CRR.
        Assert:  guarantor_rw = 0.30, rwa = 300,000,
                 guarantee_status = "SA_RW_SUBSTITUTION".

        PRE-FIX: guarantor_rw = 0.50 (INSTITUTION_RISK_WEIGHTS_CRR[CQS2] via the
        institution misroute) → rwa = 500,000 → FAILS on both pins.
        """
        lf = _guaranteed_irb_frame(guarantor_entity_type="mdb", guarantor_cqs=2)

        result = apply_guarantee_substitution(lf, crr_config).collect()

        actual_rw = result["guarantor_rw"][0]
        assert actual_rw == pytest.approx(EXPECTED_MDB_CQS2_RW, rel=1e-9), (
            f"Rated non-named MDB guarantor CQS 2 should substitute at "
            f"{EXPECTED_MDB_CQS2_RW:.2f} (MDB_RISK_WEIGHTS_TABLE_2B Table 2B). "
            f"Got {actual_rw!r} — 0.50 means class 'mdb' is still priced from "
            f"INSTITUTION_RISK_WEIGHTS_CRR (Art. 120 Table 3) instead of Table 2B."
        )
        assert result["rwa"][0] == pytest.approx(EAD * EXPECTED_MDB_CQS2_RW, rel=1e-9)
        assert result["guarantee_status"][0] == "SA_RW_SUBSTITUTION"
