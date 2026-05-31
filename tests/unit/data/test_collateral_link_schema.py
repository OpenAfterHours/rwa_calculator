"""
Unit tests for ``COLLATERAL_LINK_SCHEMA`` (collateral_links input table).

Covers the M:N collateral-to-beneficiary linkage schema that lets one finite
collateral item be pledged against multiple beneficiaries, with the engine
splitting the value for the most beneficial RWA impact.

References:
- CRR Art. 193/194/207: eligibility and recognition of credit risk mitigation
- CRR Art. 230-231: substitution / sequential allocation of collateral
"""

from __future__ import annotations

import polars as pl

from rwa_calc.data.schemas import (
    COLLATERAL_LINK_SCHEMA,
    COLUMN_VALUE_CONSTRAINTS,
    VALID_BENEFICIARY_TYPES,
)


class TestCollateralLinkSchema:
    """The collateral_links table maps one collateral item to many beneficiaries."""

    def test_required_columns_present(self) -> None:
        # Arrange / Act
        required = {name for name, spec in COLLATERAL_LINK_SCHEMA.items() if spec.required}

        # Assert
        assert required == {
            "collateral_reference",
            "beneficiary_type",
            "beneficiary_reference",
        }

    def test_optional_columns_present(self) -> None:
        # Arrange / Act
        optional = {name for name, spec in COLLATERAL_LINK_SCHEMA.items() if not spec.required}

        # Assert
        assert {"max_pledge_amount", "priority"} <= optional

    def test_collateral_reference_is_string(self) -> None:
        assert COLLATERAL_LINK_SCHEMA["collateral_reference"].dtype == pl.String

    def test_max_pledge_amount_is_float(self) -> None:
        assert COLLATERAL_LINK_SCHEMA["max_pledge_amount"].dtype == pl.Float64

    def test_priority_is_integer(self) -> None:
        assert COLLATERAL_LINK_SCHEMA["priority"].dtype == pl.Int32

    def test_beneficiary_type_constraint_registered(self) -> None:
        # Assert — reuses the same beneficiary-type value set as the collateral table.
        assert (
            COLUMN_VALUE_CONSTRAINTS["collateral_links"]["beneficiary_type"]
            == VALID_BENEFICIARY_TYPES
        )
