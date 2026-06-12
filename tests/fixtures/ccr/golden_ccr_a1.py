"""
Golden CCR-A1 scenario: single 10-year GBP vanilla IR swap, unmargined.

Pipeline position:
    fixture-builder output -> test-writer (tests/integration/, tests/acceptance/)
    -> engine-implementer (SA-CCR replacement cost + PFE add-on)

Scenario design:
    One trade (T_001): 10-year GBP vanilla IR swap, notional GBP 100m,
    MtM = 0.0 (at-par), delta = 1.0 (non-option directional long).
    One netting set (NS_001): counterparty CP_001, legally enforceable
    (Art. 295 condition met), unmargined (CCR-A1 scope).
    Zero margin agreements: no CSA in place.
    Zero CCR collateral: no posted or received collateral.

Regulatory hand-calc reference (unmargined RC formula, Art. 275(1)):
    RC = max(V - C, 0) = max(0.0 - 0.0, 0) = 0.0

Module-level constants are the single source of truth for test-writer
assertions and are re-exported by ``generate_p8_5_minimal.py`` under the
legacy names (TRADE_ID, NETTING_SET_ID, COUNTERPARTY_REF) so that
``tests/integration/test_ccr_loader.py`` continues to work without edits.

Portfolio bundle helpers (P8.20)
---------------------------------
``build_raw_data_bundle_with_ccr_a1()`` and ``build_raw_data_bundle_no_ccr()``
assemble a complete ``RawDataBundle`` for pipeline-integration tests:

- CP_001 is an institution counterparty (entity_type="institution", CQS 2,
  GB) so the Classifier routes the CCR-derived exposure through SA-Institution.
  CRR Art. 120(1) Table 3: institution CQS 2 → 50% risk weight.
- A matching external rating (CQS 2, S&P "A") provides the classifier's
  ``external_cqs`` input for SA risk-weight look-up.
- Zero-row facility / loan / contingent / mapping frames so the only exposure
  in the test bundle is the CCR-derived synthetic row appended by the
  pipeline adapter (P8.20 engine).
- ``ccr=RawCCRBundle(...)`` populated from the existing per-domain builders
  (with-CCR variant) or ``ccr=None`` (no-op / no-CCR variant).

References:
    - CRR Art. 271 (CCR scope)
    - CRR Art. 272(4) (netting set), 272(7) (margin agreement)
    - CRR Art. 275(1) (unmargined RC = max(V - C, 0))
    - CRR Art. 279b (PFE add-on — interest rate asset class)
    - CRR Art. 285(2)(b) (10-day minimum MPOR)
    - CRR Art. 295-297 (contractual netting recognition)
    - CRR Art. 120(1) Table 3 (institution CQS 2 SA risk weight = 50%)
    - src/rwa_calc/data/schemas.py — TRADE_SCHEMA, NETTING_SET_SCHEMA,
      MARGIN_AGREEMENT_SCHEMA, CCR_COLLATERAL_SCHEMA, COUNTERPARTY_SCHEMA,
      RATINGS_SCHEMA, FACILITY_SCHEMA, LOAN_SCHEMA, FACILITY_MAPPING_SCHEMA,
      LENDING_MAPPING_SCHEMA
"""

from __future__ import annotations

from datetime import date as _date
from pathlib import Path

import polars as pl

from rwa_calc.contracts.bundles import (
    CCRCollateralBundle,
    MarginAgreementBundle,
    NettingSetBundle,
    RawCCRBundle,
    RawDataBundle,
    TradeBundle,
)
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    CCR_COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)
from tests.fixtures.raw_bundle import make_raw_bundle

from .margin_builder import create_margin_agreements
from .netting_set_builder import NettingSet, create_netting_sets
from .trade_builder import Trade, create_trades, make_trade

# ---------------------------------------------------------------------------
# Scenario constants — single source of truth for test-writer assertions.
# ---------------------------------------------------------------------------

CCR_A1_TRADE_ID: str = "T_001"
CCR_A1_NETTING_SET_ID: str = "NS_001"
CCR_A1_COUNTERPARTY_REF: str = "CP_001"

CCR_A1_NOTIONAL: float = 100_000_000.0  # GBP 100m
CCR_A1_CURRENCY: str = "GBP"
CCR_A1_ASSET_CLASS: str = "interest_rate"
CCR_A1_TRANSACTION_TYPE: str = "derivative"
CCR_A1_MTM: float = 0.0  # at-par vanilla swap
CCR_A1_DELTA: float = 1.0  # non-option directional long
CCR_A1_IS_LONG: bool = True

# 10-year tenor: 2026-01-15 start, 2036-01-15 maturity.
CCR_A1_START_DATE: _date = _date(2026, 1, 15)
CCR_A1_MATURITY_DATE: _date = _date(2036, 1, 15)

CCR_A1_IS_LEGALLY_ENFORCEABLE: bool = True  # Art. 295 condition met
CCR_A1_IS_MARGINED: bool = False  # unmargined (CCR-A1 scope)

# ---------------------------------------------------------------------------
# P8.20 portfolio-stub constants — counterparty and rating for bundle helpers.
# ---------------------------------------------------------------------------

# CP_001: institution, CQS 2, GB.
# CRR Art. 120(1) Table 3: institution CQS 2 → 50% SA risk weight.
# entity_type="institution" → Classifier routes to ExposureClass.INSTITUTION.
CCR_A1_CP_ENTITY_TYPE: str = "institution"
CCR_A1_CP_COUNTRY_CODE: str = "GB"

# External rating: S&P "A" = CQS 2 for institutions under CRR ECRA.
# CRR Art. 120(1) Table 3: CQS 2 → risk weight 50%.
CCR_A1_RATING_REF: str = "RTG_CCR_A1_CP_001"
CCR_A1_RATING_TYPE: str = "external"
CCR_A1_RATING_AGENCY: str = "S&P"
CCR_A1_RATING_VALUE: str = "A"
CCR_A1_RATING_CQS: int = 2
CCR_A1_RATING_DATE: _date = _date(2026, 1, 15)

# Expected SA risk weight for CQS 2 institution under CRR Art. 120(1) Table 3.
CCR_A1_EXPECTED_INSTITUTION_CQS2_RW: float = 0.50


# ---------------------------------------------------------------------------
# Private scenario builders (CCR domain)
# ---------------------------------------------------------------------------


def _ccr_a1_trade() -> Trade:
    """Return the single CCR-A1 trade instance."""
    return make_trade(
        trade_id=CCR_A1_TRADE_ID,
        netting_set_id=CCR_A1_NETTING_SET_ID,
        asset_class=CCR_A1_ASSET_CLASS,
        transaction_type=CCR_A1_TRANSACTION_TYPE,
        notional=CCR_A1_NOTIONAL,
        currency=CCR_A1_CURRENCY,
        maturity_date=CCR_A1_MATURITY_DATE,
        start_date=CCR_A1_START_DATE,
        delta=CCR_A1_DELTA,
        is_long=CCR_A1_IS_LONG,
        mtm_value=CCR_A1_MTM,
    )


def _ccr_a1_netting_set() -> NettingSet:
    """Return the single CCR-A1 netting set instance."""
    return NettingSet(
        netting_set_id=CCR_A1_NETTING_SET_ID,
        counterparty_reference=CCR_A1_COUNTERPARTY_REF,
        is_legally_enforceable=CCR_A1_IS_LEGALLY_ENFORCEABLE,
        is_margined=CCR_A1_IS_MARGINED,
    )


# ---------------------------------------------------------------------------
# DataFrame factories (CCR domain)
# ---------------------------------------------------------------------------


def create_ccr_a1_trades() -> pl.DataFrame:
    """Return the single-row trades DataFrame for CCR-A1."""
    return create_trades([_ccr_a1_trade()])


def create_ccr_a1_netting_sets() -> pl.DataFrame:
    """Return the single-row netting-sets DataFrame for CCR-A1."""
    return create_netting_sets([_ccr_a1_netting_set()])


def create_ccr_a1_margin_agreements() -> pl.DataFrame:
    """Return a zero-row margin-agreements DataFrame (CCR-A1: no CSA)."""
    return create_margin_agreements([])


def create_ccr_a1_collateral() -> pl.DataFrame:
    """Return a zero-row CCR-collateral DataFrame (CCR-A1: no collateral)."""
    return pl.DataFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))


# ---------------------------------------------------------------------------
# Private portfolio-stub builders (P8.20)
# ---------------------------------------------------------------------------


def _build_cp_001_counterparty() -> pl.LazyFrame:
    """
    Return a one-row counterparty LazyFrame for CP_001.

    CP_001 is a GB institution with CQS 2 under CRR.  entity_type="institution"
    drives the Classifier to ExposureClass.INSTITUTION → SA risk weight lookup via
    CRR Art. 120(1) Table 3 (CQS 2 → 50%).

    ``institution_cqs`` is set to 2 so the SA calculator can resolve the risk
    weight even when the rating-inheritance pipeline is bypassed in narrow unit
    tests.  The matching external rating row (``_build_cp_001_rating()``) carries
    the same CQS 2 so that the full pipeline also resolves correctly.
    """
    row = {
        "counterparty_reference": CCR_A1_COUNTERPARTY_REF,
        "counterparty_name": "CCR-A1 Test Institution (CQS 2)",
        "entity_type": CCR_A1_CP_ENTITY_TYPE,
        "country_code": CCR_A1_CP_COUNTRY_CODE,
        "default_status": False,
        "apply_fi_scalar": False,
        "is_managed_as_retail": False,
        "institution_cqs": CCR_A1_RATING_CQS,
    }
    return pl.DataFrame([row], schema=dtypes_of(COUNTERPARTY_SCHEMA)).lazy()


def _build_cp_001_rating() -> pl.LazyFrame:
    """
    Return a one-row external ratings LazyFrame for CP_001.

    S&P "A" = CQS 2 under CRR ECRA mapping for institutions.
    CRR Art. 120(1) Table 3: institution CQS 2 → 50% risk weight.
    ``is_solicited=True`` (solicited rating — standard for ECRA use).
    ``pd=None`` — external ratings carry no PD (PD is internal-rating only).
    """
    row = {
        "rating_reference": CCR_A1_RATING_REF,
        "counterparty_reference": CCR_A1_COUNTERPARTY_REF,
        "rating_type": CCR_A1_RATING_TYPE,
        "rating_agency": CCR_A1_RATING_AGENCY,
        "rating_value": CCR_A1_RATING_VALUE,
        "cqs": CCR_A1_RATING_CQS,
        "pd": None,
        "rating_date": CCR_A1_RATING_DATE,
        "is_solicited": True,
        "model_id": None,
        "is_short_term": False,
        "scope_type": None,
        "scope_id": None,
    }
    return pl.DataFrame([row], schema=dtypes_of(RATINGS_SCHEMA)).lazy()


def _build_empty_facilities() -> pl.LazyFrame:
    """Return a zero-row facilities LazyFrame (no traditional lending in CCR-A1 bundle)."""
    return pl.LazyFrame(schema=dtypes_of(FACILITY_SCHEMA))


def _build_empty_loans() -> pl.LazyFrame:
    """Return a zero-row loans LazyFrame (no drawn loans in CCR-A1 bundle)."""
    return pl.LazyFrame(schema=dtypes_of(LOAN_SCHEMA))


def _build_empty_facility_mappings() -> pl.LazyFrame:
    """Return a zero-row facility-mappings LazyFrame (no facility hierarchy in CCR-A1 bundle)."""
    return pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA))


def _build_empty_lending_mappings() -> pl.LazyFrame:
    """Return a zero-row lending-mappings LazyFrame (no retail lending groups in CCR-A1 bundle)."""
    return pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA))


def _build_ccr_a1_raw_ccr_bundle() -> RawCCRBundle:
    """
    Assemble the RawCCRBundle from the four CCR-A1 domain frames.

    Composition:
        trades          — 1 row  (T_001, 10y GBP IR swap, NS_001)
        netting_sets    — 1 row  (NS_001, CP_001, enforceable, unmargined)
        margin_agreements — 0 rows (CCR-A1: unmargined, no CSA)
        ccr_collateral  — 0 rows (CCR-A1: no posted/received collateral)
    """
    return RawCCRBundle(
        trades=TradeBundle(trades=create_ccr_a1_trades().lazy()),
        netting_sets=NettingSetBundle(netting_sets=create_ccr_a1_netting_sets().lazy()),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=create_ccr_a1_margin_agreements().lazy()
        ),
        ccr_collateral=CCRCollateralBundle(ccr_collateral=create_ccr_a1_collateral().lazy()),
    )


# ---------------------------------------------------------------------------
# Public bundle-assembly helpers (P8.20)
# ---------------------------------------------------------------------------


def build_raw_data_bundle_with_ccr_a1() -> RawDataBundle:
    """
    Assemble a complete RawDataBundle with CCR-A1 data populated.

    Key responsibilities:
    - Provides CP_001 as an institution counterparty (entity_type="institution",
      CQS 2, GB) so the Classifier routes the CCR-derived synthetic exposure
      through SA-Institution (CRR Art. 120(1) Table 3 → 50% RW).
    - Provides a matching external rating (CQS 2, S&P "A") so the full
      rating-inheritance pipeline resolves ``external_cqs`` correctly.
    - Zero-row facility / loan / contingent / mapping frames so the only
      exposure in the pipeline is the CCR-derived synthetic row appended by
      the P8.20 pipeline adapter.
    - ``ccr`` is populated with a RawCCRBundle containing the single trade
      T_001 (10y GBP IR swap) in netting set NS_001 (CP_001, enforceable,
      unmargined), with empty margin and collateral frames.

    Integration test usage:
        from tests.fixtures.ccr.golden_ccr_a1 import build_raw_data_bundle_with_ccr_a1
        data = build_raw_data_bundle_with_ccr_a1()
        result = pipeline_orchestrator.run_with_data(data, config)

    References:
        - CRR Art. 271 (CCR scope)
        - CRR Art. 120(1) Table 3 (institution CQS 2 → 50% RW)
    """
    return make_raw_bundle(
        counterparties=_build_cp_001_counterparty(),
        facilities=_build_empty_facilities(),
        loans=_build_empty_loans(),
        facility_mappings=_build_empty_facility_mappings(),
        lending_mappings=_build_empty_lending_mappings(),
        ratings=_build_cp_001_rating(),
        ccr=_build_ccr_a1_raw_ccr_bundle(),
    )


def build_raw_data_bundle_no_ccr() -> RawDataBundle:
    """
    Assemble a complete RawDataBundle with ccr=None (no CCR inputs).

    Identical portfolio stub to ``build_raw_data_bundle_with_ccr_a1()`` —
    same CP_001 institution counterparty and external rating — but with
    ``ccr=None`` so the CCR pipeline stage no-ops.

    Used for:
    - Assertion 6: verifying the pipeline produces zero CCR exposures when
      ``data.ccr is None`` (no-op guard).
    - Assertion 7: regression-guard total — total RWA when CCR is absent
      equals the SA/IRB total from the traditional lending portfolio only
      (which is zero here, since all lending frames are empty).

    Integration test usage:
        from tests.fixtures.ccr.golden_ccr_a1 import build_raw_data_bundle_no_ccr
        data = build_raw_data_bundle_no_ccr()
        result = pipeline_orchestrator.run_with_data(data, config)
        assert result has zero CCR rows

    References:
        - CRR Art. 271 (CCR scope — firm with no derivatives book is outside scope)
    """
    return make_raw_bundle(
        counterparties=_build_cp_001_counterparty(),
        facilities=_build_empty_facilities(),
        loans=_build_empty_loans(),
        facility_mappings=_build_empty_facility_mappings(),
        lending_mappings=_build_empty_lending_mappings(),
        ratings=_build_cp_001_rating(),
        ccr=None,
    )


# ---------------------------------------------------------------------------
# Save helper — canonical entry point for generate_all.py and standalone use.
# ---------------------------------------------------------------------------


def save_golden_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all four CCR-A1 golden parquet files to *output_dir*.

    Files produced:
        trades.parquet              — 1 row  (T_001, 10y GBP IR swap)
        netting_sets.parquet        — 1 row  (NS_001, CP_001, enforceable, unmargined)
        margin_agreements.parquet   — 0 rows (CCR-A1: no CSA)
        ccr_collateral.parquet      — 0 rows (CCR-A1: no collateral)

    Args:
        output_dir: Target directory.  Defaults to the directory containing
            this script (``tests/fixtures/ccr/``).

    Returns:
        Dict mapping artefact name to saved absolute ``Path``.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("trades", create_ccr_a1_trades()),
        ("netting_sets", create_ccr_a1_netting_sets()),
        ("margin_agreements", create_ccr_a1_margin_agreements()),
        ("ccr_collateral", create_ccr_a1_collateral()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_golden_fixtures()
    print("CCR-A1 golden fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<25} {len(df):>2} row(s)  {len(df.columns):>2} cols  ->  {path.name}")
    print("-" * 70)
    print("Scenario: CCR-A1 — single 10y GBP IR swap, unmargined, no collateral")
    print(
        f"  Trade:       {CCR_A1_TRADE_ID} (asset_class={CCR_A1_ASSET_CLASS!r},"
        f" notional={CCR_A1_NOTIONAL:,.0f} {CCR_A1_CURRENCY})"
    )
    print(
        f"  Netting set: {CCR_A1_NETTING_SET_ID} -> {CCR_A1_COUNTERPARTY_REF}"
        f" (enforceable={CCR_A1_IS_LEGALLY_ENFORCEABLE},"
        f" margined={CCR_A1_IS_MARGINED})"
    )
    print("  Margin agreements: 0 rows (unmargined CCR-A1)")
    print("  CCR collateral:    0 rows (no posted/received collateral)")
    print()
    print("P8.20 portfolio bundle helpers:")
    bundle_ccr = build_raw_data_bundle_with_ccr_a1()
    bundle_no_ccr = build_raw_data_bundle_no_ccr()
    print(
        f"  build_raw_data_bundle_with_ccr_a1(): ccr={'present' if bundle_ccr.ccr is not None else 'absent'}"
    )
    print(
        f"  build_raw_data_bundle_no_ccr():       ccr={'present' if bundle_no_ccr.ccr is not None else 'absent'}"
    )


if __name__ == "__main__":
    main()
