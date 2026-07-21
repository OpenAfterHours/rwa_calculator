"""
Generate the multi-entity solo-vs-consolidated fixture dataset.

Small, deterministic, SA-only (no IRB fields) dataset used to drive the
solo/sub-consolidated/consolidated scope-resolver integration tests (see
``docs/plans/multi-entity-reporting.md``). Writes a full loadable input
directory (``exposures/``, ``counterparty/``, ``mapping/``, ``guarantee/``,
``config/`` — mirroring ``src/rwa_calc/config/data_sources.py``) rather than a
flat scenario bundle, so it can be pointed at directly as ``data_path`` once
the ``resolve_scope`` stage (W2-D) lands.

Reporting-entity hierarchy (config/reporting_entities.parquet):
    GRP (apex, no parent)
    +-- BANK_A (parent GRP)
    +-- BANK_B (parent GRP)

Book -> entity mapping (mapping/book_entity_mapping.parquet):
    BOOK_A1 -> BANK_A
    BOOK_A2 -> BANK_A
    BOOK_B1 -> BANK_B

Counterparties (counterparty/counterparties.parquet) — 6 rows:
    CORP_EXT_A1, CORP_EXT_A2, CORP_EXT_B1  -- plain external corporates, unrated
    BANK_A, BANK_B                          -- the two banks, also modelled as
                                                institution counterparties so they
                                                can sit on the *other* bank's books
                                                as an intragroup borrower/guarantor
    EXT_BANK_1                              -- plain external institution (contrast
                                                guarantor)

Loans / facilities (SA-only, no IRB fields; each facility.limit == its loan's
drawn_amount, so there is no undrawn portion and EAD = drawn_amount exactly)
— 5 rows each, GBP 1,000,000 round balances:
    LOAN_A1_EXT          book BOOK_A1  cp CORP_EXT_A1  external
    LOAN_A2_EXT          book BOOK_A2  cp CORP_EXT_A2  external
    LOAN_B1_EXT          book BOOK_B1  cp CORP_EXT_B1  external
    LOAN_A1_IG_TO_BANK_B book BOOK_A1  cp BANK_B        intragroup_entity_reference=BANK_B
    LOAN_B1_IG_TO_BANK_A book BOOK_B1  cp BANK_A        intragroup_entity_reference=BANK_A

Guarantees (guarantee/guarantee.parquet) — 2 rows:
    GUAR_IG_BANK_B_TO_A1EXT  guarantor=BANK_B (guarantor_entity_reference=BANK_B),
                             covers 50% of LOAN_A1_EXT (an external BANK_A loan)
    GUAR_EXT_PLAIN           guarantor=EXT_BANK_1 (guarantor_entity_reference=None),
                             covers 50% of LOAN_B1_EXT — plain contrast guarantee

Mandatory files the loader requires (RequirementLevel.MANDATORY in
data_sources.py) are all present: facilities, loans, facility_mapping,
counterparties, lending_mapping (the latter written with 0 rows — this
dataset is corporate-only, no retail connected-party aggregation needed).

Expected row counts per scope, once the resolve_scope stage (W2-D) is wired
in (CRR Art. 6/11/18 individual/sub-consolidated/consolidated levels; hand
derivable from the membership + booking-filter + intragroup rules in
docs/plans/multi-entity-reporting.md "Scope resolver stage"):

    GRP consolidated  (membership = {GRP, BANK_A, BANK_B}, all books in scope):
        loans=3, facilities=3 -- both intragroup loans/facilities eliminated
          (their intragroup_entity_reference is a member of the consolidated
          subtree); the 3 surviving loans are the externals, one per book.
        guarantees=1 -- GUAR_IG_BANK_B_TO_A1EXT dropped (guarantor_entity_reference
          BANK_B is in-scope); GUAR_EXT_PLAIN kept (guarantor is external).

    BANK_A individual (membership = {BANK_A} alone; books BOOK_A1, BOOK_A2):
        loans=3, facilities=3 -- LOAN_A1_EXT, LOAN_A2_EXT, and
          LOAN_A1_IG_TO_BANK_B (intragroup rows are KEPT on individual runs,
          Art. 113(6) treatment deferred). LOAN_B1_* excluded (wrong book).
        guarantees kept (raw frame)=2 (individual runs never drop by guarantor)
          but only GUAR_IG_BANK_B_TO_A1EXT has a beneficiary (LOAN_A1_EXT)
          inside BANK_A's booking-filtered scope; GUAR_EXT_PLAIN's beneficiary
          (LOAN_B1_EXT) is out of scope and so is inert for this run.

    BANK_B individual (membership = {BANK_B} alone; book BOOK_B1):
        loans=2, facilities=2 -- LOAN_B1_EXT and LOAN_B1_IG_TO_BANK_A.
        guarantees kept (raw frame)=2; only GUAR_EXT_PLAIN (beneficiary
        LOAN_B1_EXT) is in-scope-relevant; GUAR_IG_BANK_B_TO_A1EXT's
        beneficiary (LOAN_A1_EXT) is out of scope for this run.

    Note: BANK_A individual (3 loans) + BANK_B individual (2 loans) = 5 raw
    loans, deliberately NOT equal to GRP consolidated (3 loans) -- the two
    intragroup loans are each counted once solo but eliminated at group
    level. This asymmetry is the point of the fixture (solo != consolidated).

CUG variant (tests/fixtures/multi_entity_cug/, core_uk_group=True on GRP,
BANK_A, BANK_B) -- CRR Art. 113(6) 0% risk weight for core-UK-group intragroup
exposures on an INDIVIDUAL-basis run. The registry differs (all three entities
core_uk_group=True) AND the CUG variant adds ONE intragroup facility with
undrawn headroom on BANK_A's book -- FAC_A1_IG_UNDRAWN (limit 1.5m, intragroup
to BANK_B) drawn 1m via LOAN_A1_IG_UNDRAWN -> a 0.5m undrawn commitment (FR
risk_type, 100% CCF -> 0.5m EAD). The base multi_entity/ dataset is unchanged
(5 facilities / 5 loans). Because both the reporting entity and each tagged
intragroup entity are in the core UK group, each solo run's intragroup exposures
(drawn loans AND the undrawn commitment) drop from 100% RW to 0%:

    BANK_A individual : LOAN_A1_EXT (1m) + LOAN_A2_EXT (1m)          -> 2,000,000 RWA
                        + LOAN_A1_IG_TO_BANK_B (0%)
                        + LOAN_A1_IG_UNDRAWN (1m drawn, 0%)
                        + FAC_A1_IG_UNDRAWN undrawn (0.5m EAD, 0%)
    BANK_B individual : LOAN_B1_EXT (1m)                             -> 1,000,000 RWA
                        + LOAN_B1_IG_TO_BANK_A (0%)
                        (FAC_A1_IG_UNDRAWN is on BANK_A's book, out of scope)
    GRP consolidated  : 3 externals (all intragroup eliminated       -> 3,000,000 RWA
                        BEFORE weighting, so the 0% never bites)      (unchanged)
    unscoped          : base 5m + LOAN_A1_IG_UNDRAWN (1m @ 100%)      -> 6,500,000 RWA
                        + FAC_A1_IG_UNDRAWN undrawn (0.5m @ 100%)
                        -- no scope -> no eligibility

The guaranteed external loan LOAN_A1_EXT (guarantor BANK_B, a CUG member) is
untouched: the 0% is keyed on a row's OWN intragroup tag, not on who guarantees
it (Art. 113(6) covers direct exposures TO members, not protection FROM them),
so both its guarantee-split legs stay at 100% and it totals 1,000,000 RWA. The
base dataset's unchanged BANK_A=3m / BANK_B=2m totals prove the permission gate
(core_uk_group=False -> no eligibility -> normal risk weights).

References:
    - CRR Part One Title II (Art. 6, 11-18): individual / sub-consolidated /
      consolidated levels.
    - docs/plans/multi-entity-reporting.md: data model, scope resolver spec.

Usage:
    uv run python tests/fixtures/multi_entity/multi_entity.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    BOOK_ENTITY_MAPPING_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    GUARANTEE_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    LOAN_SCHEMA,
    REPORTING_ENTITY_SCHEMA,
)

VALUE_DATE = date(2026, 1, 1)
MATURITY_DATE = date(2030, 12, 31)
DRAWN_AMOUNT: float = 1_000_000.0
# CUG-variant-only intragroup facility limit (> DRAWN_AMOUNT) so its undrawn
# headroom (0.5m at 100% CCF for risk_type FR) exercises the Art. 113(6) 0% on a
# facility_undrawn row. See the module docstring's CUG hand-calc.
UNDRAWN_LIMIT: float = 1_500_000.0

# Column names for the multi-entity fields declared on FACILITY_SCHEMA /
# LOAN_SCHEMA / GUARANTEE_SCHEMA (data/schemas.py) -- used as literal dict
# keys in the row dataclasses' to_dict() below.
_INTRAGROUP_COL = "intragroup_entity_reference"
_GUARANTOR_ENTITY_COL = "guarantor_entity_reference"


def main() -> None:
    """Entry point for multi-entity fixture generation (base + CUG variant)."""
    base_dir = Path(__file__).parent
    saved = save_multi_entity_fixtures(base_dir)
    print_summary(saved)
    # CRR Art. 113(6) core-UK-group variant — identical exposures, registry with
    # core_uk_group=True on all three entities (see the module docstring).
    cug_dir = base_dir.parent / "multi_entity_cug"
    saved_cug = save_multi_entity_fixtures(cug_dir, core_uk_group=True)
    print_summary(saved_cug)


# =============================================================================
# Row dataclasses
# =============================================================================


@dataclass(frozen=True)
class _Counterparty:
    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    annual_revenue: float | None
    total_assets: float | None
    default_status: bool
    is_financial_sector_entity: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "annual_revenue": self.annual_revenue,
            "total_assets": self.total_assets,
            "default_status": self.default_status,
            "is_financial_sector_entity": self.is_financial_sector_entity,
            "apply_fi_scalar": False,
            "is_managed_as_retail": False,
        }


@dataclass(frozen=True)
class _Facility:
    facility_reference: str
    book_code: str
    counterparty_reference: str
    limit: float
    intragroup_entity_reference: str | None = None

    def to_dict(self) -> dict:
        return {
            "facility_reference": self.facility_reference,
            "product_type": "term_facility",
            "book_code": self.book_code,
            "counterparty_reference": self.counterparty_reference,
            "value_date": VALUE_DATE,
            "maturity_date": MATURITY_DATE,
            "currency": "GBP",
            "limit": self.limit,
            "committed": True,
            "lgd": 0.0,
            "beel": 0.0,
            "is_revolving": False,
            "seniority": "senior",
            "risk_type": "FR",
            _INTRAGROUP_COL: self.intragroup_entity_reference,
        }


@dataclass(frozen=True)
class _Loan:
    loan_reference: str
    book_code: str
    counterparty_reference: str
    drawn_amount: float
    intragroup_entity_reference: str | None = None

    def to_dict(self) -> dict:
        return {
            "loan_reference": self.loan_reference,
            "product_type": "term_loan",
            "book_code": self.book_code,
            "counterparty_reference": self.counterparty_reference,
            "value_date": VALUE_DATE,
            "maturity_date": MATURITY_DATE,
            "currency": "GBP",
            "drawn_amount": self.drawn_amount,
            "interest": 0.0,
            "lgd": 0.0,
            "beel": 0.0,
            "seniority": "senior",
            _INTRAGROUP_COL: self.intragroup_entity_reference,
        }


@dataclass(frozen=True)
class _FacilityMapping:
    parent_facility_reference: str
    child_reference: str
    child_type: str = "loan"

    def to_dict(self) -> dict:
        return {
            "parent_facility_reference": self.parent_facility_reference,
            "child_reference": self.child_reference,
            "child_type": self.child_type,
        }


@dataclass(frozen=True)
class _Guarantee:
    guarantee_reference: str
    guarantor: str
    beneficiary_reference: str
    amount_covered: float
    percentage_covered: float
    guarantor_entity_reference: str | None = None

    def to_dict(self) -> dict:
        return {
            "guarantee_reference": self.guarantee_reference,
            "guarantee_type": "bank_guarantee",
            "guarantor": self.guarantor,
            "currency": "GBP",
            "maturity_date": MATURITY_DATE,
            "amount_covered": self.amount_covered,
            "percentage_covered": self.percentage_covered,
            "beneficiary_type": "loan",
            "beneficiary_reference": self.beneficiary_reference,
            _GUARANTOR_ENTITY_COL: self.guarantor_entity_reference,
        }


@dataclass(frozen=True)
class _ReportingEntity:
    entity_reference: str
    entity_name: str
    lei: str
    parent_entity_reference: str | None
    institution_type: str | None = None
    core_uk_group: bool = False

    def to_dict(self) -> dict:
        return {
            "entity_reference": self.entity_reference,
            "entity_name": self.entity_name,
            "lei": self.lei,
            "parent_entity_reference": self.parent_entity_reference,
            "institution_type": self.institution_type,
            "core_uk_group": self.core_uk_group,
        }


@dataclass(frozen=True)
class _BookEntityMapping:
    book_code: str
    reporting_entity_reference: str

    def to_dict(self) -> dict:
        return {
            "book_code": self.book_code,
            "reporting_entity_reference": self.reporting_entity_reference,
        }


# =============================================================================
# Table builders
# =============================================================================


def create_counterparties() -> pl.DataFrame:
    """Build the 6-row counterparty table (3 external corporates + 2 banks + 1
    external institution)."""
    rows = [
        _Counterparty(
            "CORP_EXT_A1",
            "External Corporate A1",
            "corporate",
            "GB",
            500_000_000.0,
            1_000_000_000.0,
            False,
            False,
        ),
        _Counterparty(
            "CORP_EXT_A2",
            "External Corporate A2",
            "corporate",
            "GB",
            500_000_000.0,
            1_000_000_000.0,
            False,
            False,
        ),
        _Counterparty(
            "CORP_EXT_B1",
            "External Corporate B1",
            "corporate",
            "GB",
            500_000_000.0,
            1_000_000_000.0,
            False,
            False,
        ),
        _Counterparty(
            "BANK_A",
            "Bank A Ltd",
            "institution",
            "GB",
            None,
            None,
            False,
            True,
        ),
        _Counterparty(
            "BANK_B",
            "Bank B Ltd",
            "institution",
            "GB",
            None,
            None,
            False,
            True,
        ),
        _Counterparty(
            "EXT_BANK_1",
            "External Bank 1",
            "institution",
            "GB",
            None,
            None,
            False,
            True,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_facilities(*, core_uk_group: bool = False) -> pl.DataFrame:
    """Build the facility table (5 rows base; 6 in the CUG variant).

    Base: one facility per loan with limit == drawn_amount, so there is no
    undrawn portion. The CUG variant appends ``FAC_A1_IG_UNDRAWN`` (limit 1.5m,
    intragroup to BANK_B) whose 0.5m undrawn headroom exercises the Art. 113(6)
    0% on a synthetic facility_undrawn row on the BANK_A solo run.
    """
    rows = [
        _Facility("FAC_A1_EXT", "BOOK_A1", "CORP_EXT_A1", DRAWN_AMOUNT),
        _Facility("FAC_A2_EXT", "BOOK_A2", "CORP_EXT_A2", DRAWN_AMOUNT),
        _Facility("FAC_B1_EXT", "BOOK_B1", "CORP_EXT_B1", DRAWN_AMOUNT),
        _Facility(
            "FAC_A1_IG", "BOOK_A1", "BANK_B", DRAWN_AMOUNT, intragroup_entity_reference="BANK_B"
        ),
        _Facility(
            "FAC_B1_IG", "BOOK_B1", "BANK_A", DRAWN_AMOUNT, intragroup_entity_reference="BANK_A"
        ),
    ]
    if core_uk_group:
        rows.append(
            _Facility(
                "FAC_A1_IG_UNDRAWN",
                "BOOK_A1",
                "BANK_B",
                UNDRAWN_LIMIT,
                intragroup_entity_reference="BANK_B",
            )
        )
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(FACILITY_SCHEMA))


def create_loans(*, core_uk_group: bool = False) -> pl.DataFrame:
    """Build the loan table (5 rows base; 6 in the CUG variant).

    Base: 3 external + 2 intragroup (one per direction). The CUG variant appends
    ``LOAN_A1_IG_UNDRAWN`` (1m drawn under FAC_A1_IG_UNDRAWN's 1.5m limit).
    """
    rows = [
        _Loan("LOAN_A1_EXT", "BOOK_A1", "CORP_EXT_A1", DRAWN_AMOUNT),
        _Loan("LOAN_A2_EXT", "BOOK_A2", "CORP_EXT_A2", DRAWN_AMOUNT),
        _Loan("LOAN_B1_EXT", "BOOK_B1", "CORP_EXT_B1", DRAWN_AMOUNT),
        _Loan(
            "LOAN_A1_IG_TO_BANK_B",
            "BOOK_A1",
            "BANK_B",
            DRAWN_AMOUNT,
            intragroup_entity_reference="BANK_B",
        ),
        _Loan(
            "LOAN_B1_IG_TO_BANK_A",
            "BOOK_B1",
            "BANK_A",
            DRAWN_AMOUNT,
            intragroup_entity_reference="BANK_A",
        ),
    ]
    if core_uk_group:
        rows.append(
            _Loan(
                "LOAN_A1_IG_UNDRAWN",
                "BOOK_A1",
                "BANK_B",
                DRAWN_AMOUNT,
                intragroup_entity_reference="BANK_B",
            )
        )
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_facility_mappings(*, core_uk_group: bool = False) -> pl.DataFrame:
    """Build the facility_mapping table (5 rows base; 6 in the CUG variant)."""
    rows = [
        _FacilityMapping("FAC_A1_EXT", "LOAN_A1_EXT"),
        _FacilityMapping("FAC_A2_EXT", "LOAN_A2_EXT"),
        _FacilityMapping("FAC_B1_EXT", "LOAN_B1_EXT"),
        _FacilityMapping("FAC_A1_IG", "LOAN_A1_IG_TO_BANK_B"),
        _FacilityMapping("FAC_B1_IG", "LOAN_B1_IG_TO_BANK_A"),
    ]
    if core_uk_group:
        rows.append(_FacilityMapping("FAC_A1_IG_UNDRAWN", "LOAN_A1_IG_UNDRAWN"))
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(FACILITY_MAPPING_SCHEMA))


def create_lending_mappings() -> pl.DataFrame:
    """Build the (empty) lending_mapping table -- mandatory file, corporate-only
    dataset needs no retail connected-party aggregation."""
    return pl.DataFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA))


def create_guarantees() -> pl.DataFrame:
    """Build the 2-row guarantee table: one intragroup, one plain external."""
    rows = [
        _Guarantee(
            "GUAR_IG_BANK_B_TO_A1EXT",
            "BANK_B",
            "LOAN_A1_EXT",
            amount_covered=500_000.0,
            percentage_covered=0.5,
            guarantor_entity_reference="BANK_B",
        ),
        _Guarantee(
            "GUAR_EXT_PLAIN",
            "EXT_BANK_1",
            "LOAN_B1_EXT",
            amount_covered=500_000.0,
            percentage_covered=0.5,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(GUARANTEE_SCHEMA))


def create_reporting_entities(*, core_uk_group: bool = False) -> pl.DataFrame:
    """Build the 3-row reporting-entity registry: GRP apex, BANK_A, BANK_B.

    ``core_uk_group`` stamps the CRR Art. 113(6) permission flag on all three
    entities — the only difference between the base ``multi_entity`` dataset
    (False) and the ``multi_entity_cug`` variant (True). See the module
    docstring for the per-scope hand-calc the flag produces.
    """
    rows = [
        _ReportingEntity(
            "GRP", "Group PLC", "LEI00000000000000GRP", None, core_uk_group=core_uk_group
        ),
        _ReportingEntity(
            "BANK_A", "Bank A Ltd", "LEI00000000000000BKA", "GRP", core_uk_group=core_uk_group
        ),
        _ReportingEntity(
            "BANK_B", "Bank B Ltd", "LEI00000000000000BKB", "GRP", core_uk_group=core_uk_group
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(REPORTING_ENTITY_SCHEMA))


def create_book_entity_mappings() -> pl.DataFrame:
    """Build the 3-row book -> reporting-entity mapping table."""
    rows = [
        _BookEntityMapping("BOOK_A1", "BANK_A"),
        _BookEntityMapping("BOOK_A2", "BANK_A"),
        _BookEntityMapping("BOOK_B1", "BANK_B"),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(BOOK_ENTITY_MAPPING_SCHEMA))


# =============================================================================
# Persistence
# =============================================================================


def save_multi_entity_fixtures(output_dir: Path, *, core_uk_group: bool = False) -> dict[str, Path]:
    """Write the full input directory tree under ``output_dir``.

    Mirrors ``src/rwa_calc/config/data_sources.py`` relative paths so the
    directory can be pointed at directly as ``data_path`` (e.g.
    ``CreditRiskCalc(data_path=output_dir)``) once the two new OPTIONAL
    sources (``reporting_entities``, ``book_entity_mapping``) are registered.

    ``core_uk_group`` selects the variant: False writes the base
    ``multi_entity`` dataset (normal intragroup risk weights); True writes the
    ``multi_entity_cug`` variant (all three entities in the CRR Art. 113(6) core
    UK group), where an individual-basis run applies the 0% intragroup RW. The
    CUG variant differs by the registry flag PLUS three appended rows exercising
    the undrawn path (FAC_A1_IG_UNDRAWN / LOAN_A1_IG_UNDRAWN / its mapping); the
    base dataset's files are unchanged.

    Returns:
        Mapping of a short logical name to the written parquet path (used by
        ``generate_all.py`` for row-count reporting).
    """
    tables: dict[str, tuple[Path, pl.DataFrame]] = {
        "counterparties": (
            output_dir / "counterparty" / "counterparties.parquet",
            create_counterparties(),
        ),
        "facilities": (
            output_dir / "exposures" / "facilities.parquet",
            create_facilities(core_uk_group=core_uk_group),
        ),
        "loans": (
            output_dir / "exposures" / "loans.parquet",
            create_loans(core_uk_group=core_uk_group),
        ),
        "facility_mapping": (
            output_dir / "exposures" / "facility_mapping.parquet",
            create_facility_mappings(core_uk_group=core_uk_group),
        ),
        "lending_mapping": (
            output_dir / "mapping" / "lending_mapping.parquet",
            create_lending_mappings(),
        ),
        "book_entity_mapping": (
            output_dir / "mapping" / "book_entity_mapping.parquet",
            create_book_entity_mappings(),
        ),
        "guarantee": (
            output_dir / "guarantee" / "guarantee.parquet",
            create_guarantees(),
        ),
        "reporting_entities": (
            output_dir / "config" / "reporting_entities.parquet",
            create_reporting_entities(core_uk_group=core_uk_group),
        ),
    }

    saved: dict[str, Path] = {}
    for name, (path, df) in tables.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(path)
        saved[name] = path
    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print generation summary."""
    print(f"Saved multi-entity fixtures to: {saved['counterparties'].parent.parent}")
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name}: {len(df)} rows -> {path.relative_to(Path(__file__).parent)}")


if __name__ == "__main__":
    main()
