"""
Generate P1.223 fixtures: obligor-level short-term ECAI spillover (Art. 120(3)(c)).

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer
    (engine/stages/hierarchy/enrich.py: ``apply_short_term_rating_override``;
    engine/sa/risk_weights.py: B31 ``_b31_append_institution_maturity_branches`` /
    CRR ``_crr_append_institution_maturity_branches``)

Key responsibilities:
- Produce one counterparty row: institution (``entity_type="bank"``), GB, not
  defaulted.
- Produce three facility rows: FAC-A / FAC-B (73-day short-term maturity
  window, 2027-01-01 -> 2027-03-15) and FAC-C (5-year long-term maturity,
  2027-01-01 -> 2032-01-01).
- Produce three loan rows, one per facility: LN-A (GBP 1,000,000 drawn,
  issue-specific ST rating attached to FAC-A), LN-B (GBP 2,000,000 drawn,
  unrated ST claim), LN-C (GBP 4,000,000 drawn, long-term claim / negative
  control).
- Produce three facility-mapping rows linking each loan to its parent
  facility (``child_type="loan"``).
- Produce two rating rows: a counterparty-wide long-term external rating
  (CQS 2, ``is_short_term=False``, scope null/null) and an issue-specific
  short-term ECAI rating scoped to FAC-A (CQS 3, ``is_short_term=True``,
  ``scope_type="facility"``, ``scope_id=FAC-A``).
- No collateral, no guarantee, no provisions — clean multi-exposure,
  single-obligor SA test.
- Framework: numerically-distinct-only-on-the-long-term-leg twin —
  ``CalculationConfig.basel_3_1()`` (primary) and ``CalculationConfig.crr()``
  (secondary, same parquets, LN-C risk weight differs 30% vs 50%).

Scenario rationale (the bug):
    Art. 120(3)(c) (PS1/26; CRR twin identical in substance) requires that
    when an issue-specific short-term ECAI assessment maps to a LESS
    favourable (higher) risk weight than the general preferential
    short-term treatment (Table 4 / Art. 120(2)) for that obligor, the
    general preferential treatment is DISAPPLIED for ALL of that obligor's
    unrated short-term claims — not just the specifically-rated exposure.

    The current engine (``apply_short_term_rating_override``,
    ``engine/stages/hierarchy/enrich.py:160-240``) applies the short-term
    override strictly per-exposure, scoped by ``(scope_type, scope_id)``.
    LN-A (the FAC-A-scoped rating target) correctly receives the Table 4A
    ECAI risk weight. But LN-B — the OTHER short-term claim on the SAME
    obligor, with no rating row of its own — incorrectly keeps the general
    preferential 20% (Table 4, CQS 2) instead of spilling over to the
    worse 100% (Table 4A, CQS 3) that Art. 120(3)(c) mandates. This is the
    capital understatement P1.223 targets.

    LN-C is a long-term claim (>3 months original maturity) on the same
    obligor: Art. 120(3)(c) spillover is scoped to short-term claims only
    (``in_st_window`` gate), so LN-C must be UNAFFECTED by the spillover —
    it is included purely as a negative control.

        FAC-A/FAC-B: 73 days = 2027-03-15 - 2027-01-01
                     original_maturity_years = 73 / 365 ~= 0.1999y (<= 0.25y -> ST window)
        FAC-C:       5 years = 2032-01-01 - 2027-01-01
                     original_maturity_years = 5.0y (> 0.25y -> long-term, NOT in ST window)

Hand-calculation (Basel 3.1, ``CalculationConfig.basel_3_1()``):
    Scalars (pack-bound via ``engine/sa/b31_risk_weight_tables.py``):
        - General preferential ST Table 4 (Art. 120(2)):     CQS <= 3 -> 20%
        - ST ECAI assessment Table 4A (Art. 120(2B)):        CQS 3    -> 100%
        - Long-term ECRA institution Table 3 (Art. 120(1)):  CQS 2    -> 30%

    Step 1 - Maturity window: FAC-A/FAC-B 73/365 ~= 0.1999y <= 0.25y -> ST
             window; FAC-C 5.0y > 0.25y -> long-term.
    Step 2 - Per-exposure ST override (existing, unchanged): LN-A matches
             the FAC-A-scoped ST rating -> cqs 2 -> 3,
             has_short_term_ecai=True. LN-B, LN-C: no scope match -> cqs
             stays 2 (inherited long-term counterparty rating),
             has_short_term_ecai=False.
    Step 3 - Art. 120(3)(c) obligor test (the fix): worst ST-assessment RW
             for INST-001 = Table 4A(CQS 3) = 100%; general preferential
             ST RW = Table 4(CQS 2) = 20%. 100% > 20% -> less favourable ->
             fires: general preferential disapplied for ALL of INST-001's
             unrated ST claims (LN-B). Scope = ST claims only
             (``in_st_window`` gate) -> LN-C (long-term) unaffected.
    Step 4 - Risk weights:
             LN-A: Table 4A CQS 3            -> 1.00
             LN-B: pre-fix Table 4 CQS 2     -> 0.20 (bug)
                   post-fix spillover        -> 1.00 (fix)
             LN-C: long-term ECRA CQS 2      -> 0.30 (Table 3, unaffected)
    Step 5 - EAD = drawn_amount + interest; RWA = EAD x RW; K = RWA x 0.08:
             LN-A: EAD 1,000,000; RWA 1,000,000; K  80,000
             LN-B: EAD 2,000,000; RWA 2,000,000; K 160,000
                   (pre-fix RWA 400,000, K 32,000)
             LN-C: EAD 4,000,000; RWA 1,200,000; K  96,000

    CRR twin (``CalculationConfig.crr()``, same parquets): LN-A/LN-B are
    numerically identical (Art. 131 Table 7 CQS 3 = 100%; Table 4 CQS 2 =
    20% -> spillover 100%). Only LN-C differs: long-term Table 3
    institution CQS 2 = 50% (vs 30% under B31) -> RWA 2,000,000, K 160,000.

    Headline fail-first assertion: LN-B.risk_weight == 1.00 and
    LN-B.rwa_final == 2,000,000 (pre-fix engine returns 0.20 / 400,000).
    LN-A (100%) and LN-C (30% B31 / 50% CRR) are regression guards that
    already pass under the current per-exposure-only override.

    Reporting-date guidance for the downstream acceptance test: pick a
    reference date strictly BEFORE 2027-03-15 (e.g. 2027-02-01) so it sits
    ahead of FAC-A/FAC-B's maturity. This fixture package carries no
    ``reporting_date`` column itself (that is a ``CalculationConfig`` run
    parameter, not a parquet field) — the constant below is documentation
    only, consumed by the acceptance test that drives
    ``CalculationConfig.basel_3_1(reporting_date=...)`` /
    ``CalculationConfig.crr(reporting_date=...)``.

References:
    - PRA PS1/26 Art. 120(3)(c) (obligor spillover; ps126app1.pdf p.41).
    - PRA PS1/26 Art. 120(2) Table 4 (general preferential short-term).
    - PRA PS1/26 Art. 120(2B) Table 4A (short-term ECAI assessment).
    - CRR Art. 120(3)(c) + Art. 120(2) Table 4 + Art. 131 Table 7
      (crr.pdf p.118).
    - BCBS CRE20.19.
    - src/rwa_calc/engine/stages/hierarchy/enrich.py:160-240
      (``apply_short_term_rating_override`` — per-exposure scoping; the
      obligor-level spillover fix belongs here or in a follow-on stage).
    - src/rwa_calc/engine/sa/risk_weights.py:634-702
      (``_b31_append_institution_maturity_branches``), :818-867
      (``_crr_append_institution_maturity_branches``).
    - src/rwa_calc/engine/sa/b31_risk_weight_tables.py (Table 3/4/4A scalar
      shims).
    - docs/specifications/crr/sa-risk-weights.md L257-273 (Short-Term
      Institution, Art. 120(2)), L605-617 (B31 Table 4A + Art. 120(3)),
      L631-653 (Short-Term Assessments, Art. 131 Table 7).
    - docs/plans/compliance-audit-crr-111-241-rectification.md L109-113
      (Section 5 WS1, P1.223).
    - tests/fixtures/p1_105/p1_105.py (single-exposure ST ECAI pattern
      anchor); tests/contracts/test_short_term_rating_override.py
      (multi-rating-row bundle shape anchor).

Usage:
    uv run python tests/fixtures/p1_223/p1_223.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

COUNTERPARTY_REF = "INST-001"

FACILITY_REF_A = "FAC-A"
FACILITY_REF_B = "FAC-B"
FACILITY_REF_C = "FAC-C"

LOAN_REF_A = "LN-A"
LOAN_REF_B = "LN-B"
LOAN_REF_C = "LN-C"

RATING_REF_LONG_TERM = "RTG-INST-001-LT"
RATING_REF_SHORT_TERM = "RTG-INST-001-ST-A"

# Short-term window: 73 days = 2027-03-15 - 2027-01-01 -> 73/365 ~= 0.1999y (<= 0.25y).
VALUE_DATE = date(2027, 1, 1)
MATURITY_DATE_SHORT_TERM = date(2027, 3, 15)
# Long-term negative control: 5 years -> > 0.25y, outside the ST window.
MATURITY_DATE_LONG_TERM = date(2032, 1, 1)

# Reference/reporting date guidance for the downstream acceptance test (not a
# fixture column) -- must sit strictly before MATURITY_DATE_SHORT_TERM.
REPORTING_DATE_GUIDANCE = date(2027, 2, 1)

LIMIT_A = 1_000_000.0
LIMIT_B = 2_000_000.0
LIMIT_C = 4_000_000.0

DRAWN_A = 1_000_000.0
DRAWN_B = 2_000_000.0
DRAWN_C = 4_000_000.0

# Long-term counterparty rating (Table 4 general preferential gate / Table 3 long-term).
CQS_LONG_TERM = 2
# Issue-specific short-term ECAI assessment attached to FAC-A (Table 4A).
CQS_SHORT_TERM = 3

RATING_AGENCY = "S&P"
RATING_VALUE_SHORT_TERM = "A-2"
RATING_DATE_SHORT_TERM = date(2027, 1, 2)

# Table 4A (Art. 120(2B)) / Art. 131 Table 7 CQS 3 -> 100%. Identical under
# both regimes.
EXPECTED_RISK_WEIGHT_LN_A: float = 1.00
# Post-fix Art. 120(3)(c) spillover: general preferential (20%) disapplied
# for LN-B -> Table 4A worst-ST-assessment RW (100%) applies instead.
EXPECTED_RISK_WEIGHT_LN_B_POST_FIX: float = 1.00
# Pre-fix (bug): LN-B incorrectly keeps the general preferential 20%.
ILLUSTRATIVE_PRE_FIX_RISK_WEIGHT_LN_B: float = 0.20
# Long-term ECRA institution risk weight, CQS 2: B31 Table 3 = 30%,
# CRR Table 3 = 50%. LN-C is a negative control -- unaffected by the
# short-term spillover under either regime.
EXPECTED_RISK_WEIGHT_LN_C_B31: float = 0.30
EXPECTED_RISK_WEIGHT_LN_C_CRR: float = 0.50

EXPECTED_RWA_LN_A: float = DRAWN_A * EXPECTED_RISK_WEIGHT_LN_A  # 1,000,000
EXPECTED_RWA_LN_B_POST_FIX: float = DRAWN_B * EXPECTED_RISK_WEIGHT_LN_B_POST_FIX  # 2,000,000
ILLUSTRATIVE_PRE_FIX_RWA_LN_B: float = DRAWN_B * ILLUSTRATIVE_PRE_FIX_RISK_WEIGHT_LN_B  # 400,000
EXPECTED_RWA_LN_C_B31: float = DRAWN_C * EXPECTED_RISK_WEIGHT_LN_C_B31  # 1,200,000
EXPECTED_RWA_LN_C_CRR: float = DRAWN_C * EXPECTED_RISK_WEIGHT_LN_C_CRR  # 2,000,000


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """P1.223 institution counterparty: entity_type=bank, country_code=GB, not defaulted."""

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    default_status: bool
    apply_fi_scalar: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
        }


@dataclass(frozen=True)
class _Facility:
    """P1.223 facility: term_loan, GBP, committed, senior, MR risk_type."""

    facility_reference: str
    counterparty_reference: str
    value_date: date
    maturity_date: date
    limit: float

    def to_dict(self) -> dict:
        return {
            "facility_reference": self.facility_reference,
            "product_type": "term_loan",
            "book_code": "FI_LENDING",
            "counterparty_reference": self.counterparty_reference,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "currency": "GBP",
            "limit": self.limit,
            "committed": True,
            "lgd": 0.45,
            "beel": 0.0,
            "is_revolving": False,
            "seniority": "senior",
            "risk_type": "MR",
            "is_short_term_trade_lc": False,
        }


@dataclass(frozen=True)
class _Loan:
    """P1.223 loan: GBP drawn, dates matching parent facility, senior."""

    loan_reference: str
    counterparty_reference: str
    value_date: date
    maturity_date: date
    drawn_amount: float

    def to_dict(self) -> dict:
        return {
            "loan_reference": self.loan_reference,
            "counterparty_reference": self.counterparty_reference,
            "currency": "GBP",
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "drawn_amount": self.drawn_amount,
            "interest": 0.0,
            "seniority": "senior",
        }


@dataclass(frozen=True)
class _FacilityMapping:
    """Maps a P1.223 loan to its parent facility."""

    parent_facility_reference: str
    child_reference: str
    child_type: str

    def to_dict(self) -> dict:
        return {
            "parent_facility_reference": self.parent_facility_reference,
            "child_reference": self.child_reference,
            "child_type": self.child_type,
        }


@dataclass(frozen=True)
class _Rating:
    """
    P1.223 external rating row (long-term counterparty rating or short-term
    issue-specific ECAI assessment).
    """

    rating_reference: str
    counterparty_reference: str
    rating_type: str
    rating_agency: str | None
    rating_value: str | None
    cqs: int
    pd: float | None
    rating_date: date | None
    is_solicited: bool
    model_id: str | None
    is_short_term: bool
    scope_type: str | None
    scope_id: str | None

    def to_dict(self) -> dict:
        return {
            "rating_reference": self.rating_reference,
            "counterparty_reference": self.counterparty_reference,
            "rating_type": self.rating_type,
            "rating_agency": self.rating_agency,
            "rating_value": self.rating_value,
            "cqs": self.cqs,
            "pd": self.pd,
            "rating_date": self.rating_date,
            "is_solicited": self.is_solicited,
            "model_id": self.model_id,
            "is_short_term": self.is_short_term,
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1223_counterparty() -> pl.DataFrame:
    """Return the P1.223 counterparty (INST-001, institution, GB) as a DataFrame."""
    row = _Counterparty(
        counterparty_reference=COUNTERPARTY_REF,
        counterparty_name="Spillover Test Bank",
        entity_type="bank",
        country_code="GB",
        default_status=False,
        apply_fi_scalar=False,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1223_facilities() -> pl.DataFrame:
    """
    Return the three P1.223 facility rows as a DataFrame.

    FAC-A / FAC-B: 73-day short-term window (2027-01-01 -> 2027-03-15).
    FAC-C: 5-year long-term maturity (2027-01-01 -> 2032-01-01), the
    negative control outside the Art. 120(3)(c) spillover scope.
    """
    rows = [
        _Facility(
            facility_reference=FACILITY_REF_A,
            counterparty_reference=COUNTERPARTY_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE_SHORT_TERM,
            limit=LIMIT_A,
        ),
        _Facility(
            facility_reference=FACILITY_REF_B,
            counterparty_reference=COUNTERPARTY_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE_SHORT_TERM,
            limit=LIMIT_B,
        ),
        _Facility(
            facility_reference=FACILITY_REF_C,
            counterparty_reference=COUNTERPARTY_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE_LONG_TERM,
            limit=LIMIT_C,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(FACILITY_SCHEMA))


def create_p1223_loans() -> pl.DataFrame:
    """
    Return the three P1.223 loan rows as a DataFrame.

    LN-A: issue-specific ST assessment (via the rating row scoped to
    FAC-A). LN-B: unrated ST claim -- the exposure that must spill over
    post-fix. LN-C: long-term claim, negative control.
    """
    rows = [
        _Loan(
            loan_reference=LOAN_REF_A,
            counterparty_reference=COUNTERPARTY_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE_SHORT_TERM,
            drawn_amount=DRAWN_A,
        ),
        _Loan(
            loan_reference=LOAN_REF_B,
            counterparty_reference=COUNTERPARTY_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE_SHORT_TERM,
            drawn_amount=DRAWN_B,
        ),
        _Loan(
            loan_reference=LOAN_REF_C,
            counterparty_reference=COUNTERPARTY_REF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE_LONG_TERM,
            drawn_amount=DRAWN_C,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_p1223_facility_mappings() -> pl.DataFrame:
    """Return the three P1.223 facility-to-loan mapping rows as a DataFrame."""
    rows = [
        _FacilityMapping(
            parent_facility_reference=FACILITY_REF_A,
            child_reference=LOAN_REF_A,
            child_type="loan",
        ),
        _FacilityMapping(
            parent_facility_reference=FACILITY_REF_B,
            child_reference=LOAN_REF_B,
            child_type="loan",
        ),
        _FacilityMapping(
            parent_facility_reference=FACILITY_REF_C,
            child_reference=LOAN_REF_C,
            child_type="loan",
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(FACILITY_MAPPING_SCHEMA))


def create_p1223_ratings() -> pl.DataFrame:
    """
    Return the two P1.223 rating rows as a DataFrame.

    Row 1 -- long-term counterparty-wide external rating: CQS 2,
    ``is_short_term=False``, scope null/null (Table 4 general preferential
    gate / Table 3 long-term fallback).
    Row 2 -- issue-specific short-term ECAI assessment: CQS 3,
    ``is_short_term=True``, ``scope_type="facility"``,
    ``scope_id=FAC-A`` (Table 4A). ``pd`` and ``model_id`` are None.
    """
    rows = [
        _Rating(
            rating_reference=RATING_REF_LONG_TERM,
            counterparty_reference=COUNTERPARTY_REF,
            rating_type="external",
            rating_agency=None,
            rating_value=None,
            cqs=CQS_LONG_TERM,
            pd=None,
            rating_date=None,
            is_solicited=True,
            model_id=None,
            is_short_term=False,
            scope_type=None,
            scope_id=None,
        ),
        _Rating(
            rating_reference=RATING_REF_SHORT_TERM,
            counterparty_reference=COUNTERPARTY_REF,
            rating_type="external",
            rating_agency=RATING_AGENCY,
            rating_value=RATING_VALUE_SHORT_TERM,
            cqs=CQS_SHORT_TERM,
            pd=None,
            rating_date=RATING_DATE_SHORT_TERM,
            is_solicited=True,
            model_id=None,
            is_short_term=True,
            scope_type="facility",
            scope_id=FACILITY_REF_A,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p1223_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.223 parquet files and return a mapping of name -> path.

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("counterparty", create_p1223_counterparty()),
        ("facility", create_p1223_facilities()),
        ("loan", create_p1223_loans()),
        ("facility_mapping", create_p1223_facility_mappings()),
        ("rating", create_p1223_ratings()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.223 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: single institution obligor INST-001, three GBP loans.")
    print("          LN-A (ST, rated CQS3 Table 4A), LN-B (ST, unrated -- spillover")
    print("          target), LN-C (long-term, negative control).")
    print("")
    print("Post-fix (Art. 120(3)(c) obligor-level spillover):")
    print(f"  LN-A risk_weight = {EXPECTED_RISK_WEIGHT_LN_A:.0%}  rwa = {EXPECTED_RWA_LN_A:,.0f}")
    print(
        f"  LN-B risk_weight = {EXPECTED_RISK_WEIGHT_LN_B_POST_FIX:.0%}  "
        f"rwa = {EXPECTED_RWA_LN_B_POST_FIX:,.0f}  "
        f"(pre-fix bug: {ILLUSTRATIVE_PRE_FIX_RISK_WEIGHT_LN_B:.0%} / "
        f"{ILLUSTRATIVE_PRE_FIX_RWA_LN_B:,.0f})"
    )
    print(
        f"  LN-C risk_weight = {EXPECTED_RISK_WEIGHT_LN_C_B31:.0%} (B31) / "
        f"{EXPECTED_RISK_WEIGHT_LN_C_CRR:.0%} (CRR)  "
        f"rwa = {EXPECTED_RWA_LN_C_B31:,.0f} (B31) / {EXPECTED_RWA_LN_C_CRR:,.0f} (CRR)"
    )
    print("")
    print(f"Reporting-date guidance for the acceptance test: {REPORTING_DATE_GUIDANCE}")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1223_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
