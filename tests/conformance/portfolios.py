"""
Combinatorial classification input space and its classifier-only runner (C4a).

Pipeline position:
    Combination -> build_bundle -> resolve_scope .. classifier (stage prefix)
        -> ClassifiedExposuresBundle.all_exposures

Key responsibilities:
- Describe one point of the discriminating input space as a hashable value
  (``Combination``) and enumerate the whole space (``combinations``).
- Seal the space into a loader-shaped ``RawDataBundle`` — one obligor, one
  drawn leg (and, for the QRRE flavour, one revolving parent facility) per
  combination — using the same contract-sealing helper production uses.
- Run **only** the stage prefix up to and including ``classifier`` and return
  the classifier-exit frame, memoised per regime. The downstream stages
  (CRM, RE-split, calculators, aggregator) legitimately mutate the exposure
  class, so the conformance verdict is stated at the classifier's own exit.

Why the entity-type vocabulary is read from the engine's pack binding: the
space must cover every input the engine ACCEPTS. Reading the vocabulary from
``ENTITY_TYPE_TO_SA_CLASS`` means a newly-added entity type is generated
automatically and — having no verdict in the externally-authored table —
fails hard. The verdicts themselves never come from the engine; they come from
``classification_table.toml``.

References:
- CRR Art. 112: SA exposure classes; CRR Art. 147: IRB exposure classes
- CRR Art. 123 / PS1/26 Art. 147(5)(a)(ii): retail monetary limits
- CRR Art. 154(4) / PS1/26 Art. 147(5A): QRRE conditions
- docs/plans/independent-validation-system.md §C4a
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.context import PipelineContext
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
    SPECIALISED_LENDING_SCHEMA,
)
from rwa_calc.domain.enums import ApproachType, ExposureClass, PermissionMode
from rwa_calc.engine.entity_class_maps import ENTITY_TYPE_TO_SA_CLASS
from rwa_calc.engine.orchestrator import (
    CLASSIFIED,
    COMPONENTS,
    PIPELINE_ERRORS,
    RAW_DATA,
    SECURITISATION_RESOLVED,
    STAGE_ERRORS,
    build_components,
    run_stages,
)
from rwa_calc.engine.registry import PIPELINE_STAGES
from rwa_calc.rulebook import RulepackV0
from tests.fixtures.raw_bundle import make_raw_bundle

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import RawDataBundle

# ---------------------------------------------------------------------------
# Constants — the space definition
# ---------------------------------------------------------------------------

#: Regime name -> (framework, reporting date).
REGIMES: tuple[str, ...] = ("CRR", "B31")

_REPORTING_DATE: dict[str, date] = {
    "CRR": date(2025, 12, 31),
    "B31": date(2027, 6, 1),
}

#: Every entity type the engine accepts, read from the pack binding so the
#: space cannot silently stop covering an input the classifier still maps.
ENTITY_TYPES: tuple[str, ...] = tuple(sorted(ENTITY_TYPE_TO_SA_CLASS))

#: The entity types crossed with every modifier. Chosen because the
#: sub-classification waterfall (Art. 147(4B)-(5C), Art. 123/123A) and the
#: approach ladder (Art. 147A(1)) only discriminate on these obligor kinds;
#: ``company`` is carried alongside ``corporate`` deliberately — the two are
#: aliases in the class map and any divergence between them is a defect.
CORE_ENTITY_TYPES: tuple[str, ...] = (
    "corporate",
    "company",
    "individual",
    "institution",
    "sovereign",
    "specialised_lending",
)

#: Counterparty size, driving the SME (Art. 4(1)(128D)) and large-corporate
#: (PS1/26 Art. 147(4C)(b)(ii)) tests. ``none`` leaves both revenue and assets
#: null, which is itself a discriminating input.
SIZE_BANDS: tuple[str, ...] = ("none", "sme", "large")

#: IRB input availability. ``none`` = external rating only (no internal PD),
#: ``pd`` = internal PD, ``pd_lgd`` = internal PD plus a firm LGD estimate.
IRB_INPUTS: tuple[str, ...] = ("none", "pd", "pd_lgd")

#: Product/facility shape. The two revolving flavours differ only in headroom:
#: ``revolving_qrre`` is drawn to its parent facility's limit (one leg), while
#: ``revolving_qrre_headroom`` leaves the facility partly undrawn, so the
#: hierarchy emits a second ``_UNDRAWN`` leg for the SAME facility. Both must
#: satisfy the Art. 154(4)(c) / PS1/26 Art. 147(5A)(c) per-individual aggregate
#: on identical facts — one facility of GBP 70,000. Keeping only the fully-drawn
#: shape is exactly the ``.claude/LESSONS.md`` B5 trap.
FLAVOURS: tuple[str, ...] = (
    "plain",
    "mortgage",
    "revolving_qrre",
    "revolving_qrre_headroom",
    "defaulted",
    "slotting",
)

#: Entity types probed with an internal rating to reach the IRB-permission
#: lookup. Their derived IRB class is where CRR Art. 147(3)(b)/(c) and PS1/26
#: Art. 147(3)(f)/(g) speak most directly, and the approach they end up on is
#: the observable consequence of getting that class right.
IRB_PROBE_ENTITY_TYPES: tuple[str, ...] = ("mdb_named", "international_org", "covered_bond")

#: Origination date, comfortably before every reporting date used here.
VALUE_DATE = date(2015, 1, 1)

#: Drawn amount for the non-revolving flavours. Below the Art. 123 EUR 1m and
#: the PS1/26 Art. 147(5)(a)(ii) GBP 880,000 retail caps under both regimes, so
#: a retail obligor stays retail and the class test is about the class.
DRAWN = 500_000.0

#: The QRRE parent's limit — under the Art. 154(4)(c) EUR 100,000 and PS1/26
#: Art. 147(5A)(c) GBP 90,000 per-individual aggregate caps under both regimes.
QRRE_LIMIT = 70_000.0

#: Drawn amount of the QRRE child in the headroom flavour, leaving GBP 20,000
#: undrawn on the same facility.
QRRE_DRAWN_HEADROOM = 50_000.0

#: Annual revenue per size band. ``sme`` is inside both the EUR 50m (CRR
#: Art. 4(1)(128D)) and GBP 44m (PS1/26) turnover tests; ``large`` is above the
#: PS1/26 Art. 147(4C)(b)(ii) GBP 440m large-corporate threshold.
REVENUE: dict[str, float | None] = {"none": None, "sme": 10_000_000.0, "large": 600_000_000.0}

#: The single model id every internal rating carries.
MODEL_ID = "CONF_IRB"

#: Internal PD used wherever ``irb_inputs`` supplies one, and the firm LGD used
#: for ``pd_lgd``. Values are immaterial to classification; only presence is.
INTERNAL_PD = 0.02
FIRM_LGD = 0.35

#: External CQS used when no internal rating is supplied.
EXTERNAL_CQS = 3

_NATURAL_PERSON_TYPES: frozenset[str] = frozenset({"individual", "retail", "natural_person"})

#: The stage prefix the conformance verdict is stated over — every stage up to
#: and including the classifier. Resolved by NAME so a registry re-order cannot
#: silently change what is being asserted.
_CLASSIFY_STAGE = "classifier"


# ---------------------------------------------------------------------------
# The combination value
# ---------------------------------------------------------------------------


@dataclass(frozen=True, order=True)
class Combination:
    """One point of the discriminating input space.

    Frozen and ordered so the space is a deterministic, hashable sequence and a
    failing point prints as a literal that can be pasted into a reproducer.
    """

    regime: str
    entity_type: str
    size_band: str
    irb_inputs: str
    flavour: str

    @property
    def key(self) -> str:
        """A stable, human-readable identity for reports and error messages."""
        return "|".join(
            (self.regime, self.entity_type, self.size_band, self.irb_inputs, self.flavour)
        )

    def as_dict(self) -> dict[str, str]:
        """The dimension map a decision-table rule is matched against."""
        return {
            "regime": self.regime,
            "entity_type": self.entity_type,
            "size_band": self.size_band,
            "irb_inputs": self.irb_inputs,
            "flavour": self.flavour,
        }


# ---------------------------------------------------------------------------
# Main public entry points
# ---------------------------------------------------------------------------


def combinations(regime: str) -> tuple[Combination, ...]:
    """Every generated point of the space for one regime, deterministically ordered.

    The union of two sub-spaces:

    - the **entity-type axis** — every accepted ``entity_type`` at a fixed
      baseline (no size signal, no internal rating, plain term loan), which is
      the direct Art. 112 / Art. 147 mapping assertion;
    - the **modifier cross-product** — :data:`CORE_ENTITY_TYPES` crossed with
      every size band, IRB-input availability and flavour, which is the
      sub-classification waterfall and approach ladder.

    Exclusions are NOT applied here; the caller applies the table's declared
    exclusions so the excluded count can be reported.
    """
    axis = {Combination(regime, et, "none", "none", "plain") for et in ENTITY_TYPES}
    cross = {
        Combination(regime, et, size, irb, flavour)
        for et in CORE_ENTITY_TYPES
        for size in SIZE_BANDS
        for irb in IRB_INPUTS
        for flavour in FLAVOURS
    }
    probe = {
        Combination(regime, et, "none", irb, "plain")
        for et in IRB_PROBE_ENTITY_TYPES
        for irb in ("pd", "pd_lgd")
    }
    return tuple(sorted(axis | cross | probe))


@lru_cache(maxsize=4)
def classified(regime: str, combos: tuple[Combination, ...]) -> pl.DataFrame:
    """The classifier-exit frame for ``combos`` under ``regime``, memoised.

    Runs the registry stage prefix ending at the classifier — not the whole
    pipeline. Downstream stages (CRM substitution, the RE splitter, the
    aggregator's ``exposure_class_applied``) legitimately re-key the class, so
    stating the verdict here keeps the table about classification.
    """
    config = config_for(regime)
    ctx = (
        PipelineContext.empty()
        .put(RAW_DATA, build_bundle(combos))
        .put(COMPONENTS, build_components(config))
        .put(SECURITISATION_RESOLVED, None)
        .put(PIPELINE_ERRORS, ())
        .put(STAGE_ERRORS, ())
    )
    ctx = run_stages(ctx, RulepackV0.from_config(config), config, _stage_prefix())
    return ctx.get(CLASSIFIED).all_exposures.collect()


def verdicts(regime: str, combos: tuple[Combination, ...]) -> dict[str, dict[str, str]]:
    """Map ``Combination.key`` -> the four observed classification outputs.

    One row per combination: every combination owns its counterparty, and the
    drawn loan is selected by its own reference, so a parent facility's own
    undrawn leg never contaminates the verdict.
    """
    frame = classified(regime, combos)
    wanted = ["exposure_class_sa", "exposure_class_irb", "exposure_class", "approach"]
    selected = frame.select(["exposure_reference", *wanted])
    by_reference = {
        row["exposure_reference"]: {col: row[col] for col in wanted}
        for row in selected.iter_rows(named=True)
    }
    return {
        combo.key: by_reference[_loan_reference(index)]
        for index, combo in enumerate(combos)
        if _loan_reference(index) in by_reference
    }


def config_for(regime: str) -> CalculationConfig:
    """The ``CalculationConfig`` for a named regime.

    ``enforce_retail_granularity=False`` under Basel 3.1 for the reason the
    reporting goldens already record: the Art. 123A(1)(b)(ii) 0.2%-of-portfolio
    granularity limb is a PORTFOLIO property, and in a compact one-obligor-per-
    combination portfolio it fails for every obligor, which would make every
    retail verdict a statement about portfolio size rather than about
    classification. CRE20.66 leaves the limb to national discretion.
    """
    reporting_date = _REPORTING_DATE[regime]
    if regime == "CRR":
        return CalculationConfig.crr(
            reporting_date=reporting_date, permission_mode=PermissionMode.IRB
        )
    return CalculationConfig.basel_3_1(
        reporting_date=reporting_date,
        permission_mode=PermissionMode.IRB,
        enforce_retail_granularity=False,
    )


def build_bundle(combos: tuple[Combination, ...]) -> RawDataBundle:
    """Seal ``combos`` into a loader-shaped ``RawDataBundle``."""
    counterparties: list[dict] = []
    loans: list[dict] = []
    ratings: list[dict] = []
    facilities: list[dict] = []
    facility_mappings: list[dict] = []
    collateral: list[dict] = []
    specialised_lending: list[dict] = []

    for index, combo in enumerate(combos):
        counterparties.append(_counterparty(index, combo))
        loans.append(_loan(index, combo))
        ratings.append(_rating(index, combo))
        if combo.flavour.startswith("revolving_qrre"):
            facilities.append(_facility(index, combo))
            facility_mappings.append(_facility_mapping(index))
        if combo.flavour == "mortgage":
            collateral.append(_collateral(index))
        if combo.flavour == "slotting":
            specialised_lending.append(_specialised_lending(index))

    return make_raw_bundle(
        counterparties=pl.DataFrame(
            counterparties, schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA)
        ),
        loans=pl.DataFrame(loans, schema_overrides=dtypes_of(LOAN_SCHEMA)),
        ratings=pl.DataFrame(ratings, schema_overrides=dtypes_of(RATINGS_SCHEMA)),
        facilities=_frame_or_none(facilities, FACILITY_SCHEMA),
        facility_mappings=_frame_or_none(facility_mappings, FACILITY_MAPPING_SCHEMA),
        collateral=_frame_or_none(collateral, COLLATERAL_SCHEMA),
        specialised_lending=_frame_or_none(specialised_lending, SPECIALISED_LENDING_SCHEMA),
        model_permissions=model_permissions(),
    )


def model_permissions() -> pl.LazyFrame:
    """IRB permissions granted exactly where PS1/26 Art. 147A(1) admits them.

    Not the shared ``create_full_irb_model_permissions`` fixture: the grant is
    itself part of the regulatory premise under test, so it is derived here from
    the article rather than inherited from another suite's convenience helper.

      - (b) institutions, (e) financial/large corporates, (f) other general
        corporates: F-IRB and A-IRB both admissible (the choice is then a
        function of the exposure's own inputs and of Art. 147A(1)(e)).
      - (d) object/project/commodities-finance specialised lending: F-IRB,
        A-IRB and Slotting all admissible.
      - (g) retail: A-IRB only — Art. 147A(1)(g)(ii) offers no F-IRB limb, and
        CRR Art. 151(4) likewise requires own LGD estimates for retail.
      - (a) central governments / quasi-sovereigns: granted under CRR (where
        Art. 150(1) permanent partial use is an election, not a mandate) so the
        CRR routing is genuinely exercised; PS1/26 Art. 147A(1)(a) then blocks
        it data-side under Basel 3.1, which is the behaviour being tested.
      - (h) equity: no grant — SA under PS1/26 Art. 147A(1)(h).
    """
    both = (ApproachType.FIRB, ApproachType.AIRB)
    grants: dict[ExposureClass, tuple[ApproachType, ...]] = {
        ExposureClass.CENTRAL_GOVT_CENTRAL_BANK: both,
        ExposureClass.INSTITUTION: both,
        ExposureClass.CORPORATE: both,
        ExposureClass.CORPORATE_SME: both,
        ExposureClass.SPECIALISED_LENDING: (*both, ApproachType.SLOTTING),
        ExposureClass.RETAIL_MORTGAGE: (ApproachType.AIRB,),
        ExposureClass.RETAIL_QRRE: (ApproachType.AIRB,),
        ExposureClass.RETAIL_OTHER: (ApproachType.AIRB,),
    }
    rows = [
        {"model_id": MODEL_ID, "exposure_class": ec.value, "approach": approach.value}
        for ec, approaches in grants.items()
        for approach in approaches
    ]
    return pl.LazyFrame(rows).cast(
        {"model_id": pl.String, "exposure_class": pl.String, "approach": pl.String}
    )


# ---------------------------------------------------------------------------
# Row builders (private)
# ---------------------------------------------------------------------------


def _stage_prefix() -> tuple:
    """The registry prefix ending at the classifier, resolved by stage name."""
    names = [spec.name for spec in PIPELINE_STAGES]
    return tuple(PIPELINE_STAGES[: names.index(_CLASSIFY_STAGE) + 1])


def _frame_or_none(rows: list[dict], schema: dict) -> pl.DataFrame | None:
    """A typed frame, or None when the table is empty (the loader's own idiom)."""
    if not rows:
        return None
    return pl.DataFrame(rows, schema_overrides=dtypes_of(schema))


def _counterparty_reference(index: int) -> str:
    return f"CP{index:04d}"


def _loan_reference(index: int) -> str:
    return f"LN{index:04d}"


def _counterparty(index: int, combo: Combination) -> dict:
    """One obligor.

    ``is_managed_as_retail`` is attested explicitly for natural persons rather
    than left null: the loader edge contract gives the Boolean column a default
    of ``False``, so an unset field reads as a positive "not managed as retail"
    and PS1/26 Art. 123A(1)(b)(iii) would then expel every generated natural
    person to corporate.
    """
    is_person = combo.entity_type in _NATURAL_PERSON_TYPES
    return {
        "counterparty_reference": _counterparty_reference(index),
        "counterparty_name": _counterparty_reference(index),
        "entity_type": combo.entity_type,
        "country_code": "GB",
        "annual_revenue": REVENUE[combo.size_band],
        "is_natural_person": is_person,
        "is_managed_as_retail": is_person,
        "default_status": combo.flavour == "defaulted",
    }


def _loan(index: int, combo: Combination) -> dict:
    """The single drawn leg.

    ``product_type`` carries the mortgage signal (``is_mortgage`` reads it
    directly), and the ``mortgage`` flavour additionally pledges residential
    property so the hierarchy's property aggregates are populated too — the
    classifier's mortgage predicate is an OR over both, and testing only the
    product-name limb would leave the collateral limb dark.
    """
    row: dict = {
        "loan_reference": _loan_reference(index),
        "counterparty_reference": _counterparty_reference(index),
        "product_type": "mortgage" if combo.flavour == "mortgage" else "term_loan",
        "drawn_amount": _drawn_amount(combo),
        "currency": "GBP",
        "value_date": VALUE_DATE,
        "maturity_date": _maturity_date(),
        "seniority": "senior",
        "is_defaulted": combo.flavour == "defaulted",
    }
    if combo.flavour == "mortgage":
        row["property_type"] = "residential"
    if combo.irb_inputs == "pd_lgd":
        row["lgd"] = FIRM_LGD
        row["has_sufficient_collateral_data"] = True
    return row


def _drawn_amount(combo: Combination) -> float:
    """The drawn leg's size.

    ``revolving_qrre`` is drawn to the facility limit so the facility has one
    leg; ``revolving_qrre_headroom`` leaves headroom so it has two. The
    per-individual aggregate the Art. 154(4)(c) test measures is the same
    GBP 70,000 facility in both cases.
    """
    if combo.flavour == "revolving_qrre":
        return QRRE_LIMIT
    if combo.flavour == "revolving_qrre_headroom":
        return QRRE_DRAWN_HEADROOM
    return DRAWN


def _rating(index: int, combo: Combination) -> dict:
    """An internal PD (with a model id) routes IRB; an external CQS routes SA."""
    base = {
        "rating_reference": f"RT{index:04d}",
        "counterparty_reference": _counterparty_reference(index),
        "rating_date": VALUE_DATE,
    }
    if combo.irb_inputs == "none":
        return {
            **base,
            "rating_type": "external",
            "rating_agency": "CONF_AGENCY",
            "cqs": EXTERNAL_CQS,
        }
    return {**base, "rating_type": "internal", "pd": INTERNAL_PD, "model_id": MODEL_ID}


def _facility(index: int, combo: Combination) -> dict:
    """The revolving parent carrying the Art. 147(5A)(b) QRRE attributes.

    ``is_revolving`` / ``is_secured`` / ``risk_type`` / ``limit`` live on the
    facility; the hierarchy stage coalesces them onto the drawn child, which is
    where the classifier reads them. ``risk_type="LR"`` is the unconditional-
    cancellability signal the CCF machinery already owns.
    """
    return {
        "facility_reference": f"FC{index:04d}",
        "counterparty_reference": _counterparty_reference(index),
        "product_type": "revolving_credit_facility",
        "limit": QRRE_LIMIT,
        "risk_type": "LR",
        "currency": "GBP",
        "value_date": VALUE_DATE,
        "maturity_date": _maturity_date(),
        "committed": True,
        "is_revolving": True,
        "is_secured": False,
        "is_qrre_transactor": False,
        "is_defaulted": combo.flavour == "defaulted",
        "seniority": "senior",
    }


def _facility_mapping(index: int) -> dict:
    return {
        "parent_facility_reference": f"FC{index:04d}",
        "child_reference": _loan_reference(index),
        "child_type": "loan",
    }


def _collateral(index: int) -> dict:
    """Residential property pledged to the drawn leg (the mortgage flavour)."""
    return {
        "collateral_reference": f"CL{index:04d}",
        "collateral_type": "residential",
        "currency": "GBP",
        "market_value": DRAWN * 2.0,
        "nominal_value": DRAWN * 2.0,
        "beneficiary_type": "loan",
        "beneficiary_reference": _loan_reference(index),
        "is_eligible_financial_collateral": False,
        "is_eligible_irb_collateral": True,
        "valuation_date": VALUE_DATE,
        "valuation_type": "market",
    }


def _specialised_lending(index: int) -> dict:
    """Project-finance metadata — an Art. 147(4B)(d) non-IPRE, non-HVCRE category.

    Deliberately NOT IPRE/HVCRE: PS1/26 Art. 147A(1)(c) forces those two to
    Slotting, while (d) leaves object / project / commodities finance open to
    F-IRB and A-IRB. Testing the (d) branch is what distinguishes a correct
    slotting-only restriction from a blanket one.
    """
    return {
        "counterparty_reference": _counterparty_reference(index),
        "sl_type": "project_finance",
        "project_phase": "operational",
        "slotting_category": "strong",
        "is_hvcre": False,
    }


def _maturity_date() -> date:
    """Maturity measured from the latest reporting date, so residual maturity is
    the same under every regime and a cross-regime comparison is like-for-like."""
    return max(_REPORTING_DATE.values()) + timedelta(days=5 * 365)
