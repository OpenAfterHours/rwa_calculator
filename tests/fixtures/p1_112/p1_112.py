"""
Generate P1.112 fixtures: non-UK unrated PSE sovereign-derived risk weight.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (sa/namespace.py fix)

Key responsibilities:
- Produce one counterparty row: German PSE (entity_type=pse_institution),
  sovereign_cqs=1, own cqs=null (unrated), country_code=DE.
- Produce one facility row: EUR, committed, 5-year term.
- Produce one loan row: fully drawn, EUR 100,000,000.
- Produce one facility-mapping row linking facility to loan.
- Produce one FX rate row: EUR->GBP = 1.0 (arithmetic clarity).

Defect under test (pre-fix):
    In engine/sa/namespace.py the unrated PSE branch evaluates:
        cp_country_code == "GB"  ->  20% (domestic)
        otherwise                ->  100% (pse_unrated fallback)
    A non-UK PSE backed by a CQS 1 sovereign should receive 20%, not 100%.

Post-fix assertion (Art. 116(1) Table 2, PSE_RISK_WEIGHTS_SOVEREIGN_DERIVED):
    cp_sovereign_cqs=1 -> risk_weight=0.20
    EAD=100_000_000, RWA=20_000_000

Hand-calculation (Basel 3.1, CalculationConfig.basel_3_1()):
    Step 1 - Classification: entity_type="pse_institution" -> exposure_class="pse"
    Step 2 - Domestic check: cp_country_code="DE", currency="EUR" -> not UK domestic
    Step 3 - Short-term carve-out (Art. 116(3)): maturity=5yr -> does NOT apply
    Step 4 - Unrated PSE branch: cqs=null -> sentinel=-1 -> unrated path
    Step 5 - Sovereign-derived lookup (Art. 116(1) Table 2):
             cp_sovereign_cqs=1 -> PSE_RISK_WEIGHTS_SOVEREIGN_DERIVED[1] = 0.20
    Step 6 - RWA: EAD=100_000_000 x RW=0.20 = 20_000_000

    Current bug: code uses country_code != "GB" -> pse_unrated=1.00 -> RWA=100_000_000
                 (5x overstatement)

References:
    - CRR Art. 116(1) Table 2 — sovereign-derived PSE risk weights (unrated PSE)
    - PRA PS1/26 Art. 116(1) Table 2 (identical values)
    - src/rwa_calc/data/tables/crr_risk_weights.py:207-214 (PSE_RISK_WEIGHTS_SOVEREIGN_DERIVED)
    - src/rwa_calc/data/tables/crr_risk_weights.py:233 (PSE_UNRATED_DEFAULT_RW = 1.00)
    - src/rwa_calc/engine/sa/namespace.py:867-872 (B31 PSE unrated branch — bug site)
    - docs/specifications/basel31/sa-risk-weights.md lines 165-199

Usage:
    uv run python tests/fixtures/p1_112/p1_112.py
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
    FX_RATES_SCHEMA,
    LOAN_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

COUNTERPARTY_REF = "CP_PSE_DE_001"
FACILITY_REF = "FAC_PSE_DE_001"
LOAN_REF = "LN_PSE_DE_001"

VALUE_DATE = date(2026, 1, 15)
MATURITY_DATE = date(2031, 1, 15)  # ~5 years; guards Art. 116(3) short-term carve-out

# Sovereign CQS of Germany — CQS 1 -> PSE risk weight = 20% (Art. 116(1) Table 2)
# Single source of truth: src/rwa_calc/data/tables/crr_risk_weights.py:207-214
SOVEREIGN_CQS: int = 1
EXPECTED_RISK_WEIGHT: float = 0.20

LOAN_AMOUNT: float = 100_000_000.0  # EUR 100m

# FX rate pinned to 1.0 for arithmetic clarity: EUR -> GBP = 1.0
# This means EAD_GBP == EAD_EUR == 100_000_000 and RWA_GBP == 20_000_000
FX_EUR_GBP: float = 1.0


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """German PSE (pse_institution), unrated, sovereign CQS 1."""

    counterparty_reference: str
    entity_type: str
    country_code: str
    sovereign_cqs: int  # CQS of the backing sovereign (Germany = 1)
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
class _Facility:
    """
    EUR committed 5-year term facility.

    Maturity of 5 years explicitly guards Art. 116(3): the short-term carve-out
    (<=3 months original maturity -> 20% regardless of CQS) must NOT fire here.
    risk_type="FR" is appropriate for a fully drawn term loan facility.
    """

    facility_reference: str
    counterparty_reference: str
    currency: str
    value_date: date
    maturity_date: date
    limit: float
    committed: bool
    seniority: str
    risk_type: str

    def to_dict(self) -> dict:
        return {
            "facility_reference": self.facility_reference,
            "counterparty_reference": self.counterparty_reference,
            "currency": self.currency,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "limit": self.limit,
            "committed": self.committed,
            "seniority": self.seniority,
            "risk_type": self.risk_type,
        }


@dataclass(frozen=True)
class _Loan:
    """
    EUR 100m drawn loan.

    EAD = drawn_amount (on-balance sheet; no CCF applied to drawn loans).
    interest=0.0: no accrued interest — keeps EAD exactly 100_000_000 for
    the hand-calculation.

    Note: facility_reference is NOT a column in LOAN_SCHEMA; the parent-child
    link is expressed via FACILITY_MAPPING_SCHEMA (parent_facility_reference /
    child_reference / child_type). The _FacilityMapping row carries that link.
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


@dataclass(frozen=True)
class _FacilityMapping:
    """Maps the P1.112 facility to its loan child."""

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
class _FXRate:
    """FX rate pinned to 1.0 for arithmetic clarity."""

    currency_from: str
    currency_to: str
    rate: float

    def to_dict(self) -> dict:
        return {
            "currency_from": self.currency_from,
            "currency_to": self.currency_to,
            "rate": self.rate,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1112_counterparty() -> pl.DataFrame:
    """
    Return the P1.112 counterparty as a single-row DataFrame.

    entity_type="pse_institution" -> SA exposure class "pse".
    sovereign_cqs=1 -> Art. 116(1) Table 2 -> RW=20%.
    No own CQS (cqs will be null after ratings resolution) -> unrated PSE path.
    country_code="DE" -> non-UK -> the existing bug returns 100%, fix returns 20%.
    """
    rows = [
        _Counterparty(
            counterparty_reference=COUNTERPARTY_REF,
            entity_type="pse_institution",
            country_code="DE",
            sovereign_cqs=SOVEREIGN_CQS,
            default_status=False,
            apply_fi_scalar=False,
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1112_facility() -> pl.DataFrame:
    """
    Return the P1.112 facility as a single-row DataFrame.

    committed=True, seniority="senior", currency="EUR", maturity=2031-01-15 (~5yr).
    risk_type="FR" (fully drawn term loan — on-balance-sheet; no CCF contribution).
    """
    rows = [
        _Facility(
            facility_reference=FACILITY_REF,
            counterparty_reference=COUNTERPARTY_REF,
            currency="EUR",
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            limit=LOAN_AMOUNT,
            committed=True,
            seniority="senior",
            risk_type="FR",
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(FACILITY_SCHEMA))


def create_p1112_loan() -> pl.DataFrame:
    """
    Return the P1.112 loan as a single-row DataFrame.

    drawn_amount=100_000_000 EUR; interest=0 -> EAD=100_000_000 exactly.
    With FX EUR->GBP=1.0: EAD_GBP=100_000_000, RWA_GBP=20_000_000.
    """
    rows = [
        _Loan(
            loan_reference=LOAN_REF,
            counterparty_reference=COUNTERPARTY_REF,
            currency="EUR",
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            drawn_amount=LOAN_AMOUNT,
            interest=0.0,
            seniority="senior",
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_p1112_facility_mapping() -> pl.DataFrame:
    """Return the P1.112 facility-to-loan mapping as a single-row DataFrame."""
    rows = [
        _FacilityMapping(
            parent_facility_reference=FACILITY_REF,
            child_reference=LOAN_REF,
            child_type="loan",
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(FACILITY_MAPPING_SCHEMA))


def create_p1112_fx_rate() -> pl.DataFrame:
    """
    Return the EUR->GBP FX rate pinned to 1.0 for this scenario.

    Rate=1.0 keeps EAD_GBP == EAD_EUR == 100_000_000 and
    RWA_GBP == 20_000_000, making hand-calculation verification trivial.

    Note: test fixtures that use the shared fx_rates.parquet will see EUR->GBP=0.88.
    This scenario-local override (rate=1.0) is used by acceptance tests that
    load the p1_112 fixtures directly to isolate the PSE risk-weight logic from
    FX conversion rounding.
    """
    rows = [
        _FXRate(currency_from="EUR", currency_to="GBP", rate=FX_EUR_GBP),
        _FXRate(currency_from="GBP", currency_to="GBP", rate=1.0),  # identity
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(FX_RATES_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p1112_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.112 parquet files and return a mapping of name -> path.

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts = [
        ("counterparty", create_p1112_counterparty()),
        ("facility", create_p1112_facility()),
        ("loan", create_p1112_loan()),
        ("facility_mapping", create_p1112_facility_mapping()),
        ("fx_rate", create_p1112_fx_rate()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.112 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: German PSE (pse_institution), DE, sovereign_cqs=1,")
    print("          own cqs=null (unrated), committed EUR 100m 5-yr term loan.")
    print("Post-fix: risk_weight=0.20, RWA=20_000_000 (Art. 116(1) Table 2).")
    print("Bug:      risk_weight=1.00, RWA=100_000_000 (wrong country_code guard).")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1112_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
