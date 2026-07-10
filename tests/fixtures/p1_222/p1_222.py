"""
Generate P1.222 fixtures: unrated Italian municipality RGLA — Table 1A CQS 3.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer
    (engine/sa/risk_weights.py: ``_prepare_risk_weight_lookup`` composite
    ``is_domestic_currency`` flag; ``_apply_b31_risk_weight_overrides`` /
    ``_apply_crr_risk_weight_overrides`` RGLA 20% branch)

Key responsibilities:
- Produce one counterparty row: Italian municipality
  (entity_type="rgla_institution"), country_code="IT", sovereign_cqs=3,
  no external rating (own CQS stays null after ratings resolution -- there
  is no ratings.parquet row for this counterparty, so the SA calculator
  hits the RGLA *unrated* branch).
- Produce one loan row: EUR 5,000,000 drawn, senior, ~5-year term (well
  outside any maturity-sensitive branch; RGLA has no short-term carve-out
  analogous to the PSE Art. 116(3) one, so the long tenor is for realism
  only).

The bug (capital understatement):
    ``_prepare_risk_weight_lookup`` builds
    ``is_domestic_currency = is_uk_domestic | is_eu_domestic``
    (engine/sa/risk_weights.py). That composite flag is legitimately reused
    for the Art. 114(4)/(7) CGCB 0% branch, but the SAME flag also gates the
    Art. 115(5) RGLA 20% branch, whose scope is UK RGLAs denominated AND
    funded in sterling only. Italy is EU-domestic-currency for EUR
    (``eu_country_domestic_currency``, packs/common.py), so
    ``is_eu_domestic`` is wrongly TRUE for this Italian municipality and the
    RGLA 20% branch fires ahead of the correct Table 1A unrated
    sovereign-derived lookup, understating risk_weight (0.20 vs the correct
    1.00) and RWA (1,000,000 vs the correct 5,000,000).

Post-fix assertion (CRR Art. 115(1)(a) Table 1A / PS1/26 Art. 115(1)(a),
identical under both regimes):
    entity_type="rgla_institution" -> SA exposure_class="rgla"
    own cqs=null (unrated) -> Table 1A sovereign-derived branch
    cp_sovereign_cqs=3 -> RGLA_RISK_WEIGHTS_SOVEREIGN_DERIVED[CQS3] = 1.00
    EAD=5,000,000 -> RWA = 5,000,000 x 1.00 = 5,000,000

Hand-calculation (identical CRR / Basel 3.1 -- Art. 115 unchanged between
regimes):
    Step 1 - Classification: entity_type="rgla_institution" ->
             SA exposure_class="rgla" (ordinary RGLA, not rgla_sovereign).
    Step 2 - UK devolved 0% branch: cp_entity_type != "rgla_sovereign" ->
             does NOT apply.
    Step 3 - Domestic-currency 20% branch (Art. 115(5), UK/GBP-scoped
             post-fix): country_code="IT", currency="EUR" ->
             is_uk_domestic=False; is_eu_domestic=True but Art. 115(5) is
             scoped to UK RGLAs funded in sterling only -> does NOT apply
             post-fix (fires incorrectly pre-fix -- see bug above).
    Step 4 - Unrated sovereign-derived lookup (Art. 115(1)(a) Table 1A):
             own cqs=null -> cp_sovereign_cqs=3 ->
             RGLA_RISK_WEIGHTS_SOVEREIGN_DERIVED[CQS3] = 1.00.
    Step 5 - RWA: EAD=5,000,000 x RW=1.00 x SF=1.0 = 5,000,000.

    Pre-fix (bug): is_domestic_currency=True (over-extended EU-domestic
    flag) -> RGLA domestic-currency branch fires first -> RW=0.20 ->
    RWA=1,000,000 (understated by 4,000,000).

References:
    - CRR Art. 115(1)(a) Table 1A / PRA PS1/26 Art. 115(1)(a) Table 1A --
      RGLA sovereign-derived risk weights (unrated RGLA).
    - CRR Art. 115(5) / PRA PS1/26 Art. 115(5) -- domestic-currency 20%,
      scoped to UK RGLAs denominated and funded in sterling.
    - CRR Art. 114(4)/(7) / PRA PS1/26 Art. 114(4)/(7) -- CGCB 0% domestic
      currency branch (legitimate use of the composite is_domestic_currency
      flag; this scenario does NOT touch that branch).
    - src/rwa_calc/rulebook/packs/crr.py:840-853 --
      rgla_risk_weights_sovereign_derived (CQS3 -> 1.00).
    - src/rwa_calc/rulebook/packs/common.py:497-501 --
      rgla_domestic_currency_rw = 0.20 (Citation CRR 115(5)).
    - src/rwa_calc/rulebook/packs/common.py:780-815 --
      eu_country_domestic_currency (IT -> EUR; confirms the mis-scoping).
    - src/rwa_calc/engine/sa/risk_weights.py:952-954 (composite
      is_domestic_currency flag), :1143 (_apply_b31_risk_weight_overrides
      RGLA 20% branch), :1349 (_apply_crr_risk_weight_overrides RGLA 20%
      branch) -- both must be fixed to scope the branch to UK/GBP only.
    - docs/plans/compliance-audit-crr-111-241-rectification.md:354-358
      (Section 5 WS6, P1.222).

Usage:
    uv run python tests/fixtures/p1_222/p1_222.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, LOAN_SCHEMA

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

COUNTERPARTY_REF = "CP_RGLA_IT_001"
LOAN_REF = "LN_RGLA_IT_001"

VALUE_DATE = date(2026, 1, 15)
MATURITY_DATE = date(2031, 1, 15)  # ~5 years -- long tenor, no maturity-sensitive branch

# Italy's sovereign CQS -> Art. 115(1)(a) Table 1A RGLA sovereign-derived RW.
# Single source of truth: src/rwa_calc/rulebook/packs/crr.py
# rgla_risk_weights_sovereign_derived (CQS3 -> 1.00).
SOVEREIGN_CQS: int = 3

EAD: float = 5_000_000.0

# Expected outputs (post-fix -- identical under CRR and Basel 3.1).
EXPECTED_EXPOSURE_CLASS = "rgla"  # ExposureClass.RGLA.value
EXPECTED_RISK_WEIGHT: float = 1.00
EXPECTED_EAD: float = EAD
EXPECTED_RWA: float = EAD * EXPECTED_RISK_WEIGHT  # 5,000,000.0

# Illustrative-only "before" figure (pre-fix RGLA domestic-currency
# over-extension). Not the primary assertion target, but useful for a
# regression-guard / documentation constant in the acceptance test.
ILLUSTRATIVE_PRE_FIX_RISK_WEIGHT: float = 0.20
ILLUSTRATIVE_PRE_FIX_RWA: float = EAD * ILLUSTRATIVE_PRE_FIX_RISK_WEIGHT  # 1,000,000.0


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    Unrated Italian municipality (rgla_institution), sovereign CQS 3.

    entity_type="rgla_institution" -> SA exposure_class "rgla" (ordinary
    RGLA, NOT "rgla_sovereign" -- so the UK-devolved 0% branch never
    applies regardless of country). No ratings.parquet row is produced for
    this counterparty, so cqs stays null after ratings resolution -> the SA
    calculator hits the RGLA unrated (Table 1A) branch.
    """

    counterparty_reference: str
    entity_type: str
    country_code: str
    sovereign_cqs: int
    default_status: bool
    apply_fi_scalar: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "sovereign_cqs": self.sovereign_cqs,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
        }


@dataclass(frozen=True)
class _Loan:
    """
    EUR 5,000,000 drawn loan to the Italian municipality.

    EAD = drawn_amount (on-balance-sheet; no CCF applied to drawn loans).
    interest=0.0 keeps EAD exactly 5,000,000 for the hand-calculation.
    currency="EUR" is Italy's domestic currency
    (``eu_country_domestic_currency``) -- the mis-scoped composite flag
    this scenario exercises.

    Note: facility_reference is NOT a column in LOAN_SCHEMA; the loan links
    directly to the counterparty via counterparty_reference. No facility
    hierarchy is exercised (mirrors the P1.220 minimal two-parquet shape).
    """

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


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1222_counterparty() -> pl.DataFrame:
    """
    Return the P1.222 counterparty as a single-row DataFrame.

    entity_type="rgla_institution" -> SA exposure class "rgla".
    sovereign_cqs=3 -> Art. 115(1)(a) Table 1A -> RW=1.00 (post-fix).
    No own CQS (cqs stays null after ratings resolution -- no
    ratings.parquet row) -> unrated RGLA path.
    country_code="IT" -- EU domestic-currency country for EUR; NOT UK, so
    the UK/GBP-scoped Art. 115(5) domestic-currency 20% branch must not
    apply post-fix.
    """
    rows = [
        _Counterparty(
            counterparty_reference=COUNTERPARTY_REF,
            entity_type="rgla_institution",
            country_code="IT",
            sovereign_cqs=SOVEREIGN_CQS,
            default_status=False,
            apply_fi_scalar=False,
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1222_loan() -> pl.DataFrame:
    """
    Return the P1.222 loan as a single-row DataFrame.

    drawn_amount=5,000,000 EUR; interest=0 -> EAD=5,000,000 exactly.
    """
    rows = [
        _Loan(
            loan_reference=LOAN_REF,
            counterparty_reference=COUNTERPARTY_REF,
            currency="EUR",
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            drawn_amount=EAD,
            interest=0.0,
            seniority="senior",
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p1222_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.222 parquet files and return a mapping of name to path.

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("counterparty", create_p1222_counterparty()),
        ("loan", create_p1222_loan()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.222 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: unrated Italian municipality (rgla_institution), IT, EUR,")
    print("          sovereign_cqs=3, EAD=5,000,000 (no collateral/guarantee/provision).")
    print("Post-fix (CRR and Basel 3.1, identical):")
    print(f"  risk_weight = {EXPECTED_RISK_WEIGHT:.2%}  (Table 1A, CQS 3 sovereign-derived)")
    print(f"  rwa         = {EXPECTED_RWA:,.0f}")
    print("Bug (pre-fix, illustrative -- RGLA domestic-currency over-extension):")
    print(f"  risk_weight = {ILLUSTRATIVE_PRE_FIX_RISK_WEIGHT:.2%}")
    print(f"  rwa         = {ILLUSTRATIVE_PRE_FIX_RWA:,.0f}")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1222_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
