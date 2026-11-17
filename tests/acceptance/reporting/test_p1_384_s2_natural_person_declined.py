"""
P1.384 — the crm-substitution S2 natural-person guarantee is declined under Art. 201.

Pipeline position:
    build_reporting_crm_substitution_bundle() -> PipelineOrchestrator
        -> AggregatedResultBundle -> COREPGenerator

Why this exists: S2 is a 3,300,000 (55%) credit derivative written by a natural
person (``CSUB-CP-GTOR-S2``: entity_type ``individual``, internal PD 2.00%) on
an F-IRB large-corporate loan (obligor PD 0.60%). Art. 201 lists no natural
person in either regime, so the protection is not recognised and the covered
part keeps the obligor's own F-IRB basis. The engine used to apply parameter
substitution at the person's retail PD instead, understating RWEA by 1,660,414.55
(CRR) / 1,392,381.17 (Basel 3.1) on this leg alone; the reporting layer then split
the leg between templates. This file runs the registered portfolio through the
same configs as ``RUNS`` (``test_supervisory_validations.py``) and pins:

- the leg (adequacy first): RW, RWEA and EL are the obligor's own, re-derived
  here by hand from the Art. 153(1) formula, and exactly one CRM013 names it;
- one cross-template tie per regime that the defect broke, each red on its own
  regime before the fix (LESSONS C7: one red across a parametrisation proves one
  regime, not two):
    CRR    C 02.00 r0300 (F-IRB corporates - other) == C 08.01[corporate] c0260
           - no published rule makes this comparison, which is why the CRR half
           of the defect shipped silently;
    B31    OF 09.02 r0030 c0105 == OF 08.01 corporate sheets' c0110 (z0010 + z0012)
           - the published ``boe_b0283``.

References:
- CRR Art. 201(1)/(2), Art. 194(5); CRR Art. 153(1) (corporate RW function)
- PS1/26 Credit Risk Mitigation (CRR) Part Art. 201(1)/(2), Art. 194(6)(c)
- PS1/26 Annex II para 42: the covered part is an outflow of the obligor's class
  and an inflow of the guarantor's ONLY where the protection is recognised
"""

from __future__ import annotations

import functools
import math
from datetime import date
from statistics import NormalDist

import polars as pl
import pytest
from tests.fixtures.reporting_crm_substitution_portfolio import (
    AMOUNT_COVERED_S2,
    GTOR_S2,
    LN_S2,
    PD_OB_S2,
    build_reporting_crm_substitution_bundle,
)

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.contracts.errors import ERROR_INELIGIBLE_GUARANTOR, CalculationError
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle

_REGIMES: dict[str, str] = {"crr": "CRR", "b31": "BASEL_3_1"}
_S2_LEG = f"{LN_S2}__G_{GTOR_S2}"

#: F-IRB senior unsecured LGD and the IRB scaling factor, per regime: CRR
#: Art. 161(1)(a) 45% and Art. 153(1) x1.06; PS1/26 Art. 161(1)(aa) 40%, no 1.06.
_LGD: dict[str, float] = {"crr": 0.45, "b31": 0.40}
_SCALING: dict[str, float] = {"crr": 1.06, "b31": 1.0}
_MATURITY_YEARS = 5.0


def _config(regime_key: str) -> CalculationConfig:
    """The ``RUNS`` configs for crm-substitution (``_irb_config``), restated here."""
    if regime_key == "crr":
        return CalculationConfig.crr(
            reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.IRB
        )
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 1),
        permission_mode=PermissionMode.IRB,
        enforce_retail_granularity=False,
    )


@functools.cache
def _run(regime_key: str) -> tuple[pl.DataFrame, tuple[CalculationError, ...], COREPTemplateBundle]:
    """One pipeline run + COREP per regime, memoised. Treat the result as read-only."""
    result = PipelineOrchestrator().run_with_data(
        build_reporting_crm_substitution_bundle(), _config(regime_key)
    )
    corep = COREPGenerator().generate_from_lazyframe(
        result.results,
        framework=_REGIMES[regime_key],
        output_floor_summary=result.output_floor_summary,
    )
    return result.results.collect(), tuple(result.errors), corep


def _s2_leg(regime_key: str) -> dict[str, object]:
    results, _errors, _corep = _run(regime_key)
    legs = results.filter(pl.col("exposure_reference") == _S2_LEG)
    assert legs.height == 1, f"{regime_key}: no {_S2_LEG} leg - this file would prove nothing"
    return legs.row(0, named=True)


def _obligor_risk_weight(regime_key: str) -> float:
    """CRR / PS1/26 Art. 153(1) corporate RW at the OBLIGOR's PD, by hand.

    Large corporate (no SME adjustment), M = 5: the basis the covered part keeps
    once the natural person's protection is not recognised.
    """
    pd_, lgd = PD_OB_S2, _LGD[regime_key]
    weight = (1 - math.exp(-50 * pd_)) / (1 - math.exp(-50))
    correlation = 0.12 * weight + 0.24 * (1 - weight)
    b = (0.11852 - 0.05478 * math.log(pd_)) ** 2
    normal = NormalDist()
    conditional_pd = normal.cdf(
        (normal.inv_cdf(pd_) + math.sqrt(correlation) * normal.inv_cdf(0.999))
        / math.sqrt(1 - correlation)
    )
    maturity_adjustment = (1 + (_MATURITY_YEARS - 2.5) * b) / (1 - 1.5 * b)
    k = lgd * (conditional_pd - pd_) * maturity_adjustment
    return k * 12.5 * _SCALING[regime_key]


class TestS2LegKeepsTheObligorsBasis:
    """The natural person's protection is not recognised: no substitution at all."""

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_leg_is_the_f_irb_path_that_used_to_substitute(self, regime_key: str) -> None:
        """Adequacy: the leg carries cover, a natural-person guarantor and an F-IRB obligor."""
        leg = _s2_leg(regime_key)

        assert leg["guaranteed_portion"] == pytest.approx(AMOUNT_COVERED_S2)
        assert leg["guarantor_entity_type"] == "individual"
        assert leg["approach"] == "foundation_irb"

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_leg_is_not_substituted(self, regime_key: str) -> None:
        leg = _s2_leg(regime_key)

        assert leg["guarantor_approach"] == ""
        assert leg["is_guarantee_beneficial"] is False
        assert leg["exposure_class_post_crm"] == "corporate"
        assert leg["reporting_class"] == "corporate"

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_leg_rwea_is_the_obligors_own(self, regime_key: str) -> None:
        """RW = the Art. 153(1) corporate RW at PD 0.60%, LGD per regime, M = 5."""
        leg = _s2_leg(regime_key)
        risk_weight = _obligor_risk_weight(regime_key)

        assert leg["risk_weight"] == pytest.approx(risk_weight, rel=1e-9)
        assert leg["rwa_final"] == pytest.approx(AMOUNT_COVERED_S2 * risk_weight, rel=1e-9)
        assert leg["rwa_final"] == pytest.approx(leg["rwa_irb_original"], rel=1e-12)

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_leg_expected_loss_is_the_obligors_own(self, regime_key: str) -> None:
        leg = _s2_leg(regime_key)

        assert leg["expected_loss"] == pytest.approx(
            AMOUNT_COVERED_S2 * PD_OB_S2 * _LGD[regime_key], rel=1e-9
        )

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_exactly_one_crm013_names_the_natural_person(self, regime_key: str) -> None:
        _results, errors, _corep = _run(regime_key)

        crm013 = [
            e
            for e in errors
            if e.code == ERROR_INELIGIBLE_GUARANTOR and e.exposure_reference == LN_S2
        ]

        assert len(crm013) == 1, [e.message for e in crm013]
        assert GTOR_S2 in crm013[0].message
        assert "natural person" in crm013[0].message


class TestTemplatesPlaceTheCoveredPartOnce:
    """With the protection declined, every template carries S2 as corporate."""

    @pytest.mark.parametrize("regime_key", list(_REGIMES))
    def test_no_retail_irb_sheet_is_reported(self, regime_key: str) -> None:
        """No exposure in this portfolio is retail once S2 is declined."""
        _results, _errors, corep = _run(regime_key)

        assert sorted(key for key in corep.c08_01 if key.startswith("retail")) == []

    def test_crr_c02_corporate_row_equals_the_c0801_corporate_sheet(self) -> None:
        """CRR: C 02.00 r0300 is the RWEA of C 08.01[corporate] row 0010 col 0260.

        Before the fix C 02.00 reverted S2 to its obligor (27,414,657.41) while
        C 08.01 put it on an inflow-only retail_other sheet (25,386,291.63).
        """
        _results, _errors, corep = _run("crr")
        c02 = corep.c_02_00.filter(pl.col("row_ref") == "0300")
        c0801 = corep.c08_01["corporate"].filter(pl.col("row_ref") == "0010")

        assert c0801["0260"][0] > 0.0, "C 08.01[corporate] carries no RWEA - vacuous"
        assert c02["0010"][0] == pytest.approx(c0801["0260"][0], rel=1e-12)

    def test_b31_of0902_corporates_equal_the_of0801_corporate_sheets(self) -> None:
        """Basel 3.1 ``boe_b0283``: OF 09.02 r0030 c0105 = OF 08.01 z0010 + z0012 c0110.

        Before the fix OF 09.02 counted S2's 3,300,000 as retail (43,000,000)
        while OF 08.01 kept it on the obligor's sheet 0012 (46,300,000).
        """
        _results, _errors, corep = _run("b31")
        of0902 = corep.c09_02["TOTAL"].filter(pl.col("row_ref") == "0030")
        corporate_sheets = ("corporate_non_sme_firb", "specialised_lending_firb_slotting")
        of0801 = sum(
            corep.c08_01[key].filter(pl.col("row_ref") == "0010")["0110"][0]
            for key in corporate_sheets
        )

        assert of0801 > 0.0, "OF 08.01 corporate sheets carry no exposure value - vacuous"
        assert of0902["0105"][0] == pytest.approx(of0801, rel=1e-12)
