"""
Generate P1.154 fixtures: CRR Art. 118 international organisation vs Art. 117 non-named MDB.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (domain/enums.py, engine/classifier.py)

Key responsibilities:
- Produce two counterparty rows: one named international organisation (IMF, Art. 118)
  and one non-named MDB (Black Sea Trade and Development Bank, Art. 117).
- Produce two facility rows: one per counterparty (USD and EUR, 5-year committed, full_risk).
- Produce one rating row: CQS 3 for the non-named MDB counterparty only.
  The IMF counterparty has no rating row — Art. 118 assigns 0% unconditionally,
  bypassing the CQS lookup.

Scenario rationale (CRR Art. 118 vs Art. 117):

  entity_type="international_org" (IMF, Art. 118):
    CRR Art. 118 lists a closed five-entry list of named international organisations —
    the EU, IMF, BIS, EFSF and ESM — that receive a 0% risk weight
    unconditionally, regardless of CQS or credit assessment. Under the existing engine the
    "international_org" entity_type is incorrectly routed to the MDB branch (Art. 117),
    which would impose a non-zero risk weight. The new ExposureClass.INTERNATIONAL_ORGANISATION
    enum value corrects this by routing to the Art. 118 branch.

  entity_type="mdb" (Black Sea Trade and Development Bank, Art. 117):
    Non-named MDB (not on the Art. 117(2) list). Under Art. 117(1) the exposure is treated
    as an institution and the risk weight is looked up from Table 2B using the CQS. With a
    CQS 3 rating row the engine resolves cp_cqs=3 → MDB_RISK_WEIGHTS_TABLE_2B[CQS3] = 0.50
    (50%). This counterparty acts as a control to confirm the MDB branch is unaffected by
    the new INTERNATIONAL_ORGANISATION routing.

Hand-calculation (CRR, CalculationConfig.crr(), reporting_date = 2026-06-30):

  FAC_IO_IMF_001 (CP_IO_IMF, entity_type="international_org"):
    Exposure class (post-fix): INTERNATIONAL_ORGANISATION
    Risk weight (Art. 118): 0% unconditional (no CQS lookup)
    EAD: USD 100,000,000 × USD/GBP (from global fx_rates, ~0.79) ≈ 79,000,000 GBP
    RWA: 79,000,000 × 0.00 = 0

  FAC_MDB_NN_001 (CP_MDB_NONNAMED, entity_type="mdb"):
    Exposure class: MDB
    CQS: 3 (from rating row RATING_MDB_NN_CQS3)
    Risk weight (Art. 117(1) + Table 2B, CQS 3): 50%
    EAD: EUR 50,000,000 × EUR/GBP (from global fx_rates, ~1.17) ≈ 58,500,000 GBP
    RWA: 58,500,000 × 0.50 ≈ 29,250,000

  Note on FX: the fixture does not specify FX rates. Test assertions should use the
  global fx_rates fixture for conversion. For classification-level assertions (exposure
  class and risk weight) FX is irrelevant — use raw limit values.

References:
    - CRR Art. 118: named international organisations → 0% SA risk weight
    - CRR Art. 117(1): non-named MDB treated as institution → Table 2B CQS lookup
    - CRR Art. 112(1)(e): exposure class for international organisations
    - src/rwa_calc/domain/enums.py: ExposureClass (new INTERNATIONAL_ORGANISATION member)
    - src/rwa_calc/engine/classifier.py: ENTITY_TYPE_TO_SA_CLASS mapping (~line 80)
    - src/rwa_calc/data/tables/crr_risk_weights.py: MDB_RISK_WEIGHTS_TABLE_2B (CQS 3 = 0.50)
    - data/schemas.py: VALID_ENTITY_TYPES — "international_org" already present at line 538

Usage:
    uv run python tests/fixtures/p1_154/p1_154.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, FACILITY_SCHEMA, RATINGS_SCHEMA

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

# Counterparty references
CP_IO_IMF: str = "CP_IO_IMF"
CP_MDB_NONNAMED: str = "CP_MDB_NONNAMED"

# Facility references
FAC_IO_IMF_001: str = "FAC_IO_IMF_001"
FAC_MDB_NN_001: str = "FAC_MDB_NN_001"

# Rating reference
RATING_MDB_NN_CQS3: str = "RATING_MDB_NN_CQS3"

VALUE_DATE: date = date(2026, 1, 1)
MATURITY_DATE: date = date(2031, 1, 1)  # 5-year maturity, well beyond all short-term carve-outs

# Facility limits
IMF_LIMIT: float = 100_000_000.0  # USD 100m
MDB_LIMIT: float = 50_000_000.0  # EUR 50m

# ---------------------------------------------------------------------------
# Expected risk weights (referenced by test-writer assertions)
# ---------------------------------------------------------------------------

#: CRR Art. 118: named international organisation → 0% unconditional
EXPECTED_RW_INTERNATIONAL_ORG: float = 0.00

#: CRR Art. 117(1) + Table 2B, CQS 3 = 50%
EXPECTED_RW_MDB_CQS3: float = 0.50

# ---------------------------------------------------------------------------
# Minimal frozen dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    P1.154 counterparty row.

    Two variants:
      CP_IO_IMF       : entity_type="international_org" → Art. 118 → 0% RW (post-fix)
      CP_MDB_NONNAMED : entity_type="mdb"               → Art. 117(1) Table 2B CQS 3 → 50%

    is_financial_sector_entity=False: no FI scalar.
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
    P1.154 facility row.

    committed=True: fully committed facility — CCF applies to the undrawn portion.
    risk_type="full_risk": standard on-balance-sheet / fully drawn treatment.
    seniority="senior": senior claim in all scenarios.
    No loans or contingents are created — facilities are self-sufficient for SA routing.
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
    P1.154 rating row.

    Only CP_MDB_NONNAMED receives a rating (CQS 3). CP_IO_IMF has no rating row
    because Art. 118 bypasses the CQS lookup unconditionally.

    rating_type="external_cqs": long-term ECAI CQS rating.
    is_solicited=True: conservative default (solicited ratings are used preferentially).
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


def create_p1154_counterparties() -> pl.DataFrame:
    """
    Return all P1.154 counterparties as a DataFrame.

    Two counterparties exercising the Art. 118 vs Art. 117 routing split:
      CP_IO_IMF       : international_org → Art. 118 → INTERNATIONAL_ORGANISATION class
      CP_MDB_NONNAMED : mdb               → Art. 117(1) Table 2B CQS 3 → 50%

    The schema uses dtypes_of(COUNTERPARTY_SCHEMA) so all optional columns are
    present as nulls — the loader can apply boolean defaults without error.
    """
    rows = [
        # =====================================================================
        # IMF: named international organisation (Art. 118)
        # entity_type="international_org" already in VALID_ENTITY_TYPES.
        # No CQS is provided — Art. 118 assigns 0% unconditionally.
        # country_code="US" reflects IMF's Washington DC domicile.
        # =====================================================================
        _Counterparty(
            counterparty_reference=CP_IO_IMF,
            counterparty_name="International Monetary Fund",
            entity_type="international_org",
            country_code="US",
            default_status=False,
            is_financial_sector_entity=False,
            is_core_market_participant=False,
        ),
        # =====================================================================
        # Black Sea Trade and Development Bank: non-named MDB (Art. 117)
        # entity_type="mdb" → institution path → Table 2B CQS lookup.
        # CQS 3 is supplied via the ratings table → RW = 50%.
        # country_code="GR" (Greece — host of BSTDB headquarters).
        # =====================================================================
        _Counterparty(
            counterparty_reference=CP_MDB_NONNAMED,
            counterparty_name="Black Sea Trade and Development Bank",
            entity_type="mdb",
            country_code="GR",
            default_status=False,
            is_financial_sector_entity=False,
            is_core_market_participant=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1154_facilities() -> pl.DataFrame:
    """
    Return all P1.154 facilities as a DataFrame.

    Two facilities, one per counterparty:
      FAC_IO_IMF_001  : USD 100,000,000, committed, full_risk, 5-year
      FAC_MDB_NN_001  : EUR  50,000,000, committed, full_risk, 5-year

    5-year maturity (2026-01-01 to 2031-01-01) ensures no short-term carve-outs
    apply. Both facilities are committed, which exercises the standard CCF path.
    """
    rows = [
        _Facility(
            facility_reference=FAC_IO_IMF_001,
            counterparty_reference=CP_IO_IMF,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="USD",
            limit=IMF_LIMIT,
            committed=True,
            risk_type="full_risk",
        ),
        _Facility(
            facility_reference=FAC_MDB_NN_001,
            counterparty_reference=CP_MDB_NONNAMED,
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            currency="EUR",
            limit=MDB_LIMIT,
            committed=True,
            risk_type="full_risk",
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(FACILITY_SCHEMA))


def create_p1154_ratings() -> pl.DataFrame:
    """
    Return all P1.154 rating rows as a DataFrame.

    One row only: CQS 3 for CP_MDB_NONNAMED (Black Sea Trade and Development Bank).
    This is the load-bearing field that routes the non-named MDB to the 50% risk weight
    via Art. 117(1) Table 2B.

    CP_IO_IMF (IMF) deliberately has no rating row: Art. 118 bypasses the CQS lookup
    entirely, so supplying a rating would be misleading and could mask a bug where the
    engine incorrectly uses the CQS for international organisations.
    """
    rows = [
        _Rating(
            rating_reference=RATING_MDB_NN_CQS3,
            counterparty_reference=CP_MDB_NONNAMED,
            rating_type="external",
            rating_agency="Moody's",
            rating_value="Baa2",  # Baa2 is representative of CQS 3 (Moody's scale)
            cqs=3,
            rating_date=date(2026, 1, 1),
            is_solicited=True,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------


def save_p1154_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.154 parquet files and return a mapping of name to path.

    Files written:
        counterparties.parquet — 2 rows (CP_IO_IMF, CP_MDB_NONNAMED)
        facilities.parquet     — 2 rows (FAC_IO_IMF_001, FAC_MDB_NN_001)
        ratings.parquet        — 1 row  (RATING_MDB_NN_CQS3 for CP_MDB_NONNAMED only)

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    output_dir.mkdir(parents=True, exist_ok=True)

    saved: dict[str, Path] = {}

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("counterparties", create_p1154_counterparties()),
        ("facilities", create_p1154_facilities()),
        ("ratings", create_p1154_ratings()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.154 fixture generation complete")
    print("-" * 75)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<25} {len(df):>3} row(s)  ->  {path}")
    print("-" * 75)
    print("Scenario: CRR Art. 118 international org vs Art. 117 non-named MDB routing")
    print()
    print("  CP_IO_IMF       | international_org | no CQS | RW= 0% (Art. 118, post-fix)")
    print("  CP_MDB_NONNAMED | mdb               | CQS=3  | RW=50% (Art. 117(1) Table 2B)")
    print()
    print(f"  Expected RW international_org : {EXPECTED_RW_INTERNATIONAL_ORG:.0%}")
    print(f"  Expected RW mdb (CQS 3)       : {EXPECTED_RW_MDB_CQS3:.0%}")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1154_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
