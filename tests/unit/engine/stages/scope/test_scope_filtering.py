"""
Booking-filter, intragroup-elimination and guarantee-drop behaviour for the
scope resolver, plus the SCP001 / SCP002 / SCP003 / SCP005 data-quality codes.

References:
- CRR Part One Title II (Art. 6, 11-18): consolidation eliminates intragroup
  exposures; solo books include them.
- docs/plans/multi-entity-reporting.md: scope resolver specification.
"""

from __future__ import annotations

from datetime import date

import polars as pl
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ErrorSeverity, ReportingBasis
from rwa_calc.engine.stages.scope import resolver

# GRP apex over BANK_A / BANK_B; BOOK_A->BANK_A, BOOK_B->BANK_B.
_TREE = pl.DataFrame(
    {
        "entity_reference": ["GRP", "BANK_A", "BANK_B"],
        "parent_entity_reference": [None, "GRP", "GRP"],
    }
)
_MAPPING = pl.DataFrame(
    {
        "book_code": ["BOOK_A", "BOOK_B"],
        "reporting_entity_reference": ["BANK_A", "BANK_B"],
    }
)


def _loans(rows: list[tuple[str, str, str, str | None]]) -> pl.DataFrame:
    """rows: (loan_reference, book_code, counterparty_reference, intragroup)."""
    return pl.DataFrame(
        {
            "loan_reference": [r[0] for r in rows],
            "book_code": [r[1] for r in rows],
            "counterparty_reference": [r[2] for r in rows],
            "intragroup_entity_reference": [r[3] for r in rows],
        }
    )


def _guarantees(rows: list[tuple[str, str, str | None]]) -> pl.DataFrame:
    """rows: (guarantee_reference, beneficiary_reference, guarantor_entity)."""
    return pl.DataFrame(
        {
            "guarantee_reference": [r[0] for r in rows],
            "beneficiary_reference": [r[1] for r in rows],
            "guarantor_entity_reference": [r[2] for r in rows],
        }
    )


def _bundle(
    *,
    loans: pl.DataFrame | None = None,
    guarantees: pl.DataFrame | None = None,
    mapping: pl.DataFrame | None = None,
):
    return make_raw_bundle(
        loans=loans,
        guarantees=guarantees,
        reporting_entities=_TREE,
        book_entity_mappings=_MAPPING if mapping is None else mapping,
    )


def _resolve(bundle, entity: str, basis: ReportingBasis):
    config = CalculationConfig.crr(
        reporting_date=date(2026, 1, 1), reporting_entity=entity, reporting_basis=basis
    )
    return resolver.resolve_scope(bundle, config)


def _refs(frame: pl.LazyFrame | None, column: str) -> set[str]:
    assert frame is not None
    return set(frame.collect()[column].to_list())


def _codes(result) -> list[str]:
    return sorted(e.code for e in result.errors if e.code.startswith("SCP"))


# ---------------------------------------------------------------------------
# Booking filter
# ---------------------------------------------------------------------------


def test_booking_filter_keeps_only_in_scope_books():
    bundle = _bundle(
        loans=_loans(
            [("LA", "BOOK_A", "CP1", None), ("LB", "BOOK_B", "CP2", None)],
        )
    )

    result = _resolve(bundle, "BANK_A", ReportingBasis.INDIVIDUAL)

    assert _refs(result.loans, "loan_reference") == {"LA"}


def test_consolidated_membership_spans_subsidiary_books():
    bundle = _bundle(
        loans=_loans(
            [("LA", "BOOK_A", "CP1", None), ("LB", "BOOK_B", "CP2", None)],
        )
    )

    result = _resolve(bundle, "GRP", ReportingBasis.CONSOLIDATED)

    assert _refs(result.loans, "loan_reference") == {"LA", "LB"}


def test_blank_or_unmapped_book_is_excluded_with_scp001():
    bundle = _bundle(
        loans=_loans(
            [
                ("LA", "BOOK_A", "CP1", None),
                ("BLANK", "", "CP2", None),
                ("UNMAPPED", "BOOK_Z", "CP3", None),
            ],
        )
    )

    result = _resolve(bundle, "BANK_A", ReportingBasis.INDIVIDUAL)

    assert _refs(result.loans, "loan_reference") == {"LA"}
    assert resolver.SCP_UNATTRIBUTABLE_BOOK in _codes(result)


def test_mapping_to_unknown_entity_raises_scp002_and_ignores_row():
    mapping = pl.DataFrame(
        {
            "book_code": ["BOOK_A", "BOOK_GHOST"],
            "reporting_entity_reference": ["BANK_A", "GHOST_ENTITY"],
        }
    )
    bundle = _bundle(
        loans=_loans(
            [("LA", "BOOK_A", "CP1", None), ("LG", "BOOK_GHOST", "CP2", None)],
        ),
        mapping=mapping,
    )

    result = _resolve(bundle, "BANK_A", ReportingBasis.INDIVIDUAL)

    # BOOK_GHOST maps only to an unregistered entity -> ignored -> LG excluded,
    # and it is NOT double-reported as an unattributable (SCP001) book.
    assert _refs(result.loans, "loan_reference") == {"LA"}
    assert resolver.SCP_MAPPING_UNKNOWN_ENTITY in _codes(result)
    assert resolver.SCP_UNATTRIBUTABLE_BOOK not in _codes(result)


# ---------------------------------------------------------------------------
# Intragroup elimination vs retention
# ---------------------------------------------------------------------------


def test_consolidated_drops_intragroup_to_member():
    bundle = _bundle(
        loans=_loans(
            [
                ("EXT", "BOOK_A", "CP_EXT", None),
                ("IG", "BOOK_A", "BANK_B", "BANK_B"),
            ],
        )
    )

    result = _resolve(bundle, "GRP", ReportingBasis.CONSOLIDATED)

    assert _refs(result.loans, "loan_reference") == {"EXT"}


def test_individual_keeps_intragroup_to_member():
    bundle = _bundle(
        loans=_loans(
            [
                ("EXT", "BOOK_A", "CP_EXT", None),
                ("IG", "BOOK_A", "BANK_B", "BANK_B"),
            ],
        )
    )

    result = _resolve(bundle, "BANK_A", ReportingBasis.INDIVIDUAL)

    assert _refs(result.loans, "loan_reference") == {"EXT", "IG"}


def test_intragroup_tag_to_unknown_entity_is_kept_with_scp003():
    bundle = _bundle(
        loans=_loans(
            [("IG_BAD", "BOOK_A", "CP1", "GHOST_ENTITY")],
        )
    )

    result = _resolve(bundle, "GRP", ReportingBasis.CONSOLIDATED)

    # Tag names an unregistered entity: the row is kept (external) and flagged.
    assert _refs(result.loans, "loan_reference") == {"IG_BAD"}
    assert resolver.SCP_INTRAGROUP_UNKNOWN_ENTITY in _codes(result)


# ---------------------------------------------------------------------------
# Guarantees
# ---------------------------------------------------------------------------


def test_consolidated_drops_internal_guarantee():
    bundle = _bundle(
        loans=_loans([("LA", "BOOK_A", "CP1", None)]),
        guarantees=_guarantees(
            [("G_INT", "LA", "BANK_B"), ("G_EXT", "LA", None)],
        ),
    )

    result = _resolve(bundle, "GRP", ReportingBasis.CONSOLIDATED)

    assert _refs(result.guarantees, "guarantee_reference") == {"G_EXT"}


def test_individual_keeps_all_guarantees():
    bundle = _bundle(
        loans=_loans([("LA", "BOOK_A", "CP1", None)]),
        guarantees=_guarantees(
            [("G_INT", "LA", "BANK_B"), ("G_EXT", "LA", None)],
        ),
    )

    result = _resolve(bundle, "BANK_A", ReportingBasis.INDIVIDUAL)

    assert _refs(result.guarantees, "guarantee_reference") == {"G_INT", "G_EXT"}


# ---------------------------------------------------------------------------
# SCP005 — mixed tagging
# ---------------------------------------------------------------------------


def test_mixed_tagging_counterparty_raises_scp005_warning():
    bundle = _bundle(
        loans=_loans(
            [
                ("TAGGED", "BOOK_A", "CP_MIX", "BANK_B"),
                ("UNTAGGED", "BOOK_A", "CP_MIX", None),
            ],
        )
    )

    result = _resolve(bundle, "BANK_A", ReportingBasis.INDIVIDUAL)

    warning = next(e for e in result.errors if e.code == resolver.SCP_MIXED_TAGGING)
    assert warning.severity is ErrorSeverity.WARNING
    assert "CP_MIX" in warning.message


def test_consistent_tagging_raises_no_scp005():
    bundle = _bundle(
        loans=_loans(
            [
                ("A1", "BOOK_A", "CP_TAGGED", "BANK_B"),
                ("A2", "BOOK_A", "CP_TAGGED", "BANK_B"),
                ("B1", "BOOK_A", "CP_PLAIN", None),
            ],
        )
    )

    result = _resolve(bundle, "BANK_A", ReportingBasis.INDIVIDUAL)

    assert resolver.SCP_MIXED_TAGGING not in _codes(result)
