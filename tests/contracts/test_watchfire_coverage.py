"""Pin the @cites decorator inventory against accidental removal.

Each row in WHITELIST is ``(module_path, attribute_path, expected_canonical_citations)``.
``attribute_path`` is dot-separated: bare function name for module-level
functions, ``ClassName.method`` for class methods. The expected tuple lists
each citation in the same order the decorators appear from outermost to
innermost (matching how watchfire 0.3.0 builds ``__watchfire__``).

Adding a new ``@cites(...)`` decorator? Add a row here too. Removing one
deliberately? Remove the row. The test surfaces accidental decorator
removal as a named parameterised failure rather than a silent matrix
shrink.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

# fmt: off
WHITELIST: list[tuple[str, str, tuple[str, ...]]] = [
    # --- IRB formulas (module-level) ---
    ("rwa_calc.engine.irb.formulas", "calculate_k", ("CRR Art. 153(1)",)),
    ("rwa_calc.engine.irb.formulas", "calculate_correlation", ("CRR Art. 153(1)",)),
    ("rwa_calc.engine.irb.formulas", "calculate_maturity_adjustment", ("CRR Art. 162",)),
    ("rwa_calc.engine.irb.formulas", "calculate_double_default_k", ("CRR Art. 153(3)",)),
    ("rwa_calc.engine.irb.formulas", "apply_irb_formulas",
     ("CRR Art. 153", "CRR Art. 154")),
    ("rwa_calc.engine.irb.formulas", "_pd_floor_expression",
     ("CRR Art. 163", "PS1/26, paragraph 163")),
    ("rwa_calc.engine.irb.formulas", "_lgd_floor_expression",
     ("CRR Art. 164", "PS1/26, paragraph 164")),
    ("rwa_calc.engine.irb.formulas", "_lgd_floor_expression_with_collateral",
     ("PS1/26, paragraph 164",)),
    ("rwa_calc.engine.irb.formulas", "_lgd_floor_blended_expression",
     ("PS1/26, paragraph 164",)),
    ("rwa_calc.engine.irb.formulas", "_correlation_expr_from_pd", ("CRR Art. 153(2)",)),
    ("rwa_calc.engine.irb.formulas", "_capital_k_expr_from_params", ("CRR Art. 153(1)",)),
    ("rwa_calc.engine.irb.formulas", "_maturity_adjustment_expr_from_pd",
     ("CRR Art. 162(2)", "CRR Art. 162(3)")),
    ("rwa_calc.engine.irb.formulas", "_double_default_multiplier_expr",
     ("CRR Art. 153(3)",)),
    ("rwa_calc.engine.irb.formulas", "_parametric_irb_risk_weight_expr",
     ("CRR Art. 161",)),
    # --- IRB namespace (class methods) ---
    ("rwa_calc.engine.irb.namespace", "IRBLazyFrame.apply_pd_floor",
     ("CRR Art. 163", "PS1/26, paragraph 163")),
    ("rwa_calc.engine.irb.namespace", "IRBLazyFrame.apply_lgd_floor",
     ("CRR Art. 164", "PS1/26, paragraph 164")),
    ("rwa_calc.engine.irb.namespace", "IRBLazyFrame.calculate_correlation",
     ("CRR Art. 153(1)",)),
    ("rwa_calc.engine.irb.namespace", "IRBLazyFrame.calculate_k", ("CRR Art. 153(1)",)),
    ("rwa_calc.engine.irb.namespace", "IRBLazyFrame.calculate_maturity_adjustment",
     ("CRR Art. 162",)),
    # --- IRB guarantee ---
    ("rwa_calc.engine.irb.guarantee", "apply_guarantee_substitution",
     ("CRR Art. 161(3)",)),
    ("rwa_calc.engine.irb.guarantee", "_compute_guarantor_rw_sa", ("CRR Art. 122",)),
    # --- SA namespace ---
    ("rwa_calc.engine.sa.namespace", "SALazyFrame.apply_risk_weights",
     ("CRR Art. 112",)),
    ("rwa_calc.engine.sa.namespace", "SALazyFrame.apply_fcsm_rw_substitution",
     ("CRR Art. 222",)),
    ("rwa_calc.engine.sa.namespace", "SALazyFrame.apply_life_insurance_rw_mapping",
     ("CRR Art. 232",)),
    ("rwa_calc.engine.sa.namespace", "SALazyFrame.apply_guarantee_substitution",
     ("CRR Art. 213",)),
    ("rwa_calc.engine.sa.namespace", "SALazyFrame.apply_currency_mismatch_multiplier",
     ("PS1/26, paragraph 123B",)),
    ("rwa_calc.engine.sa.namespace", "SALazyFrame.apply_due_diligence_override",
     ("PS1/26, paragraph 110A",)),
    ("rwa_calc.engine.sa.namespace", "SALazyFrame.apply_supporting_factors",
     ("CRR Art. 501",)),
    # --- SA supporting factors ---
    ("rwa_calc.engine.sa.supporting_factors",
     "SupportingFactorCalculator.calculate_sme_factor", ("CRR Art. 501",)),
    ("rwa_calc.engine.sa.supporting_factors",
     "SupportingFactorCalculator.apply_factors", ("CRR Art. 501",)),
    # --- CRM ---
    ("rwa_calc.engine.crm.collateral", "generate_netting_collateral",
     ("CRR Art. 195", "CRR Art. 223")),
    ("rwa_calc.engine.crm.collateral", "apply_collateral",
     ("CRR Art. 223", "CRR Art. 230")),
    ("rwa_calc.engine.crm.collateral", "apply_firb_supervisory_lgd_no_collateral",
     ("CRR Art. 161",)),
    ("rwa_calc.engine.crm.guarantees", "apply_guarantees",
     ("CRR Art. 213", "CRR Art. 217")),
    ("rwa_calc.engine.crm.guarantees", "_apply_maturity_mismatch_to_guarantees",
     ("CRR Art. 217",)),
    ("rwa_calc.engine.crm.haircuts", "HaircutCalculator.apply_haircuts",
     ("CRR Art. 224",)),
    ("rwa_calc.engine.crm.haircuts", "HaircutCalculator.apply_maturity_mismatch",
     ("CRR Art. 237", "CRR Art. 238")),
    ("rwa_calc.engine.crm.processor", "CRMProcessor.apply_crm", ("CRR Art. 194",)),
    ("rwa_calc.engine.crm.provisions", "resolve_provisions", ("CRR Art. 111",)),
    ("rwa_calc.engine.crm.life_insurance", "compute_life_insurance_columns",
     ("CRR Art. 232",)),
    ("rwa_calc.engine.crm.simple_method", "compute_fcsm_columns", ("CRR Art. 222",)),
    # --- CCF ---
    ("rwa_calc.engine.ccf", "sa_ccf_expression", ("CRR Art. 111",)),
    ("rwa_calc.engine.ccf", "_firb_ccf_for_col", ("CRR Art. 166",)),
    ("rwa_calc.engine.ccf", "CCFCalculator.apply_ccf",
     ("CRR Art. 111", "CRR Art. 166")),
    # --- RE splitter ---
    ("rwa_calc.engine.re_splitter", "RealEstateSplitter.split",
     ("CRR Art. 125", "CRR Art. 126", "PS1/26, paragraph 124F")),
    # --- Equity ---
    ("rwa_calc.engine.equity.calculator", "EquityCalculator.calculate_branch",
     ("CRR Art. 133",)),
    ("rwa_calc.engine.equity.calculator", "EquityCalculator.calculate",
     ("CRR Art. 133", "CRR Art. 155")),
    # --- Slotting ---
    ("rwa_calc.engine.slotting.calculator", "SlottingCalculator.calculate_branch",
     ("CRR Art. 153(5)",)),
    ("rwa_calc.engine.slotting.namespace", "SlottingLazyFrame.apply_slotting_weights",
     ("CRR Art. 153(5)",)),
    # --- Classifier ---
    ("rwa_calc.engine.classifier", "ExposureClassifier.classify", ("CRR Art. 112",)),
    # --- Aggregator ---
    ("rwa_calc.engine.aggregator.aggregator", "OutputAggregator.aggregate",
     ("PS1/26, paragraph 92",)),
    ("rwa_calc.engine.aggregator._floor", "apply_floor_with_impact",
     ("PS1/26, paragraph 92",)),
    # --- data/tables/ builders ---
    ("rwa_calc.data.tables.crr_risk_weights", "build_institution_guarantor_rw_expr",
     ("CRR Art. 120", "CRR Art. 121")),
    ("rwa_calc.data.tables.crr_risk_weights", "build_corporate_guarantor_rw_expr",
     ("CRR Art. 122",)),
    ("rwa_calc.data.tables.eu_sovereign", "build_eu_domestic_currency_expr",
     ("CRR Art. 114",)),
    ("rwa_calc.data.tables.eu_sovereign", "build_domestic_cgcb_guarantor_expr",
     ("CRR Art. 114",)),
    ("rwa_calc.data.tables.firb_lgd", "get_firb_lgd_table_for_framework",
     ("CRR Art. 161",)),
    ("rwa_calc.data.tables.firb_lgd", "get_firb_lgd_table", ("CRR Art. 161",)),
    ("rwa_calc.data.tables.haircuts", "get_haircut_table", ("CRR Art. 224",)),
    ("rwa_calc.data.tables.haircuts", "get_maturity_band", ("CRR Art. 224",)),
    ("rwa_calc.data.tables.b31_risk_weights", "get_b31_combined_cqs_risk_weights",
     ("PS1/26, paragraph 122",)),
    # --- Defaulted exposures (Art. 127) ---
    ("rwa_calc.engine.sa.namespace", "_apply_defaulted_risk_weight",
     ("CRR Art. 127", "PS1/26, paragraph 127")),
    # --- High-risk items (Art. 128, B31-only — omitted from UK CRR) ---
    ("rwa_calc.engine.sa.namespace", "_b31_append_high_risk_branch",
     ("PS1/26, paragraph 128",)),
    # --- Covered bonds (Art. 129) ---
    ("rwa_calc.engine.sa.namespace", "_crr_unrated_cb_rw_expr", ("CRR Art. 129",)),
    ("rwa_calc.engine.sa.namespace", "_b31_unrated_cb_rw_expr",
     ("CRR Art. 129", "PS1/26, paragraph 129")),
    ("rwa_calc.data.tables.crr_risk_weights", "_create_covered_bond_df",
     ("CRR Art. 129",)),
    ("rwa_calc.data.tables.b31_risk_weights", "_create_b31_covered_bond_df",
     ("PS1/26, paragraph 129",)),
    # --- CIU treatment (Art. 132 — UK CRR omitted; PS1/26 132A-132C reintroduce) ---
    ("rwa_calc.engine.equity.calculator", "_append_ciu_branches",
     ("PS1/26, paragraph 132",)),
]
# fmt: on


def _resolve(module_path: str, attr_path: str) -> Any:
    module = importlib.import_module(module_path)
    obj: Any = module
    for part in attr_path.split("."):
        obj = getattr(obj, part)
    return obj


def _test_id(row: tuple[str, str, tuple[str, ...]]) -> str:
    module_path, attr_path, _ = row
    return f"{module_path}::{attr_path}"


@pytest.mark.parametrize(
    "module_path,attr_path,expected", WHITELIST, ids=[_test_id(r) for r in WHITELIST]
)
def test_function_carries_expected_citations(
    module_path: str,
    attr_path: str,
    expected: tuple[str, ...],
) -> None:
    """Each whitelisted function must carry the expected canonical citations.

    Verifies (a) the function still exists, (b) ``__watchfire__`` is
    populated, and (c) every citation in the tuple round-trips to the
    expected canonical string.
    """
    func = _resolve(module_path, attr_path)
    citations = getattr(func, "__watchfire__", ())
    actual = tuple(c.canonical() for c in citations)
    assert actual == expected, (
        f"{module_path}.{attr_path}: expected citations {expected}, "
        f"got {actual} — was the @cites decorator removed or its argument changed?"
    )
