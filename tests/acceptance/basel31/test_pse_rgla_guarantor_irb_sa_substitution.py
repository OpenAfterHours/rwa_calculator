"""
Phase 4 Slice 5 — IRB borrower + PSE / RGLA SA guarantors → RWSM substitution gap.

Pipeline position:
    Loader → HierarchyResolver → Classifier → CRMProcessor → IRBCalculator → Aggregator

Key assertion:
    When a FIRB corporate borrower is covered by an unfunded guarantee from a PSE or
    RGLA guarantor with no internal PD, the engine must fall back to the SA risk-weight
    substitution method (RWSM, Art. 235) and price the guarantor via the PSE / RGLA SA
    tables — exactly as the SA-side twin already does
    (engine/sa/namespace.py::_build_guarantor_rw_expr).

    Pre-fix (current engine bug — the recorded Phase 4 IRB-guarantor PSE/RGLA gap):
        engine/irb/guarantee.py::_compute_guarantor_rw_sa has no "pse" / "rgla"
        branches; both fall to ``.otherwise(pl.lit(None))``, so guarantor_rw is null,
        is_guarantee_beneficial is False and the guarantee is silently discarded:
            guarantor_rw     = None
            rwa_final        = rwa_irb_original (1,554,597.18 CRR / 1,303,645.43 B31
                               for this fixture's pd=0.02, M=5y FIRB borrower)
            guarantee_status = "GUARANTEE_NOT_APPLIED_NON_BENEFICIAL"

    Post-fix expected (hand-calculated; PSE/RGLA SA tables are identical under CRR
    and PRA PS1/26, so both framework arms pin the same absolute values):

        Scenario A  — rated PSE guarantor CQS 2 (CRR Art. 116(2) Table 2A):
            guarantor_rw = 0.50, rwa_final = 500,000,
            guarantee_status = "SA_RW_SUBSTITUTION", is_guarantee_beneficial = True,
            guarantor_exposure_class = "pse".
        Scenario A2 — rated PSE guarantor CQS 3 (anti-corporate confound:
            PSE Table 2A 50% vs corporate CRR Table 5 100% / B31 Table 6 75%):
            guarantor_rw = 0.50, rwa_final = 500,000.
        Scenario B  — unrated RGLA guarantor, GB: guarantor_rw = 0.20,
            rwa_final = 200,000 (documented SA-side unrated approximation — see
            test docstring).
        Scenario B  — unrated RGLA guarantor, DE: guarantor_rw = 1.00,
            rwa_final = 1,000,000 — still beneficial vs the borrower's own FIRB RW
            (>100% both frameworks), so rwa_final < rwa_irb_original.

Routing note:
    The guaranteed sub-row inherits approach=FIRB from the borrower exposure (the CRM
    processor does not change the approach field). The pipeline router places it in the
    IRB branch, so assertions must query irb_results, not sa_results.

References:
    - CRR Art. 116(2) Table 2A: rated PSE risk weights by own CQS (CQS 2/3 = 50%);
      PRA PS1/26 values identical
    - CRR Art. 115(1)(b) Table 1B: rated RGLA risk weights (same values)
    - PRA PS1/26 Art. 235: SA risk-weight substitution method (RWSM) for guarantees
    - CRR Art. 237(2)(a): unfunded credit protection original maturity >= 1 year
    - engine/irb/guarantee.py::_compute_guarantor_rw_sa: bug site (.otherwise(null))
    - engine/sa/namespace.py::_build_guarantor_rw_expr: SA-side reference implementation
    - docs/plans/target-architecture-migration.md: the recorded Phase 4 fix
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.acceptance.conftest import get_guaranteed_row
from tests.fixtures.pse_rgla_guarantor.pse_rgla_guarantor import (
    EXPECTED_GUARANTEE_STATUS,
    EXPECTED_GUARANTOR_EXPOSURE_CLASS_PSE,
    EXPECTED_GUARANTOR_EXPOSURE_CLASS_RGLA,
    EXPECTED_GUARANTOR_RW_PSE_RATED,
    EXPECTED_GUARANTOR_RW_RGLA_UNRATED_GB,
    EXPECTED_GUARANTOR_RW_RGLA_UNRATED_NON_GB,
    EXPECTED_RWA_PSE_RATED,
    EXPECTED_RWA_RGLA_UNRATED_GB,
    EXPECTED_RWA_RGLA_UNRATED_NON_GB,
    LOAN_PSE_CQS2_REF,
    LOAN_PSE_CQS3_REF,
    LOAN_RGLA_DE_REF,
    LOAN_RGLA_GB_REF,
    PRE_FIX_GUARANTEE_STATUS,
    load_pse_rgla_guarantor_bundle,
)

# ---------------------------------------------------------------------------
# Config factories
# ---------------------------------------------------------------------------


def _b31_irb_config() -> CalculationConfig:
    """Basel 3.1 IRB config (post-go-live, 2027-06-30).

    PermissionMode.IRB activates model-level IRB permissions. The
    MODEL_BORROWER_FIRB model permission row in the fixture grants
    foundation_irb for corporate exposures, routing CP_BORROWER_PSERGLA
    through F-IRB. The PSE/RGLA guarantors have no internal PD → they stay
    on SA, falling through to the RWSM guarantor RW lookup.
    """
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30),
        permission_mode=PermissionMode.IRB,
    )


def _crr_irb_config() -> CalculationConfig:
    """CRR IRB config (pre-Basel-3.1 effective date, 2025-12-31).

    Same fixture data routed under CRR. PSE Table 2A / RGLA Table 1B values
    are identical under CRR and PS1/26, so both arms pin the same numbers.
    """
    return CalculationConfig.crr(
        reporting_date=date(2025, 12, 31),
        permission_mode=PermissionMode.IRB,
    )


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------


def _run_pipeline(config: CalculationConfig) -> pl.DataFrame:
    """
    Run the PSE/RGLA-guarantor fixtures through the credit risk pipeline and
    return the IRB results DataFrame.

    The CRM processor splits each guaranteed FIRB loan into two sub-rows:
      - ``<loan>__G_<guarantor>``: guaranteed portion (ead_final = 1,000,000)
      - ``<loan>__REM``: unguaranteed remainder (ead_final = 0 — fully covered)
    Both inherit approach=FIRB → routed to the IRB branch → irb_results.
    """
    bundle = load_pse_rgla_guarantor_bundle()
    results = PipelineOrchestrator().run_with_data(bundle, config)
    assert results.irb_results is not None, (
        "IRB results should not be None — check PermissionMode.IRB config and "
        "that model_permission.parquet contains MODEL_BORROWER_FIRB."
    )
    return results.irb_results.collect()


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestPseRglaGuarantorIRBSubstitution:
    """
    Phase 4 Slice 5: FIRB borrower with PSE / RGLA SA guarantors must receive
    RWSM substitution at the PSE/RGLA SA tables.

    All four loans live in one fixture bundle (one pipeline run per framework):

    1. LOAN_PSE_CQS2  — rated PSE CQS 2  → 50% (Art. 116(2) Table 2A), headline pin
    2. LOAN_PSE_CQS3  — rated PSE CQS 3  → 50% (anti-corporate confound: corporate
       CQS 3 is 100% CRR / 75% B31 — a 50% result proves the PSE table was hit)
    3. LOAN_RGLA_GB   — unrated RGLA, GB → 20% (documented unrated approximation)
    4. LOAN_RGLA_DE   — unrated RGLA, DE → 100% (substitution still beneficial vs
       the borrower's >100% FIRB RW)

    PRE-FIX (today) every one of these FAILS the same way: guarantor_rw = None,
    rwa_final = rwa_irb_original, guarantee_status =
    "GUARANTEE_NOT_APPLIED_NON_BENEFICIAL" (engine/irb/guarantee.py
    _compute_guarantor_rw_sa .otherwise(null) — no pse/rgla branches).
    """

    # ------------------------------------------------------------------
    # Class-scoped IRB result fixtures (one pipeline run per framework)
    # ------------------------------------------------------------------

    @pytest.fixture(scope="class")
    def b31_irb_results(self) -> pl.DataFrame:
        """
        Basel 3.1 IRB pipeline results for the PSE/RGLA-guarantor fixture.

        Arrange: PSE/RGLA parquets — FIRB corporate borrower (pd=0.02), four
                 100%-coverage guarantees, reporting_date=2027-06-30.
        Act:     PipelineOrchestrator with CalculationConfig.basel_3_1(),
                 PermissionMode.IRB, MODEL_BORROWER_FIRB → corporate/foundation_irb.
        Return:  Collected IRB results DataFrame.
        """
        return _run_pipeline(_b31_irb_config())

    @pytest.fixture(scope="class")
    def crr_irb_results(self) -> pl.DataFrame:
        """
        CRR IRB pipeline results for the PSE/RGLA-guarantor fixture.

        Arrange: Same parquets, reporting_date=2025-12-31 (CRR era).
        Act:     PipelineOrchestrator with CalculationConfig.crr(), PermissionMode.IRB.
        Return:  Collected IRB results DataFrame.
        """
        return _run_pipeline(_crr_irb_config())

    # ------------------------------------------------------------------
    # Shared assertion helper
    # ------------------------------------------------------------------

    @staticmethod
    def _assert_substitution(
        row: dict,
        *,
        framework: str,
        loan_ref: str,
        expected_rw: float,
        expected_rwa: float,
        expected_class: str,
        rule: str,
    ) -> None:
        """Assert the post-fix RWSM substitution pins on one guaranteed sub-row.

        Pre-fix every call fails on the first assertion with guarantor_rw=None
        (engine/irb/guarantee.py _compute_guarantor_rw_sa .otherwise(null)) and
        rwa_final stuck at rwa_irb_original with guarantee_status
        "GUARANTEE_NOT_APPLIED_NON_BENEFICIAL".
        """
        actual_rw = row["guarantor_rw"]
        assert actual_rw == pytest.approx(expected_rw, rel=1e-9), (
            f"{framework} {loan_ref}: guarantor_rw should be {expected_rw:.2f} ({rule}). "
            f"Got {actual_rw!r}. "
            f"None means _compute_guarantor_rw_sa (engine/irb/guarantee.py) still has "
            f"no '{expected_class}' branch — the guarantee was silently dropped "
            f"(pre-fix status {PRE_FIX_GUARANTEE_STATUS!r})."
        )

        actual_rwa = row["rwa_final"]
        assert actual_rwa == pytest.approx(expected_rwa, rel=1e-9), (
            f"{framework} {loan_ref}: guaranteed-portion rwa_final should be "
            f"{expected_rwa:,.0f} (EAD 1,000,000 x guarantor_rw {expected_rw:.2f}, "
            f"100% coverage blend). Got {actual_rwa!r}. "
            f"Pre-fix it equals rwa_irb_original (the borrower's own FIRB RWA)."
        )

        assert row["guarantee_status"] == EXPECTED_GUARANTEE_STATUS, (
            f"{framework} {loan_ref}: guarantee_status should be "
            f"{EXPECTED_GUARANTEE_STATUS!r}; got {row['guarantee_status']!r} "
            f"(pre-fix the row is mislabelled {PRE_FIX_GUARANTEE_STATUS!r} even though "
            f"the guarantee was never priced)."
        )

        assert row["is_guarantee_beneficial"] is True, (
            f"{framework} {loan_ref}: is_guarantee_beneficial should be True "
            f"(guarantor_rw {expected_rw:.2f} < borrower FIRB RW > 1.00); "
            f"got {row['is_guarantee_beneficial']!r}."
        )

        assert row["guarantor_exposure_class"] == expected_class, (
            f"{framework} {loan_ref}: guarantor_exposure_class should be "
            f"{expected_class!r}; got {row['guarantor_exposure_class']!r}."
        )

    # ------------------------------------------------------------------
    # Scenario A — rated PSE guarantor CQS 2 (headline pin), both arms
    # ------------------------------------------------------------------

    def test_crr_rated_pse_cqs2_guarantor_substitutes_at_50pct(
        self, crr_irb_results: pl.DataFrame
    ) -> None:
        """
        Scenario A (CRR arm): FIRB borrower + rated PSE guarantor CQS 2 must
        substitute at 50% (CRR Art. 116(2) Table 2A).

        Anti-confound: CQS 2 distinguishes a PSE Table 2A hit (50%) from a CGCB
        misroute (20%); guarantor_exposure_class == "pse" guards against a
        corporate-branch coincidence (corporate CQS 2 is also 50%).

        Arrange: CRR config, LOAN_PSE_CQS2 guaranteed 100% by CP_GTR_PSE_CQS2
                 (entity_type="pse_institution", external CQS 2, pd=None).
        Act:     IRB results for the LOAN_PSE_CQS2 guaranteed-portion sub-row.
        Assert:  guarantor_rw = 0.50, rwa_final = 500,000,
                 guarantee_status = "SA_RW_SUBSTITUTION",
                 is_guarantee_beneficial = True, guarantor_exposure_class = "pse".

        PRE-FIX (today): guarantor_rw = None, rwa_final = 1,554,597.18
        (= rwa_irb_original), status GUARANTEE_NOT_APPLIED_NON_BENEFICIAL → FAILS.
        """
        row = get_guaranteed_row(crr_irb_results, LOAN_PSE_CQS2_REF)
        self._assert_substitution(
            row,
            framework="CRR",
            loan_ref=LOAN_PSE_CQS2_REF,
            expected_rw=EXPECTED_GUARANTOR_RW_PSE_RATED,
            expected_rwa=EXPECTED_RWA_PSE_RATED,
            expected_class=EXPECTED_GUARANTOR_EXPOSURE_CLASS_PSE,
            rule="CRR Art. 116(2) Table 2A: PSE own-rating CQS 2 = 50%",
        )

    def test_b31_rated_pse_cqs2_guarantor_substitutes_at_50pct(
        self, b31_irb_results: pl.DataFrame
    ) -> None:
        """
        Scenario A (B31 arm): FIRB borrower + rated PSE guarantor CQS 2 must
        substitute at 50% (PRA PS1/26 Art. 116(2) Table 2A — identical to CRR).

        Anti-confound: on the B31 arm CQS 2 also distinguishes the PSE table (50%)
        from an institution-ECRA misroute (30% per PS1/26 Art. 120 Table 3).

        Arrange: B31 config, same fixture data.
        Act:     IRB results for the LOAN_PSE_CQS2 guaranteed-portion sub-row.
        Assert:  guarantor_rw = 0.50, rwa_final = 500,000 (absolute pin —
                 framework-identical, so no cross-arm delta exists by design).

        PRE-FIX (today): guarantor_rw = None, rwa_final = 1,303,645.43
        (= rwa_irb_original), status GUARANTEE_NOT_APPLIED_NON_BENEFICIAL → FAILS.
        """
        row = get_guaranteed_row(b31_irb_results, LOAN_PSE_CQS2_REF)
        self._assert_substitution(
            row,
            framework="B31",
            loan_ref=LOAN_PSE_CQS2_REF,
            expected_rw=EXPECTED_GUARANTOR_RW_PSE_RATED,
            expected_rwa=EXPECTED_RWA_PSE_RATED,
            expected_class=EXPECTED_GUARANTOR_EXPOSURE_CLASS_PSE,
            rule="PRA PS1/26 Art. 116(2) Table 2A: PSE own-rating CQS 2 = 50%",
        )

    # ------------------------------------------------------------------
    # Scenario A2 — rated PSE guarantor CQS 3 (anti-corporate confound)
    # ------------------------------------------------------------------

    def test_crr_rated_pse_cqs3_guarantor_substitutes_at_50pct(
        self, crr_irb_results: pl.DataFrame
    ) -> None:
        """
        Scenario A2 (CRR arm): rated PSE guarantor CQS 3 must substitute at 50%
        (CRR Art. 116(2) Table 2A) — NOT 100% (corporate CRR Table 5 CQS 3).

        A 50% result proves the PSE table was consulted rather than the corporate
        branch: at CQS 3 the two tables diverge (PSE 50% vs corporate 100%).

        Arrange: CRR config, LOAN_PSE_CQS3 guaranteed 100% by CP_GTR_PSE_CQS3
                 (entity_type="pse_institution", external CQS 3, pd=None).
        Act:     IRB results for the LOAN_PSE_CQS3 guaranteed-portion sub-row.
        Assert:  guarantor_rw = 0.50, rwa_final = 500,000.

        PRE-FIX (today): guarantor_rw = None, rwa_final = 1,554,597.18 → FAILS.
        """
        row = get_guaranteed_row(crr_irb_results, LOAN_PSE_CQS3_REF)
        self._assert_substitution(
            row,
            framework="CRR",
            loan_ref=LOAN_PSE_CQS3_REF,
            expected_rw=EXPECTED_GUARANTOR_RW_PSE_RATED,
            expected_rwa=EXPECTED_RWA_PSE_RATED,
            expected_class=EXPECTED_GUARANTOR_EXPOSURE_CLASS_PSE,
            rule="CRR Art. 116(2) Table 2A: PSE CQS 3 = 50% (corporate Table 5 = 100%)",
        )

    def test_b31_rated_pse_cqs3_guarantor_substitutes_at_50pct(
        self, b31_irb_results: pl.DataFrame
    ) -> None:
        """
        Scenario A2 (B31 arm): rated PSE guarantor CQS 3 must substitute at 50%
        (PRA PS1/26 Art. 116(2) Table 2A) — NOT 75% (corporate B31 Table 6 CQS 3).

        At CQS 3 the PSE table (50%) diverges from the B31 corporate table (75%),
        so a 50% result proves the PSE branch was hit on the B31 arm too.

        Arrange: B31 config, same fixture data.
        Act:     IRB results for the LOAN_PSE_CQS3 guaranteed-portion sub-row.
        Assert:  guarantor_rw = 0.50, rwa_final = 500,000.

        PRE-FIX (today): guarantor_rw = None, rwa_final = 1,303,645.43 → FAILS.
        """
        row = get_guaranteed_row(b31_irb_results, LOAN_PSE_CQS3_REF)
        self._assert_substitution(
            row,
            framework="B31",
            loan_ref=LOAN_PSE_CQS3_REF,
            expected_rw=EXPECTED_GUARANTOR_RW_PSE_RATED,
            expected_rwa=EXPECTED_RWA_PSE_RATED,
            expected_class=EXPECTED_GUARANTOR_EXPOSURE_CLASS_PSE,
            rule="PS1/26 Art. 116(2) Table 2A: PSE CQS 3 = 50% (corporate Table 6 = 75%)",
        )

    # ------------------------------------------------------------------
    # Scenario B — unrated RGLA guarantor, GB (documented approximation)
    # ------------------------------------------------------------------

    def test_crr_unrated_rgla_gb_guarantor_substitutes_at_20pct(
        self, crr_irb_results: pl.DataFrame
    ) -> None:
        """
        Scenario B (CRR arm): unrated GB RGLA guarantor must substitute at 20%.

        IMPORTANT — what this pins: the SA-side DOCUMENTED UNRATED APPROXIMATION
        (engine/sa/namespace.py::_build_guarantor_rw_expr — guarantor_country_code
        == "GB" → 20% (rgla_domestic), else → 100% (pse_unrated)) as adopted by
        the shared guarantor RW expression. It is deliberately NOT the full
        CRR Art. 115(1)(a) sovereign-derived Table 1A treatment: no guarantor
        sovereign CQS join exists in the CRM guarantor column production
        (engine/crm/guarantees.py::_join_guarantor_counterparty), and inheriting
        the SA-side approximation is the recorded decision. If the eventual fix
        instead threads a real guarantor_sovereign_cqs (UK CQS 1 → 20% via
        Table 1A), the pinned number is unchanged but this docstring should be
        updated to cite the rule that produced it.

        Arrange: CRR config, LOAN_RGLA_GB guaranteed 100% by CP_GTR_RGLA_GB
                 (entity_type="rgla_institution", country_code="GB", NO rating rows).
        Act:     IRB results for the LOAN_RGLA_GB guaranteed-portion sub-row.
        Assert:  guarantor_rw = 0.20, rwa_final = 200,000,
                 guarantor_exposure_class = "rgla".

        PRE-FIX (today): guarantor_rw = None, rwa_final = 1,554,597.18 → FAILS.
        """
        row = get_guaranteed_row(crr_irb_results, LOAN_RGLA_GB_REF)
        self._assert_substitution(
            row,
            framework="CRR",
            loan_ref=LOAN_RGLA_GB_REF,
            expected_rw=EXPECTED_GUARANTOR_RW_RGLA_UNRATED_GB,
            expected_rwa=EXPECTED_RWA_RGLA_UNRATED_GB,
            expected_class=EXPECTED_GUARANTOR_EXPOSURE_CLASS_RGLA,
            rule="SA-side documented unrated approximation: GB guarantor → 20%",
        )

    def test_b31_unrated_rgla_gb_guarantor_substitutes_at_20pct(
        self, b31_irb_results: pl.DataFrame
    ) -> None:
        """
        Scenario B (B31 arm): unrated GB RGLA guarantor must substitute at 20%.

        Same documented unrated approximation as the CRR arm (see
        test_crr_unrated_rgla_gb_guarantor_substitutes_at_20pct — GB → 20%,
        else → 100%; NOT the Art. 115(1)(a) sovereign-derived table). RGLA
        values are framework-identical, so the B31 arm pins the same 20%.

        Arrange: B31 config, same fixture data.
        Act:     IRB results for the LOAN_RGLA_GB guaranteed-portion sub-row.
        Assert:  guarantor_rw = 0.20, rwa_final = 200,000.

        PRE-FIX (today): guarantor_rw = None, rwa_final = 1,303,645.43 → FAILS.
        """
        row = get_guaranteed_row(b31_irb_results, LOAN_RGLA_GB_REF)
        self._assert_substitution(
            row,
            framework="B31",
            loan_ref=LOAN_RGLA_GB_REF,
            expected_rw=EXPECTED_GUARANTOR_RW_RGLA_UNRATED_GB,
            expected_rwa=EXPECTED_RWA_RGLA_UNRATED_GB,
            expected_class=EXPECTED_GUARANTOR_EXPOSURE_CLASS_RGLA,
            rule="SA-side documented unrated approximation: GB guarantor → 20%",
        )

    # ------------------------------------------------------------------
    # Scenario B — unrated RGLA guarantor, non-GB (conservative 100%)
    # ------------------------------------------------------------------

    def test_crr_unrated_rgla_non_gb_guarantor_substitutes_at_100pct(
        self, crr_irb_results: pl.DataFrame
    ) -> None:
        """
        Scenario B (CRR arm): unrated non-GB (DE) RGLA guarantor must substitute
        at 100% — and the substitution must still be applied, because 100% beats
        the borrower's own FIRB RW (~155% for pd=0.02, LGD 45%, M=5y, x1.06).

        Pins the conservative else-branch of the documented unrated approximation
        (non-GB unrated guarantor → 100%; see the GB test docstring for why this
        is the approximation, not Art. 115(1)(a) sovereign-derived treatment).

        Arrange: CRR config, LOAN_RGLA_DE guaranteed 100% by CP_GTR_RGLA_DE
                 (entity_type="rgla_institution", country_code="DE", NO rating rows).
        Act:     IRB results for the LOAN_RGLA_DE guaranteed-portion sub-row.
        Assert:  guarantor_rw = 1.00, rwa_final = 1,000,000,
                 rwa_final < rwa_irb_original (substitution actually engaged).

        PRE-FIX (today): guarantor_rw = None, rwa_final = 1,554,597.18
        (== rwa_irb_original — guarantee no-op) → FAILS.
        """
        row = get_guaranteed_row(crr_irb_results, LOAN_RGLA_DE_REF)
        self._assert_substitution(
            row,
            framework="CRR",
            loan_ref=LOAN_RGLA_DE_REF,
            expected_rw=EXPECTED_GUARANTOR_RW_RGLA_UNRATED_NON_GB,
            expected_rwa=EXPECTED_RWA_RGLA_UNRATED_NON_GB,
            expected_class=EXPECTED_GUARANTOR_EXPOSURE_CLASS_RGLA,
            rule="SA-side documented unrated approximation: non-GB guarantor → 100%",
        )
        assert row["rwa_final"] < row["rwa_irb_original"], (
            f"CRR {LOAN_RGLA_DE_REF}: rwa_final ({row['rwa_final']!r}) should be "
            f"strictly below rwa_irb_original ({row['rwa_irb_original']!r}) — the "
            f"100% substitution beats the borrower's ~155% FIRB RW. Equality means "
            f"the guarantee was a no-op (pre-fix signature)."
        )

    def test_b31_unrated_rgla_non_gb_guarantor_substitutes_at_100pct(
        self, b31_irb_results: pl.DataFrame
    ) -> None:
        """
        Scenario B (B31 arm): unrated non-GB (DE) RGLA guarantor must substitute
        at 100% — still beneficial vs the borrower's ~130% B31 FIRB RW
        (pd=0.02, LGD 40%, M=5y, no 1.06 scaling).

        Arrange: B31 config, same fixture data.
        Act:     IRB results for the LOAN_RGLA_DE guaranteed-portion sub-row.
        Assert:  guarantor_rw = 1.00, rwa_final = 1,000,000,
                 rwa_final < rwa_irb_original.

        PRE-FIX (today): guarantor_rw = None, rwa_final = 1,303,645.43
        (== rwa_irb_original — guarantee no-op) → FAILS.
        """
        row = get_guaranteed_row(b31_irb_results, LOAN_RGLA_DE_REF)
        self._assert_substitution(
            row,
            framework="B31",
            loan_ref=LOAN_RGLA_DE_REF,
            expected_rw=EXPECTED_GUARANTOR_RW_RGLA_UNRATED_NON_GB,
            expected_rwa=EXPECTED_RWA_RGLA_UNRATED_NON_GB,
            expected_class=EXPECTED_GUARANTOR_EXPOSURE_CLASS_RGLA,
            rule="SA-side documented unrated approximation: non-GB guarantor → 100%",
        )
        assert row["rwa_final"] < row["rwa_irb_original"], (
            f"B31 {LOAN_RGLA_DE_REF}: rwa_final ({row['rwa_final']!r}) should be "
            f"strictly below rwa_irb_original ({row['rwa_irb_original']!r}) — the "
            f"100% substitution beats the borrower's ~130% FIRB RW. Equality means "
            f"the guarantee was a no-op (pre-fix signature)."
        )
