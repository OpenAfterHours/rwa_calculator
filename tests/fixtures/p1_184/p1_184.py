"""
Generate P1.184 fixtures: CRR/B31 MDB non-named vs named institution routing (Art. 117(1)).

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (sa/namespace.py MDB branch)

Key responsibilities:
- Produce four counterparty rows exercising the four MDB sub-paths:
    CP_MDB_RATED_CQS2      — non-named MDB, institution_cqs=2  → Table 2B CQS 2 = 30%
    CP_MDB_UNRATED_SOV1    — non-named MDB, unrated, sovereign_cqs=1 → 50% (unrated flat)
    CP_MDB_UNRATED_NOSOV   — non-named MDB, unrated, no sovereign_cqs → 50% (unrated flat)
    CP_MDB_NAMED           — named MDB (mdb_named), cqs=1 → 0% unconditional
- Produce four senior on-balance-sheet loan rows (one per counterparty).
- Produce FX rate rows for KES->GBP and HNL->GBP (not in global fx_rates fixture).

Regulatory routing summary (CRR Art. 117 / PRA PS1/26 Art. 117):

  entity_type="mdb_named":
    Art. 117(2): named MDB list → 0% risk weight unconditionally.
    MDB_NAMED_ZERO_RW = 0.00 (src/rwa_calc/data/tables/crr_risk_weights.py).

  entity_type="mdb" + rated (institution_cqs present):
    Art. 117(1): treated as institution → Table 2B CQS lookup.
    CQS 2 → 30% (MDB_RISK_WEIGHTS_TABLE_2B[CQS2]).

  entity_type="mdb" + unrated (no institution_cqs):
    Art. 117(1) + Table 2B unrated row → 50% (MDB_UNRATED_RW).
    Note: sovereign_cqs does NOT modify the unrated MDB path — the engine uses the
    Table 2B flat 50% regardless of whether sovereign_cqs is present. The
    CP_MDB_UNRATED_SOV1 row tests that sovereign_cqs=1 does NOT trigger the sovereign-
    derived institution path (Art. 121 Table 5) for MDBs — MDBs are excluded from
    Art. 121 short-term / sovereign-derived treatment by Art. 117(1).

Hand-calculations (both CRR and Basel 3.1, reporting_date = 2026-06-30):

  L_MDB_RATED (CP_MDB_RATED_CQS2, institution_cqs=2):
    Exposure class: MDB
    CQS: 2 → Table 2B → RW = 0.30
    EAD: 1,000,000 KES × KES/GBP = 1,000,000 GBP (FX rate = 1.0 for arithmetic clarity)
    RWA: 1,000,000 × 0.30 = 300,000

  L_MDB_UNRATED_SOV1 (CP_MDB_UNRATED_SOV1, no institution_cqs, sovereign_cqs=1):
    Exposure class: MDB
    CQS: null → unrated path → RW = 0.50 (Table 2B unrated)
    EAD: 1,000,000 HNL × HNL/GBP = 1,000,000 GBP (FX rate = 1.0)
    RWA: 1,000,000 × 0.50 = 500,000

  L_MDB_UNRATED_NOSOV (CP_MDB_UNRATED_NOSOV, no institution_cqs, no sovereign_cqs):
    Exposure class: MDB
    CQS: null → unrated path → RW = 0.50 (Table 2B unrated)
    EAD: 1,000,000 USD × USD/GBP = 790,000 GBP (FX rate = 0.79, from global fx_rates)
    RWA: 790,000 × 0.50 = 395,000

  L_MDB_NAMED (CP_MDB_NAMED, entity_type="mdb_named", institution_cqs=1):
    entity_type="mdb_named" → Art. 117(2) → 0% unconditional
    EAD: 1,000,000 GBP
    RWA: 0

References:
    - CRR Art. 117(1): non-named MDB treated as institution
    - CRR Art. 117(2): named MDB list → 0%
    - PRA PS1/26 Art. 117(1): Table 2B dedicated MDB risk weights (same engine path)
    - src/rwa_calc/data/tables/crr_risk_weights.py: MDB_RISK_WEIGHTS_TABLE_2B, MDB_NAMED_ZERO_RW
    - src/rwa_calc/engine/sa/namespace.py: MDB branch (~line 1070)
    - docs/specifications/crr/sa-risk-weights.md: MDB Exposures section

Usage:
    uv run python tests/fixtures/p1_184/p1_184.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FX_RATES_SCHEMA,
    LOAN_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

# Reporting date — picked to be well within CRR window and straightforward
REPORTING_DATE = date(2026, 6, 30)
VALUE_DATE = date(2026, 1, 15)
# 5-year maturity — keeps exposures firmly above all short-term carve-outs
MATURITY_DATE = date(2031, 6, 30)

DRAWN_AMOUNT: float = 1_000_000.0  # 1 million in local currency

# Counterparty references (as per proposal)
CP_RATED_CQS2 = "CP_MDB_RATED_CQS2"
CP_UNRATED_SOV1 = "CP_MDB_UNRATED_SOV1"
CP_UNRATED_NOSOV = "CP_MDB_UNRATED_NOSOV"
CP_NAMED = "CP_MDB_NAMED"

# Loan references (as per proposal)
LOAN_RATED = "L_MDB_RATED"
LOAN_UNRATED_SOV1 = "L_MDB_UNRATED_SOV1"
LOAN_UNRATED_NOSOV = "L_MDB_UNRATED_NOSOV"
LOAN_NAMED = "L_MDB_NAMED"

# FX rates pinned to 1.0 for KES and HNL to make hand-calculation trivial.
# USD->GBP = 0.79 is the value in the global fx_rates fixture.
FX_KES_GBP: float = 1.0  # 1 KES = 1.0 GBP (arithmetic convenience)
FX_HNL_GBP: float = 1.0  # 1 HNL = 1.0 GBP (arithmetic convenience)
FX_USD_GBP: float = 0.79  # matches global fx_rates fixture

# ---------------------------------------------------------------------------
# Expected risk weights (for test-writer assertions)
# ---------------------------------------------------------------------------

#: CRR Art. 117(1) + Table 2B, CQS 2 = 30%
EXPECTED_RW_RATED_CQS2: float = 0.30

#: CRR Art. 117(1) + Table 2B unrated row = 50% (sovereign_cqs does not override)
EXPECTED_RW_UNRATED_SOV1: float = 0.50

#: CRR Art. 117(1) + Table 2B unrated row = 50% (no sovereign either)
EXPECTED_RW_UNRATED_NOSOV: float = 0.50

#: CRR Art. 117(2): named MDB = 0% unconditional
EXPECTED_RW_NAMED: float = 0.00

# EADs in GBP (after FX conversion) and RWAs
EXPECTED_EAD_RATED = DRAWN_AMOUNT * FX_KES_GBP  # 1_000_000
EXPECTED_RWA_RATED = EXPECTED_EAD_RATED * EXPECTED_RW_RATED_CQS2  # 300_000

EXPECTED_EAD_UNRATED_SOV1 = DRAWN_AMOUNT * FX_HNL_GBP  # 1_000_000
EXPECTED_RWA_UNRATED_SOV1 = EXPECTED_EAD_UNRATED_SOV1 * EXPECTED_RW_UNRATED_SOV1  # 500_000

EXPECTED_EAD_UNRATED_NOSOV = DRAWN_AMOUNT * FX_USD_GBP  # 790_000
EXPECTED_RWA_UNRATED_NOSOV = EXPECTED_EAD_UNRATED_NOSOV * EXPECTED_RW_UNRATED_NOSOV  # 395_000

EXPECTED_EAD_NAMED = DRAWN_AMOUNT  # GBP — no FX conversion
EXPECTED_RWA_NAMED = EXPECTED_EAD_NAMED * EXPECTED_RW_NAMED  # 0


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    MDB counterparty row.

    institution_cqs: None for unrated non-named MDBs. Required for rated MDB.
    sovereign_cqs: Populated for CP_MDB_UNRATED_SOV1 to confirm the engine
        does NOT route unrated MDBs through the sovereign-derived institution
        path (Art. 121 Table 5). MDB Art. 117(1) exclusion takes priority.
    local_currency: Counterparty's domestic currency — used by loan rows.
    """

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    local_currency: str
    institution_cqs: int | None
    sovereign_cqs: int | None
    default_status: bool
    apply_fi_scalar: bool
    is_managed_as_retail: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "local_currency": self.local_currency,
            "institution_cqs": self.institution_cqs,
            "sovereign_cqs": self.sovereign_cqs,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
            "is_managed_as_retail": self.is_managed_as_retail,
        }


@dataclass(frozen=True)
class _Loan:
    """
    Senior on-balance-sheet drawdown.

    drawn_amount = 1,000,000 in local currency.
    interest = 0 — EAD = drawn_amount exactly before FX.
    maturity_date = 2031-06-30 (~5yr from reporting_date 2026-06-30).
    This guards all short-term carve-outs (Art. 120(2), 121(3)) which
    Art. 117(1) already excludes for MDBs, but the 5yr maturity removes
    any ambiguity.
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
class _FXRate:
    """Scenario-local FX rate for currencies absent from the global fx_rates fixture."""

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


def create_p1184_counterparties() -> pl.DataFrame:
    """
    Return all P1.184 counterparties as a DataFrame.

    Four MDB counterparties exercising the Art. 117 sub-paths:
      CP_MDB_RATED_CQS2   : non-named MDB, institution_cqs=2   → Table 2B CQS 2 = 30%
      CP_MDB_UNRATED_SOV1 : non-named MDB, unrated, sov_cqs=1  → Table 2B unrated = 50%
      CP_MDB_UNRATED_NOSOV: non-named MDB, unrated, no sov_cqs → Table 2B unrated = 50%
      CP_MDB_NAMED        : named MDB (mdb_named), cqs=1        → 0% unconditional
    """
    rows = [
        # =====================================================================
        # Rated non-named MDB — Table 2B CQS 2 = 30%
        # institution_cqs=2 present → rated path → RW = 30%
        # Kenya-based development bank with an ECAI rating at CQS 2.
        # =====================================================================
        _Counterparty(
            counterparty_reference=CP_RATED_CQS2,
            counterparty_name="East Africa Development Bank (Rated CQS2) - P1.184",
            entity_type="mdb",
            country_code="KE",
            local_currency="KES",
            institution_cqs=2,
            sovereign_cqs=2,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
        ),
        # =====================================================================
        # Unrated non-named MDB, sovereign_cqs=1 — Table 2B unrated = 50%
        # Tests that sovereign_cqs does NOT divert the engine to Art. 121 Table 5
        # (sovereign-derived 20%), which would be incorrect for MDBs.
        # Art. 117(1) routes unrated non-named MDBs to Table 2B flat 50%.
        # =====================================================================
        _Counterparty(
            counterparty_reference=CP_UNRATED_SOV1,
            counterparty_name="Central America Development Fund (Unrated, SovCQS1) - P1.184",
            entity_type="mdb",
            country_code="HN",
            local_currency="HNL",
            institution_cqs=None,
            sovereign_cqs=1,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
        ),
        # =====================================================================
        # Unrated non-named MDB, no sovereign_cqs — Table 2B unrated = 50%
        # Baseline unrated case: both institution_cqs and sovereign_cqs are null.
        # country_code="XX" represents a non-standard jurisdiction.
        # currency=USD — FX conversion uses global fx_rates.parquet USD->GBP=0.79.
        # =====================================================================
        _Counterparty(
            counterparty_reference=CP_UNRATED_NOSOV,
            counterparty_name="Generic Regional Development Bank (Unrated, No Sov) - P1.184",
            entity_type="mdb",
            country_code="XX",
            local_currency="USD",
            institution_cqs=None,
            sovereign_cqs=None,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
        ),
        # =====================================================================
        # Named MDB — Art. 117(2) → 0% unconditional
        # entity_type="mdb_named" routes directly to MDB_NAMED_ZERO_RW=0%.
        # institution_cqs=1 is supplied to confirm that even a rated named MDB
        # bypasses the Table 2B rated path and receives 0%.
        # =====================================================================
        _Counterparty(
            counterparty_reference=CP_NAMED,
            counterparty_name="World Bank (Named MDB) - P1.184",
            entity_type="mdb_named",
            country_code="GB",
            local_currency="GBP",
            institution_cqs=1,
            sovereign_cqs=1,
            default_status=False,
            apply_fi_scalar=False,
            is_managed_as_retail=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1184_loans() -> pl.DataFrame:
    """
    Return all P1.184 loans as a DataFrame.

    One senior drawdown per counterparty. drawn_amount=1,000,000 in local currency.
    interest=0 → EAD = drawn_amount (before FX conversion to GBP).
    maturity_date=2031-06-30 (~5yr) guards all short-term carve-outs.
    """
    rows = [
        # =====================================================================
        # L_MDB_RATED: KES 1m → GBP 1m (FX=1.0) → RW=30% → RWA=300,000
        # =====================================================================
        _Loan(
            loan_reference=LOAN_RATED,
            counterparty_reference=CP_RATED_CQS2,
            currency="KES",
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            drawn_amount=DRAWN_AMOUNT,
            interest=0.0,
            seniority="senior",
        ),
        # =====================================================================
        # L_MDB_UNRATED_SOV1: HNL 1m → GBP 1m (FX=1.0) → RW=50% → RWA=500,000
        # =====================================================================
        _Loan(
            loan_reference=LOAN_UNRATED_SOV1,
            counterparty_reference=CP_UNRATED_SOV1,
            currency="HNL",
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            drawn_amount=DRAWN_AMOUNT,
            interest=0.0,
            seniority="senior",
        ),
        # =====================================================================
        # L_MDB_UNRATED_NOSOV: USD 1m → GBP 790k (FX=0.79) → RW=50% → RWA=395,000
        # =====================================================================
        _Loan(
            loan_reference=LOAN_UNRATED_NOSOV,
            counterparty_reference=CP_UNRATED_NOSOV,
            currency="USD",
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            drawn_amount=DRAWN_AMOUNT,
            interest=0.0,
            seniority="senior",
        ),
        # =====================================================================
        # L_MDB_NAMED: GBP 1m → RW=0% → RWA=0
        # =====================================================================
        _Loan(
            loan_reference=LOAN_NAMED,
            counterparty_reference=CP_NAMED,
            currency="GBP",
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            drawn_amount=DRAWN_AMOUNT,
            interest=0.0,
            seniority="senior",
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_p1184_fx_rates() -> pl.DataFrame:
    """
    Return scenario-local FX rates for currencies absent from the global fixture.

    KES->GBP and HNL->GBP are not in the global fx_rates.parquet. Pinning both
    to 1.0 keeps EAD in GBP == drawn_amount and makes hand-calculation trivial.

    USD->GBP is also included at 0.79 for completeness (matches global fixture).
    GBP->GBP identity row ensures the named-MDB loan row needs no FX lookup.

    Test fixtures that load the p1_184 module directly should use these rates
    in place of (or in addition to) the global fx_rates.parquet.
    """
    rows = [
        _FXRate("KES", "GBP", FX_KES_GBP),
        _FXRate("HNL", "GBP", FX_HNL_GBP),
        _FXRate("USD", "GBP", FX_USD_GBP),
        _FXRate("GBP", "GBP", 1.0),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(FX_RATES_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p1184_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.184 parquet files and return a mapping of name to path.

    Files written:
        counterparty.parquet — 4 rows (rated, unrated-sov1, unrated-nosov, named)
        loan.parquet         — 4 rows (one per counterparty)
        fx_rates.parquet     — 4 rows (KES/HNL/USD/GBP to GBP)

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts = [
        ("counterparty", create_p1184_counterparties()),
        ("loan", create_p1184_loans()),
        ("fx_rates", create_p1184_fx_rates()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.184 fixture generation complete")
    print("-" * 75)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<25} {len(df):>3} row(s)  ->  {path}")
    print("-" * 75)
    print("Scenario: CRR/B31 MDB exposure-class routing (Art. 117)")
    print()
    print("  CP_MDB_RATED_CQS2    | mdb        | cqs=2   | RW=30% | RWA=300,000")
    print("  CP_MDB_UNRATED_SOV1  | mdb        | unrated | RW=50% | RWA=500,000 (sov_cqs=1 ignored)")
    print("  CP_MDB_UNRATED_NOSOV | mdb        | unrated | RW=50% | RWA=395,000 (USD, FX=0.79)")
    print("  CP_MDB_NAMED         | mdb_named  | cqs=1   | RW= 0% | RWA=0")
    print()
    print(f"  Expected RW rated CQS2  : {EXPECTED_RW_RATED_CQS2:.0%}")
    print(f"  Expected RW unrated sov1: {EXPECTED_RW_UNRATED_SOV1:.0%}")
    print(f"  Expected RW unrated nosov: {EXPECTED_RW_UNRATED_NOSOV:.0%}")
    print(f"  Expected RW named       : {EXPECTED_RW_NAMED:.0%}")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1184_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
