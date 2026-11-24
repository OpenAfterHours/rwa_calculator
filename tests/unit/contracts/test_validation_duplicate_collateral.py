"""
P1.444 (review CL-03): a repeated ``collateral.collateral_reference`` draws DQ004.

The collateral table's ``collateral_reference`` is documented as a unique
identifier (``docs/data-model/input-schemas.md``): the finite value of a pledge
that backs several exposures is stated ONCE, on one collateral row, and the
split goes in the ``collateral_links`` table (``data/schemas.py`` comment on
``COLLATERAL_LINK_SCHEMA``). Before this item the input gate accepted a repeat
silently, and the CRM stage credited the same item once per row.

Rule text: PS1/26 Art. 193(7) — "Where an institution has an item of eligible
collateral covering multiple exposures the institution shall: (a) subdivide the
eligible collateral into one or more portions; (b) allocate each portion of
eligible collateral to one of the exposures it covers, without any
double-counting". The control itself is regime-neutral: it enforces the input
contract, so it fires identically under CRR.

The finding must NOT name an exposure or a counterparty: a collateral reference
equal to a loan reference would otherwise attach the error to that loan in any
per-exposure triage join. The reference travels in ``field_name`` /
``actual_value`` instead.
"""

from __future__ import annotations

import polars as pl
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.errors import ERROR_DUPLICATE_KEY
from rwa_calc.contracts.validation import validate_duplicate_keys
from rwa_calc.domain.enums import ErrorSeverity


def _bundle(
    collateral_references: list[str | None],
    *,
    collateral_links: pl.LazyFrame | None = None,
) -> RawDataBundle:
    """Two loans and one collateral row per supplied reference, each on its own loan."""
    beneficiaries = ["L1", "L2", "L1", "L2"][: len(collateral_references)]
    return make_raw_bundle(
        loans=pl.LazyFrame({"loan_reference": ["L1", "L2"]}),
        counterparties=pl.LazyFrame({"counterparty_reference": ["CP1"]}),
        collateral=pl.LazyFrame(
            {
                "collateral_reference": collateral_references,
                "collateral_type": ["cash"] * len(collateral_references),
                "market_value": [60_000.0] * len(collateral_references),
                "beneficiary_type": ["loan"] * len(collateral_references),
                "beneficiary_reference": beneficiaries,
            },
            schema_overrides={"collateral_reference": pl.String},
        ),
        collateral_links=collateral_links,
    )


def _collateral_findings(bundle: RawDataBundle) -> list:
    return [
        e
        for e in validate_duplicate_keys(bundle)
        if e.code == ERROR_DUPLICATE_KEY and e.field_name == "collateral_reference"
    ]


class TestDuplicateCollateralReference:
    def test_a_repeated_reference_raises_one_error_naming_the_collateral(self) -> None:
        # Arrange — C1 supplied on two rows, one per loan.
        bundle = _bundle(["C1", "C1"])

        # Act
        found = _collateral_findings(bundle)

        # Assert — exactly one ERROR, carrying the reference, naming no exposure.
        assert len(found) == 1
        error = found[0]
        assert error.severity == ErrorSeverity.ERROR
        assert error.actual_value == "C1"
        assert error.exposure_reference is None
        assert error.counterparty_reference is None
        assert error.message.startswith("[collateral] 2 input rows share")

    def test_one_error_per_distinct_duplicated_reference(self) -> None:
        # Arrange — C1 and C2 each repeated: uncapped, one finding per key.
        bundle = _bundle(["C1", "C1", "C2", "C2"])

        # Act
        found = _collateral_findings(bundle)

        # Assert
        assert sorted(e.actual_value for e in found) == ["C1", "C2"]

    def test_unique_references_raise_nothing(self) -> None:
        # Arrange
        bundle = _bundle(["C1", "C2"])

        # Act / Assert
        assert _collateral_findings(bundle) == []

    def test_null_references_are_not_duplicates(self) -> None:
        # Arrange — a policy row may carry no reference (life insurance); two
        # null references are two unnamed rows, not one key named twice.
        bundle = _bundle([None, None])

        # Act / Assert
        assert _collateral_findings(bundle) == []

    def test_a_reference_repeated_in_collateral_links_is_legal(self) -> None:
        # Arrange — the M:N form: C1 stated once, linked to both loans. Repeats
        # in the links table are the documented way to pledge one item to many.
        links = pl.LazyFrame(
            {
                "collateral_reference": ["C1", "C1"],
                "beneficiary_type": ["loan", "loan"],
                "beneficiary_reference": ["L1", "L2"],
            }
        )
        bundle = _bundle(["C1"], collateral_links=links)

        # Act / Assert
        assert _collateral_findings(bundle) == []
