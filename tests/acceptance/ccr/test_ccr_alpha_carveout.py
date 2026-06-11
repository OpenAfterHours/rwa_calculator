"""
CCR-ALPHA-1 / CCR-ALPHA-2 / CCR-ALPHA-3 / P8.28: per-counterparty α=1.0 carve-out.

Pipeline position:
    Loader -> HierarchyResolver -> CCRStage (apply_alpha_gate  ← NOT YET WIRED)
    -> Classifier -> CRM -> SA Calculator -> OutputAggregator

Key responsibilities:
- Prove that the engine selects α=1.0 for non-financial / pension-scheme
  counterparties (EMIR Art. 2(9) / 2(10)) and α=1.4 for financial counterparties.
- CCR-ALPHA-1 (counterparty_type="non_financial", corporate):
    ead_ccr == α × pfe_addon = 1.0 × 3_914_298.228 = 3_914_298.228
- CCR-ALPHA-2 (counterparty_type="pension_scheme", corporate):
    ead_ccr == 1.0 × 3_914_298.228 = 3_914_298.228  (same as ALPHA-1)
- CCR-ALPHA-3 (counterparty_type="financial", institution CQS 2, anti-degenerate control):
    ead_ccr == 1.4 × 3_914_298.228 = 5_480_017.519  (= live CCR-A1 ead_ccr)
    risk_weight == 0.50 (CRR Art. 120(1) Table 3)
    rwa_final   == 2_740_008.759

Load-bearing RED assertions (fail on the unfixed pipeline that applies α=1.4 uniformly):
    (1) ead(ALPHA-1) == P828_EAD_CARVE_OUT (== 3_914_298.228)
        unfixed gives 5_480_017.519 → AssertionError: 5_480_017.519 != 3_914_298.228
    (2) ead(ALPHA-1) < ead(ALPHA-3) STRICT (canary)
        unfixed gives all-equal 5_480_017.519 → AssertionError: 5_480_017.519 < 5_480_017.519
    (3) ead(ALPHA-1) / ead(ALPHA-3) == approx(1.0/1.4, rel=1e-9)
        unfixed gives ratio 1.0 → AssertionError: 1.0 != approx(0.71428...)
    (4) alpha_applied(ALPHA-1) == 1.0
        unfixed: column absent → row.get("alpha_applied") is None
        → AssertionError: None != 1.0

References:
    - CRR Art. 274(2) — EAD = α × (RC + PFE); α=1.4 default; α=1.0 carve-out
    - EMIR Art. 2(9) — non-financial counterparty definition
    - EMIR Art. 2(10) — pension scheme arrangement definition
    - BCBS CRE52.1 — supervisory α=1.4 (1.0 carve-out for qualifying CPs)
    - CRR Art. 120(1) Table 3 — institution CQS 2 → 50% SA RW
    - tests/fixtures/ccr/p828_alpha_builder.py — CCR-ALPHA-1/2/3 fixture builders
    - tests/expected_outputs/ccr/CCR-A1.json — authoritative EAD / RWA anchors
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.ccr.p828_alpha_builder import (
    P828_ALPHA_CARVE_OUT,
    P828_ALPHA_STANDARD,
    P828_EAD_CARVE_OUT,
    P828_EAD_FINANCIAL,
    P828_NS_FIN_ID,
    P828_NS_NFC_ID,
    P828_NS_PENSION_ID,
    P828_PFE_ADDON,
    P828_RATIO,
    build_p828_bundle,
    build_p828_two_counterparty_book,
)

# ---------------------------------------------------------------------------
# Shared pipeline config
# ---------------------------------------------------------------------------

#: CRR era reporting date — must be < 2027-01-01 so CRR SA risk weights apply.
_REPORTING_DATE: date = date(2026, 1, 15)


def _make_config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def alpha1_result_bundle():
    """
    Run CCR-ALPHA-1 (non_financial, α=1.0) through the full CRR SA pipeline.

    Returns AggregatedResultBundle for structural assertions.
    Module-scoped: pipeline runs once; all ALPHA-1 tests reuse the result.

    Arrange:
        - Counterparty CP-NFC-01: entity_type="corporate", counterparty_type="non_financial"
        - NS-NFC-01: legally enforceable, unmargined
        - Trade T-NFC-01: 10y GBP IR swap, GBP 100m, MtM=0 (CCR-A1 economics)
    """
    # Arrange
    bundle = build_p828_bundle("non_financial")
    config = _make_config()

    # Act
    return PipelineOrchestrator().run_with_data(bundle, config)


@pytest.fixture(scope="module")
def alpha2_result_bundle():
    """
    Run CCR-ALPHA-2 (pension_scheme, α=1.0) through the full CRR SA pipeline.

    Returns AggregatedResultBundle for structural assertions.

    Arrange:
        - Counterparty CP-PENSION-01: entity_type="corporate", counterparty_type="pension_scheme"
        - NS-PENSION-01: legally enforceable, unmargined
        - Trade T-PENSION-01: same CCR-A1 trade economics as ALPHA-1
    """
    # Arrange
    bundle = build_p828_bundle("pension_scheme")
    config = _make_config()

    # Act
    return PipelineOrchestrator().run_with_data(bundle, config)


@pytest.fixture(scope="module")
def alpha3_result_bundle():
    """
    Run CCR-ALPHA-3 (financial, α=1.4) through the full CRR SA pipeline.

    This is the anti-degenerate control — reproduces the live CCR-A1 EAD.

    Arrange:
        - Counterparty CP-FIN-01: entity_type="institution", institution_cqs=2,
          counterparty_type="financial"
        - NS-FIN-01: legally enforceable, unmargined
        - Trade T-FIN-01: same CCR-A1 trade economics as ALPHA-1/2
    """
    # Arrange
    bundle = build_p828_bundle("financial")
    config = _make_config()

    # Act
    return PipelineOrchestrator().run_with_data(bundle, config)


@pytest.fixture(scope="module")
def two_cp_result_bundle():
    """
    Run the 2-counterparty keyed-join regression book through the pipeline.

    Returns AggregatedResultBundle for structural assertions.

    Arrange:
        - CP-NFC-01 (non_financial, corporate)     → NS-NFC-01  → T-NFC-01
        - CP-FIN-01 (financial,     institution)   → NS-FIN-01  → T-FIN-01
    """
    # Arrange
    bundle = build_p828_two_counterparty_book()
    config = _make_config()

    # Act
    return PipelineOrchestrator().run_with_data(bundle, config)


def _locate_ccr_row(result_bundle, ns_id: str, scenario_label: str) -> dict:
    """
    Locate the single synthetic CCR exposure row for the given netting-set ID.

    The pipeline emits one row per netting set with:
        exposure_reference == "ccr__<ns_id>"

    Fails with a clear assertion message if the row is absent.
    """
    df = result_bundle.results.collect()
    expected_ref = f"ccr__{ns_id}"
    rows = df.filter(pl.col("exposure_reference") == expected_ref).to_dicts()
    assert len(rows) == 1, (
        f"{scenario_label}: expected exactly 1 CCR exposure row with "
        f"exposure_reference={expected_ref!r}, got {len(rows)}. "
        f"All ccr__ references: "
        f"{df.filter(pl.col('exposure_reference').str.starts_with('ccr__'))['exposure_reference'].to_list()!r}. "
        "The CCR pipeline adapter must emit one synthetic row per netting set."
    )
    return rows[0]


@pytest.fixture(scope="module")
def alpha1_ccr_row(alpha1_result_bundle) -> dict:
    """Return the single CCR exposure row for CCR-ALPHA-1 (NS-NFC-01)."""
    return _locate_ccr_row(alpha1_result_bundle, P828_NS_NFC_ID, "CCR-ALPHA-1")


@pytest.fixture(scope="module")
def alpha2_ccr_row(alpha2_result_bundle) -> dict:
    """Return the single CCR exposure row for CCR-ALPHA-2 (NS-PENSION-01)."""
    return _locate_ccr_row(alpha2_result_bundle, P828_NS_PENSION_ID, "CCR-ALPHA-2")


@pytest.fixture(scope="module")
def alpha3_ccr_row(alpha3_result_bundle) -> dict:
    """Return the single CCR exposure row for CCR-ALPHA-3 (NS-FIN-01)."""
    return _locate_ccr_row(alpha3_result_bundle, P828_NS_FIN_ID, "CCR-ALPHA-3")


@pytest.fixture(scope="module")
def two_cp_ccr_rows(two_cp_result_bundle) -> list[dict]:
    """Return all CCR exposure rows from the 2-counterparty result."""
    df = two_cp_result_bundle.results.collect()
    return df.filter(pl.col("exposure_reference").str.starts_with("ccr__")).to_dicts()


# ---------------------------------------------------------------------------
# CCR-ALPHA-1 acceptance tests (non_financial, expected α=1.0)
# ---------------------------------------------------------------------------


class TestCCRAlpha1NonFinancial:
    """
    CCR-ALPHA-1 / P8.28: four acceptance assertions for the non-financial carve-out.

    Pin 1 (LOAD-BEARING RED) — ead_ccr == P828_EAD_CARVE_OUT (3_914_298.228).
        Unfixed pipeline applies α=1.4 uniformly → actual 5_480_017.519.
        Expected failure: AssertionError: 5_480_017.519 != approx(3_914_298.228)

    Pin 2 — pfe_addon == P828_PFE_ADDON (3_914_298.228), rel=1e-6.
        Passes on the unfixed pipeline (PFE is α-independent).

    Pin 3 — ead_final == ead_ccr (EAD not mutated after α step).
        Passes on unfixed (both contain the wrong 5_480_017.519 value).

    Pin 4 — alpha_applied == 1.0 (audit column).
        alpha_applied absent → row.get(...) == None → AssertionError: None != 1.0
    """

    def test_ccr_alpha1_ead_equals_carve_out(self, alpha1_ccr_row: dict) -> None:
        """
        CCR-ALPHA-1: ead_ccr == 1.0 × (0 + pfe_addon) = 3_914_298.228.

        Arrange:
            CP-NFC-01 (non_financial, EMIR Art. 2(9)), NS-NFC-01, unmargined,
            RC=0 (MtM=0, no collateral), pfe_addon=3_914_298.228.
        Act:
            Full CRR SA pipeline via PipelineOrchestrator.
        Assert:
            ead_ccr == approx(3_914_298.228, rel=1e-6).

        This is the primary load-bearing RED assertion for P8.28.
        The unfixed engine applies α=1.4 uniformly, yielding:
            ead_ccr = 1.4 × 3_914_298.228 = 5_480_017.519

        Expected failure mode on the unfixed pipeline:
            assert 5_480_017.519 == approx(3_914_298.228 ± ...)

        References:
            CRR Art. 274(2) second sub-paragraph — α=1.0 for non-financial CPs.
            EMIR Art. 2(9) — non-financial counterparty definition.
        """
        # Arrange
        expected_ead = P828_EAD_CARVE_OUT  # 3_914_298.228

        # Assert
        actual_ead = alpha1_ccr_row["ead_ccr"]
        assert actual_ead == pytest.approx(expected_ead, rel=1e-6), (
            f"CCR-ALPHA-1: expected ead_ccr={expected_ead:,.3f} (α=1.0 × pfe_addon), "
            f"got {actual_ead:,.3f}. "
            f"The unfixed engine applies α={P828_ALPHA_STANDARD} uniformly, yielding "
            f"ead_ccr={P828_EAD_FINANCIAL:,.3f} ({P828_ALPHA_STANDARD} × {P828_PFE_ADDON:,.3f}). "
            f"P8.28 fix: join counterparty_type onto the NS frame and select α=1.0 "
            f"for non_financial (EMIR Art. 2(9)) and pension_scheme (EMIR Art. 2(10)) CPs. "
            "CRR Art. 274(2): α=1.0 carve-out for non-financial counterparties."
        )

    def test_ccr_alpha1_pfe_addon(self, alpha1_ccr_row: dict) -> None:
        """
        CCR-ALPHA-1: pfe_addon == 3_914_298.228 (SF_IR=0.005, 10y tenor, GBP 100m).

        pfe_addon is α-independent — it is the raw SA-CCR add-on before α scaling.
        This assertion passes on the unfixed pipeline but guards against regressions.

        References: CRR Art. 278, Art. 280a (SF_IR = 0.005).
        """
        # Arrange
        expected_pfe = P828_PFE_ADDON  # 3_914_298.228

        # Assert
        actual_pfe = alpha1_ccr_row["pfe_addon"]
        assert actual_pfe == pytest.approx(expected_pfe, rel=1e-6), (
            f"CCR-ALPHA-1: expected pfe_addon={expected_pfe:,.3f}, "
            f"got {actual_pfe:,.3f}. "
            "pfe_addon is α-independent (computed before α scaling). "
            "CRR Art. 278: PFE = multiplier × AddOn_aggregate; Art. 280a: SF_IR=0.005."
        )

    def test_ccr_alpha1_ead_final_equals_ead_ccr(self, alpha1_ccr_row: dict) -> None:
        """
        CCR-ALPHA-1: ead_final must equal ead_ccr — EAD is not mutated after the α step.

        The α-carve-out affects ead_ccr at the SA-CCR stage; ead_final is a pass-through.

        References: CRR Art. 274(2); standard pipeline EAD propagation.
        """
        # Arrange / Act
        ead_ccr = alpha1_ccr_row["ead_ccr"]
        ead_final = alpha1_ccr_row["ead_final"]

        # Assert
        assert ead_final == pytest.approx(ead_ccr, rel=1e-9), (
            f"CCR-ALPHA-1: ead_final ({ead_final:,.3f}) must equal ead_ccr ({ead_ccr:,.3f}). "
            "The α-carve-out must only affect ead_ccr; ead_final must not be further mutated."
        )

    def test_ccr_alpha1_alpha_applied_is_one(self, alpha1_ccr_row: dict) -> None:
        """
        CCR-ALPHA-1: alpha_applied audit column must equal 1.0.

        The engine does NOT yet emit this column (P8.28 is unimplemented).
        Read defensively via row.get("alpha_applied") so the failure is a clean
        AssertionError (None != 1.0), NOT a KeyError.

        Expected failure mode on the unfixed pipeline:
            assert None == 1.0
            (column absent — engine-implementer must add it)

        References: CRR Art. 274(2) — α scalar per counterparty type.
        """
        # Arrange
        expected_alpha = P828_ALPHA_CARVE_OUT  # 1.0

        # Assert
        actual_alpha = alpha1_ccr_row.get("alpha_applied")
        assert actual_alpha == expected_alpha, (
            f"CCR-ALPHA-1: expected alpha_applied=={expected_alpha} (non-financial carve-out, "
            f"CRR Art. 274(2) / EMIR Art. 2(9)), got {actual_alpha!r}. "
            "The 'alpha_applied' audit column is not yet emitted by the engine. "
            "P8.28 fix: add alpha_applied to the CCR synthetic row (1.0 for "
            "non_financial/pension_scheme, 1.4 for financial)."
        )


# ---------------------------------------------------------------------------
# CCR-ALPHA-2 acceptance tests (pension_scheme, expected α=1.0)
# ---------------------------------------------------------------------------


class TestCCRAlpha2PensionScheme:
    """
    CCR-ALPHA-2 / P8.28: two acceptance assertions for the pension-scheme carve-out.

    Pin 1 (LOAD-BEARING RED) — ead_ccr == P828_EAD_CARVE_OUT (3_914_298.228).
        Unfixed pipeline applies α=1.4 → actual 5_480_017.519.

    Pin 2 — alpha_applied == 1.0 (audit column absent → None != 1.0).

    EMIR Art. 2(10) pension-scheme arrangements qualify for the same α=1.0
    carve-out as non-financial counterparties (EMIR Art. 2(9)).
    """

    def test_ccr_alpha2_ead_equals_carve_out(self, alpha2_ccr_row: dict) -> None:
        """
        CCR-ALPHA-2: ead_ccr == 1.0 × (0 + pfe_addon) = 3_914_298.228.

        Arrange:
            CP-PENSION-01 (pension_scheme, EMIR Art. 2(10)), NS-PENSION-01,
            unmargined, RC=0, pfe_addon=3_914_298.228.
        Act:
            Full CRR SA pipeline via PipelineOrchestrator.
        Assert:
            ead_ccr == approx(3_914_298.228, rel=1e-6).

        Primary RED assertion for CCR-ALPHA-2.
        Unfixed: ead_ccr == 5_480_017.519 (α=1.4 applied uniformly).

        References:
            CRR Art. 274(2) second sub-paragraph — α=1.0 carve-out.
            EMIR Art. 2(10) — pension scheme arrangement.
        """
        # Arrange
        expected_ead = P828_EAD_CARVE_OUT  # 3_914_298.228

        # Assert
        actual_ead = alpha2_ccr_row["ead_ccr"]
        assert actual_ead == pytest.approx(expected_ead, rel=1e-6), (
            f"CCR-ALPHA-2: expected ead_ccr={expected_ead:,.3f} (α=1.0, pension scheme), "
            f"got {actual_ead:,.3f}. "
            f"Unfixed engine applies α={P828_ALPHA_STANDARD} uniformly → "
            f"{P828_EAD_FINANCIAL:,.3f}. "
            "P8.28 fix: pension_scheme counterparty_type must also map to α=1.0 "
            "(EMIR Art. 2(10)). CRR Art. 274(2) second sub-paragraph."
        )

    def test_ccr_alpha2_alpha_applied_is_one(self, alpha2_ccr_row: dict) -> None:
        """
        CCR-ALPHA-2: alpha_applied audit column must equal 1.0.

        Pension-scheme arrangements (EMIR Art. 2(10)) qualify for the same α=1.0
        carve-out as non-financial counterparties. Column absent on unfixed pipeline.

        Expected failure mode:
            assert None == 1.0

        References: CRR Art. 274(2); EMIR Art. 2(10).
        """
        # Arrange
        expected_alpha = P828_ALPHA_CARVE_OUT  # 1.0

        # Assert
        actual_alpha = alpha2_ccr_row.get("alpha_applied")
        assert actual_alpha == expected_alpha, (
            f"CCR-ALPHA-2: expected alpha_applied=={expected_alpha} (pension scheme, "
            f"EMIR Art. 2(10)), got {actual_alpha!r}. "
            "alpha_applied column not yet emitted — P8.28 fix required."
        )


# ---------------------------------------------------------------------------
# CCR-ALPHA-3 acceptance tests (financial, expected α=1.4, control path)
# ---------------------------------------------------------------------------


class TestCCRAlpha3FinancialControl:
    """
    CCR-ALPHA-3 / P8.28: regression guard for the standard α=1.4 financial path.

    This control scenario PASSES on the unfixed pipeline (α=1.4 is the current
    uniform default). It guards against the engine-implementer accidentally
    lowering α for financial counterparties while fixing ALPHA-1/2.

    Pin 1 — ead_ccr == P828_EAD_FINANCIAL (5_480_017.519)  — should pass now.
    Pin 2 — alpha_applied == 1.4 (audit column absent → RED)  — fails until wired.

    NOTE — risk_weight / rwa_final assertions omitted for ALPHA-3:
        The p828_alpha_builder financial CP carries institution_cqs=2 but no
        external ratings row. The SA institution risk-weight lookup uses the ``cqs``
        column populated from the ratings join; the cp_institution_cqs→cqs coalescing
        in namespace.py applies only for MDB and non-QCCP CCP entity types, not plain
        institution. Without a ratings row the engine applies the unrated fallback
        (CRR Art. 121 → 100% → actual rw=1.0). Asserting rw==0.50 would fail for the
        WRONG reason (missing ratings fixture, not broken α logic). These assertions
        are therefore deferred — they belong in a separate test file that also supplies
        a ratings row for CP-FIN-01. P8.28 scope is α selection; CQS lookup is P8.1.
    """

    def test_ccr_alpha3_ead_equals_financial(self, alpha3_ccr_row: dict) -> None:
        """
        CCR-ALPHA-3: ead_ccr == 1.4 × (0 + pfe_addon) = 5_480_017.519.

        This is the anti-degenerate control: equals the live CCR-A1 ead_ccr.
        If the engine-implementer accidentally applies α=1.0 to financial CPs,
        this test will fail, catching the regression before merge.

        References:
            CRR Art. 274(2) — α=1.4 default for financial counterparties.
            tests/expected_outputs/ccr/CCR-A1.json — authoritative ead_ccr anchor.
        """
        # Arrange
        expected_ead = P828_EAD_FINANCIAL  # 5_480_017.519

        # Assert
        actual_ead = alpha3_ccr_row["ead_ccr"]
        assert actual_ead == pytest.approx(expected_ead, rel=1e-6), (
            f"CCR-ALPHA-3: expected ead_ccr={expected_ead:,.3f} (α=1.4, financial CP), "
            f"got {actual_ead:,.3f}. "
            "CRR Art. 274(2): α=1.4 is the default for financial counterparties. "
            "P8.28 fix must NOT lower α for financial CPs — this test guards that regression."
        )

    def test_ccr_alpha3_alpha_applied_is_14(self, alpha3_ccr_row: dict) -> None:
        """
        CCR-ALPHA-3: alpha_applied audit column must equal 1.4.

        Column absent on unfixed pipeline. Defensive .get() avoids KeyError.

        Expected failure mode (column absent):
            assert None == 1.4

        References: CRR Art. 274(2) — α=1.4 default.
        """
        # Arrange
        expected_alpha = P828_ALPHA_STANDARD  # 1.4

        # Assert
        actual_alpha = alpha3_ccr_row.get("alpha_applied")
        assert actual_alpha == expected_alpha, (
            f"CCR-ALPHA-3: expected alpha_applied=={expected_alpha} (financial CP, "
            f"CRR Art. 274(2) default), got {actual_alpha!r}. "
            "alpha_applied column not yet emitted — P8.28 fix required."
        )


# ---------------------------------------------------------------------------
# Cross-scenario invariant tests
# ---------------------------------------------------------------------------


class TestCCRAlphaInvariants:
    """
    Cross-scenario invariants / P8.28: three canary assertions.

    Invariant 1 (LOAD-BEARING RED) — ead(ALPHA-1) == ead(ALPHA-2) rel=1e-9.
        Both non-financial and pension-scheme share identical trade economics
        and α=1.0. On the unfixed pipeline both equal 5_480_017.519 so this
        passes trivially — it will guard against regressions post-fix.

    Invariant 2 (LOAD-BEARING RED) — ead(ALPHA-1) < ead(ALPHA-3) STRICT.
        Canary: the unfixed pipeline gives all three equal 5_480_017.519 →
        AssertionError: not (5_480_017.519 < 5_480_017.519)

    Invariant 3 (LOAD-BEARING RED) — ead(ALPHA-1) / ead(ALPHA-3) == approx(1.0/1.4).
        Unfixed: ratio == 1.0 → AssertionError: 1.0 != approx(0.71428...)
    """

    def test_alpha1_ead_equals_alpha2_ead(self, alpha1_ccr_row: dict, alpha2_ccr_row: dict) -> None:
        """
        CCR-ALPHA-1 and CCR-ALPHA-2 must have identical ead_ccr (rel=1e-9).

        Both scenarios share identical trade economics and both qualify for α=1.0
        (non-financial EMIR Art. 2(9) and pension-scheme EMIR Art. 2(10)).

        This invariant passes on the unfixed pipeline (both erroneously equal
        5_480_017.519) but is a regression guard post-fix.

        References: CRR Art. 274(2) — α=1.0 for both counterparty types.
        """
        # Arrange / Act
        ead_alpha1 = alpha1_ccr_row["ead_ccr"]
        ead_alpha2 = alpha2_ccr_row["ead_ccr"]

        # Assert
        assert ead_alpha1 == pytest.approx(ead_alpha2, rel=1e-9), (
            f"CCR-ALPHA-1 and CCR-ALPHA-2 must share identical ead_ccr. "
            f"ALPHA-1 ead_ccr={ead_alpha1:,.3f}, ALPHA-2 ead_ccr={ead_alpha2:,.3f}. "
            "Both non-financial (EMIR Art. 2(9)) and pension-scheme (EMIR Art. 2(10)) "
            "qualify for α=1.0 and share identical trade economics."
        )

    def test_alpha1_ead_strictly_less_than_alpha3_ead(
        self, alpha1_ccr_row: dict, alpha3_ccr_row: dict
    ) -> None:
        """
        ead(ALPHA-1) < ead(ALPHA-3) STRICT — primary canary for the α carve-out.

        Arrange:
            ALPHA-1: non-financial, α=1.0 → ead = 3_914_298.228
            ALPHA-3: financial,     α=1.4 → ead = 5_480_017.519
        Act:
            Full pipeline for each scenario.
        Assert:
            alpha1_ead < alpha3_ead (STRICT inequality).

        This is the PRIMARY RED-state canary. On the unfixed pipeline all three
        scenarios receive α=1.4 uniformly, so all ead_ccr values equal 5_480_017.519.
        The strict inequality fails immediately:
            assert not (5_480_017.519 < 5_480_017.519)

        References:
            CRR Art. 274(2) — α=1.0 carve-out: 28.6% lower EAD than α=1.4.
        """
        # Arrange / Act
        ead_alpha1 = alpha1_ccr_row["ead_ccr"]
        ead_alpha3 = alpha3_ccr_row["ead_ccr"]

        # Assert
        assert ead_alpha1 < ead_alpha3, (
            f"CCR-ALPHA canary: ead(ALPHA-1) must be STRICTLY less than ead(ALPHA-3). "
            f"ead(ALPHA-1)={ead_alpha1:,.3f}, ead(ALPHA-3)={ead_alpha3:,.3f}. "
            f"The unfixed engine applies α=1.4 uniformly → both equal {P828_EAD_FINANCIAL:,.3f}. "
            f"After P8.28 fix: ALPHA-1 ead={P828_EAD_CARVE_OUT:,.3f} (α=1.0), "
            f"ALPHA-3 ead={P828_EAD_FINANCIAL:,.3f} (α=1.4). "
            "CRR Art. 274(2): α=1.0 carve-out gives 28.6% lower EAD. "
            "P8.28 fix: join counterparty_type → α scalar before the EAD multiplication."
        )

    def test_alpha1_to_alpha3_ead_ratio(self, alpha1_ccr_row: dict, alpha3_ccr_row: dict) -> None:
        """
        ead(ALPHA-1) / ead(ALPHA-3) == approx(1.0/1.4, rel=1e-9).

        The α-ratio invariant: EAD is linear in α, so the ratio of EADs equals
        the ratio of alphas (1.0/1.4 ≈ 0.714286).

        Arrange:
            ALPHA-1 ead = α1 × pfe_addon = 1.0 × 3_914_298.228
            ALPHA-3 ead = α3 × pfe_addon = 1.4 × 3_914_298.228
        Act:
            Full pipeline for each scenario.
        Assert:
            ead_alpha1 / ead_alpha3 == approx(1.0/1.4, rel=1e-9).

        Unfixed pipeline: both EADs equal 5_480_017.519 → ratio=1.0.
        Expected failure: assert 1.0 == approx(0.714285..., rel=1e-9)

        References: CRR Art. 274(2) — EAD = α × (RC + PFE) is linear in α.
        """
        # Arrange
        expected_ratio = P828_RATIO  # 1.0 / 1.4

        # Act
        ead_alpha1 = alpha1_ccr_row["ead_ccr"]
        ead_alpha3 = alpha3_ccr_row["ead_ccr"]
        actual_ratio = ead_alpha1 / ead_alpha3

        # Assert
        assert actual_ratio == pytest.approx(expected_ratio, rel=1e-9), (
            f"CCR-ALPHA ratio canary: expected ead(ALPHA-1)/ead(ALPHA-3) == "
            f"{expected_ratio:.9f} (= 1.0/1.4), got {actual_ratio:.9f}. "
            f"ead(ALPHA-1)={ead_alpha1:,.3f}, ead(ALPHA-3)={ead_alpha3:,.3f}. "
            f"The unfixed engine gives ratio=1.0 (both α=1.4). "
            "CRR Art. 274(2): EAD is linear in α, so ratio must equal α1/α3 = 1.0/1.4."
        )


# ---------------------------------------------------------------------------
# Keyed-join guard (2-counterparty book)
# ---------------------------------------------------------------------------


class TestCCRAlphaKeyedJoinGuard:
    """
    Keyed-join regression guard / P8.28: 2-counterparty book assertions.

    A single-trade / single-NS fixture (1×1×1) is degenerate for cross-join
    detection: a cross-join of 1×1×1 frames still produces 1 row, so the
    single-CP scenarios (CCR-ALPHA-1/2/3) do NOT catch a fan-out bug in the
    counterparty_type → alpha join.

    This 2-counterparty book (2 CPs × 2 NSes × 2 trades) is the regression guard:
    - A cross-join of counterparties × netting-sets would produce 4 exposure rows
      instead of 2, failing the row-count pin.
    - Even if the cross-join happens to produce 2 rows (e.g. degenerate projection),
      the wrong alpha_applied would appear on one or both rows.

    Composition:
        CP-NFC-01   (non_financial, corporate)   → NS-NFC-01  → T-NFC-01
        CP-FIN-01   (financial,     institution) → NS-FIN-01  → T-FIN-01

    Expected per-row alpha (post-fix):
        NS-NFC-01:  alpha_applied = 1.0  (non-financial carve-out)
        NS-FIN-01:  alpha_applied = 1.4  (financial standard)
    """

    def test_two_cp_book_produces_exactly_two_ccr_rows(self, two_cp_ccr_rows: list[dict]) -> None:
        """
        Exactly 2 CCR exposure rows must appear in the 2-counterparty book result.

        Arrange:
            2 counterparties, 2 netting sets, 2 trades (all CCR-A1 economics).
        Act:
            Full CRR SA pipeline via PipelineOrchestrator.
        Assert:
            Exactly 2 rows with exposure_reference starting with "ccr__".

        A cross-join fan-out in the counterparty_type → alpha join would produce
        4 rows (2 CP rows × 2 NS rows = fan-out). The single-CP scenarios CANNOT
        catch this because 1×1×1 cross-join still yields 1 row.

        References: CRR Art. 271 — one EAD row per netting set.
        """
        # Arrange
        expected_count = 2

        # Assert
        actual_count = len(two_cp_ccr_rows)
        assert actual_count == expected_count, (
            f"CCR alpha keyed-join guard: expected {expected_count} CCR exposure rows "
            f"(one per netting set), got {actual_count}. "
            f"NS IDs found: "
            f"{[r.get('source_netting_set_id') for r in two_cp_ccr_rows]!r}. "
            f"A cross-join in the counterparty_type→alpha lookup would produce "
            f"{expected_count * expected_count} rows for a {expected_count}-NS book. "
            "Single-CP scenarios (1×1×1) cannot catch this fan-out bug. "
            "P8.28 fix: join counterparties keyed on counterparty_reference so each NS "
            "receives exactly one alpha value."
        )

    def test_two_cp_book_nfc_row_alpha_applied(self, two_cp_ccr_rows: list[dict]) -> None:
        """
        NS-NFC-01 row in the 2-CP book: alpha_applied == 1.0 (non-financial carve-out).

        Defensive .get("alpha_applied") to guard against absent column.
        Column absent → assertion fails with None != 1.0 (clean AssertionError).

        References: CRR Art. 274(2) / EMIR Art. 2(9).
        """
        # Arrange: locate the non-financial NS row
        nfc_rows = [r for r in two_cp_ccr_rows if r.get("source_netting_set_id") == P828_NS_NFC_ID]
        assert len(nfc_rows) == 1, (
            f"CCR alpha keyed-join guard: expected 1 row for NS {P828_NS_NFC_ID!r}, "
            f"got {len(nfc_rows)}. "
            f"All NS IDs: {[r.get('source_netting_set_id') for r in two_cp_ccr_rows]!r}."
        )

        # Assert
        actual_alpha = nfc_rows[0].get("alpha_applied")
        assert actual_alpha == P828_ALPHA_CARVE_OUT, (
            f"CCR alpha keyed-join guard: NS-NFC-01 expected alpha_applied="
            f"{P828_ALPHA_CARVE_OUT} (non-financial carve-out, CRR Art. 274(2)), "
            f"got {actual_alpha!r}. "
            "P8.28 fix: alpha=1.0 must be keyed strictly to NS-NFC-01 (CP-NFC-01), "
            "not leaked to NS-FIN-01 via cross-join."
        )

    def test_two_cp_book_fin_row_alpha_applied(self, two_cp_ccr_rows: list[dict]) -> None:
        """
        NS-FIN-01 row in the 2-CP book: alpha_applied == 1.4 (financial standard).

        Defensive .get("alpha_applied") to guard against absent column.

        References: CRR Art. 274(2) — α=1.4 default.
        """
        # Arrange: locate the financial NS row
        fin_rows = [r for r in two_cp_ccr_rows if r.get("source_netting_set_id") == P828_NS_FIN_ID]
        assert len(fin_rows) == 1, (
            f"CCR alpha keyed-join guard: expected 1 row for NS {P828_NS_FIN_ID!r}, "
            f"got {len(fin_rows)}. "
            f"All NS IDs: {[r.get('source_netting_set_id') for r in two_cp_ccr_rows]!r}."
        )

        # Assert
        actual_alpha = fin_rows[0].get("alpha_applied")
        assert actual_alpha == P828_ALPHA_STANDARD, (
            f"CCR alpha keyed-join guard: NS-FIN-01 expected alpha_applied="
            f"{P828_ALPHA_STANDARD} (financial standard, CRR Art. 274(2) default), "
            f"got {actual_alpha!r}. "
            "P8.28 fix: alpha=1.4 must be keyed strictly to NS-FIN-01 (CP-FIN-01). "
            "If cross-join leaks α=1.0 from NFC counterparty, this fails."
        )
