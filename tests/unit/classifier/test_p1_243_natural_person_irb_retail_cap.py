"""Unit tests for P1.243: the IRB retail monetary cap is an SME-limb-only condition.

CRR Art. 147(5)(a) and PS1/26 Art. 147(5)(a) admit an exposure to the IRB retail
exposure class when it is either:
    (i)  an exposure to one or more natural persons — NO monetary cap; or
    (ii) an exposure to an SME, provided the total amount owed (excluding
         residential-property-secured exposures) does not exceed EUR 1,000,000
         (CRR) / GBP 880,000 (PS1/26).

The engine previously applied the aggregate-owed threshold to EVERY row via
``qualifies_as_retail`` and reclassified any RETAIL_OTHER row that failed it —
including natural persons — to CORPORATE, expelling large-borrowing individuals
from the retail IRB class. The fix bypasses the threshold for natural persons in
the IRB exposure class only; the SA regulatory-retail flag ``qualifies_as_retail``
(CRR Art. 123 / PS1/26 Art. 123A — a separate rule that DOES cap natural persons)
is left untouched.

Scope assertions (both regimes):
- Natural person, aggregate 2,000,000 > cap -> exposure_class_irb == retail_other
  and the row routes to A-IRB with the retail class, while the SA regulatory-retail
  flag stays False (SA class untouched).
- SME, aggregate 2,000,000 > cap -> stays corporate_sme under IRB (cap binds the
  SME limb).
- Natural person, aggregate 500,000 <= cap -> retail_other (control; the bypass
  does not change the under-cap outcome).

References:
- CRR Art. 147(5)(a)(i)/(ii); PRA PS1/26 Art. 147(5)(a)(i)/(ii).
- CRR Art. 123 / PS1/26 Art. 123A: the SA regulatory-retail cap (untouched).
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType, ExposureClass
from rwa_calc.engine.classifier import ExposureClassifier
from tests.fixtures.p1_243.p1_243 import (
    LOAN_NATURAL_PERSON,
    LOAN_SME,
    make_natural_person_over_cap_bundle,
    make_natural_person_under_cap_bundle,
    make_sme_over_cap_bundle,
)


@pytest.fixture
def classifier() -> ExposureClassifier:
    return ExposureClassifier()


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2026, 12, 31))


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


def _row(classifier: ExposureClassifier, config: CalculationConfig, bundle, ref: str) -> dict:
    result = classifier.classify(bundle, config)
    df = result.all_exposures.filter(pl.col("exposure_reference") == ref).collect()
    assert len(df) == 1, f"expected 1 row for {ref!r}, got {len(df)}"
    return df.to_dicts()[0]


# =============================================================================
# (A) Natural person over the cap -> IRB retail; SA regulatory-retail untouched
# =============================================================================


class TestNaturalPersonOverCapStaysIRBRetail:
    """Art. 147(5)(a)(i): a natural person carries no amount cap in IRB retail."""

    def test_crr_natural_person_over_cap_irb_class_is_retail(
        self, classifier: ExposureClassifier, crr_config: CalculationConfig
    ) -> None:
        row = _row(
            classifier, crr_config, make_natural_person_over_cap_bundle(), LOAN_NATURAL_PERSON
        )
        assert row["exposure_class_irb"] == ExposureClass.RETAIL_OTHER.value

    def test_b31_natural_person_over_cap_irb_class_is_retail(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        row = _row(
            classifier, b31_config, make_natural_person_over_cap_bundle(), LOAN_NATURAL_PERSON
        )
        assert row["exposure_class_irb"] == ExposureClass.RETAIL_OTHER.value

    def test_crr_natural_person_over_cap_routes_to_airb_retail(
        self, classifier: ExposureClassifier, crr_config: CalculationConfig
    ) -> None:
        """The IRB calculator reads exposure_class (post-align) -> must be retail."""
        row = _row(
            classifier, crr_config, make_natural_person_over_cap_bundle(), LOAN_NATURAL_PERSON
        )
        assert row["approach"] == ApproachType.AIRB.value
        assert row["exposure_class"] == ExposureClass.RETAIL_OTHER.value

    def test_b31_natural_person_over_cap_routes_to_airb_retail(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        row = _row(
            classifier, b31_config, make_natural_person_over_cap_bundle(), LOAN_NATURAL_PERSON
        )
        assert row["approach"] == ApproachType.AIRB.value
        assert row["exposure_class"] == ExposureClass.RETAIL_OTHER.value

    def test_crr_sa_regulatory_retail_flag_still_false(
        self, classifier: ExposureClassifier, crr_config: CalculationConfig
    ) -> None:
        """SA/IRB separation: the SA regulatory-retail flag (Art. 123) is untouched."""
        row = _row(
            classifier, crr_config, make_natural_person_over_cap_bundle(), LOAN_NATURAL_PERSON
        )
        assert row["qualifies_as_retail"] is False

    def test_b31_sa_regulatory_retail_flag_still_false(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        row = _row(
            classifier, b31_config, make_natural_person_over_cap_bundle(), LOAN_NATURAL_PERSON
        )
        assert row["qualifies_as_retail"] is False


# =============================================================================
# (B) SME over the cap -> stays corporate under IRB (cap binds the SME limb)
# =============================================================================


class TestSMEOverCapStaysCorporate:
    """Art. 147(5)(a)(ii): the monetary cap conditions the SME limb only."""

    def test_crr_sme_over_cap_irb_class_is_corporate_sme(
        self, classifier: ExposureClassifier, crr_config: CalculationConfig
    ) -> None:
        row = _row(classifier, crr_config, make_sme_over_cap_bundle(), LOAN_SME)
        assert row["exposure_class_irb"] == ExposureClass.CORPORATE_SME.value

    def test_b31_sme_over_cap_irb_class_is_corporate_sme(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        row = _row(classifier, b31_config, make_sme_over_cap_bundle(), LOAN_SME)
        assert row["exposure_class_irb"] == ExposureClass.CORPORATE_SME.value


# =============================================================================
# (C) Natural person under the cap -> IRB retail (control; unchanged)
# =============================================================================


class TestNaturalPersonUnderCapControl:
    """The bypass must not change the under-cap outcome (already retail)."""

    def test_crr_natural_person_under_cap_irb_class_is_retail(
        self, classifier: ExposureClassifier, crr_config: CalculationConfig
    ) -> None:
        row = _row(
            classifier, crr_config, make_natural_person_under_cap_bundle(), LOAN_NATURAL_PERSON
        )
        assert row["exposure_class_irb"] == ExposureClass.RETAIL_OTHER.value

    def test_b31_natural_person_under_cap_irb_class_is_retail(
        self, classifier: ExposureClassifier, b31_config: CalculationConfig
    ) -> None:
        row = _row(
            classifier, b31_config, make_natural_person_under_cap_bundle(), LOAN_NATURAL_PERSON
        )
        assert row["exposure_class_irb"] == ExposureClass.RETAIL_OTHER.value
