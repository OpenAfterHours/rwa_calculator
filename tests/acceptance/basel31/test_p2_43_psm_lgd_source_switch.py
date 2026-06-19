"""
P2.43 — Basel 3.1 PSM LGD source switch: Art. 236(1)(a)(i) option (i) vs option (ii).

Pipeline position:
    IRBPermissions.psm_lgd_source (config) → CRMProcessor / IRB guarantee substitution
    (_apply_parameter_substitution → guarantor LGD selection)

Scenario design:
    A single F-IRB corporate exposure (EXP_P2_43, GBP 1,000,000, subordinated borrower,
    M=2.5y, PD=0.05) is fully guaranteed by GUARANTOR_99 (senior, non-FSE, PD=0.005).

    The discriminating engine field is ``IRBPermissions.psm_lgd_source``, a NEW field
    the engine-implementer must add. Two valid string values:

    "option_ii" (default) — use the guarantor's F-IRB supervisory LGD keyed on the
        GUARANTOR's seniority ("senior" → Art. 161(1)(a) LGD = 40% under Basel 3.1).
        This produces the LOWER RWA.

    "option_i"  — use the BORROWER's own F-IRB supervisory LGD (unprotected LGD),
        driven by the borrower's seniority ("subordinated" → Art. 161(1)(b) LGD = 75%).
        This produces the HIGHER RWA because the PSM uses the borrower's own higher LGD
        instead of the guarantor's senior LGD.

    The fixture is identical for both test arms. Only the config changes.

Hand-calculation (Basel 3.1, scaling factor = 1.0, Art. 153):
    PD_guarantor = 0.005 (above B31 corporate floor 0.0005 → no floor effect)
    M = 2.5y; EAD = 1,000,000 GBP; full coverage.

    Option ii (default): LGD_psm = 0.40 (guarantor's senior supervisory LGD, B31)
        R = 0.12*(1-exp(-50*0.005))/(1-exp(-50)) + 0.24*(1 - ...) ≈ 0.23641
        MA ≈ 1.5883
        K  ≈ LGD*N[...] − PD*LGD = 0.40 * N[...] − 0.005 * 0.40 ≈ 0.04951
        RW = K * 12.5 ≈ 0.619037
        RWA = 0.619037 * 1,000,000 ≈ 619,037
        EL  = 0.005 * 0.40 * 1,000,000 = 2,000

    Option i: LGD_psm = 0.75 (borrower's own subordinated supervisory LGD)
        Same PD/M/R/MA, different LGD:
        K  ≈ 0.75 * N[...] − 0.005 * 0.75 ≈ 0.09282
        RW = K * 12.5 ≈ 1.160695
        RWA = 1.160695 * 1,000,000 ≈ 1,160,695
        EL  = 0.005 * 0.75 * 1,000,000 = 3,750

    Delta: RWA_option_i − RWA_option_ii ≈ 1,160,695 − 619,037 = 541,658

Regulatory references:
    - PRA PS1/26 Art. 236(1)(a)(i): PSM LGD source — either the supervisory LGD for a
      direct obligation of the guarantor's seniority (option ii, the proposed default),
      or the unprotected LGD of the borrower's own obligation (option i).
    - PRA PS1/26 Art. 161(1)(a): B31 F-IRB supervisory LGD 40% (corporate senior, non-FSE).
    - PRA PS1/26 Art. 161(1)(b): B31 F-IRB supervisory LGD 75% (corporate subordinated).
    - PRA PS1/26 Art. 163(1): B31 corporate PD floor 0.05% (both PDs well above floor).

Engine gap (to be fixed by engine-implementer):
    ``IRBPermissions`` dataclass (src/rwa_calc/contracts/config.py) does not have a
    ``psm_lgd_source`` field. Adding it (default="option_ii") is the minimal change
    required to make test 1 pass; routing the IRB guarantee substitution to use the
    correct LGD based on that field makes tests 2 and 3 pass.

Code references:
    - tests/fixtures/p2_43/p2_43.py: fixture constants and parquet generators
    - src/rwa_calc/contracts/config.py: IRBPermissions (add psm_lgd_source field)
    - src/rwa_calc/engine/irb/guarantee.py: _apply_parameter_substitution (LGD dispatch)
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rwa_calc.contracts.bundles import AggregatedResultBundle, RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, IRBPermissions
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.p2_43.p2_43 import (
    EAD,
    EXPECTED_LGD_BORROWER,
    EXPECTED_LGD_OPTION_I_B31,
    EXPECTED_LGD_OPTION_II,
    LOAN_REF,
    PD_BORROWER,
    PD_GUARANTOR,
)
from tests.fixtures.raw_bundle import make_raw_bundle

# =============================================================================
# Scenario expected values (hand-calculation in module docstring above)
# =============================================================================

# Option ii (default): LGD_psm = 0.40 (guarantor's senior supervisory LGD, B31)
# PD=0.005, LGD=0.40, M=2.5, EAD=1,000,000, scaling=1.0
# Engine (polars-normal-stats): RW ≈ 0.618771, RWA ≈ 618,771; proposal: 0.619037 / 619,037
# Relative gap: ~0.04% (normal-approx). Use rel=5e-3 to span both while remaining discriminating.
EXPECTED_RW_OPTION_II: float = 0.619037  # proposal anchor
EXPECTED_RWA_OPTION_II: float = 619_037.0  # proposal anchor
EXPECTED_EL_OPTION_II: float = 2_000.0  # 0.005 * 0.40 * 1,000,000

# Option i: LGD_psm = 0.75 (borrower's own subordinated supervisory LGD)
# PD=0.005, LGD=0.75, M=2.5, EAD=1,000,000, scaling=1.0
# Engine: RW ≈ 1.160196, RWA ≈ 1,160,196; proposal: 1.160695 / 1,160,695
# Relative gap: ~0.04% (normal-approx). Use rel=5e-3 to span both.
EXPECTED_RW_OPTION_I: float = 1.160695  # proposal anchor
EXPECTED_RWA_OPTION_I: float = 1_160_695.0  # proposal anchor
EXPECTED_EL_OPTION_I: float = 3_750.0  # 0.005 * 0.75 * 1,000,000

# Delta: option_i − option_ii
# Engine: 1,160,196 − 618,771 = 541,425; proposal: 541,658
# Relative gap ~0.04%; use rel=1e-2 to span.
EXPECTED_RWA_DELTA: float = 541_658.0  # proposal anchor

# =============================================================================
# Fixture directory
# =============================================================================

_FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures" / "p2_43"


# =============================================================================
# Pipeline helpers
# =============================================================================


def _build_p2_43_bundle() -> RawDataBundle:
    """
    Load P2.43 parquet fixtures and assemble a RawDataBundle.

    The bundle is identical for both option_i and option_ii test arms.
    Only the config (IRBPermissions.psm_lgd_source) varies between arms.

    Provides:
        - One F-IRB corporate subordinated loan (EXP_P2_43, GBP 1,000,000)
        - One corporate guarantor (GUARANTOR_99, senior, 100% coverage)
        - IRB model permission: foundation_irb for corporate class
        - Both borrower (PD=5%) and guarantor (PD=0.5%) internal ratings
    """
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

    return make_raw_bundle(
        facilities=pl.scan_parquet(_FIXTURES_DIR / "facility.parquet"),
        loans=pl.scan_parquet(_FIXTURES_DIR / "loan.parquet"),
        counterparties=pl.scan_parquet(_FIXTURES_DIR / "counterparty.parquet"),
        guarantees=pl.scan_parquet(_FIXTURES_DIR / "guarantee.parquet"),
        ratings=pl.scan_parquet(_FIXTURES_DIR / "rating.parquet"),
        model_permissions=pl.scan_parquet(_FIXTURES_DIR / "model_permission.parquet"),
        facility_mappings=facility_mappings,
        lending_mappings=lending_mappings,
    )


def _find_irb_row(results: AggregatedResultBundle, loan_ref: str) -> dict:
    """
    Return the guaranteed portion IRB result row for *loan_ref*.

    When a guarantee is applied the pipeline splits the exposure into sub-rows
    keyed by parent_exposure_reference. For a 100%-covered exposure:
        ``{loan_ref}__G_{guarantor_ref}`` — the guaranteed portion (has rwa > 0)
        ``{loan_ref}__REM``               — the remainder (rwa = 0)

    This helper finds the sub-row whose parent_exposure_reference matches *loan_ref*
    and which has a non-zero EAD (the guaranteed portion), and asserts exactly one
    such row exists.
    """
    assert results.irb_results is not None, "irb_results must not be None for IRB scenario"
    irb_df = results.irb_results.collect()
    # First try: direct match on exposure_reference (no guarantee split)
    direct_rows = irb_df.filter(pl.col("exposure_reference") == loan_ref).to_dicts()
    if len(direct_rows) == 1:
        return direct_rows[0]
    # Second: match by parent_exposure_reference; pick guaranteed portion (ead_final > 0)
    sub_rows = irb_df.filter(
        (pl.col("parent_exposure_reference") == loan_ref) & (pl.col("ead_final") > 0)
    ).to_dicts()
    all_irb_refs = irb_df["exposure_reference"].to_list()
    sa_refs = (
        results.sa_results.collect()["exposure_reference"].to_list()
        if results.sa_results is not None
        else []
    )
    assert len(sub_rows) == 1, (
        f"Expected exactly 1 guaranteed-portion IRB row for parent {loan_ref!r}, "
        f"got {len(sub_rows)}. "
        f"All IRB exposure_references: {all_irb_refs!r}. "
        f"SA exposure_references: {sa_refs!r}"
    )
    return sub_rows[0]


# =============================================================================
# P2.43 acceptance tests: PSM LGD source switch
# =============================================================================


class TestP243PSMLGDSourceSwitch:
    """
    P2.43: Basel 3.1 IRBPermissions.psm_lgd_source controls PSM LGD selection.

    Art. 236(1)(a)(i) gives firms a choice of two LGDs when applying parameter
    substitution (PSM) to an IRB guarantee:
        option ii (proposed default): supervisory LGD for the guarantor's own seniority
            → lower RWA when guarantor's seniority is senior (LGD=40%)
        option i: unprotected LGD of the borrower's own obligation
            → higher RWA when borrower's obligation is subordinated (LGD=75%)

    The new ``IRBPermissions.psm_lgd_source`` field (engine-implementer must add it)
    selects between these paths. Tests 1-3 verify the switch produces the expected
    RWA values and that the two options are materially different.
    """

    def test_psm_option_ii_default_uses_guarantor_lgd(self) -> None:
        """
        P2.43-1: Default psm_lgd_source (option_ii) uses guarantor's supervisory LGD.

        Under PSM option ii, the covered portion is re-weighted using the F-IRB
        supervisory LGD for a DIRECT obligation of the guarantor — i.e., the LGD
        based on the GUARANTOR's seniority, not the borrower's. For this scenario:
            guarantor_seniority = "senior" → Art. 161(1)(a) LGD = 40% (B31)
        PD_guarantor = 0.005, M = 2.5y, EAD = 1,000,000 GBP, scaling = 1.0.

        Expected: risk_weight ≈ 0.619037, rwa ≈ 619,037, expected_loss ≈ 2,000.
        These are the LOWER values (LGD=0.40 < borrower's LGD=0.75).

        Arrange: P2.43 bundle, default IRBPermissions (no psm_lgd_source argument).
        Act:     PipelineOrchestrator().run_with_data(bundle, config).
        Assert:  IRB result row for EXP_P2_43 has expected risk_weight / rwa / EL.
        """
        # Arrange
        bundle = _build_p2_43_bundle()
        config = CalculationConfig.basel_3_1(
            reporting_date=date(2027, 6, 30),
            permission_mode=PermissionMode.IRB,
        )

        # Act
        results = PipelineOrchestrator().run_with_data(bundle, config)
        row = _find_irb_row(results, LOAN_REF)

        # Assert
        actual_rw = row["risk_weight"]
        assert actual_rw == pytest.approx(EXPECTED_RW_OPTION_II, rel=5e-3), (
            f"P2.43-1: risk_weight should be {EXPECTED_RW_OPTION_II:.6f} "
            f"(option_ii default: guarantor LGD=0.40, Art. 161(1)(a) B31 senior). "
            f"Got {actual_rw:.6f}."
        )

        actual_rwa = row["rwa"]
        assert actual_rwa == pytest.approx(EXPECTED_RWA_OPTION_II, rel=5e-3), (
            f"P2.43-1: rwa should be {EXPECTED_RWA_OPTION_II:,.0f} "
            f"(option_ii: LGD=0.40, K×12.5×EAD). Got {actual_rwa:,.0f}."
        )

        actual_el = row["expected_loss"]
        assert actual_el == pytest.approx(EXPECTED_EL_OPTION_II, rel=1e-2), (
            f"P2.43-1: expected_loss should be {EXPECTED_EL_OPTION_II:,.0f} "
            f"(PD=0.005 × LGD=0.40 × EAD=1,000,000). Got {actual_el:,.2f}."
        )

    def test_psm_option_i_uses_borrower_unprotected_lgd(self) -> None:
        """
        P2.43-2: psm_lgd_source="option_i" uses the borrower's own (unprotected) LGD.

        Under PSM option i, the covered portion is re-weighted using the borrower's own
        F-IRB supervisory LGD (unprotected) — i.e., the LGD derived from the BORROWER's
        seniority. For this scenario:
            borrower seniority = "subordinated" → Art. 161(1)(b) LGD = 75%
        PD_guarantor = 0.005 (PSM still substitutes guarantor PD), LGD = 0.75,
        M = 2.5y, EAD = 1,000,000 GBP.

        Expected: risk_weight ≈ 1.160695, rwa ≈ 1,160,695, expected_loss ≈ 3,750.
        These are HIGHER values (LGD=0.75 > option_ii LGD=0.40).

        Anti-regression: rwa > 1,000,000 (distinguishes option_i from option_ii).

        Engine gap: IRBPermissions has no psm_lgd_source field — this test MUST FAIL
        with TypeError at config construction (unexpected keyword argument) until the
        engine-implementer adds the field. That is the intended failure mode.

        Arrange: P2.43 bundle, IRBPermissions with psm_lgd_source="option_i".
        Act:     PipelineOrchestrator().run_with_data(bundle, config).
        Assert:  risk_weight ≈ 1.160695, rwa ≈ 1,160,695, expected_loss ≈ 3,750.
        """
        # Arrange
        bundle = _build_p2_43_bundle()

        # This construction MUST FAIL until engine-implementer adds psm_lgd_source
        # to IRBPermissions. The TypeError is the intended pre-fix failure mode.
        # After fix: IRBPermissions(psm_lgd_source="option_i") accepted, engine routes
        # to borrower's subordinated LGD=0.75 in _apply_parameter_substitution.
        from dataclasses import replace as dc_replace

        base_perms = IRBPermissions.full_irb_b31()
        irb_perms_option_i = dc_replace(base_perms, psm_lgd_source="option_i")

        config = CalculationConfig.basel_3_1(
            reporting_date=date(2027, 6, 30),
            permission_mode=PermissionMode.IRB,
        )
        # Override irb_permissions with option_i variant
        config = dc_replace(config, irb_permissions=irb_perms_option_i)

        # Act
        results = PipelineOrchestrator().run_with_data(bundle, config)
        row = _find_irb_row(results, LOAN_REF)

        # Assert — primary
        actual_rw = row["risk_weight"]
        assert actual_rw == pytest.approx(EXPECTED_RW_OPTION_I, rel=5e-3), (
            f"P2.43-2: risk_weight should be {EXPECTED_RW_OPTION_I:.6f} "
            f"(option_i: borrower subordinated LGD=0.75, Art. 161(1)(b)). "
            f"Got {actual_rw:.6f}."
        )

        actual_rwa = row["rwa"]
        assert actual_rwa == pytest.approx(EXPECTED_RWA_OPTION_I, rel=5e-3), (
            f"P2.43-2: rwa should be {EXPECTED_RWA_OPTION_I:,.0f} "
            f"(option_i: LGD=0.75, K×12.5×EAD). Got {actual_rwa:,.0f}."
        )

        actual_el = row["expected_loss"]
        assert actual_el == pytest.approx(EXPECTED_EL_OPTION_I, rel=1e-2), (
            f"P2.43-2: expected_loss should be {EXPECTED_EL_OPTION_I:,.0f} "
            f"(PD=0.005 × LGD=0.75 × EAD=1,000,000). Got {actual_el:,.2f}."
        )

        # Anti-regression: option_i must produce materially higher RWA than option_ii
        assert actual_rwa > 1_000_000, (
            f"P2.43-2 anti-regression: option_i rwa must exceed 1,000,000 "
            f"(LGD=0.75 distinguishes from option_ii LGD=0.40). Got {actual_rwa:,.0f}."
        )

    def test_psm_option_i_vs_option_ii_rwa_delta(self) -> None:
        """
        P2.43-3: RWA delta between option_i and option_ii ≈ 541,658.

        The difference arises entirely from the PSM LGD choice:
            option_i  LGD=0.75 → RWA ≈ 1,160,695
            option_ii LGD=0.40 → RWA ≈ 619,037
            delta = 541,658 (≈ 541,424 by engine; within 1% rel tol)

        Anti-regression: rwa_option_i != rwa_option_ii (exact inequality guard —
        a future revert that ignores psm_lgd_source and returns the same value
        for both arms will fail loudly here).

        Arrange: P2.43 bundle run twice — once per psm_lgd_source value.
        Act:     extract rwa from each arm's IRB result row.
        Assert:  |rwa_option_i − rwa_option_ii − 541,658| / 541,658 < 1%.
        """
        # Arrange — option_ii (default): standard config, no psm_lgd_source kwarg
        bundle_ii = _build_p2_43_bundle()
        config_ii = CalculationConfig.basel_3_1(
            reporting_date=date(2027, 6, 30),
            permission_mode=PermissionMode.IRB,
        )
        results_ii = PipelineOrchestrator().run_with_data(bundle_ii, config_ii)
        row_ii = _find_irb_row(results_ii, LOAN_REF)
        rwa_option_ii = row_ii["rwa"]

        # Arrange — option_i: psm_lgd_source="option_i" on IRBPermissions
        # This will FAIL (TypeError) until engine-implementer adds psm_lgd_source field.
        bundle_i = _build_p2_43_bundle()
        from dataclasses import replace as dc_replace

        base_perms = IRBPermissions.full_irb_b31()
        irb_perms_option_i = dc_replace(base_perms, psm_lgd_source="option_i")

        config_i = CalculationConfig.basel_3_1(
            reporting_date=date(2027, 6, 30),
            permission_mode=PermissionMode.IRB,
        )
        config_i = dc_replace(config_i, irb_permissions=irb_perms_option_i)
        results_i = PipelineOrchestrator().run_with_data(bundle_i, config_i)
        row_i = _find_irb_row(results_i, LOAN_REF)
        rwa_option_i = row_i["rwa"]

        # Anti-regression: the two arms must produce different RWA
        assert rwa_option_i != rwa_option_ii, (
            f"P2.43-3: rwa_option_i ({rwa_option_i:,.0f}) must differ from "
            f"rwa_option_ii ({rwa_option_ii:,.0f}) — if equal, psm_lgd_source switch "
            f"is not being respected by the engine."
        )

        # Assert: delta ≈ 541,658
        actual_delta = rwa_option_i - rwa_option_ii
        assert actual_delta == pytest.approx(EXPECTED_RWA_DELTA, rel=1e-2), (
            f"P2.43-3: rwa_option_i − rwa_option_ii should be ≈{EXPECTED_RWA_DELTA:,.0f} "
            f"(LGD=0.75 vs LGD=0.40, same PD=0.005/M=2.5/EAD=1m). "
            f"Got delta = {actual_delta:,.0f} "
            f"(option_i={rwa_option_i:,.0f}, option_ii={rwa_option_ii:,.0f})."
        )


# =============================================================================
# Fixture sanity guards (fast, no pipeline invocation)
# =============================================================================


class TestP243FixtureConstants:
    """Fixture constant sanity checks — no pipeline invocation."""

    def test_p2_43_fixture_both_pds_above_b31_corporate_floor(self) -> None:
        """
        P2.43: both PDs (0.05 and 0.005) are above the B31 corporate floor 0.0005.

        This ensures the scenario isolates the psm_lgd_source switch, not a PD
        floor effect. Both PDs must be well above 0.0005 (Art. 163(1)(a)).
        """
        B31_CORPORATE_PD_FLOOR = 0.0005
        assert PD_BORROWER > B31_CORPORATE_PD_FLOOR, (
            f"Fixture: PD_BORROWER ({PD_BORROWER}) must exceed B31 floor ({B31_CORPORATE_PD_FLOOR})"
        )
        assert PD_GUARANTOR > B31_CORPORATE_PD_FLOOR, (
            f"Fixture: PD_GUARANTOR ({PD_GUARANTOR}) must exceed B31 floor "
            f"({B31_CORPORATE_PD_FLOOR})"
        )

    def test_p2_43_fixture_lgd_option_i_is_borrower_subordinated(self) -> None:
        """
        P2.43: EXPECTED_LGD_BORROWER=0.75 (Art. 161(1)(b) subordinated) drives option_i.

        The large LGD gap between option_i (0.75) and option_ii (0.40) makes the
        test unambiguous — the two arms cannot accidentally produce the same RWA.
        """
        assert pytest.approx(0.75, abs=1e-10) == EXPECTED_LGD_BORROWER, (
            f"Fixture: EXPECTED_LGD_BORROWER should be 0.75 (Art. 161(1)(b)), "
            f"got {EXPECTED_LGD_BORROWER}"
        )

    def test_p2_43_fixture_lgd_option_ii_is_guarantor_senior(self) -> None:
        """
        P2.43: EXPECTED_LGD_OPTION_I_B31=0.40 (Art. 161(1)(a) B31 senior) drives option_ii.

        Note: the fixture names this constant EXPECTED_LGD_OPTION_I_B31 (from the
        regulatory text perspective where option (i) = guarantor senior LGD); the test
        uses it as option_ii (the lower, default path in the engine's IRBPermissions).
        """
        assert pytest.approx(0.40, abs=1e-10) == EXPECTED_LGD_OPTION_I_B31, (
            f"Fixture: EXPECTED_LGD_OPTION_I_B31 should be 0.40 (Art. 161(1)(a) B31), "
            f"got {EXPECTED_LGD_OPTION_I_B31}"
        )

    def test_p2_43_fixture_lgd_option_ii_is_borrower_subordinated(self) -> None:
        """
        P2.43: EXPECTED_LGD_OPTION_II=0.75 (same as borrower's own LGD) drives option_i.

        Both regulatory option_ii and EXPECTED_LGD_BORROWER/EXPECTED_LGD_OPTION_II
        resolve to 0.75 because the borrower's obligation is subordinated.
        """
        assert pytest.approx(0.75, abs=1e-10) == EXPECTED_LGD_OPTION_II, (
            f"Fixture: EXPECTED_LGD_OPTION_II should be 0.75 (subordinated), "
            f"got {EXPECTED_LGD_OPTION_II}"
        )

    def test_p2_43_fixture_ead_is_one_million(self) -> None:
        """P2.43: EAD = 1,000,000 (drawn_amount, no interest, no undrawn)."""
        assert pytest.approx(1_000_000.0, abs=0.01) == EAD, (
            f"Fixture: EAD should be 1,000,000, got {EAD}"
        )

    def test_p2_43_parquet_files_exist(self) -> None:
        """P2.43: all required parquet fixture files must be present on disk."""
        for name in ("facility", "loan", "counterparty", "guarantee", "rating", "model_permission"):
            path = _FIXTURES_DIR / f"{name}.parquet"
            assert path.exists(), (
                f"P2.43 fixture file missing: {path}. "
                f"Run: uv run python tests/fixtures/p2_43/p2_43.py"
            )
