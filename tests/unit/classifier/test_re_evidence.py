"""
Unit tests: ``engine/classify/re_evidence.py`` (review CL-08).

Pipeline position:
    HierarchyResolver -> ExposureClassifier (subtypes -> approach ->
    withhold_unevidenced_re_class) -> CRMProcessor

Key responsibilities pinned here:
- ``re_evidence_expr``: a valued property (direct or allocated), a facility /
  counterparty pledge allocated nothing, or an LTV is evidence; nothing else is.
- ``withhold_unevidenced_re_class``: only a Standardised-Approach row takes its
  recorded non-mortgage class; an IRB row keeps its IRB retail-mortgage class.
- ``classify_exposure_subtypes`` records the fallback only where the mortgage
  class rests on the product label alone.

Rule text (verbatim): PS1/26 Glossary — "real estate exposure means an ADC
exposure or an exposure secured by a charge on immovable property"; CRR
Art. 125(1) — "exposures fully and completely secured by mortgages on
residential property shall be treated as follows".

References:
- PS1/26 Glossary, Art. 124A(1)(a); CRR Art. 125(1)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType, ExposureClass
from rwa_calc.engine.classify.re_evidence import (
    RE_UNEVIDENCED_CLASS_COLUMN,
    re_evidence_expr,
    withhold_unevidenced_re_class,
)
from rwa_calc.engine.classify.subtypes import classify_exposure_subtypes
from tests.fixtures.p1_244.p1_244 import make_subtypes_frame


@pytest.mark.parametrize(
    ("property_value", "facility_pledge", "ltv", "expected"),
    [
        (0.0, False, None, False),  # a mortgage label and nothing else
        (100_000.0, False, None, True),  # a valued property linked directly
        (0.0, True, None, True),  # a facility pledge allocated nothing (undrawn row)
        (0.0, False, 0.6, True),  # an LTV, supplied or derived
    ],
)
def test_re_evidence_truth_table(
    property_value: float, facility_pledge: bool, ltv: float | None, expected: bool
) -> None:
    # Arrange
    frame = pl.DataFrame(
        {
            "property_collateral_value": [property_value],
            "has_facility_property_collateral": [facility_pledge],
            "ltv": [ltv],
        },
        schema_overrides={"ltv": pl.Float64},
    )

    # Act
    result = frame.select(re_evidence_expr().alias("evidence")).item()

    # Assert
    assert result is expected


@pytest.mark.parametrize(
    ("approach", "expected_class"),
    [
        (ApproachType.SA.value, ExposureClass.RETAIL_OTHER.value),
        # The IRB retail-mortgage class carries its own correlation and LGD
        # floors; re-classing it is not this change's question.
        (ApproachType.AIRB.value, ExposureClass.RETAIL_MORTGAGE.value),
        (ApproachType.FIRB.value, ExposureClass.RETAIL_MORTGAGE.value),
    ],
)
def test_only_standardised_rows_are_withheld(approach: str, expected_class: str) -> None:
    # Arrange
    frame = pl.LazyFrame(
        {
            "exposure_class": [ExposureClass.RETAIL_MORTGAGE.value],
            "approach": [approach],
            RE_UNEVIDENCED_CLASS_COLUMN: [ExposureClass.RETAIL_OTHER.value],
        }
    )

    # Act
    result = withhold_unevidenced_re_class(frame).collect()

    # Assert
    assert result["exposure_class"].item() == expected_class


def test_evidenced_standardised_mortgage_is_untouched() -> None:
    frame = pl.LazyFrame(
        {
            "exposure_class": [ExposureClass.RETAIL_MORTGAGE.value],
            "approach": [ApproachType.SA.value],
            RE_UNEVIDENCED_CLASS_COLUMN: [None],
        },
        schema_overrides={RE_UNEVIDENCED_CLASS_COLUMN: pl.String},
    )
    result = withhold_unevidenced_re_class(frame).collect()
    assert result["exposure_class"].item() == ExposureClass.RETAIL_MORTGAGE.value


class TestSubtypesRecordTheFallback:
    """``classify_exposure_subtypes`` sets the scratch only for label-only mortgages."""

    @staticmethod
    def _classify(**overrides: object) -> dict:
        frame = make_subtypes_frame(cp_entity_type="individual", cp_is_natural_person=True)
        frame = frame.with_columns(
            pl.lit(True).alias("is_mortgage"),
            pl.lit(False).alias("is_revolving"),
            *[pl.lit(value).alias(name) for name, value in overrides.items()],
        )
        config = CalculationConfig.crr(reporting_date=date(2026, 12, 31))
        return classify_exposure_subtypes(frame, config).collect().row(0, named=True)

    def test_label_only_mortgage_records_retail_other(self) -> None:
        row = self._classify()
        assert row["exposure_class"] == ExposureClass.RETAIL_MORTGAGE.value
        assert row[RE_UNEVIDENCED_CLASS_COLUMN] == ExposureClass.RETAIL_OTHER.value

    def test_mortgage_with_property_records_nothing(self) -> None:
        row = self._classify(property_collateral_value=150_000.0)
        assert row["exposure_class"] == ExposureClass.RETAIL_MORTGAGE.value
        assert row[RE_UNEVIDENCED_CLASS_COLUMN] is None
