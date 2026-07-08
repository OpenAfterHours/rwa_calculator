"""
Generate P1.216 fixtures: CRR Art. 131 Table 7 short-term ECAI risk weights
(institution + corporate legs).

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (sa/risk_weights.py,
    engine/sa/crr_risk_weight_tables.py, rulebook/packs/crr.py)

Key responsibilities:
- Produce two counterparty rows: one institution (``entity_type=bank``), one
  corporate (``entity_type=corporate``, deliberately non-SME).
- Produce two loan rows: GBP 1,000,000 drawn each, 73-day original maturity
  window (2025-12-01 to 2026-02-12), no facility (loan-scope rating attachment
  needs no facility row — ``apply_short_term_rating_override`` matches
  ``scope_type='loan'`` directly against the loan's ``exposure_reference``).
- Produce two **short-term** external rating rows, one per leg, each
  attached via ``scope_type='loan'`` / ``scope_id=<loan_reference>`` with
  ``is_short_term=True``. CQS differs per leg by design (see rationale below).
- No collateral, no guarantee, no provisions, no facilities/facility_mappings/
  lending_mappings — clean two-exposure CRR SA test.
- Framework: CRR (``CalculationConfig.crr()``, ``PermissionMode.STANDARDISED``).

Scenario rationale:
    CRR Art. 131 Table 7 provides a dedicated short-term ECAI CQS mapping for
    institutions and corporates. The calculator currently has no CRR branch for
    this table: institution short-term-ECAI exposures fall through to the
    existing Art. 120(2) Table 4 short-term-maturity branch (keyed on residual
    maturity, not on the rating's issue-specific short-term flag), and corporate
    short-term-ECAI exposures fall through to the plain Art. 122 long-term
    ``corporate_risk_weights`` join. Both are understatements at the CQS bands
    this fixture pins.

    CQS is chosen per leg to isolate the exact divergence:
    - Institution CQS 3: Table 4 (short-term general) = 20% vs Table 7 = 100%.
      This is the cleanest institution discriminator.
    - Corporate CQS 4: Table 5/6 (Art. 122 long-term) = 100% vs Table 7 = 150%.
      Corporate CQS 3 is 100% in *both* tables and would not fail — CQS 4 is
      the only CRR corporate divergence. This is why the existing B31 fixture
      ``p1_103`` (CQS 3) cannot be reused for a CRR failing test.

    Both exposures sit in the residual-maturity ≤ 3-month window under the
    *current* (pre-fix) code, which is what proves the institution leg is
    presently routed through the Table-4 short-term-maturity branch rather
    than Table 3 (long-term) — i.e. the bug is Table-4-vs-Table-7, not
    Table-3-vs-Table-7.

        73 days = 2026-02-12 - 2025-12-01
        original_maturity_years  = 73 / 365 ≈ 0.2000y (≤ 0.25y)
        residual_maturity_years  = (2026-02-12 - 2025-12-31) / 365 ≈ 0.1178y (≤ 0.25y)

Hand-calculation (CRR, CalculationConfig.crr(reporting_date=date(2025, 12, 31))):

    Leg A — Institution, CQS 3:
        EAD = drawn_amount + interest = 1,000,000 + 0.00 = 1,000,000
        RW (correct, Table 7 Art. 131)      = 1.00  -> RWA = 1,000,000, K = 80,000
        RW (pre-fix, Table 4 Art. 120(2))   = 0.20  -> RWA =   200,000 (understated 5x)

    Leg B — Corporate, CQS 4:
        EAD = drawn_amount + interest = 1,000,000 + 0.00 = 1,000,000
        RW (correct, Table 7 Art. 131)      = 1.50  -> RWA = 1,500,000, K = 120,000
        RW (pre-fix, Art. 122 base join)    = 1.00  -> RWA = 1,000,000 (understated 50pp)

References:
    - CRR Art. 131, Table 7: short-term credit assessment risk weights
      (institutions and corporates) — 20/50/100/150/150/150 for CQS 1-6.
    - docs/specifications/crr/sa-risk-weights.md:631-653 (Table 7 + implementation-status note).
    - CRR Art. 120(2) Table 4: institution short-term general (contrastive, pre-fix path).
    - CRR Art. 122: corporate long-term risk weights (contrastive, pre-fix fallback).
    - src/rwa_calc/data/schemas.py: RATINGS_SCHEMA ``is_short_term``/``scope_type``/``scope_id``;
      VALID_RATING_SCOPE_TYPES = {"facility", "loan", "contingent"}.
    - src/rwa_calc/engine/stages/hierarchy/enrich.py: apply_short_term_rating_override
      (``scope_type='loan'`` matches the loan exposure with the same ``exposure_reference``).
    - tests/fixtures/p1_105/p1_105.py, tests/fixtures/p1_103/p1_103.py: B31 analogues
      (Table 4A / Table 6A) — not reusable for CRR (2027 dates, basel_3_1() config,
      and p1_103's CQS 3 does not diverge under CRR Art. 122 == Table 7 at CQS 3).
    - docs/plans/compliance-audit-crr-111-241-rectification.md:104-128 (WS1, P1.216 cluster).

Usage:
    uv run python tests/fixtures/p1_216/p1_216.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, LOAN_SCHEMA, RATINGS_SCHEMA

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

# Leg A — Institution
COUNTERPARTY_REF_INST = "CP_INST_ST7"
LOAN_REF_INST = "LN_INST_ST7"
RATING_REF_INST = "RTG_INST_ST7"
CQS_INST = 3

# Leg B — Corporate
COUNTERPARTY_REF_CORP = "CP_CORP_ST7"
LOAN_REF_CORP = "LN_CORP_ST7"
RATING_REF_CORP = "RTG_CORP_ST7"
CQS_CORP = 4

# Common date window: 73-day original maturity (~0.20y); residual from
# reporting_date=2025-12-31 to maturity_date is ~0.118y — both <= 0.25y so
# the pre-fix institution branch (Art. 120(2) Table 4, residual-maturity-gated)
# fires, proving the current understatement.
REPORTING_DATE = date(2025, 12, 31)
VALUE_DATE = date(2025, 12, 1)
MATURITY_DATE = date(2026, 2, 12)  # 73 days from VALUE_DATE

EAD = 1_000_000.0  # GBP 1,000,000; interest=0 -> EAD exact per leg

RATING_AGENCY = "S&P"
RATING_DATE = date(2025, 12, 2)

# Art. 131 Table 7 expected risk weights (the fix).
TABLE7_RISK_WEIGHTS: dict[int, float] = {
    1: 0.20,
    2: 0.50,
    3: 1.00,
    4: 1.50,
    5: 1.50,
    6: 1.50,
}

EXPECTED_RISK_WEIGHT_INST: float = TABLE7_RISK_WEIGHTS[CQS_INST]  # 1.00
EXPECTED_RWA_INST: float = EAD * EXPECTED_RISK_WEIGHT_INST  # 1,000,000
EXPECTED_K_INST: float = EXPECTED_RWA_INST * 0.08  # 80,000

EXPECTED_RISK_WEIGHT_CORP: float = TABLE7_RISK_WEIGHTS[CQS_CORP]  # 1.50
EXPECTED_RWA_CORP: float = EAD * EXPECTED_RISK_WEIGHT_CORP  # 1,500,000
EXPECTED_K_CORP: float = EXPECTED_RWA_CORP * 0.08  # 120,000

# Pre-fix (buggy) contrastive values — the test must NOT accept these.
TABLE4_FALLBACK_RISK_WEIGHT_INST: float = 0.20  # Art. 120(2) Table 4, CQS 3
TABLE4_FALLBACK_RWA_INST: float = EAD * TABLE4_FALLBACK_RISK_WEIGHT_INST  # 200,000

ART122_FALLBACK_RISK_WEIGHT_CORP: float = 1.00  # Art. 122 base join, CQS 4
ART122_FALLBACK_RWA_CORP: float = EAD * ART122_FALLBACK_RISK_WEIGHT_CORP  # 1,000,000


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """P1.216 counterparty: institution or corporate, GB, not defaulted."""

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
class _Loan:
    """P1.216 loan: GBP 1,000,000 drawn, 73-day maturity, senior, on-balance-sheet."""

    loan_reference: str
    counterparty_reference: str
    currency: str
    value_date: date
    maturity_date: date
    drawn_amount: float
    interest: float
    seniority: str

    def to_dict(self) -> dict:
        return {
            "loan_reference": self.loan_reference,
            "counterparty_reference": self.counterparty_reference,
            "currency": self.currency,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "drawn_amount": self.drawn_amount,
            "interest": self.interest,
            "seniority": self.seniority,
        }


@dataclass(frozen=True)
class _Rating:
    """
    P1.216 short-term external ECAI rating, loan-scoped.

    ``is_short_term=True`` with ``scope_type='loan'`` / ``scope_id=<loan_reference>``
    attaches the rating to exactly one loan exposure — ``apply_short_term_rating_override``
    matches this against the loan's own ``exposure_reference`` (no facility needed),
    overriding the counterparty-level rating inheritance and (post-fix) routing the
    CRR SA engine to Art. 131 Table 7.
    """

    rating_reference: str
    counterparty_reference: str
    rating_type: str
    rating_agency: str
    rating_value: str
    cqs: int
    pd: float | None
    rating_date: date
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


def create_p1216_counterparties() -> pl.DataFrame:
    """Return the two P1.216 counterparty rows (institution + corporate) as a DataFrame."""
    rows = [
        _Counterparty(
            counterparty_reference=COUNTERPARTY_REF_INST,
            counterparty_name="Institution, Short-Term ECAI Table 7 (P1.216 Leg A)",
            entity_type="bank",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
        ),
        _Counterparty(
            counterparty_reference=COUNTERPARTY_REF_CORP,
            counterparty_name="Corporate, Short-Term ECAI Table 7 (P1.216 Leg B)",
            entity_type="corporate",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1216_loans() -> pl.DataFrame:
    """Return the two P1.216 loan rows (one per leg) as a DataFrame."""
    rows = [
        _Loan(
            loan_reference=LOAN_REF_INST,
            counterparty_reference=COUNTERPARTY_REF_INST,
            currency="GBP",
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            drawn_amount=EAD,
            interest=0.0,
            seniority="senior",
        ),
        _Loan(
            loan_reference=LOAN_REF_CORP,
            counterparty_reference=COUNTERPARTY_REF_CORP,
            currency="GBP",
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            drawn_amount=EAD,
            interest=0.0,
            seniority="senior",
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_p1216_ratings() -> pl.DataFrame:
    """
    Return the two P1.216 short-term external rating rows (one per leg) as a DataFrame.

    Each row is loan-scoped (``scope_type='loan'``, ``scope_id=<loan_reference>``)
    with ``is_short_term=True``, routing the SA engine (post-fix) to Art. 131
    Table 7 regardless of the residual-maturity gate that drives the pre-fix
    Table-4 institution branch.
    """
    rows = [
        _Rating(
            rating_reference=RATING_REF_INST,
            counterparty_reference=COUNTERPARTY_REF_INST,
            rating_type="external",
            rating_agency=RATING_AGENCY,
            rating_value="A-2",
            cqs=CQS_INST,
            pd=None,
            rating_date=RATING_DATE,
            is_solicited=True,
            model_id=None,
            is_short_term=True,
            scope_type="loan",
            scope_id=LOAN_REF_INST,
        ),
        _Rating(
            rating_reference=RATING_REF_CORP,
            counterparty_reference=COUNTERPARTY_REF_CORP,
            rating_type="external",
            rating_agency=RATING_AGENCY,
            rating_value="A-3",
            cqs=CQS_CORP,
            pd=None,
            rating_date=RATING_DATE,
            is_solicited=True,
            model_id=None,
            is_short_term=True,
            scope_type="loan",
            scope_id=LOAN_REF_CORP,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p1216_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.216 parquet files and return a mapping of name -> path.

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("counterparty", create_p1216_counterparties()),
        ("loan", create_p1216_loans()),
        ("rating", create_p1216_ratings()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.216 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: CRR Art. 131 Table 7 — short-term ECAI risk weights")
    print(f"          value_date={VALUE_DATE}, maturity_date={MATURITY_DATE} (73 days)")
    print(f"          reporting_date={REPORTING_DATE}")
    print("")
    print("  Leg A — Institution (entity_type=bank), CQS 3:")
    print(
        f"    Table 7 (correct)  RW={EXPECTED_RISK_WEIGHT_INST:.0%}  RWA={EXPECTED_RWA_INST:>12,.0f}  K={EXPECTED_K_INST:>10,.0f}"
    )
    print(
        f"    Table 4 (pre-fix)  RW={TABLE4_FALLBACK_RISK_WEIGHT_INST:.0%}  RWA={TABLE4_FALLBACK_RWA_INST:>12,.0f}"
    )
    print("")
    print("  Leg B — Corporate (entity_type=corporate), CQS 4:")
    print(
        f"    Table 7 (correct)  RW={EXPECTED_RISK_WEIGHT_CORP:.0%}  RWA={EXPECTED_RWA_CORP:>12,.0f}  K={EXPECTED_K_CORP:>10,.0f}"
    )
    print(
        f"    Art. 122 (pre-fix) RW={ART122_FALLBACK_RISK_WEIGHT_CORP:.0%}  RWA={ART122_FALLBACK_RWA_CORP:>12,.0f}"
    )


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1216_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
