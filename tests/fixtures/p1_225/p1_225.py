"""
Generate P1.225 fixtures: Art. 140(2) obligor-level short-term ECAI
contamination (150% force / 100% floor spillover to UNRATED claims).

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer
    (engine/stages/hierarchy/enrich.py: obligor-level force/floor flags,
    mirroring the ``_apply_obligor_short_term_spillover`` P1.223 pattern;
    engine/sa/risk_weights.py: CRR institution/corporate branches consume
    the force/floor flags downstream of the base risk-weight lookup)

Key responsibilities:
- Produce two counterparty rows: CP-C1 (corporate, non-SME, unrated) and
  CP-I1 (institution, non-SME, unrated). Neither carries ``annual_revenue``
  (null -> the classifier's SME size test resolves ``is_sme=False`` for
  both), and neither carries an external long-term rating row.
- Produce five loan rows, all drawn on-balance-sheet GBP, ``value_date``
  2026-06-30, unsecured (no collateral/guarantee rows at all -> Art.
  140(2)'s "unless CRM is used" carve-out never fires):
    - LN-F1 (CP-C1, 1,000,000, 90-day maturity): limb (a) TRIGGER --
      ST-rated CQS 4 -> Table 7 150%.
    - LN-L1 (CP-C1, 2,000,000, 5y maturity): limb (a) TARGET -- unrated,
      LONG-term claim. Proves Art. 140(2)(a) reaches beyond the short-term
      window (the key distinction from the Art. 120(3)(c) / P1.223
      spillover, which is short-term-window-scoped only).
    - LN-L2 (CP-C1, 500,000, 90-day maturity): limb (a) TARGET -- unrated,
      short-term claim.
    - LN-F2 (CP-I1, 800,000, 90-day maturity): limb (b) TRIGGER --
      ST-rated CQS 2 -> Table 7 50%.
    - LN-L3 (CP-I1, 600,000, 90-day maturity): limb (b) TARGET -- unrated,
      short-term claim. Proves Art. 140(2)(b) FLOORS (not forces) the
      natural Art. 121(3) unrated-institution short-term 20% up to 100%.
- Produce two rating rows -- ONLY the two ST-rated triggers carry a rating
  row; LN-L1/LN-L2/LN-L3 are unrated by omission (no rating row references
  them). Both ratings are loan-scoped (``scope_type='loan'``), mirroring
  the ``apply_short_term_rating_override`` scope-match pattern used by
  p1_216 / p1_223:
    - RT-F1: CP-C1, external, is_short_term=True, scope loan LN-F1, CQS 4.
    - RT-F2: CP-I1, external, is_short_term=True, scope loan LN-F2, CQS 2.
- No facilities, no facility_mappings, no collateral, no guarantee, no
  provisions -- clean two-obligor, five-loan, CRR-only SA test.
- Framework: UK CRR (``CalculationConfig.crr()``). Regime pin: calc date
  2026-06-30 sits inside the CRR arm (Basel 3.1 effective 2027-01-01);
  parity with PS1/26 Art. 140(2) is noted in the proposal but not
  separately asserted by this fixture.

Scenario rationale (the bug):
    CRR Art. 140(2)(a)/(b) requires that when ANY of an obligor's
    short-term-ECAI-rated exposures maps (via Art. 131 Table 7) to:
      (a) 150% (CQS 4/5/6) -- EVERY unrated, unsecured claim on that
          obligor (short- OR long-term) is contaminated to 150%; or
      (b) 50% (CQS 2) -- every unrated SHORT-TERM claim on that obligor is
          floored at max(natural_RW, 100%);
    the natural class-default risk weight is disapplied/floored
    accordingly. No obligor-level 150%/floor mechanism currently exists in
    the engine (enrich.py:783-875 implements the analogous P1.223
    Art. 120(3)(c) obligor spillover for the *general-preferential-vs-
    ECAI* comparison only; no Art. 140(2) equivalent exists yet -- this is
    the gap this fixture targets).

    Both obligors are fully UNRATED at the general/long-term level
    (``_general_cqs`` null for both), so the P1.223 Art. 120(3)(c) helper
    stays dormant here -- this fixture isolates Art. 140(2) in a
    non-conflicting way (see proposal Section 5, "P1.225 vs P1.223
    composition").

        LN-F1/LN-L2/LN-F2/LN-L3: 90 days = 2026-09-28 - 2026-06-30
                                  original_maturity_years = 90/365 ~= 0.2466y
                                  (<= 0.25y -> short-term window)
        LN-L1:                   5 years  = 2031-06-30 - 2026-06-30
                                  original_maturity_years ~= 5.0027y
                                  (> 0.25y -> long-term, outside the ST window)

Hand-calculation (CRR, ``CalculationConfig.crr()``):

    Pack scalars (value home, each cited in packs/crr.py):
        - crr_short_term_ecai_risk_weights (Art. 131 Table 7):
              CQS 1 -> 20%, CQS 2 -> 50%, CQS 3 -> 100%, CQS 4-6 -> 150%.
        - corporate_risk_weights UNRATED (Art. 122):            100%.
        - institution_short_term_unrated_rw_crr (Art. 121(3)):   20%.

    Limb (a) -- CP-C1 (corporate, unrated):
        LN-F1 (ST CQS 4, rated): Table 7 CQS 4 = 1.50 (not contaminated --
              already rated). EAD 1,000,000. RWA = 1,500,000. K = 120,000.
        LN-L1 (unrated, unsecured, LONG-term): natural Art. 122 UNRATED =
              1.00; CP-C1 has an ST facility at 150% (LN-F1) -> Art.
              140(2)(a) forces RW = 1.50 (reaches the long-term leg -- the
              defect this fixture targets). EAD 2,000,000. RWA (post-fix)
              = 3,000,000, K = 240,000 (baseline pre-fix RWA = 2,000,000,
              K = 160,000).
        LN-L2 (unrated, unsecured, short-term): natural Art. 122 UNRATED =
              1.00; forced to 1.50 by the same Art. 140(2)(a) obligor
              flag. EAD 500,000. RWA (post-fix) = 750,000, K = 60,000
              (baseline pre-fix RWA = 500,000, K = 40,000).
        CP-C1 subtotal RWA (post-fix) = 5,250,000 (baseline 4,000,000 --
              corrected understatement 1,250,000).

    Limb (b) -- CP-I1 (institution, unrated):
        LN-F2 (ST CQS 2, rated): Table 7 CQS 2 = 0.50 (not floored --
              already rated). EAD 800,000. RWA = 400,000. K = 32,000.
        LN-L3 (unrated, unsecured, short-term): natural Art. 121(3)
              unrated-institution short-term = 0.20; CP-I1 has an ST
              facility at 50% (LN-F2) -> Art. 140(2)(b) floors
              RW = max(0.20, 1.00) = 1.00. EAD 600,000. RWA (post-fix)
              = 600,000, K = 48,000 (baseline pre-fix RWA = 120,000,
              K = 9,600).
        CP-I1 subtotal RWA (post-fix) = 1,000,000 (baseline 520,000 --
              corrected understatement 480,000).

    Headline fail-first assertions (new behaviour, engine-implementer
    target): LN-L1.risk_weight == 1.50, LN-L2.risk_weight == 1.50,
    LN-L3.risk_weight == 1.00. LN-F1 (1.50) and LN-F2 (0.50) are
    regression anchors -- already correct via the existing per-exposure
    Art. 131 Table 7 override (P1.216/P1.224), unaffected by this fix.

References:
    - CRR Art. 140(2)(a)/(b) (obligor-level short-term-ECAI spillover);
      Art. 131 Table 7 (short-term credit assessment risk weights);
      Art. 122 (corporate unrated 100%); Art. 121(3) (unrated institution
      short-term 20%); Art. 140(1) (short-term treatment limited to
      institutions and corporates).
    - PRA PS1/26 Art. 140(2) (identical substance); Art. 120(2B) Table 4A;
      Art. 122(3) Table 6A (parity noted, not asserted by this fixture).
    - BCBS CRE21.17-21.18.
    - src/rwa_calc/engine/stages/hierarchy/enrich.py:160-250
      (``apply_short_term_rating_override`` -- per-exposure scope match);
      :783-875 (``_apply_obligor_short_term_spillover`` -- the P1.223
      Art. 120(3)(c) obligor-aggregate pattern this scenario mirrors; no
      Art. 140(2) 150%-force / 100%-floor equivalent exists yet).
    - src/rwa_calc/engine/sa/risk_weights.py:818-895 (CRR institution/
      corporate short-term-ECAI branches -- force/floor must apply
      downstream of the base risk-weight lookup here).
    - src/rwa_calc/data/schemas.py (LOAN_SCHEMA, COUNTERPARTY_SCHEMA,
      RATINGS_SCHEMA -- ``is_short_term``/``scope_type``/``scope_id``).
    - docs/plans/compliance-audit-crr-111-241-rectification.md Section 5
      WS1, P1.225 (two-lens verified).
    - tests/fixtures/p1_223/p1_223.py (obligor-level spillover fixture
      anchor); tests/fixtures/p1_216/p1_216.py (loan-scoped short-term
      rating attachment anchor).

Usage:
    uv run python tests/fixtures/p1_225/p1_225.py
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

# Limb (a) -- corporate obligor, 150% contamination.
COUNTERPARTY_REF_C1 = "CP-C1"
# Limb (b) -- institution obligor, 100% floor.
COUNTERPARTY_REF_I1 = "CP-I1"

LOAN_REF_F1 = "LN-F1"  # CP-C1, limb-a TRIGGER (ST-rated CQS 4)
LOAN_REF_L1 = "LN-L1"  # CP-C1, limb-a TARGET, long-term unrated
LOAN_REF_L2 = "LN-L2"  # CP-C1, limb-a TARGET, short-term unrated
LOAN_REF_F2 = "LN-F2"  # CP-I1, limb-b TRIGGER (ST-rated CQS 2)
LOAN_REF_L3 = "LN-L3"  # CP-I1, limb-b TARGET, short-term unrated

RATING_REF_F1 = "RT-F1"
RATING_REF_F2 = "RT-F2"

# Common value date; maturities set the short-term (<=0.25y) / long-term windows.
VALUE_DATE = date(2026, 6, 30)
# 90 days = 2026-09-28 - 2026-06-30 -> 90/365 ~= 0.2466y (<= 0.25y -> ST window).
MATURITY_DATE_SHORT_TERM = date(2026, 9, 28)
# 5 years = 2031-06-30 - 2026-06-30 -> ~5.0027y (> 0.25y -> long-term, outside ST window).
MATURITY_DATE_LONG_TERM = date(2031, 6, 30)

DRAWN_F1 = 1_000_000.0
DRAWN_L1 = 2_000_000.0
DRAWN_L2 = 500_000.0
DRAWN_F2 = 800_000.0
DRAWN_L3 = 600_000.0

# Reporting-date guidance for the downstream acceptance test (not a fixture
# column) -- CalculationConfig.crr(reporting_date=...) should sit on or after
# VALUE_DATE and strictly before MATURITY_DATE_SHORT_TERM so the short-term
# window is live for LN-F1/LN-L2/LN-F2/LN-L3.
REPORTING_DATE_GUIDANCE = date(2026, 6, 30)

RATING_AGENCY = "S&P"
RATING_DATE_F1 = date(2026, 6, 29)
RATING_DATE_F2 = date(2026, 6, 29)

# Art. 131 Table 7 CQS -> risk weight (identical mapping CRR/PS1/26).
CQS_TRIGGER_150 = 4  # limb (a): Table 7 CQS 4 -> 150%
CQS_TRIGGER_50 = 2  # limb (b): Table 7 CQS 2 -> 50%

TABLE7_RISK_WEIGHTS: dict[int, float] = {
    1: 0.20,
    2: 0.50,
    3: 1.00,
    4: 1.50,
    5: 1.50,
    6: 1.50,
}

# Natural (pre-contamination) unrated class-default risk weights.
UNRATED_CORPORATE_RW: float = 1.00  # Art. 122 UNRATED
UNRATED_INSTITUTION_ST_RW: float = 0.20  # Art. 121(3) unrated institution, short-term

# --- Limb (a): CP-C1 --------------------------------------------------------
EXPECTED_RISK_WEIGHT_LN_F1: float = TABLE7_RISK_WEIGHTS[CQS_TRIGGER_150]  # 1.50
EXPECTED_RWA_LN_F1: float = DRAWN_F1 * EXPECTED_RISK_WEIGHT_LN_F1  # 1,500,000

# Post-fix Art. 140(2)(a): general unrated 100% is disapplied -- forced to 150%.
EXPECTED_RISK_WEIGHT_LN_L1_POST_FIX: float = 1.50
EXPECTED_RWA_LN_L1_POST_FIX: float = DRAWN_L1 * EXPECTED_RISK_WEIGHT_LN_L1_POST_FIX  # 3,000,000
BASELINE_RISK_WEIGHT_LN_L1: float = UNRATED_CORPORATE_RW  # 1.00 (pre-fix)
BASELINE_RWA_LN_L1: float = DRAWN_L1 * BASELINE_RISK_WEIGHT_LN_L1  # 2,000,000

EXPECTED_RISK_WEIGHT_LN_L2_POST_FIX: float = 1.50
EXPECTED_RWA_LN_L2_POST_FIX: float = DRAWN_L2 * EXPECTED_RISK_WEIGHT_LN_L2_POST_FIX  # 750,000
BASELINE_RISK_WEIGHT_LN_L2: float = UNRATED_CORPORATE_RW  # 1.00 (pre-fix)
BASELINE_RWA_LN_L2: float = DRAWN_L2 * BASELINE_RISK_WEIGHT_LN_L2  # 500,000

# --- Limb (b): CP-I1 --------------------------------------------------------
EXPECTED_RISK_WEIGHT_LN_F2: float = TABLE7_RISK_WEIGHTS[CQS_TRIGGER_50]  # 0.50
EXPECTED_RWA_LN_F2: float = DRAWN_F2 * EXPECTED_RISK_WEIGHT_LN_F2  # 400,000

# Post-fix Art. 140(2)(b): floor at max(natural, 100%) -- natural 20% -> floored to 100%.
EXPECTED_RISK_WEIGHT_LN_L3_POST_FIX: float = 1.00
EXPECTED_RWA_LN_L3_POST_FIX: float = DRAWN_L3 * EXPECTED_RISK_WEIGHT_LN_L3_POST_FIX  # 600,000
BASELINE_RISK_WEIGHT_LN_L3: float = UNRATED_INSTITUTION_ST_RW  # 0.20 (pre-fix)
BASELINE_RWA_LN_L3: float = DRAWN_L3 * BASELINE_RISK_WEIGHT_LN_L3  # 120,000


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """P1.225 counterparty: corporate or institution, GB, not defaulted, unrated."""

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
    """P1.225 loan: GBP drawn on-balance-sheet, senior, unsecured (no CRM rows)."""

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
class _Rating:
    """P1.225 loan-scoped short-term external ECAI rating (the two ST triggers only)."""

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


def create_p1225_counterparties() -> pl.DataFrame:
    """Return the two P1.225 counterparty rows (CP-C1 corporate, CP-I1 institution)."""
    rows = [
        _Counterparty(
            counterparty_reference=COUNTERPARTY_REF_C1,
            counterparty_name="Obligor Contamination Test Corporate (P1.225 limb a)",
            entity_type="corporate",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
        ),
        _Counterparty(
            counterparty_reference=COUNTERPARTY_REF_I1,
            counterparty_name="Obligor Contamination Test Institution (P1.225 limb b)",
            entity_type="institution",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1225_loans() -> pl.DataFrame:
    """Return the five P1.225 loan rows (three CP-C1, two CP-I1)."""
    rows = [
        _Loan(
            loan_reference=LOAN_REF_F1,
            counterparty_reference=COUNTERPARTY_REF_C1,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE_SHORT_TERM,
            drawn_amount=DRAWN_F1,
        ),
        _Loan(
            loan_reference=LOAN_REF_L1,
            counterparty_reference=COUNTERPARTY_REF_C1,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE_LONG_TERM,
            drawn_amount=DRAWN_L1,
        ),
        _Loan(
            loan_reference=LOAN_REF_L2,
            counterparty_reference=COUNTERPARTY_REF_C1,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE_SHORT_TERM,
            drawn_amount=DRAWN_L2,
        ),
        _Loan(
            loan_reference=LOAN_REF_F2,
            counterparty_reference=COUNTERPARTY_REF_I1,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE_SHORT_TERM,
            drawn_amount=DRAWN_F2,
        ),
        _Loan(
            loan_reference=LOAN_REF_L3,
            counterparty_reference=COUNTERPARTY_REF_I1,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE_SHORT_TERM,
            drawn_amount=DRAWN_L3,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_p1225_ratings() -> pl.DataFrame:
    """
    Return the two P1.225 short-term external rating rows (the ST triggers only).

    LN-L1/LN-L2/LN-L3 deliberately carry NO rating row of their own -- they
    are unrated and rely purely on the Art. 140(2) obligor-level
    contamination/floor from their respective obligor's ST-rated sibling.
    """
    rows = [
        _Rating(
            rating_reference=RATING_REF_F1,
            counterparty_reference=COUNTERPARTY_REF_C1,
            rating_type="external",
            rating_agency=RATING_AGENCY,
            rating_value="BB",
            cqs=CQS_TRIGGER_150,
            pd=None,
            rating_date=RATING_DATE_F1,
            is_solicited=True,
            model_id=None,
            is_short_term=True,
            scope_type="loan",
            scope_id=LOAN_REF_F1,
        ),
        _Rating(
            rating_reference=RATING_REF_F2,
            counterparty_reference=COUNTERPARTY_REF_I1,
            rating_type="external",
            rating_agency=RATING_AGENCY,
            rating_value="A-2",
            cqs=CQS_TRIGGER_50,
            pd=None,
            rating_date=RATING_DATE_F2,
            is_solicited=True,
            model_id=None,
            is_short_term=True,
            scope_type="loan",
            scope_id=LOAN_REF_F2,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p1225_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.225 parquet files and return a mapping of name -> path.

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("counterparty", create_p1225_counterparties()),
        ("loan", create_p1225_loans()),
        ("rating", create_p1225_ratings()),
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
    print("Scenario: two UK CRR obligors, five GBP loans, unsecured.")
    print("  CP-C1 (corporate) -- limb (a) 150% contamination:")
    print(
        f"    LN-F1 (ST rated CQS4)      RW={EXPECTED_RISK_WEIGHT_LN_F1:.0%}  "
        f"RWA={EXPECTED_RWA_LN_F1:>12,.0f}"
    )
    print(
        f"    LN-L1 (unrated, long-term) RW={EXPECTED_RISK_WEIGHT_LN_L1_POST_FIX:.0%}  "
        f"RWA={EXPECTED_RWA_LN_L1_POST_FIX:>12,.0f}  (baseline {BASELINE_RWA_LN_L1:,.0f})"
    )
    print(
        f"    LN-L2 (unrated, short-term)RW={EXPECTED_RISK_WEIGHT_LN_L2_POST_FIX:.0%}  "
        f"RWA={EXPECTED_RWA_LN_L2_POST_FIX:>12,.0f}  (baseline {BASELINE_RWA_LN_L2:,.0f})"
    )
    print("  CP-I1 (institution) -- limb (b) 100% floor:")
    print(
        f"    LN-F2 (ST rated CQS2)      RW={EXPECTED_RISK_WEIGHT_LN_F2:.0%}  "
        f"RWA={EXPECTED_RWA_LN_F2:>12,.0f}"
    )
    print(
        f"    LN-L3 (unrated, short-term)RW={EXPECTED_RISK_WEIGHT_LN_L3_POST_FIX:.0%}  "
        f"RWA={EXPECTED_RWA_LN_L3_POST_FIX:>12,.0f}  (baseline {BASELINE_RWA_LN_L3:,.0f})"
    )
    print("")
    print(f"Reporting-date guidance for the acceptance test: {REPORTING_DATE_GUIDANCE}")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1225_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
