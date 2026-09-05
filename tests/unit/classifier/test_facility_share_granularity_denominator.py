"""
Art. 123A(1)(b)(ii): facility-share candidate rows must not move the denominator.

Pipeline position:
    HierarchyResolver (candidate fan-out) -> ExposureClassifier
        (engine/classify/attributes.py::_build_qualifies_as_retail_expr)

The limb, and why the fan-out is a hazard for it
------------------------------------------------
PS1/26 Art. 123A(1)(b)(ii) (BCBS CRE20.66) requires that no single obligor's
aggregate exposure exceed 0.2% of the total regulatory-retail portfolio. The
engine builds that portfolio total as a PORTFOLIO-WIDE sum with no ``.over()``:
each retail-candidate row contributes ``lending_group_adjusted_exposure`` divided
by its obligor's line count, so an obligor is counted once however many rows it
has.

The candidate fan-out adds synthetic rows to that population. The design of
record treats this as the one site where decision D4's "no special-casing" is
unsafe, on the reasoning that extra rows inflate the denominator and so lower
every obligor's share against the 0.2% limit — which would be anti-conservative,
keeping an obligor in retail that should have re-routed to corporate.

What the measurement says, which is not what the design predicted
-----------------------------------------------------------------
MEASURED on the pre-change engine, three ways (a candidate row for the pool
obligor itself, a candidate row for a member with no other exposure, and both):
**candidate rows do not move the denominator at all.** Two mechanisms combine.

1. CRR Art. 147 defines "total amount owed" as the DRAWN amount, and
   ``enrich.py`` implements exactly that (``total_exposure_amount =
   drawn_amount``). A ``facility_undrawn`` row is drawn-zero, so it contributes
   0.0 to ``exposure_for_retail_threshold`` and hence 0.0 to
   ``lending_group_adjusted_exposure``. The design expected this carrier to be
   inflated by the fan-out; it cannot be.
2. The denominator divides each obligor's aggregate by that obligor's LINE
   COUNT, so adding a row to an obligor whose rows share one ``_sa_class``
   leaves its term algebraically unchanged.

The one residual case, and its direction. An obligor with ``L`` retail-class rows
contributes ``L . A / L = A``. If a candidate row joins it carrying a
NON-retail class, the numerator's row count stays ``L`` while the divisor becomes
``L + 1``, so the obligor's contribution falls to ``L . A / (L + 1)`` and the
denominator SHRINKS. A smaller denominator makes every obligor's share of the
portfolio LARGER, which pushes obligors ACROSS the 0.2% limit rather than back
inside it — so the residual effect is conservative, and it is the opposite of the
anti-conservative direction the design of record predicted.

So this file does not drive a fix. It PINS the invariance, on a fixture sized so
that a denominator move of even 0.1% would be visible — which is what makes the
green meaningful rather than vacuous, and what will redden if a later change
starts counting undrawn amounts in the retail threshold or special-cases the
denominator in a way that shifts it.

The FS-1 acceptance portfolio cannot host this at all: its divergence chain
requires every standardised member to sit BELOW the output-floor percentage, and
regulatory retail sits above it at 75%, so no fixture that proves the
floor-aware allocation metric can also carry a retail obligor.

References:
- PS1/26 Art. 123A(1)(b)(ii); BCBS CRE20.66 — the 0.2% granularity limb.
- CRR Art. 147 — "total amount owed" is the drawn amount.
- src/rwa_calc/engine/classify/attributes.py::_build_qualifies_as_retail_expr
- docs/plans/facility-share-riskiest-member.md Section 4 (D4).
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import ResolvedHierarchyBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ExposureClass
from rwa_calc.engine.classify import ExposureClassifier
from rwa_calc.rulebook.resolve import resolve
from tests.fixtures.resolved_bundle import make_counterparty_lookup, make_resolved_bundle

_REPORTING_DATE = date(2027, 6, 1)
_VALUE_DATE = date(2023, 1, 1)
_MATURITY_DATE = date(2032, 1, 1)

#: The 0.2% limit, read from the pack rather than typed.
_LIMIT = float(resolve("b31", _REPORTING_DATE).scalar("b31_retail_granularity_limit"))

#: The rest of the regulatory-retail portfolio. One obligor is enough: the limb
#: compares each obligor's aggregate against the TOTAL, and a hundred small
#: obligors would only make the arithmetic harder to read.
_POOL = 500_000.0

#: The near-limit obligor's aggregate at the exact boundary, and two probes a
#: tenth of a percent either side of it. ``share = a / (a + pool)``, so
#: ``a* = limit . pool / (1 - limit)``.
_BOUNDARY = _LIMIT * _POOL / (1.0 - _LIMIT)
_JUST_UNDER = _BOUNDARY * 0.999
_JUST_OVER = _BOUNDARY * 1.001

_SMALL = "RT-NEAR-LIMIT"
_BIG = "RT-POOL"
_MEMBER = "RT-SHARE-MEMBER"


# ---------------------------------------------------------------------------
# Frame builders
# ---------------------------------------------------------------------------


def _counterparties() -> pl.LazyFrame:
    """Three natural-person retail obligors, all managed as part of a retail pool.

    Natural persons, because Art. 123A(1)(a)'s SME auto-qualification would
    short-circuit the granularity limb entirely for an SME entity and this file
    would then test nothing.
    """
    references = (_SMALL, _BIG, _MEMBER)
    return (
        pl.DataFrame(
            {
                "counterparty_reference": list(references),
                "counterparty_name": list(references),
                "entity_type": ["individual"] * 3,
                "country_code": ["GB"] * 3,
                "annual_revenue": [0.0] * 3,
                "total_assets": [0.0] * 3,
                "default_status": [False] * 3,
                "sector_code": ["RETAIL"] * 3,
                "apply_fi_scalar": [False] * 3,
                "is_managed_as_retail": [True] * 3,
                "is_natural_person": [True] * 3,
            }
        )
        .lazy()
        .with_columns(
            [
                pl.lit(False).alias("counterparty_has_parent"),
                pl.lit(None).cast(pl.String).alias("parent_counterparty_reference"),
                pl.lit(None).cast(pl.String).alias("ultimate_parent_reference"),
                pl.lit(0).cast(pl.Int32).alias("counterparty_hierarchy_depth"),
                pl.lit(None).cast(pl.Int8).alias("cqs"),
            ]
        )
    )


def _row(
    reference: str,
    counterparty: str,
    drawn: float,
    *,
    aggregate: float | None = None,
    exposure_type: str = "loan",
) -> dict[str, object]:
    """One classifier-ready exposure row.

    ``exposure_for_retail_threshold`` is set to the DRAWN amount, which is what
    ``enrich.py`` produces — an undrawn row therefore carries 0.0 here, and that
    zero is the whole reason the fan-out cannot inflate the denominator.
    """
    return {
        "exposure_reference": reference,
        "exposure_type": exposure_type,
        "product_type": "PERSONAL",
        "book_code": "RETAIL",
        "counterparty_reference": counterparty,
        "value_date": _VALUE_DATE,
        "maturity_date": _MATURITY_DATE,
        "currency": "GBP",
        "drawn_amount": drawn,
        "undrawn_amount": 0.0,
        "nominal_amount": 0.0,
        "lgd": 0.45,
        "seniority": "senior",
        "exposure_has_parent": False,
        "root_facility_reference": None,
        "facility_hierarchy_depth": 1,
        "counterparty_has_parent": False,
        "parent_counterparty_reference": None,
        "ultimate_parent_reference": None,
        "counterparty_hierarchy_depth": 1,
        "lending_group_reference": None,
        "lending_group_total_exposure": drawn if aggregate is None else aggregate,
        "lending_group_adjusted_exposure": drawn if aggregate is None else aggregate,
        "residential_collateral_value": 0.0,
        "exposure_for_retail_threshold": drawn,
    }


def _bundle(rows: list[dict[str, object]]) -> ResolvedHierarchyBundle:
    return make_resolved_bundle(
        exposures=pl.DataFrame(rows).lazy(),
        lending_group_totals=pl.LazyFrame(
            schema={"lending_group_reference": pl.String, "total_exposure": pl.Float64}
        ),
        counterparty_lookup=make_counterparty_lookup(
            counterparties=_counterparties(),
            parent_mappings=pl.LazyFrame(
                schema={
                    "child_counterparty_reference": pl.String,
                    "parent_counterparty_reference": pl.String,
                }
            ),
            ultimate_parent_mappings=pl.LazyFrame(
                schema={
                    "counterparty_reference": pl.String,
                    "ultimate_parent_reference": pl.String,
                    "hierarchy_depth": pl.Int32,
                }
            ),
            rating_inheritance=pl.LazyFrame(
                schema={
                    "counterparty_reference": pl.String,
                    "internal_pd": pl.Float64,
                    "internal_model_id": pl.String,
                    "external_cqs": pl.Int8,
                    "cqs": pl.Int8,
                    "pd": pl.Float64,
                }
            ),
        ),
        hierarchy_errors=[],
    )


def _config() -> CalculationConfig:
    """Basel 3.1 with the granularity limb ENFORCED — the production default."""
    return CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE, enforce_retail_granularity=True
    )


def _candidate_rows() -> list[dict[str, object]]:
    """Two flagged fan-out rows for members OTHER than the near-limit obligor.

    One belongs to the pool obligor, which already has a row; the other to a
    member with no other exposure in the book at all — the FS-1 owner shape,
    where a facility's owner has no loan under it. Both are drawn-zero, exactly
    as ``calculate_facility_undrawn`` produces them.
    """
    return [
        _row("SHARE_UNDRAWN@" + _BIG, _BIG, 0.0, aggregate=_POOL, exposure_type="facility_undrawn"),
        _row("SHARE_UNDRAWN@" + _MEMBER, _MEMBER, 0.0, exposure_type="facility_undrawn"),
    ]


def _qualification(aggregate: float, *, with_candidates: bool) -> tuple[bool, str]:
    """Classify the book and report the near-limit obligor's retail verdict."""
    rows = [
        _row("E-NEAR-LIMIT", _SMALL, aggregate),
        _row("E-POOL", _BIG, _POOL),
    ]
    if with_candidates:
        rows += _candidate_rows()
    frame = ExposureClassifier().classify(_bundle(rows), _config()).all_exposures.collect()
    hit = frame.filter(pl.col("exposure_reference") == "E-NEAR-LIMIT")
    return bool(hit["qualifies_as_retail"][0]), str(hit["exposure_class"][0])


# ---------------------------------------------------------------------------
# Adequacy — the fixture must sit ON the boundary, or the invariance is vacuous
# ---------------------------------------------------------------------------


def test_the_near_limit_obligor_sits_on_the_granularity_boundary() -> None:
    """
    A tenth of a percent either side of the limit flips the verdict.

    Arrange: a two-obligor retail book whose smaller obligor is placed at the
             exact 0.2% boundary, then 0.1% either side of it.
    Act:     classify each.
    Assert:  just under qualifies as retail; just over is re-routed to corporate.

    This is the adequacy assertion for everything below. The invariance claim
    "candidate rows do not move the denominator" is only worth making on a
    fixture where a move WOULD be visible. Here a denominator shift of 0.1% is
    enough to change the answer, so a green invariance test bounds the effect at
    0.1% rather than merely reporting that nothing obvious happened.

    Green before and after — it measures the fixture, not the change.
    """
    # Arrange / Act
    under_qualifies, under_class = _qualification(_JUST_UNDER, with_candidates=False)
    over_qualifies, over_class = _qualification(_JUST_OVER, with_candidates=False)

    # Assert
    assert under_qualifies is True, (
        f"an aggregate of {_JUST_UNDER:,.4f} against a {_POOL:,.0f} pool is "
        f"{_JUST_UNDER / (_JUST_UNDER + _POOL):.6%} of the portfolio, below the "
        f"{_LIMIT:.1%} limit, and must stay retail"
    )
    assert under_class == ExposureClass.RETAIL_OTHER.value
    assert over_qualifies is False, (
        "the fixture is not on the boundary: a 0.2% move in the obligor's own "
        "aggregate does not change the verdict, so an equal move in the "
        "DENOMINATOR would not either and the invariance test below is vacuous"
    )
    assert over_class == ExposureClass.CORPORATE.value


# ---------------------------------------------------------------------------
# The invariance
# ---------------------------------------------------------------------------


def test_classifier_granularity_denominator_excludes_candidates() -> None:
    """
    Adding flagged candidate rows for OTHER members leaves the verdict untouched.

    Arrange: the boundary book, then the same book plus two facility-share
             candidate rows — one for the pool obligor, one for a member with no
             other exposure at all.
    Act:     classify both, at the aggregate just under the limit and at the one
             just over it.
    Assert:  the verdict is identical in every cell.

    Both sides of the boundary are asserted, not just the qualifying side. A test
    that only checked "still retail" would pass on an implementation that made
    EVERYTHING retail, and the failure mode this limb exists to prevent is
    precisely an obligor staying retail when it should not.

    Since the verdict is a step function of the denominator and the fixture flips
    on a 0.1% move, this pins the candidate rows' effect on the denominator to
    below 0.1%. MEASURED to be exactly zero, for the two reasons in the module
    docstring — the drawn-only retail-threshold carrier and the line-count
    normalisation.
    """
    # Arrange / Act / Assert — both sides of the boundary, both books.
    for aggregate, expected in ((_JUST_UNDER, True), (_JUST_OVER, False)):
        without = _qualification(aggregate, with_candidates=False)
        with_them = _qualification(aggregate, with_candidates=True)
        assert without[0] is expected
        assert with_them == without, (
            f"at an aggregate of {aggregate:,.4f} the near-limit obligor is "
            f"{with_them} with candidate rows and {without} without them; a "
            "synthetic allocation row must not decide whether an UNRELATED "
            "obligor is regulatory retail"
        )


def test_candidate_rows_do_not_change_any_other_obligors_classification() -> None:
    """
    No row shared between the two books classifies differently.

    Arrange: the boundary book with and without the candidate rows.
    Act:     classify both and align on ``exposure_reference``.
    Assert:  class, retail qualification and the obligor aggregate all match.

    Broader than the single near-limit obligor on purpose: the granularity limb
    is portfolio-wide, so a denominator shift moves every obligor near ITS own
    limit, and asserting on one row would leave the rest of that population
    unobserved.
    """
    # Arrange
    base = [_row("E-NEAR-LIMIT", _SMALL, _JUST_UNDER), _row("E-POOL", _BIG, _POOL)]
    columns = ["exposure_class", "qualifies_as_retail", "lending_group_adjusted_exposure"]

    def classify(rows: list[dict[str, object]]) -> dict[str, dict]:
        frame = ExposureClassifier().classify(_bundle(rows), _config()).all_exposures.collect()
        return {
            row["exposure_reference"]: {name: row[name] for name in columns}
            for row in frame.select(["exposure_reference", *columns]).to_dicts()
        }

    # Act
    without = classify(base)
    with_them = classify([*base, *_candidate_rows()])

    # Assert
    for reference, values in without.items():
        assert with_them[reference] == values, f"{reference} moved"


@pytest.mark.parametrize("aggregate", [_JUST_UNDER, _JUST_OVER])
def test_a_candidate_row_contributes_nothing_to_the_retail_threshold_carrier(
    aggregate: float,
) -> None:
    """
    The undrawn candidate rows carry a zero retail-threshold amount.

    Arrange: the boundary book plus the candidate rows.
    Act:     classify and read ``exposure_for_retail_threshold`` on the candidates.
    Assert:  it is 0.0 on both.

    This is the mechanism the invariance rests on, asserted separately from the
    consequence. CRR Art. 147's "total amount owed" is the DRAWN amount, so a
    ``facility_undrawn`` row contributes nothing here. If a later change starts
    counting undrawn commitments in the retail threshold, this test reddens next
    to the reason rather than the invariance test reddening with no explanation.
    """
    # Arrange
    rows = [
        _row("E-NEAR-LIMIT", _SMALL, aggregate),
        _row("E-POOL", _BIG, _POOL),
        *_candidate_rows(),
    ]

    # Act
    frame = ExposureClassifier().classify(_bundle(rows), _config()).all_exposures.collect()

    # Assert
    candidates = frame.filter(pl.col("exposure_type") == "facility_undrawn")
    assert len(candidates) == 2
    assert candidates["exposure_for_retail_threshold"].to_list() == [0.0, 0.0]
