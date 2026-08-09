"""
Engine drivers for the oracle suite.

This is the *only* module in ``tests/oracle/`` that imports ``rwa_calc``. It
exists to drive the engine with an explicit, complete single-row frame so an
oracle can exercise any regulatory path — including ones the shared helper in
``tests/fixtures/single_exposure.py`` does not expose (QRRE transactor flags,
prior charges, self-build, slotting phases, ...).

Pipeline position tested:
    (bypasses hierarchy / classifier / CRM) -> <Approach>Calculator.calculate_branch
    hierarchy / classifier bypassed -> CRMProcessor -> SACalculator  (``run_crm_sa``)

``run_crm_sa`` is the one exception to the bypass, and it has to be: phase O3
is the CRM stage. Art. 222 writes ``fcsm_*`` columns that only the SA
calculator's risk-weight substitution reads, Art. 223 rewrites EAD, and
Art. 235 splits the exposure into a guaranteed leg and a remainder leg -- none
of which can be reached by calling a calculator's branch directly.

Key responsibilities:
- Build a production-shaped single-row LazyFrame with sane defaults.
- Apply per-oracle overrides on top.
- Return the collected row as a plain dict.

Nothing here derives or asserts an expected value. Expected values come only
from ``tests/oracle/derivations/`` (stdlib-only, regulation-sourced).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import polars as pl

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.edges import CLASSIFIER_EXIT_EDGE
from rwa_calc.data.schemas import COLLATERAL_SCHEMA, GUARANTEE_SCHEMA
from rwa_calc.domain.enums import ApproachType, CRMCollateralMethod, PermissionMode
from rwa_calc.engine.crm.processor import CRMProcessor
from rwa_calc.engine.equity.calculator import EquityCalculator
from rwa_calc.engine.irb.calculator import IRBCalculator
from rwa_calc.engine.sa.calculator import SACalculator
from rwa_calc.engine.slotting.calculator import SlottingCalculator
from tests.fixtures.resolved_bundle import make_classified_bundle, make_counterparty_lookup

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
    """Run the SA branch on one row. Returns the collected row as a dict.

    Phase O3 rides this entry point: an oracle that supplies ``collateral`` /
    ``guarantees`` needs the CRM stage in front of the SA branch, and the
    dispatch table in ``test_oracle.py`` keys only on ``record["approach"]``.
    Delegating here keeps the O3 records on ``approach: "SA"`` rather than
    requiring a new approach key. See ``run_crm_sa``.
    """
    if _CRM_DRIVER_KEYS.intersection(overrides):
        return run_crm_sa(framework=framework, ead=ead, **overrides)

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
# CRM -> SA  (phase O3)
# =============================================================================

#: Driver-level keywords an O3 oracle passes that are NOT exposure columns.
#: ``run_sa`` keys on their presence to route through the CRM stage.
_CRM_DRIVER_KEYS = frozenset(
    {"collateral", "guarantees", "guarantors", "crm_method", "exposure_maturity_years"}
)

#: A plain drawn on-balance-sheet SA loan, in the CRM stage's input vocabulary.
#: Every key is a declared ``classifier_exit`` column -- the lenient seal
#: PROJECTS to that contract (``EdgeContract.conform_lenient`` ends in
#: ``lf.select(emitted)``), so a column the edge does not declare is DROPPED
#: without a word. That is the ``LESSONS.md`` B1 failure mode: the oracle would
#: test the default instead of the value it set. ``_reject_unknown_frame_columns``
#: is what makes it loud.
_CRM_EXPOSURE_DEFAULTS: dict[str, Any] = {
    "exposure_reference": "EXP001",
    "counterparty_reference": "CP001",
    "exposure_class": "corporate",
    "approach": ApproachType.SA.value,
    "drawn_amount": 0.0,
    "interest": 0.0,
    "nominal_amount": 0.0,
    "risk_type": "FR",
    "seniority": "senior",
    "parent_facility_reference": "FAC001",
    "currency": "GBP",
    "original_currency": "GBP",
    "cqs": None,
    "is_defaulted": False,
    "is_sft": False,
    "maturity_date": None,
}

#: One pledge of eligible financial collateral against the single exposure.
#: Keys are ``data/schemas.py::COLLATERAL_SCHEMA`` columns, and the frame is
#: built at that schema's dtypes -- the CRM processor diagonally concats input
#: collateral with the synthetic netting frame, which resolves only when the
#: overlapping dtypes match.
_COLLATERAL_DEFAULTS: dict[str, Any] = {
    "collateral_reference": "COLL001",
    "beneficiary_reference": "EXP001",
    "beneficiary_type": "exposure",
    "collateral_type": "cash",
    "market_value": 0.0,
    "currency": "GBP",
    "issuer_cqs": None,
    "issuer_type": None,
    "residual_maturity_years": None,
    "is_eligible_financial_collateral": True,
    "is_main_index": None,
    "is_listed": None,
}

#: One guarantee over the single exposure. ``includes_restructuring=True`` keeps
#: the Art. 233(2) 40% restructuring-exclusion haircut out of the way so the
#: Art. 233(3) currency-mismatch adjustment is the only one in play.
_GUARANTEE_DEFAULTS: dict[str, Any] = {
    "guarantee_reference": "GTE001",
    "guarantor": "GTOR001",
    "beneficiary_reference": "EXP001",
    "beneficiary_type": "exposure",
    "protection_type": "guarantee",
    "includes_restructuring": True,
    "currency": "GBP",
    "amount_covered": None,
    "percentage_covered": None,
    "maturity_date": None,
    "original_maturity_years": None,
}


def run_crm_sa(
    *,
    framework: str,
    ead: float,
    collateral: list[dict[str, Any]] | None = None,
    guarantees: list[dict[str, Any]] | None = None,
    guarantors: list[dict[str, Any]] | None = None,
    crm_method: str = "comprehensive",
    exposure_maturity_years: float | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Run the CRM stage and then the SA branch over one obligor exposure.

    The only oracle driver that does NOT bypass CRM. It is needed because the
    whole of phase O3 lives in that stage: Art. 222 sets ``fcsm_*`` columns the
    SA calculator reads, Art. 223 rewrites EAD, and Art. 235 splits the row.

    ``collateral`` / ``guarantees`` are lists of partial rows merged onto
    ``_COLLATERAL_DEFAULTS`` / ``_GUARANTEE_DEFAULTS``. ``guarantors`` describes
    the protection providers (``ref``, ``entity_type``, ``cqs``) and becomes the
    ``CounterpartyLookup`` the guarantee substitution resolves the guarantor's
    class and CQS through.

    ``exposure_maturity_years`` is a driver-level parameter, not a column: the
    articles speak in maturities and the engine's Art. 238 gate reads a Date, so
    the conversion happens here. It matters for every collateral oracle -- a null
    exposure maturity makes the engine take T = 5 years (Art. 238(1)), which puts
    a maturity-mismatch factor of ``(t - 0.25) / (T - 0.25)`` on every pledge
    whose residual maturity is under five years and would silently turn an
    Art. 224 haircut oracle into an Art. 238 one.

    Art. 235(1) splits a guaranteed exposure into a guaranteed leg and a
    remainder leg, so the return is the AGGREGATE over the legs the engine
    produced: total ``ead_final``, total RWA, and ``risk_weight`` as
    ``total RWA / total EAD`` -- which is exactly the weight the Art. 235(1)
    formula defines. For an unguaranteed row there is one leg and the aggregate
    is that leg.
    """
    columns = resolve_aliases(overrides)
    _reject_unknown_frame_columns(columns, set(CLASSIFIER_EXIT_EDGE.columns), "exposure")
    data = dict(_CRM_EXPOSURE_DEFAULTS)
    data["drawn_amount"] = ead
    data.update(columns)

    reporting_date = REPORTING_DATE_CRR if framework == "CRR" else REPORTING_DATE_B31
    if exposure_maturity_years is not None:
        data["maturity_date"] = reporting_date + timedelta(
            days=round(exposure_maturity_years * 365)
        )

    exposures = pl.DataFrame(
        {k: [v] for k, v in data.items()},
        schema_overrides={"cqs": pl.Int8(), "maturity_date": pl.Date()},
    ).lazy()
    # Production hierarchy always emits the ancestor closure; a typed null here
    # would silently de-activate the facility-level collateral cascade.
    exposures = exposures.with_columns(
        pl.concat_list(pl.col("parent_facility_reference")).alias("ancestor_facilities")
    )

    config = _crm_config(framework, crm_method)
    bundle = make_classified_bundle(
        all_exposures=exposures,
        counterparty_lookup=_guarantor_lookup(guarantors),
        collateral=_crm_table(collateral, _COLLATERAL_DEFAULTS, COLLATERAL_SCHEMA, "collateral"),
        guarantees=_crm_table(guarantees, _GUARANTEE_DEFAULTS, GUARANTEE_SCHEMA, "guarantee"),
    )
    crm = CRMProcessor().get_crm_unified_bundle(bundle, config)
    legs = SACalculator().calculate_branch(crm.exposures, config).collect()
    return _aggregate_legs(legs, [error.code for error in crm.crm_errors])


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


def _reject_unknown_frame_columns(
    columns: dict[str, Any],
    allowed: set[str],
    frame: str,
) -> None:
    """``reject_unknown_columns`` for the CRM stage's three input frames.

    Same failure mode, different authority. The exposure frame's authority is
    the ``classifier_exit`` edge contract and the collateral / guarantee frames'
    is their loader schema, so ``allowed`` is passed in rather than assembled
    from the branch-driver defaults. Keying on the contract rather than on a
    hand-written list is deliberate (``LESSONS.md`` B3): a list would drift out
    of step with the engine and the oracle would stop noticing.
    """
    unknown = sorted(set(columns) - allowed)
    if unknown:
        raise ValueError(
            f"oracle {frame} input(s) {unknown} match no engine column. The seal "
            f"(exposure) or the frame build (collateral / guarantee) would DROP "
            f"them, the engine would read the default of the column the oracle "
            f"meant to set, and the resulting disagreement would look exactly "
            f"like an engine defect."
        )


def _crm_config(framework: str, crm_method: str) -> CalculationConfig:
    """The run config for a CRM oracle, including the Art. 191A method election."""
    method = (
        CRMCollateralMethod.SIMPLE if crm_method == "simple" else CRMCollateralMethod.COMPREHENSIVE
    )
    if framework == "CRR":
        return CalculationConfig.crr(
            reporting_date=REPORTING_DATE_CRR,
            permission_mode=PermissionMode.STANDARDISED,
            crm_collateral_method=method,
        )
    if framework == "BASEL_3_1":
        return CalculationConfig.basel_3_1(
            reporting_date=REPORTING_DATE_B31,
            permission_mode=PermissionMode.STANDARDISED,
            crm_collateral_method=method,
        )
    raise ValueError(f"unknown framework {framework!r}")


def _crm_table(
    rows: list[dict[str, Any]] | None,
    defaults: dict[str, Any],
    schema: dict[str, Any],
    frame: str,
) -> pl.LazyFrame | None:
    """Build a collateral / guarantee frame at its loader dtypes, or None.

    Every column the loader schema declares is present -- so the frame is
    shape-identical to the one the CRM stage sees in production -- with the
    oracle's values on top of ``defaults`` and typed nulls everywhere else.
    """
    if not rows:
        return None
    dtypes = {name: spec.dtype for name, spec in schema.items()}
    built: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        _reject_unknown_frame_columns(row, set(dtypes), frame)
        merged: dict[str, Any] = dict.fromkeys(dtypes)
        merged.update(defaults)
        merged.update(row)
        merged[f"{frame}_reference"] = f"{frame.upper()[:4]}{index:03d}"
        built.append(merged)
    return pl.DataFrame(built, schema=dtypes).lazy()


def _guarantor_lookup(guarantors: list[dict[str, Any]] | None) -> Any:
    """The ``CounterpartyLookup`` the Art. 235 substitution resolves through.

    The obligor is always the unrated corporate ``CP001``; each guarantor
    contributes its ``entity_type`` (which Art. 201 eligibility and the
    guarantor risk-weight lookup both key on) and its ``cqs``.
    """
    refs = ["CP001"]
    types = ["corporate"]
    cqs: list[int | None] = [None]
    for guarantor in guarantors or []:
        refs.append(guarantor["ref"])
        types.append(guarantor["entity_type"])
        cqs.append(guarantor.get("cqs"))
    return make_counterparty_lookup(
        counterparties=pl.LazyFrame(
            {"counterparty_reference": refs, "entity_type": types},
            schema={"counterparty_reference": pl.String(), "entity_type": pl.String()},
        ),
        parent_mappings=pl.LazyFrame(
            schema={
                "child_counterparty_reference": pl.String(),
                "parent_counterparty_reference": pl.String(),
            }
        ),
        ultimate_parent_mappings=pl.LazyFrame(
            schema={
                "counterparty_reference": pl.String(),
                "ultimate_parent_reference": pl.String(),
                "hierarchy_depth": pl.Int32(),
            }
        ),
        rating_inheritance=pl.LazyFrame(
            {
                "counterparty_reference": refs,
                "cqs": cqs,
                "rating_type": ["external"] * len(refs),
            },
            schema={
                "counterparty_reference": pl.String(),
                "cqs": pl.Int8(),
                "rating_type": pl.String(),
            },
        ),
    )


#: Per-leg engine columns the CRM aggregate carries through for diagnosis. None
#: is compared by ``test_oracle.py`` -- they exist so a failure message can name
#: the CRM intermediate that moved, not only the RWA.
_CRM_DIAGNOSTIC_SUMS = (
    "collateral_market_value",
    "collateral_adjusted_value",
    "fcsm_collateral_value",
    "guaranteed_portion",
    "unguaranteed_portion",
)
_CRM_DIAGNOSTIC_FIRST = (
    "fcsm_collateral_rw",
    "guarantor_rw",
    "guarantee_status",
    "guarantee_fx_haircut",
    "ead_calculation_method",
)


def _aggregate_legs(legs: pl.DataFrame, error_codes: list[str]) -> dict[str, Any]:
    """Total the Art. 235(1) legs into the one row the oracle compares against."""
    total_ead = float(legs["ead_final"].sum())
    total_rwa = float(legs["rwa_post_factor"].sum())
    row: dict[str, Any] = {
        "ead_final": total_ead,
        "rwa_post_factor": total_rwa,
        "rwa": total_rwa,
        "risk_weight": (total_rwa / total_ead) if total_ead else 0.0,
        "legs": legs.height,
        "crm_error_codes": error_codes,
    }
    for name in _CRM_DIAGNOSTIC_SUMS:
        if name in legs.columns:
            row[name] = float(legs[name].fill_null(0.0).sum())
    for name in _CRM_DIAGNOSTIC_FIRST:
        if name in legs.columns:
            row[name] = legs[name][0]
    return row
