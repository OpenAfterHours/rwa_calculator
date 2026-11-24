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
    RawDataBundle -> PipelineOrchestrator (every stage)               (``run_pipeline``)

``run_crm_sa`` is the one exception to the bypass among the branch drivers, and
it has to be: phase O3 is the CRM stage. Art. 222 writes ``fcsm_*`` columns that
only the SA calculator's risk-weight substitution reads, Art. 223 rewrites EAD,
and Art. 235 splits the exposure into a guaranteed leg and a remainder leg --
none of which can be reached by calling a calculator's branch directly.

``run_pipeline`` (P5.43) exists because the branch drivers hand the calculator
the very column the article keys on, so a branch oracle can be green while that
column never reaches the branch in production: P1.316 made the Art. 121(1)
Table 5 oracles pass while every leg of a real portfolio still took the 100%
unrated fallback, because ``cp_sovereign_cqs`` was set by the driver and by
nothing upstream. ``run_pipeline`` translates a record into the raw input tables
a firm would load and runs them through ``PipelineOrchestrator``, so the same
hand-derived figure is reached the way production reaches it. It drives only the
curated records listed in ``test_oracle_pipeline.py``.

Every stage RUNS, but the curated records reach only part of what the stages do,
and a green pipeline oracle says nothing about the rest. Read off the exit of
every curated run, the paths no curated record exercises are: FX conversion (no
``fx_rates`` is supplied; ``fx_rate_applied`` is null), the date-derived IRB
``M`` (an F-IRB record's ``M`` arrives as the ``effective_maturity`` override),
the real-estate splitter (no property collateral; ``re_split_mode`` is null),
CCF and off-balance-sheet conversion (each exposure is a fully drawn loan or an
equity holding; ``ead_from_ccf`` is 0 or null), the facility hierarchy (no
facility rows; depth 0), provisions (none; ``provision_allocated`` 0), a
BINDING output floor (``floor_impact_rwa`` is 0 on every Basel 3.1 run), and two
limbs of the PS1/26 Art. 121(6) sovereign floor: the floor binding (the one
Basel 3.1 institution, ORC-052, is lent in its local currency and reads
``domestic_currency``), and the floor's fallback domesticity test -- every
obligor is loaded with its jurisdiction's ``local_currency``, so the floor never
falls back to the engine's UK/EU country map, nor reaches the indeterminate case
that map leaves for any other jurisdiction (P1.333; the branch oracles ORC-052
to ORC-055 reach that, each reading ``UNKNOWN_FALLBACK`` with
``cp_local_currency`` null) -- plus every approach outside
``PIPELINE_APPROACHES``, which ``run_pipeline`` refuses.

Key responsibilities:
- Build a production-shaped single-row LazyFrame with sane defaults.
- Apply per-oracle overrides on top.
- Return the collected row as a plain dict.
- For ``run_pipeline``: translate a record into raw tables, reject any input it
  has no faithful translation for, and total the pipeline's legs for the record.

Nothing here derives or asserts an expected value. Expected values come only
from ``tests/oracle/derivations/`` (stdlib-only, regulation-sourced).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import polars as pl

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.edges import CLASSIFIER_EXIT_EDGE
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    EQUITY_EXPOSURE_SCHEMA,
    GUARANTEE_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
    SPECIALISED_LENDING_SCHEMA,
)
from rwa_calc.domain.branch_reasons import BRANCH_REASON_VOCABULARIES
from rwa_calc.domain.enums import ApproachType, CRMCollateralMethod, PermissionMode
from rwa_calc.engine.crm.processor import CRMProcessor
from rwa_calc.engine.equity.calculator import EquityCalculator
from rwa_calc.engine.irb.calculator import IRBCalculator
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.engine.sa.calculator import SACalculator
from rwa_calc.engine.slotting.calculator import SlottingCalculator
from tests.fixtures.irb_test_helpers import create_full_irb_model_permissions
from tests.fixtures.raw_bundle import make_raw_bundle
from tests.fixtures.resolved_bundle import make_classified_bundle, make_counterparty_lookup

if TYPE_CHECKING:
    from rwa_calc.contracts.errors import CalculationError

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
    the protection providers (``ref``, ``entity_type``, ``cqs``, and optionally
    ``country_code`` / ``is_equivalent_jurisdiction``) and becomes the
    ``CounterpartyLookup`` the guarantee substitution resolves the guarantor's
    class, CQS and jurisdiction through.

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
    "is_speculative": False,
    "is_exchange_traded": False,
    "is_government_supported": False,
    "ciu_approach": None,
    "ciu_mandate_rw": None,
    "ciu_third_party_calc": None,
    "ciu_look_through_rw": None,
    "ciu_unrestricted_access": None,
    # Glossary "higher risk equity exposure" limb (2): years the underlying
    # business has existed. Null is the engine contract's own default.
    "business_age_years": None,
}

_EQUITY_SCHEMA: dict[str, pl.DataType] = {
    "exposure_reference": pl.String(),
    "equity_type": pl.String(),
    "ciu_approach": pl.String(),
    "ciu_mandate_rw": pl.Float64(),
    "ciu_third_party_calc": pl.Boolean(),
    "ciu_look_through_rw": pl.Float64(),
    "ciu_unrestricted_access": pl.Boolean(),
    "business_age_years": pl.Float64(),
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
# Full pipeline  (P5.43)
# =============================================================================

#: ``record["approach"]`` -> the ``approach_applied`` the pipeline must reach for
#: a translation to be testing the record's fact pattern at all. An approach
#: missing here has no translation yet, and ``run_pipeline`` refuses it.
PIPELINE_APPROACHES: dict[str, str] = {
    "SA": ApproachType.SA.value,
    "FIRB": ApproachType.FIRB.value,
    "SLOTTING": ApproachType.SLOTTING.value,
    "EQUITY": ApproachType.EQUITY.value,
}

#: Record input -> the aggregator-exit column that must carry it, unchanged, on
#: every leg the pipeline produced. This is the check the branch drivers cannot
#: make: they SET these columns, so they can never see one fail to arrive. A null
#: input must arrive as a null -- that is the whole point of the Art. 121(2)
#: survivor (ORC-021) beside the Table 5 ladder, and of ``cqs``: an unrated
#: institution's ``cqs`` must still be null at the exit, or something upstream
#: lent it a rating (an Art. 120 Table 3 lift of the sovereign's CQS agrees with
#: Table 5 at every step but CQS 3, so the numbers alone barely see it).
PIPELINE_ECHOES: dict[str, str] = {
    "entity_type": "cp_entity_type",
    "country_code": "cp_country_code",
    "sovereign_cqs": "cp_sovereign_cqs",
    "scra_grade": "cp_scra_grade",
    "cqs": "cqs",
    "currency": "currency",
    "pd_value": "pd",
    "maturity": "irb_maturity_m",
    "slotting_category": "slotting_category",
    "sl_type": "sl_type",
    "is_short_maturity": "is_short_maturity",
    "equity_type": "equity_type",
}

#: Record input stated in years -> the aggregator-exit column that must carry it
#: to within ``PIPELINE_YEAR_ECHO_TOLERANCE``. Not exact, because the translation
#: places the loan's dates on whole days (0.25 years is 91 days, which the
#: pipeline reads back as 0.2493). ``original_maturity_years`` is load-bearing:
#: CRR Art. 121(3) gives an unrated institution 20% on an ORIGINAL effective
#: maturity of three months or less, whatever its sovereign's step.
PIPELINE_YEAR_ECHOES: dict[str, str] = {
    "original_maturity_years": "original_maturity_years",
}

#: One day, in the 365-day years ``_pipeline_loan`` lays the dates out in.
PIPELINE_YEAR_ECHO_TOLERANCE = 1 / 365

#: Record inputs the aggregator exit does NOT carry as the record states them:
#: why, and what holds each one instead. Most are held by the numbers
#: ``test_pipeline_matches_oracle`` compares (or, for ``exposure_class``, by the
#: class assertion), so a slip in translating one surfaces as a wrong figure
#: rather than as a missing input -- each such reason names the move measured
#: when that input was varied on a curated record. Three are INERT: varied on
#: every curated record that states them, they moved no compared figure, so
#: NOTHING in the pipeline module holds them. They are listed to keep the
#: partition total, not as coverage.
#: Every input a curated record states must be in exactly one of this map,
#: ``PIPELINE_ECHOES`` and ``PIPELINE_YEAR_ECHOES`` -- the pipeline test module
#: asserts it, so a new record cannot bring an input nobody has classified.
PIPELINE_UNECHOED_INPUTS: dict[str, str] = {
    "ead": (
        "the exit carries ead_final, compared as `ead` (measured: doubling ORC-003's "
        "doubles ead_final)"
    ),
    "exposure_class": "derived by the classifier; asserted as every leg's class",
    "lgd_post_crm": "derived by the CRM stage; compared as `lgd_applied`",
    "lgd": (
        "null means no own estimate; the exit carries the supervisory LGD in its "
        "place, compared as `firb_supervisory_lgd` (a non-null one has no translation "
        "and raises)"
    ),
    "residual_maturity_years": (
        "INERT on this record's path (measured): 5.0 -> 0.2, original maturity held, "
        "moved no compared figure on ORC-105 / 020 / 106 / 109 / 021 / 052. The exit's "
        "residual_maturity_years is null; the input only places the loan's "
        "maturity_date. Nothing here holds it"
    ),
    "exposure_maturity_years": (
        "INERT on this record's path (measured): 0.25 -> 5.0 moved no compared figure "
        "on ORC-243 / 244. The input only places the loan's maturity_date. Nothing "
        "here holds it"
    ),
    "crm_method": (
        "a run election (CalculationConfig), not a column; held by the numbers "
        "(measured: comprehensive for ORC-244's simple moves ead_final 1.0m -> 0.7m "
        "and risk_weight 1.05 -> 1.5)"
    ),
    "collateral": (
        "pledged items; held by ead / risk_weight / rwa (measured: dropping ORC-243's "
        "moves ead_final 630k -> 1.0m)"
    ),
    "guarantees": (
        "guarantee items; held by the legs' totals (measured: halving ORC-259's cover "
        "moves risk_weight 0.98 -> 1.24)"
    ),
    "guarantors": (
        "provider rows; held by the legs' totals (measured: ORC-259's guarantor at "
        "CQS 3 for 1 moves risk_weight 0.98 -> 1.10)"
    ),
    "is_exchange_traded": (
        "INERT on this record's path (measured): True -> False moved no compared "
        "figure on ORC-036 / 080, and the exit does not carry it. Nothing here holds it"
    ),
}

#: Inputs the pipeline COMPUTES rather than reads. Translating one into an input
#: would hand the pipeline the answer the classifier or the CRM stage exists to
#: produce, so each is asserted on the output instead: ``exposure_class`` by the
#: fact-pattern test, ``lgd_post_crm`` through the record's own ``lgd_applied``
#: and ``firb_supervisory_lgd`` intermediates.
_PIPELINE_DERIVED_INPUTS = frozenset({"exposure_class", "lgd_post_crm"})

_PIPELINE_EXPOSURE = "ORACLE_EXP"
_PIPELINE_OBLIGOR = "ORACLE_CP"
#: The model id ``create_full_irb_model_permissions`` grants F-IRB, A-IRB and
#: slotting for. A mismatch routes every IRB record standardised, which the
#: fact-pattern test reports as an ``approach_applied`` disagreement.
_PIPELINE_MODEL_ID = "TEST_FULL_IRB"
_PIPELINE_RATING_DATE = date(2015, 1, 1)
#: Jurisdiction of incorporation -> its local currency, loaded as the obligor's
#: raw ``local_currency`` beside its ``country_code``, as a firm loads it. A
#: record states the jurisdiction but not its currency, and PS1/26
#: Art. 121(6)(a)(i) turns on exactly that pair: the floor applies where the
#: exposure "is not in the local currency of the jurisdiction of incorporation of
#: the debtor institution". Left unloaded, the engine can name the local currency
#: only for the UK and the EU, so a US obligor's domesticity is indeterminate and
#: the run takes the engine's UNKNOWN_FALLBACK limb (P1.333) instead of the
#: record's fact pattern -- for ORC-052, a US bank lent USD, 40% either way but
#: not for the record's reason. A jurisdiction missing here raises.
_JURISDICTION_LOCAL_CURRENCY: dict[str, str] = {"GB": "GBP", "US": "USD"}
#: The maturity of a record that states none: past every short-term limb the
#: curated records could otherwise trip (the three-month institution limbs and
#: the Art. 153(5) 2.5-year slotting column).
_PIPELINE_DEFAULT_MATURITY_YEARS = 5.0
#: ``is_short_maturity`` ("remaining maturity of less than 2.5 years") as a maturity.
_SLOTTING_SHORT_MATURITY_YEARS = 1.0

#: The exposure's own RWEA. Where the output floor runs, ``rwa_final`` carries the
#: entity-level floor add-on (``.claude/LESSONS.md`` G) and the pre-floor figure
#: is ``rwa_pre_floor``; where no floor runs that column is not emitted and
#: ``rwa_final`` IS the pre-floor amount. The carrier used is returned, and the
#: test asserts which one each regime must resolve to.
_PRE_FLOOR_RWA_CARRIERS = ("rwa_pre_floor", "rwa_final")

#: Per-leg columns returned for a single-leg result -- the carriers
#: ``test_oracle._COMPARISONS`` reads -- so a disagreement names the intermediate
#: that moved. A multi-leg result has no single value for them and omits them.
_PIPELINE_SINGLE_LEG_COLUMNS = (
    "pd_floored",
    "lgd",
    "lgd_floored",
    "irb_maturity_m",
    "correlation",
    "maturity_adjustment",
    "scaling_factor",
    "supporting_factor",
    "mortgage_rw_floor_adjustment",
)


def run_pipeline(record: dict[str, Any]) -> dict[str, Any]:
    """Translate one oracle record into raw input tables and run every stage.

    The record speaks calculator vocabulary (``cp_*`` columns, a pre-assigned
    ``exposure_class``); a firm loads counterparties, loans, ratings and
    protection. ``_translate_record`` maps one onto the other, key by key, and
    raises on any input it has no faithful translation for -- the same refusal
    ``reject_unknown_columns`` makes for the branch drivers, because a key that
    silently translates to nothing makes the pipeline test the default.

    One record per run. Several records in one bundle would couple them through
    the portfolio-level steps (the output floor, retail granularity, the
    facility hierarchy), and a disagreement could then belong to a neighbour.

    ``fx_rates`` is never supplied. A rate row rewrites ``currency`` and EAD in
    the converter, which changes the record's fact pattern; a non-GBP record
    therefore runs in its own currency and the pipeline reports DQ020 for it.

    Returns the AGGREGATE over the legs the pipeline produced for the record's
    exposure, keyed on ``source_exposure_reference`` (the guarantee substitution
    and the RE splitter both turn one exposure into several legs): total
    ``ead_final``, the total pre-floor RWEA as ``rwa_pre_floor`` (see
    ``_PRE_FLOOR_RWA_CARRIERS``), and ``risk_weight`` -- the leg's own column for
    a single leg, ``total RWEA / total EAD`` otherwise. ``leg_values`` carries
    the class, approach, ``PIPELINE_ECHOES`` and branch-reason
    (``BRANCH_REASON_VOCABULARIES``) columns of every leg, and ``errors`` the
    run's ``(code, severity)`` pairs, for the adequacy test.
    """
    approach = record["approach"]
    if approach not in PIPELINE_APPROACHES:
        raise ValueError(
            f"{record['exposure_id']}: no pipeline translation for approach {approach!r}. "
            f"Add one to drivers._translate_record, with a curated record that exercises it."
        )
    framework = record["framework"]
    reporting_date = REPORTING_DATE_CRR if framework == "CRR" else REPORTING_DATE_B31
    translation = _translate_record(record, reporting_date)
    config = _crm_config(framework, translation.crm_method, translation.permission)
    bundle = make_raw_bundle(**translation.tables)
    result = PipelineOrchestrator().run_with_data(bundle, config)
    return _total_pipeline_legs(result.results.collect(), result.errors)


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


def _crm_config(
    framework: str,
    crm_method: str,
    permission: PermissionMode = PermissionMode.STANDARDISED,
) -> CalculationConfig:
    """The run config for a CRM or pipeline oracle, with the Art. 191A method election."""
    method = (
        CRMCollateralMethod.SIMPLE if crm_method == "simple" else CRMCollateralMethod.COMPREHENSIVE
    )
    if framework == "CRR":
        return CalculationConfig.crr(
            reporting_date=REPORTING_DATE_CRR,
            permission_mode=permission,
            crm_collateral_method=method,
        )
    if framework == "BASEL_3_1":
        return CalculationConfig.basel_3_1(
            reporting_date=REPORTING_DATE_B31,
            permission_mode=permission,
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
    guarantor risk-weight lookup both key on), its ``cqs``, and optionally its
    ``country_code`` and ``is_equivalent_jurisdiction`` — the jurisdiction the
    CRR Art. 116(5) gate tests for a PSE guarantor. Both default to null, which
    that gate reads as a third-country PSE with no equivalence determination
    (100%), so a PSE oracle that means a UK guarantor must say ``"GB"``.
    """
    refs = ["CP001"]
    types = ["corporate"]
    cqs: list[int | None] = [None]
    countries: list[str | None] = [None]
    equivalent: list[bool | None] = [None]
    for guarantor in guarantors or []:
        refs.append(guarantor["ref"])
        types.append(guarantor["entity_type"])
        cqs.append(guarantor.get("cqs"))
        countries.append(guarantor.get("country_code"))
        equivalent.append(guarantor.get("is_equivalent_jurisdiction"))
    return make_counterparty_lookup(
        counterparties=pl.LazyFrame(
            {
                "counterparty_reference": refs,
                "entity_type": types,
                "country_code": countries,
                "is_equivalent_jurisdiction": equivalent,
            },
            schema={
                "counterparty_reference": pl.String(),
                "entity_type": pl.String(),
                "country_code": pl.String(),
                "is_equivalent_jurisdiction": pl.Boolean(),
            },
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


# -----------------------------------------------------------------------------
# run_pipeline: one record -> the raw tables a firm would load
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class _PipelineTranslation:
    """One record as raw input tables, plus the run elections it implies."""

    tables: dict[str, Any]
    permission: PermissionMode
    crm_method: str


def _translate_record(record: dict[str, Any], reporting_date: date) -> _PipelineTranslation:
    """Map a record's calculator-vocabulary inputs onto raw input tables.

    Every input is consumed by exactly one rule here, and whatever is left over
    has no translation and raises (``_reject_untranslated``). The vocabulary is
    deliberately only as wide as the curated records need: a rule no curated
    record exercises is a translation nobody has seen work.

    The obligor defaults to a GB corporate (a ``specialised_lending`` entity for
    a slotting record, which is what routes it to the specialised-lending class),
    loaded with its jurisdiction's ``local_currency``
    (``_JURISDICTION_LOCAL_CURRENCY``); the exposure to a drawn GBP term loan,
    ``_PIPELINE_DEFAULT_MATURITY_YEARS`` long. Protection defaults are the CRM
    driver's own (``_COLLATERAL_DEFAULTS``, ``_GUARANTEE_DEFAULTS``), so the two
    O3 drivers cannot disagree about them.
    """
    inputs = dict(record["inputs"])
    approach = record["approach"]
    ead = float(inputs.pop("ead"))
    for key in _PIPELINE_DERIVED_INPUTS:
        inputs.pop(key, None)
    crm_method = inputs.pop("crm_method", "comprehensive")

    counterparties = [_pipeline_obligor(inputs, approach)]
    ratings = _pipeline_obligor_ratings(inputs, approach)
    guarantors = inputs.pop("guarantors", None) or []
    for guarantor in guarantors:
        counterparties.append(_pipeline_guarantor(guarantor))
        if guarantor.get("cqs") is not None:
            ratings.append(_pipeline_rating(guarantor["ref"], cqs=guarantor["cqs"]))
    collateral = [
        _pipeline_collateral(index, item)
        for index, item in enumerate(inputs.pop("collateral", None) or [])
    ]
    guarantees = [
        _pipeline_guarantee(index, item)
        for index, item in enumerate(inputs.pop("guarantees", None) or [])
    ]

    tables: dict[str, Any] = {
        "counterparties": _raw_frame(counterparties, COUNTERPARTY_SCHEMA),
        "ratings": _raw_frame(ratings, RATINGS_SCHEMA),
        "collateral": _raw_frame(collateral, COLLATERAL_SCHEMA),
        "guarantees": _raw_frame(guarantees, GUARANTEE_SCHEMA),
    }
    if approach == "EQUITY":
        tables["equity_exposures"] = _raw_frame(
            [_pipeline_equity(inputs, ead)], EQUITY_EXPOSURE_SCHEMA
        )
    else:
        tables["loans"] = _raw_frame([_pipeline_loan(inputs, ead, reporting_date)], LOAN_SCHEMA)
    if approach == "SLOTTING":
        tables["specialised_lending"] = _raw_frame(
            [_pipeline_specialised_lending(inputs)], SPECIALISED_LENDING_SCHEMA
        )

    permission = PermissionMode.STANDARDISED
    if approach in ("FIRB", "SLOTTING"):
        permission = PermissionMode.IRB
        tables["model_permissions"] = create_full_irb_model_permissions()

    _reject_untranslated(record["exposure_id"], inputs)
    return _PipelineTranslation(tables=tables, permission=permission, crm_method=crm_method)


def _pipeline_obligor(inputs: dict[str, Any], approach: str) -> dict[str, Any]:
    """The obligor's counterparty row. Consumes its inputs from ``inputs``.

    ``local_currency`` is not a record input: it is the stated jurisdiction's
    currency (``_JURISDICTION_LOCAL_CURRENCY``), loaded for every obligor.
    """
    default_type = "specialised_lending" if approach == "SLOTTING" else "corporate"
    country = inputs.pop("country_code", "GB")
    if country not in _JURISDICTION_LOCAL_CURRENCY:
        raise ValueError(
            f"no local currency known for jurisdiction {country!r}: add it to "
            f"drivers._JURISDICTION_LOCAL_CURRENCY rather than loading none"
        )
    row: dict[str, Any] = {
        "counterparty_reference": _PIPELINE_OBLIGOR,
        "counterparty_name": _PIPELINE_OBLIGOR,
        "entity_type": inputs.pop("entity_type", default_type),
        "country_code": country,
        "local_currency": _JURISDICTION_LOCAL_CURRENCY[country],
    }
    # Raw counterparty columns of the same name. ``sovereign_cqs`` is the input
    # whose loss P1.316 demonstrated: the classifier is its only route to
    # ``cp_sovereign_cqs`` (classify/attributes.py).
    for key in ("sovereign_cqs", "scra_grade"):
        if key in inputs:
            row[key] = inputs.pop(key)
    return row


def _pipeline_obligor_ratings(inputs: dict[str, Any], approach: str) -> list[dict[str, Any]]:
    """The obligor's rating rows: an external CQS, or the internal-model pair.

    An internal rating carrying ``model_id`` is what lets the model permission
    attach. A slotting record gets ``model_id`` with NO PD, which is what leaves
    the specialised-lending F-IRB / A-IRB branches unavailable and the exposure
    to the slotting table.
    """
    rows: list[dict[str, Any]] = []
    cqs = inputs.pop("cqs", None)
    if cqs is not None:
        rows.append(_pipeline_rating(_PIPELINE_OBLIGOR, cqs=cqs))
    pd_value = inputs.pop("pd_value", None)
    if pd_value is not None or approach == "SLOTTING":
        rows.append(
            {
                "rating_reference": f"RT_INT_{_PIPELINE_OBLIGOR}",
                "counterparty_reference": _PIPELINE_OBLIGOR,
                "rating_type": "internal",
                "pd": pd_value,
                "model_id": _PIPELINE_MODEL_ID,
                "rating_date": _PIPELINE_RATING_DATE,
            }
        )
    return rows


def _pipeline_rating(counterparty_reference: str, *, cqs: int) -> dict[str, Any]:
    """One external ECAI rating row."""
    return {
        "rating_reference": f"RT_EXT_{counterparty_reference}",
        "counterparty_reference": counterparty_reference,
        "rating_type": "external",
        "rating_agency": "ORACLE_ECAI",
        "cqs": cqs,
        "rating_date": _PIPELINE_RATING_DATE,
    }


def _pipeline_loan(inputs: dict[str, Any], ead: float, reporting_date: date) -> dict[str, Any]:
    """The exposure as one drawn term loan. Consumes its inputs from ``inputs``.

    ``lgd`` is consumed only when it is null -- "no own estimate", which is a raw
    loan's default and what routes an IRB record to F-IRB. An own LGD estimate
    has no translation yet and is left to raise. ``maturity`` (the IRB ``M`` the
    record fixes) becomes ``effective_maturity``, the firm-supplied override
    that the IRB maturity chain ranks first; deriving ``M`` from the dates
    instead would put day-count arithmetic between the record and the engine.
    """
    residual = _pipeline_maturity_years(inputs)
    original = float(inputs.pop("original_maturity_years", residual))
    maturity_date = reporting_date + timedelta(days=round(residual * 365))
    row: dict[str, Any] = {
        "loan_reference": _PIPELINE_EXPOSURE,
        "counterparty_reference": _PIPELINE_OBLIGOR,
        "product_type": "term_loan",
        "drawn_amount": ead,
        "currency": inputs.pop("currency", "GBP"),
        "value_date": maturity_date - timedelta(days=round(original * 365)),
        "maturity_date": maturity_date,
        "seniority": "senior",
    }
    if "maturity" in inputs:
        row["effective_maturity"] = float(inputs.pop("maturity"))
    if "lgd" in inputs and inputs["lgd"] is None:
        del inputs["lgd"]
    return row


def _pipeline_maturity_years(inputs: dict[str, Any]) -> float:
    """The exposure's residual maturity, from whichever input states it.

    Three record inputs state a maturity -- the O1 ``residual_maturity_years``,
    the O3 ``exposure_maturity_years`` and the slotting ``is_short_maturity``
    flag. A record stating two would be ambiguous, so that raises.
    """
    stated = sorted(
        key
        for key in ("residual_maturity_years", "exposure_maturity_years", "is_short_maturity")
        if key in inputs
    )
    if len(stated) > 1:
        raise ValueError(f"oracle inputs {stated} each state the exposure's maturity")
    if "is_short_maturity" in inputs:
        is_short = inputs.pop("is_short_maturity")
        return _SLOTTING_SHORT_MATURITY_YEARS if is_short else _PIPELINE_DEFAULT_MATURITY_YEARS
    years = inputs.pop("residual_maturity_years", None)
    if years is None:
        years = inputs.pop("exposure_maturity_years", None)
    return _PIPELINE_DEFAULT_MATURITY_YEARS if years is None else float(years)


def _pipeline_specialised_lending(inputs: dict[str, Any]) -> dict[str, Any]:
    """The specialised-lending row that moves the obligor to the SL class.

    ``project_phase="operational"`` mirrors ``_SLOTTING_DEFAULTS``'
    ``is_pre_operational=False``, so the two slotting drivers state one fact.
    """
    return {
        "counterparty_reference": _PIPELINE_OBLIGOR,
        "sl_type": inputs.pop("sl_type"),
        "slotting_category": inputs.pop("slotting_category"),
        "is_hvcre": inputs.pop("is_hvcre", False),
        "project_phase": "operational",
    }


def _pipeline_equity(inputs: dict[str, Any], ead: float) -> dict[str, Any]:
    """The equity holding, valued at the record's EAD."""
    return {
        "exposure_reference": _PIPELINE_EXPOSURE,
        "counterparty_reference": _PIPELINE_OBLIGOR,
        "equity_type": inputs.pop("equity_type"),
        "is_exchange_traded": inputs.pop("is_exchange_traded", False),
        "carrying_value": ead,
        "fair_value": ead,
        "currency": "GBP",
    }


def _pipeline_guarantor(guarantor: dict[str, Any]) -> dict[str, Any]:
    """A protection provider's counterparty row (``ref``, ``entity_type``, ``cqs``)."""
    _reject_unknown_frame_columns(guarantor, {"ref", "entity_type", "cqs"}, "guarantor")
    return {
        "counterparty_reference": guarantor["ref"],
        "counterparty_name": guarantor["ref"],
        "entity_type": guarantor["entity_type"],
        "country_code": "GB",
    }


def _pipeline_collateral(index: int, item: dict[str, Any]) -> dict[str, Any]:
    """One pledge against the record's loan, on the CRM driver's defaults."""
    _reject_unknown_frame_columns(item, set(COLLATERAL_SCHEMA), "collateral")
    return {
        **_COLLATERAL_DEFAULTS,
        "beneficiary_reference": _PIPELINE_EXPOSURE,
        "beneficiary_type": "loan",
        **item,
        "collateral_reference": f"COLL{index:03d}",
    }


def _pipeline_guarantee(index: int, item: dict[str, Any]) -> dict[str, Any]:
    """One guarantee over the record's loan, on the CRM driver's defaults."""
    _reject_unknown_frame_columns(item, set(GUARANTEE_SCHEMA), "guarantee")
    return {
        **_GUARANTEE_DEFAULTS,
        "beneficiary_reference": _PIPELINE_EXPOSURE,
        "beneficiary_type": "loan",
        **item,
        "guarantee_reference": f"GUAR{index:03d}",
    }


def _raw_frame(rows: list[dict[str, Any]], schema: dict[str, Any]) -> pl.DataFrame | None:
    """A raw table at its loader dtypes, or None when empty (the loader's own idiom)."""
    if not rows:
        return None
    return pl.DataFrame(rows, schema_overrides=dtypes_of(schema))


def _reject_untranslated(exposure_id: str, leftover: dict[str, Any]) -> None:
    """Fail loudly on a record input no translation rule consumed.

    The pipeline form of ``reject_unknown_columns``: an input that translates to
    nothing leaves the pipeline reading its default, the case silently tests a
    different fact pattern, and a disagreement would look like an engine defect.
    """
    if leftover:
        raise ValueError(
            f"{exposure_id}: oracle input(s) {sorted(leftover)} have no pipeline "
            f"translation. Add a rule to drivers._translate_record -- and a curated "
            f"record that exercises it -- rather than dropping the input."
        )


def _total_pipeline_legs(results: pl.DataFrame, errors: list[CalculationError]) -> dict[str, Any]:
    """Total the pipeline's legs for the record's exposure into one comparable row."""
    legs = results.filter(pl.col("source_exposure_reference") == _PIPELINE_EXPOSURE)
    carrier = next((name for name in _PRE_FLOOR_RWA_CARRIERS if name in legs.columns), None)
    if carrier is None:
        raise ValueError(f"pipeline results carry none of {_PRE_FLOOR_RWA_CARRIERS}")
    total_ead = float(legs["ead_final"].sum())
    total_rwa = float(legs[carrier].sum())
    risk_weight = legs["risk_weight"][0] if legs.height == 1 else None
    if legs.height > 1 and total_ead:
        risk_weight = total_rwa / total_ead
    row: dict[str, Any] = {
        "legs": legs.height,
        "stray_rows": results.height - legs.height,
        "ead_final": total_ead,
        "rwa_pre_floor": total_rwa,
        "rwa_carrier": carrier,
        "risk_weight": risk_weight,
        "leg_values": {
            name: legs[name].to_list()
            for name in (
                "exposure_class",
                "approach_applied",
                *PIPELINE_ECHOES.values(),
                *PIPELINE_YEAR_ECHOES.values(),
                *BRANCH_REASON_VOCABULARIES,
                "cp_local_currency",
            )
            if name in legs.columns
        },
        "errors": [(error.code, str(error.severity)) for error in errors],
    }
    if legs.height == 1:
        row.update(
            {name: legs[name][0] for name in _PIPELINE_SINGLE_LEG_COLUMNS if name in legs.columns}
        )
    return row
