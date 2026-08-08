"""
Engine drivers for the oracle suite.

This is the *only* module in ``tests/oracle/`` that imports ``rwa_calc``. It
exists to drive the engine with an explicit, complete single-row frame so an
oracle can exercise any regulatory path — including ones the shared helper in
``tests/fixtures/single_exposure.py`` does not expose (QRRE transactor flags,
prior charges, self-build, slotting phases, ...).

Pipeline position tested:
    (bypasses hierarchy / classifier / CRM) -> <Approach>Calculator.calculate_branch

Key responsibilities:
- Build a production-shaped single-row LazyFrame with sane defaults.
- Apply per-oracle overrides on top.
- Return the collected row as a plain dict.

Nothing here derives or asserts an expected value. Expected values come only
from ``tests/oracle/derivations/`` (stdlib-only, regulation-sourced).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.equity.calculator import EquityCalculator
from rwa_calc.engine.irb.calculator import IRBCalculator
from rwa_calc.engine.sa.calculator import SACalculator
from rwa_calc.engine.slotting.calculator import SlottingCalculator

REPORTING_DATE_CRR = date(2025, 12, 31)
REPORTING_DATE_B31 = date(2027, 6, 30)


# =============================================================================
# Configurations
# =============================================================================


#: Config *elections* an oracle may set. These are firm-level permissions the
#: regulation makes conditional (e.g. PS1/26 Art. 122(6) needs PRA permission
#: before the 65% / 135% investment-grade weights become available), so they
#: belong on the config rather than on the exposure row.
_CONFIG_ELECTIONS = ("use_investment_grade_assessment",)


def config_for(
    framework: str,
    permission: PermissionMode,
    elections: dict[str, Any] | None = None,
) -> CalculationConfig:
    """Build the CalculationConfig for an oracle's framework + permission mode."""
    kwargs = dict(elections or {})
    if framework == "CRR":
        return CalculationConfig.crr(
            reporting_date=REPORTING_DATE_CRR,
            permission_mode=permission,
            **kwargs,
        )
    if framework == "BASEL_3_1":
        return CalculationConfig.basel_3_1(
            reporting_date=REPORTING_DATE_B31,
            permission_mode=permission,
            **kwargs,
        )
    raise ValueError(f"unknown framework {framework!r}")


def split_elections(overrides: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Separate config elections from exposure-row columns."""
    elections = {k: overrides[k] for k in _CONFIG_ELECTIONS if k in overrides}
    columns = {k: v for k, v in overrides.items() if k not in elections}
    return columns, elections


# =============================================================================
# SA
# =============================================================================

# Defaults mirror tests/fixtures/single_exposure.py: a plain, drawn,
# on-balance-sheet, non-defaulted, unsecured exposure with no CRM.
_SA_DEFAULTS: dict[str, Any] = {
    "exposure_reference": "SINGLE",
    "exposure_class": "corporate",
    "cqs": None,
    "ltv": None,
    "is_sme": False,
    "is_infrastructure": False,
    "has_income_cover": False,
    "cp_is_managed_as_retail": False,
    "qualifies_as_retail": True,
    "property_type": None,
    "is_adc": False,
    "is_presold": False,
    "seniority": "senior",
    "cp_scra_grade": None,
    "cp_is_investment_grade": False,
    "is_defaulted": False,
    "provision_allocated": 0.0,
    "provision_deducted": 0.0,
    "currency": None,
    "cp_country_code": None,
    "borrower_income_currency": None,
    "residual_maturity_years": None,
    "original_maturity_years": None,
    "cp_entity_type": None,
    "is_short_term_trade_lc": False,
    "cp_is_natural_person": False,
    "cp_is_social_housing": False,
    "is_payroll_loan": False,
    "cp_sovereign_cqs": None,
    "cp_is_equivalent_jurisdiction": None,
    "cp_local_currency": None,
    "cp_institution_cqs": None,
    "is_hedged": False,
}

# Polars cannot infer a dtype from an all-null single-row column, so pin the
# ones whose default is None to the dtype the sealed sa_branch edge expects.
_SA_SCHEMA: dict[str, pl.DataType] = {
    "exposure_reference": pl.String(),
    "exposure_class": pl.String(),
    "cqs": pl.Int8(),
    "ltv": pl.Float64(),
    "property_type": pl.String(),
    "seniority": pl.String(),
    "cp_scra_grade": pl.String(),
    "currency": pl.String(),
    "cp_country_code": pl.String(),
    "borrower_income_currency": pl.String(),
    "residual_maturity_years": pl.Float64(),
    "original_maturity_years": pl.Float64(),
    "cp_entity_type": pl.String(),
    "cp_sovereign_cqs": pl.Int8(),
    "cp_is_equivalent_jurisdiction": pl.Boolean(),
    "cp_local_currency": pl.String(),
    "cp_institution_cqs": pl.Int8(),
    "prior_charge_ltv": pl.Float64(),
    "collateral_re_value": pl.Float64(),
    "guarantor_rw": pl.Float64(),
    "guaranteed_portion": pl.Float64(),
    "unguaranteed_portion": pl.Float64(),
    "guarantee_currency": pl.String(),
    "guarantor_entity_type": pl.String(),
    "due_diligence_override_rw": pl.Float64(),
    "sl_type": pl.String(),
    "sl_project_phase": pl.String(),
    "drawn_amount": pl.Float64(),
    "facility_limit": pl.Float64(),
}


#: Regulation-facing input names -> the engine's counterparty column names.
#: The oracle records speak the language of the article ("the counterparty's
#: entity type", "the sovereign's CQS"); the engine prefixes those with ``cp_``.
_INPUT_ALIASES = {
    "entity_type": "cp_entity_type",
    "country_code": "cp_country_code",
    "sovereign_cqs": "cp_sovereign_cqs",
    "local_currency": "cp_local_currency",
    "institution_cqs": "cp_institution_cqs",
    "scra_grade": "cp_scra_grade",
    "is_investment_grade": "cp_is_investment_grade",
    "is_managed_as_retail": "cp_is_managed_as_retail",
    "is_natural_person": "cp_is_natural_person",
    "is_social_housing": "cp_is_social_housing",
    "is_diversified": "is_diversified_portfolio",
    "is_equivalent_jurisdiction": "cp_is_equivalent_jurisdiction",
}

#: Engine columns an oracle may legitimately set that are absent from the
#: defaults above, because they are only meaningful for a few fact patterns.
_EXTRA_INPUT_COLUMNS = frozenset(
    {
        "is_qualifying_re",  # PS1/26 Art. 124A regulatory real estate flag
        "is_qrre_transactor",  # PS1/26 Art. 123(3)(a) transactor flag
        "is_revolving",
        "beel",  # Art. 154(1)(a) best estimate of expected loss
        "cp_is_financial_sector_entity",  # Art. 153(2)
        "requires_fi_scalar",
        "approach",
        "slotting_category",
        "is_hvcre",
        "is_short_maturity",
        "is_pre_operational",
        "has_short_term_ecai",
        "cp_eca_score",
    }
)


def resolve_aliases(overrides: dict[str, Any]) -> dict[str, Any]:
    """Rename regulation-facing input keys to engine column names."""
    return {_INPUT_ALIASES.get(key, key): value for key, value in overrides.items()}


def reject_unknown_columns(columns: dict[str, Any], defaults: dict[str, Any]) -> None:
    """Fail loudly on an override that resolves to no engine column.

    An unrecognised key would otherwise be added to the frame as a dead column:
    the engine reads the *default* value of the column the oracle meant to set,
    the oracle silently tests the wrong fact pattern, and the resulting
    disagreement looks like an engine defect. That is exactly how a spurious
    "``cp_is_equivalent_jurisdiction`` has no effect" finding was produced --
    the alias for it was missing, so the flag never reached the column.

    This is the ``LESSONS.md`` B1 failure mode (a presence guard on a name no
    pipeline produces) applied to the oracle's own harness.
    """
    allowed = set(defaults) | set(_SA_SCHEMA) | set(_IRB_SCHEMA) | _EXTRA_INPUT_COLUMNS
    unknown = sorted(set(columns) - allowed)
    if unknown:
        raise ValueError(
            f"oracle input(s) {unknown} match no engine column and no alias in "
            f"_INPUT_ALIASES. They would be added to the frame as dead columns "
            f"and the oracle would silently test the wrong fact pattern. Add the "
            f"alias, or add the column to _EXTRA_INPUT_COLUMNS if it is real."
        )


def run_sa(*, framework: str, ead: float, **overrides: Any) -> dict[str, Any]:
    """Run the SA branch on one row. Returns the collected row as a dict."""
    columns, elections = split_elections(resolve_aliases(overrides))
    reject_unknown_columns(columns, _SA_DEFAULTS)
    data = dict(_SA_DEFAULTS)
    data["ead_final"] = ead
    data["ead_gross"] = ead
    data.update(columns)
    if data.get("original_maturity_years") is None:
        data["original_maturity_years"] = data.get("residual_maturity_years")

    lf = _frame(data).lazy()
    config = config_for(framework, PermissionMode.STANDARDISED, elections)
    row = SACalculator().calculate_branch(lf, config).collect().to_dicts()[0]
    row["rwa"] = row.get("rwa_post_factor")
    return row


# =============================================================================
# IRB
# =============================================================================

_IRB_DEFAULTS: dict[str, Any] = {
    "exposure_reference": "SINGLE",
    "exposure_class": "corporate",
    "seniority": "senior",
    "maturity": 2.5,
    "purchased_receivables_subtype": None,
    "cp_is_financial_sector_entity": False,
    "is_sme": False,
    "sme_size_metric_gbp": None,
    "is_infrastructure": False,
    "is_qrre_transactor": False,
    "requires_fi_scalar": False,
    "has_one_day_maturity_floor": False,
    "is_defaulted": False,
    "beel": 0.0,
    "total_collateral_for_lgd": 0.0,
    "crm_alloc_financial": 0.0,
    "crm_alloc_covered_bond": 0.0,
    "crm_alloc_receivables": 0.0,
    "crm_alloc_real_estate": 0.0,
    "crm_alloc_other_physical": 0.0,
    "crm_alloc_life_insurance": 0.0,
    "provision_allocated": 0.0,
    "ava_amount": 0.0,
    "other_own_funds_reductions": 0.0,
    "exposure_volatility_haircut": 0.0,
}

#: Sentinel: "lgd_post_crm was not supplied, mirror lgd onto it".
_MIRROR_LGD: Any = object()

_IRB_SCHEMA: dict[str, pl.DataType] = {
    "exposure_reference": pl.String(),
    "exposure_class": pl.String(),
    "seniority": pl.String(),
    "lgd": pl.Float64(),
    "lgd_post_crm": pl.Float64(),
    "purchased_receivables_subtype": pl.String(),
    "sme_size_metric_gbp": pl.Float64(),
    "turnover_m": pl.Float64(),
    "collateral_type": pl.String(),
}


def run_irb(
    *,
    framework: str,
    ead: float,
    pd_value: float,
    lgd: float | None,
    lgd_post_crm: float | None = _MIRROR_LGD,
    approach: str = "foundation_irb",
    **overrides: Any,
) -> dict[str, Any]:
    """Run the IRB branch on one row.

    ``lgd`` is what the *bank* supplies. Pass ``None`` on a Foundation IRB row:
    the engine then has to derive the supervisory LGD from Art. 161 itself and
    publish it on the ``lgd`` column, which is what makes the F-IRB LGD oracles
    a test of that table rather than of the risk-weight formula alone.

    ``lgd_post_crm`` is what the CRM stage would hand the branch, and is the
    value the risk-weight formula actually consumes. It defaults to mirroring
    ``lgd`` (the A-IRB case: own estimate, engine applies any input floor).
    F-IRB oracles set it explicitly to the supervisory LGD, because the CRM
    stage -- which this driver bypasses -- is what populates it in production.
    """
    data = dict(_IRB_DEFAULTS)
    data["ead_final"] = ead
    data["ead_gross"] = ead
    data["ead_for_crm"] = ead
    data["pd"] = pd_value
    data["lgd"] = lgd
    data["lgd_post_crm"] = lgd if lgd_post_crm is _MIRROR_LGD else lgd_post_crm
    data["approach"] = approach
    columns = resolve_aliases(overrides)
    reject_unknown_columns(columns, _IRB_DEFAULTS)
    data.update(columns)

    lf = _frame(data).lazy()
    config = config_for(framework, PermissionMode.IRB)
    return IRBCalculator().calculate_branch(lf, config).collect().to_dicts()[0]


# =============================================================================
# Slotting and equity
# =============================================================================

_SLOTTING_DEFAULTS: dict[str, Any] = {
    "exposure_reference": "SINGLE",
    "approach": "slotting",
    "slotting_category": "strong",
    "is_hvcre": False,
    "sl_type": "project_finance",
    "is_short_maturity": False,
    "is_pre_operational": False,
    "maturity_date": None,
    "is_infrastructure": False,
    "is_sme": False,
    "provision_allocated": 0.0,
    "ava_amount": 0.0,
    "other_own_funds_reductions": 0.0,
}


def run_slotting(*, framework: str, ead: float, **overrides: Any) -> dict[str, Any]:
    """Run the slotting branch on one row."""
    data = dict(_SLOTTING_DEFAULTS)
    data["ead_final"] = ead
    columns = resolve_aliases(overrides)
    reject_unknown_columns(columns, _SLOTTING_DEFAULTS)
    data.update(columns)
    lf = _frame(data, extra_schema={"maturity_date": pl.Date()}).lazy()
    config = config_for(framework, PermissionMode.IRB)
    return SlottingCalculator().calculate_branch(lf, config).collect().to_dicts()[0]


_EQUITY_DEFAULTS: dict[str, Any] = {
    "exposure_reference": "SINGLE",
    "equity_type": "listed",
    "is_diversified_portfolio": False,
    "is_speculative": False,
    "is_exchange_traded": False,
    "is_government_supported": False,
    "ciu_approach": None,
    "ciu_mandate_rw": None,
    "ciu_third_party_calc": None,
    "ciu_look_through_rw": None,
    "ciu_unrestricted_access": None,
}

_EQUITY_SCHEMA: dict[str, pl.DataType] = {
    "exposure_reference": pl.String(),
    "equity_type": pl.String(),
    "ciu_approach": pl.String(),
    "ciu_mandate_rw": pl.Float64(),
    "ciu_third_party_calc": pl.Boolean(),
    "ciu_look_through_rw": pl.Float64(),
    "ciu_unrestricted_access": pl.Boolean(),
}


def run_equity(
    *,
    framework: str,
    ead: float,
    permission: PermissionMode = PermissionMode.STANDARDISED,
    **overrides: Any,
) -> dict[str, Any]:
    """Run the equity branch on one row."""
    data = dict(_EQUITY_DEFAULTS)
    data["ead_final"] = ead
    columns = resolve_aliases(overrides)
    reject_unknown_columns(columns, _EQUITY_DEFAULTS | _EQUITY_SCHEMA)
    data.update(columns)
    lf = _frame(data, extra_schema=_EQUITY_SCHEMA).lazy()
    config = config_for(framework, permission)
    return EquityCalculator().calculate_branch(lf, config).collect().to_dicts()[0]


# =============================================================================
# Private helpers
# =============================================================================


def _frame(
    data: dict[str, Any],
    *,
    extra_schema: dict[str, pl.DataType] | None = None,
) -> pl.DataFrame:
    """One-row DataFrame with dtypes pinned for the columns that default null."""
    schema: dict[str, pl.DataType] = {**_SA_SCHEMA, **_IRB_SCHEMA}
    if extra_schema:
        schema = {**schema, **extra_schema}
    overrides = {k: v for k, v in schema.items() if k in data}
    return pl.DataFrame({k: [v] for k, v in data.items()}, schema_overrides=overrides)
