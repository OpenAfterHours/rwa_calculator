"""
Unit pins — P1.277: CRR Art. 160(1) does not floor central-government PDs.

Pipeline position:
    ExposureClassifier -> CRMProcessor -> IRBCalculator
        (engine/irb/formulas.py::_pd_floor_expression, and the guarantor-class
        variant compiled by engine/irb/guarantee.py's parameter-substitution path)

Key assertion:
    CRR Art. 160(1) (crr.pdf p.155, verbatim): "The PD of an exposure to a
    corporate or an institution shall be at least 0,03 %."

    The floor is limited to corporates and institutions. Retail is floored
    separately by Art. 163(1) (crr.pdf p.161, verbatim: "The PD of an exposure
    shall be at least 0,03 %", in the retail sub-section). There is no
    central-government / central-bank limb in either article, so a CRR CGCB IRB
    exposure is unfloored and the pack's ``sovereign: 0.0003`` was a
    conservative over-statement.

    Because every CRR ``pd_floors`` value was identical, ``_pd_floor_expression``
    took its all-equal shortcut and returned one scalar, so the class ladder never
    executed under CRR. Setting the sovereign floor to 0 makes the value set
    non-uniform, the shortcut stops firing, and the ladder routes by class — which
    is why the guarantor-class rows below move too (the three
    ``guarantor_exposure_class`` call sites in ``guarantee.py`` start
    dereferencing that column for the first time under CRR).

    Guarantor-side basis: CRR Art. 161(3) (crr.pdf p.157, verbatim) "An
    institution shall not assign guaranteed exposures an adjusted PD or LGD such
    that the adjusted risk weight would be lower than that of a comparable,
    direct exposure to the guarantor", with Art. 160(4) (p.156) as the
    PD-substitution authority ("Institutions may take into account unfunded
    credit protection in the PD in accordance with the provisions of Chapter 4").
    A comparable DIRECT CRR exposure to a central government is itself unfloored,
    so measuring the covered portion against the guarantor's class — including
    the absence of a floor — is what Art. 161(3) directs.

References:
    - CRR Art. 160(1): corporate / institution 0.03% PD floor (no CGCB limb)
    - CRR Art. 163(1): retail 0.03% PD floor
    - CRR Art. 160(4) / 161(3): PD substitution and the "no better than a direct
      exposure to the guarantor" constraint
    - PRA PS1/26 Art. 160(1) / 163(1): Basel 3.1 floors, unchanged by this item
    - src/rwa_calc/rulebook/packs/crr.py: ``pd_floors``
    - src/rwa_calc/engine/irb/formulas.py::_pd_floor_expression
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import polars as pl
import pytest
from tests.fixtures.contract_columns import pad_crm_exit_defaults

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.irb import IRBCalculator
from rwa_calc.engine.irb.formulas import _pd_floor_expression
from rwa_calc.engine.irb.guarantee import apply_guarantee_substitution
from rwa_calc.rulebook import RulepackV0

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_UNFLOORED = 0.0
_FLOOR_3BP = 0.0003

# Sub-floor modelled PD: below 3bp so the floor binds wherever it applies.
SUB_FLOOR_PD = 0.0001

EAD = 1_000_000.0
LGD = 0.45
MATURITY = 2.5

# Art. 153(1) hand-calc (see module docstring of the acceptance sibling): CRR
# carries the 1.06 scaling factor.
#   PD 0.0001 -> R 0.2394014975, b 0.3882068111, MA 2.3941212829,
#                K 0.0060258057, RW 0.0798419258
#   PD 0.0003 -> R 0.2382134328, b 0.3168344172, MA 1.9056752706,
#                K 0.0115548538, RW 0.1531018133
RW_UNFLOORED_PD = 0.0798419258
RW_FLOORED_PD = 0.1531018133
RWA_UNFLOORED_PD = 79_841.925755
RWA_FLOORED_PD = 153_101.813286


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=date(2026, 6, 30))


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


def _floor_for(
    config: CalculationConfig,
    exposure_class: str | None,
    *,
    column: str = "exposure_class",
) -> float:
    """Evaluate ``_pd_floor_expression`` for one exposure-class label."""
    frame = pl.LazyFrame({column: [exposure_class]}, schema_overrides={column: pl.String})
    expr = _pd_floor_expression(
        config,
        has_transactor_col=False,
        exposure_class_col=column,
        pack=RulepackV0.from_config(config).pack,
    )
    return frame.select(expr.alias("pd_floor")).collect()["pd_floor"][0]


# ---------------------------------------------------------------------------
# Pack values
# ---------------------------------------------------------------------------


class TestCRRPDFloorPackValues:
    """The pack is the value home: only the sovereign key changes."""

    def test_crr_sovereign_pd_floor_is_zero(self, crr_config: CalculationConfig) -> None:
        """CRR ``pd_floors["sovereign"]`` == 0 — Art. 160(1) has no CGCB limb.

        Zero (not ``None``): the key is dereferenced by name in the ladder and by
        ``api/service.py``, so every key must survive.
        """
        # Arrange / Act
        floors = RulepackV0.from_config(crr_config).pack.formula("pd_floors").params

        # Assert
        assert floors["sovereign"] == Decimal("0")

    def test_crr_corporate_institution_and_retail_floors_unchanged(
        self, crr_config: CalculationConfig
    ) -> None:
        """The Art. 160(1) and Art. 163(1) floors stay at 0.03%.

        Art. 160(1) covers corporates and institutions; Art. 163(1) covers retail.
        Only the sovereign key was outside both.
        """
        # Arrange / Act
        floors = RulepackV0.from_config(crr_config).pack.formula("pd_floors").params

        # Assert
        assert floors["corporate"] == Decimal("0.0003")
        assert floors["corporate_sme"] == Decimal("0.0003")
        assert floors["institution"] == Decimal("0.0003")
        assert floors["retail_mortgage"] == Decimal("0.0003")
        assert floors["retail_other"] == Decimal("0.0003")
        assert floors["retail_qrre_transactor"] == Decimal("0.0003")
        assert floors["retail_qrre_revolver"] == Decimal("0.0003")

    def test_b31_pd_floors_untouched(self, b31_config: CalculationConfig) -> None:
        """Basel 3.1 keeps its own PS1/26 Art. 160(1) sovereign floor (0.05%)."""
        # Arrange / Act
        floors = RulepackV0.from_config(b31_config).pack.formula("pd_floors").params

        # Assert
        assert floors["sovereign"] == Decimal("0.0005")


# ---------------------------------------------------------------------------
# The class ladder now executes under CRR
# ---------------------------------------------------------------------------


class TestCRRPDFloorLadderByClass:
    """With a non-uniform bundle the all-equal shortcut stops firing."""

    def test_cgcb_is_unfloored(self, crr_config: CalculationConfig) -> None:
        """CRR CGCB -> 0.0 (Art. 160(1) covers corporates and institutions only).

        Pre-fix failure: 0.0003 — the uniform-bundle scalar shortcut returned the
        corporate floor for every class, CGCB included.
        """
        # Arrange / Act
        floor = _floor_for(crr_config, "central_govt_central_bank")

        # Assert
        assert floor == pytest.approx(_UNFLOORED, abs=1e-12), (
            "CRR Art. 160(1) floors only corporates and institutions, so a "
            f"central-government exposure is unfloored; got {floor}."
        )

    @pytest.mark.parametrize(
        "exposure_class",
        ["corporate", "corporate_sme", "institution"],
    )
    def test_art_160_1_classes_still_floored(
        self, crr_config: CalculationConfig, exposure_class: str
    ) -> None:
        """Corporate / corporate-SME / institution keep the Art. 160(1) 0.03% floor."""
        # Arrange / Act
        floor = _floor_for(crr_config, exposure_class)

        # Assert
        assert floor == pytest.approx(_FLOOR_3BP, abs=1e-12)

    @pytest.mark.parametrize(
        "exposure_class",
        ["retail_other", "retail_mortgage", "retail_qrre"],
    )
    def test_art_163_1_retail_still_floored(
        self, crr_config: CalculationConfig, exposure_class: str
    ) -> None:
        """Retail keeps the Art. 163(1) 0.03% floor — a separate article.

        This is the regression that the ladder starting to execute could have
        broken: retail is reached by the ``contains("RETAIL")`` /
        ``contains("MORTGAGE")`` / ``contains("QRRE")`` arms, not by the
        ``otherwise`` corporate arm.
        """
        # Arrange / Act
        floor = _floor_for(crr_config, exposure_class)

        # Assert
        assert floor == pytest.approx(_FLOOR_3BP, abs=1e-12)

    @pytest.mark.parametrize("exposure_class", ["mdb", "covered_bond", "other", None, ""])
    def test_unmapped_labels_take_the_conservative_corporate_arm(
        self, crr_config: CalculationConfig, exposure_class: str | None
    ) -> None:
        """Labels with no ladder branch fall to ``otherwise`` = the 0.03% floor.

        Fan-out pin for the newly-live ladder. ``mdb`` is an institution exposure
        under CRR Art. 147(4)(c) and ``covered_bond`` is an exposure to the
        issuing institution, so the corporate arm's 0.03% is the numerically
        correct Art. 160(1) floor for both. A null label becomes ``"CORPORATE"``
        via ``fill_null`` and an empty string matches no branch — both land on the
        same 0.03%, so no row silently loses its floor.
        """
        # Arrange / Act
        floor = _floor_for(crr_config, exposure_class)

        # Assert
        assert floor == pytest.approx(_FLOOR_3BP, abs=1e-12)

    def test_b31_cgcb_still_floored(self, b31_config: CalculationConfig) -> None:
        """Regression: a Basel 3.1 CGCB row keeps the PS1/26 0.05% floor."""
        # Arrange / Act
        floor = _floor_for(b31_config, "central_govt_central_bank")

        # Assert
        assert floor == pytest.approx(0.0005, abs=1e-12)


# ---------------------------------------------------------------------------
# Borrower-side capital effect
# ---------------------------------------------------------------------------


class TestCRRCGCBBorrowerCapitalEffect:
    """A CRR CGCB IRB row with a sub-floor PD now keeps its modelled PD."""

    @staticmethod
    def _irb_row(exposure_class: str, config: CalculationConfig) -> dict:
        frame = pl.DataFrame(
            {
                "exposure_reference": ["P1277"],
                "ead_final": [EAD],
                "pd": [SUB_FLOOR_PD],
                "lgd": [LGD],
                "exposure_class": [exposure_class],
                "maturity": [MATURITY],
                "approach": ["foundation_irb"],
            }
        ).lazy()
        return (
            IRBCalculator()
            .calculate_branch(pad_crm_exit_defaults(frame), config)
            .collect()
            .to_dicts()[0]
        )

    def test_cgcb_row_keeps_modelled_pd_and_rwa_falls(self, crr_config: CalculationConfig) -> None:
        """CRR CGCB, modelled PD 1bp -> PD stays 1bp, RWA 79,841.93.

        Arrange: EAD 1,000,000, PD 0.0001, LGD 45%, M 2.5y, F-IRB, CRR.
        Act:     IRBCalculator.calculate_branch.
        Assert:  pd_floored == 0.0001, risk_weight == 0.0798419258, rwa == 79,841.93.

        Pre-fix failure: PD floored to 0.0003 -> RW 0.1531018133 -> RWA
        153,101.81. The 73,259.89 reduction is the over-statement Art. 160(1)
        never authorised.
        """
        # Arrange / Act
        row = self._irb_row("central_govt_central_bank", crr_config)

        # Assert
        assert row["pd_floored"] == pytest.approx(SUB_FLOOR_PD, rel=1e-9)
        assert row["risk_weight"] == pytest.approx(RW_UNFLOORED_PD, rel=1e-9)
        assert row["rwa"] == pytest.approx(RWA_UNFLOORED_PD, rel=1e-9)

    def test_corporate_row_is_still_floored(self, crr_config: CalculationConfig) -> None:
        """Control: a CRR corporate row with the same PD is still floored to 3bp.

        Assert: pd_floored == 0.0003 and rwa == 153,101.81 — the pre-fix value, which the
        CGCB row must no longer share.
        """
        # Arrange / Act
        row = self._irb_row("corporate", crr_config)

        # Assert
        assert row["pd_floored"] == pytest.approx(_FLOOR_3BP, rel=1e-9)
        assert row["risk_weight"] == pytest.approx(RW_FLOORED_PD, rel=1e-9)
        assert row["rwa"] == pytest.approx(RWA_FLOORED_PD, rel=1e-9)

    def test_b31_cgcb_row_is_still_floored(self, b31_config: CalculationConfig) -> None:
        """Regression: a Basel 3.1 CGCB row is still floored (PS1/26 0.05%)."""
        # Arrange / Act
        row = self._irb_row("central_govt_central_bank", b31_config)

        # Assert
        assert row["pd_floored"] == pytest.approx(0.0005, rel=1e-9)


# ---------------------------------------------------------------------------
# Guarantor-side effect (the second surface the dead shortcut was hiding)
# ---------------------------------------------------------------------------


class TestCRRGuarantorPDFloorByClass:
    """The three ``guarantor_exposure_class`` call sites now route by class."""

    @staticmethod
    def _guaranteed_row(guarantor_exposure_class: str, config: CalculationConfig) -> dict:
        """One fully-guaranteed corporate borrower with an IRB-modelled guarantor."""
        frame = pl.LazyFrame(
            {
                "exposure_reference": ["P1277-G"],
                "pd": [0.02],
                "lgd": [LGD],
                "ead_final": [EAD],
                "maturity": [MATURITY],
                "exposure_class": ["corporate"],
                "risk_weight": [1.0],
                "rwa": [EAD],
                "guaranteed_portion": [EAD],
                "unguaranteed_portion": [0.0],
                "guarantor_exposure_class": [guarantor_exposure_class],
                "guarantor_entity_type": ["sovereign"],
                "guarantor_cqs": [1],
                "guarantor_approach": ["irb"],
                "guarantor_pd": [SUB_FLOOR_PD],
                "guarantor_seniority": ["senior"],
            },
            schema_overrides={"guarantor_cqs": pl.Int8, "guarantor_pd": pl.Float64},
        )
        return apply_guarantee_substitution(frame, config).collect().to_dicts()[0]

    def test_cgcb_guarantor_pd_is_unfloored(self, crr_config: CalculationConfig) -> None:
        """A CRR central-government guarantor's substituted PD is unfloored.

        Art. 161(3) measures the covered portion against "a comparable, direct
        exposure to the guarantor". A direct CRR CGCB exposure is unfloored, so
        the substituted PD keeps the modelled 1bp and the guarantor risk weight
        falls to the unfloored-PD level.

        Pre-fix: the uniform-bundle shortcut floored every guarantor PD at 3bp
        regardless of the guarantor's class.
        """
        # Arrange / Act
        row = self._guaranteed_row("central_govt_central_bank", crr_config)

        # Assert
        assert row["guarantor_rw"] == pytest.approx(RW_UNFLOORED_PD, rel=1e-6), (
            "a CGCB guarantor should price off the unfloored modelled PD; got "
            f"{row['guarantor_rw']}"
        )

    def test_corporate_guarantor_pd_is_still_floored(self, crr_config: CalculationConfig) -> None:
        """Control: a corporate guarantor keeps the Art. 160(1) 3bp floor."""
        # Arrange / Act
        row = self._guaranteed_row("corporate", crr_config)

        # Assert
        assert row["guarantor_rw"] == pytest.approx(RW_FLOORED_PD, rel=1e-6)

    def test_empty_guarantor_class_is_still_floored(self, crr_config: CalculationConfig) -> None:
        """Null-semantics pin: the ``""`` default lands on the 3bp corporate arm.

        ``guarantor_exposure_class`` is defaulted to an empty string (not null) by
        the CRM processor, and an empty string matches no ladder branch, so such a
        row keeps today's 0.03% floor — the newly-live ladder cannot silently
        unfloor a row whose guarantor class is unknown.
        """
        # Arrange / Act
        row = self._guaranteed_row("", crr_config)

        # Assert
        assert row["guarantor_rw"] == pytest.approx(RW_FLOORED_PD, rel=1e-6)
