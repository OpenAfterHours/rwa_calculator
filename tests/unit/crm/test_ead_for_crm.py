"""
Tests for the ead_for_crm and effective_ccf columns.

CRR Art. 223(4) and PS1/26 Art. 223(4) both require that, when computing
the exposure value used for CRM (financial collateral via FCCM, other
eligible collateral via the Foundation Collateral Method, and unfunded
credit protection via Art. 235/236), off-balance-sheet items shall be
valued at 100% of nominal — overriding the regulatory CCF.  The actual
CCF only re-couples afterwards: under SA per Art. 228(1) the CCF is
applied to E*; under FIRB the actual CCF stays in EAD but is absent
from the LGD* ratio.

The pipeline therefore carries two parallel quantities:

- ``ead_gross``       (post-CCF, actual EAD basis)
- ``ead_for_crm``     (CCF=100 % override, used to net collateral and to
                       form E in the LGD* and Art. 230 thresholds)

The accompanying ``effective_ccf`` re-couples the two for the SA
post-collateral EAD.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    ClassifiedExposuresBundle,
    create_empty_counterparty_lookup,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType, PermissionMode
from rwa_calc.engine.crm.processor import CRMProcessor

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=date(2024, 12, 31),
        permission_mode=PermissionMode.IRB,
    )


@pytest.fixture
def crr_processor() -> CRMProcessor:
    return CRMProcessor(is_basel_3_1=False)


def _bundle(rows: dict[str, list]) -> ClassifiedExposuresBundle:
    """Build a minimal ClassifiedExposuresBundle from a per-row dict."""
    n = len(next(iter(rows.values())))
    defaults: dict[str, list] = {
        "exposure_type": ["loan"] * n,
        "drawn_amount": [0.0] * n,
        "interest": [0.0] * n,
        "undrawn_amount": [0.0] * n,
        "nominal_amount": [0.0] * n,
        "risk_type": [None] * n,
        "ccf_modelled": [None] * n,
        "is_short_term_trade_lc": [False] * n,
        "product_type": ["TERM_LOAN"] * n,
        "value_date": [date(2024, 1, 1)] * n,
        "book_code": ["BOOK1"] * n,
        "lgd": [0.45] * n,
        "exposure_class": ["CORPORATE"] * n,
        "approach": [ApproachType.FIRB.value] * n,
        "currency": ["GBP"] * n,
        "maturity_date": [date(2034, 12, 31)] * n,
        "seniority": ["senior"] * n,
    }
    for k, v in defaults.items():
        rows.setdefault(k, v)

    lf = pl.DataFrame(rows).lazy()
    return ClassifiedExposuresBundle(
        all_exposures=lf,
        equity_exposures=None,
        collateral=None,
        guarantees=None,
        provisions=None,
        counterparty_lookup=create_empty_counterparty_lookup(),
        classification_audit=None,
        classification_errors=[],
    )


def _run(
    processor: CRMProcessor,
    config: CalculationConfig,
    bundle: ClassifiedExposuresBundle,
) -> pl.DataFrame:
    collected = processor.get_crm_unified_bundle(bundle, config).exposures.collect()
    assert isinstance(collected, pl.DataFrame)
    return collected


# --------------------------------------------------------------------------- #
# Pure on-balance-sheet
# --------------------------------------------------------------------------- #


def test_ead_for_crm_pure_on_bs(crr_processor: CRMProcessor, crr_config: CalculationConfig) -> None:
    """A drawn-only loan: ead_for_crm == on_bs_for_ead == ead_gross."""
    bundle = _bundle(
        {
            "exposure_reference": ["LN1"],
            "counterparty_reference": ["CP1"],
            "drawn_amount": [100.0],
            "nominal_amount": [0.0],
            "risk_type": ["fr"],
        }
    )

    df = _run(crr_processor, crr_config, bundle)

    assert df["ead_for_crm"][0] == pytest.approx(100.0)
    assert df["on_bs_for_ead"][0] == pytest.approx(100.0)
    assert df["ead_gross"][0] == pytest.approx(100.0)
    assert df["effective_ccf"][0] == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# Pure off-balance-sheet
# --------------------------------------------------------------------------- #


def test_ead_for_crm_pure_off_bs_independent_of_ccf(
    crr_processor: CRMProcessor, crr_config: CalculationConfig
) -> None:
    """A pure off-BS contingent: ead_for_crm == nominal regardless of CCF.

    Two SA contingents with identical 100m nominal but different CCFs (50% vs
    100% under CRR Art. 111) produce identical ead_for_crm; only ead_gross
    diverges.
    """
    bundle = _bundle(
        {
            "exposure_reference": ["CONT_MR", "CONT_FR"],
            "counterparty_reference": ["CP1", "CP2"],
            "exposure_type": ["contingent", "contingent"],
            "drawn_amount": [0.0, 0.0],
            "nominal_amount": [100.0, 100.0],
            "risk_type": ["mr", "fr"],  # SA: 50% CCF vs 100% CCF
            "approach": [ApproachType.SA.value, ApproachType.SA.value],
        }
    )

    df = _run(crr_processor, crr_config, bundle).sort("exposure_reference")

    # Both have ead_for_crm = 100 (CCF=100% override per Art. 223(4))
    assert df["ead_for_crm"].to_list() == pytest.approx([100.0, 100.0])

    fr_row = df.filter(pl.col("exposure_reference") == "CONT_FR")
    mr_row = df.filter(pl.col("exposure_reference") == "CONT_MR")
    assert fr_row["ead_gross"][0] == pytest.approx(100.0)
    assert mr_row["ead_gross"][0] == pytest.approx(50.0)
    assert fr_row["effective_ccf"][0] == pytest.approx(1.0)
    assert mr_row["effective_ccf"][0] == pytest.approx(0.5)


def test_ead_for_crm_firb_off_bs(
    crr_processor: CRMProcessor, crr_config: CalculationConfig
) -> None:
    """FIRB off-BS exposure: ead_for_crm = nominal, ead_gross = nominal × FIRB CCF.

    Phil's worked example: 100m nominal, FIRB MR commitment (Art. 166(8)(d) -> 75%
    CCF).  ead_for_crm should be 100m (CCF=100% override per Art. 223(4)),
    ead_gross should be 75m, effective_ccf should be 0.75.
    """
    bundle = _bundle(
        {
            "exposure_reference": ["FIRB_OBS"],
            "counterparty_reference": ["CP1"],
            "exposure_type": ["contingent"],
            "drawn_amount": [0.0],
            "nominal_amount": [100.0],
            "risk_type": ["mr"],
            "approach": [ApproachType.FIRB.value],
            "is_obs_commitment": [True],
        }
    )

    df = _run(crr_processor, crr_config, bundle)

    assert df["ead_for_crm"][0] == pytest.approx(100.0)
    assert df["ead_gross"][0] == pytest.approx(75.0)
    assert df["effective_ccf"][0] == pytest.approx(0.75)


# --------------------------------------------------------------------------- #
# Mixed on-BS + off-BS row
# --------------------------------------------------------------------------- #


def test_ead_for_crm_mixed_row(crr_processor: CRMProcessor, crr_config: CalculationConfig) -> None:
    """Mixed row (50m drawn + 50m undrawn @50% SA CCF): blended effective_ccf."""
    bundle = _bundle(
        {
            "exposure_reference": ["MIX1"],
            "counterparty_reference": ["CP1"],
            "exposure_type": ["loan"],
            "drawn_amount": [50.0],
            "nominal_amount": [50.0],
            "approach": [ApproachType.SA.value],
            "risk_type": ["mr"],  # 50% CCF
        }
    )

    df = _run(crr_processor, crr_config, bundle)

    # ead_for_crm = on_bal + nominal_after_provision = 50 + 50 = 100
    assert df["ead_for_crm"][0] == pytest.approx(100.0)
    # ead_gross  = on_bal + nominal × CCF       = 50 + 25 = 75
    assert df["ead_gross"][0] == pytest.approx(75.0)
    # effective_ccf = ead_pre_crm / ead_for_crm = 75 / 100 = 0.75
    assert df["effective_ccf"][0] == pytest.approx(0.75)


# --------------------------------------------------------------------------- #
# Provision on nominal
# --------------------------------------------------------------------------- #


def test_ead_for_crm_after_provision_on_nominal(
    crr_processor: CRMProcessor, crr_config: CalculationConfig
) -> None:
    """A provision on the off-BS nominal should reduce ead_for_crm in step."""
    bundle = _bundle(
        {
            "exposure_reference": ["CONT1"],
            "counterparty_reference": ["CP1"],
            "exposure_type": ["contingent"],
            "drawn_amount": [0.0],
            "nominal_amount": [100.0],
            "nominal_after_provision": [80.0],  # 20m provision on the off-BS leg
            "provision_on_drawn": [0.0],
            "provision_allocated": [20.0],
            "provision_deducted": [20.0],
            "provision_on_nominal": [20.0],
            "risk_type": ["fr"],
        }
    )

    df = _run(crr_processor, crr_config, bundle)

    # ead_for_crm = on_bal + nominal_after_provision = 0 + 80 = 80
    assert df["ead_for_crm"][0] == pytest.approx(80.0)


# --------------------------------------------------------------------------- #
# Zero-nominal divide-by-zero guard
# --------------------------------------------------------------------------- #


def test_effective_ccf_zero_nominal_defaults_to_one(
    crr_processor: CRMProcessor, crr_config: CalculationConfig
) -> None:
    """Row with no exposure value yields effective_ccf == 1.0 (no divide-by-zero)."""
    bundle = _bundle(
        {
            "exposure_reference": ["EMPTY1"],
            "counterparty_reference": ["CP1"],
            "drawn_amount": [0.0],
            "nominal_amount": [0.0],
            "risk_type": ["fr"],
        }
    )

    df = _run(crr_processor, crr_config, bundle)

    assert df["ead_for_crm"][0] == pytest.approx(0.0)
    assert df["effective_ccf"][0] == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# End-to-end pin: Phil's worked example (FIRB cash, off-BS, 75% CCF)
# --------------------------------------------------------------------------- #


def _bundle_with_collateral(
    exposure_rows: dict[str, list],
    collateral_rows: dict[str, list],
) -> ClassifiedExposuresBundle:
    """Bundle helper that attaches collateral and minimal lookup."""
    bundle = _bundle(exposure_rows)

    n = len(next(iter(collateral_rows.values())))
    coll_defaults = {
        "issuer_type": [""] * n,
        "issuer_cqs": [1] * n,
        "is_main_index": [False] * n,
        "is_eligible_financial_collateral": [True] * n,
        "value_after_haircut": [None] * n,
        "value_after_maturity_adj": [None] * n,
        "residual_maturity_years": [10.0] * n,
    }
    for k, v in coll_defaults.items():
        collateral_rows.setdefault(k, v)
    coll_lf = pl.DataFrame(collateral_rows).lazy()

    return ClassifiedExposuresBundle(
        all_exposures=bundle.all_exposures,
        equity_exposures=None,
        collateral=coll_lf,
        guarantees=None,
        provisions=None,
        counterparty_lookup=bundle.counterparty_lookup,
        classification_audit=None,
        classification_errors=[],
    )


def test_firb_off_bs_cash_collateral_phils_example(
    crr_processor: CRMProcessor, crr_config: CalculationConfig
) -> None:
    """
    Phil's worked example end-to-end (CRR Art. 223(4) + Art. 228(2)).

    100m off-BS FIRB exposure, 75% CCF (medium-risk commitment, Art. 166(8)(d)),
    50m cash collateral, senior unsecured (LGDU=45%), cash LGDS=0%.

    Expected (regulatorily correct):
        ead_for_crm = 100m, ead_gross = 75m, effective_ccf = 0.75
        LGD* = (0% × 50 + 45% × 50) / 100 = 22.5%
    Pre-fix code returned LGD* = 15% (incorrectly using post-CCF EAD as E).
    """
    bundle = _bundle_with_collateral(
        exposure_rows={
            "exposure_reference": ["PHIL_FIRB"],
            "counterparty_reference": ["CP1"],
            "exposure_type": ["contingent"],
            "drawn_amount": [0.0],
            "nominal_amount": [100.0e6],
            "risk_type": ["mr"],
            "approach": [ApproachType.FIRB.value],
            "is_obs_commitment": [True],
            "lgd": [0.45],
        },
        collateral_rows={
            "collateral_reference": ["COLL_CASH"],
            "beneficiary_reference": ["PHIL_FIRB"],
            "beneficiary_type": ["loan"],
            "collateral_type": ["cash"],
            "market_value": [50.0e6],
            "currency": ["GBP"],
            "maturity_date": [date(2034, 12, 31)],
        },
    )

    df = crr_processor.get_crm_unified_bundle(bundle, crr_config).exposures.collect()

    assert df["ead_for_crm"][0] == pytest.approx(100.0e6)
    assert df["ead_gross"][0] == pytest.approx(75.0e6)
    assert df["effective_ccf"][0] == pytest.approx(0.75)
    assert df["lgd_post_crm"][0] == pytest.approx(0.225, abs=1e-6)


def test_sa_off_bs_cash_collateral_post_ccf_recoupling(
    crr_processor: CRMProcessor, crr_config: CalculationConfig
) -> None:
    """
    SA off-BS exposure with cash collateral (CRR Art. 228(1)).

    100m off-BS, 50% CCF (medium_risk under SA), 30m cash collateral.

    Expected:
        ead_for_crm = 100m, ead_gross = 50m, effective_ccf = 0.5
        E* = max(0, 100 − 30) = 70m
        ead_after_collateral = E* × CCF = 70 × 0.5 = 35m
    Pre-fix code returned ead_after_collateral = max(0, 50 − 30) = 20m.
    """
    bundle = _bundle_with_collateral(
        exposure_rows={
            "exposure_reference": ["SA_OBS"],
            "counterparty_reference": ["CP1"],
            "exposure_type": ["contingent"],
            "drawn_amount": [0.0],
            "nominal_amount": [100.0e6],
            "risk_type": ["mr"],
            "approach": [ApproachType.SA.value],
            "lgd": [0.45],
        },
        collateral_rows={
            "collateral_reference": ["COLL_CASH_SA"],
            "beneficiary_reference": ["SA_OBS"],
            "beneficiary_type": ["loan"],
            "collateral_type": ["cash"],
            "market_value": [30.0e6],
            "currency": ["GBP"],
            "maturity_date": [date(2034, 12, 31)],
        },
    )

    df = crr_processor.get_crm_unified_bundle(bundle, crr_config).exposures.collect()

    assert df["ead_for_crm"][0] == pytest.approx(100.0e6)
    assert df["ead_gross"][0] == pytest.approx(50.0e6)
    assert df["effective_ccf"][0] == pytest.approx(0.5)
    assert df["ead_after_collateral"][0] == pytest.approx(35.0e6, abs=1.0)
