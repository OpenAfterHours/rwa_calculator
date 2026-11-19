"""
IV-06: CRR equity flagged ``is_significant_investment`` takes the Art. 48(4) 250%.

Rule text
---------
CRR Art. 133(2), verbatim (legislation.gov.uk, onshored): "Equity exposures
shall be assigned a risk weight of 100 %, unless they are required to be
deducted in accordance with Part Two, assigned a 250 % risk weight in
accordance with Article 48(4), assigned a 1 250 % risk weight in accordance with
Article 89(3) or treated as high risk items in accordance with Article 128."

CRR Art. 155(1), verbatim: "Institutions shall determine their risk-weighted
exposure amounts for equity exposures, excluding those deducted in accordance
with Part Two or subject to a 250 % risk weight in accordance with Article 48,
in accordance with the approaches set out in paragraphs 2, 3 and 4 of this
Article." So the 250% leg is OUTSIDE the IRB simple-RW and PD/LGD approaches.
For those two paths the change LOWERS the weight (290% / 370% / PD-LGD K to
250%) -- RWA-reducing, quoted here per LESSONS A2.

(Art. 48 now sits in the PRA Rulebook Own Funds (CRR) Part; PS1/26
Art. 133(6)(c) cross-refers to "paragraph 4 of Own Funds (CRR) Part Article
48". The flag carries the firm's assertion that the amount is a non-deducted
significant investment weighted under Art. 48(4); the engine does no deduction.)

Scope of this file: CRR only. Basel 3.1 is unchanged here (its Art. 133(3)
250% already applies to a standard-risk significant investment; the higher-risk
and transitional interplay is P1.393).

Hand calculations (EAD 1,000,000):
    CRR SA listed / unlisted, significant:   RW 2.50, RWA 2,500,000 (pre-fix 1.00)
    CRR IRB simple exchange-traded, sig:     RW 2.50, RWA 2,500,000 (pre-fix 2.90)
    CRR IRB simple other, sig:               RW 2.50, RWA 2,500,000 (pre-fix 3.70)
    CRR PD/LGD, sig:                         RW 2.50, RWA 2,500,000
    Not significant: unchanged (1.00 / 2.90 / 3.70).
"""

from __future__ import annotations

import dataclasses
from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.equity import EquityCalculator

_EAD = 1_000_000.0

_SA = CalculationConfig.crr(reporting_date=date(2026, 6, 30))
_IRB = CalculationConfig.crr(reporting_date=date(2026, 6, 30), permission_mode=PermissionMode.IRB)
_PD_LGD = dataclasses.replace(_IRB, equity_pd_lgd=True)


def _row(config: CalculationConfig, **attributes: object) -> dict:
    """One equity leg through ``calculate_branch`` (the input contract fills the rest)."""
    frame = pl.LazyFrame(
        {"exposure_reference": ["EQ"], "ead_final": [_EAD]}
        | {name: [value] for name, value in attributes.items()}
    )
    return EquityCalculator().calculate_branch(frame, config).collect().row(0, named=True)


class TestCrrSaSignificantInvestment:
    """Art. 133(2): 250% in place of the 100% flat weight."""

    @pytest.mark.parametrize(
        "attributes",
        [
            {"equity_type": "listed", "is_exchange_traded": True},
            {"equity_type": "unlisted"},
            {"equity_type": "other"},
        ],
        ids=["listed", "unlisted", "other"],
    )
    def test_significant_investment_is_250(self, attributes: dict) -> None:
        # Act
        row = _row(_SA, is_significant_investment=True, **attributes)

        # Assert
        assert row["risk_weight"] == pytest.approx(2.50)
        assert row["rwa_final"] == pytest.approx(2_500_000.0)

    def test_not_significant_stays_100(self) -> None:
        # Act
        row = _row(_SA, equity_type="listed", is_significant_investment=False)

        # Assert
        assert row["risk_weight"] == pytest.approx(1.00)

    def test_null_flag_is_not_a_significant_investment(self) -> None:
        # Act
        row = _row(_SA, equity_type="listed", is_significant_investment=None)

        # Assert
        assert row["risk_weight"] == pytest.approx(1.00)

    def test_ciu_keeps_its_article_132_treatment(self) -> None:
        """A CIU unit is weighted under Arts. 132-132C, whatever the flag says."""
        # Act
        row = _row(_SA, equity_type="ciu", ciu_approach="fallback", is_significant_investment=True)

        # Assert
        assert row["risk_weight"] == pytest.approx(12.50)

    def test_central_bank_keeps_zero(self) -> None:
        # Act
        row = _row(_SA, equity_type="central_bank", is_significant_investment=True)

        # Assert
        assert row["risk_weight"] == pytest.approx(0.0)


class TestCrrIrbSimpleSignificantInvestment:
    """Art. 155(1) excludes the Art. 48 250% leg from the simple-RW approach."""

    @pytest.mark.parametrize(
        ("attributes", "pre_fix_rw"),
        [
            ({"equity_type": "listed", "is_exchange_traded": True}, 2.90),
            ({"equity_type": "other"}, 3.70),
            ({"equity_type": "private_equity_diversified"}, 1.90),
        ],
        ids=["exchange_traded", "other", "private_equity_diversified"],
    )
    def test_significant_investment_is_250_not_the_simple_weight(
        self, attributes: dict, pre_fix_rw: float
    ) -> None:
        # Act
        sig = _row(_IRB, is_significant_investment=True, **attributes)
        plain = _row(_IRB, is_significant_investment=False, **attributes)

        # Assert
        assert plain["risk_weight"] == pytest.approx(pre_fix_rw), "simple RW control"
        assert sig["risk_weight"] == pytest.approx(2.50)
        assert sig["rwa_final"] == pytest.approx(2_500_000.0)

    def test_significant_leg_is_not_an_article_155_leg(self) -> None:
        """No Art. 158(7) simple-RW EL, and the sealed method is ``irb_fixed_rw``.

        Pillar 3 CR10.5 and OV1 UK 4a read ``equity_method == irb_simple`` as
        Art. 155(2) simple-RW equity; a 250% Art. 48(4) leg is excluded from
        Art. 155 by its paragraph 1, so it must not carry that tag. Nor is it SA:
        COREP Annex II, C 10.01 row 0110 "Equity exposures subject to risk
        weights", verbatim: "Institutions applying the IRB approach shall report
        risk weighted exposure amounts for those equity exposures which attract a
        fixed risk weight treatment (without however being explicitly treated
        according to the Simple Risk Weight approach or the (temporary or
        permanent) partial use of the credit risk standardised approach). For
        example, the risk weighted exposure amount of equity positions in
        financial sector entities treated in accordance with Article 48(4) of the
        CRR ... shall be reported in row 110." (EBA Q&A 2013_670 confirms.) So
        the leg is sealed ``irb_fixed_rw``: IRB-umbrella equity (C 02.00 r0420),
        not simple-RW equity and not SA equity (C 02.00 r0210 / C 07.00).
        """
        # Act
        sig = _row(
            _IRB, equity_type="listed", is_exchange_traded=True, is_significant_investment=True
        )
        plain = _row(_IRB, equity_type="listed", is_exchange_traded=True)

        # Assert
        assert plain["equity_method"] == "irb_simple"
        assert plain["expected_loss"] == pytest.approx(8_000.0)
        assert sig["equity_method"] == "irb_fixed_rw"
        assert sig["expected_loss"] is None

    def test_ciu_keeps_its_own_treatment_on_the_irb_simple_path(self) -> None:
        """The predicate's CIU exclusion, on the one path where it is load-bearing.

        On the SA chain the CIU branches precede the 250% branch, so a flagged CIU
        there cannot tell whether the predicate excludes CIUs. The IRB simple
        chain has no CIU branch: without the exclusion a flagged CIU would drop
        to 250%. Asserted against its unflagged twin, so the CIU weight itself
        (P1.380) is not pinned here.
        """
        # Act
        sig = _row(_IRB, equity_type="ciu", ciu_approach="fallback", is_significant_investment=True)
        plain = _row(_IRB, equity_type="ciu", ciu_approach="fallback")

        # Assert
        assert plain["risk_weight"] != pytest.approx(2.50), "control must not already be 250%"
        assert sig["risk_weight"] == pytest.approx(plain["risk_weight"])
        assert sig["equity_method"] == plain["equity_method"] == "irb_simple"


class TestCrrPdLgdSignificantInvestment:
    """Art. 155(1) excludes the Art. 48 250% leg from the PD/LGD approach too."""

    def test_significant_investment_is_250_not_the_k_formula(self) -> None:
        # Act
        sig = _row(_PD_LGD, equity_type="other", is_significant_investment=True)
        plain = _row(_PD_LGD, equity_type="other", is_significant_investment=False)

        # Assert
        assert plain["equity_method"] == "pd_lgd"
        assert plain["risk_weight"] != pytest.approx(2.50), "control must take the K formula"
        assert sig["risk_weight"] == pytest.approx(2.50)
        assert sig["rwa_final"] == pytest.approx(2_500_000.0)
        assert sig["rwa"] == pytest.approx(2_500_000.0)
        assert sig["expected_loss"] is None
        assert sig["equity_method"] == "irb_fixed_rw"
        assert sig["equity_pd_lgd_cap_binds"] is False
        assert sig["exposure_class"] == "equity"

    def test_central_bank_keeps_its_own_treatment_on_the_pd_lgd_path(self) -> None:
        """The predicate's central-bank exclusion, where it is load-bearing.

        The SA and IRB simple chains test central bank first; the PD/LGD path has
        no central-bank branch, so without the exclusion a flagged central-bank
        leg would take 250% instead of the K formula its unflagged twin takes.
        """
        # Act
        sig = _row(_PD_LGD, equity_type="central_bank", is_significant_investment=True)
        plain = _row(_PD_LGD, equity_type="central_bank")

        # Assert
        assert plain["risk_weight"] != pytest.approx(2.50), "control must not already be 250%"
        assert sig["risk_weight"] == pytest.approx(plain["risk_weight"])
        assert sig["equity_method"] == plain["equity_method"] == "pd_lgd"
