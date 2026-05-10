"""
Generate P1.154-B31 fixtures: Basel 3.1 Art. 118 IO discriminator vs Art. 117(1)(a) Table 2B MDB.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (engine/classifier.py,
    data/tables/crr_risk_weights.py)

Key responsibilities:
- Produce two counterparty rows:
    CP_IO_IMF_B31   : entity_type="international_org" (named IO: IMF) — Art. 118 → 0% RW
    CP_MDB_NN_B31   : entity_type="mdb" (non-named MDB: Black Sea T&D Bank) — Art. 117(1)(a)
- Produce one rating row: CQS 2 for CP_MDB_NN_B31 only.
    IMF has no rating row (Art. 118 assigns 0% unconditionally, bypassing CQS lookup).
- Produce two facility rows: one per counterparty (USD and EUR, 5-year committed, full_risk).
- Produce empty parquet files for unused streams (loans, collateral, guarantees, provisions,
    model_permissions, fx_rates) so RawDataBundle is well-formed.

Scenario rationale (Basel 3.1 Art. 118 vs Art. 117(1)(a) Table 2B):

  entity_type="international_org" (IMF, Art. 118):
    PRA PS1/26 Art. 118 lists named international organisations — IMF, BIS, ECB, EU, IBRD,
    IFC, IADB, ADB, AfDB, CEB, NIB, CDB, EBRD, EFSI, ESM, EFSF — that receive 0% risk weight
    unconditionally, regardless of CQS or credit assessment.  The "international_org" entity_type
    maps to ExposureClass.INTERNATIONAL_ORGANISATION in the classifier, bypassing the MDB/
    institution branch entirely.

  entity_type="mdb" (Black Sea Trade and Development Bank, Art. 117(1)(a) Table 2B):
    Under Basel 3.1 Art. 117(1)(a), non-named MDBs are assigned a risk weight from the
    dedicated Table 2B based on the MDB's own CQS (not the sovereign-derived table used
    under CRR Art. 117(1)).  With CQS 2, Table 2B → 30%.  This is the discriminating B31
    vs CRR difference: under CRR Art. 117(1) a non-named MDB with CQS 2 would be treated
    as an institution and receive 50% (ECRA, >3m maturity); under B31 Art. 117(1)(a) the
    dedicated MDB Table 2B applies → 30%.

Hand-calculation (Basel 3.1, CalculationConfig.basel_3_1(), reporting_date=2027-06-30,
                  permission_mode=PermissionMode.STANDARDISED):

  FAC_IO_IMF_B31_001 (CP_IO_IMF_B31, entity_type="international_org"):
    Exposure class: INTERNATIONAL_ORGANISATION
    Risk weight (Art. 118): 0% unconditional (no CQS lookup)
    EAD: USD 100,000,000 (FX conversion uses global fx_rates fixture; test may use raw limit)
    RWA: EAD × 0.00 = 0

  FAC_MDB_NN_B31_001 (CP_MDB_NN_B31, entity_type="mdb"):
    Exposure class: MDB
    CQS: 2 (from RATING_MDB_NN_B31_CQS2)
    Risk weight (Art. 117(1)(a) Table 2B, CQS 2): 30%
    EAD: EUR 50,000,000 (FX conversion uses global fx_rates fixture)
    RWA: EAD × 0.30

  CRR comparison (for regression fixture):
    Non-named MDB with CQS 2 under CRR Art. 117(1) → institution treatment → ECRA
    Table 2B (>3m): CQS 2 = 50%.  The Table 2B constant in crr_risk_weights.py confirms
    CQS.CQS2: Decimal("0.30") is the B31 value; CRR institution ECRA CQS 2 (>3m) = 50%.
    This 30% vs 50% split is the load-bearing discriminator for P1.154-B31.

References:
    - PRA PS1/26 Art. 118: named international organisations → 0% SA risk weight
    - PRA PS1/26 Art. 117(1)(a) Table 2B: B31 MDB risk weights by own CQS
      (CQS 2 = 30%, differs from CRR institution ECRA CQS 2 = 50%)
    - src/rwa_calc/data/tables/crr_risk_weights.py: MDB_RISK_WEIGHTS_TABLE_2B (CQS2=0.30)
    - src/rwa_calc/data/schemas.py: VALID_ENTITY_TYPES ("international_org" and "mdb")
    - src/rwa_calc/domain/enums.py: ExposureClass.INTERNATIONAL_ORGANISATION

Usage:
    uv run python tests/fixtures/p1_154_b31/p1_154_b31.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COLLATERAL_SCHEMA,
    CONTINGENTS_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_SCHEMA,
    GUARANTEE_SCHEMA,
    LOAN_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    PROVISION_SCHEMA,
    RATINGS_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

# Counterparty references
CP_IO_IMF_B31: str = "CP_IO_IMF_B31"
CP_MDB_NN_B31: str = "CP_MDB_NN_B31"

# Facility references
FAC_IO_IMF_B31_001: str = "FAC_IO_IMF_B31_001"
FAC_MDB_NN_B31_001: str = "FAC_MDB_NN_B31_001"

# Rating reference (MDB only — IMF has no rating row)
RATING_MDB_NN_B31_CQS2: str = "RATING_MDB_NN_B31_CQS2"

VALUE_DATE: date = date(2026, 1, 1)
MATURITY_DATE: date = date(2031, 1, 1)  # 5-year, well beyond all short-term carve-outs

# Facility limits
IMF_LIMIT: float = 100_000_000.0  # USD 100m
MDB_LIMIT: float = 50_000_000.0  # EUR 50m

# ---------------------------------------------------------------------------
# Expected risk weights (referenced by test-writer assertions)
# ---------------------------------------------------------------------------

#: PRA PS1/26 Art. 118: named international organisation → 0% unconditional
EXPECTED_RW_INTERNATIONAL_ORG: float = 0.00

#: PRA PS1/26 Art. 117(1)(a) Table 2B, CQS 2 = 30%
#: This is the load-bearing B31 discriminator: CRR would give 50% (institution ECRA CQS 2, >3m)
EXPECTED_RW_MDB_CQS2_B31: float = 0.30

# ---------------------------------------------------------------------------
# Minimal frozen dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    P1.154-B31 counterparty row.

    Two variants:
      CP_IO_IMF_B31 : entity_type="international_org" → Art. 118 → 0% RW (unconditional)
      CP_MDB_NN_B31 : entity_type="mdb"               → Art. 117(1)(a) Table 2B CQS 2 → 30%

    is_financial_sector_entity=False: no FI scalar applied.
    is_core_market_participant=False: no FCSM SFT carve-out.
    default_status=False: performing exposure.
    """

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    default_status: bool
    is_financial_sector_entity: bool
    is_core_market_participant: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "default_status": self.default_status,
            "is_financial_sector_entity": self.is_financial_sector_entity,
            "is_core_market_participant": self.is_core_market_participant,
        }


@dataclass(frozen=True)
class _Facility:
    """
    P1.154-B31 facility row.

    committed=True: fully committed — CCF applies to the undrawn portion.
    risk_type="full_risk": standard on-balance-sheet / full-drawn treatment.
    No loans or contingents — facilities are self-sufficient for SA routing.
    """

    facility_reference: str
    counterparty_reference: str
    value_date: date
    maturity_date: date
    currency: str
    limit: float
    committed: bool
    risk_type: str

    def to_dict(self) -> dict:
        return {
            "facility_reference": self.facility_reference,
            "counterparty_reference": self.counterparty_reference,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "currency": self.currency,
            "limit": self.limit,
            "committed": self.committed,
            "risk_type": self.risk_type,
        }


@dataclass(frozen=True)
class _Rating:
    """
    P1.154-B31 rating row.

    Only CP_MDB_NN_B31 receives a rating (CQS 2). CP_IO_IMF_B31 has no rating row
    because Art. 118 bypasses the CQS lookup unconditionally — supplying a rating
    would mask a potential bug where the engine incorrectly uses CQS for IOs.

    rating_type="external": valid value per VALID_RATING_TYPES in schemas.py.
    cqs=2: Aa3 (Moody's) maps to CQS 2 — the load-bearing threshold that gives
           Table 2B 30% under B31 vs 50% under CRR institution ECRA (>3m).
    is_solicited=True: solicited ratings are used preferentially.
    """

    rating_reference: str
    counterparty_reference: str
    rating_type: str
    rating_agency: str
    rating_value: str
    cqs: int
    rating_date: date
    is_solicited: bool

    def to_dict(self) -> dict:
        return {
            "rating_reference": self.rating_reference,
            "counterparty_reference": self.counterparty_reference,
            "rating_type": self.rating_type,
            "rating_agency": self.rating_agency,
            "rating_value": self.rating_value,
            "cqs": self.cqs,
            "rating_date": self.rating_date,
            "is_solicited": self.is_solicited,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1154b31_counterparties() -> pl.DataFrame:
    """
    Return all P1.154-B31 counterparties as a DataFrame.

    Two counterparties exercising the B31 Art. 118 vs Art. 117(1)(a) Table 2B split:
      CP_IO_IMF_B31 : international_org → Art. 118 → 0% (INTERNATIONAL_ORGANISATION class)
      CP_MDB_NN_B31 : mdb               → Art. 117(1)(a) Table 2B CQS 2 → 30%

    Schema uses dtypes_of(COUNTERPARTY_SCHEMA) so all optional columns are present
    as nulls — the loader can apply boolean defaults without error.
    """
    rows = [
        # =====================================================================
        # IMF: named international organisation (Art. 118).
        # entity_type="international_org" already in VALID_ENTITY_TYPES.
        # No rating row — Art. 118 assigns 0% unconditionally.
        # country_code="US" reflects IMF's Washington DC domicile.
        # =====================================================================
        _Counterparty(
            counterparty_reference=CP_IO_IMF_B31,
            counterparty_name="International Monetary Fund",
            entity_type="international_org",
            country_code="US",
            default_status=False,
            is_financial_sector_entity=False,
            is_core_market_participant=False,
        ),
        # =====================================================================
        # Black Sea Trade and Development Bank: non-named MDB (Art. 117(1)(a)).
        # entity_type="mdb" → B31 Table 2B CQS lookup → CQS 2 = 30%.
        # Under CRR Art. 117(1) this would be institution treatment → ECRA 50%.
        # country_code="GR" (Greece — host of BSTDB headquarters).
        # =====================================================================
        _Counterparty(
            counterparty_reference=CP_MDB_NN_B31,
            counterparty_name="Black Sea Trade and Development Bank",
            entity_type="mdb",
            country_code="GR",
            default_status=False,
            is_financial_sector_entity=False,
            is_core_market_participant=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1154b31_facilities() -> pl.DataFrame:
    """
    Return all P1.154-B31 facilities as a DataFrame.

    Two facilities, one per counterparty:
      FAC_IO_IMF_B31_001 : USD 100,000,000, committed, full_risk, 5-year
      FAC_MDB_NN_B31_001 : EUR  50,000,000, committed, full_risk, 5-year

    5-year maturity (2026-01-01 to 2031-01-01) ensures no short-term carve-outs apply.
    Both committed, exercising the standard CCF path.
    """
    rows = [
        _Facility(
            facility_reference=FAC_IO_IMF_B31_001,
            counterparty_reference=CP_IO_IMF_B31,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="USD",
            limit=IMF_LIMIT,
            committed=True,
            risk_type="full_risk",
        ),
        _Facility(
            facility_reference=FAC_MDB_NN_B31_001,
            counterparty_reference=CP_MDB_NN_B31,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="EUR",
            limit=MDB_LIMIT,
            committed=True,
            risk_type="full_risk",
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(FACILITY_SCHEMA))


def create_p1154b31_ratings() -> pl.DataFrame:
    """
    Return all P1.154-B31 rating rows as a DataFrame.

    One row only: CQS 2 for CP_MDB_NN_B31 (Black Sea Trade and Development Bank).
    This is the load-bearing field that routes the non-named MDB to the B31 Table 2B
    30% risk weight (vs CRR institution ECRA 50% for >3m exposures with CQS 2).

    Moody's Aa3 maps to CQS 2 per the standard ECAI CQS mapping table.
    CP_IO_IMF_B31 (IMF) deliberately has no rating row — Art. 118 bypasses the CQS
    lookup entirely, so supplying a rating would be misleading and could mask a bug
    where the engine incorrectly reads CQS for international organisations.
    """
    rows = [
        _Rating(
            rating_reference=RATING_MDB_NN_B31_CQS2,
            counterparty_reference=CP_MDB_NN_B31,
            rating_type="external",
            rating_agency="Moody's",
            rating_value="Aa3",  # Aa3 is representative of CQS 2 (Moody's scale)
            cqs=2,
            rating_date=date(2026, 1, 1),
            is_solicited=True,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


# ---------------------------------------------------------------------------
# Empty-frame factories for unused streams
# (required so RawDataBundle is well-formed at test time)
# ---------------------------------------------------------------------------


def create_p1154b31_loans() -> pl.DataFrame:
    """Return an empty loans DataFrame (no loans in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(LOAN_SCHEMA))


def create_p1154b31_contingents() -> pl.DataFrame:
    """Return an empty contingents DataFrame (no contingents in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(CONTINGENTS_SCHEMA))


def create_p1154b31_collateral() -> pl.DataFrame:
    """Return an empty collateral DataFrame (no collateral in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(COLLATERAL_SCHEMA))


def create_p1154b31_guarantees() -> pl.DataFrame:
    """Return an empty guarantees DataFrame (no guarantees in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(GUARANTEE_SCHEMA))


def create_p1154b31_provisions() -> pl.DataFrame:
    """Return an empty provisions DataFrame (no provisions in this scenario)."""
    return pl.DataFrame(schema=dtypes_of(PROVISION_SCHEMA))


def create_p1154b31_model_permissions() -> pl.DataFrame:
    """Return an empty model_permissions DataFrame (SA-only scenario)."""
    return pl.DataFrame(schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p1154b31_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.154-B31 parquet files and return a mapping of name to path.

    Files written to output_dir (defaults to the package data/ subdirectory):
        counterparties.parquet   — 2 rows (CP_IO_IMF_B31, CP_MDB_NN_B31)
        facilities.parquet       — 2 rows (FAC_IO_IMF_B31_001, FAC_MDB_NN_B31_001)
        ratings.parquet          — 1 row  (RATING_MDB_NN_B31_CQS2 for CP_MDB_NN_B31 only)
        loans.parquet            — 0 rows (empty, well-formed schema)
        collateral.parquet       — 0 rows (empty, well-formed schema)
        guarantees.parquet       — 0 rows (empty, well-formed schema)
        provisions.parquet       — 0 rows (empty, well-formed schema)
        model_permissions.parquet— 0 rows (empty, well-formed schema)

    Args:
        output_dir: Target directory. Defaults to the package data/ subdirectory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent / "data"

    output_dir.mkdir(parents=True, exist_ok=True)

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("counterparties", create_p1154b31_counterparties()),
        ("facilities", create_p1154b31_facilities()),
        ("ratings", create_p1154b31_ratings()),
        ("loans", create_p1154b31_loans()),
        ("collateral", create_p1154b31_collateral()),
        ("guarantees", create_p1154b31_guarantees()),
        ("provisions", create_p1154b31_provisions()),
        ("model_permissions", create_p1154b31_model_permissions()),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.154-B31 fixture generation complete")
    print("-" * 80)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<25} {len(df):>3} row(s)  ->  {path}")
    print("-" * 80)
    print("Scenario: B31 Art. 118 international org (0%) vs Art. 117(1)(a) Table 2B MDB (30%)")
    print()
    print("  CP_IO_IMF_B31 | international_org | no CQS | RW=  0% (Art. 118)")
    print("  CP_MDB_NN_B31 | mdb               | CQS=2  | RW= 30% (Art. 117(1)(a) Table 2B)")
    print()
    print(f"  Expected RW international_org      : {EXPECTED_RW_INTERNATIONAL_ORG:.0%}")
    print(f"  Expected RW mdb CQS 2 (B31 Table 2B): {EXPECTED_RW_MDB_CQS2_B31:.0%}")
    print()
    print("  Note: CRR Art. 117(1) institution ECRA CQS 2 (>3m) would give 50%.")
    print("  The 30% vs 50% split is the load-bearing B31 discriminator for this scenario.")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1154b31_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
