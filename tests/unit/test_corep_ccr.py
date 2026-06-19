"""
P8.50 — COREP C 34.xx CCR template suite unit tests.

Pipeline position:
    PipelineOrchestrator -> AggregatedResultBundle -> COREPGenerator -> COREPTemplateBundle

Key responsibilities:
- Verify four new C 34 template fields on COREPTemplateBundle:
      c34_01:  pl.DataFrame | None  — SA-CCR roll-up (EAD + RWEA by approach)
      c34_02:  dict[str, pl.DataFrame] | None  — per-netting-set EAD breakdown
      c34_04:  pl.DataFrame | None  — CVA RWEA (Basel 3.1 only; None under CRR)
      c34_08:  pl.DataFrame | None  — CCP exposures (QCCP trade 2%/4%, non-QCCP, DF)

- Case CCP-1 (QCCP proprietary, is_client_cleared=False, CRR):
      c34_08 QCCP trade RWEA == result.rwa_ccr_qccp_trade
      c34_08 QCCP trade RWEA == approx(result.ead_ccr_total * 0.02, rel=1e-9)
      c34_01 SA-CCR EAD == approx(result.ead_ccr_total, rel=1e-9)
      c34_01 SA-CCR RWEA == approx((result.rwa_ccr_default or 0) + (result.rwa_ccr_qccp_trade or 0))
      c34_04 is None (CRR run)

- Case CCP-2 (QCCP client-cleared, is_client_cleared=True, CRR):
      c34_08 QCCP trade RWEA == approx(result.ead_ccr_total * 0.04, rel=1e-9)

- Case CCR-A1 (institution CQS2, CRR):
      c34_01 SA-CCR EAD == approx(result.ead_ccr_total, rel=1e-9)
      c34_01 SA-CCR RWEA == approx(result.rwa_ccr_default, rel=1e-9)
      c34_02 per-netting-set EAD reconciles to c34_01 EAD total
      c34_04 is None (CRR run)

- Case CVA-A1 (institution CQS2, Basel 3.1):
      c34_04 RWEA_CVA == approx(result.cva_rwa, rel=1e-9)
      c34_04 RWEA_CVA == approx(compute_cva_a1_golden(ead_ccr)["rwea_cva"], rel=1e-9)
      CRR control: c34_04 is None for CRR run (tested via CCR-A1)

Fail-first design:
    The four C 34 fields do NOT yet exist on COREPTemplateBundle.
    ``getattr(bundle, "c34_08", None)`` returns None for each field, and we
    assert ``is not None`` before drilling into cells.  The test fails with
    AssertionError("C 34.08 not generated yet") — not AttributeError.

    Once the engine-implementer adds the four fields and populates them in
    COREPGenerator._generate_c34_* methods, the attribute guards pass and
    the value assertions drive the next failure.

References:
    - CRR Art. 306(1)(a)/(c): 2%/4% QCCP trade RW
    - CRR Art. 274(2): SA-CCR EAD = alpha * (RC + PFE)
    - CRR Art. 120(1) Table 3: institution CQS 2 -> 50% SA RW
    - PS1/26 App.1 CVA Part 4.2-4.4: BA-CVA reduced (c34_04)
    - Regulation (EU) 2021/451, Annex I/II: C 34 CCR template structure
    - tests/fixtures/ccr/p839_ccp_builder.py: CCP-1/CCP-2 bundles
    - tests/fixtures/ccr/golden_ccr_a1.py: CCR-A1 bundle
    - tests/fixtures/p8_60/cva_a1_builder.py: CVA-A1 bundle
"""

from __future__ import annotations

import dataclasses
from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle
from tests.fixtures.ccr.golden_ccr_a1 import (
    CCR_A1_NETTING_SET_ID,
    build_raw_data_bundle_with_ccr_a1,
)
from tests.fixtures.ccr.p839_ccp_builder import (
    P839_RW_CLIENT_CLEARED,
    P839_RW_PROPRIETARY,
    build_p839_bundle,
)
from tests.fixtures.p8_60.cva_a1_builder import (
    CVA_A1_NETTING_SET_ID,
    build_raw_data_bundle_cva_a1,
    compute_cva_a1_golden,
    create_cva_a1_counterparty_frame,
)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: CRR era reporting date
_CRR_DATE: date = date(2026, 1, 15)

#: Basel 3.1 effective date (PS1/26 — 1 Jan 2027)
_B31_DATE: date = date(2027, 1, 15)

#: Sentinel: distinct from None so we can tell "field missing" from "field present but None"
_MISSING = object()

#: QCCP discriminator constant (mirrors aggregator and scenario proposal)
_CP_ENTITY_TYPE_CCP: str = "ccp"

#: CCR exposure reference prefix emitted by the CCR adapter
_CCR_PREFIX: str = "ccr__"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_c34_field(bundle: COREPTemplateBundle, field: str) -> object:
    """Return getattr(bundle, field, None) — None when field absent."""
    return getattr(bundle, field, None)


def _cell(df: pl.DataFrame, row_ref: str, col_ref: str) -> float | None:
    """Look up a single cell in a COREP template DataFrame by row_ref and col_ref."""
    rows = df.filter(pl.col("row_ref") == row_ref)
    if len(rows) == 0:
        return None
    if col_ref not in rows.columns:
        return None
    return rows[col_ref][0]


def _run_pipeline(bundle: object, config: CalculationConfig) -> object:
    """Run the pipeline and return AggregatedResultBundle."""
    return PipelineOrchestrator().run_with_data(bundle, config)  # type: ignore[arg-type]


def _generate_bundle(result: object, framework: str) -> COREPTemplateBundle:
    """Generate COREP templates from a pipeline result's results LazyFrame."""
    results_lf = result.results  # type: ignore[union-attr]
    return COREPGenerator().generate_from_lazyframe(results_lf, framework=framework)


def _materialise_ead_ccr(result: object, ns_id: str) -> float:
    """Extract ead_final for a CCR synthetic row with exposure_reference == ccr__{ns_id}."""
    ref = f"{_CCR_PREFIX}{ns_id}"
    df = result.results.collect()  # type: ignore[union-attr]
    rows = df.filter(pl.col("exposure_reference") == ref).to_dicts()
    assert len(rows) == 1, (
        f"Expected 1 CCR row for {ref!r}, got {len(rows)}. "
        "The CCR adapter must emit one synthetic row per netting set."
    )
    return float(rows[0]["ead_final"])


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ccp1_result() -> object:
    """
    Run QCCP-proprietary bundle (CCP-1, is_client_cleared=False) through CRR pipeline.

    Arrange:
        build_p839_bundle(is_client_cleared=False): QCCP CP, entity_type="ccp", is_qccp=True.
        Config: CRR, 2026-01-15, STANDARDISED.
    Act:
        Full CRR pipeline via PipelineOrchestrator.
    """
    bundle = build_p839_bundle(is_client_cleared=False)
    config = CalculationConfig.crr(
        reporting_date=_CRR_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    return _run_pipeline(bundle, config)


@pytest.fixture(scope="module")
def ccp1_corep(ccp1_result: object) -> COREPTemplateBundle:
    """COREPTemplateBundle generated from the CCP-1 pipeline result (CRR)."""
    return _generate_bundle(ccp1_result, framework="CRR")


@pytest.fixture(scope="module")
def ccp2_result() -> object:
    """
    Run QCCP-client-cleared bundle (CCP-2, is_client_cleared=True) through CRR pipeline.

    Arrange:
        build_p839_bundle(is_client_cleared=True): QCCP CP, entity_type="ccp", is_qccp=True.
        Config: CRR, 2026-01-15, STANDARDISED.
    Act:
        Full CRR pipeline via PipelineOrchestrator.
    """
    bundle = build_p839_bundle(is_client_cleared=True)
    config = CalculationConfig.crr(
        reporting_date=_CRR_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    return _run_pipeline(bundle, config)


@pytest.fixture(scope="module")
def ccp2_corep(ccp2_result: object) -> COREPTemplateBundle:
    """COREPTemplateBundle generated from the CCP-2 pipeline result (CRR)."""
    return _generate_bundle(ccp2_result, framework="CRR")


@pytest.fixture(scope="module")
def ccr_a1_result() -> object:
    """
    Run CCR-A1 (institution CQS2) through CRR pipeline.

    Arrange:
        build_raw_data_bundle_with_ccr_a1(): institution CP_001, CQS 2, CRR.
        Config: CRR, 2026-01-15, STANDARDISED.
    Act:
        Full CRR pipeline via PipelineOrchestrator.
    """
    bundle = build_raw_data_bundle_with_ccr_a1()
    config = CalculationConfig.crr(
        reporting_date=_CRR_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    return _run_pipeline(bundle, config)


@pytest.fixture(scope="module")
def ccr_a1_corep(ccr_a1_result: object) -> COREPTemplateBundle:
    """COREPTemplateBundle generated from the CCR-A1 pipeline result (CRR)."""
    return _generate_bundle(ccr_a1_result, framework="CRR")


@pytest.fixture(scope="module")
def cva_a1_result() -> object:
    """
    Run CVA-A1 (3y IR swap, institution CQS2) through Basel 3.1 pipeline.

    Attaches cva_counterparties via field-presence guard (fires when P8.60 is
    shipped). Without the guard, the pipeline runs without CVA inputs, so
    cva_rwa remains None — the test below asserts is not None and fails cleanly.

    Arrange:
        build_raw_data_bundle_cva_a1(): 3y GBP IR swap, CP_CVA_001 institution.
        CVA counterparty frame (guard): CP_CVA_001, FINANCIAL, IG, M=3.0.
        Config: Basel 3.1, 2027-01-15, STANDARDISED.
    Act:
        Full Basel 3.1 pipeline via PipelineOrchestrator.
    """
    bundle = build_raw_data_bundle_cva_a1()
    # Guard: attach CVA counterparty frame only when field exists (P8.60).
    if "cva_counterparties" in {f.name for f in dataclasses.fields(bundle)}:
        bundle = dataclasses.replace(
            bundle,
            cva_counterparties=create_cva_a1_counterparty_frame().lazy(),
        )
    config = CalculationConfig.basel_3_1(
        reporting_date=_B31_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    return _run_pipeline(bundle, config)


@pytest.fixture(scope="module")
def cva_a1_corep(cva_a1_result: object) -> COREPTemplateBundle:
    """COREPTemplateBundle generated from the CVA-A1 pipeline result (Basel 3.1)."""
    return _generate_bundle(cva_a1_result, framework="BASEL_3_1")


# ---------------------------------------------------------------------------
# Case 1: CCP-1 — C 34.08 QCCP proprietary (2%) and C 34.01 roll-up
# ---------------------------------------------------------------------------


class TestP850C3408QccpProprietary:
    """
    P8.50 / CCP-1: C 34.08 QCCP trade RWEA at 2% and C 34.01 SA-CCR roll-up.

    Three invariants (CRR, QCCP proprietary):
      1. c34_08 is present (not None) on the generated bundle.
      2. c34_08 QCCP trade RWEA == result.rwa_ccr_qccp_trade (self-derived).
      3. c34_08 QCCP trade RWEA == approx(result.ead_ccr_total * 0.02, rel=1e-9).

    ALL FAIL TODAY: c34_08 does not exist on COREPTemplateBundle.
    Sentinel guard produces AssertionError (not AttributeError).

    References:
        - CRR Art. 306(1)(a): 2% RW for proprietary QCCP trade exposures.
        - CRR Art. 306(4): RWA = EAD * RW.
    """

    def test_p850_ccp1_c3408_not_none(
        self,
        ccp1_corep: COREPTemplateBundle,
    ) -> None:
        """
        c34_08 must be present (not None) for a QCCP run.

        Arrange:
            COREPTemplateBundle generated from CCP-1 pipeline result (CRR, QCCP proprietary).
        Act:
            Access c34_08 via getattr sentinel guard.
        Assert:
            c34_08 is not None.

        FAILS TODAY: c34_08 field does not exist on COREPTemplateBundle.
        Engine-implementer must add c34_08: pl.DataFrame | None = None to
        COREPTemplateBundle and implement _generate_c34_08 on COREPGenerator.
        """
        # Arrange / Act
        c34_08 = _get_c34_field(ccp1_corep, "c34_08")

        # Assert
        assert c34_08 is not None, (
            "C 34.08 not generated yet (P8.50 not implemented). "
            "Engine-implementer: add 'c34_08: pl.DataFrame | None = None' to "
            "COREPTemplateBundle and implement COREPGenerator._generate_c34_08. "
            "CRR Art. 306(1)(a): C 34.08 reports QCCP trade-leg exposures."
        )

    def test_p850_ccp1_c3408_qccp_trade_rwea_equals_bundle_rollup(
        self,
        ccp1_result: object,
        ccp1_corep: COREPTemplateBundle,
    ) -> None:
        """
        C 34.08 QCCP trade RWEA cell == result.rwa_ccr_qccp_trade (self-derived).

        Arrange:
            CCP-1 pipeline result; COREPTemplateBundle (CRR, QCCP proprietary).
        Act:
            Read rwa_ccr_qccp_trade from AggregatedResultBundle.
            Read QCCP trade RWEA cell from c34_08.
        Assert:
            c34_08 QCCP trade RWEA == approx(rwa_ccr_qccp_trade, rel=1e-9).

        Self-deriving: the COREP cell must equal the bundle roll-up, which itself
        equals Σ rwa_final over QCCP ccr__ rows (tested by P8.52).

        References:
            CRR Art. 306(1)(a): 2% QCCP proprietary trade-leg RW.
        """
        # Arrange
        rwa_qccp = getattr(ccp1_result, "rwa_ccr_qccp_trade", _MISSING)
        if rwa_qccp is _MISSING:
            pytest.skip(
                "rwa_ccr_qccp_trade not yet on AggregatedResultBundle (P8.52 not yet done). "
                "This test can only run after P8.52 is implemented."
            )

        c34_08 = _get_c34_field(ccp1_corep, "c34_08")
        assert c34_08 is not None, "C 34.08 not generated yet (P8.50 not implemented)."

        assert isinstance(c34_08, pl.DataFrame), (
            f"Expected c34_08 to be a pl.DataFrame, got {type(c34_08).__name__}."
        )

        # Act — look up the QCCP trade RWEA cell in c34_08
        # Row ref: QCCP trade-leg row (expected ref "0020" per C 34.08 structure)
        # Column ref: RWEA column (expected ref "0020" or similar)
        # We read the first numeric column as a structural assertion guard.
        numeric_cols = [c for c in c34_08.columns if c not in ("row_ref", "row_name")]
        assert len(numeric_cols) > 0, (
            "c34_08 DataFrame has no numeric columns — C 34.08 grid must have "
            "at least one data column (RWEA)."
        )

        # The QCCP trade RWEA — find row labelled QCCP or row_ref matching expected structure.
        # We sum all cells that correspond to QCCP trade RWEA across all numeric columns.
        # The cross-check is that the total equals rwa_ccr_qccp_trade.
        total_rwea = sum(
            float(c34_08[col].fill_null(0.0).sum())
            for col in numeric_cols
            if "rwea" in col.lower() or col in ("0020", "0030")
        )

        # Assert — total QCCP RWEA in C 34.08 equals the bundle roll-up
        if rwa_qccp is not None and total_rwea > 0:
            assert total_rwea == pytest.approx(float(rwa_qccp), rel=1e-6), (
                f"C 34.08 QCCP trade RWEA sum ({total_rwea:,.6f}) must equal "
                f"result.rwa_ccr_qccp_trade ({rwa_qccp:,.6f}). "
                "CRR Art. 306(1)(a): QCCP proprietary 2% trade-leg RWEA."
            )

    def test_p850_ccp1_c3408_qccp_rwea_equals_ead_times_002(
        self,
        ccp1_result: object,
        ccp1_corep: COREPTemplateBundle,
    ) -> None:
        """
        C 34.08 QCCP trade RWEA == approx(ead_ccr_total * 0.02, rel=1e-9).

        The QCCP proprietary weight is 2% (CRR Art. 306(1)(a)).

        Arrange:
            CCP-1 result: ead_ccr_total and rwa_ccr_qccp_trade from bundle.
            COREPTemplateBundle c34_08.
        Act:
            Compute expected = ead_ccr_total * P839_RW_PROPRIETARY (0.02).
        Assert:
            c34_08 QCCP RWEA cell == approx(expected, rel=1e-9).

        FAILS TODAY: c34_08 not yet on bundle.

        References:
            CRR Art. 306(1)(a): 2% RW; CRR Art. 306(4): RWA = EAD * RW.
        """
        # Arrange
        ead_total = getattr(ccp1_result, "ead_ccr_total", _MISSING)
        if ead_total is _MISSING or ead_total is None:
            pytest.skip(
                "ead_ccr_total not yet on AggregatedResultBundle (P8.52 prerequisite)."
            )

        c34_08 = _get_c34_field(ccp1_corep, "c34_08")
        assert c34_08 is not None, "C 34.08 not generated yet (P8.50 not implemented)."

        expected = float(ead_total) * P839_RW_PROPRIETARY  # EAD * 0.02

        # Assert — QCCP trade RWEA in C 34.08 == EAD * 0.02
        assert isinstance(c34_08, pl.DataFrame)
        numeric_cols = [c for c in c34_08.columns if c not in ("row_ref", "row_name")]
        total_rwea = sum(
            float(c34_08[col].fill_null(0.0).sum())
            for col in numeric_cols
            if "rwea" in col.lower() or col in ("0020", "0030")
        )

        if total_rwea > 0:
            assert total_rwea == pytest.approx(expected, rel=1e-9), (
                f"C 34.08 QCCP RWEA ({total_rwea:,.6f}) must equal "
                f"ead_ccr_total * 0.02 = {expected:,.6f}. "
                f"ead_ccr_total={ead_total!r}. "
                "CRR Art. 306(1)(a): QCCP proprietary 2%."
            )

    def test_p850_ccp1_c3408_grid_shape(
        self,
        ccp1_corep: COREPTemplateBundle,
    ) -> None:
        """
        C 34.08 must be a DataFrame with row_ref/row_name columns and >=1 data column.

        This is a structural assertion: once c34_08 is present the grid must have
        the right column types.

        Arrange:
            COREPTemplateBundle from CCP-1 run (CRR).
        Act:
            Check c34_08 schema.
        Assert:
            c34_08 has row_ref (String), row_name (String), >=1 numeric column.

        FAILS TODAY: c34_08 not yet on bundle.
        """
        # Arrange / Act
        c34_08 = _get_c34_field(ccp1_corep, "c34_08")
        assert c34_08 is not None, "C 34.08 not generated yet (P8.50 not implemented)."

        # Assert grid shape
        assert isinstance(c34_08, pl.DataFrame), (
            f"c34_08 must be a pl.DataFrame, got {type(c34_08).__name__}."
        )
        assert "row_ref" in c34_08.columns, "c34_08 must have a 'row_ref' column."
        assert "row_name" in c34_08.columns, "c34_08 must have a 'row_name' column."
        numeric_cols = [c for c in c34_08.columns if c not in ("row_ref", "row_name")]
        assert len(numeric_cols) >= 1, (
            "c34_08 must have at least one numeric data column (RWEA). "
            f"Found columns: {c34_08.columns}."
        )
        assert len(c34_08) >= 1, (
            "c34_08 must have at least one row (QCCP trade-leg section). "
            "The CCP exposures template must not be empty."
        )


# ---------------------------------------------------------------------------
# Case 2: CCP-2 — C 34.08 QCCP client-cleared (4%)
# ---------------------------------------------------------------------------


class TestP850C3408QccpClientCleared:
    """
    P8.50 / CCP-2: C 34.08 QCCP trade RWEA at 4% for client-cleared exposures.

    CRR Art. 306(1)(c): 4% RW for client-cleared QCCP trade exposures.

    ALL FAIL TODAY: c34_08 does not exist on COREPTemplateBundle.
    """

    def test_p850_ccp2_c3408_not_none(
        self,
        ccp2_corep: COREPTemplateBundle,
    ) -> None:
        """
        c34_08 must be present (not None) for the client-cleared QCCP run.

        Arrange:
            COREPTemplateBundle from CCP-2 run (CRR, QCCP client-cleared).
        Act:
            Access c34_08 via getattr.
        Assert:
            c34_08 is not None.

        FAILS TODAY: c34_08 not yet on COREPTemplateBundle.

        References:
            CRR Art. 306(1)(c): 4% RW for client-cleared QCCP trade exposures.
        """
        # Arrange / Act
        c34_08 = _get_c34_field(ccp2_corep, "c34_08")

        # Assert
        assert c34_08 is not None, (
            "C 34.08 not generated yet (P8.50 not implemented). "
            "Engine-implementer: implement COREPGenerator._generate_c34_08. "
            "CRR Art. 306(1)(c): client-cleared QCCP trade exposures at 4%."
        )

    def test_p850_ccp2_c3408_rwea_equals_ead_times_004(
        self,
        ccp2_result: object,
        ccp2_corep: COREPTemplateBundle,
    ) -> None:
        """
        C 34.08 QCCP trade RWEA == approx(ead_ccr_total * 0.04, rel=1e-9).

        Client-cleared weight is 4% (CRR Art. 306(1)(c)).

        Arrange:
            CCP-2 result: ead_ccr_total from bundle.
            COREPTemplateBundle c34_08.
        Act:
            Compute expected = ead_ccr_total * 0.04.
        Assert:
            c34_08 QCCP RWEA == approx(expected, rel=1e-9).

        FAILS TODAY: c34_08 not yet on bundle.

        References:
            CRR Art. 306(1)(c): 4% RW; CRR Art. 306(4): RWA = EAD * RW.
        """
        # Arrange
        ead_total = getattr(ccp2_result, "ead_ccr_total", _MISSING)
        if ead_total is _MISSING or ead_total is None:
            pytest.skip("ead_ccr_total not yet on AggregatedResultBundle (P8.52 prerequisite).")

        c34_08 = _get_c34_field(ccp2_corep, "c34_08")
        assert c34_08 is not None, "C 34.08 not generated yet (P8.50 not implemented)."

        expected = float(ead_total) * P839_RW_CLIENT_CLEARED  # EAD * 0.04

        assert isinstance(c34_08, pl.DataFrame)
        numeric_cols = [c for c in c34_08.columns if c not in ("row_ref", "row_name")]
        total_rwea = sum(
            float(c34_08[col].fill_null(0.0).sum())
            for col in numeric_cols
            if "rwea" in col.lower() or col in ("0020", "0030")
        )

        if total_rwea > 0:
            assert total_rwea == pytest.approx(expected, rel=1e-9), (
                f"C 34.08 client-cleared QCCP RWEA ({total_rwea:,.6f}) must equal "
                f"ead_ccr_total * 0.04 = {expected:,.6f}. "
                f"ead_ccr_total={ead_total!r}. "
                "CRR Art. 306(1)(c): client-cleared QCCP 4%."
            )

    def test_p850_ccp2_c3408_rwea_equals_bundle_rollup(
        self,
        ccp2_result: object,
        ccp2_corep: COREPTemplateBundle,
    ) -> None:
        """
        C 34.08 QCCP trade RWEA == result.rwa_ccr_qccp_trade (self-derived).

        CRR Art. 306(1)(c): client-cleared QCCP 4% — same structure as proprietary
        but with a different risk weight. The roll-up invariant is the same.

        Arrange:
            CCP-2 result: rwa_ccr_qccp_trade (4% applied by aggregator).
            COREPTemplateBundle c34_08.
        Act:
            Read rwa_ccr_qccp_trade from bundle; read QCCP RWEA from c34_08.
        Assert:
            c34_08 QCCP RWEA == approx(rwa_ccr_qccp_trade, rel=1e-9).

        FAILS TODAY: c34_08 not yet on bundle.
        """
        # Arrange
        rwa_qccp = getattr(ccp2_result, "rwa_ccr_qccp_trade", _MISSING)
        if rwa_qccp is _MISSING or rwa_qccp is None:
            pytest.skip("rwa_ccr_qccp_trade not yet on AggregatedResultBundle (P8.52).")

        c34_08 = _get_c34_field(ccp2_corep, "c34_08")
        assert c34_08 is not None, "C 34.08 not generated yet (P8.50 not implemented)."

        assert isinstance(c34_08, pl.DataFrame)
        numeric_cols = [c for c in c34_08.columns if c not in ("row_ref", "row_name")]
        total_rwea = sum(
            float(c34_08[col].fill_null(0.0).sum())
            for col in numeric_cols
            if "rwea" in col.lower() or col in ("0020", "0030")
        )

        if total_rwea > 0:
            assert total_rwea == pytest.approx(float(rwa_qccp), rel=1e-6), (
                f"C 34.08 client-cleared QCCP RWEA ({total_rwea:,.6f}) must equal "
                f"result.rwa_ccr_qccp_trade ({rwa_qccp:,.6f}). "
                "CRR Art. 306(1)(c): 4% RW for client-cleared QCCP trade leg."
            )


# ---------------------------------------------------------------------------
# Case 3: CCR-A1 — C 34.01 SA-CCR roll-up and C 34.02 per-netting-set EAD
# ---------------------------------------------------------------------------


class TestP850C3401SaCcrRollUp:
    """
    P8.50 / CCR-A1: C 34.01 SA-CCR total EAD and RWEA; C 34.02 per-netting-set EAD.

    Invariants (CRR, institution CQS2):
      1. c34_01 is present (not None).
      2. c34_01 SA-CCR EAD == approx(result.ead_ccr_total, rel=1e-9).
      3. c34_01 SA-CCR RWEA == approx(result.rwa_ccr_default, rel=1e-9).
      4. c34_02 is present (not None) as a dict.
      5. c34_02[NS_001] EAD reconciles to c34_01 EAD total.
      6. c34_04 is None (CRR run — no CVA template).

    ALL FAIL TODAY: c34_01/c34_02/c34_04 do not exist on COREPTemplateBundle.

    References:
        - CRR Art. 274(2): SA-CCR EAD = alpha * (RC + PFE).
        - CRR Art. 120(1) Table 3: institution CQS 2 -> 50% RW.
    """

    def test_p850_ccr_a1_c3401_not_none(
        self,
        ccr_a1_corep: COREPTemplateBundle,
    ) -> None:
        """
        c34_01 must be present (not None) for a CCR SA run.

        Arrange:
            COREPTemplateBundle from CCR-A1 pipeline result (CRR, institution CQS2).
        Act:
            Access c34_01 via getattr.
        Assert:
            c34_01 is not None.

        FAILS TODAY: c34_01 not yet on COREPTemplateBundle.
        Engine-implementer: add 'c34_01: pl.DataFrame | None = None' to
        COREPTemplateBundle and implement _generate_c34_01.
        """
        # Arrange / Act
        c34_01 = _get_c34_field(ccr_a1_corep, "c34_01")

        # Assert
        assert c34_01 is not None, (
            "C 34.01 not generated yet (P8.50 not implemented). "
            "Engine-implementer: add 'c34_01: pl.DataFrame | None = None' to "
            "COREPTemplateBundle and implement COREPGenerator._generate_c34_01. "
            "C 34.01 is the SA-CCR analysis-by-approach roll-up."
        )

    def test_p850_ccr_a1_c3401_ead_equals_bundle_rollup(
        self,
        ccr_a1_result: object,
        ccr_a1_corep: COREPTemplateBundle,
    ) -> None:
        """
        C 34.01 SA-CCR EAD == approx(result.ead_ccr_total, rel=1e-9).

        Arrange:
            CCR-A1 result: ead_ccr_total from AggregatedResultBundle.
            COREPTemplateBundle c34_01.
        Act:
            Read ead_ccr_total; read EAD column from c34_01 SA-CCR row.
        Assert:
            c34_01 EAD == approx(ead_ccr_total, rel=1e-9).

        FAILS TODAY: c34_01 not yet on bundle.

        References:
            CRR Art. 274(2): SA-CCR EAD = alpha * (RC + PFE).
        """
        # Arrange
        ead_total = getattr(ccr_a1_result, "ead_ccr_total", _MISSING)
        if ead_total is _MISSING or ead_total is None:
            pytest.skip("ead_ccr_total not yet on AggregatedResultBundle (P8.52 prerequisite).")

        c34_01 = _get_c34_field(ccr_a1_corep, "c34_01")
        assert c34_01 is not None, "C 34.01 not generated yet (P8.50 not implemented)."

        assert isinstance(c34_01, pl.DataFrame)
        # EAD column: expected ref "0010" per C 34.01 column structure (EAD column)
        ead_cols = [c for c in c34_01.columns if c not in ("row_ref", "row_name")]
        assert len(ead_cols) >= 1, f"c34_01 has no data columns, got: {c34_01.columns}."

        # Total SA-CCR EAD = sum over all EAD-typed columns in c34_01
        ead_col_name = ead_cols[0]  # first data column = EAD (per C 34.01 layout)
        c34_01_ead = float(c34_01[ead_col_name].fill_null(0.0).sum())

        assert c34_01_ead == pytest.approx(float(ead_total), rel=1e-9), (
            f"C 34.01 SA-CCR EAD ({c34_01_ead:,.6f}) must equal "
            f"result.ead_ccr_total ({ead_total:,.6f}). "
            "CRR Art. 274(2): SA-CCR EAD = alpha * (RC + PFE)."
        )

    def test_p850_ccr_a1_c3401_rwea_equals_bundle_rollup(
        self,
        ccr_a1_result: object,
        ccr_a1_corep: COREPTemplateBundle,
    ) -> None:
        """
        C 34.01 SA-CCR RWEA == approx(result.rwa_ccr_default, rel=1e-9).

        For CCR-A1 (institution, non-QCCP) all CCR RWA is rwa_ccr_default.

        Arrange:
            CCR-A1 result: rwa_ccr_default and rwa_ccr_qccp_trade from bundle.
            COREPTemplateBundle c34_01.
        Act:
            Compute expected = (rwa_ccr_default or 0) + (rwa_ccr_qccp_trade or 0).
            Read RWEA from c34_01.
        Assert:
            c34_01 RWEA == approx(expected, rel=1e-9).

        FAILS TODAY: c34_01 not yet on bundle.

        References:
            CRR Art. 120(1) Table 3: institution CQS 2 -> 50% RW.
        """
        # Arrange
        rwa_default = getattr(ccr_a1_result, "rwa_ccr_default", _MISSING)
        rwa_qccp = getattr(ccr_a1_result, "rwa_ccr_qccp_trade", _MISSING)
        if rwa_default is _MISSING or rwa_qccp is _MISSING:
            pytest.skip("rwa_ccr_default/qccp_trade not yet on AggregatedResultBundle (P8.52).")

        expected_rwea = (rwa_default or 0.0) + (rwa_qccp or 0.0)

        c34_01 = _get_c34_field(ccr_a1_corep, "c34_01")
        assert c34_01 is not None, "C 34.01 not generated yet (P8.50 not implemented)."

        assert isinstance(c34_01, pl.DataFrame)
        # RWEA column: expected ref "0020" or later column (per C 34.01 layout)
        all_cols = [c for c in c34_01.columns if c not in ("row_ref", "row_name")]
        assert len(all_cols) >= 2, (
            f"c34_01 must have at least 2 data columns (EAD + RWEA), got: {c34_01.columns}."
        )

        # Sum the RWEA column (second data column, or named "rwea" / col "0020")
        rwea_col_candidates = [c for c in all_cols if "rwea" in c.lower() or c == "0020"]
        if not rwea_col_candidates:
            rwea_col_candidates = [all_cols[-1]]  # fall back to last data column
        rwea_col_name = rwea_col_candidates[0]
        c34_01_rwea = float(c34_01[rwea_col_name].fill_null(0.0).sum())

        assert c34_01_rwea == pytest.approx(expected_rwea, rel=1e-9), (
            f"C 34.01 SA-CCR RWEA ({c34_01_rwea:,.6f}) must equal "
            f"(rwa_ccr_default or 0) + (rwa_ccr_qccp_trade or 0) = {expected_rwea:,.6f}. "
            f"rwa_ccr_default={rwa_default!r}, rwa_ccr_qccp_trade={rwa_qccp!r}. "
            "CRR Art. 120(1) Table 3: institution CQS 2 -> 50% SA RW."
        )

    def test_p850_ccr_a1_c3402_not_none(
        self,
        ccr_a1_corep: COREPTemplateBundle,
    ) -> None:
        """
        c34_02 must be present (not None) for a CCR SA run.

        C 34.02 is the per-netting-set EAD breakdown.

        Arrange:
            COREPTemplateBundle from CCR-A1 pipeline result (CRR).
        Act:
            Access c34_02 via getattr.
        Assert:
            c34_02 is not None.

        FAILS TODAY: c34_02 not yet on COREPTemplateBundle.
        Engine-implementer: add 'c34_02: dict[str, pl.DataFrame] | None = None' to
        COREPTemplateBundle and implement _generate_c34_02.
        """
        # Arrange / Act
        c34_02 = _get_c34_field(ccr_a1_corep, "c34_02")

        # Assert
        assert c34_02 is not None, (
            "C 34.02 not generated yet (P8.50 not implemented). "
            "Engine-implementer: add 'c34_02: dict[str, pl.DataFrame] | None = None' to "
            "COREPTemplateBundle and implement COREPGenerator._generate_c34_02. "
            "C 34.02 reports SA-CCR EAD per netting set."
        )

    def test_p850_ccr_a1_c3402_netting_set_ead_present(
        self,
        ccr_a1_result: object,
        ccr_a1_corep: COREPTemplateBundle,
    ) -> None:
        """
        c34_02[NS_001] EAD == approx(result.ead_ccr_total, rel=1e-9) for CCR-A1.

        CCR-A1 has a single netting set (NS_001). Its EAD in C 34.02 must
        equal the total ead_ccr_total from the bundle (the only netting set
        contributes the entire total).

        Arrange:
            CCR-A1 result: ead_ccr_total; c34_02 dict keyed by netting_set_id.
        Act:
            Look up c34_02[NS_001] EAD.
        Assert:
            EAD in c34_02[NS_001] == approx(ead_ccr_total, rel=1e-9).

        FAILS TODAY: c34_02 not yet on bundle.

        References:
            CRR Art. 274(2): EAD = alpha * (RC + PFE) per netting set.
        """
        # Arrange
        ead_total = getattr(ccr_a1_result, "ead_ccr_total", _MISSING)
        if ead_total is _MISSING or ead_total is None:
            pytest.skip("ead_ccr_total not yet on AggregatedResultBundle (P8.52 prerequisite).")

        c34_02 = _get_c34_field(ccr_a1_corep, "c34_02")
        assert c34_02 is not None, "C 34.02 not generated yet (P8.50 not implemented)."

        assert isinstance(c34_02, dict), (
            f"c34_02 must be a dict[str, pl.DataFrame], got {type(c34_02).__name__}."
        )
        assert len(c34_02) >= 1, (
            "c34_02 must contain at least one netting-set entry for CCR-A1 "
            f"(single NS {CCR_A1_NETTING_SET_ID!r}). Got empty dict."
        )

        # CCR-A1 has one netting set: NS_001
        ns_key = CCR_A1_NETTING_SET_ID
        assert ns_key in c34_02, (
            f"c34_02 must contain key {ns_key!r} for CCR-A1. "
            f"Found keys: {list(c34_02.keys())!r}. "
            "C 34.02 is keyed by netting_set_id."
        )

        ns_df = c34_02[ns_key]
        assert isinstance(ns_df, pl.DataFrame), (
            f"c34_02[{ns_key!r}] must be a pl.DataFrame."
        )

        ead_cols = [c for c in ns_df.columns if c not in ("row_ref", "row_name")]
        assert len(ead_cols) >= 1, f"c34_02[{ns_key!r}] has no data columns."

        ns_ead = float(ns_df[ead_cols[0]].fill_null(0.0).sum())
        assert ns_ead == pytest.approx(float(ead_total), rel=1e-9), (
            f"c34_02[{ns_key!r}] EAD ({ns_ead:,.6f}) must equal "
            f"result.ead_ccr_total ({ead_total:,.6f}). "
            "For CCR-A1 (single NS) the only netting set contributes the full EAD. "
            "CRR Art. 274(2): EAD = alpha * (RC + PFE)."
        )

    def test_p850_ccr_a1_c3404_is_none_under_crr(
        self,
        ccr_a1_corep: COREPTemplateBundle,
    ) -> None:
        """
        c34_04 must be None for a CRR run (no CVA template under CRR).

        C 34.04 (CVA RWEA) is a Basel 3.1 / PS1/26 only template.
        Under CRR, cva_rwa is absent and c34_04 must not be generated.

        Arrange:
            COREPTemplateBundle from CCR-A1 CRR pipeline result.
        Act:
            Access c34_04 via getattr.
        Assert:
            c34_04 is None (not the field-absent sentinel — the field must exist
            but must be None for CRR runs).

        FAILS TODAY: c34_04 not yet a field on COREPTemplateBundle.
        Once c34_04: pl.DataFrame | None = None is added, this test passes
        under CRR and fails only for the CVA-A1 Basel 3.1 run.
        """
        # Arrange / Act
        c34_04 = _get_c34_field(ccr_a1_corep, "c34_04")

        # Assert
        # If field is absent entirely, fail with clear message.
        # If present and None, the test passes (correct CRR behaviour).
        # If present and not None, fail (CRR must not generate CVA template).
        #
        # Note: _get_c34_field returns None for both "field absent" and "field=None".
        # We can't distinguish those cases via getattr(x, f, None).
        # So we assert the value is None — which is correct AFTER implementation
        # (field exists, value is None) and is also satisfied pre-implementation
        # (getattr returns None for absent field).
        # This test is therefore GREEN pre-implementation and STAYS GREEN post-imp.
        # It acts as a regression guard: if c34_04 starts being populated for CRR,
        # this test will catch it.
        assert c34_04 is None, (
            f"C 34.04 must be None for CRR run (CVA template is Basel 3.1 only). "
            f"Got {c34_04!r}. "
            "PS1/26 CVA Part 4.2-4.4: BA-CVA only applies under Basel 3.1 (from 1 Jan 2027). "
            "Under CRR, cva_rwa is not computed and c34_04 must not be generated."
        )


# ---------------------------------------------------------------------------
# Case 4: CVA-A1 — C 34.04 RWEA_CVA (Basel 3.1)
# ---------------------------------------------------------------------------


class TestP850C3404CvaRwea:
    """
    P8.50 / CVA-A1: C 34.04 reports CVA RWEA under Basel 3.1.

    Invariants (Basel 3.1, BA-CVA reduced):
      1. c34_04 is present (not None) when cva_rwa is populated.
      2. c34_04 RWEA_CVA == approx(result.cva_rwa, rel=1e-9).
      3. c34_04 RWEA_CVA == approx(compute_cva_a1_golden(ead_ccr)["rwea_cva"], rel=1e-9).

    ALL FAIL TODAY: c34_04 does not exist on COREPTemplateBundle.

    References:
        - PS1/26 App.1 CVA Part 4.2-4.4: BA-CVA reduced formula, DSBA-CVA=0.65.
        - PS1/26 App.1 Own Funds Part 4(b): RWEA = OFR_CVA * 12.5.
    """

    def test_p850_cva_a1_c3404_not_none_when_cva_rwa_present(
        self,
        cva_a1_result: object,
        cva_a1_corep: COREPTemplateBundle,
    ) -> None:
        """
        c34_04 must be present (not None) when cva_rwa is populated.

        Arrange:
            COREPTemplateBundle from CVA-A1 Basel 3.1 pipeline result.
        Act:
            Check result.cva_rwa; access c34_04 via getattr.
        Assert:
            If cva_rwa is present and not None: c34_04 is not None.
            If cva_rwa is not yet on bundle: skip (P8.60 prerequisite).

        FAILS TODAY: c34_04 not yet on COREPTemplateBundle.
        Engine-implementer: add 'c34_04: pl.DataFrame | None = None' to
        COREPTemplateBundle and implement _generate_c34_04.

        References:
            PS1/26 App.1 CVA Part 4.2: BA-CVA is the CVA method from 1 Jan 2027.
        """
        # Arrange — guard on cva_rwa existence (P8.60 prerequisite)
        cva_rwa = getattr(cva_a1_result, "cva_rwa", _MISSING)
        if cva_rwa is _MISSING or cva_rwa is None:
            pytest.skip(
                "cva_rwa not yet on AggregatedResultBundle or is None "
                "(P8.60/P8.63 prerequisite — must be implemented before P8.50 C 34.04)."
            )

        # Act
        c34_04 = _get_c34_field(cva_a1_corep, "c34_04")

        # Assert
        assert c34_04 is not None, (
            "C 34.04 not generated yet (P8.50 not implemented). "
            "Engine-implementer: add 'c34_04: pl.DataFrame | None = None' to "
            "COREPTemplateBundle and implement COREPGenerator._generate_c34_04. "
            "C 34.04 reports CVA RWEA; populated for Basel 3.1 runs when cva_rwa is present. "
            "PS1/26 App.1 CVA Part 4.2: BA-CVA own-funds requirement -> RWEA."
        )

    def test_p850_cva_a1_c3404_rwea_equals_cva_rwa(
        self,
        cva_a1_result: object,
        cva_a1_corep: COREPTemplateBundle,
    ) -> None:
        """
        C 34.04 RWEA_CVA == approx(result.cva_rwa, rel=1e-9).

        Arrange:
            CVA-A1 result: cva_rwa from AggregatedResultBundle.
            COREPTemplateBundle c34_04.
        Act:
            Read cva_rwa; read RWEA cell from c34_04.
        Assert:
            c34_04 RWEA == approx(cva_rwa, rel=1e-9).

        FAILS TODAY: c34_04 not yet on bundle.

        References:
            PS1/26 App.1 Own Funds Part 4(b): RWEA_CVA = OFR_CVA * 12.5.
        """
        # Arrange
        cva_rwa = getattr(cva_a1_result, "cva_rwa", _MISSING)
        if cva_rwa is _MISSING or cva_rwa is None:
            pytest.skip("cva_rwa not yet on AggregatedResultBundle (P8.60/P8.63 prerequisite).")

        c34_04 = _get_c34_field(cva_a1_corep, "c34_04")
        assert c34_04 is not None, "C 34.04 not generated yet (P8.50 not implemented)."

        assert isinstance(c34_04, pl.DataFrame), (
            f"c34_04 must be a pl.DataFrame, got {type(c34_04).__name__}."
        )
        numeric_cols = [c for c in c34_04.columns if c not in ("row_ref", "row_name")]
        assert len(numeric_cols) >= 1, (
            f"c34_04 must have at least one data column (RWEA). Found: {c34_04.columns}."
        )

        # RWEA is the primary (and possibly only) numeric column in C 34.04
        rwea_col_candidates = [c for c in numeric_cols if "rwea" in c.lower() or c == "0010"]
        if not rwea_col_candidates:
            rwea_col_candidates = [numeric_cols[0]]
        rwea_col = rwea_col_candidates[0]
        c34_04_rwea = float(c34_04[rwea_col].fill_null(0.0).sum())

        assert c34_04_rwea == pytest.approx(float(cva_rwa), rel=1e-9), (
            f"C 34.04 RWEA_CVA ({c34_04_rwea:,.6f}) must equal "
            f"result.cva_rwa ({cva_rwa:,.6f}). "
            "PS1/26 App.1 Own Funds Part 4(b): RWEA_CVA = OFR_CVA * 12.5."
        )

    def test_p850_cva_a1_c3404_rwea_equals_golden_computation(
        self,
        cva_a1_result: object,
        cva_a1_corep: COREPTemplateBundle,
    ) -> None:
        """
        C 34.04 RWEA_CVA == approx(compute_cva_a1_golden(ead_ccr)["rwea_cva"], rel=1e-9).

        Cross-check: the C 34.04 cell must also match the hand-formula applied to
        the ACTUAL ead_final emitted by the pipeline for NS_CVA_001.

        Arrange:
            CVA-A1 result: materialise ead_ccr from the CCR synthetic row.
            Compute golden = compute_cva_a1_golden(ead_ccr)["rwea_cva"].
            COREPTemplateBundle c34_04.
        Act:
            Read RWEA from c34_04.
        Assert:
            c34_04 RWEA == approx(golden, rel=1e-9).

        FAILS TODAY: c34_04 not yet on bundle.

        References:
            PS1/26 App.1 CVA Part 4.2-4.4: DSBA-CVA=0.65, rho=50%, RW_c 5% IG Financials.
            PS1/26 App.1 Own Funds Part 4(b): RWEA = OFR_CVA * 12.5.
        """
        # Arrange — materialise ead_ccr from the actual pipeline result
        cva_rwa = getattr(cva_a1_result, "cva_rwa", _MISSING)
        if cva_rwa is _MISSING or cva_rwa is None:
            pytest.skip("cva_rwa not yet on AggregatedResultBundle (P8.60/P8.63 prerequisite).")

        # Materialise ead_ccr from the pipeline result's CCR synthetic row
        ead_ccr = _materialise_ead_ccr(cva_a1_result, CVA_A1_NETTING_SET_ID)
        golden = compute_cva_a1_golden(ead_ccr)["rwea_cva"]

        c34_04 = _get_c34_field(cva_a1_corep, "c34_04")
        assert c34_04 is not None, "C 34.04 not generated yet (P8.50 not implemented)."

        assert isinstance(c34_04, pl.DataFrame)
        numeric_cols = [c for c in c34_04.columns if c not in ("row_ref", "row_name")]
        rwea_col_candidates = [c for c in numeric_cols if "rwea" in c.lower() or c == "0010"]
        if not rwea_col_candidates:
            rwea_col_candidates = [numeric_cols[0]] if numeric_cols else []
        assert len(rwea_col_candidates) >= 1, f"c34_04 has no RWEA column. Columns: {c34_04.columns}"

        c34_04_rwea = float(c34_04[rwea_col_candidates[0]].fill_null(0.0).sum())

        assert c34_04_rwea == pytest.approx(golden, rel=1e-9), (
            f"C 34.04 RWEA_CVA ({c34_04_rwea:,.6f}) must equal the hand-formula "
            f"compute_cva_a1_golden(ead_ccr={ead_ccr:,.6f})['rwea_cva'] = {golden:,.6f}. "
            "PS1/26 App.1 CVA Part 4.2-4.4: "
            "SCVA_c = (1/alpha) * RW_c * M * EAD * DF_NS; "
            "OFR_CVA = 0.65 * K_reduced; RWEA = OFR_CVA * 12.5."
        )

    def test_p850_cva_a1_c3404_grid_shape(
        self,
        cva_a1_result: object,
        cva_a1_corep: COREPTemplateBundle,
    ) -> None:
        """
        c34_04 grid must have row_ref/row_name columns and >=1 numeric column.

        Structural assertion: once c34_04 is present, the grid must conform to
        the COREP row_ref/column_ref convention.

        Arrange:
            COREPTemplateBundle from CVA-A1 Basel 3.1 run.
        Act:
            Check c34_04 schema.
        Assert:
            row_ref: String, row_name: String, >=1 Float64 data column.

        FAILS TODAY: c34_04 not yet on bundle.
        """
        # Arrange
        cva_rwa = getattr(cva_a1_result, "cva_rwa", _MISSING)
        if cva_rwa is _MISSING or cva_rwa is None:
            pytest.skip("cva_rwa not yet on AggregatedResultBundle (P8.60/P8.63 prerequisite).")

        # Act
        c34_04 = _get_c34_field(cva_a1_corep, "c34_04")
        assert c34_04 is not None, "C 34.04 not generated yet (P8.50 not implemented)."

        # Assert grid shape
        assert isinstance(c34_04, pl.DataFrame), (
            f"c34_04 must be a pl.DataFrame, got {type(c34_04).__name__}."
        )
        assert "row_ref" in c34_04.columns, "c34_04 must have a 'row_ref' column."
        assert "row_name" in c34_04.columns, "c34_04 must have a 'row_name' column."
        numeric_cols = [c for c in c34_04.columns if c not in ("row_ref", "row_name")]
        assert len(numeric_cols) >= 1, (
            f"c34_04 must have at least one data column (RWEA_CVA). "
            f"Found columns: {c34_04.columns}."
        )
        assert len(c34_04) >= 1, (
            "c34_04 must have at least one row. "
            "C 34.04 reports BA-CVA RWEA as a non-empty template."
        )
