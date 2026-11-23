"""
Unit tests for "Other Items" (Art. 134) risk weights under CRR and Basel 3.1.

Why these tests matter:
    Art. 134 defines risk weights for miscellaneous items not covered by other
    exposure classes. Without explicit handling, all Other Items exposures
    silently default to 100% via the CQS join fallback. This is correct for
    tangible assets (Art. 134(1)) but wrong for:
    - Cash, and gold backed by bullion liabilities: should be 0% (Art. 134(3)/(4))
      — 100% default OVERSTATES
    - Items in collection: should be 20% (Art. 134(3)) — 100% default OVERSTATES
    - Residual lease value: should be 1/t × 100% (Art. 134(7)) — can differ

    The entity_type sub-values (other_cash, other_gold, other_gold_unbacked,
    other_items_in_collection, other_tangible, other_residual_lease) drive
    sub-type routing in the SA calculator.

Other Items treatment is identical under CRR and PRA PS1/26 Basel 3.1:
    - Cash and equivalent: 0% (Art. 134(3))
    - Gold bullion held in own vaults or on an allocated basis, ONLY to the
      extent backed by bullion liabilities: 0% (Art. 134(4)). The 0% is not
      unconditional: the unbacked share is booked as a separate
      ``other_gold_unbacked`` row and takes 100%, because Arts. 114-134 provide
      no calculation for it (Art. 113(5)). See TestGoldBullionBackingSplit.
    - Items in course of collection: 20% (Art. 134(3))
    - Tangible assets, prepaid expenses: 100% (Art. 134(1))
    - Residual value of leased assets: 1/t × 100% where t ≥ 1 (Art. 134(7))
    - All other: 100% (Art. 134(2); Art. 113(5) for anything Arts. 114-134 do not price)

NOT COVERED HERE, and not implemented anywhere — stated explicitly because the
earlier silence is what made the gap invisible (this docstring enumerated
(1),(2),(3),(4),(7) and simply omitted the rest):
    - Art. 134(5) repo-style transactions — risk weight of the underlying asset
    - Art. 134(6) sold nth-to-default basket protection. No input field can
      express it, so there is no data-quality error either. See the scope
      exclusion in docs/specifications/crr/sa-risk-weights.md, which also names
      the IRB sibling (CRR/PS1/26 Art. 153(8)) and the classification limb
      (CRR Art. 147(10) / PS1/26 Art. 147(9)).

References:
    - CRR Art. 134 / PRA PS1/26 Art. 134: Other items risk weights
    - CRR Art. 112(q): Other items exposure class
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ERROR_INVALID_COLUMN_VALUE
from rwa_calc.data.schemas import VALID_ENTITY_TYPES
from rwa_calc.domain.enums import ExposureClass
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.engine.sa import SACalculator
from rwa_calc.engine.sa import risk_weights as sa_risk_weights
from rwa_calc.rulebook.compile import scalar_value
from rwa_calc.rulebook.resolve import resolve
from tests.fixtures.raw_bundle import make_raw_bundle
from tests.fixtures.single_exposure import calculate_single_sa_exposure

# Other-items SA risk weights (CRR Art. 134) now live in the common rulepack
# pack; the value pins below read them back so there is one source of truth.
_PACK = resolve("crr", date(2026, 1, 1))
OTHER_ITEMS_CASH_RW = _PACK.scalar_param("other_items_cash_rw").value
OTHER_ITEMS_COLLECTION_RW = _PACK.scalar_param("other_items_collection_rw").value
OTHER_ITEMS_DEFAULT_RW = _PACK.scalar_param("other_items_default_rw").value
OTHER_ITEMS_GOLD_RW = _PACK.scalar_param("other_items_gold_rw").value
OTHER_ITEMS_TANGIBLE_RW = _PACK.scalar_param("other_items_tangible_rw").value

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def sa_calculator() -> SACalculator:
    return SACalculator()


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2024, 12, 31))


# =============================================================================
# DATA TABLE TESTS
# =============================================================================


class TestOtherItemsRiskWeightConstants:
    """Tests for Art. 134 risk weight constants."""

    def test_cash_rw_zero(self):
        """Art. 134(3): Cash and equivalent → 0%."""
        assert Decimal("0.00") == OTHER_ITEMS_CASH_RW

    def test_gold_rw_zero(self):
        """Art. 134(4): gold bullion, to the extent backed by bullion liabilities → 0%."""
        assert Decimal("0.00") == OTHER_ITEMS_GOLD_RW

    def test_collection_rw_twenty(self):
        """Art. 134(3): Items in course of collection → 20%."""
        assert Decimal("0.20") == OTHER_ITEMS_COLLECTION_RW

    def test_tangible_rw_hundred(self):
        """Art. 134(1): Tangible assets → 100%."""
        assert Decimal("1.00") == OTHER_ITEMS_TANGIBLE_RW

    def test_default_rw_hundred(self):
        """Art. 134(2): All other items → 100%."""
        assert Decimal("1.00") == OTHER_ITEMS_DEFAULT_RW


# =============================================================================
# CRR SA CALCULATOR TESTS
# =============================================================================


class TestCRROtherItemsRiskWeights:
    """Tests for Other Items risk weights through the CRR SA calculator."""

    def test_cash_zero_percent(self, sa_calculator, crr_config):
        """CRR Art. 134(3): Cash and equivalent → 0% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="other",
            config=crr_config,
            entity_type="other_cash",
        )
        assert result["risk_weight"] == pytest.approx(0.0)
        assert result["rwa"] == pytest.approx(0.0)

    def test_gold_zero_percent(self, sa_calculator, crr_config):
        """CRR Art. 134(4): ``other_gold`` (the backed share only) → 0% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("3000000"),
            exposure_class="other",
            config=crr_config,
            entity_type="other_gold",
        )
        assert result["risk_weight"] == pytest.approx(0.0)
        assert result["rwa"] == pytest.approx(0.0)

    def test_unbacked_gold_hundred_percent(self, sa_calculator, crr_config):
        """CRR Art. 113(5): ``other_gold_unbacked`` (gold not backed) → 100% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("2000000"),
            exposure_class="other",
            config=crr_config,
            entity_type="other_gold_unbacked",
        )
        assert result["risk_weight"] == pytest.approx(1.0)
        assert result["rwa"] == pytest.approx(2000000.0)

    def test_items_in_collection_twenty_percent(self, sa_calculator, crr_config):
        """CRR Art. 134(3): Items in course of collection → 20% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("2000000"),
            exposure_class="other",
            config=crr_config,
            entity_type="other_items_in_collection",
        )
        assert result["risk_weight"] == pytest.approx(0.20)
        assert result["rwa"] == pytest.approx(400000.0)

    def test_tangible_hundred_percent(self, sa_calculator, crr_config):
        """CRR Art. 134(1): Tangible assets → 100% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="other",
            config=crr_config,
            entity_type="other_tangible",
        )
        assert result["risk_weight"] == pytest.approx(1.0)
        assert result["rwa"] == pytest.approx(1000000.0)

    def test_residual_lease_five_years(self, sa_calculator, crr_config):
        """CRR Art. 134(7): Residual lease value, t=5 years → 1/5 = 20% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="other",
            config=crr_config,
            entity_type="other_residual_lease",
            residual_maturity_years=5.0,
        )
        assert result["risk_weight"] == pytest.approx(0.20)
        assert result["rwa"] == pytest.approx(200000.0)

    def test_residual_lease_one_year(self, sa_calculator, crr_config):
        """CRR Art. 134(7): Residual lease value, t=1 year → 1/1 = 100% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="other",
            config=crr_config,
            entity_type="other_residual_lease",
            residual_maturity_years=1.0,
        )
        assert result["risk_weight"] == pytest.approx(1.0)

    def test_residual_lease_two_point_five_years(self, sa_calculator, crr_config):
        """CRR Art. 134(7): t=2.5 years rounds to 2 whole years → 1/2 = 50% RW.

        Inverted by P1.289. This asserted 1/2.5 = 40%, i.e. it codified the
        fractional divisor as the rule. Art. 134(7) says ``t`` is "the greater
        of 1 and the **nearest number of whole years** of the lease remaining",
        so 2.5 resolves to a whole-year count, not to 2.5.

        2.5 is the tie case: neither 2 nor 3 is nearest, and the article does
        not say which to take. It is resolved toward the higher risk weight,
        so t=2 and RW=50% rather than t=3 and RW=33.3%.
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="other",
            config=crr_config,
            entity_type="other_residual_lease",
            residual_maturity_years=2.5,
        )
        assert result["risk_weight"] == pytest.approx(0.50)

    @pytest.mark.parametrize(
        ("years_remaining", "expected_rw"),
        [
            (1.49, 1.0),  # rounds to 1 — the worst case, 32.9pp understated before
            (1.6, 0.50),  # rounds to 2
            (2.4, 0.50),  # rounds down to 2
            (2.6, 1.0 / 3.0),  # rounds up to 3 — the over-statement direction
            (4.7, 0.20),  # rounds to 5
        ],
    )
    def test_p1_289_residual_lease_divides_by_whole_years(
        self, sa_calculator, crr_config, years_remaining, expected_rw
    ):
        """Art. 134(7) divides by whole years, so the weight is a step function.

        Arrange: a leased-asset residual with a fractional number of years left.
        Act: risk-weight it under CRR.
        Assert: ``1/t`` with ``t`` the nearest whole year, floored at 1.

        Before P1.289 the engine divided by the raw fraction, which errs in
        **both** directions — 1.49 years returned 0.671 against a required 1.00
        (a 32.9pp understatement) while 2.6 returned 0.385 against 0.333. The
        cases below straddle three rounding boundaries so a fix that truncates,
        or that always rounds up, fails on at least one of them: truncation
        breaks 1.6 and 2.6, always-up breaks 1.49 and 2.4.

        PS1/26 Art. 134(7) is word-for-word identical and carries a note that
        it corresponds to CRR Art. 134, so no regime split applies — unlike
        Art. 120, where the two frameworks genuinely differ on maturity basis.
        """
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="other",
            config=crr_config,
            entity_type="other_residual_lease",
            residual_maturity_years=years_remaining,
        )
        assert result["risk_weight"] == pytest.approx(expected_rw), (
            f"P1.289: {years_remaining} years remaining must divide by the nearest "
            f"whole year, not the fraction. Got {result['risk_weight']}."
        )

    def test_residual_lease_sub_one_year_floors_to_one(self, sa_calculator, crr_config):
        """CRR Art. 134(7): Residual lease t < 1 year floors to 1 → 100% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="other",
            config=crr_config,
            entity_type="other_residual_lease",
            residual_maturity_years=0.5,
        )
        assert result["risk_weight"] == pytest.approx(1.0)

    def test_residual_lease_null_maturity_defaults_to_hundred(self, sa_calculator, crr_config):
        """CRR Art. 134(7): Residual lease with null maturity → 100% (conservative)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="other",
            config=crr_config,
            entity_type="other_residual_lease",
        )
        assert result["risk_weight"] == pytest.approx(1.0)

    def test_generic_other_hundred_percent(self, sa_calculator, crr_config):
        """CRR Art. 134(2): Generic 'other' with no entity_type → 100% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="other",
            config=crr_config,
        )
        assert result["risk_weight"] == pytest.approx(1.0)


# =============================================================================
# BASEL 3.1 SA CALCULATOR TESTS
# =============================================================================


class TestB31OtherItemsRiskWeights:
    """Tests for Other Items risk weights through the Basel 3.1 SA calculator.

    Other Items treatment is unchanged between CRR and Basel 3.1 (Art. 134
    is not modified by PRA PS1/26). These tests confirm identical behaviour.
    """

    def test_cash_zero_percent(self, sa_calculator, b31_config):
        """B31 Art. 134(3): Cash and equivalent → 0% RW (unchanged from CRR)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("5000000"),
            exposure_class="other",
            config=b31_config,
            entity_type="other_cash",
        )
        assert result["risk_weight"] == pytest.approx(0.0)
        assert result["rwa"] == pytest.approx(0.0)

    def test_gold_zero_percent(self, sa_calculator, b31_config):
        """B31 Art. 134(4): ``other_gold`` (the backed share only) → 0% RW (as CRR)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("3000000"),
            exposure_class="other",
            config=b31_config,
            entity_type="other_gold",
        )
        assert result["risk_weight"] == pytest.approx(0.0)

    def test_unbacked_gold_hundred_percent(self, sa_calculator, b31_config):
        """B31 Art. 113(5): ``other_gold_unbacked`` (gold not backed) → 100% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("2000000"),
            exposure_class="other",
            config=b31_config,
            entity_type="other_gold_unbacked",
        )
        assert result["risk_weight"] == pytest.approx(1.0)
        assert result["rwa"] == pytest.approx(2000000.0)

    def test_items_in_collection_twenty_percent(self, sa_calculator, b31_config):
        """B31 Art. 134(3): Items in course of collection → 20% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("2000000"),
            exposure_class="other",
            config=b31_config,
            entity_type="other_items_in_collection",
        )
        assert result["risk_weight"] == pytest.approx(0.20)
        assert result["rwa"] == pytest.approx(400000.0)

    def test_tangible_hundred_percent(self, sa_calculator, b31_config):
        """B31 Art. 134(1): Tangible assets → 100% RW (unchanged from CRR)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="other",
            config=b31_config,
            entity_type="other_tangible",
        )
        assert result["risk_weight"] == pytest.approx(1.0)

    def test_residual_lease_five_years(self, sa_calculator, b31_config):
        """B31 Art. 134(7): Residual lease value, t=5 years → 20% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="other",
            config=b31_config,
            entity_type="other_residual_lease",
            residual_maturity_years=5.0,
        )
        assert result["risk_weight"] == pytest.approx(0.20)

    def test_residual_lease_ten_years(self, sa_calculator, b31_config):
        """B31 Art. 134(7): Residual lease value, t=10 years → 10% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="other",
            config=b31_config,
            entity_type="other_residual_lease",
            residual_maturity_years=10.0,
        )
        assert result["risk_weight"] == pytest.approx(0.10)

    def test_residual_lease_sub_one_year_floors(self, sa_calculator, b31_config):
        """B31 Art. 134(7): Residual lease t < 1yr floors to t=1 → 100% RW."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="other",
            config=b31_config,
            entity_type="other_residual_lease",
            residual_maturity_years=0.25,
        )
        assert result["risk_weight"] == pytest.approx(1.0)

    def test_generic_other_hundred_percent(self, sa_calculator, b31_config):
        """B31 Art. 134(2): Generic OTHER → 100% RW (unchanged from CRR)."""
        result = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("1000000"),
            exposure_class="other",
            config=b31_config,
        )
        assert result["risk_weight"] == pytest.approx(1.0)


# =============================================================================
# P1.288 — THE ART. 134(4) 0% IS "TO THE EXTENT BACKED BY BULLION LIABILITIES"
# =============================================================================

_REGIMES = ("crr", "b31")
_REGIME_PACK_DATE = {"crr": date(2026, 1, 1), "b31": date(2027, 1, 1)}

# One GBP 5,000,000 bullion holding, split at the backing line. The two legs
# carry DIFFERENT money so a swapped or uniform weight is detectable: both at
# 0% gives 0, both at 100% gives 5,000,000, swapped gives 3,000,000 — only the
# correct split gives 2,000,000.
_BACKED_GOLD_EAD = 3_000_000.0
_UNBACKED_GOLD_EAD = 2_000_000.0
_BACKED_GOLD_REF = "P1288-LN-GOLD-BACKED"
_UNBACKED_GOLD_REF = "P1288-LN-GOLD-UNBACKED"


def _regime_config(regime: str) -> CalculationConfig:
    """The ``CalculationConfig`` for one regime, through its factory."""
    if regime == "crr":
        return CalculationConfig.crr(reporting_date=date(2026, 6, 30))
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


def _gold_holding_bundle() -> RawDataBundle:
    """A bullion holding booked as two rows: the backed share and the rest.

    ``entity_type`` is a counterparty attribute, so each share carries its own
    pseudo-counterparty — the same convention the other Art. 134 sub-types use.
    """
    counterparties = pl.DataFrame(
        {
            "counterparty_reference": ["P1288-CP-GOLD-BACKED", "P1288-CP-GOLD-UNBACKED"],
            "counterparty_name": ["Bullion backed by bullion liabilities", "Unbacked bullion"],
            "entity_type": ["other_gold", "other_gold_unbacked"],
            "country_code": ["GB", "GB"],
            "default_status": [False, False],
        }
    )
    loans = pl.DataFrame(
        {
            "loan_reference": [_BACKED_GOLD_REF, _UNBACKED_GOLD_REF],
            "counterparty_reference": ["P1288-CP-GOLD-BACKED", "P1288-CP-GOLD-UNBACKED"],
            "currency": ["GBP", "GBP"],
            "value_date": [date(2025, 1, 1), date(2025, 1, 1)],
            "maturity_date": [date(2030, 1, 1), date(2030, 1, 1)],
            "drawn_amount": [_BACKED_GOLD_EAD, _UNBACKED_GOLD_EAD],
            "interest": [0.0, 0.0],
            "seniority": ["senior", "senior"],
        }
    )
    return make_raw_bundle(counterparties=counterparties, loans=loans)


class TestGoldBullionBackingSplit:
    """P1.288: only the share of a bullion holding backed by bullion liabilities is 0%.

    Verbatim, identical in both regimes — PS1/26 Art. 134(4) (ps126app1.pdf
    p.68, "[Note: This rule corresponds to Article 134 of CRR ...]") and CRR
    Art. 134(4): "Gold bullion held in own vaults or on an allocated basis to
    the extent backed by bullion liabilities shall be assigned a 0% risk
    weight." Arts. 114-134 provide no calculation for the unbacked share, so it
    takes the Art. 113(5) 100% (CRR and PS1/26 alike). The IRB twin, PS1/26
    Art. 156(1)(a) / CRR Art. 156(a), states the same condition and 100%
    otherwise, so the two approaches agree on gold.

    Before P1.288 the 0% was described as unconditional and the input contract
    had no value for the unbacked share: ``other_gold_unbacked`` raised DQ006
    (invalid entity_type) and was classified only by the classifier's
    unknown-type fallback. The backing condition is read as binding BOTH the
    own-vaults and the allocated limb — the conservative reading, and the one
    ``docs/data-model/input-schemas.md`` already stated.
    """

    @pytest.mark.parametrize("regime", _REGIMES)
    def test_unbacked_gold_is_a_declared_other_items_entity_type(self, regime):
        """``other_gold_unbacked`` is accepted and mapped to OTHER in both class maps."""
        # Arrange
        pack = resolve(regime, _REGIME_PACK_DATE[regime])

        # Act
        sa_class = pack.category_map("entity_type_to_sa_class").entries.get("other_gold_unbacked")
        irb_class = pack.category_map("entity_type_to_irb_class").entries.get("other_gold_unbacked")

        # Assert
        assert "other_gold_unbacked" in VALID_ENTITY_TYPES
        assert (sa_class, irb_class) == (ExposureClass.OTHER.value, ExposureClass.OTHER.value)

    @pytest.mark.parametrize("regime", _REGIMES)
    def test_backed_and_unbacked_gold_split_through_the_pipeline(self, regime):
        """A 5,000,000 holding, 3,000,000 backed: RWA 2,000,000 and no DQ006."""
        # Arrange
        assert _BACKED_GOLD_EAD != _UNBACKED_GOLD_EAD, (
            "equal legs cannot tell a swapped weight from a correct split"
        )
        bundle = _gold_holding_bundle()

        # Act
        result = PipelineOrchestrator().run_with_data(bundle, _regime_config(regime))
        rows = {r["exposure_reference"]: r for r in result.results.collect().to_dicts()}
        entity_type_findings = [
            e
            for e in result.errors
            if e.code == ERROR_INVALID_COLUMN_VALUE and e.field_name == "entity_type"
        ]

        # Assert
        assert entity_type_findings == [], [str(e.message) for e in entity_type_findings]
        backed, unbacked = rows[_BACKED_GOLD_REF], rows[_UNBACKED_GOLD_REF]
        assert (backed["exposure_class"], unbacked["exposure_class"]) == ("other", "other")
        assert backed["risk_weight"] == pytest.approx(0.0)
        assert unbacked["risk_weight"] == pytest.approx(1.0)
        assert backed["rwa_final"] + unbacked["rwa_final"] == pytest.approx(_UNBACKED_GOLD_EAD)

    @pytest.mark.parametrize("regime", _REGIMES)
    def test_gold_branch_reads_the_cited_gold_scalar(self, regime, sa_calculator, monkeypatch):
        """``other_gold`` is weighted by ``other_items_gold_rw``, not the cash scalar.

        Both are 0%, so before P1.288 nothing showed that the gold branch read
        ``other_items_cash_rw`` and left the cited Art. 134(4) entry dead.
        Moving only the gold key must move only the gold row.
        """
        # Arrange
        pack_gold_rw = scalar_value(
            resolve(regime, _REGIME_PACK_DATE[regime]).scalar_param("other_items_gold_rw")
        )
        wired_gold_rw = sa_risk_weights._SA_SHARED_RW.get("other_gold")
        monkeypatch.setitem(sa_risk_weights._SA_SHARED_RW, "other_gold", 0.5)
        config = _regime_config(regime)

        # Act
        gold = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("3000000"),
            exposure_class="other",
            config=config,
            entity_type="other_gold",
        )
        cash = calculate_single_sa_exposure(
            sa_calculator,
            ead=Decimal("3000000"),
            exposure_class="other",
            config=config,
            entity_type="other_cash",
        )

        # Assert — the gold row follows its own key, cash does not, and the key
        # holds the cited Art. 134(4) pack value when nothing patches it
        assert gold["risk_weight"] == pytest.approx(0.5)
        assert cash["risk_weight"] == pytest.approx(0.0)
        assert wired_gold_rw == pack_gold_rw
