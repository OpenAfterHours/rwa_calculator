"""
Integration tests: group-wide obligor aggregates on solo / sub-consolidated runs.

Pipeline position:
    resolve_scope (GROUP_POPULATION) -> hierarchy_resolver -> classifier
    -> calculators (Art. 501 E*) -> aggregator

Review items RC-07 / RG-02 / RE-12 (one defect). The scope stage filters the
lending frames to the reporting entity's books BEFORE the hierarchy sums the
retail-threshold aggregate and before the calculators sum the SME supporting
factor's E*, so a solo or sub-consolidated run only ever saw the obligor's debt
on its own books. The rules count debt owed to the whole banking group:

- PS1/26 Art. 123A(1)(b)(ii) (regulatory retail, natural persons) and, in
  identical words, Art. 123(1)(b)(ii) (retail SMEs) and Art. 147(5)(a)(ii): "the
  total amount (including defaulted exposures) owed to the institution, its
  parent undertakings, its subsidiaries and subsidiaries of its parent
  undertakings by the obligor or group of connected clients, excluding all
  residential real estate exposures, does not exceed GBP 880,000".
- UK CRR Art. 123(c): "the total amount owed to the institution and parent
  undertakings and its subsidiaries, including any exposure in default, by the
  obligor client or group of connected clients, but excluding exposures fully and
  completely secured on residential property collateral ..., shall not, to the
  knowledge of the institution, exceed EUR 1 million. The institution shall take
  reasonable steps to acquire this knowledge."
- UK CRR Art. 501(1): "E* = the total amount owed to the institution, its
  subsidiaries, its parent undertakings and other subsidiaries of those parent
  undertakings, including any exposure in default, but excluding claims or
  contingent claims secured on residential property collateral, by the SME or
  the group of connected clients of the SME."

Every entity in the reporting-entity registry sits under the registry root, so
every in-registry book is owed to the institution, a parent, a subsidiary or a
subsidiary of a parent. Registry: PARENT (root) <- SUB. One obligor borrows on
PARENT's book (BOOK_P) and on SUB's (BOOK_S).

Hand calculations (EUR/GBP 0.8732; no collateral, no undrawn, SA):

1. Natural person, 600,000 + 600,000 personal loans. Aggregate 1,200,000 >
   CRR 873,200 / B31 880,000, so neither loan is regulatory retail: 100% (CRR
   Art. 123 fails -> corporate 100%; B31 Art. 123(3)(c) other retail 100%), RWA
   600,000 per loan. Before the fix the PARENT individual run saw 600,000 and
   priced 75% (450,000).
2. SME corporate (turnover GBP 10m), 2,000,000 + 2,000,000 drawn, CRR: E* =
   4,000,000. Tier threshold EUR 2.5m x 0.8732 = 2,183,000.
   factor = (2,183,000 x 0.7619 + 1,817,000 x 0.85) / 4,000,000 = 0.801919425;
   RWA = 2,000,000 x 100% x 0.801919425 = 1,603,838.85 per loan. Before the fix
   the individual run saw E* 2,000,000 -> 0.7619 -> 1,523,800.00.
3. Retail-managed SME (turnover GBP 2m), 500,000 + 500,000: aggregate 1,000,000
   fails both thresholds, so the loan is a corporate SME: B31 85% -> 425,000;
   CRR 100% x 0.7619 (E* 1m < 2,183,000) -> 380,950. Before the fix the SUB
   individual run priced retail 75%: B31 375,000; CRR 285,712.50.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_GROUP_THRESHOLD_FROM_OTHER_ENTITIES
from rwa_calc.domain.enums import ReportingBasis
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import make_raw_bundle

_REGISTRY = pl.DataFrame(
    {"entity_reference": ["PARENT", "SUB"], "parent_entity_reference": [None, "PARENT"]}
)
_BOOK_MAP = pl.DataFrame(
    {"book_code": ["BOOK_P", "BOOK_S"], "reporting_entity_reference": ["PARENT", "SUB"]}
)

_UNSCOPED: dict[str, Any] = {}
_PARENT_CONSOLIDATED: dict[str, Any] = {
    "reporting_entity": "PARENT",
    "reporting_basis": ReportingBasis.CONSOLIDATED,
}
_PARENT_INDIVIDUAL: dict[str, Any] = {
    "reporting_entity": "PARENT",
    "reporting_basis": ReportingBasis.INDIVIDUAL,
}
_SUB_INDIVIDUAL: dict[str, Any] = {
    "reporting_entity": "SUB",
    "reporting_basis": ReportingBasis.INDIVIDUAL,
}
_SUB_SUBCONSOLIDATED: dict[str, Any] = {
    "reporting_entity": "SUB",
    "reporting_basis": ReportingBasis.SUB_CONSOLIDATED,
}


def _config(regime: str, **scope: Any) -> CalculationConfig:
    if regime == "CRR":
        return CalculationConfig.crr(reporting_date=date(2026, 6, 30), **scope)
    # Granularity off: a one-obligor pool fails the 0.2% limb for an unrelated
    # reason and would mask the threshold limb under test.
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30), enforce_retail_granularity=False, **scope
    )


def _two_book_loans(counterparty: str, amounts: tuple[float, float]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "loan_reference": ["L_P", "L_S"],
            "counterparty_reference": [counterparty, counterparty],
            "currency": ["GBP", "GBP"],
            "book_code": ["BOOK_P", "BOOK_S"],
            "product_type": ["personal_loan", "personal_loan"],
            "drawn_amount": list(amounts),
            "value_date": [date(2025, 1, 1)] * 2,
            "maturity_date": [date(2030, 1, 1)] * 2,
        }
    )


def _bundle(counterparty: dict[str, list[Any]], amounts: tuple[float, float]):
    ref = counterparty["counterparty_reference"][0]
    return make_raw_bundle(
        loans=_two_book_loans(ref, amounts),
        counterparties=pl.DataFrame(counterparty),
        reporting_entities=_REGISTRY,
        book_entity_mappings=_BOOK_MAP,
    )


def _natural_person_bundle():
    return _bundle(
        {
            "counterparty_reference": ["IND1"],
            "entity_type": ["individual"],
            "country_code": ["GB"],
            "is_managed_as_retail": [True],
        },
        (600_000.0, 600_000.0),
    )


def _sme_bundle():
    return _bundle(
        {
            "counterparty_reference": ["SME1"],
            "entity_type": ["corporate"],
            "country_code": ["GB"],
            "annual_revenue": [10_000_000.0],
        },
        (2_000_000.0, 2_000_000.0),
    )


def _retail_sme_bundle():
    return _bundle(
        {
            "counterparty_reference": ["SME2"],
            "entity_type": ["corporate"],
            "country_code": ["GB"],
            "annual_revenue": [2_000_000.0],
            "total_assets": [1_000_000.0],
            "is_managed_as_retail": [True],
        },
        (500_000.0, 500_000.0),
    )


def _run(bundle, config: CalculationConfig) -> tuple[pl.DataFrame, set[str]]:
    result = PipelineOrchestrator().run_with_data(bundle, config)
    frame = result.results
    df = frame.collect() if isinstance(frame, pl.LazyFrame) else frame
    return df.sort("exposure_reference"), {e.code for e in result.errors}


def _row(df: pl.DataFrame, reference: str) -> dict[str, Any]:
    rows = df.filter(pl.col("exposure_reference") == reference).to_dicts()
    assert len(rows) == 1, f"expected one result row for {reference}, got {len(rows)}"
    return rows[0]


# =============================================================================
# 1. Natural-person retail threshold (Art. 123(c) / Art. 123A(1)(b)(ii))
# =============================================================================


@pytest.mark.parametrize("regime", ["CRR", "B31"])
@pytest.mark.parametrize(
    ("scope", "loan"),
    [(_PARENT_INDIVIDUAL, "L_P"), (_SUB_INDIVIDUAL, "L_S"), (_SUB_SUBCONSOLIDATED, "L_S")],
    ids=["parent-individual", "sub-individual", "sub-subconsolidated"],
)
def test_solo_run_counts_debt_owed_to_other_group_entities(
    regime: str, scope: dict[str, Any], loan: str
) -> None:
    """Each solo book holds 600,000 but the group is owed 1,200,000: not retail, 100%."""
    df, codes = _run(_natural_person_bundle(), _config(regime, **scope))

    row = _row(df, loan)
    assert row["risk_weight"] == pytest.approx(1.0)
    assert row["rwa_final"] == pytest.approx(600_000.0)
    assert ERROR_GROUP_THRESHOLD_FROM_OTHER_ENTITIES in codes


@pytest.mark.parametrize("regime", ["CRR", "B31"])
@pytest.mark.parametrize(
    "scope", [_UNSCOPED, _PARENT_CONSOLIDATED], ids=["unscoped", "parent-consolidated"]
)
def test_whole_group_runs_are_unchanged(regime: str, scope: dict[str, Any]) -> None:
    """The whole-group population was already summed: 100% on both loans, no AGG004."""
    df, codes = _run(_natural_person_bundle(), _config(regime, **scope))

    assert df["rwa_final"].to_list() == pytest.approx([600_000.0, 600_000.0])
    assert ERROR_GROUP_THRESHOLD_FROM_OTHER_ENTITIES not in codes


@pytest.mark.parametrize("regime", ["CRR", "B31"])
def test_solo_run_below_threshold_stays_retail(regime: str) -> None:
    """Group aggregate 400,000 is under both limits: the solo loan stays 75% retail.

    Guards the fix against over-reach - the out-of-scope amount is added, not
    substituted by a blanket "not retail".
    """
    bundle = _bundle(
        {
            "counterparty_reference": ["IND2"],
            "entity_type": ["individual"],
            "country_code": ["GB"],
            "is_managed_as_retail": [True],
        },
        (200_000.0, 200_000.0),
    )
    df, codes = _run(bundle, _config(regime, **_PARENT_INDIVIDUAL))

    row = _row(df, "L_P")
    assert row["risk_weight"] == pytest.approx(0.75)
    assert row["rwa_final"] == pytest.approx(150_000.0)
    assert ERROR_GROUP_THRESHOLD_FROM_OTHER_ENTITIES not in codes


# =============================================================================
# 2. CRR Art. 501 E* (SME supporting factor tier)
# =============================================================================


@pytest.mark.parametrize(
    ("scope", "loan"),
    [(_UNSCOPED, "L_P"), (_PARENT_INDIVIDUAL, "L_P"), (_SUB_INDIVIDUAL, "L_S")],
    ids=["unscoped", "parent-individual", "sub-individual"],
)
def test_e_star_counts_debt_owed_to_other_group_entities(scope: dict[str, Any], loan: str) -> None:
    """E* = 4,000,000 on every run -> factor 0.801919425, RWA 1,603,838.85."""
    df, _codes = _run(_sme_bundle(), _config("CRR", **scope))

    row = _row(df, loan)
    assert row["supporting_factor"] == pytest.approx(0.801919425)
    assert row["rwa_final"] == pytest.approx(1_603_838.85)


def test_e_star_increment_is_inert_under_basel_3_1() -> None:
    """B31 has no supporting factor: the corporate SME weighs 85% on a solo run either way."""
    df, _codes = _run(_sme_bundle(), _config("B31", **_PARENT_INDIVIDUAL))

    row = _row(df, "L_P")
    assert row["risk_weight"] == pytest.approx(0.85)
    assert row["rwa_final"] == pytest.approx(1_700_000.0)


# =============================================================================
# 3. Retail-managed SME (Art. 123(1)(b)(ii) / CRR Art. 123(c)) - review probe p14
# =============================================================================


@pytest.mark.parametrize(
    ("regime", "risk_weight", "rwa"),
    [("CRR", 1.0, 380_950.0), ("B31", 0.85, 425_000.0)],
)
@pytest.mark.parametrize(
    ("scope", "loan"),
    [(_UNSCOPED, "L_S"), (_PARENT_CONSOLIDATED, "L_S"), (_SUB_INDIVIDUAL, "L_S")],
    ids=["unscoped", "parent-consolidated", "sub-individual"],
)
def test_retail_sme_solo_run_matches_the_group(
    regime: str, risk_weight: float, rwa: float, scope: dict[str, Any], loan: str
) -> None:
    """Aggregate 1,000,000 fails both thresholds on every run: corporate SME, not retail."""
    df, _codes = _run(_retail_sme_bundle(), _config(regime, **scope))

    row = _row(df, loan)
    assert row["exposure_class"] == "corporate_sme"
    assert row["risk_weight"] == pytest.approx(risk_weight)
    assert row["rwa_final"] == pytest.approx(rwa)
