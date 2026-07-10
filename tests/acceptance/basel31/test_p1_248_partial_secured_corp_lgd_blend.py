"""
P1.248 — Basel 3.1 A-IRB partially-secured corporate LGD-floor blend.

Validates that a partially-secured CORPORATE A-IRB exposure receives the
Art. 164(4)(c)-style EAD-weighted-average LGD floor blend (PS1/26 Art. 161(5) /
BCBS CRE32.17) across its secured (commercial real estate) and unsecured
portions, rather than a single flat floor.

Defect under test (``engine/irb/formulas.py:319-405``,
``_lgd_floor_blended_expression``): the EAD-weighted blend eligibility gate
(``is_blended_eligible``, line 402) is restricted to ``retail_other`` /
``retail_qrre`` only. A partially-secured CORPORATE A-IRB exposure never
reaches the blend and falls through to the flat single-collateral-type /
flat-unsecured floor path (``_lgd_floor_expression_with_collateral`` /
``_lgd_floor_expression``), which for this fixture shape (numeric
``crm_alloc_*`` / ``total_collateral_for_lgd`` columns only, no raw
``collateral_type`` string column on the exposures frame) collapses to the
flat 25% unsecured floor — collateral entirely ignored.

Scenario: one corporate A-IRB exposure (GBP 1,000,000 drawn term loan, own
LGD=0.15) partially secured by commercial real estate collateral. After the
Art. 230(2) flat 40% non-financial haircut, the recognised secured amount is
~GBP 400,000.00 (~40% of EAD); the remaining ~60% is unsecured.

Hand-calculation (Basel 3.1, CalculationConfig.basel_3_1(),
permission_mode=IRB — see tests/fixtures/p1_248/p1_248.py module docstring
"Hand-calculation" / "Verification" for the full derivation):
    EAD           = 1,000,000.00
    PD_floored    = max(0.01, 0.0005) = 0.01     (Art. 163(1)/CRE30.55)
    LGD_floored   = (400,000 x 0.10 + 600,000 x 0.25) / 1,000,000 = 0.19
                    (PRIMARY -- distinguishes the fix from the pre-fix 0.25
                    flat unsecured floor, which ignores the collateral)
    correlation   = 0.192783679165516                (Art. 153(1), corporate)
    maturity_adj  = 1.2598095009238282                (M=2.5, via override)
    k             = 0.024751808867656228              (engine convention:
                    k EXCLUDES the maturity adjustment)
    risk_weight   = k x 12.5 x maturity_adj = 0.38978204970654967
    rwa           = risk_weight x EAD       = 389,782.05
    expected_loss = PD_floored x LGD_floored x EAD = 1,900.00

Pre-fix (bug) figures -- flat unsecured floor, collateral ignored (confirmed
by a direct PipelineOrchestrator run against this exact fixture; see
tests/fixtures/p1_248/p1_248.py "Verification"):
    lgd_floored=0.25, k=0.03256816961587036,
    risk_weight=0.5128711188721529, rwa=512,871.12, expected_loss=2,500.00

References:
    - PS1/26 Art. 161(5): A-IRB unsecured corporate LGD floor 25% /
      collateral-type LGDS floors (CRE unsecured floor 10%).
    - BCBS CRE32.17: partially-secured exposure-weighted-average LGD floor.
    - PS1/26 Art. 230: Foundation Collateral Method Art. 231 sequential
      waterfall (crm_alloc_* / total_collateral_for_lgd), reused by the fix.
    - PS1/26 Art. 163(1)/CRE30.55: corporate PD floor 0.05%.
    - PS1/26 Art. 153-154: IRB K, correlation, maturity adjustment.
    - src/rwa_calc/engine/irb/formulas.py:301-315 (bug fallback), :319-405
      (blend, gate at :402, LGDU at :388-393).
    - src/rwa_calc/rulebook/packs/b31.py:157-179 (lgd_floors FormulaParams).
    - tests/fixtures/p1_248/p1_248.py: fixture constants + full hand-calc.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl
import pytest

from tests.fixtures.p1_248.p1_248 import (
    EXPECTED_EAD_FINAL,
    EXPECTED_EXPECTED_LOSS,
    EXPECTED_K,
    EXPECTED_LGD_FLOORED,
    EXPECTED_RISK_WEIGHT,
    EXPECTED_RWA,
    LOAN_REF,
)
from tests.fixtures.raw_bundle import make_raw_bundle

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import AggregatedResultBundle
    from rwa_calc.contracts.config import CalculationConfig

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p1_248"

# B31 effective date (PRA PS1/26 goes live 2027-01-01) -- keeps the regime's
# date-effective schedules on their post-2027 values. The loan's
# effective_maturity=2.5 is set explicitly on the fixture (highest-priority M
# override), so this reporting_date does not affect the maturity/correlation
# hand-calc.
_REPORTING_DATE = __import__("datetime").date(2027, 1, 1)

# Relative tolerance for downstream k/risk_weight/rwa (normal_cdf/normal_ppf
# float precision) per the scenario proposal's closing note.
_REL_TOL = 1e-4


# ---------------------------------------------------------------------------
# Pipeline runner -- module-scoped so the pipeline runs once for all tests
# ---------------------------------------------------------------------------


def _run_pipeline_p1248() -> AggregatedResultBundle:
    """
    Run the Basel 3.1 A-IRB pipeline with the P1.248 scenario inputs.

    Loads counterparty, loan, rating, model_permission, and collateral from
    the p1_248 parquet fixtures. Empty facilities, facility_mappings, and
    lending_mappings are supplied with the minimum schema the loader needs
    (mirrors tests/acceptance/basel31/test_p1_151_art_161_purchased_receivables_lgd.py).

    Returns the AggregatedResultBundle from PipelineOrchestrator.run_with_data().
    """
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.domain.enums import PermissionMode
    from rwa_calc.engine.pipeline import PipelineOrchestrator

    lending_mappings = pl.LazyFrame(
        schema={
            "parent_counterparty_reference": pl.String,
            "child_counterparty_reference": pl.String,
        }
    )
    facility_mappings = pl.LazyFrame(
        schema={
            "parent_facility_reference": pl.String,
            "child_reference": pl.String,
            "child_type": pl.String,
        }
    )
    facilities = pl.LazyFrame(
        schema={
            "facility_reference": pl.String,
            "counterparty_reference": pl.String,
        }
    )

    bundle = make_raw_bundle(
        facilities=facilities,
        loans=pl.scan_parquet(_FIXTURES_DIR / "loan.parquet"),
        counterparties=pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet"),
        facility_mappings=facility_mappings,
        lending_mappings=lending_mappings,
        ratings=pl.scan_parquet(_FIXTURES_DIR / "rating.parquet"),
        model_permissions=pl.scan_parquet(_FIXTURES_DIR / "model_permission.parquet"),
        collateral=pl.scan_parquet(_FIXTURES_DIR / "collateral.parquet"),
    )
    config: CalculationConfig = CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.IRB,
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


def _find_irb_row(results: AggregatedResultBundle, loan_ref: str) -> dict:
    """
    Return the single IRB result row for *loan_ref*.

    Asserts exactly one row matches -- fails with a descriptive message if
    the exposure is missing (fixture or pipeline routing issue).
    """
    assert results.irb_results is not None, "irb_results must not be None for A-IRB scenario"
    df = results.irb_results.collect()
    rows = df.filter(pl.col("exposure_reference") == loan_ref).to_dicts()
    assert len(rows) == 1, (
        f"Expected exactly 1 IRB result row for {loan_ref!r}, got {len(rows)}. "
        f"All exposure_references: {df['exposure_reference'].to_list()}"
    )
    return rows[0]


# ---------------------------------------------------------------------------
# P1.248 acceptance test class
# ---------------------------------------------------------------------------


class TestP1248PartialSecuredCorpLgdBlend:
    """
    P1.248: partially-secured corporate A-IRB exposure must receive the
    EAD-weighted LGD-floor blend (PS1/26 Art. 161(5)/BCBS CRE32.17), not the
    flat 25% unsecured floor with collateral ignored.
    """

    @pytest.fixture(scope="class")
    def pipeline_results(self) -> AggregatedResultBundle:
        """Run the B31 A-IRB pipeline once and return AggregatedResultBundle."""
        return _run_pipeline_p1248()

    @pytest.fixture(scope="class")
    def loan_row(self, pipeline_results: AggregatedResultBundle) -> dict:
        """Result dict for LN-CORP-AIRB-P1248."""
        return _find_irb_row(pipeline_results, LOAN_REF)

    # =========================================================================
    # PRIMARY assertion -- lgd_floored == 0.19 exactly (blend, not flat floor)
    # =========================================================================

    def test_p1_248_lgd_floored_blended_exact(self, loan_row: dict) -> None:
        """
        P1.248 PRIMARY: lgd_floored == 0.19 exactly (EAD-weighted blend).

        Distinguishes the fix (0.19 -- Art. 161(5)/CRE32.17 blend across the
        secured CRE portion at floor 0.10 and the unsecured portion at floor
        0.25) from the pre-fix flat unsecured floor (0.25 -- collateral
        entirely ignored because corporate is excluded from the blend
        eligibility gate, formulas.py:402).

        Arrange: corporate A-IRB, own LGD=0.15, ~40% secured by commercial_re.
        Act:     Basel 3.1 A-IRB pipeline.
        Assert:  lgd_floored == 0.19 (abs tol 1e-9).

        Pre-fix: lgd_floored == 0.25 -> AssertionError.
        """
        lgd_floored = loan_row["lgd_floored"]

        assert lgd_floored == pytest.approx(EXPECTED_LGD_FLOORED, abs=1e-9), (
            f"P1.248 Art. 161(5)/CRE32.17: expected lgd_floored="
            f"{EXPECTED_LGD_FLOORED} (EAD-weighted blend: 400,000x0.10 + "
            f"600,000x0.25, all / 1,000,000), got {lgd_floored}. "
            f"If == 0.25: the blend eligibility gate still excludes "
            f"'corporate' (formulas.py:402) -- collateral is being ignored "
            f"and the flat unsecured floor applied instead."
        )

    # =========================================================================
    # Downstream k / risk_weight / rwa / expected_loss
    # =========================================================================

    def test_p1_248_k_matches_hand_calc(self, loan_row: dict) -> None:
        """
        P1.248: k ~= 0.024751808867656228 (engine convention -- k excludes
        the maturity adjustment; MA applied separately at risk_weight).

        Arrange: same as PRIMARY test.
        Act:     Basel 3.1 A-IRB pipeline.
        Assert:  k ~= EXPECTED_K (rel tol 1e-4).

        Pre-fix: k ~= 0.03256816961587036 (derived from lgd_floored=0.25).
        """
        k = loan_row["k"]

        assert k == pytest.approx(EXPECTED_K, rel=_REL_TOL), (
            f"P1.248: expected k~={EXPECTED_K:.8f} "
            f"(derived from lgd_floored=0.19), got {k:.8f}."
        )

    def test_p1_248_risk_weight_and_rwa_match_hand_calc(self, loan_row: dict) -> None:
        """
        P1.248: risk_weight ~= 0.38978204970654967, rwa/rwa_final ~= 389,782.05.

        Arrange: same as PRIMARY test.
        Act:     Basel 3.1 A-IRB pipeline.
        Assert:  risk_weight ~= EXPECTED_RISK_WEIGHT, rwa ~= EXPECTED_RWA,
                  rwa_final ~= EXPECTED_RWA (rel tol 1e-4).

        Pre-fix: risk_weight ~= 0.5128711188721529, rwa ~= 512,871.12 --
        the current engine over-floors the exposure to the flat 25%
        unsecured floor, ignoring the CRE collateral, overstating RWA by
        ~£123,089 (+31.6%).
        """
        risk_weight = loan_row["risk_weight"]
        rwa = loan_row["rwa"]
        rwa_final = loan_row["rwa_final"]

        assert risk_weight == pytest.approx(EXPECTED_RISK_WEIGHT, rel=_REL_TOL), (
            f"P1.248: expected risk_weight~={EXPECTED_RISK_WEIGHT:.8f} "
            f"(k x 12.5 x maturity_adjustment, lgd_floored=0.19), "
            f"got {risk_weight:.8f}."
        )
        assert rwa == pytest.approx(EXPECTED_RWA, rel=_REL_TOL), (
            f"P1.248: expected rwa~={EXPECTED_RWA:,.2f}, got {rwa:,.2f}. "
            f"Pre-fix (flat 25% floor): rwa~=512,871.12."
        )
        assert rwa_final == pytest.approx(EXPECTED_RWA, rel=_REL_TOL), (
            f"P1.248: expected rwa_final~={EXPECTED_RWA:,.2f}, got {rwa_final:,.2f}."
        )

    def test_p1_248_expected_loss_matches_hand_calc(self, loan_row: dict) -> None:
        """
        P1.248: expected_loss == 1,900.00 (PD_floored=0.01 x lgd_floored=0.19
        x ead_final=1,000,000).

        Arrange: same as PRIMARY test.
        Act:     Basel 3.1 A-IRB pipeline.
        Assert:  expected_loss == 1,900.00 (abs tol 1).

        Pre-fix: expected_loss == 2,500.00 (PD 0.01 x LGD 0.25 x EAD 1,000,000).
        """
        expected_loss = loan_row["expected_loss"]

        assert expected_loss == pytest.approx(EXPECTED_EXPECTED_LOSS, abs=1), (
            f"P1.248: expected expected_loss={EXPECTED_EXPECTED_LOSS:,.2f} "
            f"(0.01 x 0.19 x 1,000,000), got {expected_loss:,.2f}. "
            f"Pre-fix: expected_loss=2,500.00 (0.01 x 0.25 x 1,000,000)."
        )

    def test_p1_248_ead_final_unchanged(self, loan_row: dict) -> None:
        """
        P1.248 regression guard: ead_final == 1,000,000.00 -- fully drawn,
        no CCF ambiguity, unaffected by the LGD-floor fix.

        Arrange: same as PRIMARY test.
        Act:     Basel 3.1 A-IRB pipeline.
        Assert:  ead_final == 1,000,000.00 (rel tol 1e-6).
        """
        ead_final = loan_row["ead_final"]

        assert ead_final == pytest.approx(EXPECTED_EAD_FINAL, rel=1e-6), (
            f"P1.248: expected ead_final={EXPECTED_EAD_FINAL:,.2f}, got {ead_final:,.2f}."
        )

    # =========================================================================
    # Structural guard: corporate A-IRB routing (not SA / not F-IRB / not retail)
    # =========================================================================

    def test_p1_248_classifies_corporate_advanced_irb(self, loan_row: dict) -> None:
        """
        P1.248 regression guard: the exposure classifies as corporate and
        routes to the Advanced IRB approach, via model_id=UK_CORP_AIRB_01.

        Arrange: CP-CORP-AIRB-P1248 (entity_type=corporate), model permission
                 UK_CORP_AIRB_01 (advanced_irb, GB, excludes TRADE_FINANCE).
        Act:     Basel 3.1 A-IRB pipeline.
        Assert:  exposure_class == 'corporate', approach_applied ==
                  'advanced_irb', is_airb is True.
        """
        assert loan_row["exposure_class"] == "corporate", (
            f"P1.248: expected exposure_class='corporate', "
            f"got {loan_row['exposure_class']!r}."
        )
        assert loan_row["approach_applied"] == "advanced_irb", (
            f"P1.248: expected approach_applied='advanced_irb', "
            f"got {loan_row['approach_applied']!r}. Check model_permission "
            f"fixture (UK_CORP_AIRB_01, corporate, advanced_irb)."
        )
        assert loan_row["is_airb"] is True, (
            f"P1.248: expected is_airb=True, got {loan_row['is_airb']!r}."
        )
