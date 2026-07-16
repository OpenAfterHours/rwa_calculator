"""
Generate P1.225 fixtures: CRR/PS1-26 Art. 140(2) obligor-level short-term
rating contamination.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer
    (engine/stages/hierarchy/enrich.py: ``apply_short_term_rating_override``
    obligor-level spillover; engine/sa/risk_weights.py: SA branches that must
    force 150% / floor 100% on contaminated obligors' unrated unsecured rows)

Key responsibilities:
- Produce four counterparty rows: CP_P225_X (corporate, unrated at the
  counterparty level), CP_P225_Y (institution, unrated at the counterparty
  level), CP_P225_Z (corporate, unrated, isolated control obligor — no
  ST-rated facility anywhere), CP_P225_GOV (sovereign, CQS 1 -> 0% RW
  guarantor).
- Produce six GBP 1,000,000 loans, one per scenario row (E1-E6 below), each
  scoped to its counterparty. No facilities/facility_mappings — mirrors the
  p1_216 loan-scoped rating-attachment pattern (``apply_short_term_rating_
  override`` matches ``scope_type='loan'`` directly against the loan's own
  ``exposure_reference``, no facility parent needed).
- Produce three rating rows: two loan-scoped short-term issue-specific ECAI
  assessments (E1 at CQS 4, E3 at CQS 2 — the two contamination TRIGGERS)
  plus one external long-term rating for the guarantor (CQS 1).
- Produce one guarantee row: E5, 100% covered by CP_P225_GOV — the "unsecured"
  exclusion control (Art. 140(2)(a) contaminates only UNRATED UNSECURED
  exposures; a guaranteed exposure is not unsecured, so contamination must
  not override the guarantor-substituted leg).
- No collateral, no provisions — clean multi-obligor SA test.
- Framework: both ``CalculationConfig.crr()`` and ``CalculationConfig.
  basel_3_1()`` against the SAME parquets (SA permission mode) — the
  Art. 140(2) text is identical in both regimes (CRE21.17-21.18) and the
  short-term Table 7 (CRR, landed P1.216) / Table 4A-6A (B31) risk weights
  this fixture's triggers exercise are numerically identical at CQS 2 (50%)
  and CQS 4 (150%).

Scenario rows (six loans across four obligors):

    | ref | obligor    | maturity   | rating          | role                              |
    |-----|------------|------------|-----------------|------------------------------------|
    | E1  | CP_P225_X  | short (ST) | ST-CQS4 (150%)  | TRIGGER — obligor-150%-contaminates|
    | E2  | CP_P225_X  | LONG (3y)  | unrated         | TARGET — unsecured, expect 150% post-fix (Art. 140(2)(a): "short- or long-term") |
    | E3  | CP_P225_Y  | short (ST) | ST-CQS2 (50%)   | TRIGGER — obligor-100%-floors      |
    | E4  | CP_P225_Y  | short (ST) | unrated         | TARGET — unsecured ST, expect max(base,100%) post-fix (Art. 140(2)(b)) |
    | E5  | CP_P225_X  | LONG (3y)  | unrated         | CONTROL — 100% guaranteed by CP_P225_GOV; NOT unsecured, must NOT be swept into E2's 150% contamination |
    | E6  | CP_P225_Z  | LONG (3y)  | unrated         | CONTROL — isolated obligor, no ST-rated facility anywhere; RW must not move |

    ST window: 73 days (2027-01-01 -> 2027-03-15), mirroring p1_216/p1_223
    (73/365 ~= 0.1999y <= 0.25y). Long-term negative-control window: 3 years
    (2027-01-01 -> 2030-01-01), mirroring p1_223's LN-C.

Defect under test (pre-fix):
    ``apply_short_term_rating_override`` (engine/stages/hierarchy/enrich.py:
    160-240) applies the short-term ECAI override strictly per-exposure — it
    has no obligor-level aggregation step at all (grep for 150%-contamination
    / unrated-floor logic returns nothing beyond the ``@cites`` decorator).
    E1 and E3 correctly receive their own issue-specific short-term risk
    weights (150% and 50% respectively). But Art. 140(2) requires that
    finding to CONTAMINATE the rest of the obligor's book:
        (a) if any ST-rated facility of an obligor attracts 150%, ALL
            unrated UNSECURED exposures to that obligor (short- OR
            long-term) must also be weighted 150%;
        (b) if a ST-rated facility attracts 50%, no unrated ST exposure to
            that obligor may be weighted below 100%.
    E2 (CP_P225_X, unrated, long-term, unsecured) incorrectly keeps its
    class-default 100% instead of the mandated 150% (a 50pp understatement).
    E4 (CP_P225_Y, unrated, short-term, unsecured) incorrectly keeps
    whatever the class-default unrated-institution short-term treatment is
    (pipeline-run below reports the exact pre-fix number) instead of being
    floored at 100%.

    E5 and E6 must NOT move:
        E5 is guaranteed -> not "unsecured" -> Art. 140(2)(a) never reaches
        it regardless of CP_P225_X's contamination state.
        E6's obligor (CP_P225_Z) has no ST-rated facility at all -> no
        contamination trigger exists for that obligor.

Hand-calculation (Table 7 / Table 4A-6A CQS-to-RW, numerically identical
under CRR and B31 at these two bands — see p1_216/p1_223 precedent):
    E1: CQS 4 -> 150%  -> RWA = 1,000,000 x 1.50 = 1,500,000 (both regimes)
    E3: CQS 2 -> 50%   -> RWA = 1,000,000 x 0.50 =   500,000 (both regimes)
    E2 (pre-fix):  unrated corporate      100% -> RWA = 1,000,000
    E2 (post-fix): Art. 140(2)(a) 150% contamination -> RWA = 1,500,000
    E4 (pre-fix):  unrated ST institution, SCRA grade A (Table 5A preferential
        short-term band) -> 20% -> RWA = 200,000, CONFIRMED IDENTICAL under
        both CRR (Art. 121(3)) and B31 (SCRA Table 5A) by a live pipeline run
        -- pipeline-run-verified, not assumed. A null scra_grade would instead
        hit the B31 conservative Grade-C default (150%, engine/sa/
        risk_weights.py:676-690), which sits ABOVE the 100% floor and makes
        the Art. 140(2)(b) check inert under B31; grade "A" keeps the floor
        genuinely live in both regimes.
    E4 (post-fix): Art. 140(2)(b) floor -> max(20%, 100%) = 100% -> RWA = 1,000,000
    E5: guarantor CQS 1 -> 0% RW on the guaranteed leg, BOTH pre- and
        post-fix (unsecured exclusion) -> RWA = 0 on the guaranteed leg.
    E6: unrated corporate 100% -> RWA = 1,000,000, BOTH pre- and post-fix
        (no obligor-level trigger exists for CP_P225_Z).

References:
    - CRR Art. 140(2) / PS1/26 Art. 140(2) (CRE21.17-21.18): obligor-level
      short-term-assessment contamination — 150% broadcast / 100% floor.
    - CRR Art. 140(1) / PS1/26 Art. 140(1): short-term assessments confined
      to institution/corporate obligors (CP_P225_X corporate, CP_P225_Y
      institution — both eligible; distinguishes this fixture from the
      P1.264 mis-scoping gap, out of scope here).
    - CRR Art. 131 Table 7 (landed P1.216) / PS1/26 Art. 120(2B) Table 4A /
      Art. 122(3) Table 6A: CQS 1-6 -> 20/50/100/150/150/150.
    - docs/plans/compliance-audit-crr-111-241-rectification.md:119-123
      (P1.225 finding — the fix note explicitly separates the 150%-broadcast
      (a) and 100%-floor (b) mechanics this fixture's two obligors isolate).
    - tests/fixtures/p1_216/p1_216.py: loan-scoped rating attachment pattern
      (``scope_type='loan'``, no facility parent needed) — reused here.
    - tests/fixtures/p1_223/p1_223.py: sibling Art. 120(3)(c) ST spillover
      fixture (narrower — scoped only to short-term claims); this fixture's
      E2 row is the discriminator proving Art. 140(2)(a) is a BROADER,
      short-AND-long-term obligor-level rule, not the same provision.
    - tests/fixtures/p1_10/p1_10.py: guarantor pattern reused for E5/CP_P225_GOV.

Usage:
    uv run python tests/fixtures/p1_225/p1_225.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    GUARANTEE_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

CP_X_REF = "CP_P225_X"  # corporate, unrated at counterparty level (trigger obligor A)
CP_Y_REF = "CP_P225_Y"  # institution, unrated at counterparty level (trigger obligor B)
CP_Z_REF = "CP_P225_Z"  # corporate, unrated, isolated control obligor
CP_GOV_REF = "CP_P225_GOV"  # sovereign guarantor, CQS 1 -> 0% RW

LOAN_E1_REF = "LN_P225_E1"  # CP_X, ST-CQS4 trigger (150%)
LOAN_E2_REF = "LN_P225_E2"  # CP_X, unrated long-term target
LOAN_E3_REF = "LN_P225_E3"  # CP_Y, ST-CQS2 trigger (50%)
LOAN_E4_REF = "LN_P225_E4"  # CP_Y, unrated short-term target
LOAN_E5_REF = "LN_P225_E5"  # CP_X, unrated long-term, guarantee control
LOAN_E6_REF = "LN_P225_E6"  # CP_Z, unrated long-term, isolated control

RATING_E1_REF = "RTG_P225_E1"
RATING_E3_REF = "RTG_P225_E3"
RATING_GOV_REF = "RTG_P225_GOV"

GUARANTEE_E5_REF = "GUAR_P225_E5"

# Short-term (ST) window: 73 days = 2027-03-15 - 2027-01-01 -> 73/365 ~= 0.1999y
# (<= 0.25y), mirroring p1_216 / p1_223.
VALUE_DATE = date(2027, 1, 1)
MATURITY_DATE_SHORT_TERM = date(2027, 3, 15)
# Long-term window: 3 years -> > 0.25y, outside the ST window (mirrors p1_223's LN-C).
MATURITY_DATE_LONG_TERM = date(2030, 1, 1)

DRAWN_AMOUNT = 1_000_000.0  # every loan is GBP 1,000,000 drawn, interest=0

# Issue-specific short-term ECAI assessments (Table 7 / Table 4A-6A CQS -> RW).
CQS_E1_TRIGGER_150 = 4  # CQS 4 -> 150% (Art. 140(2)(a) trigger)
CQS_E3_TRIGGER_50 = 2  # CQS 2 -> 50% (Art. 140(2)(b) trigger)
CQS_GOV = 1  # sovereign CQS 1 -> 0% RW (Art. 114 Table 1)

RATING_AGENCY = "S&P"
RATING_DATE = date(2027, 1, 2)

# Table 7 / Table 4A-6A risk weights (CQS 1-6 -> 20/50/100/150/150/150%),
# numerically identical under CRR (landed P1.216) and B31.
EXPECTED_RW_E1: float = 1.50
EXPECTED_RW_E3: float = 0.50
EXPECTED_RW_E2_PRE_FIX: float = 1.00  # unrated corporate class default
EXPECTED_RW_E2_POST_FIX: float = 1.50  # Art. 140(2)(a) 150% broadcast
# SCRA grade A (Table 5A) preferential short-term band, pipeline-run-confirmed
# identical under CRR (Art. 121(3)) and B31 (SCRA) -- see CP_P225_Y's
# scra_grade comment for why a null grade would make this row's B31 side inert.
EXPECTED_RW_E4_PRE_FIX: float = 0.20
EXPECTED_RW_E4_POST_FIX_FLOOR: float = 1.00  # Art. 140(2)(b) floor (>= 100%)
EXPECTED_RW_E5_GUARANTOR: float = 0.00  # CQS 1 sovereign, both pre- and post-fix
EXPECTED_RW_E6_CONTROL: float = 1.00  # unrated corporate, both pre- and post-fix

EXPECTED_RWA_E1: float = DRAWN_AMOUNT * EXPECTED_RW_E1  # 1,500,000
EXPECTED_RWA_E3: float = DRAWN_AMOUNT * EXPECTED_RW_E3  # 500,000
EXPECTED_RWA_E2_PRE_FIX: float = DRAWN_AMOUNT * EXPECTED_RW_E2_PRE_FIX  # 1,000,000
EXPECTED_RWA_E2_POST_FIX: float = DRAWN_AMOUNT * EXPECTED_RW_E2_POST_FIX  # 1,500,000
EXPECTED_RWA_E6: float = DRAWN_AMOUNT * EXPECTED_RW_E6_CONTROL  # 1,000,000


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """P1.225 counterparty row (trigger obligor, control obligor, or guarantor)."""

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    annual_revenue: float | None
    total_assets: float | None
    default_status: bool
    apply_fi_scalar: bool
    scra_grade: str | None = None

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "annual_revenue": self.annual_revenue,
            "total_assets": self.total_assets,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
            "scra_grade": self.scra_grade,
        }


@dataclass(frozen=True)
class _Loan:
    """P1.225 loan: GBP 1,000,000 drawn, senior, dates per scenario row."""

    loan_reference: str
    counterparty_reference: str
    maturity_date: date

    def to_dict(self) -> dict:
        return {
            "loan_reference": self.loan_reference,
            "counterparty_reference": self.counterparty_reference,
            "currency": "GBP",
            "value_date": VALUE_DATE,
            "maturity_date": self.maturity_date,
            "drawn_amount": DRAWN_AMOUNT,
            "interest": 0.0,
            "seniority": "senior",
        }


@dataclass(frozen=True)
class _Rating:
    """
    P1.225 external rating row.

    Loan-scoped short-term issue-specific ECAI assessment (``scope_type=
    'loan'`` — mirrors p1_216, no facility parent needed) for E1/E3, or a
    plain long-term external rating for the guarantor.
    """

    rating_reference: str
    counterparty_reference: str
    rating_agency: str
    rating_value: str
    cqs: int
    rating_date: date
    is_short_term: bool
    scope_type: str | None
    scope_id: str | None

    def to_dict(self) -> dict:
        return {
            "rating_reference": self.rating_reference,
            "counterparty_reference": self.counterparty_reference,
            "rating_type": "external",
            "rating_agency": self.rating_agency,
            "rating_value": self.rating_value,
            "cqs": self.cqs,
            "pd": None,
            "rating_date": self.rating_date,
            "is_solicited": True,
            "model_id": None,
            "is_short_term": self.is_short_term,
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
        }


@dataclass(frozen=True)
class _Guarantee:
    """P1.225 guarantee row: E5's loan, 100% covered by CP_P225_GOV."""

    guarantee_reference: str
    guarantor: str
    maturity_date: date
    amount_covered: float
    beneficiary_reference: str

    def to_dict(self) -> dict:
        return {
            "guarantee_reference": self.guarantee_reference,
            "guarantee_type": "sovereign_guarantee",
            "guarantor": self.guarantor,
            "currency": "GBP",
            "maturity_date": self.maturity_date,
            "amount_covered": self.amount_covered,
            "percentage_covered": 1.0,
            "beneficiary_type": "loan",
            "beneficiary_reference": self.beneficiary_reference,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p225_counterparties() -> pl.DataFrame:
    """Return the four P1.225 counterparties as a DataFrame."""
    rows = [
        _Counterparty(
            counterparty_reference=CP_X_REF,
            counterparty_name="P1.225 Trigger Corporate CP-X",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=600_000_000.0,  # large corporate, matches CORP_UR_001
            total_assets=500_000_000.0,
            default_status=False,
            apply_fi_scalar=False,
        ),
        _Counterparty(
            counterparty_reference=CP_Y_REF,
            counterparty_name="P1.225 Trigger Institution CP-Y",
            entity_type="bank",
            country_code="GB",
            annual_revenue=None,
            total_assets=None,
            default_status=False,
            apply_fi_scalar=False,
            # SCRA is the B31 assessment regime for UNRATED institutions (CP-Y has
            # no ECAI rating at the counterparty level, only the loan-scoped ST
            # assessment on E3). Grade "A" -> the preferential B31 SCRA
            # short-term band (Table 5A), keeping CP-Y genuinely "unrated" in the
            # ECRA sense while giving E4 a below-100% baseline under BOTH regimes,
            # so the Art. 140(2)(b) 100% floor actually bites under B31 too. A
            # null scra_grade would instead hit the conservative Grade-C default
            # at engine/sa/risk_weights.py:676-690 (150%, already above the
            # floor) and make the B31 side of the floor check inert. Do not
            # strip this value.
            scra_grade="A",
        ),
        _Counterparty(
            counterparty_reference=CP_Z_REF,
            counterparty_name="P1.225 Isolated Control Corporate CP-Z",
            entity_type="corporate",
            country_code="GB",
            annual_revenue=600_000_000.0,
            total_assets=500_000_000.0,
            default_status=False,
            apply_fi_scalar=False,
        ),
        _Counterparty(
            counterparty_reference=CP_GOV_REF,
            counterparty_name="P1.225 Central Government Guarantor",
            entity_type="sovereign",
            country_code="GB",
            annual_revenue=None,
            total_assets=None,
            default_status=False,
            apply_fi_scalar=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p225_loans() -> pl.DataFrame:
    """Return the six P1.225 loans (E1-E6) as a DataFrame."""
    rows = [
        _Loan(LOAN_E1_REF, CP_X_REF, MATURITY_DATE_SHORT_TERM),
        _Loan(LOAN_E2_REF, CP_X_REF, MATURITY_DATE_LONG_TERM),
        _Loan(LOAN_E3_REF, CP_Y_REF, MATURITY_DATE_SHORT_TERM),
        _Loan(LOAN_E4_REF, CP_Y_REF, MATURITY_DATE_SHORT_TERM),
        _Loan(LOAN_E5_REF, CP_X_REF, MATURITY_DATE_LONG_TERM),
        _Loan(LOAN_E6_REF, CP_Z_REF, MATURITY_DATE_LONG_TERM),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_p225_ratings() -> pl.DataFrame:
    """
    Return the three P1.225 rating rows as a DataFrame.

    RTG_P225_E1: loan-scoped ST assessment on E1, CQS 4 -> 150% (Table 7 /
    Table 4A-6A) -- the Art. 140(2)(a) 150%-contamination trigger for CP_X.
    RTG_P225_E3: loan-scoped ST assessment on E3, CQS 2 -> 50% -- the
    Art. 140(2)(b) 100%-floor trigger for CP_Y.
    RTG_P225_GOV: long-term external rating for the guarantor, CQS 1 -> 0% RW.
    """
    rows = [
        _Rating(
            rating_reference=RATING_E1_REF,
            counterparty_reference=CP_X_REF,
            rating_agency=RATING_AGENCY,
            rating_value="B",
            cqs=CQS_E1_TRIGGER_150,
            rating_date=RATING_DATE,
            is_short_term=True,
            scope_type="loan",
            scope_id=LOAN_E1_REF,
        ),
        _Rating(
            rating_reference=RATING_E3_REF,
            counterparty_reference=CP_Y_REF,
            rating_agency=RATING_AGENCY,
            rating_value="A-2",
            cqs=CQS_E3_TRIGGER_50,
            rating_date=RATING_DATE,
            is_short_term=True,
            scope_type="loan",
            scope_id=LOAN_E3_REF,
        ),
        _Rating(
            rating_reference=RATING_GOV_REF,
            counterparty_reference=CP_GOV_REF,
            rating_agency=RATING_AGENCY,
            rating_value="AAA",
            cqs=CQS_GOV,
            rating_date=RATING_DATE,
            is_short_term=False,
            scope_type=None,
            scope_id=None,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


def create_p225_guarantee() -> pl.DataFrame:
    """
    Return the single P1.225 guarantee: E5's loan, 100% covered by CP_P225_GOV.

    Maturity matches the loan (both 2030-01-01) -- no Art. 233 mismatch
    scaling to disentangle from the "unsecured exclusion" this row proves.
    """
    rows = [
        _Guarantee(
            guarantee_reference=GUARANTEE_E5_REF,
            guarantor=CP_GOV_REF,
            maturity_date=MATURITY_DATE_LONG_TERM,
            amount_covered=DRAWN_AMOUNT,
            beneficiary_reference=LOAN_E5_REF,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(GUARANTEE_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p225_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.225 parquet files and return a mapping of name to path.

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("counterparty", create_p225_counterparties()),
        ("loan", create_p225_loans()),
        ("rating", create_p225_ratings()),
        ("guarantee", create_p225_guarantee()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.225 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: CRR/PS1-26 Art. 140(2) obligor-level ST contamination")
    print(f"  E1 (CP_X trigger, ST-CQS4):  RW={EXPECTED_RW_E1:.0%}  RWA={EXPECTED_RWA_E1:,.0f}")
    print(
        f"  E2 (CP_X target, long-term unrated): pre-fix RW={EXPECTED_RW_E2_PRE_FIX:.0%} "
        f"RWA={EXPECTED_RWA_E2_PRE_FIX:,.0f} -> post-fix RW={EXPECTED_RW_E2_POST_FIX:.0%} "
        f"RWA={EXPECTED_RWA_E2_POST_FIX:,.0f}"
    )
    print(f"  E3 (CP_Y trigger, ST-CQS2):  RW={EXPECTED_RW_E3:.0%}  RWA={EXPECTED_RWA_E3:,.0f}")
    print(
        f"  E4 (CP_Y target, short-term unrated, SCRA grade A): pre-fix RW="
        f"{EXPECTED_RW_E4_PRE_FIX:.0%} (both regimes, pipeline-confirmed) -> "
        f"post-fix floor = max(RW, 100%) = {EXPECTED_RW_E4_POST_FIX_FLOOR:.0%}"
    )
    print(
        f"  E5 (CP_X, guaranteed by {CP_GOV_REF}): RW={EXPECTED_RW_E5_GUARANTOR:.0%} on the "
        "guaranteed leg, unaffected by CP_X's contamination (not unsecured)"
    )
    print(
        f"  E6 (CP_Z isolated control): RW={EXPECTED_RW_E6_CONTROL:.0%} both pre- and "
        f"post-fix (RWA={EXPECTED_RWA_E6:,.0f}) -- no ST-rated facility on this obligor"
    )


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p225_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
