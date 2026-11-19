"""
Integration tests: SME / large-FSE size tests read the consolidated group (RC-05, RC-06, RC-16).

Pipeline position:
    hierarchy_resolver (org ancestor closure) -> classifier (SME size, LFSE,
    Art. 147(4C) large corporate) -> calculators -> aggregator

RC-05. The SME size test read the entity's OWN turnover and assets, so a GBP 10m
subsidiary of a GBP 1bn group was an SME (B31 85%, CRR supporting factor 0.7619)
in the same run that called it a large corporate (CLS011). The rules size the
enterprise on its group:
- PS1/26 glossary, SME: "a micro, small or medium enterprise with an annual
  turnover of not more than GBP 44 million where: (1) the annual turnover shall
  be calculated on the basis of the highest consolidated accounts of the group to
  which the enterprise belongs, if any".
- PS1/26 Art. 153(4) "the total annual revenue for the consolidated group of
  which the entity is a part"; UK CRR Art. 153(4) "the total annual sales for the
  consolidated group of which the firm is a part".
- PS1/26 glossary, large financial sector entity: "total assets, taken at the
  highest level of consolidation at which audited financial statements are
  available, are equal to or greater than GBP 79 billion" (B31 only: UK CRR
  Art. 142(1)(4)(a) reads "calculated on an individual or consolidated basis").

RC-06. The group figure was max(own, ULTIMATE parent): an apex with no revenue
(a fund, a holding company) hid the consolidating mid-parent. It is now the max
over the entity and EVERY org ancestor.

RC-16. Under Basel 3.1 the SME definition is turnover-only and inclusive ("not
more than GBP 44 million"): no balance-sheet fallback (CLS015 when a corporate's
turnover is unknown but its assets would have qualified), and GBP 44,000,000
exactly is an SME. CRR keeps Commission Rec 2003/361/EC's balance-sheet limb
(Art. 4(1)(128D)) and its strict test.

Hand calculations (SA, unrated corporate, 1,000,000 drawn, EUR/GBP 0.8732):
- SME B31 85% -> 850,000; corporate 100% -> 1,000,000.
- SME CRR: E* 1,000,000 < EUR 2.5m x 0.8732 -> factor 0.7619 -> 761,900;
  non-SME factor 1.0 -> 1,000,000.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.contracts.errors import (
    ERROR_LARGE_CORP_GROUP_ROLLUP,
    ERROR_SME_GROUP_SIZE_FLIP,
    ERROR_SME_REVENUE_NULL_B31,
)
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.integration.conftest import (
    make_counterparty,
    make_facility,
    make_loan,
    make_model_permission,
    make_rating,
    make_raw_data_bundle,
)


def _config(regime: str, **kwargs: Any) -> CalculationConfig:
    if regime == "CRR":
        return CalculationConfig.crr(reporting_date=date(2026, 6, 30), **kwargs)
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30), **kwargs)


def _org(*edges: tuple[str, str]) -> list[dict[str, str]]:
    """(parent, child) org-mapping edges."""
    return [
        {"parent_counterparty_reference": p, "child_counterparty_reference": c} for p, c in edges
    ]


def _run(
    counterparties: list[dict[str, Any]],
    config: CalculationConfig,
    *,
    org_mappings: list[dict[str, str]] | None = None,
    borrower: str = "SUB",
    **bundle_kwargs: Any,
) -> tuple[dict[str, Any], set[str]]:
    bundle = make_raw_data_bundle(
        counterparties=counterparties,
        loans=[
            make_loan(
                loan_reference="LS",
                counterparty_reference=borrower,
                drawn_amount=1_000_000.0,
                interest=0.0,
                lgd=bundle_kwargs.pop("lgd", None),
            )
        ],
        facilities=[
            make_facility(facility_reference="FS", counterparty_reference=borrower, limit=0.0)
        ],
        facility_mappings=[],
        org_mappings=org_mappings,
        **bundle_kwargs,
    )
    result = PipelineOrchestrator().run_with_data(bundle, config)
    frame = result.results
    df = frame.collect() if isinstance(frame, pl.LazyFrame) else frame
    rows = df.filter(pl.col("exposure_reference") == "LS").to_dicts()
    assert len(rows) == 1
    return rows[0], {e.code for e in result.errors}


_PARENT_1BN = make_counterparty(
    counterparty_reference="P", annual_revenue=1_000_000_000.0, total_assets=2_000_000_000.0
)
_SUB_10M = make_counterparty(
    counterparty_reference="SUB", annual_revenue=10_000_000.0, total_assets=20_000_000.0
)


# =============================================================================
# RC-05: the SME size test reads the consolidated group
# =============================================================================


@pytest.mark.parametrize(("regime", "factor"), [("CRR", 1.0), ("B31", 1.0)], ids=["CRR", "B31"])
def test_subsidiary_of_large_group_is_not_an_sme(regime: str, factor: float) -> None:
    """Own 10m under a 1bn group: corporate 100%, no SME weight / factor, CLS016."""
    row, codes = _run([_PARENT_1BN, _SUB_10M], _config(regime), org_mappings=_org(("P", "SUB")))

    assert row["exposure_class"] == "corporate"
    assert row["risk_weight"] == pytest.approx(1.0)
    assert row["supporting_factor"] == pytest.approx(factor)
    assert row["rwa_final"] == pytest.approx(1_000_000.0)
    assert ERROR_SME_GROUP_SIZE_FLIP in codes


@pytest.mark.parametrize(
    ("regime", "risk_weight", "rwa"),
    [("CRR", 1.0, 761_900.0), ("B31", 0.85, 850_000.0)],
    ids=["CRR", "B31"],
)
def test_standalone_sme_keeps_sme_treatment(regime: str, risk_weight: float, rwa: float) -> None:
    """The same 10m entity with no group: SME treatment, no CLS016 (control)."""
    row, codes = _run([_PARENT_1BN, _SUB_10M], _config(regime))

    assert row["exposure_class"] == "corporate_sme"
    assert row["risk_weight"] == pytest.approx(risk_weight)
    assert row["rwa_final"] == pytest.approx(rwa)
    assert ERROR_SME_GROUP_SIZE_FLIP not in codes


@pytest.mark.parametrize("regime", ["CRR", "B31"])
def test_small_group_keeps_sme_treatment(regime: str) -> None:
    """Own 10m under a 30m group: still an SME on the consolidated figure."""
    parent = make_counterparty(
        counterparty_reference="P", annual_revenue=30_000_000.0, total_assets=30_000_000.0
    )
    row, codes = _run([parent, _SUB_10M], _config(regime), org_mappings=_org(("P", "SUB")))

    assert row["exposure_class"] == "corporate_sme"
    assert ERROR_SME_GROUP_SIZE_FLIP not in codes


# =============================================================================
# RC-06: the group figure is the max over EVERY org ancestor
# =============================================================================


@pytest.mark.parametrize(
    "edges",
    [(("TOPFUND", "MIDCO"), ("MIDCO", "SUB")), (("MIDCO", "SUB"),)],
    ids=["fund-midco-sub", "midco-sub"],
)
def test_null_revenue_apex_does_not_hide_the_consolidating_midco(
    edges: tuple[tuple[str, str], ...],
) -> None:
    """B31, A-IRB permission only: MIDCO's GBP 1bn makes SUB a large corporate.

    Art. 147(4C)(b)(ii) forces F-IRB; with no F-IRB permission the loan falls to
    SA, unrated corporate 100% -> 1,000,000 with CLS011, whether or not a
    null-revenue fund sits above MIDCO. (Before: the fund hid MIDCO -> A-IRB
    568,750.)
    """
    counterparties = [
        make_counterparty(counterparty_reference="TOPFUND", annual_revenue=None, total_assets=None),
        make_counterparty(counterparty_reference="MIDCO", annual_revenue=1e9, total_assets=3e9),
        make_counterparty(counterparty_reference="SUB", annual_revenue=300e6, total_assets=600e6),
    ]
    row, codes = _run(
        counterparties,
        _config("B31", permission_mode=PermissionMode.IRB),
        org_mappings=_org(*edges),
        ratings=[
            make_rating(rating_reference="RS", counterparty_reference="SUB", pd=0.01, model_id="M1")
        ],
        model_permissions=[
            make_model_permission(
                model_id="M1", exposure_class="corporate", approach="advanced_irb"
            )
        ],
        lgd=0.20,
    )

    assert row["approach_applied"] == "standardised"
    assert row["rwa_final"] == pytest.approx(1_000_000.0)
    assert ERROR_LARGE_CORP_GROUP_ROLLUP in codes


@pytest.mark.parametrize("regime", ["CRR", "B31"])
def test_sme_size_reads_a_mid_level_consolidator_under_a_null_apex(regime: str) -> None:
    """Fund (no figures) -> MIDCO 100m -> SUB 10m: not an SME in either regime."""
    counterparties = [
        make_counterparty(counterparty_reference="TOPFUND", annual_revenue=None, total_assets=None),
        make_counterparty(counterparty_reference="MIDCO", annual_revenue=100e6, total_assets=200e6),
        _SUB_10M,
    ]
    row, _codes = _run(
        counterparties,
        _config(regime),
        org_mappings=_org(("TOPFUND", "MIDCO"), ("MIDCO", "SUB")),
    )

    assert row["exposure_class"] == "corporate"
    assert row["rwa_final"] == pytest.approx(1_000_000.0)


# =============================================================================
# RC-16: Basel 3.1 SME definition is turnover-only and inclusive
# =============================================================================


def test_b31_unknown_turnover_is_not_an_sme_even_with_small_assets() -> None:
    """B31, revenue null, assets 10m: corporate 100% (no balance-sheet limb), CLS015."""
    cp = make_counterparty(counterparty_reference="SUB", annual_revenue=None, total_assets=10e6)
    row, codes = _run([cp], _config("B31"))

    assert row["exposure_class"] == "corporate"
    assert row["risk_weight"] == pytest.approx(1.0)
    assert row["rwa_final"] == pytest.approx(1_000_000.0)
    assert ERROR_SME_REVENUE_NULL_B31 in codes


def test_crr_keeps_the_balance_sheet_limb() -> None:
    """CRR, revenue null, assets 10m: corporate SME (Rec 2003/361 Art. 2), factor 1.0.

    The Art. 501 factor is turnover-only (Art. 501(2)(b)), so no 0.7619 without a
    revenue figure: 1,000,000. No CLS015 under CRR.
    """
    cp = make_counterparty(counterparty_reference="SUB", annual_revenue=None, total_assets=10e6)
    row, codes = _run([cp], _config("CRR"))

    assert row["exposure_class"] == "corporate_sme"
    assert row["supporting_factor"] == pytest.approx(1.0)
    assert row["rwa_final"] == pytest.approx(1_000_000.0)
    assert ERROR_SME_REVENUE_NULL_B31 not in codes


@pytest.mark.parametrize(
    ("revenue", "exposure_class", "rwa"),
    [
        (43_999_999.0, "corporate_sme", 850_000.0),
        (44_000_000.0, "corporate_sme", 850_000.0),
        (44_000_001.0, "corporate", 1_000_000.0),
    ],
)
def test_b31_turnover_bound_is_not_more_than_gbp_44m(
    revenue: float, exposure_class: str, rwa: float
) -> None:
    """'not more than GBP 44 million': 44,000,000 exactly is an SME (85%)."""
    cp = make_counterparty(counterparty_reference="SUB", annual_revenue=revenue, total_assets=100e6)
    row, _codes = _run([cp], _config("B31"))

    assert row["exposure_class"] == exposure_class
    assert row["rwa_final"] == pytest.approx(rwa)


# =============================================================================
# RC-05 LFSE limb (B31 only): total assets at the highest level of consolidation
# =============================================================================


@pytest.mark.parametrize(("regime", "expected"), [("CRR", False), ("B31", True)])
def test_lfse_reads_group_assets_under_b31_only(regime: str, expected: bool) -> None:
    """FSE subsidiary with GBP 5bn own assets in a GBP 500bn group.

    B31: the glossary takes total assets "at the highest level of consolidation"
    -> large FSE -> 1.25x correlation (requires_fi_scalar). CRR Art. 142(1)(4)(a)
    accepts the individual basis, which the engine keeps -> no scalar.
    """
    counterparties = [
        make_counterparty(
            counterparty_reference="P",
            entity_type="institution",
            annual_revenue=None,
            total_assets=500e9,
            is_financial_sector_entity=True,
        ),
        make_counterparty(
            counterparty_reference="SUB",
            entity_type="corporate",
            annual_revenue=500e6,
            total_assets=5e9,
            is_financial_sector_entity=True,
        ),
    ]
    row, _codes = _run(
        counterparties,
        _config(regime, permission_mode=PermissionMode.IRB),
        org_mappings=_org(("P", "SUB")),
        ratings=[
            make_rating(rating_reference="RS", counterparty_reference="SUB", pd=0.01, model_id="M1")
        ],
        model_permissions=[
            make_model_permission(
                model_id="M1", exposure_class="corporate", approach="foundation_irb"
            )
        ],
    )

    assert row["requires_fi_scalar"] is expected
