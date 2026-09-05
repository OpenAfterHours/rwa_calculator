"""
Facility-share candidate fan-out portfolio — scenario **FS-1**.

Pipeline position:
    build_facility_share_bundle(variant) -> RawDataBundle -> PipelineOrchestrator
        -> AggregatedResultBundle -> COREPGenerator / Pillar3Generator

What this portfolio is for
--------------------------
One facility (``FS-FAC-SHARE``) whose undrawn headroom is shared by obligors that
route to DIFFERENT approaches, so the firm-policy "riskiest member" allocation has
to choose between them. The choice is only interesting when the two available
metrics disagree, which is what every amount below is sized to produce:

    member          role                       approach       SA-equivalent RW
    --------------- -------------------------- -------------- -----------------
    FS-CP-SA        facility OWNER, CQS 2      standardised   50%
    FS-CP-LOW       descendant, CQS 1          standardised   20%
    FS-CP-IRB       descendant, internal PD    foundation_irb 100% (unrated)
    FS-CP-ANCHOR    NOT a member — the anchor  foundation_irb 100% (unrated)

``FS-CP-ANCHOR`` holds no share of the facility. It exists to set the Basel 3.1
output-floor state for the whole book, which is what makes the two metrics
diverge or agree. ``FS-FAC-SOLO`` is a second facility whose only descendant
belongs to the owner, so its member set is a singleton: it is the control leg
that must keep its undrawn row in every cell of the matrix.

The single free input
---------------------
Exactly ONE input differs between the two variants — ``FS-CP-ANCHOR``'s internal
PD (see :data:`ANCHOR_PD`). ``binding`` puts the Basel 3.1 output floor in a
binding state, ``nonbinding`` does not. The anchor loan's Pool B amount is
DERIVED from that PD by :func:`_b31_expected_loss`, so it is not a second free
input; it exists to neutralise the expected-loss channel of OF-ADJ.

Why ``risk_type = "MR"`` and not ``"OC"``
-----------------------------------------
Both facilities carry ``risk_type = "MR"`` (CRR Annex I para 2(b)(ii) medium
risk), which puts the conversion factor at 50% under BOTH regimes and keeps the
arithmetic legible. The honest counter-argument, recorded here so a later reader
finds the reasoning and not only the choice: PS1/26 Table A1 row (5) — "any other
commitment that is not subject to a conversion factor of 10%, 50% or 100%", 40% —
is arguably the Basel 3.1 home for an ordinary undrawn corporate commitment of
more than one year, and the pack's ``sa_ccf`` entry keyed ``OC`` carries that 40%.
Measured on these inputs, ``OC`` gives 0.50 under CRR and 0.40 under Basel 3.1.
``MR`` was chosen so the conversion factor is regime-invariant. The scenario's
divergence chain is homogeneous in exposure amount, so a later switch to ``OC``
rescales every Basel 3.1 amount by 0.8 and changes nothing structural.

Deliberately absent
-------------------
No collateral, guarantees, provisions or netting; no ``child_type="facility"``
mapping, so neither facility is a Multiple Option Facility; no retail obligor, no
equity, no slotting, no CCR/SFT. All four obligors sit in ``GB`` on purpose — the
C 09.01 / C 09.02 geographical basis is an open question in this estate and
entangling it here would make a failure ambiguous.

Note the structural limit that absence records: the divergence chain needs every
standardised member to sit BELOW the output-floor percentage, and regulatory
retail sits above it at 75%, so no fixture that proves the floor-aware metric can
also carry a retail obligor. The Art. 123A(1)(b)(ii) granularity denominator and
the QRRE demotion path therefore need their own, separate fixtures.

Regulatory values
-----------------
This module types NO regulatory value. The only one it needs — the Basel 3.1
F-IRB supervisory LGD for a senior unsecured non-FSE exposure — is read back from
the resolved rulepack by :func:`_b31_supervisory_lgd`.

References:
- CRR Art. 111(1) / Annex I para 2(b)(ii); PS1/26 Art. 111(1)(b) Table A1: the
  medium-risk 50% conversion factor both facilities select.
- CRR Art. 166(8)(d); PS1/26 Art. 166C(1): the F-IRB conversion factor, 75% under
  CRR and the SA factor under Basel 3.1.
- CRR Art. 122(1) Table 6; PS1/26 Art. 122(2) Table 6: the SA corporate weights.
- CRR Art. 161(1)(a); PS1/26 Art. 161(1)(aa): the F-IRB supervisory LGD.
- CRR Art. 158 / 159(1); PS1/26 Art. 92(2A): expected loss, Pool B and OF-ADJ.
- PS1/26 Art. 123A(1)(b)(ii): the retail granularity limb — inert here, and the
  config says so explicitly rather than by inheritance.
- docs/plans/facility-share-riskiest-member.md: the design of record.
"""

from __future__ import annotations

from dataclasses import fields, replace
from datetime import date
from typing import Literal

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)
from rwa_calc.domain.enums import PermissionMode, Seniority
from rwa_calc.rulebook.resolve import resolve
from tests.fixtures.irb_test_helpers import _TEST_MODEL_ID, create_firb_only_model_permissions
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants — the single source of truth for test assertions.
# ---------------------------------------------------------------------------

#: The two bundles this module builds. They differ in exactly one input value.
FacilityShareVariant = Literal["binding", "nonbinding"]

CP_SA: str = "FS-CP-SA"
CP_LOW: str = "FS-CP-LOW"
CP_IRB: str = "FS-CP-IRB"
CP_ANCHOR: str = "FS-CP-ANCHOR"

RTG_SA: str = "FS-RTG-SA"
RTG_LOW: str = "FS-RTG-LOW"
RTG_IRB: str = "FS-RTG-IRB"
RTG_ANCHOR: str = "FS-RTG-ANCHOR"

FAC_SHARE: str = "FS-FAC-SHARE"
FAC_SOLO: str = "FS-FAC-SOLO"

LN_IRB: str = "FS-LN-IRB"
LN_LOW: str = "FS-LN-LOW"
LN_SOLO: str = "FS-LN-SOLO"
LN_ANCHOR: str = "FS-LN-ANCHOR"

#: Facility limits. Different on purpose, so a row swapped between the two
#: facilities is identifiable from one cell.
LIMIT_SHARE: float = 1_000_000.0
LIMIT_SOLO: float = 300_000.0

#: Drawn balances. ``LN_IRB`` + ``LN_LOW`` are the two mapped descendants of
#: ``FS-FAC-SHARE``; ``LN_SOLO`` is the owner's own loan under ``FS-FAC-SOLO``;
#: ``LN_ANCHOR`` is unmapped and belongs to the anchor obligor.
DRAWN_IRB: float = 400_000.0
DRAWN_LOW: float = 200_000.0
DRAWN_SOLO: float = 100_000.0
DRAWN_ANCHOR: float = 2_000_000.0

#: Undrawn headroom, ``limit - sum(descendant drawn)``, clipped at zero. Stated
#: here because every expected exposure amount in the scenario is built from it.
#: 1,000,000 - (400,000 + 200,000) and 300,000 - 100,000.
HEADROOM_SHARE: float = LIMIT_SHARE - (DRAWN_IRB + DRAWN_LOW)
HEADROOM_SOLO: float = LIMIT_SOLO - DRAWN_SOLO

#: ``FS-CP-IRB``'s internal PD. Comfortably above both regimes' corporate PD input
#: floors, so ``pd_floored == pd`` and the floor is a non-binding pass-through.
PD_IRB: float = 0.0008

#: The ONE input that differs between the two bundles: the anchor's internal PD.
#: It sets the Basel 3.1 output-floor state for the whole book and reaches nothing
#: else — under CRR the floor Feature is off, so the two CRR runs differ only in
#: the anchor's own risk weight and its C 08.03 PD band.
ANCHOR_PD: dict[str, float] = {"binding": 0.0030, "nonbinding": 0.0500}

#: Turnover on all four obligors, identical so revenue cannot identify a
#: mis-attributed row. Above the CRR SME turnover threshold and the Basel 3.1
#: one, so neither the Art. 153(4) SME correlation adjustment nor the Art. 501
#: supporting factor engages; below the Basel 3.1 large-corporate revenue
#: threshold, so no large-corporate IRB restriction engages either.
ANNUAL_REVENUE: float = 200_000_000.0

#: Explicit Art. 162(3) maturity override on every exposure. It sits at the top
#: of the maturity priority chain and inside the [1/365, 5.0] clip, so M = 2.5 in
#: both regimes and the maturity adjustment collapses to 1 / (1 - 1.5b). It also
#: reaches the synthetic undrawn row.
EFFECTIVE_MATURITY: float = 2.5

_CURRENCY: str = "GBP"
_PRODUCT_TYPE: str = "term_loan"
#: CRR Annex I para 2(b)(ii) medium-risk bucket. The input vocabulary here is the
#: short code in ``data/schemas.py::VALID_RISK_TYPES_INPUT``, not the
#: ``RiskType`` enum's long-form value.
_RISK_TYPE: str = "MR"
_VALUE_DATE: date = date(2020, 1, 1)
_MATURITY_DATE: date = date(2031, 12, 31)  # after both reporting dates
_RATING_DATE: date = _VALUE_DATE

#: Reporting dates, matching the IRB runs already registered in the supervisory
#: validation gate. The Basel 3.1 date resolves the ``output_floor_pct`` Schedule
#: to its 2027 transitional step.
CRR_REPORTING_DATE: date = date(2025, 12, 31)
B31_REPORTING_DATE: date = date(2027, 6, 1)

#: Prior reporting dates for the C 08.04 opening balance, using the same offsets
#: the gate's own prior-config helper uses per regime.
CRR_PRIOR_DATE: date = date(2025, 6, 30)
B31_PRIOR_DATE: date = date(2027, 1, 1)

#: The default facility-share metric. ``"own_approach"`` is the firm election that
#: pins the allocation to the un-floored risk weight.
DEFAULT_FACILITY_SHARE_METRIC: str = "floor_aware"

#: Name of the ``CalculationConfig`` field the aggregator slice (S3) adds. Until
#: it exists, :func:`facility_share_config` ignores its ``facility_share_metric``
#: argument so this module imports and runs cleanly on current code.
_METRIC_FIELD: str = "facility_share_metric"


# ---------------------------------------------------------------------------
# Main public entry points
# ---------------------------------------------------------------------------


def build_facility_share_bundle(variant: FacilityShareVariant) -> RawDataBundle:
    """Assemble the FS-1 facility-share portfolio as a sealed bundle.

    Sealed against the loader edge contracts by ``make_raw_bundle``, so it is
    shape-identical to a parquet-loaded production bundle. Run it through
    ``PipelineOrchestrator().run_with_data`` under either regime with the
    matching :func:`facility_share_config`.

    ``model_permissions`` grants F-IRB only. That is deliberate: with A-IRB
    unavailable, a stray own-estimate LGD cannot silently re-route a candidate to
    the advanced branch and change its exposure value through a different floor.

    Args:
        variant: ``"binding"`` or ``"nonbinding"`` — the Basel 3.1 output-floor
            state the anchor obligor's PD produces. See :data:`ANCHOR_PD`.
    """
    return make_raw_bundle(
        counterparties=_counterparties(),
        loans=_loans(variant),
        facilities=_facilities(),
        facility_mappings=_facility_mappings(),
        ratings=_ratings(variant),
        model_permissions=create_firb_only_model_permissions(),
    )


def facility_share_config(
    framework: str,
    *,
    facility_share_metric: str = DEFAULT_FACILITY_SHARE_METRIC,
) -> CalculationConfig:
    """The FS-1 run config for one framework.

    Written out rather than cloned from the gate's shared IRB helper, and the
    difference is load-bearing: that helper passes
    ``enforce_retail_granularity=False`` on its Basel 3.1 arm so a compact oracle
    portfolio's natural-person rows stay retail. THIS portfolio has no retail
    obligor at all, so the Art. 123A(1)(b)(ii) 0.2% limb decides nothing here and
    the production default must stand. Registering this portfolio inside the
    supervisory gate against a config that softens a feature its own assertions
    describe is the third form of the LESSONS B5 trap — registered, wrong config,
    dead cell. No number moves either way on this portfolio, which is exactly what
    makes the conflict worth closing now rather than after it starts mattering.

    ``use_investment_grade_assessment`` is False in both regimes, which selects the
    Art. 122(2) flat 100% for an unrated corporate rather than the Art. 122(6)
    65% / 135% split. Under Basel 3.1 that is passed explicitly. Under CRR the
    ``crr`` factory takes no such keyword — the dataclass field's own default is
    False and the Art. 122(6) election is Basel 3.1 only — so there is nothing to
    pass and the CRR arm relies on that default.

    Args:
        framework: ``"CRR"`` or ``"BASEL_3_1"``.
        facility_share_metric: the allocation metric election. Passed through only
            when ``CalculationConfig`` carries the field; the field lands with the
            S3 aggregator slice, so on current code the argument is accepted and
            ignored and this module still imports.
    """
    if framework == "CRR":
        config = CalculationConfig.crr(
            reporting_date=CRR_REPORTING_DATE,
            permission_mode=PermissionMode.IRB,
        )
    else:
        config = _b31_config(B31_REPORTING_DATE)
    return _with_metric(config, facility_share_metric)


def facility_share_prior_config(framework: str) -> CalculationConfig:
    """The same config at an EARLIER reporting date, for C 08.04's opening balance.

    C 08.04 reports RWEA flows against the prior reference date, so without a
    prior frame its rows are null by construction and every published rule over
    the movement table stays NOT_EVALUATED — the fail-open shape. A genuinely
    earlier date rather than the same frame re-passed, so the opening balance is a
    real prior figure rather than a fiction asserting nothing moved.

    The metric election is deliberately NOT a parameter here: the prior frame
    supplies an opening balance, and running it under a different allocation than
    the current period would manufacture a movement that no input change caused.
    """
    if framework == "CRR":
        return CalculationConfig.crr(
            reporting_date=CRR_PRIOR_DATE,
            permission_mode=PermissionMode.IRB,
        )
    return _b31_config(B31_PRIOR_DATE)


# ---------------------------------------------------------------------------
# Table builders (private)
# ---------------------------------------------------------------------------


def _counterparties() -> pl.DataFrame:
    """Four corporate obligors, identical in every attribute that prices them.

    None is a natural person and none is managed as retail, so the Art. 123A
    granularity limb is inert. None is defaulted. None is a financial-sector
    entity, so the Basel 3.1 F-IRB senior LGD resolves to its non-FSE row, and
    ``apply_fi_scalar`` is False so the Art. 153(2) financial-institution
    correlation multiplier stays off.
    """
    return pl.DataFrame(
        [_counterparty(ref) for ref in (CP_SA, CP_LOW, CP_IRB, CP_ANCHOR)],
        schema=dtypes_of(COUNTERPARTY_SCHEMA),
    )


def _ratings(variant: FacilityShareVariant) -> pl.DataFrame:
    """Two external CQS ratings and two internal PD ratings, never both on one obligor.

    An obligor carrying only an external rating routes standardised on a null
    internal PD; an obligor carrying only an internal PD takes the unrated
    corporate weight for its SA-equivalent. That separation is what gives the
    three share candidates three distinct metrics.
    """
    return pl.DataFrame(
        [
            _external(RTG_SA, CP_SA, cqs=2),
            _external(RTG_LOW, CP_LOW, cqs=1),
            _internal(RTG_IRB, CP_IRB, pd=PD_IRB),
            _internal(RTG_ANCHOR, CP_ANCHOR, pd=ANCHOR_PD[variant]),
        ],
        schema=dtypes_of(RATINGS_SCHEMA),
    )


def _facilities() -> pl.DataFrame:
    """The shared facility and the single-member control, both owned by ``CP_SA``.

    ``is_obs_commitment=True`` selects the Art. 166(8)(d) credit-line limb of the
    F-IRB conversion factor under CRR (Art. 166C routes it to the SA factor under
    Basel 3.1). ``lgd`` and ``lgd_unsecured`` are left null and
    ``has_sufficient_collateral_data`` False, which keeps every IRB row on the
    Foundation branch and its supervisory LGD.
    """
    return pl.DataFrame(
        [_facility(FAC_SHARE, LIMIT_SHARE), _facility(FAC_SOLO, LIMIT_SOLO)],
        schema=dtypes_of(FACILITY_SCHEMA),
    )


def _loans(variant: FacilityShareVariant) -> pl.DataFrame:
    """Four drawn exposures — two mapped to the share, one to the control, one loose.

    ``other_own_funds_reductions`` is set on the two F-IRB loans to exactly their
    Basel 3.1 expected loss, which makes Pool B cover the loans' EL and leaves the
    winning candidate's own EL as the only assignment-dependent OF-ADJ channel.
    It is derived from the PD rather than typed, so the anchor's PD stays the
    single free input across the two variants. Measured: the column does not move
    ``ead_final`` — it is read only by the expected-loss summary and the IRB
    shortfall adjustment.
    """
    return pl.DataFrame(
        [
            _loan(
                LN_IRB,
                CP_IRB,
                DRAWN_IRB,
                other_own_funds_reductions=_b31_expected_loss(PD_IRB, DRAWN_IRB),
            ),
            _loan(LN_LOW, CP_LOW, DRAWN_LOW),
            _loan(LN_SOLO, CP_SA, DRAWN_SOLO),
            _loan(
                LN_ANCHOR,
                CP_ANCHOR,
                DRAWN_ANCHOR,
                other_own_funds_reductions=_b31_expected_loss(ANCHOR_PD[variant], DRAWN_ANCHOR),
            ),
        ],
        schema=dtypes_of(LOAN_SCHEMA),
    )


def _facility_mappings() -> pl.DataFrame:
    """Three loan mappings, and no ``child_type="facility"`` row anywhere.

    Without a facility-to-facility edge neither parent is a Multiple Option
    Facility, so the waterfall and residual paths are untouched.

    Note what is NOT here: the owner has no loan mapped to ``FS-FAC-SHARE``. That
    is the point of the scenario. Today's candidate detection reads distinct
    counterparties off DESCENDANTS only, so the owner is not a member and the
    candidate set is the two descendants; admitting the owner is what the design
    of record's D3 decision changes, and the owner is the winner under the
    un-floored metric.
    """
    return pl.DataFrame(
        [
            _mapping(FAC_SHARE, LN_IRB),
            _mapping(FAC_SHARE, LN_LOW),
            _mapping(FAC_SOLO, LN_SOLO),
        ],
        schema=dtypes_of(FACILITY_MAPPING_SCHEMA),
    )


# ---------------------------------------------------------------------------
# Row helpers (private)
# ---------------------------------------------------------------------------


def _counterparty(reference: str) -> dict:
    """One corporate obligor row (unset optional columns take schema defaults)."""
    return {
        "counterparty_reference": reference,
        "entity_type": "corporate",
        "country_code": "GB",
        "annual_revenue": ANNUAL_REVENUE,
        "default_status": False,
        "is_financial_sector_entity": False,
        "apply_fi_scalar": False,
    }


def _external(reference: str, counterparty_reference: str, *, cqs: int) -> dict:
    """External ECAI rating row — a CQS with no PD and no model, so the obligor routes SA."""
    return {
        "rating_reference": reference,
        "counterparty_reference": counterparty_reference,
        "rating_type": "external",
        "cqs": cqs,
        "rating_date": _RATING_DATE,
    }


def _internal(reference: str, counterparty_reference: str, *, pd: float) -> dict:
    """Internal model rating row (PD + model_id — the IRB routing pair).

    ``model_id`` is imported from the IRB helpers rather than typed: it is the
    same constant ``create_firb_only_model_permissions`` writes into its
    permission rows, so the ratings and the permissions cannot drift apart.
    """
    return {
        "rating_reference": reference,
        "counterparty_reference": counterparty_reference,
        "rating_type": "internal",
        "pd": pd,
        "model_id": _TEST_MODEL_ID,
        "rating_date": _RATING_DATE,
    }


def _facility(reference: str, limit: float) -> dict:
    """One committed, unsecured, non-revolving medium-risk facility owned by ``CP_SA``."""
    return {
        "facility_reference": reference,
        "counterparty_reference": CP_SA,
        "limit": limit,
        "risk_type": _RISK_TYPE,
        "committed": True,
        "is_obs_commitment": True,
        "is_revolving": False,
        "is_secured": False,
        "has_sufficient_collateral_data": False,
        "seniority": Seniority.SENIOR.value,
        "currency": _CURRENCY,
        "effective_maturity": EFFECTIVE_MATURITY,
        "value_date": _VALUE_DATE,
        "maturity_date": _MATURITY_DATE,
    }


def _loan(
    reference: str,
    counterparty_reference: str,
    drawn_amount: float,
    *,
    other_own_funds_reductions: float | None = None,
) -> dict:
    """One drawn, unsecured, senior term loan (unset optional columns take defaults)."""
    row: dict = {
        "loan_reference": reference,
        "counterparty_reference": counterparty_reference,
        "product_type": _PRODUCT_TYPE,
        "drawn_amount": drawn_amount,
        "interest": 0.0,
        "currency": _CURRENCY,
        "seniority": Seniority.SENIOR.value,
        "effective_maturity": EFFECTIVE_MATURITY,
        "has_sufficient_collateral_data": False,
        "due_diligence_performed": True,
        "value_date": _VALUE_DATE,
        "maturity_date": _MATURITY_DATE,
    }
    if other_own_funds_reductions is not None:
        row["other_own_funds_reductions"] = other_own_funds_reductions
    return row


def _mapping(parent_facility_reference: str, child_reference: str) -> dict:
    """One parent-facility -> loan edge."""
    return {
        "parent_facility_reference": parent_facility_reference,
        "child_reference": child_reference,
        "child_type": "loan",
    }


# ---------------------------------------------------------------------------
# Derived amounts and config plumbing (private)
# ---------------------------------------------------------------------------


def _b31_supervisory_lgd() -> float:
    """The Basel 3.1 F-IRB supervisory LGD for a senior unsecured non-FSE exposure.

    Read back from the resolved rulepack rather than typed. The rulepack is the
    value home; a literal here would be a second one, and it would drift.
    """
    pack = resolve("b31", B31_REPORTING_DATE)
    rows = dict(pack.decision("firb_supervisory_lgd").rows)
    return float(rows[("unsecured", "senior", False)])


def _b31_expected_loss(pd: float, drawn: float) -> float:
    """Basel 3.1 expected loss on a drawn F-IRB exposure — ``PD x LGD x EAD``.

    Used as the loan's Pool B amount so the expected-loss channel of OF-ADJ is
    exactly neutralised for the drawn book, leaving the winning candidate's own
    expected loss as the only assignment-dependent term.
    """
    return pd * _b31_supervisory_lgd() * drawn


def _b31_config(reporting_date: date) -> CalculationConfig:
    """The Basel 3.1 arm, with every OF-ADJ input pinned to zero explicitly.

    ``gcra_amount = 0`` makes the general-credit-risk-adjustment cap
    ``min(0, rate x S-TREA)`` inert and demonstrably so, and ``sa_t2_credit`` /
    ``art_40_deductions`` at zero leave the expected-loss channel as the whole of
    OF-ADJ. ``skip_transitional_floor=False`` keeps the floor percentage on the
    PRA transitional schedule, which the June-2027 reporting date resolves to the
    2027 step.
    """
    return CalculationConfig.basel_3_1(
        reporting_date=reporting_date,
        permission_mode=PermissionMode.IRB,
        use_investment_grade_assessment=False,
        # This portfolio has no retail obligor, so the Art. 123A(1)(b)(ii) limb
        # decides nothing and the run must NOT be softened relative to production
        # defaults. Stated rather than inherited — see facility_share_config.
        enforce_retail_granularity=True,
        gcra_amount=0.0,
        sa_t2_credit=0.0,
        art_40_deductions=0.0,
        skip_transitional_floor=False,
    )


def _with_metric(config: CalculationConfig, metric: str) -> CalculationConfig:
    """Apply the facility-share metric election, if the config carries the field yet.

    The field arrives with the S3 aggregator slice. Until then this is a no-op, so
    the fixture imports and every run in this module works on current code — and
    the day the field lands, the election starts flowing with no edit here.
    """
    if any(field.name == _METRIC_FIELD for field in fields(CalculationConfig)):
        return replace(config, **{_METRIC_FIELD: metric})
    return config
