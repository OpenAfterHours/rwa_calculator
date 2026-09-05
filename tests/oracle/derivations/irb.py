"""
Phase O2 -- Foundation and Advanced IRB oracles, both regimes.

Every parameter below was read out of the article text: `docs/assets/crr.pdf`
for the CRR oracles and `docs/assets/ps126app1.pdf` for the PS1/26 ones.

The two regimes differ in four ways that a conservation or monotonicity
property cannot see, and that this module exists to pin:

1. The 1.06 scaling factor in CRR Art. 153(1)(iii) / 154(1)(ii) is removed by
   PS1/26 Art. 153(1)(c) / 154(1)(b).
2. The F-IRB senior unsecured LGD for a non-financial corporate falls from 45%
   (CRR Art. 161(1)(a)) to 40% (PS1/26 Art. 161(1)(aa)).
3. The PD floor rises from 0.03% (CRR Art. 160(1), 163(1)) to 0.05% / 0.1%
   depending on the sub-portfolio (PS1/26 Art. 160(1), 163(1)).
4. PS1/26 Art. 161(5) and 164(4) add A-IRB LGD input floors, which CRR has none
   of.

References:
- CRR Art. 153(1), (2), (4); Art. 154(1), (3), (4); Art. 160(1), (3);
  Art. 161(1); Art. 162(1)
- PS1/26 Art. 153(1), (2), (4); Art. 154(1), (3), (4); Art. 160(1), (3);
  Art. 161(1), (5); Art. 163(1); Art. 164(4)
"""

from __future__ import annotations

from typing import Any

from .formulas import (
    B31_IRB_SCALING_FACTOR,
    CORRELATION_RETAIL_MORTGAGE,
    CORRELATION_RETAIL_QRRE,
    CRR_IRB_SCALING_FACTOR,
    FINANCIAL_SECTOR_CORRELATION_MULTIPLIER,
    conditional_pd,
    correlation_corporate,
    correlation_corporate_sme,
    correlation_retail,
    expected_loss,
    irb_risk_weight_corporate,
    irb_risk_weight_defaulted_airb,
    irb_risk_weight_retail,
    maturity_adjustment,
    maturity_adjustment_b,
    sme_supporting_factor,
)
from .record import oracle

PHASE = "O2"
M = 1_000_000.0
EAD = 10 * M

#: What the *bank* supplies as LGD on a Foundation IRB exposure: nothing.
#: The engine must derive the supervisory value from Art. 161 itself, which is
#: what makes the F-IRB oracles a test of that table and not just of the
#: risk-weight formula.
SUPERVISORY = None

# CRR Art. 161(1)(a)/(b): F-IRB supervisory LGD.
CRR_FIRB_LGD_SENIOR = 0.45
CRR_FIRB_LGD_SUBORDINATED = 0.75
# PS1/26 Art. 161(1)(a)/(aa)/(b).
B31_FIRB_LGD_SENIOR_FSE = 0.45
B31_FIRB_LGD_SENIOR_CORPORATE = 0.40
B31_FIRB_LGD_SUBORDINATED = 0.75

# CRR Art. 160(1) and 163(1): a single 0.03% PD floor.
CRR_PD_FLOOR = 0.0003
# PS1/26 Art. 160(1): corporates and institutions.
B31_PD_FLOOR_CORPORATE = 0.0005
# PS1/26 Art. 163(1)(a)-(c): retail.
B31_PD_FLOOR_QRRE_NON_TRANSACTOR = 0.001
B31_PD_FLOOR_RETAIL_UK_RRE = 0.001
B31_PD_FLOOR_RETAIL_OTHER = 0.0005

# PS1/26 Art. 161(5)(a) and 164(4)(a)/(b): A-IRB LGD input floors.
B31_LGD_FLOOR_CORPORATE_UNSECURED = 0.25
B31_LGD_FLOOR_RETAIL_RRE = 0.05
B31_LGD_FLOOR_RETAIL_QRRE = 0.50
B31_LGD_FLOOR_RETAIL_OTHER_UNSECURED = 0.30

# CRR Art. 162(1): F-IRB maturity is fixed at 2.5 years (0.5 for repos).
FIRB_FIXED_MATURITY = 2.5

# PS1/26 Art. 154(4A)(b): risk-weighted exposure amounts for non-defaulted retail
# exposures secured by UK residential immovable property must be at least 10% of
# the exposure value. There is no CRR equivalent. It binds whenever the modelled
# risk weight falls below 10%, which the 5% LGD input floor makes easy to reach.
B31_RETAIL_UK_RRE_RWEA_FLOOR = 0.10


def _corporate(
    oracle_id: str,
    framework: str,
    approach: str,
    regulation: str,
    *,
    pd_value: float,
    lgd: float,
    maturity: float,
    scaling_factor: float,
    correlation: float,
    exposure_class: str = "corporate",
    inputs: dict[str, Any] | None = None,
    ead: float = EAD,
    unasserted: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Build a corporate/institution IRB oracle with all intermediates recorded.

    ``approach`` also decides what the bank supplies as LGD: a Foundation IRB
    row supplies none, so the engine has to reach for the Art. 161 table.
    """
    declared_inputs = dict(inputs or {})
    supervisory: dict[str, Any] = {}
    if approach == "FIRB":
        # The bank supplies no own LGD estimate; the CRM stage hands the branch
        # the Art. 161 supervisory value. Recording it as ``firb_supervisory_lgd``
        # makes the engine's own Art. 161 derivation (published on ``lgd``) a
        # separately-checked intermediate rather than an assumption.
        declared_inputs["lgd"] = SUPERVISORY
        declared_inputs["lgd_post_crm"] = lgd
        supervisory["firb_supervisory_lgd"] = lgd
    risk_weight = irb_risk_weight_corporate(
        pd_value=pd_value,
        lgd=lgd,
        maturity=maturity,
        correlation=correlation,
        scaling_factor=scaling_factor,
    )
    return oracle(
        oracle_id=oracle_id,
        phase=PHASE,
        framework=framework,
        approach=approach,
        exposure_class=exposure_class,
        regulation=regulation,
        ead=ead,
        risk_weight=risk_weight,
        inputs={"exposure_class": exposure_class, **declared_inputs},
        intermediate={
            "pd_applied": pd_value,
            "lgd_applied": lgd,
            "maturity_applied": maturity,
            "correlation_R": correlation,
            "maturity_adj_b": maturity_adjustment_b(pd_value),
            "maturity_adj_MA": maturity_adjustment(pd_value, maturity),
            "conditional_pd": conditional_pd(pd_value, correlation),
            "scaling_factor": scaling_factor,
            "expected_loss_rate": expected_loss(pd_value, lgd),
            **supervisory,
        },
        unasserted=unasserted,
    )


def _retail(
    oracle_id: str,
    framework: str,
    regulation: str,
    *,
    pd_value: float,
    lgd: float,
    correlation: float,
    scaling_factor: float,
    exposure_class: str,
    inputs: dict[str, Any] | None = None,
    ead: float = EAD,
) -> dict[str, Any]:
    """Build a retail A-IRB oracle. No maturity adjustment (Art. 154(1))."""
    risk_weight = irb_risk_weight_retail(
        pd_value=pd_value,
        lgd=lgd,
        correlation=correlation,
        scaling_factor=scaling_factor,
    )
    return oracle(
        oracle_id=oracle_id,
        phase=PHASE,
        framework=framework,
        approach="AIRB",
        exposure_class=exposure_class,
        regulation=regulation,
        ead=ead,
        risk_weight=risk_weight,
        inputs={"exposure_class": exposure_class, **(inputs or {})},
        intermediate={
            "pd_applied": pd_value,
            "lgd_applied": lgd,
            "correlation_R": correlation,
            "conditional_pd": conditional_pd(pd_value, correlation),
            "scaling_factor": scaling_factor,
            "expected_loss_rate": expected_loss(pd_value, lgd),
        },
    )


# -----------------------------------------------------------------------------
# CRR -- corporates and institutions (Art. 153)
# -----------------------------------------------------------------------------
def crr_corporate() -> list[dict[str, Any]]:
    pd_1pc = 0.01
    return [
        _corporate(
            "ORC-003",
            "CRR",
            "FIRB",
            "CRR Art. 153(1) with Art. 161(1)(a) and Art. 162(1): F-IRB corporate, "
            "senior unsecured (LGD 45%), M = 2.5, including the 1.06 scaling factor",
            pd_value=pd_1pc,
            lgd=CRR_FIRB_LGD_SENIOR,
            maturity=FIRB_FIXED_MATURITY,
            scaling_factor=CRR_IRB_SCALING_FACTOR,
            correlation=correlation_corporate(pd_1pc),
            inputs={
                "pd_value": pd_1pc,
                "lgd": CRR_FIRB_LGD_SENIOR,
                "maturity": FIRB_FIXED_MATURITY,
            },
        ),
        _corporate(
            "ORC-081",
            "CRR",
            "FIRB",
            "CRR Art. 153(1) with Art. 161(1)(b): F-IRB corporate, subordinated "
            "without eligible collateral -> LGD 75%",
            pd_value=pd_1pc,
            lgd=CRR_FIRB_LGD_SUBORDINATED,
            maturity=FIRB_FIXED_MATURITY,
            scaling_factor=CRR_IRB_SCALING_FACTOR,
            correlation=correlation_corporate(pd_1pc),
            inputs={
                "pd_value": pd_1pc,
                "lgd": CRR_FIRB_LGD_SUBORDINATED,
                "maturity": FIRB_FIXED_MATURITY,
                "seniority": "subordinated",
            },
        ),
        _corporate(
            "ORC-082",
            "CRR",
            "AIRB",
            "CRR Art. 153(1): A-IRB corporate at the Art. 162(2) five-year maturity "
            "cap -- exercises the maturity adjustment numerator",
            pd_value=pd_1pc,
            lgd=0.30,
            maturity=5.0,
            scaling_factor=CRR_IRB_SCALING_FACTOR,
            correlation=correlation_corporate(pd_1pc),
            inputs={"pd_value": pd_1pc, "lgd": 0.30, "maturity": 5.0},
        ),
        _corporate(
            "ORC-083",
            "CRR",
            "AIRB",
            "CRR Art. 153(1): A-IRB corporate at M = 1 -- the maturity adjustment "
            "numerator is below 1, so MA is at its minimum",
            pd_value=pd_1pc,
            lgd=0.30,
            maturity=1.0,
            scaling_factor=CRR_IRB_SCALING_FACTOR,
            correlation=correlation_corporate(pd_1pc),
            inputs={"pd_value": pd_1pc, "lgd": 0.30, "maturity": 1.0},
        ),
        _corporate(
            "ORC-084",
            "CRR",
            "FIRB",
            "CRR Art. 160(1): a reported PD of 0.01% is lifted to the 0.03% floor "
            "before the Art. 153(1) formula is evaluated",
            pd_value=CRR_PD_FLOOR,
            lgd=CRR_FIRB_LGD_SENIOR,
            maturity=FIRB_FIXED_MATURITY,
            scaling_factor=CRR_IRB_SCALING_FACTOR,
            correlation=correlation_corporate(CRR_PD_FLOOR),
            inputs={
                "pd_value": 0.0001,
                "lgd": CRR_FIRB_LGD_SENIOR,
                "maturity": FIRB_FIXED_MATURITY,
            },
        ),
        _corporate(
            "ORC-085",
            "CRR",
            "FIRB",
            "CRR Art. 153(1) with Art. 161(1)(a): F-IRB institution exposure -- "
            "same formula and supervisory LGD as a corporate",
            pd_value=0.002,
            lgd=CRR_FIRB_LGD_SENIOR,
            maturity=FIRB_FIXED_MATURITY,
            scaling_factor=CRR_IRB_SCALING_FACTOR,
            correlation=correlation_corporate(0.002),
            exposure_class="institution",
            inputs={
                "pd_value": 0.002,
                "lgd": CRR_FIRB_LGD_SENIOR,
                "maturity": FIRB_FIXED_MATURITY,
            },
        ),
        _corporate(
            "ORC-086",
            "CRR",
            "FIRB",
            "CRR Art. 153(2): exposure to a large financial sector entity -- the "
            "coefficient of correlation is multiplied by 1.25",
            pd_value=pd_1pc,
            lgd=CRR_FIRB_LGD_SENIOR,
            maturity=FIRB_FIXED_MATURITY,
            scaling_factor=CRR_IRB_SCALING_FACTOR,
            correlation=correlation_corporate(pd_1pc) * FINANCIAL_SECTOR_CORRELATION_MULTIPLIER,
            inputs={
                "pd_value": pd_1pc,
                "lgd": CRR_FIRB_LGD_SENIOR,
                "maturity": FIRB_FIXED_MATURITY,
                "cp_is_financial_sector_entity": True,
                "requires_fi_scalar": True,
            },
        ),
        _sme_corporate_crr(),
    ]


# CRR Art. 153(4) states the SME size threshold in EUR while the size metric is
# reported in sterling, so the exact correlation depends on an FX rate that no
# article supplies. Both the size metric and the exposure are therefore chosen
# small enough that the conversion cannot change the answer:
#
#   * S = GBP 3m converts to at most EUR 3.9m at any plausible rate, so it sits
#     below the EUR 5m floor and the size adjustment is its maximum, a flat 0.04.
#   * E* = GBP 1m converts to at most EUR 1.3m, so it sits below the EUR 2.5m
#     Art. 501(1) threshold and the SME supporting factor is exactly 0.7619.
#
# That leaves an oracle that genuinely tests both articles and is independent of
# the run's FX rates.
CRR_SME_SIZE_METRIC_M = 3.0
CRR_SME_EAD = 1_000_000.0


def _sme_corporate_crr() -> dict[str, Any]:
    """F-IRB SME corporate: Art. 153(4) correlation and the Art. 501 factor."""
    pd_1pc = 0.01
    correlation = correlation_corporate_sme(pd_1pc, CRR_SME_SIZE_METRIC_M, floor=5.0, cap=50.0)
    factor = sme_supporting_factor(CRR_SME_EAD)
    risk_weight = irb_risk_weight_corporate(
        pd_value=pd_1pc,
        lgd=CRR_FIRB_LGD_SENIOR,
        maturity=FIRB_FIXED_MATURITY,
        correlation=correlation,
        scaling_factor=CRR_IRB_SCALING_FACTOR,
    )
    return oracle(
        oracle_id="ORC-087",
        phase=PHASE,
        framework="CRR",
        approach="FIRB",
        exposure_class="corporate_sme",
        regulation="CRR Art. 153(4) with Art. 501(1): F-IRB SME corporate below "
        "the EUR 5m size floor -- correlation reduced by the full 0.04, and the "
        "RWEA multiplied by the 0.7619 SME supporting factor",
        ead=CRR_SME_EAD,
        risk_weight=risk_weight,
        rwa=CRR_SME_EAD * risk_weight * factor,
        inputs={
            "exposure_class": "corporate_sme",
            "pd_value": pd_1pc,
            "lgd": SUPERVISORY,
            "lgd_post_crm": CRR_FIRB_LGD_SENIOR,
            "maturity": FIRB_FIXED_MATURITY,
            "is_sme": True,
            "turnover_m": CRR_SME_SIZE_METRIC_M,
        },
        intermediate={
            "pd_applied": pd_1pc,
            "firb_supervisory_lgd": CRR_FIRB_LGD_SENIOR,
            "lgd_applied": CRR_FIRB_LGD_SENIOR,
            "maturity_applied": FIRB_FIXED_MATURITY,
            "correlation_R": correlation,
            "maturity_adj_MA": maturity_adjustment(pd_1pc, FIRB_FIXED_MATURITY),
            "scaling_factor": CRR_IRB_SCALING_FACTOR,
            "supporting_factor": factor,
        },
        extra_expected={"supporting_factor": factor},
    )


# -----------------------------------------------------------------------------
# CRR -- retail (Art. 154)
# -----------------------------------------------------------------------------
def crr_retail() -> list[dict[str, Any]]:
    return [
        _retail(
            "ORC-088",
            "CRR",
            "CRR Art. 154(1): A-IRB other retail -- correlation curve on the 35 "
            "decay factor, no maturity adjustment, 1.06 scaling factor",
            pd_value=0.02,
            lgd=0.40,
            correlation=correlation_retail(0.02),
            scaling_factor=CRR_IRB_SCALING_FACTOR,
            exposure_class="retail_other",
            inputs={"pd_value": 0.02, "lgd": 0.40},
        ),
        _retail(
            "ORC-089",
            "CRR",
            "CRR Art. 154(3): retail secured by immovable property -- correlation is a flat 0.15",
            pd_value=0.01,
            lgd=0.20,
            correlation=CORRELATION_RETAIL_MORTGAGE,
            scaling_factor=CRR_IRB_SCALING_FACTOR,
            exposure_class="retail_mortgage",
            inputs={"pd_value": 0.01, "lgd": 0.20},
        ),
        _retail(
            "ORC-090",
            "CRR",
            "CRR Art. 154(4): qualifying revolving retail -- correlation is a flat 0.04",
            pd_value=0.03,
            lgd=0.60,
            correlation=CORRELATION_RETAIL_QRRE,
            scaling_factor=CRR_IRB_SCALING_FACTOR,
            exposure_class="retail_qrre",
            inputs={"pd_value": 0.03, "lgd": 0.60},
        ),
    ]


# -----------------------------------------------------------------------------
# PS1/26 -- corporates and institutions (Art. 153, 160, 161)
# -----------------------------------------------------------------------------
def b31_corporate() -> list[dict[str, Any]]:
    pd_1pc = 0.01
    return [
        _corporate(
            "ORC-091",
            "BASEL_3_1",
            "FIRB",
            "PS1/26 Art. 153(1)(c) with Art. 161(1)(aa): F-IRB corporate that is "
            "not a financial sector entity -- LGD 40% and no 1.06 scaling factor",
            pd_value=pd_1pc,
            lgd=B31_FIRB_LGD_SENIOR_CORPORATE,
            maturity=FIRB_FIXED_MATURITY,
            scaling_factor=B31_IRB_SCALING_FACTOR,
            correlation=correlation_corporate(pd_1pc),
            inputs={
                "pd_value": pd_1pc,
                "lgd": B31_FIRB_LGD_SENIOR_CORPORATE,
                "maturity": FIRB_FIXED_MATURITY,
            },
        ),
        _corporate(
            "ORC-092",
            "BASEL_3_1",
            "FIRB",
            "PS1/26 Art. 161(1)(a) with Art. 153(2): F-IRB senior unsecured "
            "exposure to a financial sector entity -- LGD stays at 45% and the "
            "correlation is multiplied by 1.25",
            pd_value=pd_1pc,
            lgd=B31_FIRB_LGD_SENIOR_FSE,
            maturity=FIRB_FIXED_MATURITY,
            scaling_factor=B31_IRB_SCALING_FACTOR,
            correlation=correlation_corporate(pd_1pc) * FINANCIAL_SECTOR_CORRELATION_MULTIPLIER,
            inputs={
                "pd_value": pd_1pc,
                "lgd": B31_FIRB_LGD_SENIOR_FSE,
                "maturity": FIRB_FIXED_MATURITY,
                "cp_is_financial_sector_entity": True,
                "requires_fi_scalar": True,
            },
        ),
        _corporate(
            "ORC-093",
            "BASEL_3_1",
            "FIRB",
            "PS1/26 Art. 161(1)(b): F-IRB corporate, subordinated without "
            "collateral recognised under the Foundation Collateral Method -> LGD 75%",
            pd_value=pd_1pc,
            lgd=B31_FIRB_LGD_SUBORDINATED,
            maturity=FIRB_FIXED_MATURITY,
            scaling_factor=B31_IRB_SCALING_FACTOR,
            correlation=correlation_corporate(pd_1pc),
            inputs={
                "pd_value": pd_1pc,
                "lgd": B31_FIRB_LGD_SUBORDINATED,
                "maturity": FIRB_FIXED_MATURITY,
                "seniority": "subordinated",
            },
        ),
        _corporate(
            "ORC-094",
            "BASEL_3_1",
            "FIRB",
            "PS1/26 Art. 160(1): a reported PD of 0.01% is lifted to the 0.05% "
            "corporate floor before the risk-weight formula is evaluated",
            pd_value=B31_PD_FLOOR_CORPORATE,
            lgd=B31_FIRB_LGD_SENIOR_CORPORATE,
            maturity=FIRB_FIXED_MATURITY,
            scaling_factor=B31_IRB_SCALING_FACTOR,
            correlation=correlation_corporate(B31_PD_FLOOR_CORPORATE),
            inputs={
                "pd_value": 0.0001,
                "lgd": B31_FIRB_LGD_SENIOR_CORPORATE,
                "maturity": FIRB_FIXED_MATURITY,
            },
        ),
        _corporate(
            "ORC-095",
            "BASEL_3_1",
            "AIRB",
            "PS1/26 Art. 161(5)(a): an own LGD estimate of 10% on an unsecured "
            "corporate exposure is lifted to the 25% A-IRB LGD input floor",
            pd_value=pd_1pc,
            lgd=B31_LGD_FLOOR_CORPORATE_UNSECURED,
            maturity=FIRB_FIXED_MATURITY,
            scaling_factor=B31_IRB_SCALING_FACTOR,
            correlation=correlation_corporate(pd_1pc),
            inputs={"pd_value": pd_1pc, "lgd": 0.10, "maturity": FIRB_FIXED_MATURITY},
        ),
        _corporate(
            "ORC-096",
            "BASEL_3_1",
            "AIRB",
            "PS1/26 Art. 153(1)(c): A-IRB corporate at M = 5 -- the maturity "
            "adjustment with no 1.06 scaling factor",
            pd_value=pd_1pc,
            lgd=0.30,
            maturity=5.0,
            scaling_factor=B31_IRB_SCALING_FACTOR,
            correlation=correlation_corporate(pd_1pc),
            inputs={"pd_value": pd_1pc, "lgd": 0.30, "maturity": 5.0},
        ),
        _corporate(
            "ORC-097",
            "BASEL_3_1",
            "FIRB",
            "PS1/26 Art. 153(4): SME corporate with total annual revenue "
            "S = GBP 22m -- correlation reduced by 0.04 * (1 - (S-4.4)/39.6)",
            pd_value=pd_1pc,
            lgd=B31_FIRB_LGD_SENIOR_CORPORATE,
            maturity=FIRB_FIXED_MATURITY,
            scaling_factor=B31_IRB_SCALING_FACTOR,
            correlation=correlation_corporate_sme(pd_1pc, 22.0, floor=4.4, cap=44.0),
            exposure_class="corporate_sme",
            inputs={
                "pd_value": pd_1pc,
                "lgd": B31_FIRB_LGD_SENIOR_CORPORATE,
                "maturity": FIRB_FIXED_MATURITY,
                "is_sme": True,
                "sme_size_metric_gbp": 22_000_000.0,
            },
            # PS1/26 restates Part Three of CRR; the SME supporting factor lives
            # in Part Ten Art. 501, which is in neither ps126app1.pdf nor the
            # comparison document. Whether it survives Basel 3.1 could not be
            # sourced here, so the correlation and risk weight are asserted and
            # the RWEA -- which would depend on that factor -- is published but
            # deliberately not compared.
            unasserted=("rwa",),
        ),
    ]


# -----------------------------------------------------------------------------
# PS1/26 -- retail (Art. 154, 163, 164)
# -----------------------------------------------------------------------------
def b31_retail() -> list[dict[str, Any]]:
    return [
        _retail(
            "ORC-098",
            "BASEL_3_1",
            "PS1/26 Art. 154(1)(b): A-IRB other retail -- same correlation curve "
            "as CRR but with no 1.06 scaling factor",
            pd_value=0.02,
            lgd=0.40,
            correlation=correlation_retail(0.02),
            scaling_factor=B31_IRB_SCALING_FACTOR,
            exposure_class="retail_other",
            inputs={"pd_value": 0.02, "lgd": 0.40},
        ),
        _retail(
            "ORC-099",
            "BASEL_3_1",
            "PS1/26 Art. 164(4)(b)(ii): an own LGD of 12% on an unsecured other "
            "retail exposure is lifted to the 30% LGD input floor",
            pd_value=0.02,
            lgd=B31_LGD_FLOOR_RETAIL_OTHER_UNSECURED,
            correlation=correlation_retail(0.02),
            scaling_factor=B31_IRB_SCALING_FACTOR,
            exposure_class="retail_other",
            inputs={"pd_value": 0.02, "lgd": 0.12},
        ),
        _uk_residential_mortgage_b31(),
        _retail(
            "ORC-101",
            "BASEL_3_1",
            "PS1/26 Art. 154(4) with Art. 163(1)(a) and Art. 164(4)(b)(i): "
            "non-transactor QRRE -- correlation 0.04, PD floored at 0.1% and LGD "
            "floored at 50%",
            pd_value=B31_PD_FLOOR_QRRE_NON_TRANSACTOR,
            lgd=B31_LGD_FLOOR_RETAIL_QRRE,
            correlation=CORRELATION_RETAIL_QRRE,
            scaling_factor=B31_IRB_SCALING_FACTOR,
            exposure_class="retail_qrre",
            inputs={"pd_value": 0.0002, "lgd": 0.35, "is_qrre_transactor": False},
        ),
        _retail(
            "ORC-102",
            "BASEL_3_1",
            "PS1/26 Art. 163(1)(c): a reported PD of 0.02% on other retail is "
            "lifted to the 0.05% floor",
            pd_value=B31_PD_FLOOR_RETAIL_OTHER,
            lgd=0.40,
            correlation=correlation_retail(B31_PD_FLOOR_RETAIL_OTHER),
            scaling_factor=B31_IRB_SCALING_FACTOR,
            exposure_class="retail_other",
            inputs={"pd_value": 0.0002, "lgd": 0.40},
        ),
    ]


def _uk_residential_mortgage_b31() -> dict[str, Any]:
    """A-IRB UK residential mortgage where the Art. 154(4A)(b) floor binds.

    The 5% LGD input floor (Art. 164(4)(a)) keeps the modelled risk weight far
    below 10%, so the RWEA floor is what actually sets the answer. The risk
    weight itself stays at the modelled value -- Art. 154(4A)(b) is worded as an
    increase to the risk-weighted exposure amount, not to the risk weight.
    """
    pd_value = 0.01
    lgd = B31_LGD_FLOOR_RETAIL_RRE
    risk_weight = irb_risk_weight_retail(
        pd_value=pd_value,
        lgd=lgd,
        correlation=CORRELATION_RETAIL_MORTGAGE,
        scaling_factor=B31_IRB_SCALING_FACTOR,
    )
    modelled_rwea = EAD * risk_weight
    floor_rwea = EAD * B31_RETAIL_UK_RRE_RWEA_FLOOR
    return oracle(
        oracle_id="ORC-100",
        phase=PHASE,
        framework="BASEL_3_1",
        approach="AIRB",
        exposure_class="retail_mortgage",
        regulation="PS1/26 Art. 154(3), Art. 164(4)(a) and Art. 154(4A)(b): "
        "retail secured by UK residential immovable property -- correlation "
        "0.15, a 5% LGD input floor, and an RWEA floor of 10% of the exposure "
        "value, which binds here",
        ead=EAD,
        risk_weight=risk_weight,
        rwa=max(modelled_rwea, floor_rwea),
        inputs={"exposure_class": "retail_mortgage", "pd_value": pd_value, "lgd": 0.02},
        intermediate={
            "pd_applied": pd_value,
            "lgd_applied": lgd,
            "correlation_R": CORRELATION_RETAIL_MORTGAGE,
            "scaling_factor": B31_IRB_SCALING_FACTOR,
            "modelled_rwea": modelled_rwea,
            "rwea_floor": floor_rwea,
            "mortgage_rwea_floor_adjustment": floor_rwea - modelled_rwea,
        },
    )


# -----------------------------------------------------------------------------
# Art. 154(4A)(b) -- the scope of the 10% RWEA floor
# -----------------------------------------------------------------------------
# Verbatim from ps126app1.pdf p104, Art. 154(4A):
#
#   "An institution shall increase the total risk-weighted exposure amounts
#    calculated under paragraphs 1, 3 and 4 for retail exposures to reflect: ...
#    (b) any amount needed to ensure that risk-weighted exposure amounts for
#    NON-DEFAULTED exposures which are RETAIL exposures secured by UK
#    RESIDENTIAL immovable property are greater than or equal to 10% of the
#    exposure value for such exposures ..."
#
# Three cumulative conditions, so three ways to be out of scope. ORC-100 pins
# the in-scope case where the floor binds; the three oracles below pin each
# out-of-scope limb. Each asserts ``mortgage_rwea_floor_adjustment == 0``, which
# is derivable straight from the article without having to settle what the risk
# weight should be.
def floor_scope() -> list[dict[str, Any]]:
    return [_floor_scope_defaulted(), _floor_scope_commercial(), _floor_scope_non_uk()]


def _floor_scope_defaulted() -> dict[str, Any]:
    """Limb 1: the floor reaches only NON-DEFAULTED exposures."""
    lgd = B31_LGD_FLOOR_RETAIL_RRE
    beel = B31_LGD_FLOOR_RETAIL_RRE
    risk_weight = irb_risk_weight_defaulted_airb(lgd, beel)
    return oracle(
        oracle_id="ORC-140",
        phase=PHASE,
        framework="BASEL_3_1",
        approach="AIRB",
        exposure_class="retail_mortgage",
        regulation="PS1/26 Art. 154(1)(a) with Art. 154(4A)(b): a DEFAULTED "
        "retail residential mortgage takes RW = max(0, 12.5 * (LGD - BEEL)), and "
        "the 10% RWEA floor does not reach it -- Art. 154(4A)(b) is expressly "
        "confined to non-defaulted exposures",
        ead=EAD,
        risk_weight=risk_weight,
        rwa=EAD * risk_weight,
        inputs={
            "exposure_class": "retail_mortgage",
            "pd_value": 1.0,
            "lgd": lgd,
            "beel": beel,
            "is_defaulted": True,
        },
        intermediate={
            "lgd_applied": lgd,
            "beel_applied": beel,
            "mortgage_rwea_floor_adjustment": 0.0,
        },
    )


def _floor_scope_commercial() -> dict[str, Any]:
    """Limb 2: the floor reaches only exposures secured by RESIDENTIAL property."""
    return oracle(
        oracle_id="ORC-141",
        phase=PHASE,
        framework="BASEL_3_1",
        approach="AIRB",
        exposure_class="commercial_mortgage",
        regulation="PS1/26 Art. 154(4A)(b): the 10% RWEA floor reaches only "
        "exposures secured by UK RESIDENTIAL immovable property, so a "
        "commercial real estate exposure is out of scope whatever its risk weight",
        ead=EAD,
        risk_weight=0.0,
        rwa=0.0,
        inputs={
            "exposure_class": "commercial_mortgage",
            "pd_value": 0.0005,
            "lgd": 0.05,
        },
        intermediate={"mortgage_rwea_floor_adjustment": 0.0},
        # The correlation for a commercial-real-estate row reaching the IRB
        # RETAIL branch is a classification question Art. 154 does not settle:
        # Art. 154(3) gives R = 0.15 to "retail exposures secured by immovable
        # property", and whether a commercial mortgage is a retail exposure at
        # all depends on Art. 147(5), not on Art. 154. The risk weight and RWEA
        # are therefore published as zero placeholders and NOT asserted -- only
        # the floor-scope claim, which the article does settle, is compared.
        unasserted=("risk_weight", "rwa"),
    )


def _floor_scope_non_uk() -> dict[str, Any]:
    """Limb 3: the floor reaches only property located in the UK."""
    pd_value = 0.01
    lgd = B31_LGD_FLOOR_RETAIL_RRE
    risk_weight = irb_risk_weight_retail(
        pd_value=pd_value,
        lgd=lgd,
        correlation=CORRELATION_RETAIL_MORTGAGE,
        scaling_factor=B31_IRB_SCALING_FACTOR,
    )
    return oracle(
        oracle_id="ORC-142",
        phase=PHASE,
        framework="BASEL_3_1",
        approach="AIRB",
        exposure_class="retail_mortgage",
        regulation="PS1/26 Art. 154(4A)(b): the 10% RWEA floor reaches only "
        "exposures secured by UK residential immovable property -- identical to "
        "ORC-100 but for property outside the UK, so the modelled RWEA stands",
        ead=EAD,
        risk_weight=risk_weight,
        rwa=EAD * risk_weight,
        inputs={
            "exposure_class": "retail_mortgage",
            "pd_value": pd_value,
            "lgd": 0.02,
            "country_code": "US",
        },
        intermediate={
            "pd_applied": pd_value,
            "lgd_applied": lgd,
            "correlation_R": CORRELATION_RETAIL_MORTGAGE,
            "mortgage_rwea_floor_adjustment": 0.0,
        },
    )


# -----------------------------------------------------------------------------
# Defaulted exposures (Art. 153(1)(b), 154(1)(a))
# -----------------------------------------------------------------------------
def defaulted() -> list[dict[str, Any]]:
    lgd = 0.45
    beel = 0.30
    return [
        oracle(
            oracle_id="ORC-103",
            phase=PHASE,
            framework="CRR",
            approach="AIRB",
            exposure_class="retail_other",
            regulation="CRR Art. 154(1)(i): defaulted retail exposure under own "
            "LGD estimates -> RW = max(0, 12.5 * (LGD - EL_BE))",
            ead=EAD,
            risk_weight=irb_risk_weight_defaulted_airb(lgd, beel),
            inputs={
                "exposure_class": "retail_other",
                "pd_value": 1.0,
                "lgd": lgd,
                "beel": beel,
                "is_defaulted": True,
            },
            intermediate={"lgd_applied": lgd, "beel_applied": beel},
        ),
        oracle(
            oracle_id="ORC-104",
            phase=PHASE,
            framework="BASEL_3_1",
            approach="FIRB",
            exposure_class="corporate",
            regulation="PS1/26 Art. 153(1)(b): defaulted corporate exposure under "
            "the Foundation IRB Approach -> RW = 0 (the loss is carried by the "
            "expected loss amount, not the risk weight)",
            ead=EAD,
            risk_weight=0.0,
            inputs={
                "exposure_class": "corporate",
                "pd_value": 1.0,
                "lgd": SUPERVISORY,
                "lgd_post_crm": B31_FIRB_LGD_SENIOR_CORPORATE,
                "is_defaulted": True,
            },
        ),
    ]


# -----------------------------------------------------------------------------
# FS-1 -- the priced facility-share candidate, both regimes
# -----------------------------------------------------------------------------
#
# WHAT LAYER THIS EXERCISES, stated first because it bounds the case.
# ``tests/oracle/drivers.py`` bypasses the hierarchy, the classifier and the CRM
# stage and drives one explicit row into a single calculator branch. It therefore
# CANNOT reach the facility-share fan-out (a hierarchy emission), the resolution
# step that picks a winner (an aggregator step) or the output floor (a portfolio
# quantity). These two records referee only the PER-CANDIDATE PRICING that the
# rest of the FS-1 hand calculation rests on: the risk weight that member's
# undrawn candidate row is priced at once it exists. The pipeline-level
# acceptance tests in tests/acceptance/test_fs1_facility_share_fanout.py are the
# real referee for the mechanism.
#
# The two exposure values differ DELIBERATELY -- 300,000 under CRR and 200,000
# under Basel 3.1 -- because they are the same 400,000 of undrawn headroom
# through two different conversion factors. CRR Art. 166(8)(d) gives an F-IRB
# credit line its own 75%; PS1/26 Art. 166C(1) routes F-IRB to the Standardised
# Approach factor instead, which for this medium-risk commitment is 50%. Pinning
# both amounts here makes that divergence a checked fact rather than an
# assumption of the acceptance tests.
#
# The internal PD of 0.08% clears both PD input floors (CRR 0.03%, PS1/26
# 0.05%), so the floor is a non-binding pass-through and the risk weight is a
# function of the fixture's own input rather than of the floor.

#: The undrawn headroom of the FS-1 shared facility, and the two conversion
#: factors it passes through. Stated as an amount and a factor rather than as
#: two exposure values so the Art. 166C divergence is visible in the arithmetic.
FS1_HEADROOM = 400_000.0
FS1_CRR_CREDIT_LINE_CCF = 0.75
FS1_SA_MEDIUM_RISK_CCF = 0.50

#: The F-IRB member's internal PD on the FS-1 portfolio.
FS1_PD = 0.0008


def facility_share_candidate() -> list[dict[str, Any]]:
    """The FS-1 F-IRB candidate row, priced under each regime."""
    return [
        _corporate(
            "ORC-FS1-CRR",
            "CRR",
            "FIRB",
            "CRR Art. 153(1) IRB risk weight with the 1.06 scaling factor; "
            "Art. 161(1)(a) senior unsecured supervisory LGD 45%; Art. 162(2) "
            "firm-estimated M = 2.5; Art. 160(1) PD floor 0.03% (non-binding); "
            "Art. 166(8)(d) credit-line conversion factor 75% on 400,000 of "
            "undrawn commitment",
            pd_value=FS1_PD,
            lgd=CRR_FIRB_LGD_SENIOR,
            maturity=FIRB_FIXED_MATURITY,
            scaling_factor=CRR_IRB_SCALING_FACTOR,
            correlation=correlation_corporate(FS1_PD),
            ead=FS1_HEADROOM * FS1_CRR_CREDIT_LINE_CCF,
            inputs={
                "pd_value": FS1_PD,
                "lgd": CRR_FIRB_LGD_SENIOR,
                "maturity": FIRB_FIXED_MATURITY,
            },
        ),
        _corporate(
            "ORC-FS1-B31",
            "BASEL_3_1",
            "FIRB",
            "PS1/26 Art. 153(1) IRB risk weight with no 1.06 scaling factor; "
            "Art. 161(1)(aa) non-financial-sector senior unsecured supervisory "
            "LGD 40%; Art. 162(2A) firm-estimated M = 2.5; Art. 160(1) PD floor "
            "0.05% (non-binding); Art. 166C(1) routes the F-IRB conversion "
            "factor to the Standardised Art. 111 medium-risk 50% on 400,000 of "
            "undrawn commitment",
            pd_value=FS1_PD,
            lgd=B31_FIRB_LGD_SENIOR_CORPORATE,
            maturity=FIRB_FIXED_MATURITY,
            scaling_factor=B31_IRB_SCALING_FACTOR,
            correlation=correlation_corporate(FS1_PD),
            ead=FS1_HEADROOM * FS1_SA_MEDIUM_RISK_CCF,
            inputs={
                "pd_value": FS1_PD,
                "lgd": B31_FIRB_LGD_SENIOR_CORPORATE,
                "maturity": FIRB_FIXED_MATURITY,
            },
        ),
    ]


def all_oracles() -> list[dict[str, Any]]:
    return [
        *crr_corporate(),
        *crr_retail(),
        *b31_corporate(),
        *b31_retail(),
        *defaulted(),
        *floor_scope(),
        *facility_share_candidate(),
    ]
