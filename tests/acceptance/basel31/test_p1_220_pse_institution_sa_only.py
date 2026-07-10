"""
P1.220 — Institution-typed PSE stays SA-only under Basel 3.1 (quasi-sovereign
class), not F-IRB.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor
        -> SA/IRB Calculator -> OutputAggregator

Key assertion:
    ``entity_type="pse_institution"`` maps to SA exposure class PSE and IRB
    exposure class INSTITUTION (``packs/common.py`` entity-type map). Under
    CRR, an institution F-IRB model permission legitimately routes this
    counterparty to F-IRB (Art. 150(1) PPU election). Under Basel 3.1,
    PS1/26 Art. 147(3)(c)-(e) assigns regional governments, local
    authorities and public sector entities to the central-government /
    quasi-sovereign exposure class (Art. 147(2)(a)) UNCONDITIONALLY — no
    "risk weight of 0%" qualifier (that qualifier binds only to
    Art. 147(3)(g) international organisations). Art. 147A(1)(a) makes that
    class Standardised-Approach ONLY.

    Pre-fix (current engine bug):
        ``data/schemas.py`` ``B31_SOVEREIGN_LIKE_ENTITY_TYPES`` (the SA-only
        backstop keyed by ``engine/stages/classify/approach.py``
        ``_apply_b31_approach_restrictions``) deliberately excludes
        ``pse_institution`` / ``rgla_institution``, so an institution F-IRB
        model permission is wrongly honoured for this PSE and it routes to
        F-IRB (RW ~= 26.33%, understating the mandatory SA weight of 50%).

    Post-fix expected (B31):
        approach            = "standardised" (ApproachType.SA.value)
        exposure_class       = "pse" (ExposureClass.PSE.value)
        exposure_class_irb   = "institution" (unchanged)
        risk_weight          = 0.50 (Art. 116(1) Table 2, CQS 2, PSE
                                      sovereign-derived, unrated own-CQS)
        ead_final            = 10,000,000.0
        rwa_final            = 5,000,000.0 (EAD x RW x SF, SF=1.0)

References:
    - PS1/26 Art. 147(3)(c)-(e) read with Art. 147A(1)(a) (quasi-sovereign
      class assignment, unconditional; class is SA-only). See the
      orchestrator PDF-verification addendum in the P1.220 scenario
      proposal — this SUPERSEDES the "0%-RW qualifier applies to the whole
      quasi-sovereign list" reading in the repo's basel31 skill / specs.
    - CRR/PS1/26 Art. 116(1) Table 2 (PSE sovereign-derived SA weight).
    - PS1/26 Art. 160(1) (institution PD floor); Art. 161(1)(aa) (F-IRB
      supervisory LGD) — F-IRB parameters for the "before" state only.
    - src/rwa_calc/data/schemas.py: B31_SOVEREIGN_LIKE_ENTITY_TYPES (bug
      site: excludes rgla_institution / pse_institution).
    - src/rwa_calc/engine/stages/classify/approach.py:
      _apply_b31_approach_restrictions (b31_sa_only must fire for these
      entity types under the approach_restrictions_b31_applicable Feature).
    - src/rwa_calc/rulebook/packs/crr.py: pse_risk_weights_sovereign_derived
      (CQS2 -> 0.50), inherited under B31 (not overridden in b31.py).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import FACILITY_MAPPING_SCHEMA, LENDING_MAPPING_SCHEMA
from rwa_calc.domain.enums import ApproachType, ExposureClass
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.p1_220.p1_220 import (
    EXPECTED_EAD,
    EXPECTED_EXPOSURE_CLASS,
    EXPECTED_EXPOSURE_CLASS_IRB,
    EXPECTED_RISK_WEIGHT,
    EXPECTED_RWA,
    LOAN_REF,
)
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Fixture path
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_220"


# ---------------------------------------------------------------------------
# Config factory
# ---------------------------------------------------------------------------


def _b31_irb_config() -> CalculationConfig:
    """Basel 3.1 IRB config, post go-live (2027-01-04).

    PermissionMode.IRB activates model-level IRB permissions. The
    M-INST-FIRB model permission row grants foundation_irb for the
    "institution" exposure class, the permission the pre-fix engine
    wrongly honours for this institution-typed PSE.
    """
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 1, 4),
        permission_mode=PermissionMode.IRB,
    )


# ---------------------------------------------------------------------------
# Bundle builder
# ---------------------------------------------------------------------------


def _build_bundle() -> RawDataBundle:
    """
    Construct a RawDataBundle from the P1.220 parquets.

    Four parquets are loaded:
      - counterparty.parquet: CP-PSE-INST-01 (entity_type=pse_institution,
        GB, non-FSE, sovereign_cqs=2)
      - loan.parquet:         LN-PSE-INST-01 (GBP 10,000,000 senior term
        loan, no modelled LGD, ~2.5y maturity)
      - rating.parquet:       internal rating, pd=0.001, model_id=
        M-INST-FIRB, cqs=None (no external ECAI assessment)
      - model_permission.parquet: M-INST-FIRB -> institution/foundation_irb

    facility_mappings and lending_mappings are empty frames — the loan
    links directly to the counterparty via counterparty_reference, no
    facility hierarchy is exercised.
    """
    return make_raw_bundle(
        loans=pl.scan_parquet(_FIXTURES_DIR / "loan.parquet"),
        counterparties=pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet"),
        ratings=pl.scan_parquet(_FIXTURES_DIR / "rating.parquet"),
        model_permissions=pl.scan_parquet(_FIXTURES_DIR / "model_permission.parquet"),
        facility_mappings=pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
        lending_mappings=pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA)),
    )


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------


def _run_pipeline(config: CalculationConfig) -> pl.DataFrame:
    """
    Run the P1.220 fixtures through the credit risk pipeline and return the
    single-row aggregated results DataFrame for LN-PSE-INST-01.

    Post-fix, the row is SA-routed and surfaces in the aggregated
    ``results.results`` frame (not ``irb_results``) — this scenario does
    not assume which result set carries the row, it locates it by
    ``exposure_reference`` in the final aggregated bundle.
    """
    bundle = _build_bundle()
    results = PipelineOrchestrator().run_with_data(bundle, config)
    df = results.results.collect()
    rows = df.filter(pl.col("exposure_reference") == LOAN_REF)
    assert len(rows) == 1, (
        f"Expected exactly 1 aggregated row for {LOAN_REF!r}, got {len(rows)}. "
        f"All exposure_references: {df['exposure_reference'].to_list()}"
    )
    return rows


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestP1220PseInstitutionSaOnly:
    """
    P1.220: institution-typed PSE (pse_institution) with an institution
    F-IRB model permission must route to SA under Basel 3.1, not F-IRB.

    PRE-FIX (today): approach="foundation_irb", risk_weight~=0.2633,
        rwa_final does not equal the mandatory SA figure -> tests FAIL.
    POST-FIX: approach="standardised", risk_weight=0.50, ead_final=
        10,000,000.0, rwa_final=5,000,000.0 -> tests pass.
    """

    @pytest.fixture(scope="class")
    def b31_result_row(self) -> dict:
        """
        Basel 3.1 aggregated result row for P1.220's LN-PSE-INST-01.

        Arrange: P1.220 parquets — institution-typed PSE (pse_institution),
                 GB, sovereign_cqs=2, non-FSE, GBP 10,000,000 drawn,
                 internal PD=0.001, model_id=M-INST-FIRB granting
                 institution F-IRB, reporting_date=2027-01-04.
        Act:     PipelineOrchestrator with CalculationConfig.basel_3_1(),
                 PermissionMode.IRB.
        Return:  Single-row dict from the aggregated results frame.
        """
        return _run_pipeline(_b31_irb_config()).row(0, named=True)

    # ------------------------------------------------------------------
    # PRIMARY ASSERTION — FAILS pre-fix
    # ------------------------------------------------------------------

    def test_approach_is_standardised(self, b31_result_row: dict) -> None:
        """
        P1.220 PRIMARY: institution-typed PSE must route to SA under B31,
        not F-IRB, even though its model permission grants institution
        F-IRB.

        Arrange: B31 IRB config, pse_institution counterparty with an
                 institution F-IRB model permission attached via internal
                 rating model_id.
        Act:     Aggregated result row for LN-PSE-INST-01.
        Assert:  approach == "standardised" (ApproachType.SA.value).

        PRE-FIX (today): approach = "foundation_irb" -> test FAILS.
        POST-FIX:        approach = "standardised"   -> test passes.
        """
        # Arrange / Act — see fixture
        actual_approach = b31_result_row["approach"]

        # Assert — FAILS pre-fix (engine returns "foundation_irb")
        assert actual_approach == ApproachType.SA.value, (
            f"P1.220: institution-typed PSE (pse_institution) approach should be "
            f"{ApproachType.SA.value!r} (PS1/26 Art. 147(3)(c)-(e) read with "
            f"Art. 147A(1)(a): quasi-sovereign class is SA-only, unconditionally — "
            f"no 0%-RW qualifier for PSEs). Got {actual_approach!r}. "
            f"Pre-fix, the engine honours the institution F-IRB model permission "
            f"because B31_SOVEREIGN_LIKE_ENTITY_TYPES (data/schemas.py) excludes "
            f"pse_institution — fix _apply_b31_approach_restrictions "
            f"(engine/stages/classify/approach.py) to force SA for this entity type."
        )

    # ------------------------------------------------------------------
    # SUPPORTING ASSERTIONS — exposure-class preservation
    # ------------------------------------------------------------------

    def test_sa_exposure_class_preserved(self, b31_result_row: dict) -> None:
        """
        P1.220: exposure_class stays "pse" — _align_irb_exposure_class does
        not rewrite it to the IRB class because the approach is not IRB.

        Assert: exposure_class == "pse" (ExposureClass.PSE.value).
                exposure_class_irb == "institution" (unchanged).
        """
        assert ExposureClass.PSE.value == EXPECTED_EXPOSURE_CLASS
        assert b31_result_row["exposure_class"] == EXPECTED_EXPOSURE_CLASS, (
            f"P1.220: exposure_class should stay {EXPECTED_EXPOSURE_CLASS!r} "
            f"(SA class for pse_institution), not be rewritten to the IRB class. "
            f"Got {b31_result_row['exposure_class']!r}."
        )
        assert b31_result_row["exposure_class_irb"] == EXPECTED_EXPOSURE_CLASS_IRB, (
            f"P1.220: exposure_class_irb should remain "
            f"{EXPECTED_EXPOSURE_CLASS_IRB!r} (unchanged dual-class mapping). "
            f"Got {b31_result_row['exposure_class_irb']!r}."
        )

    # ------------------------------------------------------------------
    # SUPPORTING ASSERTIONS — SA risk weight / EAD / RWA
    # ------------------------------------------------------------------

    def test_sa_risk_weight_is_pse_sovereign_derived_cqs2(
        self, b31_result_row: dict
    ) -> None:
        """
        P1.220: SA risk weight = 0.50 (Art. 116(1) Table 2, CQS 2,
        PSE sovereign-derived, unrated own-CQS branch).

        PRE-FIX (today): risk_weight ~= 0.2633 (F-IRB modelled) -> FAILS.
        POST-FIX:        risk_weight = 0.50                     -> passes.
        """
        actual_rw = b31_result_row["risk_weight"]
        assert actual_rw == pytest.approx(EXPECTED_RISK_WEIGHT, rel=1e-9), (
            f"P1.220: risk_weight should be {EXPECTED_RISK_WEIGHT:.2f} "
            f"(CRR/PS1/26 Art. 116(1) Table 2, PSE sovereign-derived CQS 2). "
            f"Got {actual_rw:.6f}."
        )

    def test_ead_final_matches_drawn_amount(self, b31_result_row: dict) -> None:
        """P1.220: ead_final = drawn_amount (10,000,000.0); no CCF/CRM applies."""
        actual_ead = b31_result_row["ead_final"]
        assert actual_ead == pytest.approx(EXPECTED_EAD, rel=1e-9), (
            f"P1.220: ead_final should be {EXPECTED_EAD:,.2f}. Got {actual_ead:,.2f}."
        )

    def test_rwa_final_is_sa_mandatory_weight(self, b31_result_row: dict) -> None:
        """
        P1.220: rwa_final = EAD x SA RW x SF = 10,000,000 x 0.50 x 1.0 = 5,000,000.

        PRE-FIX (today): rwa_final reflects the F-IRB-routed (and
        output-floor-blended) figure, not the mandatory SA RWA -> FAILS.
        POST-FIX:        rwa_final = 5,000,000.0                -> passes.
        """
        actual_rwa = b31_result_row["rwa_final"]
        assert actual_rwa == pytest.approx(EXPECTED_RWA, rel=1e-9), (
            f"P1.220: rwa_final should be {EXPECTED_RWA:,.2f} "
            f"(EAD 10,000,000 x mandatory SA RW 0.50). Got {actual_rwa:,.2f}. "
            f"The mandatory SA weight (50%) sits well above the F-IRB modelled "
            f"weight (~26.33%) that the pre-fix engine wrongly applies — the bug "
            f"this scenario evidences understates capital by ~2.37m."
        )
