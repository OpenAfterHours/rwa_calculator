"""
Facility-share QRRE demotion portfolio — scenario **FS-QRRE** (P5.62).

Pipeline position:
    build_facility_share_qrre_bundle(variant) -> RawDataBundle -> PipelineOrchestrator
        -> AggregatedResultBundle

What this portfolio is for
--------------------------
The one path on which the facility-share fan-out can LOWER RWA: a natural person
whose revolving retail card is demoted out of the qualifying revolving retail
(QRRE) sub-class because a facility-share candidate row pushes their per-individual
aggregate nominal exposure over the limit, at a PD where the ordinary retail
correlation sits below the fixed QRRE one.

Under decision D4 of the design of record a candidate row counts toward its own
member's obligor aggregates with no special-casing. The QRRE aggregate
(``engine/classify/subtypes.py::qrre_obligor_aggregate_limit_expr``) dedupes on
``(counterparty_reference, parent_facility_reference)``, so a candidate adds to a
member's aggregate only where that member holds no other QRRE-candidate leg under
the shared facility. Every NON-owner member is a member *because* it holds a leg
under the facility, and that leg inherits the facility's revolving / unsecured /
limit attributes and carries ``undrawn_amount = 0``. Its QRRE-candidacy test is
therefore strictly weaker than the candidate row's (which also needs the facility's
risk type to be unconditionally cancellable), so whenever the candidate qualifies
the leg already contributes the facility limit and the member's candidate dedupes
to nothing. **The facility
OWNER with no leg of its own under the facility is therefore the only member whose
QRRE aggregate a candidate can move**, and that is the shape built here.

Two owner groups, independent of each other
--------------------------------------------
Each group is one natural-person owner, one natural-person member, a shared
revolving facility the owner owns, and the owner's own fully drawn card under a
separate facility. The card is the measured row: it survives to the results in
every variant, while the owner's candidate row is a LOSER of the share and is
dropped by the aggregator. Assert on the card, never on the candidate.

    group      owner PD   modelled LGD   what the demotion does to the card's RWA
    ---------  ---------  -------------  -----------------------------------------
    high_pd    10%        60%            lowers it in both regimes (correlation
                                         crossover, above it)
    low_lgd    6%         40%            raises it under CRR (below the correlation
                                         crossover, no LGD input floor) and LOWERS
                                         it under Basel 3.1 (the PS1/26 Art. 164(4)
                                         LGD input floor falls from the QRRE value
                                         to the other-unsecured-retail value)

Both members carry a PD well above their owner's, so the member's candidate is the
riskiest and wins the share in both regimes; the owner's candidate is the loser
whose classification-time contribution is the one this scenario measures.

The single toggle
-----------------
:data:`FacilityShareQrreVariant` names three bundles. They differ in ONE input each
against ``"cancellable"``:

- ``"cancellable"`` — the shared facility's ``risk_type`` is ``LR`` (CRR Annex I
  para 4(a) / PS1/26 Table A1 row (7) unconditionally cancellable), so the
  owner's candidate row passes the Art. 147(5A)(b) / 154(4)(b) gate, joins the
  QRRE sub-portfolio, and its facility limit enters the owner's aggregate.
- ``"not_cancellable"`` — the same facility at ``MR``. The owner's candidate
  carries undrawn headroom that is NOT unconditionally cancellable, fails the
  (b) gate, is not in the QRRE sub-portfolio, and so contributes nothing to the
  owner's aggregate. This is the in-engine counterfactual that makes "the card
  actually flips" an assertion rather than an assumption (LESSONS C11). It does
  not lean on the separate fully-drawn discontinuity (a share fully drawn by a
  non-owner emits no undrawn row at all), which is a reading still open.
- ``"unshared"`` — ``"cancellable"`` with the member's loan left unmapped, so the
  facility has one member (its owner) and emits its ordinary single undrawn row.
  The card is demoted exactly as in ``"cancellable"``: with headroom on the
  facility, sharing it does not move the owner, because the owner's candidate
  contributes exactly what its own undrawn row would on an unshared facility.

Sizing
------
The owner's card limit is below the QRRE limit and card plus shared limit is above
it, in both regimes. That limit is never typed here: the test reads it back with
``regulatory_threshold(pack, "qrre_max_limit", config.eur_gbp_rate)`` (EUR 100,000
at the run's rate under CRR; GBP 90,000 under Basel 3.1) and asserts the sizing as
an adequacy condition (LESSONS A4).

Regulatory values
-----------------
This module types NO regulatory value. PDs and LGDs are model inputs, the limits
and balances are portfolio amounts; every floor, threshold and scaling factor the
assertions need is read back from the resolved rulepack by the test.

Deliberately absent
-------------------
No collateral, guarantees, provisions, netting or ratings other than the four
internal PDs; no multiple option facility (no ``child_type="facility"`` edge); no
contingent; no transactor flag (every facility is a revolver, so the Basel 3.1
QRRE PD floor is the revolver one and sits far below every PD here). All
obligors are in ``GB`` with GBP income so the Art. 123B currency-mismatch path is
inert. This portfolio is NOT registered in the supervisory gate's ``RUNS``: it
is a classification measurement, and the C 08.01 QRRE and other-retail sheets it
would reach are already live in registered portfolios.

References:
- CRR Art. 154(4)(a)-(c); PS1/26 Art. 147(5A)(a)-(c): the QRRE conditions and
  the per-individual aggregate-nominal limit.
- CRR Art. 154(1)/(4); PS1/26 Art. 154(1)(b)/(4): the other-retail correlation
  and the fixed QRRE correlation.
- PS1/26 Art. 163(1), 164(4)(b)(i)/(ii): the retail PD and LGD input floors.
- docs/plans/facility-share-riskiest-member.md: decisions D3 / D4 and §10.3.
"""

from __future__ import annotations

from dataclasses import dataclass
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
from rwa_calc.domain.enums import PermissionMode
from tests.fixtures.irb_test_helpers import _TEST_MODEL_ID, create_full_irb_model_permissions
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants — the single source of truth for test assertions.
# ---------------------------------------------------------------------------

#: The three bundles this module builds; see the module docstring.
FacilityShareQrreVariant = Literal["cancellable", "not_cancellable", "unshared"]

ALL_VARIANTS: tuple[FacilityShareQrreVariant, ...] = (
    "cancellable",
    "not_cancellable",
    "unshared",
)


@dataclass(frozen=True)
class OwnerGroup:
    """One owner, one member, the share they hold and the owner's own card.

    Attributes:
        key: Short name used in test ids.
        owner: The share facility's owner — the natural person whose card is measured.
        member: The second natural-person member; draws under the share and wins it.
        share_facility: The revolving facility both obligors are members of.
        card_facility: The owner's own revolving card facility.
        card_loan: The owner's drawn card balance — the measured, surviving row.
        member_loan: The member's drawing under the share facility.
        owner_pd: The owner's internal PD.
        member_pd: The member's internal PD, above the owner's so the member wins.
        lgd: Modelled LGD on every exposure of the group.
    """

    key: str
    owner: str
    member: str
    share_facility: str
    card_facility: str
    card_loan: str
    member_loan: str
    owner_pd: float
    member_pd: float
    lgd: float

    @property
    def owner_candidate(self) -> str:
        """The owner's facility-share candidate row (the ``@<member>`` grammar)."""
        return f"{self.share_facility}_UNDRAWN@{self.owner}"

    @property
    def member_candidate(self) -> str:
        """The member's facility-share candidate row."""
        return f"{self.share_facility}_UNDRAWN@{self.member}"

    @property
    def share_undrawn(self) -> str:
        """The share's undrawn row as it survives the aggregator (or is emitted unshared)."""
        return f"{self.share_facility}_UNDRAWN"


#: Owner PD above the correlation crossover in both regimes, modelled LGD above
#: the Basel 3.1 QRRE LGD input floor so that floor never binds.
HIGH_PD = OwnerGroup(
    key="high_pd",
    owner="FSQ-CP-OWNER-HI",
    member="FSQ-CP-MEMBER-HI",
    share_facility="FSQ-FAC-SHARE-HI",
    card_facility="FSQ-FAC-CARD-HI",
    card_loan="FSQ-LN-CARD-HI",
    member_loan="FSQ-LN-MEMBER-HI",
    owner_pd=0.10,
    member_pd=0.25,
    lgd=0.60,
)

#: Owner PD BELOW the correlation crossover, modelled LGD below the Basel 3.1
#: QRRE LGD input floor and above the other-unsecured-retail one, so the floor
#: drop on demotion is the channel that decides the Basel 3.1 direction.
LOW_LGD = OwnerGroup(
    key="low_lgd",
    owner="FSQ-CP-OWNER-LO",
    member="FSQ-CP-MEMBER-LO",
    share_facility="FSQ-FAC-SHARE-LO",
    card_facility="FSQ-FAC-CARD-LO",
    card_loan="FSQ-LN-CARD-LO",
    member_loan="FSQ-LN-MEMBER-LO",
    owner_pd=0.06,
    member_pd=0.25,
    lgd=0.40,
)

GROUPS: tuple[OwnerGroup, ...] = (HIGH_PD, LOW_LGD)

#: The shared facility's limit, and the owner's own card limit. Card alone is
#: under the QRRE limit in both regimes; card plus share is over it in both. The
#: test asserts that against the pack, never against a typed limit.
LIMIT_SHARE: float = 50_000.0
LIMIT_CARD: float = 60_000.0

#: The card is fully drawn: no undrawn row hangs off it, and its exposure value is
#: the drawn balance with no conversion factor anywhere in its hand-calc.
DRAWN_CARD: float = LIMIT_CARD

#: The member's drawing under the share — leaves headroom, so the share emits an
#: undrawn row in every variant.
DRAWN_MEMBER: float = 20_000.0

#: Unconditionally cancellable vs medium risk — the input vocabulary is the short
#: code in ``data/schemas.py::VALID_RISK_TYPES_INPUT``.
_RISK_TYPE_CANCELLABLE: str = "LR"
_RISK_TYPE_NOT_CANCELLABLE: str = "MR"

_CURRENCY: str = "GBP"
_PRODUCT_TYPE: str = "credit_card"
_VALUE_DATE: date = date(2020, 1, 1)
_MATURITY_DATE: date = date(2031, 12, 31)  # after both reporting dates
_RATING_DATE: date = _VALUE_DATE

#: Reporting dates, the same pair the FS-1 facility-share portfolio uses.
CRR_REPORTING_DATE: date = date(2025, 12, 31)
B31_REPORTING_DATE: date = date(2027, 6, 1)


# ---------------------------------------------------------------------------
# Main public entry points
# ---------------------------------------------------------------------------


def build_facility_share_qrre_bundle(variant: FacilityShareQrreVariant) -> RawDataBundle:
    """Assemble the FS-QRRE portfolio for one variant as a sealed bundle.

    Sealed against the loader edge contracts by ``make_raw_bundle``, so it is
    shape-identical to a parquet-loaded production bundle. ``model_permissions``
    grants A-IRB for every retail class (retail has no Foundation route), so
    every exposure prices on its own PD and modelled LGD.

    Args:
        variant: ``"cancellable"``, ``"not_cancellable"`` or ``"unshared"`` — see
            the module docstring.
    """
    return make_raw_bundle(
        counterparties=_counterparties(),
        facilities=_facilities(variant),
        loans=_loans(),
        facility_mappings=_facility_mappings(variant),
        ratings=_ratings(),
        model_permissions=create_full_irb_model_permissions(),
    )


def facility_share_qrre_config(framework: str) -> CalculationConfig:
    """The FS-QRRE run config for one framework: IRB permission mode, default elections.

    The Basel 3.1 arm states ``enforce_retail_granularity=False`` rather than
    inheriting it: the optional BCBS CRE20.66 0.2% limb is not a PS1/26 Art. 123A
    condition (RE-04), and a softened or hardened granularity test would move
    regulatory-retail status, which this scenario must hold fixed.

    Args:
        framework: ``"CRR"`` or ``"BASEL_3_1"``.
    """
    if framework == "CRR":
        return CalculationConfig.crr(
            reporting_date=CRR_REPORTING_DATE,
            permission_mode=PermissionMode.IRB,
        )
    return CalculationConfig.basel_3_1(
        reporting_date=B31_REPORTING_DATE,
        permission_mode=PermissionMode.IRB,
        enforce_retail_granularity=False,
    )


def share_risk_type(variant: FacilityShareQrreVariant) -> str:
    """The shared facilities' ``risk_type`` in ``variant`` — the one toggled input."""
    return _RISK_TYPE_NOT_CANCELLABLE if variant == "not_cancellable" else _RISK_TYPE_CANCELLABLE


# ---------------------------------------------------------------------------
# Table builders (private)
# ---------------------------------------------------------------------------


def _counterparties() -> pl.DataFrame:
    """Four natural persons managed as retail, none defaulted, all with GBP income."""
    return pl.DataFrame(
        [_counterparty(reference) for group in GROUPS for reference in (group.owner, group.member)],
        schema=dtypes_of(COUNTERPARTY_SCHEMA),
    )


def _ratings() -> pl.DataFrame:
    """One internal PD per obligor — the A-IRB routing pair (PD + model_id)."""
    return pl.DataFrame(
        [
            _internal(f"FSQ-RTG-{reference}", reference, pd=pd)
            for group in GROUPS
            for reference, pd in ((group.owner, group.owner_pd), (group.member, group.member_pd))
        ],
        schema=dtypes_of(RATINGS_SCHEMA),
    )


def _facilities(variant: FacilityShareQrreVariant) -> pl.DataFrame:
    """Per group: the shared facility (risk type toggled) and the owner's own card.

    Both are owned by the group's OWNER — the owner holds no loan under the share,
    so the share's candidate row is the owner's only route to its limit.
    """
    rows: list[dict] = []
    for group in GROUPS:
        rows.append(
            _facility(
                group.share_facility,
                group.owner,
                LIMIT_SHARE,
                lgd=group.lgd,
                risk_type=share_risk_type(variant),
            )
        )
        rows.append(
            _facility(
                group.card_facility,
                group.owner,
                LIMIT_CARD,
                lgd=group.lgd,
                risk_type=_RISK_TYPE_CANCELLABLE,
            )
        )
    return pl.DataFrame(rows, schema=dtypes_of(FACILITY_SCHEMA))


def _loans() -> pl.DataFrame:
    """Per group: the owner's fully drawn card and the member's partial drawing."""
    rows: list[dict] = []
    for group in GROUPS:
        rows.append(_loan(group.card_loan, group.owner, DRAWN_CARD, lgd=group.lgd))
        rows.append(_loan(group.member_loan, group.member, DRAWN_MEMBER, lgd=group.lgd))
    return pl.DataFrame(rows, schema=dtypes_of(LOAN_SCHEMA))


def _facility_mappings(variant: FacilityShareQrreVariant) -> pl.DataFrame:
    """Card under its own facility; the member's loan under the share unless ``unshared``.

    Note what is never here: a loan or contingent of the OWNER mapped to the share.
    That is the shape the whole scenario rests on — and no ``child_type="facility"``
    edge, so no facility is a multiple option facility.
    """
    rows: list[dict] = []
    for group in GROUPS:
        rows.append(_mapping(group.card_facility, group.card_loan))
        if variant != "unshared":
            rows.append(_mapping(group.share_facility, group.member_loan))
    return pl.DataFrame(rows, schema=dtypes_of(FACILITY_MAPPING_SCHEMA))


# ---------------------------------------------------------------------------
# Row helpers (private)
# ---------------------------------------------------------------------------


def _counterparty(reference: str) -> dict:
    """One natural-person obligor row (unset optional columns take schema defaults)."""
    return {
        "counterparty_reference": reference,
        "entity_type": "individual",
        "country_code": "GB",
        "default_status": False,
        "is_managed_as_retail": True,
        "borrower_income_currency": _CURRENCY,
    }


def _internal(reference: str, counterparty_reference: str, *, pd: float) -> dict:
    """Internal model rating row; ``model_id`` matches the permission helper's rows."""
    return {
        "rating_reference": reference,
        "counterparty_reference": counterparty_reference,
        "rating_type": "internal",
        "pd": pd,
        "model_id": _TEST_MODEL_ID,
        "rating_date": _RATING_DATE,
    }


def _facility(
    reference: str,
    counterparty_reference: str,
    limit: float,
    *,
    lgd: float,
    risk_type: str,
) -> dict:
    """One committed, revolving, unsecured revolver (not a transactor) facility."""
    return {
        "facility_reference": reference,
        "counterparty_reference": counterparty_reference,
        "product_type": _PRODUCT_TYPE,
        "limit": limit,
        "risk_type": risk_type,
        "committed": True,
        "is_revolving": True,
        "is_qrre_transactor": False,
        "is_secured": False,
        "lgd": lgd,
        "currency": _CURRENCY,
        "value_date": _VALUE_DATE,
        "maturity_date": _MATURITY_DATE,
    }


def _loan(reference: str, counterparty_reference: str, drawn_amount: float, *, lgd: float) -> dict:
    """One drawn revolving balance carrying its modelled LGD."""
    return {
        "loan_reference": reference,
        "counterparty_reference": counterparty_reference,
        "product_type": _PRODUCT_TYPE,
        "drawn_amount": drawn_amount,
        "interest": 0.0,
        "lgd": lgd,
        "currency": _CURRENCY,
        "value_date": _VALUE_DATE,
        "maturity_date": _MATURITY_DATE,
    }


def _mapping(parent_facility_reference: str, child_reference: str) -> dict:
    """One parent-facility -> loan edge."""
    return {
        "parent_facility_reference": parent_facility_reference,
        "child_reference": child_reference,
        "child_type": "loan",
    }
