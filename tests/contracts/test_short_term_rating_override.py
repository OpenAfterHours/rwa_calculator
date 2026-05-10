"""Contract tests for short-term rating override semantics.

A rating row carrying ``is_short_term=True`` with ``scope_type`` /
``scope_id`` populated must override the counterparty-level long-term rating
for the matching exposure. The HierarchyResolver computes a per-exposure
``has_short_term_ecai`` derived column and overwrites ``cqs`` with the short-
term rating's value when the (counterparty_reference, scope_type, scope_id)
tuple identifies an exposure.

The user-confirmed semantics is that the override applies regardless of the
SA maturity gate — the producer is responsible for only flagging rating rows
whose underlying exposure satisfies the regulatory maturity rule
(Art. 120(2B) ≤ 3 months for institutions, Art. 122(3) ≤ 3 months for
corporates). The engine trusts the producer.

References:
- PRA PS1/26 Art. 120(2B), Art. 122(3): short-term ECAI assessment tables
- src/rwa_calc/engine/hierarchy.py::HierarchyResolver._apply_short_term_rating_override
- src/rwa_calc/engine/sa/namespace.py::_b31_append_institution_maturity_branches
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)
from rwa_calc.engine.pipeline import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Test scenario constants
# ---------------------------------------------------------------------------

_CP_REF = "CP_ST_OVERRIDE_TEST"
_FAC_REF = "FAC_ST_OVERRIDE_TEST"
_LOAN_REF = "LN_ST_OVERRIDE_TEST"

_VALUE_DATE = date(2027, 1, 1)


def _dtypes(schema: dict) -> dict[str, pl.DataType]:
    """Project a schema dict onto its dtype map (handles ColumnSpec entries)."""
    return {name: spec.dtype for name, spec in schema.items()}


def _bundle_for(
    *,
    maturity_date: date,
    rating_is_short_term: bool,
    scope_type: str | None,
    scope_id: str | None,
    cqs_short_term: int = 1,
    cqs_long_term: int = 3,
) -> RawDataBundle:
    """Build a single-exposure bundle with the requested rating shape."""
    counterparties = pl.LazyFrame(
        [
            {
                "counterparty_reference": _CP_REF,
                "counterparty_name": "Override Test Bank",
                "entity_type": "bank",
                "country_code": "GB",
                "default_status": False,
                "apply_fi_scalar": False,
            }
        ],
        schema=_dtypes(COUNTERPARTY_SCHEMA),
    )
    facilities = pl.LazyFrame(
        [
            {
                "facility_reference": _FAC_REF,
                "product_type": "term_loan",
                "book_code": "FI_LENDING",
                "counterparty_reference": _CP_REF,
                "value_date": _VALUE_DATE,
                "maturity_date": maturity_date,
                "currency": "GBP",
                "limit": 1_000_000.0,
                "committed": True,
                "lgd": 0.45,
                "beel": 0.0,
                "is_revolving": False,
                "seniority": "senior",
                "risk_type": "MR",
                "is_short_term_trade_lc": False,
            }
        ],
        schema=_dtypes(FACILITY_SCHEMA),
    )
    loans = pl.LazyFrame(
        [
            {
                "loan_reference": _LOAN_REF,
                "counterparty_reference": _CP_REF,
                "currency": "GBP",
                "value_date": _VALUE_DATE,
                "maturity_date": maturity_date,
                "drawn_amount": 1_000_000.0,
                "interest": 0.0,
                "seniority": "senior",
            }
        ],
        schema=_dtypes(LOAN_SCHEMA),
    )
    rating_rows: list[dict] = [
        # Long-term external rating attached to the counterparty.
        {
            "rating_reference": "RTG_LT",
            "counterparty_reference": _CP_REF,
            "rating_type": "external",
            "rating_agency": "S&P",
            "rating_value": "BBB",
            "cqs": cqs_long_term,
            "pd": None,
            "rating_date": _VALUE_DATE,
            "is_solicited": True,
            "model_id": None,
            "is_short_term": False,
            "scope_type": None,
            "scope_id": None,
        }
    ]
    if rating_is_short_term:
        # Short-term rating row attached to the specific facility.
        rating_rows.append(
            {
                "rating_reference": "RTG_ST",
                "counterparty_reference": _CP_REF,
                "rating_type": "external",
                "rating_agency": "S&P",
                "rating_value": "A-1+",
                "cqs": cqs_short_term,
                "pd": None,
                "rating_date": _VALUE_DATE,
                "is_solicited": True,
                "model_id": None,
                "is_short_term": True,
                "scope_type": scope_type,
                "scope_id": scope_id,
            }
        )
    ratings = pl.LazyFrame(rating_rows, schema=_dtypes(RATINGS_SCHEMA))

    # Link the loan to the facility so the facility-scoped short-term rating
    # propagates onto the loan exposure via parent_facility_reference.
    facility_mappings = pl.LazyFrame(
        [
            {
                "parent_facility_reference": _FAC_REF,
                "child_reference": _LOAN_REF,
                "child_type": "loan",
            }
        ],
        schema={
            "parent_facility_reference": pl.String,
            "child_reference": pl.String,
            "child_type": pl.String,
        },
    )
    lending_mappings = pl.LazyFrame(
        schema={
            "parent_counterparty_reference": pl.String,
            "child_counterparty_reference": pl.String,
        }
    )

    return RawDataBundle(
        facilities=facilities,
        loans=loans,
        counterparties=counterparties,
        facility_mappings=facility_mappings,
        lending_mappings=lending_mappings,
        ratings=ratings,
    )


def _sa_row(bundle: RawDataBundle) -> dict:
    """Run the Basel 3.1 SA pipeline and return the single LOAN_REF result row."""
    config = CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 30),
        permission_mode=PermissionMode.STANDARDISED,
    )
    results = PipelineOrchestrator().run_with_data(bundle, config)
    assert results.sa_results is not None
    df = results.sa_results.collect()
    rows = df.filter(pl.col("exposure_reference") == _LOAN_REF).to_dicts()
    assert len(rows) == 1, f"expected 1 row, got {len(rows)}"
    return rows[0]


class TestShortTermRatingOverride:
    """The short-term rating row's CQS overrides the counterparty long-term CQS."""

    def test_short_term_rating_routes_to_table_4a(self) -> None:
        """A short-term CQS-1 rating attached to the facility → Table 4A 20%.

        Without the override the long-term CQS 3 rating would route via Table
        4 (short-term ECRA, 20% for CQS 1-3) → still 20% for CQS 1. So we
        compare against the long-term Table 6/4 lookup at CQS 3 by using a
        long-maturity exposure (>3m) for the contrastive case.
        """
        bundle = _bundle_for(
            maturity_date=date(2027, 3, 15),  # 73 days — Art. 120(2B) qualifies
            rating_is_short_term=True,
            scope_type="facility",
            scope_id=_FAC_REF,
            cqs_short_term=1,
            cqs_long_term=3,
        )
        row = _sa_row(bundle)
        # Table 4A CQS 1 = 20%.
        assert row["risk_weight"] == pytest.approx(0.20, abs=1e-6)

    def test_override_fires_regardless_of_maturity(self) -> None:
        """Engine routes via Table 4A even when original_maturity > 3 months.

        Per user-confirmed semantics, the short-term rating row overrides the
        SA gate unconditionally — the producer guarantees regulatory fitness.
        Maturity here is 2 years; a maturity-gated engine would route via the
        long-term Table 6, returning 50% for CQS 1. The override-only engine
        returns Table 4A's 20%.
        """
        bundle = _bundle_for(
            maturity_date=date(2029, 1, 1),  # 2 years — long-term by Art. 120(2B)
            rating_is_short_term=True,
            scope_type="facility",
            scope_id=_FAC_REF,
            cqs_short_term=1,
            cqs_long_term=3,
        )
        row = _sa_row(bundle)
        assert row["risk_weight"] == pytest.approx(0.20, abs=1e-6)

    def test_no_short_term_row_falls_back_to_long_term(self) -> None:
        """Without a short-term rating row, the long-term CQS drives the lookup."""
        bundle = _bundle_for(
            maturity_date=date(2029, 1, 1),  # 2 years — long-term
            rating_is_short_term=False,
            scope_type=None,
            scope_id=None,
            cqs_long_term=3,
        )
        row = _sa_row(bundle)
        # Long-term institution CQS 3 ECRA = 50%.
        assert row["risk_weight"] == pytest.approx(0.50, abs=1e-6)

    def test_scope_id_mismatch_does_not_override(self) -> None:
        """A short-term rating attached to a different facility must not override."""
        bundle = _bundle_for(
            maturity_date=date(2029, 1, 1),
            rating_is_short_term=True,
            scope_type="facility",
            scope_id="OTHER_FACILITY",  # not _FAC_REF
            cqs_short_term=1,
            cqs_long_term=3,
        )
        row = _sa_row(bundle)
        # No override — long-term CQS 3 ECRA = 50%.
        assert row["risk_weight"] == pytest.approx(0.50, abs=1e-6)


class TestRatingsSchemaContract:
    """The new short-term rating columns must be declared on RATINGS_SCHEMA."""

    @pytest.mark.parametrize(
        ("col", "dtype"),
        [
            ("is_short_term", pl.Boolean),
            ("scope_type", pl.String),
            ("scope_id", pl.String),
        ],
    )
    def test_column_declared(self, col: str, dtype: pl.DataType) -> None:
        assert col in RATINGS_SCHEMA, f"{col} missing from RATINGS_SCHEMA"
        spec = RATINGS_SCHEMA[col]
        assert spec.dtype == dtype
        assert spec.required is False

    def test_has_short_term_ecai_removed_from_facility_schema(self) -> None:
        """The retired facility flag must no longer appear on FACILITY_SCHEMA."""
        assert "has_short_term_ecai" not in FACILITY_SCHEMA
