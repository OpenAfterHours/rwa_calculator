"""
P1.245 unit tests — Art. 147(4C)(b)(ii) group-consolidation revenue roll-up.

The financial/large-corporates F-IRB-only subclass (Art. 147A(1)(e)) captures a
corporate whose annual revenue exceeds GBP 440m "taken at the highest level of
consolidation which is performed". The classifier therefore rolls the
counterparty's own turnover up its ultimate-parent chain
(``attributes.with_group_annual_revenue``) before the large-corp test:

    sub own 50m  under 500m parent  -> B31 F-IRB (roll-up flip), CRR A-IRB
    sub own null under 500m parent  -> B31 F-IRB (parent resolves size)
    sub own 50m  under 50m  parent  -> B31 A-IRB (small group)
    standalone own 500m (no parent) -> B31 F-IRB (own large, unchanged)
    standalone own 50m  (no parent) -> B31 A-IRB (unchanged)

CLS011 records a roll-up-driven flip; CLS008 (null revenue conservatism) is
keyed on the rolled-up group figure, so a null-own subsidiary under a
revenue-bearing parent no longer trips it.

References:
- PRA PS1/26 Art. 147(4C)(b)(ii) / Art. 147A(1)(e); P1.245.
- tests/unit/test_b31_approach_restrictions.py: the standalone large-corp branch.
"""

from __future__ import annotations

from datetime import date

import pytest

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.classifier import ExposureClassifier
from tests.fixtures.p1_245.p1_245 import (
    BIG_GROUP_REVENUE,
    CP_PARENT_BIG,
    SMALL_GROUP_REVENUE,
    SUB_OWN_REVENUE,
    make_classify_bundle,
)

_B31_DATE = date(2027, 6, 30)
_CRR_DATE = date(2026, 12, 31)


@pytest.fixture
def classifier() -> ExposureClassifier:
    return ExposureClassifier()


def _b31() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=_B31_DATE, permission_mode=PermissionMode.IRB)


def _crr() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=_CRR_DATE, permission_mode=PermissionMode.IRB)


def _approach(classifier: ExposureClassifier, bundle, config: CalculationConfig) -> str:
    df = classifier.classify(bundle, config).all_exposures.collect()
    assert len(df) == 1
    return df["approach"][0]


# =============================================================================
# B31: the roll-up forces F-IRB
# =============================================================================


class TestB31RollUpForcesFIRB:
    def test_small_sub_under_large_group_gets_firb(self, classifier: ExposureClassifier) -> None:
        """Own 50m under a 500m group -> F-IRB (the core P1.245 flip)."""
        bundle = make_classify_bundle(sub_revenue=SUB_OWN_REVENUE, parent_revenue=BIG_GROUP_REVENUE)
        assert _approach(classifier, bundle, _b31()) == ApproachType.FIRB.value

    def test_null_own_revenue_under_large_group_gets_firb(
        self, classifier: ExposureClassifier
    ) -> None:
        """Null own revenue under a 500m parent -> F-IRB (parent resolves size)."""
        bundle = make_classify_bundle(sub_revenue=None, parent_revenue=BIG_GROUP_REVENUE)
        assert _approach(classifier, bundle, _b31()) == ApproachType.FIRB.value

    def test_firb_flip_clears_lgd_to_supervisory(self, classifier: ExposureClassifier) -> None:
        """A roll-up F-IRB flip clears the modelled LGD (supervisory LGD applies)."""
        bundle = make_classify_bundle(sub_revenue=SUB_OWN_REVENUE, parent_revenue=BIG_GROUP_REVENUE)
        df = classifier.classify(bundle, _b31()).all_exposures.collect()
        assert df["lgd"][0] is None


# =============================================================================
# B31: the roll-up does NOT over-reach
# =============================================================================


class TestB31RollUpDoesNotOverReach:
    def test_small_sub_under_small_group_stays_airb(self, classifier: ExposureClassifier) -> None:
        """Own 50m under a 50m group -> A-IRB (group below the threshold)."""
        bundle = make_classify_bundle(
            sub_revenue=SUB_OWN_REVENUE, parent_revenue=SMALL_GROUP_REVENUE
        )
        assert _approach(classifier, bundle, _b31()) == ApproachType.AIRB.value

    def test_standalone_small_corporate_stays_airb(self, classifier: ExposureClassifier) -> None:
        """Own 50m with no parent -> A-IRB (regression guard for the no-parent path)."""
        bundle = make_classify_bundle(
            sub_revenue=SUB_OWN_REVENUE, parent_revenue=None, parent_ref=None
        )
        assert _approach(classifier, bundle, _b31()) == ApproachType.AIRB.value

    def test_standalone_large_corporate_still_firb(self, classifier: ExposureClassifier) -> None:
        """Own 500m with no parent -> F-IRB (own-large branch unchanged)."""
        bundle = make_classify_bundle(
            sub_revenue=BIG_GROUP_REVENUE, parent_revenue=None, parent_ref=None
        )
        assert _approach(classifier, bundle, _b31()) == ApproachType.FIRB.value


# =============================================================================
# CRR control: no subclass exists, so A-IRB stays available
# =============================================================================


class TestCRRHasNoSubclass:
    def test_small_sub_under_large_group_stays_airb_under_crr(
        self, classifier: ExposureClassifier
    ) -> None:
        """The same flip data under CRR -> A-IRB (Art. 147(4C) subclass is B31-only)."""
        bundle = make_classify_bundle(sub_revenue=SUB_OWN_REVENUE, parent_revenue=BIG_GROUP_REVENUE)
        assert _approach(classifier, bundle, _crr()) == ApproachType.AIRB.value

    def test_null_own_under_large_group_stays_airb_under_crr(
        self, classifier: ExposureClassifier
    ) -> None:
        """Null-own under a large group under CRR -> A-IRB (no conservative block)."""
        bundle = make_classify_bundle(sub_revenue=None, parent_revenue=BIG_GROUP_REVENUE)
        assert _approach(classifier, bundle, _crr()) == ApproachType.AIRB.value


# =============================================================================
# CLS011 — roll-up-driven flip warning
# =============================================================================


def _errors(classifier: ExposureClassifier, bundle, config: CalculationConfig):
    return classifier.classify(bundle, config).classification_errors


class TestCLS011RollUpWarning:
    def test_cls011_emitted_on_roll_up_flip(self, classifier: ExposureClassifier) -> None:
        bundle = make_classify_bundle(sub_revenue=SUB_OWN_REVENUE, parent_revenue=BIG_GROUP_REVENUE)
        cls011 = [e for e in _errors(classifier, bundle, _b31()) if e.code == "CLS011"]
        assert len(cls011) == 1

    def test_cls011_emitted_on_null_own_under_large_group(
        self, classifier: ExposureClassifier
    ) -> None:
        bundle = make_classify_bundle(sub_revenue=None, parent_revenue=BIG_GROUP_REVENUE)
        cls011 = [e for e in _errors(classifier, bundle, _b31()) if e.code == "CLS011"]
        assert len(cls011) == 1

    def test_cls011_cites_art_147_4c(self, classifier: ExposureClassifier) -> None:
        bundle = make_classify_bundle(sub_revenue=SUB_OWN_REVENUE, parent_revenue=BIG_GROUP_REVENUE)
        cls011 = [e for e in _errors(classifier, bundle, _b31()) if e.code == "CLS011"]
        assert cls011[0].regulatory_reference == "PRA PS1/26 Art. 147(4C)(b)(ii)"

    def test_no_cls011_for_small_group(self, classifier: ExposureClassifier) -> None:
        bundle = make_classify_bundle(
            sub_revenue=SUB_OWN_REVENUE, parent_revenue=SMALL_GROUP_REVENUE
        )
        cls011 = [e for e in _errors(classifier, bundle, _b31()) if e.code == "CLS011"]
        assert len(cls011) == 0

    def test_no_cls011_for_standalone_large(self, classifier: ExposureClassifier) -> None:
        """Own already > 440m -> not roll-up-driven, so no CLS011."""
        bundle = make_classify_bundle(
            sub_revenue=BIG_GROUP_REVENUE, parent_revenue=None, parent_ref=None
        )
        cls011 = [e for e in _errors(classifier, bundle, _b31()) if e.code == "CLS011"]
        assert len(cls011) == 0

    def test_no_cls011_under_crr(self, classifier: ExposureClassifier) -> None:
        bundle = make_classify_bundle(sub_revenue=SUB_OWN_REVENUE, parent_revenue=BIG_GROUP_REVENUE)
        cls011 = [e for e in _errors(classifier, bundle, _crr()) if e.code == "CLS011"]
        assert len(cls011) == 0


# =============================================================================
# CLS008 — the null-revenue conservatism is now keyed on the GROUP figure
# =============================================================================


class TestCLS008ComposesWithRollUp:
    def test_no_cls008_when_parent_resolves_null_own_revenue(
        self, classifier: ExposureClassifier
    ) -> None:
        """Null own revenue under a revenue-bearing parent is resolved -> no CLS008."""
        bundle = make_classify_bundle(sub_revenue=None, parent_revenue=BIG_GROUP_REVENUE)
        cls008 = [e for e in _errors(classifier, bundle, _b31()) if e.code == "CLS008"]
        assert len(cls008) == 0

    def test_cls008_still_fires_when_group_unresolved(self, classifier: ExposureClassifier) -> None:
        """Null own AND null parent revenue leaves the group figure null -> CLS008 + F-IRB."""
        bundle = make_classify_bundle(
            sub_revenue=None, parent_revenue=None, parent_ref=CP_PARENT_BIG
        )
        result = classifier.classify(bundle, _b31())
        df = result.all_exposures.collect()
        cls008 = [e for e in result.classification_errors if e.code == "CLS008"]
        assert len(cls008) == 1
        assert df["approach"][0] == ApproachType.FIRB.value
