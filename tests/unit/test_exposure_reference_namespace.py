"""RC-10: an exposure_reference claimed by two namespaces draws DQ019 and is kept apart.

Uniqueness was declared PER TABLE only (``data/schemas.py::TABLE_UNIQUE_KEYS``),
so a loan and a contingent sharing a reference were plausible input — and every
join keyed on the bare reference merged them, silently (review finding RC-10,
both probes re-run by the verifier):

- guarantee on ``(loan, X1)`` with a contingent also named X1: both rows became
  ``X1__G_UKGOV`` at 500,000 each — total EAD 2,000,000 -> 1,000,000 and RWA
  1,000,000 -> 0 (the guarantee covered the contingent too);
- IRB permission mode, no CRM at all: ``classify/permissions.py``'s
  ``unique(exposure_reference)`` kept ONE row — EAD 2,000,000 -> 1,000,000.

Rule text the fix relies on (CRR and PS1/26 identical): Art. 213(1)(a) — "the
credit protection is direct" (protection bought on one claim cannot cover
another); Art. 111(1) — the exposure value of each item is measured.

The fix (orchestrator decision): DQ019 ERROR per colliding reference at the
input gate, and the hierarchy stage keeps the rows apart by re-keying each
colliding loan / contingent to ``<reference>#<type>`` and resolving every typed
pointer — here the guarantee's ``beneficiary_type`` — by its declared type.

Hand calculation (unrated non-SME corporate obligor 100%; UK sovereign CQS 1
guarantor 0% in both regimes; contingent ``full_risk`` CCF 100%): loan X1 1m
fully guaranteed -> RWA 0; contingent X1 1m unguaranteed -> RWA 1,000,000.
Total EAD 2,000,000, RWA 1,000,000 — exactly the distinct-reference result.
"""

from __future__ import annotations

import dataclasses
from datetime import date
from functools import cache
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.bundles import AggregatedResultBundle, RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_DUPLICATE_KEY, ERROR_EXPOSURE_REFERENCE_COLLISION
from rwa_calc.contracts.validation import validate_bundle_values
from rwa_calc.domain.enums import ErrorSeverity, PermissionMode
from rwa_calc.engine.classify.permissions import resolve_model_permissions
from rwa_calc.engine.hierarchy.namespace import (
    qualify_colliding_references,
    qualify_securitisation_lookup,
)
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import seal_raw_table
from tests.integration.conftest import (
    make_contingent,
    make_counterparty,
    make_equity_exposure,
    make_facility,
    make_loan,
    make_model_permission,
    make_rating,
    make_raw_data_bundle,
)

_REGIMES = ("CRR", "B31")


def _config(regime: str, **kwargs: Any) -> CalculationConfig:
    if regime == "CRR":
        return CalculationConfig.crr(reporting_date=date(2026, 6, 30), **kwargs)
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30), **kwargs)


def _dq019(bundle: RawDataBundle) -> list[Any]:
    return [
        e for e in validate_bundle_values(bundle) if e.code == ERROR_EXPOSURE_REFERENCE_COLLISION
    ]


class TestInputGate:
    """DQ019: one ERROR per reference claimed by more than one namespace."""

    def test_loan_and_contingent_sharing_a_reference(self) -> None:
        bundle = make_raw_data_bundle(
            loans=[make_loan(loan_reference="X1")],
            contingents=[make_contingent(contingent_reference="X1")],
            facility_mappings=[],
        )

        found = _dq019(bundle)

        assert [(e.exposure_reference, e.actual_value) for e in found] == [
            ("X1", "contingents, loans")
        ]
        assert found[0].severity == ErrorSeverity.ERROR
        assert "'X1#loan'" in found[0].message
        assert "'X1#contingent'" in found[0].message

    def test_loan_named_like_an_engine_minted_undrawn_row(self) -> None:
        bundle = make_raw_data_bundle(
            loans=[make_loan(loan_reference="FAC001_UNDRAWN")],
            facilities=[make_facility(facility_reference="FAC001")],
            facility_mappings=[],
        )

        found = _dq019(bundle)

        assert [e.exposure_reference for e in found] == ["FAC001_UNDRAWN"]
        assert "facilities" in found[0].actual_value

    def test_loan_and_equity_sharing_a_reference(self) -> None:
        bundle = make_raw_data_bundle(
            loans=[make_loan(loan_reference="EQ001")],
            equity_exposures=[make_equity_exposure(exposure_reference="EQ001")],
            facility_mappings=[],
        )

        assert [(e.exposure_reference, e.actual_value) for e in _dq019(bundle)] == [
            ("EQ001", "equity_exposures, loans")
        ]

    def test_facility_reference_equal_to_loan_reference_is_legitimate(self) -> None:
        # A facility is not an exposure namespace: ``F1`` the facility and ``F1``
        # the loan drawn under it is an established input pattern.
        bundle = make_raw_data_bundle(
            loans=[make_loan(loan_reference="F1")],
            facilities=[make_facility(facility_reference="F1")],
            facility_mappings=[],
        )

        assert _dq019(bundle) == []

    def test_a_within_table_duplicate_stays_dq004(self) -> None:
        bundle = make_raw_data_bundle(
            loans=[make_loan(loan_reference="L1"), make_loan(loan_reference="L1")],
            facility_mappings=[],
        )
        errors = validate_bundle_values(bundle)

        assert [e.code for e in errors if e.exposure_reference == "L1"] == [ERROR_DUPLICATE_KEY]


def _guarantee_bundle(contingent_reference: str) -> RawDataBundle:
    bundle = make_raw_data_bundle(
        counterparties=[
            make_counterparty(),
            make_counterparty(
                counterparty_reference="UKGOV",
                entity_type="sovereign",
                annual_revenue=None,
                total_assets=None,
            ),
        ],
        loans=[make_loan(loan_reference="X1", drawn_amount=1e6, interest=0.0)],
        contingents=[
            make_contingent(contingent_reference=contingent_reference, nominal_amount=1e6)
        ],
        facilities=[make_facility(facility_reference="F1", limit=0.0)],
        facility_mappings=[],
        ratings=[
            make_rating(
                rating_reference="RG",
                counterparty_reference="UKGOV",
                rating_type="external",
                rating_agency="SP",
                rating_value="AA",
                cqs=1,
                pd=None,
            )
        ],
    )
    guarantees = seal_raw_table(
        pl.LazyFrame(
            {
                "guarantee_reference": ["G1"],
                "guarantor": ["UKGOV"],
                "amount_covered": [1_000_000.0],
                "beneficiary_type": ["loan"],
                "beneficiary_reference": ["X1"],
                "currency": ["GBP"],
                "maturity_date": [date(2030, 1, 1)],
            }
        ),
        "guarantees",
    )
    return dataclasses.replace(bundle, guarantees=guarantees)


@cache
def _guarantee_run(regime: str, contingent_reference: str) -> AggregatedResultBundle:
    return PipelineOrchestrator().run_with_data(
        _guarantee_bundle(contingent_reference), _config(regime)
    )


@pytest.mark.parametrize("regime", _REGIMES)
class TestGuaranteeIsDirect:
    """The guarantee on loan X1 covers the loan, not the contingent sharing X1."""

    def test_totals_equal_the_distinct_reference_hand_calculation(self, regime: str) -> None:
        ledger = _guarantee_run(regime, "X1").results.collect()

        assert ledger["ead_final"].sum() == pytest.approx(2_000_000.0)
        assert ledger["rwa_final"].sum() == pytest.approx(1_000_000.0)

    def test_the_twin_with_distinct_references_agrees(self, regime: str) -> None:
        # Adequacy: the shared-reference book must be priced exactly as the same
        # book with the contingent renamed - the property the defect broke.
        shared = _guarantee_run(regime, "X1").results.collect()
        distinct = _guarantee_run(regime, "C1").results.collect()

        assert distinct["rwa_final"].sum() == pytest.approx(1_000_000.0)
        assert shared["rwa_final"].sum() == pytest.approx(distinct["rwa_final"].sum())

    def test_rows_are_published_under_type_qualified_references(self, regime: str) -> None:
        ledger = _guarantee_run(regime, "X1").results.collect()
        contingent = ledger.filter(pl.col("exposure_type") == "contingent")

        assert contingent["exposure_reference"].to_list() == ["X1#contingent"]
        assert contingent["rwa_final"].sum() == pytest.approx(1_000_000.0)
        assert set(ledger.filter(pl.col("exposure_type") == "loan")["exposure_reference"]) <= {
            "X1#loan__G_UKGOV",
            "X1#loan__REM",
        }

    def test_dq019_reaches_the_result(self, regime: str) -> None:
        found = [
            e
            for e in _guarantee_run(regime, "X1").errors
            if e.code == ERROR_EXPOSURE_REFERENCE_COLLISION
        ]

        assert [e.exposure_reference for e in found] == ["X1"]


@cache
def _irb_run(regime: str, contingent_reference: str) -> AggregatedResultBundle:
    bundle = make_raw_data_bundle(
        counterparties=[make_counterparty(annual_revenue=200e6, total_assets=500e6)],
        loans=[make_loan(loan_reference="X1", drawn_amount=1e6, interest=0.0)],
        contingents=[
            make_contingent(contingent_reference=contingent_reference, nominal_amount=1e6)
        ],
        facilities=[make_facility(facility_reference="F1", limit=0.0)],
        facility_mappings=[],
        ratings=[make_rating(pd=0.01, model_id="M1")],
        model_permissions=[make_model_permission(model_id="M1")],
    )
    return PipelineOrchestrator().run_with_data(
        bundle, _config(regime, permission_mode=PermissionMode.IRB)
    )


@pytest.mark.parametrize("regime", _REGIMES)
class TestIrbPermissionDeduplication:
    """No CRM at all: the model-permission de-duplication must keep both rows.

    EAD = 1,000,000 drawn + 1,000,000 x 100% (full risk) = 2,000,000; the IRB
    RWA must equal the distinct-reference twin's (verifier: CRR 2,227,298 /
    B31 1,642,115, against 1,113,649 / 821,057 with one row lost).
    """

    def test_both_rows_survive(self, regime: str) -> None:
        ledger = _irb_run(regime, "X1").results.collect()

        assert sorted(ledger["exposure_reference"].to_list()) == ["X1#contingent", "X1#loan"]
        assert ledger["ead_final"].sum() == pytest.approx(2_000_000.0)

    def test_rwa_equals_the_distinct_reference_twin(self, regime: str) -> None:
        shared = _irb_run(regime, "X1").results.collect()
        distinct = _irb_run(regime, "C1").results.collect()

        assert set(distinct["approach_applied"]) == {"foundation_irb"}, "adequacy: IRB rows"
        assert shared["rwa_final"].sum() == pytest.approx(distinct["rwa_final"].sum())


class TestPermissionDeduplicationIsTypeAware:
    """``classify/permissions.py`` keeps one row per (reference, type), not per reference.

    Defence in depth behind the re-key: the de-duplication that collapsed the
    contingent in the IRB probe must not delete a row of another table should
    two still meet there.
    """

    def test_a_loan_and_a_contingent_sharing_a_reference_both_survive(self) -> None:
        exposures = pl.LazyFrame(
            {
                "exposure_reference": ["X1", "X1"],
                "exposure_type": ["loan", "contingent"],
                "cp_internal_model_id": ["M1", "M1"],
                "model_id": ["M1", "M1"],
                "exposure_class": ["corporate", "corporate"],
                "exposure_class_irb": ["corporate", "corporate"],
                "book_code": ["MAIN", "MAIN"],
                "cp_country_code": ["GB", "GB"],
            }
        )
        permissions = pl.LazyFrame(
            {
                "model_id": ["M1"],
                "exposure_class": ["corporate"],
                "approach": ["foundation_irb"],
                "country_codes": [None],
                "excluded_book_codes": [None],
                "ppu_reason": [None],
            },
            schema_overrides={
                "country_codes": pl.String,
                "excluded_book_codes": pl.String,
                "ppu_reason": pl.String,
            },
        )

        result = resolve_model_permissions(exposures, permissions).collect()

        assert sorted(result["exposure_type"].to_list()) == ["contingent", "loan"]
        assert result["model_firb_permitted"].to_list() == [True, True]


def _pointer_frame(table: str, rows: list[tuple[str, str]], **extra: list[Any]) -> pl.LazyFrame:
    """A sealed CRM pointer table: (beneficiary_type, beneficiary_reference) rows."""
    reference = {"collateral": "collateral_reference", "provisions": "provision_reference"}
    columns: dict[str, list[Any]] = {
        "beneficiary_type": [kind for kind, _ in rows],
        "beneficiary_reference": [ref for _, ref in rows],
        **extra,
    }
    if table in reference:
        columns[reference[table]] = [f"{table}_{i}" for i in range(len(rows))]
    if table == "collateral_links":
        columns["collateral_reference"] = ["COLL"] * len(rows)
    return seal_raw_table(pl.LazyFrame(columns), table)


class TestQualifyCollidingReferences:
    """``engine/hierarchy/namespace.py``: every typed pointer follows its row."""

    @staticmethod
    def _bundle() -> RawDataBundle:
        bundle = make_raw_data_bundle(
            loans=[make_loan(loan_reference="X1"), make_loan(loan_reference="L2")],
            contingents=[make_contingent(contingent_reference="X1")],
            facility_mappings=[
                {
                    "parent_facility_reference": "FAC001",
                    "child_reference": "X1",
                    "child_type": "loan",
                },
                {
                    "parent_facility_reference": "FAC001",
                    "child_reference": "X1",
                    "child_type": "Contingent",
                },
                {
                    "parent_facility_reference": "FAC001",
                    "child_reference": "L2",
                    "child_type": "loan",
                },
            ],
            ratings=[
                make_rating(rating_reference="R1", scope_type="loan", scope_id="X1"),
                make_rating(rating_reference="R2", scope_type="facility", scope_id="X1"),
            ],
        )
        return dataclasses.replace(
            bundle,
            collateral=_pointer_frame("collateral", [("loan", "X1"), ("counterparty", "X1")]),
            collateral_links=_pointer_frame(
                "collateral_links", [("contingent", "X1"), ("exposure", "X1")]
            ),
            provisions=_pointer_frame("provisions", [("contingent", "X1"), ("loan", "L2")]),
        )

    def test_clean_book_is_returned_untouched(self) -> None:
        bundle = self._bundle()

        assert qualify_colliding_references(bundle, []) is bundle

    def test_rows_and_typed_pointers_are_re_keyed(self) -> None:
        qualified = qualify_colliding_references(self._bundle(), ["X1"])

        assert qualified.loans.collect()["loan_reference"].to_list() == ["X1#loan", "L2"]
        assert qualified.contingents is not None
        assert qualified.contingents.collect()["contingent_reference"].to_list() == [
            "X1#contingent"
        ]
        assert qualified.facility_mappings.collect()["child_reference"].to_list() == [
            "X1#loan",
            "X1#contingent",
            "L2",
        ]
        assert qualified.ratings is not None
        assert qualified.ratings.collect()["scope_id"].to_list() == ["X1#loan", "X1"]

    @pytest.mark.parametrize(
        ("field", "expected"),
        [
            ("collateral", ["X1#loan", "X1"]),
            ("collateral_links", ["X1#contingent", "X1"]),
            ("provisions", ["X1#contingent", "L2"]),
        ],
    )
    def test_crm_beneficiaries_follow_their_declared_type(
        self, field: str, expected: list[str]
    ) -> None:
        # A counterparty-level pointer and the generic 'exposure' type do not name
        # a loan or a contingent, so they are left alone (and match neither row).
        frame = getattr(qualify_colliding_references(self._bundle(), ["X1"]), field)

        assert frame.collect()["beneficiary_reference"].to_list() == expected

    def test_securitisation_allocations_follow_the_loan(self) -> None:
        lookup = pl.LazyFrame(
            {
                "exposure_reference": ["X1", "X1", "F9"],
                "exposure_type": ["loan", "facility", "facility"],
            }
        )

        qualified = qualify_securitisation_lookup(lookup, ["X1"])

        assert qualified is not None
        assert qualified.collect()["exposure_reference"].to_list() == ["X1#loan", "X1", "F9"]
