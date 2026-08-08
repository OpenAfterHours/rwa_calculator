"""Regenerate the pack-derived reference surfaces from the resolved rulepacks.

The regulatory-tables docs page used to be hand-written prose that restated the
pack values — and hand-maintained copies of machine-knowable facts drift. This
script makes drift impossible instead of detected: it resolves both regime
packs (``crr`` at its 2026 reporting date, ``b31`` at commencement) and renders
every cited entry — features, scalars, lookup / banded / decision tables,
schedules, formula bundles — into one deterministic markdown reference.
Entries identical in both regimes render once; regime-divergent entries render
side by side, which is exactly the CRR↔B31 delta a reader wants.

Two kinds of target are written:

- ``docs/data-model/regulatory-tables.md`` — the whole page, every cited entry.
- **Skill fragments** — marked regions inside the hand-written ``basel31`` /
  ``crr`` skill reference files under ``.claude/skills/``. The skills used to
  restate pack values as prose tables and drifted exactly as predicted: the
  corporate CQS5 Basel 3.1 risk weight was stated as 100% in three separate
  files while the pack, the engine and PS1/26 Art. 122(2) Table 6 all say 150%.
  Prose outside the markers stays hand-written (judgment, article precedence,
  traps); every number comes from the pack. ``scripts/check_skill_values.py``
  enforces the split from the other side.

Determinism is load-bearing: the output embeds the package version and each
pack's content hash but no timestamps, so re-running on an unchanged tree is
byte-identical and ``tests/contracts/test_docs_freshness.py`` can gate
freshness by simple string equality. A pack edit that skips regeneration turns
that test red.

Usage:
    uv run python scripts/generate_regulatory_tables.py           # rewrite targets
    uv run python scripts/generate_regulatory_tables.py --check   # exit 1 if stale

Exit codes:
    0 = targets written (or already fresh under --check)
    1 = --check found a target stale
    2 = the fragment spec and the skill files disagree (author error)
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from dataclasses import dataclass, fields, is_dataclass
from datetime import date
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rwa_calc.rulebook.model import (  # noqa: E402
    BandedTable,
    CategoryMap,
    DateParam,
    DecisionTable,
    Feature,
    FormulaParams,
    IntParam,
    LookupTable,
    ScalarParam,
    Schedule,
)
from rwa_calc.rulebook.resolve import ResolvedRulepack, resolve  # noqa: E402

OUTPUT_PATH = REPO_ROOT / "docs" / "data-model" / "regulatory-tables.md"

#: The canonical resolution date per regime: CRR as currently in force, B31 at
#: its PS1/26 commencement. Changing a date changes every date-gated entry, so
#: these are deliberately fixed rather than "today".
REGIME_DATES: tuple[tuple[str, date], ...] = (
    ("crr", date(2026, 1, 1)),
    ("b31", date(2027, 1, 1)),
)

REGIME_LABELS = {"crr": "CRR", "b31": "Basel 3.1"}

#: Section order on the page: behaviour switches first, simple values next,
#: structured tables after.
SECTIONS: tuple[tuple[str, type, str], ...] = (
    ("Regime features", Feature, "On/off behaviour switches (`Feature`)."),
    (
        "Scalar parameters",
        ScalarParam,
        "Decimal-valued parameters (`ScalarParam`). "
        "Risk weights and factors are decimal fractions (0.20 = 20%).",
    ),
    (
        "Integer parameters",
        IntParam,
        "Integer counts — day floors, thresholds, band bounds (`IntParam`).",
    ),
    ("Date parameters", DateParam, "Calendar-date parameters (`DateParam`)."),
    ("Lookup tables", LookupTable, "Exact-match key → value tables (`LookupTable`)."),
    ("Category maps", CategoryMap, "Label → label classification maps (`CategoryMap`)."),
    (
        "Banded tables",
        BandedTable,
        "Ordered threshold tables over a numeric input (`BandedTable`).",
    ),
    ("Schedules", Schedule, "Date-stepped values with carry-forward (`Schedule`)."),
    ("Decision tables", DecisionTable, "Multi-key decision tables (`DecisionTable`)."),
    (
        "Formula parameter bundles",
        FormulaParams,
        "Named parameter sets for one formula (`FormulaParams`).",
    ),
)

SKILLS_ROOT = REPO_ROOT / ".claude" / "skills"

#: Shapes rendered as one CRR-vs-B31 comparison row rather than their own block.
SIMPLE_SHAPES: tuple[type, ...] = (Feature, ScalarParam, IntParam, DateParam)

BEGIN_MARKER = re.compile(r"^<!-- BEGIN GENERATED: ([a-z0-9-]+) -->$")
END_MARKER = re.compile(r"^<!-- END GENERATED: ([a-z0-9-]+) -->$")


@dataclass(frozen=True)
class Fragment:
    """One generated region inside an otherwise hand-written skill reference file.

    ``entries`` is an explicit, ordered list of pack entry names rather than a
    prefix match: a skill section is a curated regulatory topic, and silently
    absorbing a newly added pack entry into a skill's prose is exactly the kind
    of surprise this machinery exists to prevent. A new entry that belongs in a
    skill is added here deliberately.
    """

    path: Path
    fragment_id: str
    entries: tuple[str, ...]


def _names(*entries: str) -> tuple[str, ...]:
    return entries


FRAGMENTS: tuple[Fragment, ...] = (
    # ---- basel31 / sa-risk-weights.md ------------------------------------
    Fragment(
        SKILLS_ROOT / "basel31" / "references" / "sa-risk-weights.md",
        "b31-sa-corporate",
        _names(
            "b31_corporate_risk_weights",
            "b31_corporate_short_term_ecai_risk_weights",
            "b31_corporate_investment_grade_rw",
            "b31_corporate_non_investment_grade_rw",
            "b31_corporate_sme_rw",
            "b31_subordinated_debt_rw",
        ),
    ),
    Fragment(
        SKILLS_ROOT / "basel31" / "references" / "sa-risk-weights.md",
        "b31-sa-institution",
        _names(
            "institution_rw_b31_ecra",
            "institution_short_term_rw_b31_ecra",
            "b31_ecra_short_term_risk_weights",
            "b31_ecra_short_term_ecai_risk_weights",
            "b31_scra_risk_weights",
            "b31_scra_short_term_risk_weights",
        ),
    ),
    Fragment(
        SKILLS_ROOT / "basel31" / "references" / "sa-risk-weights.md",
        "b31-sa-covered-bond",
        _names(
            "b31_covered_bond_risk_weights",
            "b31_covered_bond_unrated_from_scra",
            "covered_bond_unrated_derivation_b31",
        ),
    ),
    Fragment(
        SKILLS_ROOT / "basel31" / "references" / "sa-risk-weights.md",
        "b31-sa-real-estate",
        _names(
            "b31_residential_general_secured_rw",
            "b31_residential_general_max_secured_ratio",
            "re_split_rre_secured_ltv_cap",
            "b31_rre_residual_rw_natural_person",
            "b31_rre_residual_rw_retail_sme",
            "b31_rre_residual_rw_other_sme",
            "b31_rre_residual_rw_social_housing_floor",
            "b31_rre_three_property_limit",
            "b31_art_124e_three_property_limit_applies",
            "b31_residential_income_ltv_bands",
            "b31_residential_income_junior_ltv_threshold",
            "b31_residential_income_junior_multiplier",
            "b31_commercial_general_secured_rw",
            "b31_commercial_general_max_secured_ratio",
            "re_split_cre_secured_ltv_cap",
            "b31_commercial_income_ltv_bands",
            "b31_cre_income_junior_rw_low",
            "b31_cre_income_junior_rw_mid",
            "b31_cre_income_junior_rw_high",
            "b31_other_re_income_dependent_rw",
            "b31_other_re_cre_floor_rw",
            "b31_adc_risk_weight",
            "b31_adc_presold_risk_weight",
        ),
    ),
    Fragment(
        SKILLS_ROOT / "basel31" / "references" / "sa-risk-weights.md",
        "b31-sa-retail",
        _names(
            "retail_risk_weight",
            "b31_retail_transactor_rw",
            "b31_retail_payroll_loan_rw",
            "b31_retail_non_regulatory_rw",
            "b31_retail_granularity_limit",
        ),
    ),
    Fragment(
        SKILLS_ROOT / "basel31" / "references" / "sa-risk-weights.md",
        "b31-sa-specialised-lending",
        _names("b31_sa_sl_risk_weights", "sa_sl_inferred_rating_disapplied"),
    ),
    Fragment(
        SKILLS_ROOT / "basel31" / "references" / "sa-risk-weights.md",
        "b31-sa-defaulted",
        _names(
            "b31_defaulted_provision_threshold",
            "b31_defaulted_rw_high_provision",
            "b31_defaulted_rw_low_provision",
            "b31_defaulted_resi_re_non_income_rw",
            "sa_revised_defaulted_treatment",
        ),
    ),
    Fragment(
        SKILLS_ROOT / "basel31" / "references" / "sa-risk-weights.md",
        "b31-sa-equity-and-other-items",
        _names(
            "equity_sa_risk_weights",
            "other_items_cash_rw",
            "other_items_gold_rw",
            "other_items_collection_rw",
            "other_items_tangible_rw",
            "other_items_default_rw",
        ),
    ),
    Fragment(
        SKILLS_ROOT / "basel31" / "references" / "sa-risk-weights.md",
        "b31-sa-currency-mismatch",
        _names(
            "sa_currency_mismatch_multiplier",
            "b31_currency_mismatch_multiplier",
            "b31_currency_mismatch_rw_cap",
            "b31_currency_mismatch_hedge_coverage_floor",
        ),
    ),
    # ---- basel31 / irb-changes.md ----------------------------------------
    Fragment(
        SKILLS_ROOT / "basel31" / "references" / "irb-changes.md",
        "irb-pd-and-lgd-floors",
        _names("pd_floors", "lgd_floors", "airb_lgd_floor", "mortgage_rw_floor"),
    ),
    Fragment(
        SKILLS_ROOT / "basel31" / "references" / "irb-changes.md",
        "irb-firb-supervisory-lgd",
        _names(
            "firb_supervisory_lgd",
            "firb_fse_senior_lgd_split",
            "min_collateralisation_thresholds",
            "firb_min_collateralisation_threshold_applies",
            "overcollateralisation_ratios",
            "firb_overcollateralisation_divisor_applies",
        ),
    ),
    Fragment(
        SKILLS_ROOT / "basel31" / "references" / "irb-changes.md",
        "irb-scaling-and-restrictions",
        _names(
            "irb_scaling_factor",
            "approach_restrictions_b31_applicable",
            "post_model_adjustments",
            "double_default_treatment",
            "equity_irb_approaches_available",
        ),
    ),
    Fragment(
        SKILLS_ROOT / "basel31" / "references" / "irb-changes.md",
        "irb-maturity",
        _names(
            "firb_fixed_supervisory_maturity",
            "firb_fixed_supervisory_maturity_years",
            "firb_sft_supervisory_maturity",
            "firb_sft_supervisory_maturity_years",
            "irb_maturity_floor_collateralised_deriv_years",
            "irb_maturity_floor_repo_sft_years",
            "one_day_maturity_floor",
            "one_day_maturity_floor_years",
            "revolving_uses_termination_maturity",
        ),
    ),
    Fragment(
        SKILLS_ROOT / "basel31" / "references" / "irb-changes.md",
        "irb-ead-and-ccf-floors",
        _names(
            "airb_ead_floor_applies",
            "airb_obs_floor_b_multiplier",
            "airb_revolving_ccf_floor_multiplier",
            "firb_uses_sa_ccf",
        ),
    ),
    # ---- basel31 / output-floor.md ---------------------------------------
    Fragment(
        SKILLS_ROOT / "basel31" / "references" / "output-floor.md",
        "output-floor-values",
        _names(
            "output_floor", "output_floor_pct", "output_floor_pct_full", "own_funds_to_rwa_factor"
        ),
    ),
    # ---- basel31 / credit-conversion-factors.md --------------------------
    Fragment(
        SKILLS_ROOT / "basel31" / "references" / "credit-conversion-factors.md",
        "ccf-values",
        _names(
            "sa_ccf",
            "sa_ccf_default",
            "sa_revised_ccf_table",
            "obs_product_to_risk_type",
            "oc_short_maturity_ccf",
            "oc_short_maturity_threshold_days",
            "firb_uses_sa_ccf",
            "firb_credit_line_ccf",
            "firb_trade_lc_ccf",
            "firb_obs_fallback_ccf",
            "airb_revolving_ccf_floor_multiplier",
            "airb_ead_floor_applies",
            "airb_obs_floor_b_multiplier",
            "ucp_unilateral_change_ineligible",
        ),
    ),
    # ---- basel31 / crm-changes.md ----------------------------------------
    Fragment(
        SKILLS_ROOT / "basel31" / "references" / "crm-changes.md",
        "crm-haircuts",
        _names(
            "collateral_haircuts",
            "collateral_haircut_maturity_bands_revised",
            "fx_haircut",
            "zero_haircut_max_sovereign_cqs",
            "restructuring_exclusion_haircut",
            "liquidation_period_repo",
            "liquidation_period_capital_market",
            "liquidation_period_secured_lending",
        ),
    ),
    Fragment(
        SKILLS_ROOT / "basel31" / "references" / "crm-changes.md",
        "crm-collateral-methods",
        _names(
            "overcollateralisation_ratios",
            "min_collateralisation_thresholds",
            "airb_lgd_collateral_method_applicable",
            "life_insurance_secured_rw_map",
            "fcsm_rw_floor",
            "fcsm_equity_collateral_rw",
            "fcsm_sovereign_bond_discount",
            "fcsm_sft_cmp_floor",
            "fcsm_sft_non_cmp_floor",
            "gcra_cap_rate",
            "mna_intermediate_floor_requires_daily_condition",
        ),
    ),
    # ---- basel31 / slotting-changes.md -----------------------------------
    Fragment(
        SKILLS_ROOT / "basel31" / "references" / "slotting-changes.md",
        "slotting-tables",
        _names(
            "slotting_revised_tables",
            "slotting_short_maturity_threshold_years",
            "slotting_rw_base",
            "slotting_rw_short",
            "slotting_rw_hvcre",
            "slotting_rw_hvcre_short",
            "slotting_rw_preop",
            "slotting_el_base",
            "slotting_el_short",
            "slotting_el_hvcre",
            "slotting_guarantee_substitution",
        ),
    ),
    # ---- basel31 / reporting-changes.md ----------------------------------
    Fragment(
        SKILLS_ROOT / "basel31" / "references" / "reporting-changes.md",
        "reporting-template-set",
        _names("reporting_template_set", "b31_exposure_subclass_reporting_applies"),
    ),
    # ---- basel31 / what-changed.md ---------------------------------------
    Fragment(
        SKILLS_ROOT / "basel31" / "references" / "what-changed.md",
        "regime-divergence",
        (),  # empty == "every simple entry whose CRR and B31 values differ"
    ),
    # ---- crr / sa-risk-weights.md ----------------------------------------
    Fragment(
        SKILLS_ROOT / "crr" / "references" / "sa-risk-weights.md",
        "crr-sa-corporate-and-institution",
        _names(
            "corporate_risk_weights",
            "corporate_cqs_rw",
            "crr_short_term_ecai_risk_weights",
            "crr_corporate_sme_rw",
            "institution_rw_crr",
            "institution_rw_sovereign_derived",
            "institution_short_term_rw_crr",
            "institution_short_term_unrated_rw_crr",
            "covered_bond_risk_weights",
            "covered_bond_unrated_derivation_crr",
        ),
    ),
    Fragment(
        SKILLS_ROOT / "crr" / "references" / "sa-risk-weights.md",
        "crr-sa-public-sector",
        _names(
            "cgcb_risk_weights",
            "central_bank_uses_sovereign_cqs",
            "ecb_zero_rw",
            "eca_meip_risk_weights",
            "pse_risk_weights_own_rating",
            "pse_risk_weights_sovereign_derived",
            "pse_short_term_rw",
            "pse_unrated_default_rw",
            "pse_non_equivalent_jurisdiction_rw",
            "rgla_risk_weights_own_rating",
            "rgla_risk_weights_sovereign_derived",
            "rgla_domestic_currency_rw",
            "rgla_uk_devolved_rw",
            "rgla_uk_local_auth_rw",
            "rgla_unrated_default_rw",
            "mdb_risk_weights_table_2b",
            "mdb_named_zero_rw",
            "mdb_unrated_rw",
        ),
    ),
    Fragment(
        SKILLS_ROOT / "crr" / "references" / "sa-risk-weights.md",
        "crr-sa-retail-re-and-other",
        _names(
            "retail_risk_weight",
            "crr_non_regulatory_retail_rw",
            "residential_mortgage_params",
            "commercial_re_params",
            "high_risk_rw",
            "equity_sa_risk_weights",
            "other_items_cash_rw",
            "other_items_gold_rw",
            "other_items_collection_rw",
            "other_items_tangible_rw",
            "other_items_default_rw",
            "qccp_proprietary_rw",
            "qccp_client_cleared_rw",
            "io_zero_rw",
            "intragroup_zero_rw",
            "intragroup_zero_rw_pct",
        ),
    ),
    Fragment(
        SKILLS_ROOT / "crr" / "references" / "sa-risk-weights.md",
        "crr-sa-defaulted",
        _names(
            "crr_defaulted_provision_threshold",
            "crr_defaulted_rw_high_provision",
            "crr_defaulted_rw_low_provision",
        ),
    ),
    # ---- crr / irb-parameters.md -----------------------------------------
    Fragment(
        SKILLS_ROOT / "crr" / "references" / "irb-parameters.md",
        "crr-irb-parameters",
        _names(
            "pd_floors",
            "lgd_floors",
            "firb_supervisory_lgd",
            "irb_scaling_factor",
            "irb_correlation_sme_gbp_native",
            "crr_retail_re_portfolio_lgd_floor",
            "retail_residential_re_portfolio_lgd_floor",
            "retail_commercial_re_portfolio_lgd_floor",
            "double_default_treatment",
            "crr_non_named_mdb_institution_irb_class",
        ),
    ),
    Fragment(
        SKILLS_ROOT / "crr" / "references" / "irb-parameters.md",
        "crr-irb-maturity",
        _names(
            "firb_fixed_supervisory_maturity",
            "firb_fixed_supervisory_maturity_years",
            "firb_sft_supervisory_maturity",
            "firb_sft_supervisory_maturity_years",
            "irb_maturity_floor_collateralised_deriv_years",
            "irb_maturity_floor_repo_sft_years",
            "one_day_maturity_floor",
            "one_day_maturity_floor_years",
            "revolving_uses_termination_maturity",
        ),
    ),
    # ---- crr / credit-conversion-factors.md ------------------------------
    Fragment(
        SKILLS_ROOT / "crr" / "references" / "credit-conversion-factors.md",
        "crr-ccf-values",
        _names(
            "sa_ccf",
            "sa_ccf_default",
            "obs_product_to_risk_type",
            "oc_short_maturity_ccf",
            "oc_short_maturity_threshold_days",
            "firb_credit_line_ccf",
            "firb_trade_lc_ccf",
            "firb_obs_fallback_ccf",
        ),
    ),
    # ---- crr / credit-risk-mitigation.md ---------------------------------
    Fragment(
        SKILLS_ROOT / "crr" / "references" / "credit-risk-mitigation.md",
        "crr-crm-values",
        _names(
            "collateral_haircuts",
            "fx_haircut",
            "zero_haircut_max_sovereign_cqs",
            "restructuring_exclusion_haircut",
            "liquidation_period_repo",
            "liquidation_period_capital_market",
            "liquidation_period_secured_lending",
            "overcollateralisation_ratios",
            "min_collateralisation_thresholds",
            "life_insurance_secured_rw_map",
            "fcsm_rw_floor",
            "fcsm_equity_collateral_rw",
            "fcsm_sovereign_bond_discount",
            "fcsm_sft_cmp_floor",
            "fcsm_sft_non_cmp_floor",
        ),
    ),
    # ---- crr / slotting-and-equity.md ------------------------------------
    Fragment(
        SKILLS_ROOT / "crr" / "references" / "slotting-and-equity.md",
        "crr-slotting-and-equity-values",
        _names(
            "slotting_short_maturity_threshold_years",
            "slotting_rw_base",
            "slotting_rw_short",
            "slotting_rw_hvcre",
            "slotting_rw_hvcre_short",
            "slotting_el_base",
            "slotting_el_short",
            "slotting_el_hvcre",
            "equity_sa_risk_weights",
            "equity_irb_approaches_available",
            "equity_irb_simple_risk_weights",
            "equity_irb_simple_el",
            "equity_pd_floors",
            "equity_pd_lgd_lgd",
            "equity_pd_lgd_maturity",
            "equity_pd_lgd_no_default_info_scaling",
            "equity_netting_min_hedge_years",
            "equity_transitional",
            "equity_transitional_std_rw",
            "equity_transitional_hr_rw",
        ),
    ),
    # ---- crr / supporting-factors.md -------------------------------------
    Fragment(
        SKILLS_ROOT / "crr" / "references" / "supporting-factors.md",
        "crr-supporting-factors",
        _names(
            "supporting_factors",
            "supporting_factors_values",
            "regulatory_thresholds",
            "regulatory_thresholds_fx_derived",
        ),
    ),
    # ---- crr / provisions-and-el.md --------------------------------------
    Fragment(
        SKILLS_ROOT / "crr" / "references" / "provisions-and-el.md",
        "crr-provisions-values",
        _names(
            "crr_defaulted_provision_threshold",
            "crr_defaulted_rw_high_provision",
            "crr_defaulted_rw_low_provision",
            "b31_defaulted_provision_threshold",
            "b31_defaulted_rw_high_provision",
            "b31_defaulted_rw_low_provision",
            "sa_revised_defaulted_treatment",
        ),
    ),
    # ---- crr / exposure-classification.md --------------------------------
    Fragment(
        SKILLS_ROOT / "crr" / "references" / "exposure-classification.md",
        "crr-classification-maps",
        _names(
            "entity_type_to_sa_class",
            "entity_type_to_irb_class",
            "regulatory_thresholds",
            "regulatory_thresholds_fx_derived",
            "b31_retail_granularity_limit",
            "retail_art_123a_two_path_applicable",
            "b31_high_risk_class_applicable",
            "b31_exposure_subclass_reporting_applies",
            "crr_non_named_mdb_institution_irb_class",
            "central_bank_uses_sovereign_cqs",
            "eu_country_domestic_currency",
        ),
    ),
)


def render() -> str:
    """Render the whole page from freshly resolved packs."""
    packs = {regime: resolve(regime, on) for regime, on in REGIME_DATES}
    lines = _header(packs)
    for title, shape, blurb in SECTIONS:
        lines.extend(_render_section(title, shape, blurb, packs))
    lines.extend(_render_other_shapes(packs))
    return "\n".join(lines) + "\n"


def render_targets() -> dict[Path, str]:
    """Desired full text of every generated target, keyed by path.

    One resolve pass feeds the page and all skill fragments, so a fragment can
    never disagree with the page it was rendered alongside.
    """
    packs = {regime: resolve(regime, on) for regime, on in REGIME_DATES}
    targets: dict[Path, str] = {OUTPUT_PATH: render()}
    for path, fragments in _fragments_by_path().items():
        bodies = {f.fragment_id: _render_fragment_body(f, packs) for f in fragments}
        targets[path] = _splice(path, bodies)
    return targets


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Regenerate docs/data-model/regulatory-tables.md and the .claude/skills "
            "pack-value fragments from the resolved rulepacks."
        )
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if any committed target differs from a fresh render",
    )
    args = parser.parse_args()

    _validate_fragment_spec()
    targets = render_targets()

    if args.check:
        stale = [
            path
            for path, content in sorted(targets.items())
            if (path.read_text(encoding="utf-8") if path.exists() else "") != content
        ]
        if stale:
            listing = "\n".join(f"  - {p.relative_to(REPO_ROOT).as_posix()}" for p in stale)
            sys.stderr.write(
                "These generated targets no longer match the resolved rulepacks:\n"
                f"{listing}\n"
                "Regenerate (never hand-edit inside the GENERATED markers):\n"
                "  uv run python scripts/generate_regulatory_tables.py\n"
            )
            return 1
        return 0

    for path, content in sorted(targets.items()):
        path.write_text(content, encoding="utf-8")
    sys.stderr.write(f"wrote {len(targets)} target(s)\n")
    return 0


# ---------------------------------------------------------------------------
# Private helpers — skill fragments
# ---------------------------------------------------------------------------


def _fragments_by_path() -> dict[Path, list[Fragment]]:
    grouped: dict[Path, list[Fragment]] = {}
    for fragment in FRAGMENTS:
        grouped.setdefault(fragment.path, []).append(fragment)
    return grouped


def _validate_fragment_spec() -> None:
    """Fail loudly when the spec and the skill files have drifted apart.

    Three author errors are fatal rather than silent, because each one would
    otherwise leave a skill quietly stating nothing (or stating something the
    pack no longer backs): a fragment id declared here but absent from the
    file, a marker in the file that no fragment fills, and an entry name that
    resolves in neither pack — the signature of a renamed pack entry.
    """
    packs = {regime: resolve(regime, on) for regime, on in REGIME_DATES}
    known = {name for pack in packs.values() for name in pack.entries}
    problems: list[str] = []

    for fragment in FRAGMENTS:
        for name in fragment.entries:
            if name not in known:
                problems.append(
                    f"{fragment.fragment_id}: entry `{name}` is in no pack (renamed or deleted?)"
                )

    for path, fragments in _fragments_by_path().items():
        if not path.exists():
            problems.append(f"{path.relative_to(REPO_ROOT).as_posix()}: file does not exist")
            continue
        declared = {f.fragment_id for f in fragments}
        present = {
            match.group(1)
            for line in path.read_text(encoding="utf-8").splitlines()
            if (match := BEGIN_MARKER.match(line.strip()))
        }
        rel = path.relative_to(REPO_ROOT).as_posix()
        for missing in sorted(declared - present):
            problems.append(f"{rel}: no `<!-- BEGIN GENERATED: {missing} -->` marker")
        for orphan in sorted(present - declared):
            problems.append(f"{rel}: marker `{orphan}` is filled by no fragment")

    if problems:
        sys.stderr.write("Fragment spec errors:\n" + "\n".join(f"  - {p}" for p in problems) + "\n")
        raise SystemExit(2)


def _render_fragment_body(fragment: Fragment, packs: dict[str, ResolvedRulepack]) -> list[str]:
    """Render one fragment's tables — no markers, no headings above `###`.

    Declared order is preserved rather than regrouped by shape: a fragment is a
    curated topic, and the entry the author put first is the headline. Runs of
    consecutive simple entries collapse into a single comparison table so a
    `Feature` and the `ScalarParam` it gates stay adjacent.
    """
    names = list(fragment.entries) or _divergent_names(packs)
    lines: list[str] = []
    run: list[str] = []

    def flush() -> None:
        if run:
            lines.extend(_render_simple_table(run, packs))
            run.clear()

    for name in names:
        if _shape_of(name, packs) in SIMPLE_SHAPES:
            run.append(name)
            continue
        flush()
        lines.extend(_render_structured_entry(name, packs))
    flush()

    while lines and not lines[-1]:
        lines.pop()
    return lines


def _divergent_names(packs: dict[str, ResolvedRulepack]) -> list[str]:
    """Every simple-shape entry carried by both packs whose value differs.

    This is the self-maintaining half of the CRR↔B31 delta: a pack edit that
    opens or closes a divergence updates the skill's summary table with no
    author action. Entries that exist under one regime only are deliberately
    excluded — they are renames or new concepts, and belong in curated prose.
    """
    crr, b31 = packs["crr"].entries, packs["b31"].entries
    return sorted(
        name
        for name in set(crr) & set(b31)
        if type(crr[name]) in SIMPLE_SHAPES
        and type(b31[name]) is type(crr[name])
        and _simple_value(crr[name]) != _simple_value(b31[name])
    )


def _shape_of(name: str, packs: dict[str, ResolvedRulepack]) -> type:
    for regime in ("b31", "crr"):
        entry = packs[regime].entries.get(name)
        if entry is not None:
            return type(entry)
    raise KeyError(name)  # unreachable: _validate_fragment_spec ran first


def _splice(path: Path, bodies: dict[str, list[str]]) -> str:
    """Replace each marked region's contents, leaving all other prose intact."""
    out: list[str] = []
    skipping: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if skipping is None:
            out.append(line)
            if match := BEGIN_MARKER.match(stripped):
                skipping = match.group(1)
                out.extend(bodies[skipping])
            continue
        if (match := END_MARKER.match(stripped)) and match.group(1) == skipping:
            out.append(line)
            skipping = None
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Private helpers — page assembly
# ---------------------------------------------------------------------------


def _header(packs: dict[str, ResolvedRulepack]) -> list[str]:
    version = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    lines = [
        "# Regulatory Tables",
        "",
        "<!-- GENERATED FILE — DO NOT EDIT."
        " Regenerate: uv run python scripts/generate_regulatory_tables.py -->",
        "",
        "Every cited regulatory value in the rulepack packs"
        " `src/rwa_calc/rulebook/packs/{common,crr,b31}.py`, rendered from"
        " `rwa_calc.rulebook.resolve.resolve(regime, date)`. **This page is"
        " generated** — a wrong value here is a rulepack finding, never a docs"
        " edit. Entries identical under both regimes appear once; divergent"
        " entries appear per regime.",
        "",
        f"Package version `{version}`. Resolved packs:",
        "",
    ]
    for regime, on in REGIME_DATES:
        pack = packs[regime]
        lines.append(
            f"- **{REGIME_LABELS[regime]}** (`{regime}` @ {on.isoformat()}) — "
            f"{len(pack.entries)} entries, content hash `{pack.content_hash[:16]}`"
        )
    lines.append("")
    return lines


def _render_section(
    title: str, shape: type, blurb: str, packs: dict[str, ResolvedRulepack]
) -> list[str]:
    names = sorted(
        {
            name
            for pack in packs.values()
            for name, entry in pack.entries.items()
            if type(entry) is shape
        }
    )
    if not names:
        return []
    lines = [f"## {title}", "", blurb, ""]
    if shape in SIMPLE_SHAPES:
        lines.extend(_render_simple_table(names, packs, shape=shape))
    else:
        for name in names:
            lines.extend(_render_structured_entry(name, packs))
    return lines


def _render_simple_table(
    names: list[str], packs: dict[str, ResolvedRulepack], shape: type | None = None
) -> list[str]:
    """One comparison row per entry.

    ``shape`` pins the section rendering on the main page, where a section is
    by definition single-shape. Skill fragments pass ``None`` and mix shapes —
    a topic such as "IRB maturity" is naturally a `Feature` plus the
    `ScalarParam` it gates, and splitting those apart helps no reader.
    """
    lines = [
        "| Name | CRR | Basel 3.1 | Citation |",
        "|---|---|---|---|",
    ]
    for name in names:
        crr = packs["crr"].entries.get(name)
        b31 = packs["b31"].entries.get(name)
        crr_value = _simple_value(crr) if _matches(crr, shape) else "—"
        b31_value = _simple_value(b31) if _matches(b31, shape) else "—"
        lines.append(f"| `{name}` | {crr_value} | {b31_value} | {_citations(crr, b31)} |")
    lines.append("")
    return lines


def _matches(entry: Any, shape: type | None) -> bool:
    return type(entry) is shape if shape is not None else type(entry) in SIMPLE_SHAPES


def _render_structured_entry(name: str, packs: dict[str, ResolvedRulepack]) -> list[str]:
    crr = packs["crr"].entries.get(name)
    b31 = packs["b31"].entries.get(name)
    lines = [f"### `{name}`", ""]
    if crr is not None and crr == b31:
        lines.extend(_entry_block(crr, "Both regimes"))
    else:
        if crr is not None:
            lines.extend(_entry_block(crr, "CRR"))
        if b31 is not None:
            lines.extend(_entry_block(b31, "Basel 3.1" if crr is not None else "Basel 3.1 only"))
    return lines


def _entry_block(entry: Any, scope: str) -> list[str]:
    lines = [f"**{scope}** — {_md(str(entry.citation))}"]
    if getattr(entry.citation, "note", ""):
        lines.append(f" *({_md(entry.citation.note)})*")
    lines.append("")
    match entry:
        case LookupTable() | CategoryMap():
            lines.append(f"Key column: `{entry.key}`" + _default_suffix(entry.default))
            lines.append("")
            lines.append("| Key | Value |")
            lines.append("|---|---|")
            lines.extend(f"| {_md_key(k)} | {_md_value(v)} |" for k, v in entry.entries.items())
        case BandedTable():
            bound_op = "<=" if entry.right_closed else "<"
            lines.append(
                f"Input column: `{entry.input}` (band applies when input {bound_op} bound)"
            )
            lines.append("")
            lines.append("| Upper bound | Value |")
            lines.append("|---|---|")
            lines.extend(
                f"| {'—' if bound is None else _md_value(bound)} | {_md_value(value)} |"
                for bound, value in entry.bands
            )
        case Schedule():
            lines.append(f"Before first step: {_md_value(entry.before_first)}")
            lines.append("")
            lines.append("| Effective date | Value |")
            lines.append("|---|---|")
            lines.extend(
                f"| {step_date.isoformat()} | {_md_value(value)} |"
                for step_date, value in entry.steps
            )
        case DecisionTable():
            key_header = " , ".join(f"`{k}`" for k in entry.key_names)
            lines.append(f"Keys: {key_header}" + _default_suffix(entry.default))
            lines.append("")
            lines.append("| Keys | Value |")
            lines.append("|---|---|")
            lines.extend(f"| {_md_key(keys)} | {_md_value(value)} |" for keys, value in entry.rows)
        case FormulaParams():
            lines.append("| Parameter | Value |")
            lines.append("|---|---|")
            lines.extend(f"| `{k}` | {_md_value(v)} |" for k, v in entry.params.items())
        case _:
            lines.extend(_generic_fields(entry))
    lines.append("")
    return lines


def _render_other_shapes(packs: dict[str, ResolvedRulepack]) -> list[str]:
    """Any entry shape not named in ``SECTIONS`` (e.g. ``ReportingTemplateSet``).

    Rendered generically from dataclass fields so a future shape cannot be
    silently omitted from the page.
    """
    known = {shape for _, shape, _ in SECTIONS}
    names = sorted(
        {
            name
            for pack in packs.values()
            for name, entry in pack.entries.items()
            if type(entry) not in known
        }
    )
    if not names:
        return []
    lines = [
        "## Other entries",
        "",
        "Shapes outside the standard vocabulary, rendered field-by-field.",
        "",
    ]
    for name in names:
        lines.extend(_render_structured_entry(name, packs))
    return lines


def _generic_fields(entry: Any) -> list[str]:
    if not is_dataclass(entry):
        return [f"`{_md(repr(entry))}`"]
    lines = ["| Field | Value |", "|---|---|"]
    lines.extend(
        f"| `{f.name}` | {_md_value(getattr(entry, f.name))} |"
        for f in fields(entry)
        if f.name not in ("name", "citation")
    )
    return lines


# ---------------------------------------------------------------------------
# Private helpers — formatting
# ---------------------------------------------------------------------------


def _simple_value(entry: Any) -> str:
    match entry:
        case Feature():
            return "on" if entry.enabled else "off"
        case ScalarParam() | IntParam():
            return _md_value(entry.value)
        case DateParam():
            return entry.value.isoformat()
        case _:
            return "—"


def _citations(*entries: Any) -> str:
    cited = [str(e.citation) for e in entries if e is not None]
    unique = list(dict.fromkeys(cited))
    return _md(" / ".join(unique)) if unique else "—"


def _default_suffix(default: Any) -> str:
    return "" if default is None else f"; default {_md_value(default)}"


def _md_key(key: Any) -> str:
    if isinstance(key, tuple):
        return ", ".join(f"`{_md(str(part))}`" for part in key)
    return f"`{_md(str(key))}`"


def _md_value(value: Any) -> str:
    return f"`{_md(str(value))}`"


def _md(text: str) -> str:
    """Escape the one character that breaks a markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main())
