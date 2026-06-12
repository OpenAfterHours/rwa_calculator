"""
Unit tests for ``validate_collateral_links`` referential integrity.

The collateral_links table maps one finite collateral item to many
beneficiaries. Before the CRM stage splits the value, the loader validates
that every link resolves to a real collateral item and a real beneficiary,
and that no link is duplicated.

References:
- CRR Art. 193/194/207: CRM eligibility and recognition conditions
"""

from __future__ import annotations

import polars as pl
from tests.fixtures.raw_bundle import make_raw_bundle

from rwa_calc.contracts.errors import (
    ERROR_COLLATERAL_LINK_DUPLICATE,
    ERROR_COLLATERAL_LINK_UNKNOWN_BENEFICIARY,
    ERROR_COLLATERAL_LINK_UNKNOWN_COLLATERAL,
)
from rwa_calc.contracts.validation import validate_collateral_links


def _bundle(collateral_links: pl.LazyFrame | None):
    """A minimal raw bundle: two loans, one facility, one collateral item."""
    return make_raw_bundle(
        loans=pl.LazyFrame({"loan_reference": ["L1", "L2"]}),
        facilities=pl.LazyFrame({"facility_reference": ["F9"]}),
        counterparties=pl.LazyFrame({"counterparty_reference": ["CP1"]}),
        collateral=pl.LazyFrame({"collateral_reference": ["C1"]}),
        collateral_links=collateral_links,
    )


class TestValidateCollateralLinks:
    def test_valid_links_produce_no_errors(self) -> None:
        # Arrange — C1 backs loan L1, loan L2 and facility F9.
        links = pl.LazyFrame(
            {
                "collateral_reference": ["C1", "C1", "C1"],
                "beneficiary_type": ["loan", "loan", "facility"],
                "beneficiary_reference": ["L1", "L2", "F9"],
            }
        )

        # Act
        errors = validate_collateral_links(_bundle(links))

        # Assert
        assert errors == []

    def test_none_links_produce_no_errors(self) -> None:
        # Act / Assert — absent table is the no-op single-beneficiary path.
        assert validate_collateral_links(_bundle(None)) == []

    def test_unknown_collateral_reference_flagged(self) -> None:
        # Arrange — C2 is not in the collateral table.
        links = pl.LazyFrame(
            {
                "collateral_reference": ["C2"],
                "beneficiary_type": ["loan"],
                "beneficiary_reference": ["L1"],
            }
        )

        # Act
        errors = validate_collateral_links(_bundle(links))

        # Assert
        assert any(e.code == ERROR_COLLATERAL_LINK_UNKNOWN_COLLATERAL for e in errors)

    def test_unknown_beneficiary_reference_flagged(self) -> None:
        # Arrange — L9 is not a real loan.
        links = pl.LazyFrame(
            {
                "collateral_reference": ["C1"],
                "beneficiary_type": ["loan"],
                "beneficiary_reference": ["L9"],
            }
        )

        # Act
        errors = validate_collateral_links(_bundle(links))

        # Assert
        assert any(e.code == ERROR_COLLATERAL_LINK_UNKNOWN_BENEFICIARY for e in errors)

    def test_beneficiary_type_mismatch_flagged(self) -> None:
        # Arrange — F9 is a facility, not a loan; typing it as "loan" must not resolve.
        links = pl.LazyFrame(
            {
                "collateral_reference": ["C1"],
                "beneficiary_type": ["loan"],
                "beneficiary_reference": ["F9"],
            }
        )

        # Act
        errors = validate_collateral_links(_bundle(links))

        # Assert
        assert any(e.code == ERROR_COLLATERAL_LINK_UNKNOWN_BENEFICIARY for e in errors)

    def test_duplicate_link_flagged(self) -> None:
        # Arrange — the same (collateral, type, beneficiary) appears twice.
        links = pl.LazyFrame(
            {
                "collateral_reference": ["C1", "C1"],
                "beneficiary_type": ["loan", "loan"],
                "beneficiary_reference": ["L1", "L1"],
            }
        )

        # Act
        errors = validate_collateral_links(_bundle(links))

        # Assert
        assert any(e.code == ERROR_COLLATERAL_LINK_DUPLICATE for e in errors)
