"""
Parity tests: data/tables/ DataFrames must be derived from their dict constants.

Guards against regressions of the pattern fixed in commit introducing
`_build_cqs_rw_df` / `_build_haircut_df` / `_build_firb_lgd_df`. If a future
change hardcodes a numeric value in a DataFrame builder instead of reading it
from the authoritative constant dict, the corresponding test here will fail.

The authoritative dict for each DataFrame:

| DataFrame builder                         | Authoritative dict(s)                                 |
|-------------------------------------------|-------------------------------------------------------|
| crr._create_cgcb_df                       | CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS                |
| crr._create_institution_df(True)          | INSTITUTION_RISK_WEIGHTS_UK                           |
| crr._create_institution_df(False)         | INSTITUTION_RISK_WEIGHTS_STANDARD                     |
| crr._create_pse_df                        | PSE_RISK_WEIGHTS_OWN_RATING                           |
| crr._create_rgla_df                       | RGLA_RISK_WEIGHTS_OWN_RATING                          |
| crr._create_mdb_df                        | MDB_RISK_WEIGHTS_TABLE_2B                             |
| crr._create_corporate_df                  | CORPORATE_RISK_WEIGHTS                                |
| crr._create_retail_df                     | RETAIL_RISK_WEIGHT                                    |
| crr._create_residential_mortgage_df       | RESIDENTIAL_MORTGAGE_PARAMS                           |
| crr._create_commercial_re_df              | COMMERCIAL_RE_PARAMS                                  |
| crr._create_covered_bond_df               | COVERED_BOND_RISK_WEIGHTS                             |
| b31._create_b31_corporate_df              | B31_CORPORATE_RISK_WEIGHTS                            |
| b31._create_b31_covered_bond_df           | B31_COVERED_BOND_RISK_WEIGHTS                         |
| haircuts._create_crr_haircut_df           | COLLATERAL_HAIRCUTS                                   |
| haircuts._create_basel31_haircut_df       | BASEL31_COLLATERAL_HAIRCUTS                           |
| firb_lgd._create_firb_lgd_df              | FIRB_SUPERVISORY_LGD + OC ratios + min thresholds     |
| firb_lgd._create_b31_firb_lgd_df          | BASEL31_FIRB_SUPERVISORY_LGD + OC ratios + thresholds |
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from rwa_calc.data.tables import b31_risk_weights as b31
from rwa_calc.data.tables import crr_risk_weights as crr
from rwa_calc.data.tables import firb_lgd, haircuts
from rwa_calc.domain.enums import CQS

# =============================================================================
# CQS-based risk-weight DataFrames (crr_risk_weights.py)
# =============================================================================

_CQS_CASES: list[tuple[str, object, dict[CQS, Decimal], str]] = [
    (
        "cgcb",
        crr._create_cgcb_df(),
        crr.CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS,
        "CENTRAL_GOVT_CENTRAL_BANK",
    ),
    ("inst_uk", crr._create_institution_df(True), crr.INSTITUTION_RISK_WEIGHTS_UK, "INSTITUTION"),
    (
        "inst_std",
        crr._create_institution_df(False),
        crr.INSTITUTION_RISK_WEIGHTS_STANDARD,
        "INSTITUTION",
    ),
    ("pse", crr._create_pse_df(), crr.PSE_RISK_WEIGHTS_OWN_RATING, "PSE"),
    ("rgla", crr._create_rgla_df(), crr.RGLA_RISK_WEIGHTS_OWN_RATING, "RGLA"),
    ("mdb", crr._create_mdb_df(), crr.MDB_RISK_WEIGHTS_TABLE_2B, "MDB"),
    ("corporate", crr._create_corporate_df(), crr.CORPORATE_RISK_WEIGHTS, "CORPORATE"),
    ("covered_bond", crr._create_covered_bond_df(), crr.COVERED_BOND_RISK_WEIGHTS, "COVERED_BOND"),
]


@pytest.mark.parametrize("name,df,source_dict,exposure_class", _CQS_CASES)
def test_cqs_dataframe_matches_source_dict(name, df, source_dict, exposure_class):
    """Each row's risk_weight equals float(source_dict[CQS(cqs)])."""
    rows = df.to_dicts()
    assert rows, f"{name}: DataFrame is empty"
    for row in rows:
        assert row["exposure_class"] == exposure_class
        cqs_val = row["cqs"]
        cqs_key = CQS.UNRATED if cqs_val is None else CQS(cqs_val)
        assert cqs_key in source_dict, f"{name}: CQS {cqs_key} not in source dict"
        expected = float(source_dict[cqs_key])
        assert row["risk_weight"] == pytest.approx(expected), (
            f"{name}: cqs={cqs_val} DataFrame value {row['risk_weight']} != "
            f"source dict value {expected}"
        )


def test_retail_df_matches_constant():
    df = crr._create_retail_df()
    assert df.shape == (1, 3)
    assert df["risk_weight"][0] == pytest.approx(float(crr.RETAIL_RISK_WEIGHT))


def test_residential_mortgage_df_matches_params():
    df = crr._create_residential_mortgage_df()
    p = crr.RESIDENTIAL_MORTGAGE_PARAMS
    row = df.row(0, named=True)
    assert row["ltv_threshold"] == pytest.approx(float(p["ltv_threshold"]))
    assert row["rw_low_ltv"] == pytest.approx(float(p["rw_low_ltv"]))
    assert row["rw_high_ltv"] == pytest.approx(float(p["rw_high_ltv"]))


def test_commercial_re_df_matches_params():
    df = crr._create_commercial_re_df()
    p = crr.COMMERCIAL_RE_PARAMS
    row = df.row(0, named=True)
    assert row["ltv_threshold"] == pytest.approx(float(p["ltv_threshold"]))
    assert row["rw_low_ltv"] == pytest.approx(float(p["rw_low_ltv"]))
    assert row["rw_standard"] == pytest.approx(float(p["rw_standard"]))


# =============================================================================
# Basel 3.1 CQS-based risk-weight DataFrames (b31_risk_weights.py)
# =============================================================================

_B31_CQS_CASES: list[tuple[str, object, dict[int | None, Decimal], str]] = [
    ("b31_corporate", b31._create_b31_corporate_df(), b31.B31_CORPORATE_RISK_WEIGHTS, "CORPORATE"),
    (
        "b31_covered_bond",
        b31._create_b31_covered_bond_df(),
        b31.B31_COVERED_BOND_RISK_WEIGHTS,
        "COVERED_BOND",
    ),
]


@pytest.mark.parametrize("name,df,source_dict,exposure_class", _B31_CQS_CASES)
def test_b31_cqs_dataframe_matches_source_dict(name, df, source_dict, exposure_class):
    """Each row's risk_weight equals float(source_dict[cqs])."""
    for row in df.to_dicts():
        assert row["exposure_class"] == exposure_class
        key = row["cqs"]  # already int | None matching dict key type
        assert key in source_dict, f"{name}: key {key!r} missing from source dict"
        assert row["risk_weight"] == pytest.approx(float(source_dict[key]))


# =============================================================================
# Haircut DataFrames (haircuts.py)
# =============================================================================

_HAIRCUT_CASES: list[tuple[str, object, tuple, dict[str, Decimal]]] = [
    (
        "haircut_crr",
        haircuts._create_crr_haircut_df(),
        haircuts._CRR_HAIRCUT_ROW_SPECS,
        haircuts.COLLATERAL_HAIRCUTS,
    ),
    (
        "haircut_b31",
        haircuts._create_basel31_haircut_df(),
        haircuts._B31_HAIRCUT_ROW_SPECS,
        haircuts.BASEL31_COLLATERAL_HAIRCUTS,
    ),
]


@pytest.mark.parametrize("name,df,specs,source_dict", _HAIRCUT_CASES)
def test_haircut_dataframe_matches_source_dict(name, df, specs, source_dict):
    """Each DataFrame row's haircut equals float(source_dict[spec.dict_key])."""
    rows = df.to_dicts()
    assert len(rows) == len(specs), f"{name}: row count mismatch"
    for row, spec in zip(rows, specs, strict=True):
        coll_type, cqs, maturity_band, dict_key, is_main_index = spec
        assert row["collateral_type"] == coll_type
        assert row["cqs"] == cqs
        assert row["maturity_band"] == maturity_band
        assert row["is_main_index"] == is_main_index
        expected = float(source_dict[dict_key])
        assert row["haircut"] == pytest.approx(expected), (
            f"{name}: row {spec} — DataFrame haircut {row['haircut']} != "
            f"source dict value {expected}"
        )


# =============================================================================
# F-IRB supervisory LGD DataFrames (firb_lgd.py)
# =============================================================================


def test_firb_lgd_df_matches_source_dicts():
    """CRR F-IRB rows draw LGD, OC ratio, and min threshold from dicts."""
    df = firb_lgd._create_firb_lgd_df()
    specs = firb_lgd._CRR_FIRB_ROW_SPECS
    rows = df.to_dicts()
    assert len(rows) == len(specs)
    for row, spec in zip(rows, specs, strict=True):
        coll_type, seniority, lgd_key, oc_key, description = spec
        assert row["collateral_type"] == coll_type
        assert row["seniority"] == seniority
        assert row["description"] == description
        assert row["lgd"] == pytest.approx(float(firb_lgd.FIRB_SUPERVISORY_LGD[lgd_key]))
        assert row["overcollateralisation_ratio"] == pytest.approx(
            firb_lgd.FIRB_OVERCOLLATERALISATION_RATIOS[oc_key]
        )
        assert row["min_threshold"] == pytest.approx(
            firb_lgd.FIRB_MIN_COLLATERALISATION_THRESHOLDS[oc_key]
        )


def test_b31_firb_lgd_df_matches_source_dicts():
    """Basel 3.1 F-IRB rows draw LGD, OC ratio, and min threshold from dicts."""
    df = firb_lgd._create_b31_firb_lgd_df()
    specs = firb_lgd._B31_FIRB_ROW_SPECS
    rows = df.to_dicts()
    assert len(rows) == len(specs)
    for row, spec in zip(rows, specs, strict=True):
        coll_type, seniority, is_fse, lgd_key, oc_key, description = spec
        assert row["collateral_type"] == coll_type
        assert row["seniority"] == seniority
        assert row["is_fse"] == is_fse
        assert row["description"] == description
        assert row["lgd"] == pytest.approx(float(firb_lgd.BASEL31_FIRB_SUPERVISORY_LGD[lgd_key]))
        assert row["overcollateralisation_ratio"] == pytest.approx(
            firb_lgd.FIRB_OVERCOLLATERALISATION_RATIOS[oc_key]
        )
        assert row["min_threshold"] == pytest.approx(
            firb_lgd.FIRB_MIN_COLLATERALISATION_THRESHOLDS[oc_key]
        )


def test_b31_firb_scalar_aliases_match_dict():
    """B31_FIRB_LGD_* scalars must equal their corresponding dict entry."""
    d = firb_lgd.BASEL31_FIRB_SUPERVISORY_LGD
    assert d["unsecured_senior"] == firb_lgd.B31_FIRB_LGD_UNSECURED_SENIOR
    assert d["unsecured_senior_fse"] == firb_lgd.B31_FIRB_LGD_UNSECURED_SENIOR_FSE
    assert d["subordinated"] == firb_lgd.B31_FIRB_LGD_SUBORDINATED
    assert d["covered_bond"] == firb_lgd.B31_FIRB_LGD_COVERED_BOND
    assert d["financial_collateral"] == firb_lgd.B31_FIRB_LGD_FINANCIAL_COLLATERAL
    assert d["receivables"] == firb_lgd.B31_FIRB_LGD_RECEIVABLES
    assert d["residential_re"] == firb_lgd.B31_FIRB_LGD_RESIDENTIAL_RE
    assert d["commercial_re"] == firb_lgd.B31_FIRB_LGD_COMMERCIAL_RE
    assert d["other_physical"] == firb_lgd.B31_FIRB_LGD_OTHER_PHYSICAL
