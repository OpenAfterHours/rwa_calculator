"""
P8.51 — Pillar III CCR1–CCR8 disclosure tables: failing unit test.

Pipeline position:
    OutputAggregator -> Pillar3Generator
        (reads AggregatedResultBundle roll-up fields populated by P8.52/P8.63)

Key responsibilities:
- CCR1: SA-CCR EAD and RWEA by approach (one SA-CCR row from CCR-A1 run).
- CCR2: BA-CVA RWEA from cva_rwa (from CVA-A1 Basel 3.1 run).
- CCR3: SA EAD by risk-weight band (50% band for CCR-A1 institution CQS2).
- CCR8: QCCP vs non-QCCP RWEA split (from CCR-CCP-1 proprietary run).

Fail-first design (criterion C3.4):
    - Pillar3TemplateBundle does not yet have ccr1/ccr2/ccr3/ccr8 fields.
    - Every table access is guarded by getattr(bundle, "ccrN", None) with an
      assert-not-None message.  The test fails with a clean AssertionError
      (not AttributeError/collection error) on the first missing field.

Invariant assertions (self-deriving — no transcribed literals):
    - CCR1 EAD == pytest.approx(result.ead_ccr_total)
    - CCR1 RWEA == pytest.approx(result.rwa_ccr_default)
    - CCR3 50%-band cell == approx sum of ead_final over ccr__ rows with RW≈0.50
    - CCR3 Total == approx result.ead_ccr_total
    - CCR8 QCCP RWEA == approx result.rwa_ccr_qccp_trade
    - CCR8 non-QCCP RWEA == approx result.rwa_ccr_default  (None for all-QCCP run)
    - CCR2 RWEA == approx result.cva_rwa
    - result.cva_method == "BA-CVA"

Structural assertions (guarded behind same not-None check):
    - CRR framework: table code prefix "UK"
    - Basel 3.1 framework: table code prefix "UKB"
    - row_ref set includes a "Total" row
    - CCR1 has "SA-CCR" approach row

References:
    - CRR Art. 274(2): SA-CCR EAD = alpha*(RC+PFE) — source of CCR1/CCR3 EAD.
    - CRR Art. 120(1) Table 3: institution CQS 2 → 50% RW — CCR3 band cell.
    - CRR Art. 306(1)(a): 2% QCCP proprietary trade RW — CCR8 QCCP column.
    - PS1/26 App.1 CVA Part 4.2–4.4 (BA-CVA reduced) — CCR2 RWEA.
    - PRA PS1/26 Disclosure Part Art. 456 — CCR1/CCR2/CCR3/CCR8 table scope.
    - tests/fixtures/ccr/golden_ccr_a1.py — CCR-A1 CRR bundle (CCR1/CCR3 input).
    - tests/fixtures/ccr/p839_ccp_builder.py — QCCP proprietary bundle (CCR8 input).
    - tests/fixtures/p8_60/cva_a1_builder.py — CVA-A1 Basel 3.1 bundle (CCR2 input).
"""

from __future__ import annotations

import dataclasses
from datetime import date
from typing import TYPE_CHECKING, cast

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.pillar3.generator import Pillar3Generator, Pillar3TemplateBundle

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import AggregatedResultBundle
from tests.fixtures.ccr.golden_ccr_a1 import build_raw_data_bundle_with_ccr_a1
from tests.fixtures.ccr.p839_ccp_builder import build_p839_bundle
from tests.fixtures.p8_60.cva_a1_builder import (
    CVA_A1_NETTING_SET_ID,
    build_raw_data_bundle_cva_a1,
    create_cva_a1_counterparty_frame,
)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: CRR era reporting date — used for CCR1 / CCR3 / CCR8 tests.
_CRR_REPORTING_DATE: date = date(2026, 1, 15)

#: Basel 3.1 era reporting date — used for CCR2 (CVA) test.
_B31_REPORTING_DATE: date = date(2027, 1, 15)

#: Sentinel distinct from None — detects missing dataclass fields without AttributeError.
_MISSING = object()

#: CCR exposure_reference prefix (rows emitted by the CCR adapter).
_CCR_PREFIX: str = "ccr__"

#: QCCP discriminator: cp_entity_type value for CCP counterparties.
_CP_ENTITY_TYPE_CCP: str = "ccp"

#: Synthetic CCR exposure reference for the CVA-A1 netting set.
_CVA_CCR_EXPOSURE_REF: str = f"{_CCR_PREFIX}{CVA_A1_NETTING_SET_ID}"


# ---------------------------------------------------------------------------
# Module-scoped pipeline fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ccr_a1_result():
    """
    Run the CCR-A1 CRR bundle (institution CQS 2) through the full CRR pipeline.

    Arrange:
        - build_raw_data_bundle_with_ccr_a1(): 1 institution CP, 1 netting set,
          1 trade (10y GBP IR swap), CRR.
        - Config: CRR, 2026-01-15, STANDARDISED.
    Act:
        Full CRR pipeline via PipelineOrchestrator.
    Assert (in tests, not here):
        AggregatedResultBundle with ead_ccr_total, rwa_ccr_default populated.
    """
    bundle = build_raw_data_bundle_with_ccr_a1()
    config = CalculationConfig.crr(
        reporting_date=_CRR_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


@pytest.fixture(scope="module")
def ccr_a1_results_df(ccr_a1_result) -> pl.DataFrame:
    """Materialised results DataFrame for CCR-A1."""
    return ccr_a1_result.results.collect()


@pytest.fixture(scope="module")
def ccp1_result():
    """
    Run the CCR-CCP-1 QCCP proprietary bundle through the full CRR pipeline.

    Arrange:
        - build_p839_bundle(is_client_cleared=False): QCCP, CRR, proprietary.
        - Config: CRR, 2026-01-15, STANDARDISED.
    Act:
        Full CRR pipeline via PipelineOrchestrator.
    Assert (in tests):
        AggregatedResultBundle with rwa_ccr_qccp_trade populated.
    """
    bundle = build_p839_bundle(is_client_cleared=False)
    config = CalculationConfig.crr(
        reporting_date=_CRR_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    return PipelineOrchestrator().run_with_data(bundle, config)


@pytest.fixture(scope="module")
def cva_a1_result_and_ead():
    """
    Run the CVA-A1 bundle (Basel 3.1, BA-CVA reduced) through the full pipeline.

    Arrange:
        - build_raw_data_bundle_cva_a1(): 1 institution CP, 1 netting set,
          1 trade (3y GBP IR swap), Basel 3.1.
        - CVA counterparty frame attached via field-presence guard (guard fires
          once engine-implementer adds RawDataBundle.cva_counterparties in P8.60).
        - Config: Basel 3.1, 2027-01-15, STANDARDISED.
    Act:
        Full Basel 3.1 pipeline via PipelineOrchestrator.
    Returns:
        (AggregatedResultBundle, ead_ccr: float)
    """
    bundle = build_raw_data_bundle_cva_a1()

    # Guard: attach CVA counterparty frame when the field exists (P8.60 shipped).
    if "cva_counterparties" in {f.name for f in dataclasses.fields(bundle)}:
        bundle = dataclasses.replace(
            bundle,
            cva_counterparties=create_cva_a1_counterparty_frame().lazy(),
        )

    config = CalculationConfig.basel_3_1(
        reporting_date=_B31_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )
    result = PipelineOrchestrator().run_with_data(bundle, config)

    # Materialise ead_ccr from the CCR synthetic row.
    df = result.results.collect()
    ccr_rows = df.filter(pl.col("exposure_reference") == _CVA_CCR_EXPOSURE_REF)
    ead_ccr = float(ccr_rows["ead_final"][0]) if ccr_rows.height > 0 else 0.0
    return result, ead_ccr


# ---------------------------------------------------------------------------
# Helper: run Pillar3Generator on a pipeline result LazyFrame.
# ---------------------------------------------------------------------------


def _generate_bundle(result: AggregatedResultBundle, *, framework: str) -> Pillar3TemplateBundle:
    """Generate a Pillar3TemplateBundle from a pipeline result."""
    return Pillar3Generator().generate_from_lazyframe(
        result.results,
        framework=framework,
    )


# ---------------------------------------------------------------------------
# CCR1 — SA-CCR EAD and RWEA by approach (CRR, CCR-A1)
# ---------------------------------------------------------------------------


class TestCCR1SAEquivalentEAD:
    """
    P8.51 / CCR1: SA-CCR analysis by approach.

    CCR1 is the CRR Pillar III table for CCR exposure by calculation approach.
    For a single SA-CCR run (CCR-A1: institution CQS 2, CRR), the table must
    contain:
      - An "SA-CCR" approach row with EAD == result.ead_ccr_total.
      - An "SA-CCR" approach row with RWEA == result.rwa_ccr_default.
      - A Total row.
      - Table code prefixed "UK" (CRR framework).

    All value assertions are self-deriving: they read the expected value from the
    AggregatedResultBundle roll-up field (P8.52) produced by the same pipeline run,
    not from transcribed literals.

    FAILS TODAY: Pillar3TemplateBundle.ccr1 does not yet exist.

    References:
        - CRR Art. 274(2): SA-CCR EAD = alpha*(RC+PFE) — source of CCR1 EAD column.
        - CRR Art. 120(1) Table 3: institution CQS 2 → 50% RW — source of RWEA.
        - PRA PS1/26 Disclosure Part Art. 456: CCR1 table scope.
    """

    def test_ccr1_field_exists_on_bundle(
        self,
        ccr_a1_result,
        ccr_a1_results_df: pl.DataFrame,
    ) -> None:
        """
        Pillar3TemplateBundle.ccr1 must be generated (not None) for a CCR-A1 run.

        Arrange:
            CCR-A1 result (CRR pipeline, institution CQS 2, 1 netting set).
        Act:
            Generate Pillar III bundle from the CCR-A1 results LazyFrame.
            Access ccr1 via getattr sentinel guard.
        Assert:
            ccr1 is not the sentinel (field exists) AND is not None.

        FAILS TODAY: Pillar3TemplateBundle does not have a ccr1 field.
        The getattr sentinel guard produces a clean AssertionError.

        Engine-implementer must:
            (1) Add ccr1: pl.DataFrame | None = None to Pillar3TemplateBundle.
            (2) Add _generate_ccr1() method to Pillar3Generator.
            (3) Call _generate_ccr1() in generate_from_lazyframe() and include
                the result in the bundle construction.

        References:
            PRA PS1/26 Disclosure Part Art. 456: CCR1 table scope.
        """
        # Arrange
        bundle = _generate_bundle(ccr_a1_result, framework="CRR")

        # Act — sentinel guard prevents AttributeError
        ccr1 = getattr(bundle, "ccr1", _MISSING)

        # Assert — field must exist on the bundle
        assert ccr1 is not _MISSING, (
            "Pillar3TemplateBundle.ccr1 does not exist (P8.51 not yet implemented). "
            "Engine-implementer: add 'ccr1: pl.DataFrame | None = None' to the dataclass "
            "and add _generate_ccr1() to Pillar3Generator. "
            "PRA PS1/26 Disclosure Art. 456: CCR1 is a mandatory CCR disclosure table."
        )
        assert ccr1 is not None, (
            "P8.51 CCR1: ccr1 must be generated (not None) for a run that contains "
            "CCR SA-CCR rows (ccr__-prefixed exposure_references). "
            "Generator must populate CCR1 when ccr__-prefixed rows are present."
        )

    def test_ccr1_ead_equals_ead_ccr_total(
        self,
        ccr_a1_result,
        ccr_a1_results_df: pl.DataFrame,
    ) -> None:
        """
        CCR1 SA-CCR approach row EAD == result.ead_ccr_total (self-deriving).

        Arrange:
            CCR-A1 result; expected EAD read from AggregatedResultBundle.ead_ccr_total.
        Act:
            Generate Pillar III bundle; filter CCR1 to the SA-CCR approach row;
            read EAD cell.
        Assert:
            ccr1 SA-CCR EAD == pytest.approx(result.ead_ccr_total, rel=1e-9).

        Self-deriving: expected is read from the P8.52 roll-up field on the same
        result bundle, not transcribed.

        References:
            CRR Art. 274(2): SA-CCR EAD = alpha*(RC+PFE).
        """
        # Arrange
        expected_ead = getattr(ccr_a1_result, "ead_ccr_total", _MISSING)
        assert expected_ead is not _MISSING, (
            "AggregatedResultBundle.ead_ccr_total does not exist — P8.52 prerequisite "
            "not yet implemented. P8.51 cannot validate CCR1 EAD without P8.52."
        )
        assert expected_ead is not None, (
            "ead_ccr_total is None — P8.52 must populate ead_ccr_total before P8.51 "
            "can validate CCR1 EAD."
        )

        # Act
        bundle = _generate_bundle(ccr_a1_result, framework="CRR")
        ccr1 = getattr(bundle, "ccr1", _MISSING)

        assert ccr1 is not _MISSING, (
            "Pillar3TemplateBundle.ccr1 does not exist (P8.51 not yet implemented)."
        )
        assert ccr1 is not None, "P8.51 CCR1: ccr1 must be generated for a CCR run."
        ccr1 = cast("pl.DataFrame", ccr1)

        # Find SA-CCR row — approach column must contain a row labelled "SA-CCR".
        sa_ccr_rows = ccr1.filter(pl.col("row_name").str.contains("SA-CCR"))

        assert sa_ccr_rows.height > 0, (
            "P8.51 CCR1: no row with row_name containing 'SA-CCR' found. "
            "The generator must emit an approach row labelled 'SA-CCR' matching "
            "the pipeline's SA-CCR calculation approach. "
            f"Available row_names: {ccr1['row_name'].to_list()!r}"
        )

        # EAD column — must be the first data column (column "a" by convention)
        ead_col = next((c for c in ccr1.columns if c not in ("row_ref", "row_name")), None)
        assert ead_col is not None, (
            "P8.51 CCR1: no data column found in ccr1. "
            "Expected at least one non-metadata column (e.g., 'a' for EAD)."
        )

        actual_ead = sa_ccr_rows[ead_col][0]

        # Assert
        assert actual_ead == pytest.approx(expected_ead, rel=1e-9), (
            f"P8.51 CCR1: SA-CCR EAD cell must equal ead_ccr_total. "
            f"Expected {expected_ead:,.6f} (from result.ead_ccr_total), "
            f"got {actual_ead!r}. "
            "CCR1 EAD column (col a) must be populated from the same SA-CCR roll-up "
            "that populates AggregatedResultBundle.ead_ccr_total. "
            "CRR Art. 274(2): CCR1 EAD = Σ alpha*(RC+PFE) per SA-CCR approach."
        )

    def test_ccr1_rwea_equals_rwa_ccr_default(
        self,
        ccr_a1_result,
        ccr_a1_results_df: pl.DataFrame,
    ) -> None:
        """
        CCR1 SA-CCR approach row RWEA == result.rwa_ccr_default (self-deriving).

        Arrange:
            CCR-A1 result; expected RWEA read from AggregatedResultBundle.rwa_ccr_default.
        Act:
            Generate Pillar III bundle; find the SA-CCR row in CCR1; read RWEA cell.
        Assert:
            ccr1 SA-CCR RWEA == pytest.approx(result.rwa_ccr_default, rel=1e-9).

        References:
            CRR Art. 120(1) Table 3: institution CQS 2 → 50% → RWEA = EAD * 0.50.
        """
        # Arrange
        expected_rwea = getattr(ccr_a1_result, "rwa_ccr_default", _MISSING)
        assert expected_rwea is not _MISSING, (
            "AggregatedResultBundle.rwa_ccr_default does not exist — P8.52 prerequisite."
        )
        assert expected_rwea is not None, (
            "rwa_ccr_default is None — P8.52 must populate it for a non-QCCP CCR run."
        )

        # Act
        bundle = _generate_bundle(ccr_a1_result, framework="CRR")
        ccr1 = getattr(bundle, "ccr1", _MISSING)

        assert ccr1 is not _MISSING, (
            "Pillar3TemplateBundle.ccr1 does not exist (P8.51 not yet implemented)."
        )
        assert ccr1 is not None, "P8.51 CCR1: ccr1 must be generated for a CCR run."
        ccr1 = cast("pl.DataFrame", ccr1)

        sa_ccr_rows = ccr1.filter(pl.col("row_name").str.contains("SA-CCR"))
        assert sa_ccr_rows.height > 0, "P8.51 CCR1: no SA-CCR approach row found in ccr1."

        # RWEA column: typically the second data column (column "b").
        data_cols = [c for c in ccr1.columns if c not in ("row_ref", "row_name")]
        assert len(data_cols) >= 2, (
            f"P8.51 CCR1: expected at least 2 data columns (EAD, RWEA), got {data_cols!r}."
        )
        rwea_col = data_cols[1]
        actual_rwea = sa_ccr_rows[rwea_col][0]

        # Assert
        assert actual_rwea == pytest.approx(expected_rwea, rel=1e-9), (
            f"P8.51 CCR1: SA-CCR RWEA cell must equal rwa_ccr_default. "
            f"Expected {expected_rwea:,.6f} (from result.rwa_ccr_default), "
            f"got {actual_rwea!r}. "
            "CCR1 RWEA column (col b) must be populated from the same P8.52 roll-up. "
            "CRR Art. 120(1) Table 3: institution CQS 2 → 50% RW."
        )

    def test_ccr1_has_total_row(
        self,
        ccr_a1_result,
    ) -> None:
        """
        CCR1 must contain a Total row.

        Arrange:
            CCR-A1 result (CRR, institution CQS 2).
        Act:
            Generate Pillar III bundle; inspect CCR1 for a row whose row_name
            contains "Total" (case-insensitive).
        Assert:
            At least one Total row present.

        References:
            PRA PS1/26 Disclosure Art. 456: all CCR tables include a Total row.
        """
        # Act
        bundle = _generate_bundle(ccr_a1_result, framework="CRR")
        ccr1 = getattr(bundle, "ccr1", _MISSING)

        assert ccr1 is not _MISSING, (
            "Pillar3TemplateBundle.ccr1 does not exist (P8.51 not yet implemented)."
        )
        assert ccr1 is not None, "P8.51 CCR1: ccr1 must not be None for a CCR run."
        ccr1 = cast("pl.DataFrame", ccr1)

        # Assert
        total_rows = ccr1.filter(pl.col("row_name").str.to_lowercase().str.contains("total"))
        assert total_rows.height > 0, (
            f"P8.51 CCR1: no Total row found. "
            f"Available row_names: {ccr1['row_name'].to_list()!r}. "
            "CCR1 must include a Total row per PRA PS1/26 Disclosure Art. 456."
        )

    def test_ccr1_framework_prefix_crr(
        self,
        ccr_a1_result,
    ) -> None:
        """
        CCR1 under CRR framework must carry table-code prefix "UK" (not "UKB").

        Arrange:
            CCR-A1 result; generate with framework="CRR".
        Act:
            Inspect bundle.framework and confirm the export prefix is "UK".
        Assert:
            bundle.framework == "CRR" and prefix would be "UK".

        This is a structural invariant: CRR uses UK-prefixed table codes;
        Basel 3.1 uses UKB-prefixed. The generator's export_to_excel method
        already uses ``prefix = "UKB" if bundle.framework == "BASEL_3_1" else "UK"``.

        References:
            PRA PS1/26 Disclosure Part: UK CCR1 vs UKB CCR1 naming convention.
        """
        # Act
        bundle = _generate_bundle(ccr_a1_result, framework="CRR")
        ccr1 = getattr(bundle, "ccr1", _MISSING)

        assert ccr1 is not _MISSING, (
            "Pillar3TemplateBundle.ccr1 does not exist (P8.51 not yet implemented)."
        )

        # Assert
        assert bundle.framework == "CRR", (
            f"P8.51 CCR1 framework check: expected 'CRR', got {bundle.framework!r}."
        )
        # Derive prefix as the generator would.
        prefix = "UKB" if bundle.framework == "BASEL_3_1" else "UK"
        assert prefix == "UK", f"P8.51: CRR run must use UK prefix, got {prefix!r}."


# ---------------------------------------------------------------------------
# CCR3 — SA EAD by risk-weight band (CRR, CCR-A1, 50% band)
# ---------------------------------------------------------------------------


class TestCCR3EADByRiskWeightBand:
    """
    P8.51 / CCR3: SA-CCR EAD allocation by risk-weight band.

    For the CCR-A1 run (institution CQS 2, CRR, RW = 50%), the 50%-band cell
    in CCR3 must equal the sum of ead_final over ccr__-prefixed rows whose
    risk_weight is approximately 0.50. The Total column must equal ead_ccr_total.

    All value assertions are self-deriving from the same pipeline result.

    FAILS TODAY: Pillar3TemplateBundle.ccr3 does not yet exist.

    References:
        - CRR Art. 120(1) Table 3: institution CQS 2 → 50% RW.
        - PRA PS1/26 Disclosure Art. 456: CCR3 SA EAD by risk-weight band.
    """

    def test_ccr3_field_exists_on_bundle(
        self,
        ccr_a1_result,
    ) -> None:
        """
        Pillar3TemplateBundle.ccr3 must be generated (not None) for a CCR-A1 run.

        Arrange:
            CCR-A1 CRR run; generate Pillar III bundle.
        Act:
            Access ccr3 via sentinel guard.
        Assert:
            ccr3 field exists and is not None.

        FAILS TODAY: ccr3 not a field on Pillar3TemplateBundle.

        Engine-implementer must:
            (1) Add ccr3: pl.DataFrame | None = None to Pillar3TemplateBundle.
            (2) Add _generate_ccr3() to Pillar3Generator.

        References:
            PRA PS1/26 Disclosure Art. 456: CCR3 mandatory CCR table.
        """
        # Act
        bundle = _generate_bundle(ccr_a1_result, framework="CRR")
        ccr3 = getattr(bundle, "ccr3", _MISSING)

        # Assert
        assert ccr3 is not _MISSING, (
            "Pillar3TemplateBundle.ccr3 does not exist (P8.51 not yet implemented). "
            "Engine-implementer: add 'ccr3: pl.DataFrame | None = None' to the dataclass "
            "and add _generate_ccr3() to Pillar3Generator. "
            "PRA PS1/26 Disclosure Art. 456: CCR3 is mandatory."
        )
        assert ccr3 is not None, (
            "P8.51 CCR3: ccr3 must be generated (not None) for a run with CCR rows."
        )

    def test_ccr3_50pct_band_equals_sum_of_ccr_ead_at_50pct(
        self,
        ccr_a1_result,
        ccr_a1_results_df: pl.DataFrame,
    ) -> None:
        """
        CCR3 50%-band cell == sum of ead_final over ccr__ rows where risk_weight≈0.50.

        Arrange:
            CCR-A1 result; compute expected from results_df (self-deriving).
        Act:
            Generate CCR3; find the row for the 50%-band; read the SA-CCR EAD cell.
        Assert:
            cell == pytest.approx(expected_ead_50pct, rel=1e-9).

        References:
            CRR Art. 120(1) Table 3: institution CQS 2 → 50% → all CCR EAD in 50% band.
        """
        # Arrange — compute expected from the results frame (self-deriving)
        df = ccr_a1_results_df
        ccr_rows = df.filter(pl.col("exposure_reference").str.starts_with(_CCR_PREFIX))
        if "risk_weight" in ccr_rows.columns:
            rows_50pct = ccr_rows.filter(
                (pl.col("risk_weight") >= 0.495) & (pl.col("risk_weight") <= 0.505)
            )
        else:
            rows_50pct = ccr_rows  # fallback: use all ccr rows if rw column absent
        expected_ead_50pct = rows_50pct["ead_final"].sum()

        # Act
        bundle = _generate_bundle(ccr_a1_result, framework="CRR")
        ccr3 = getattr(bundle, "ccr3", _MISSING)

        assert ccr3 is not _MISSING, (
            "Pillar3TemplateBundle.ccr3 does not exist (P8.51 not yet implemented)."
        )
        assert ccr3 is not None, "P8.51 CCR3: ccr3 must not be None for a CCR run with CCR rows."
        ccr3 = cast("pl.DataFrame", ccr3)

        # Find the 50%-band row: row_name should contain "50" or row_ref matches.
        band_rows = ccr3.filter(
            pl.col("row_name").str.contains("50")
            | pl.col("row_name").str.contains("0.50")
            | pl.col("row_name").str.contains("50%")
        )
        assert band_rows.height > 0, (
            f"P8.51 CCR3: no row for the 50% risk-weight band found. "
            f"Available row_names: {ccr3['row_name'].to_list()!r}. "
            "CCR3 must have a row for each RW band including 50% (institution CQS 2)."
        )

        # EAD cell: first data column (col "a" by convention)
        data_cols = [c for c in ccr3.columns if c not in ("row_ref", "row_name")]
        assert len(data_cols) >= 1, (
            f"P8.51 CCR3: no data columns in ccr3. Got columns: {ccr3.columns!r}."
        )
        ead_col = data_cols[0]
        actual_ead_50pct = band_rows[ead_col][0]

        # Assert
        assert actual_ead_50pct == pytest.approx(expected_ead_50pct, rel=1e-9), (
            f"P8.51 CCR3: 50%-band EAD cell must equal sum of ead_final "
            f"over ccr__ rows with risk_weight≈0.50. "
            f"Expected {expected_ead_50pct:,.6f}, got {actual_ead_50pct!r}. "
            "CRR Art. 120(1) Table 3: institution CQS 2 → 50% → all CCR EAD in 50% band."
        )

    def test_ccr3_total_equals_ead_ccr_total(
        self,
        ccr_a1_result,
    ) -> None:
        """
        CCR3 Total row EAD == result.ead_ccr_total (self-deriving).

        Arrange:
            CCR-A1 result; expected = result.ead_ccr_total.
        Act:
            Generate CCR3; find Total row; read EAD cell.
        Assert:
            Total EAD cell == pytest.approx(result.ead_ccr_total, rel=1e-9).

        References:
            The CCR3 Total must equal the portfolio-wide SA-CCR EAD.
        """
        # Arrange
        expected_total_ead = getattr(ccr_a1_result, "ead_ccr_total", _MISSING)
        assert expected_total_ead is not _MISSING, (
            "AggregatedResultBundle.ead_ccr_total does not exist — P8.52 prerequisite."
        )
        assert expected_total_ead is not None, "ead_ccr_total is None — P8.52 must populate it."

        # Act
        bundle = _generate_bundle(ccr_a1_result, framework="CRR")
        ccr3 = getattr(bundle, "ccr3", _MISSING)

        assert ccr3 is not _MISSING, (
            "Pillar3TemplateBundle.ccr3 does not exist (P8.51 not yet implemented)."
        )
        assert ccr3 is not None, "P8.51 CCR3: ccr3 must not be None."
        ccr3 = cast("pl.DataFrame", ccr3)

        total_rows = ccr3.filter(pl.col("row_name").str.to_lowercase().str.contains("total"))
        assert total_rows.height > 0, (
            f"P8.51 CCR3: no Total row found. row_names: {ccr3['row_name'].to_list()!r}."
        )

        data_cols = [c for c in ccr3.columns if c not in ("row_ref", "row_name")]
        assert len(data_cols) >= 1, "P8.51 CCR3: no data columns."
        total_ead = total_rows[data_cols[0]][0]

        # Assert
        assert total_ead == pytest.approx(expected_total_ead, rel=1e-9), (
            f"P8.51 CCR3: Total EAD must equal ead_ccr_total. "
            f"Expected {expected_total_ead:,.6f}, got {total_ead!r}. "
            "CCR3 Total column must sum across all RW bands to give the portfolio total."
        )


# ---------------------------------------------------------------------------
# CCR8 — QCCP vs non-QCCP RWEA (CRR, CCR-CCP-1)
# ---------------------------------------------------------------------------


class TestCCR8QCCPNonQCCPSplit:
    """
    P8.51 / CCR8: CCP exposures — QCCP vs non-QCCP RWEA.

    For the CCR-CCP-1 run (QCCP proprietary, is_client_cleared=False):
      - QCCP RWEA cell == result.rwa_ccr_qccp_trade.
      - Non-QCCP RWEA cell must be None / zero (all rows are QCCP).

    All value assertions are self-deriving from the P8.52 roll-up fields.

    FAILS TODAY: Pillar3TemplateBundle.ccr8 does not yet exist.

    References:
        - CRR Art. 306(1)(a): 2% QCCP proprietary trade RW.
        - CRR Art. 306(4): RWA = EAD * RW.
        - PRA PS1/26 Disclosure Art. 456: CCR8 CCP exposures table.
    """

    def test_ccr8_field_exists_on_bundle(
        self,
        ccp1_result,
    ) -> None:
        """
        Pillar3TemplateBundle.ccr8 must be generated (not None) for a QCCP run.

        Arrange:
            CCR-CCP-1 result (QCCP proprietary, CRR).
        Act:
            Generate Pillar III bundle; access ccr8 via sentinel guard.
        Assert:
            ccr8 field exists and is not None.

        FAILS TODAY: ccr8 not a field on Pillar3TemplateBundle.

        Engine-implementer must:
            (1) Add ccr8: pl.DataFrame | None = None to Pillar3TemplateBundle.
            (2) Add _generate_ccr8() to Pillar3Generator.

        References:
            PRA PS1/26 Disclosure Art. 456: CCR8 is mandatory.
        """
        # Act
        bundle = _generate_bundle(ccp1_result, framework="CRR")
        ccr8 = getattr(bundle, "ccr8", _MISSING)

        # Assert
        assert ccr8 is not _MISSING, (
            "Pillar3TemplateBundle.ccr8 does not exist (P8.51 not yet implemented). "
            "Engine-implementer: add 'ccr8: pl.DataFrame | None = None' to the dataclass "
            "and add _generate_ccr8() to Pillar3Generator. "
            "PRA PS1/26 Disclosure Art. 456: CCR8 is a mandatory CCR table."
        )
        assert ccr8 is not None, (
            "P8.51 CCR8: ccr8 must be generated (not None) for a run with QCCP rows."
        )

    def test_ccr8_qccp_rwea_equals_rwa_ccr_qccp_trade(
        self,
        ccp1_result,
    ) -> None:
        """
        CCR8 QCCP RWEA cell == result.rwa_ccr_qccp_trade (self-deriving).

        Arrange:
            CCR-CCP-1 result; expected = result.rwa_ccr_qccp_trade.
        Act:
            Generate CCR8; find QCCP row; read RWEA cell.
        Assert:
            QCCP RWEA cell == pytest.approx(result.rwa_ccr_qccp_trade, rel=1e-9).

        References:
            CRR Art. 306(1)(a): 2% proprietary QCCP trade RW.
        """
        # Arrange
        expected_qccp_rwea = getattr(ccp1_result, "rwa_ccr_qccp_trade", _MISSING)
        assert expected_qccp_rwea is not _MISSING, (
            "AggregatedResultBundle.rwa_ccr_qccp_trade does not exist — P8.52 prerequisite."
        )
        assert expected_qccp_rwea is not None, (
            "rwa_ccr_qccp_trade is None — P8.52 must populate it for a QCCP run."
        )

        # Act
        bundle = _generate_bundle(ccp1_result, framework="CRR")
        ccr8 = getattr(bundle, "ccr8", _MISSING)

        assert ccr8 is not _MISSING, (
            "Pillar3TemplateBundle.ccr8 does not exist (P8.51 not yet implemented)."
        )
        assert ccr8 is not None, "P8.51 CCR8: ccr8 must not be None."
        ccr8 = cast("pl.DataFrame", ccr8)

        # Find QCCP row
        qccp_rows = ccr8.filter(
            pl.col("row_name").str.to_lowercase().str.contains("qccp")
            & ~pl.col("row_name").str.to_lowercase().str.contains("non")
        )
        assert qccp_rows.height > 0, (
            f"P8.51 CCR8: no QCCP row found. "
            f"Available row_names: {ccr8['row_name'].to_list()!r}. "
            "CCR8 must have a QCCP row for QCCP trade-leg exposures."
        )

        data_cols = [c for c in ccr8.columns if c not in ("row_ref", "row_name")]
        assert len(data_cols) >= 1, "P8.51 CCR8: no data columns found."
        rwea_col = data_cols[0]
        actual_qccp_rwea = qccp_rows[rwea_col][0]

        # Assert
        assert actual_qccp_rwea == pytest.approx(expected_qccp_rwea, rel=1e-9), (
            f"P8.51 CCR8: QCCP RWEA cell must equal rwa_ccr_qccp_trade. "
            f"Expected {expected_qccp_rwea:,.6f}, got {actual_qccp_rwea!r}. "
            "CCR8 QCCP column must be populated from the P8.52 rwa_ccr_qccp_trade roll-up. "
            "CRR Art. 306(1)(a): 2% proprietary QCCP trade RW."
        )

    def test_ccr8_non_qccp_is_none_for_all_qccp_run(
        self,
        ccp1_result,
    ) -> None:
        """
        CCR8 non-QCCP RWEA cell must be None/zero for an all-QCCP run.

        For CCR-CCP-1 all ccr__ rows are QCCP (rwa_ccr_default is None).
        The non-QCCP row in CCR8 must therefore be null/zero.

        Arrange:
            CCR-CCP-1 result; verify rwa_ccr_default is None.
        Act:
            Generate CCR8; find non-QCCP row; read RWEA cell.
        Assert:
            non-QCCP RWEA cell is None or 0.0 (consistent with rwa_ccr_default=None).

        References:
            CRR Art. 306(1)(a): QCCP trade-leg rows excluded from non-QCCP partition.
        """
        # Arrange — confirm the prerequisite from P8.52
        rwa_default = getattr(ccp1_result, "rwa_ccr_default", _MISSING)
        assert rwa_default is not _MISSING, (
            "AggregatedResultBundle.rwa_ccr_default does not exist — P8.52 prerequisite."
        )
        # rwa_ccr_default may be None for an all-QCCP run — that's the expected state.

        # Act
        bundle = _generate_bundle(ccp1_result, framework="CRR")
        ccr8 = getattr(bundle, "ccr8", _MISSING)

        assert ccr8 is not _MISSING, (
            "Pillar3TemplateBundle.ccr8 does not exist (P8.51 not yet implemented)."
        )
        assert ccr8 is not None, "P8.51 CCR8: ccr8 must not be None."
        ccr8 = cast("pl.DataFrame", ccr8)

        # Find non-QCCP row
        non_qccp_rows = ccr8.filter(pl.col("row_name").str.to_lowercase().str.contains("non"))
        assert non_qccp_rows.height > 0, (
            f"P8.51 CCR8: no non-QCCP row found. "
            f"Available row_names: {ccr8['row_name'].to_list()!r}. "
            "CCR8 must have a non-QCCP row (may be null for all-QCCP portfolios)."
        )

        data_cols = [c for c in ccr8.columns if c not in ("row_ref", "row_name")]
        assert len(data_cols) >= 1, "P8.51 CCR8: no data columns."
        rwea_col = data_cols[0]
        actual_non_qccp_rwea = non_qccp_rows[rwea_col][0]

        # Assert — non-QCCP RWEA must be None or 0 for an all-QCCP run.
        assert actual_non_qccp_rwea is None or actual_non_qccp_rwea == pytest.approx(0.0), (
            f"P8.51 CCR8: non-QCCP RWEA must be None or 0 for an all-QCCP run "
            f"(rwa_ccr_default={rwa_default!r}), got {actual_non_qccp_rwea!r}. "
            "CRR Art. 306(1)(a): all rows are QCCP → non-QCCP partition is empty."
        )

    def test_ccr8_has_total_row(
        self,
        ccp1_result,
    ) -> None:
        """
        CCR8 must contain a Total row.

        Arrange:
            CCR-CCP-1 result (all rows QCCP).
        Act:
            Generate CCR8; check for Total row.
        Assert:
            At least one row with row_name containing "Total".

        References:
            PRA PS1/26 Disclosure Art. 456: CCR8 includes Total row.
        """
        # Act
        bundle = _generate_bundle(ccp1_result, framework="CRR")
        ccr8 = getattr(bundle, "ccr8", _MISSING)

        assert ccr8 is not _MISSING, (
            "Pillar3TemplateBundle.ccr8 does not exist (P8.51 not yet implemented)."
        )
        assert ccr8 is not None, "P8.51 CCR8: ccr8 must not be None."
        ccr8 = cast("pl.DataFrame", ccr8)

        # Assert
        total_rows = ccr8.filter(pl.col("row_name").str.to_lowercase().str.contains("total"))
        assert total_rows.height > 0, (
            f"P8.51 CCR8: no Total row. row_names: {ccr8['row_name'].to_list()!r}."
        )


# ---------------------------------------------------------------------------
# CCR2 — BA-CVA RWEA (Basel 3.1, CVA-A1)
# ---------------------------------------------------------------------------


class TestCCR2BACVACapital:
    """
    P8.51 / CCR2: BA-CVA capital requirements.

    For the CVA-A1 run (Basel 3.1, single institution counterparty, 3-year IR swap):
      - CCR2 RWEA cell == result.cva_rwa (self-deriving from AggregatedResultBundle).
      - result.cva_method == "BA-CVA" (asserts the method label from P8.63).
      - Table uses UKB prefix (Basel 3.1 framework).

    FAILS TODAY: Pillar3TemplateBundle.ccr2 does not yet exist.

    References:
        - PS1/26 App.1 CVA Part 4.2–4.4 (BA-CVA reduced formula).
        - PRA PS1/26 Disclosure Art. 456: CCR2 mandatory CVA table.
    """

    def test_ccr2_field_exists_on_bundle(
        self,
        cva_a1_result_and_ead,
    ) -> None:
        """
        Pillar3TemplateBundle.ccr2 must be generated (not None) for a CVA run.

        Arrange:
            CVA-A1 Basel 3.1 result (with cva_counterparties attached if P8.60 shipped).
        Act:
            Generate Pillar III bundle (framework="BASEL_3_1"); access ccr2 via guard.
        Assert:
            ccr2 field exists and is not None.

        FAILS TODAY: ccr2 not a field on Pillar3TemplateBundle.

        Engine-implementer must:
            (1) Add ccr2: pl.DataFrame | None = None to Pillar3TemplateBundle.
            (2) Add _generate_ccr2() to Pillar3Generator.

        References:
            PRA PS1/26 Disclosure Art. 456: CCR2 is mandatory under Basel 3.1.
        """
        # Arrange
        result, _ead_ccr = cva_a1_result_and_ead

        # Act
        bundle = _generate_bundle(result, framework="BASEL_3_1")
        ccr2 = getattr(bundle, "ccr2", _MISSING)

        # Assert
        assert ccr2 is not _MISSING, (
            "Pillar3TemplateBundle.ccr2 does not exist (P8.51 not yet implemented). "
            "Engine-implementer: add 'ccr2: pl.DataFrame | None = None' to the dataclass "
            "and add _generate_ccr2() to Pillar3Generator. "
            "PRA PS1/26 Disclosure Art. 456: CCR2 is mandatory under Basel 3.1."
        )
        assert ccr2 is not None, (
            "P8.51 CCR2: ccr2 must be generated (not None) when cva_rwa is populated. "
            "Generator must emit CCR2 whenever AggregatedResultBundle.cva_rwa is not None."
        )

    def test_ccr2_rwea_equals_cva_rwa(
        self,
        cva_a1_result_and_ead,
    ) -> None:
        """
        CCR2 BA-CVA RWEA cell == result.cva_rwa (self-deriving).

        Arrange:
            CVA-A1 result; expected = result.cva_rwa (from P8.60 / P8.63).
        Act:
            Generate CCR2; find BA-CVA row; read RWEA cell.
        Assert:
            RWEA cell == pytest.approx(result.cva_rwa, rel=1e-6).

        References:
            PS1/26 App.1 CVA Part 4.2: RWEA = DS_BA_CVA * K_reduced * 12.5.
        """
        # Arrange
        result, ead_ccr = cva_a1_result_and_ead
        expected_cva_rwea = getattr(result, "cva_rwa", _MISSING)
        assert expected_cva_rwea is not _MISSING, (
            "AggregatedResultBundle.cva_rwa does not exist — P8.60 prerequisite."
        )
        assert expected_cva_rwea is not None, (
            "cva_rwa is None — P8.60 must populate it when cva_counterparties are attached. "
            "If cva_counterparties was not attached (P8.60 not shipped), "
            "this assertion confirms the guard is working correctly."
        )

        # Act
        bundle = _generate_bundle(result, framework="BASEL_3_1")
        ccr2 = getattr(bundle, "ccr2", _MISSING)

        assert ccr2 is not _MISSING, (
            "Pillar3TemplateBundle.ccr2 does not exist (P8.51 not yet implemented)."
        )
        assert ccr2 is not None, "P8.51 CCR2: ccr2 must not be None."
        ccr2 = cast("pl.DataFrame", ccr2)

        # Find BA-CVA row
        ba_cva_rows = ccr2.filter(
            pl.col("row_name").str.to_lowercase().str.contains("ba")
            | pl.col("row_name").str.to_lowercase().str.contains("cva")
        )
        assert ba_cva_rows.height > 0, (
            f"P8.51 CCR2: no BA-CVA row found. "
            f"Available row_names: {ccr2['row_name'].to_list()!r}. "
            "CCR2 must have a row for the BA-CVA method."
        )

        data_cols = [c for c in ccr2.columns if c not in ("row_ref", "row_name")]
        assert len(data_cols) >= 1, "P8.51 CCR2: no data columns."
        rwea_col = data_cols[0]
        actual_cva_rwea = ba_cva_rows[rwea_col][0]

        # Assert
        assert actual_cva_rwea == pytest.approx(expected_cva_rwea, rel=1e-6), (
            f"P8.51 CCR2: BA-CVA RWEA cell must equal result.cva_rwa. "
            f"Expected {expected_cva_rwea:,.6f}, got {actual_cva_rwea!r}. "
            "CCR2 must be populated from AggregatedResultBundle.cva_rwa. "
            "PS1/26 App.1 CVA Part 4.2: RWEA = DS_BA_CVA * K_reduced * 12.5."
        )

    def test_ccr2_cva_method_is_ba_cva(
        self,
        cva_a1_result_and_ead,
    ) -> None:
        """
        result.cva_method == "BA-CVA" — method label on AggregatedResultBundle.

        Arrange:
            CVA-A1 result (Basel 3.1, BA-CVA reduced).
        Act:
            Read cva_method from AggregatedResultBundle via sentinel guard.
        Assert:
            cva_method == "BA-CVA".

        FAILS TODAY: cva_method not yet a field on AggregatedResultBundle (P8.63).

        References:
            PS1/26 App.1 CVA Part: BA-CVA method label.
        """
        # Arrange / Act
        result, _ead_ccr = cva_a1_result_and_ead
        cva_method = getattr(result, "cva_method", _MISSING)

        # Assert
        assert cva_method is not _MISSING, (
            "AggregatedResultBundle.cva_method does not exist (P8.63 not yet implemented). "
            "Engine-implementer: add 'cva_method: str | None = None' to AggregatedResultBundle "
            "and set it to 'BA-CVA' when BA-CVA computation is performed."
        )
        assert cva_method == "BA-CVA", (
            f"P8.51 CCR2: result.cva_method must be 'BA-CVA', got {cva_method!r}. "
            "The label must be exactly 'BA-CVA' (not 'BA-CVA-REDUCED' or 'BA-CVA-FULL'). "
            "PS1/26 App.1 CVA Part: method discriminator for CCR2 row selection."
        )

    def test_ccr2_framework_prefix_b31(
        self,
        cva_a1_result_and_ead,
    ) -> None:
        """
        CCR2 under Basel 3.1 framework uses table-code prefix "UKB" (not "UK").

        Arrange:
            CVA-A1 result; generate with framework="BASEL_3_1".
        Act:
            Inspect bundle.framework and derive prefix.
        Assert:
            bundle.framework == "BASEL_3_1" and prefix == "UKB".

        References:
            PRA PS1/26 Disclosure Part: UKB CCR2 vs UK CCR2 naming convention.
        """
        # Arrange
        result, _ead_ccr = cva_a1_result_and_ead

        # Act
        bundle = _generate_bundle(result, framework="BASEL_3_1")
        ccr2 = getattr(bundle, "ccr2", _MISSING)

        assert ccr2 is not _MISSING, (
            "Pillar3TemplateBundle.ccr2 does not exist (P8.51 not yet implemented)."
        )

        # Assert
        assert bundle.framework == "BASEL_3_1", (
            f"P8.51 CCR2 framework check: expected 'BASEL_3_1', got {bundle.framework!r}."
        )
        prefix = "UKB" if bundle.framework == "BASEL_3_1" else "UK"
        assert prefix == "UKB", f"P8.51: Basel 3.1 run must use UKB prefix, got {prefix!r}."
