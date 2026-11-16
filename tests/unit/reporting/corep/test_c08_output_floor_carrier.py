"""Every Basel 3.1 IRB template reports the own-approach RWEA, never the floor's add-on.

The output floor is an entity-level maximum. PS1/26 Art. 92(2A)(a): "TREA = max
{U-TREA; x . S-TREA + OF-ADJ} where ... U-TREA = the un-floored total risk
exposure amount ... calculated in accordance with paragraph 3", and Art. 92(3)(a)
makes the credit-risk part of U-TREA "the risk-weighted exposure amounts for
credit risk ... calculated in accordance with Title II of Part Three" — the
amount each exposure's own approach produces. Nothing in the rules allocates the
floor to an exposure, a class or a template row.

The engine nonetheless spreads a binding floor's shortfall pro rata over
``rwa_final`` on every floor-eligible leg (``engine/aggregator/_floor.py``) and
keeps the un-floored figure on ``rwa_pre_floor``. The templates must read the
latter wherever it is sealed:

- PS1/26 Annex II p.112, OF 08.01 col 0260: "Institutions shall report the value
  reported in column 0251 and adjust for values reported in columns 0252 to
  0254" — the three Art. 153(5A) / 154(4A) adjustments, none of which is the
  floor. So col 0260 = 0251 + 0252 + 0253 + 0254, and the floor has no column.
- The taxonomy makes each OF 08.01 class sheet's r0010 c0260 ONE data point with
  the un-floored OF 02.00 class row (e.g. OF02.00 r0297 c0010 == OF08.01 z0012
  r0010 c0260), so the two cannot hold different values (STR007).
- The floor's one home is OF 02.00 row 0010 column 0030 (Annex II p.29).

The book here is ``irb_book`` in the engine's binding-floor shape: every
modelled leg carries ``rwa_final = own + ADD_ON`` and ``rwa_pre_floor = own``.
Each figure is stated from the leg list, never from the generator's grouping.

References:
- PRA PS1/26 Appendix 1, Art. 92(2A) and 92(3) (pp.13-14)
- PRA PS1/26 Annex II, OF 08.01 cols 0251-0260 (pp.111-112), OF 08.03 col 0090
  (p.121), OF 08.04 col 0010 (p.123), OF 08.06 col 0080 (p.129), OF 08.07 col
  0060 (p.131), OF 02.00 row 0010 (p.29)
"""

from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from rwa_calc.reporting.corep.generator import COREPTemplateBundle
from rwa_calc.reporting.corep.templates import C08_03_PD_PARENT_REFS
from rwa_calc.reporting.filing.canonical import (
    FILING_MODULE,
    FILING_TAXONOMY,
    build_canonical_return,
)
from rwa_filer.model import ReturnHeader
from rwa_filer.release import resolve_release
from rwa_filer.validate.returns import validate_return
from tests.fixtures.recon_ledger import LedgerShimCorepGenerator
from tests.unit.reporting.corep._c02_frames import MODELLED_LEGS, SLOTTING_LEGS, Leg, own
from tests.unit.reporting.corep._irb_sheet_frames import (
    EXPECTED_SHEET_CODE,
    FRAMEWORK,
    cell,
    irb_book,
    legs_on,
    sheet_key,
)

#: The add-on the engine would put on every modelled leg's ``rwa_final``.
ADD_ON = 1_000.0

#: Every published OF 08.01 class sheet the book reaches.
CLASS_CODES = sorted(set(EXPECTED_SHEET_CODE.values()))

#: The modelled legs C 08.04 counts (it reads the non-slotting IRB book).
NON_SLOTTING_LEGS: tuple[Leg, ...] = tuple(
    leg for leg in MODELLED_LEGS if leg.approach != "slotting"
)

HEADER = ReturnHeader("5493001KJTIIGC8Y1R12", dt.date(2027, 3, 31), FILING_MODULE)


def _bound_book(add_on: float = ADD_ON) -> pl.LazyFrame:
    """``irb_book`` as the engine seals it when the output floor binds, with a
    slotting category on the slotting legs so OF 08.06 has rows to report."""
    return irb_book(floor_add_on=add_on, adjustment_columns=True).with_columns(
        pl.when(pl.col("approach_applied") == "slotting")
        .then(pl.lit("strong"))
        .otherwise(pl.lit(None, dtype=pl.String))
        .alias("slotting_category")
    )


def _generate(frame: pl.LazyFrame, prior: pl.LazyFrame | None = None) -> COREPTemplateBundle:
    return LedgerShimCorepGenerator().generate_from_lazyframe(
        frame, framework=FRAMEWORK, previous_period_results=prior
    )


@pytest.fixture(scope="module")
def bound() -> COREPTemplateBundle:
    # Arrange: adequacy first — without an add-on on every modelled leg the
    # book cannot tell the two carriers apart and every test below is vacuous.
    frame = _bound_book()
    ledger = frame.collect()
    add_on = float((ledger["rwa_final"] - ledger["rwa_pre_floor"]).sum())
    assert add_on == pytest.approx(ADD_ON * len(MODELLED_LEGS)), (
        "the book carries no floor add-on - it cannot distinguish rwa_final from rwa_pre_floor"
    )
    # Act
    return _generate(frame)


@pytest.mark.parametrize("code", CLASS_CODES)
def test_rwea_after_adjustments_is_the_own_approach_amount(
    bound: COREPTemplateBundle, code: str
) -> None:
    """OF 08.01 r0010 c0260 is Art. 92(3)(a) RWEA — the same data point as the
    un-floored OF 02.00 class row."""
    # Arrange
    expected = own(legs_on(code))
    assert expected > 0.0, f"sheet {code} has no legs - the assertion would be vacuous"
    # Act
    sheet = bound.c08_01[sheet_key(code)]
    # Assert
    assert cell(sheet, "0010", "0260") == pytest.approx(expected)


@pytest.mark.parametrize("code", CLASS_CODES)
def test_rwea_after_adjustments_is_pre_adjustments_plus_the_three_adjustments(
    bound: COREPTemplateBundle, code: str
) -> None:
    """Annex II p.112: col 0260 = col 0251 adjusted for cols 0252-0254, and
    nothing else (``boe_b0751``)."""
    # Act
    sheet = bound.c08_01[sheet_key(code)]
    parts = sum(cell(sheet, "0010", col) or 0.0 for col in ("0251", "0252", "0253", "0254"))
    # Assert
    assert cell(sheet, "0010", "0260") == pytest.approx(parts)


def test_the_slotting_row_reports_pre_adjustment_rwea_unfloored(
    bound: COREPTemplateBundle,
) -> None:
    """Slotting legs carry no ``rwa_pre_adjustments``; col 0251 falls back to the
    leg's own RWEA, and that fallback must be the own-approach one too."""
    # Act
    sheet = bound.c08_01[sheet_key("0010")]
    # Assert
    assert cell(sheet, "0080", "0251") == pytest.approx(own(SLOTTING_LEGS))
    assert cell(sheet, "0080", "0260") == pytest.approx(own(SLOTTING_LEGS))


def test_the_obligor_grades_add_up_to_the_grade_row(bound: COREPTemplateBundle) -> None:
    """OF 08.02 col 0260 summed over the grades is OF 08.01 r0070 col 0260
    (``boe_b0752`` / ``boe_b0814``). Detects a carrier fixed on OF 08.01 but not on
    OF 08.02 (green before and after the fix by design)."""
    # Arrange
    compared = 0
    for code in CLASS_CODES:
        key = sheet_key(code)
        if key not in bound.c08_02:
            continue
        compared += 1
        # Act
        grades = float(bound.c08_02[key]["0260"].fill_null(0.0).sum())
        # Assert
        assert grades == pytest.approx(cell(bound.c08_01[key], "0070", "0260") or 0.0), code
    assert compared > 0, "no OF 08.02 sheet was compared"


@pytest.mark.parametrize("code", CLASS_CODES)
def test_the_obligor_grades_add_up_to_the_own_approach_amount(
    bound: COREPTemplateBundle, code: str
) -> None:
    """OF 08.02 col 0260 (Annex II p.118: the OF 08.01 instructions) on its own."""
    # Arrange
    key = sheet_key(code)
    if key not in bound.c08_02:
        pytest.skip(f"sheet {code} has no OF 08.02 (slotting-only)")
    # Act
    grades = float(bound.c08_02[key]["0260"].fill_null(0.0).sum())
    # Assert
    assert grades == pytest.approx(own(legs_on(code, NON_SLOTTING_LEGS)))


@pytest.mark.parametrize("code", ["0012", "0011", "0015"])
def test_the_pd_bands_add_up_to_the_own_approach_amount(
    bound: COREPTemplateBundle, code: str
) -> None:
    """OF 08.03 col 0090 is "the risk-weighted exposure amount calculated in
    accordance with Article 153" (p.121); the leaf bands sum to it."""
    # Act
    sheet = bound.c08_03[sheet_key(code)]
    leaves = sheet.filter(~pl.col("row_ref").is_in(sorted(C08_03_PD_PARENT_REFS)))
    # Assert
    assert float(leaves["0090"].fill_null(0.0).sum()) == pytest.approx(own(legs_on(code)))


def test_the_slotting_template_reports_the_own_approach_amount(
    bound: COREPTemplateBundle,
) -> None:
    """OF 08.06 col 0080 (p.129: "See OF CR IRB 1 instructions for column 0260"):
    the two maturity Total rows of every SL-type sheet add up to the slotting legs."""
    # Act
    reported = sum(
        float(sheet.filter(pl.col("row_ref").is_in(["0110", "0120"]))["0080"].fill_null(0.0).sum())
        for sheet in bound.c08_06.values()
    )
    # Assert
    assert reported == pytest.approx(own(SLOTTING_LEGS))


def test_scope_of_use_rwea_is_the_own_approach_amount(bound: COREPTemplateBundle) -> None:
    """OF 08.07 cols 0060 / 0150 (p.131) on the total row."""
    # Act / Assert
    assert cell(bound.c08_07, "0260", "0060") == pytest.approx(own(MODELLED_LEGS))
    assert cell(bound.c08_07, "0260", "0150") == pytest.approx(own(MODELLED_LEGS))


def test_geographical_breakdown_rwea_is_the_own_approach_amount(
    bound: COREPTemplateBundle,
) -> None:
    """OF 09.02 col 0110 on the TOTAL sheet's total row."""
    # Act
    sheet = bound.c09_02["TOTAL"]
    # Assert
    assert cell(sheet, "0150", "0110") == pytest.approx(own(MODELLED_LEGS))


def test_flow_statement_is_on_the_own_approach_amount_in_both_periods() -> None:
    """C 08.04 (p.123: "Total risk-weighted exposure amount for credit risk
    calculated under the IRB approach") — closing, opening and the residual."""
    # Arrange: the floor binds in both periods, by different amounts.
    bundle = _generate(_bound_book(1_000.0), prior=_bound_book(400.0))
    sheets = bundle.c08_04.values()
    # Act
    closing = sum(cell(f, "0090", "0010") or 0.0 for f in sheets)
    opening = sum(cell(f, "0010", "0010") or 0.0 for f in sheets)
    other = sum(cell(f, "0080", "0010") or 0.0 for f in sheets)
    # Assert
    assert closing == pytest.approx(own(NON_SLOTTING_LEGS))
    assert opening == pytest.approx(own(NON_SLOTTING_LEGS))
    assert other == pytest.approx(0.0)


def test_flow_statement_opens_on_a_prior_period_the_floor_never_ran_on() -> None:
    """A prior period with no ``rwa_pre_floor`` (a CRR prior at the 1 January 2027
    transition, or an entity outside the floor's scope) still opens on its own
    RWEA — the current period's carrier must not be imposed on it."""
    # Arrange
    prior = _bound_book(0.0).drop("rwa_pre_floor")
    bundle = _generate(_bound_book(1_000.0), prior=prior)
    # Act
    opening = [cell(f, "0010", "0010") for f in bundle.c08_04.values()]
    # Assert
    assert None not in opening, "the opening RWEA went null: the prior has no rwa_pre_floor"
    assert sum(o or 0.0 for o in opening) == pytest.approx(own(NON_SLOTTING_LEGS))


def test_flow_statement_opens_on_the_prior_own_amount_when_only_the_prior_was_floored() -> None:
    """The mirror case: the current period has no ``rwa_pre_floor`` (the floor never
    ran) and the prior one did and bound. The opening is still the prior's own RWEA."""
    # Arrange
    current = _bound_book(0.0).drop("rwa_pre_floor")
    bundle = _generate(current, prior=_bound_book(400.0))
    # Act
    opening = sum(cell(f, "0010", "0010") or 0.0 for f in bundle.c08_04.values())
    # Assert
    assert opening == pytest.approx(own(NON_SLOTTING_LEGS))


def test_a_ledger_the_floor_never_ran_on_reports_rwa_final() -> None:
    """With no ``rwa_pre_floor`` sealed (CRR, or an entity outside the floor's
    scope) no floor was applied, so ``rwa_final`` IS the own-approach figure and
    the templates read it. A frame that genuinely omits the column (LESSONS B1)."""
    # Arrange
    frame = _bound_book().drop("rwa_pre_floor")
    code = "0012"
    # Act
    bundle = _generate(frame)
    # Assert
    expected = own(legs_on(code)) + ADD_ON * len(legs_on(code))
    assert cell(bundle.c08_01[sheet_key(code)], "0010", "0260") == pytest.approx(expected)


def test_no_of08_data_point_is_filed_with_two_values(bound: COREPTemplateBundle) -> None:
    """A filed return holds one fact per data point; each OF 08.01 class sheet's
    r0010 c0260 is the same data point as an OF 02.00 class row."""
    # Arrange
    pack = resolve_release(FILING_MODULE, FILING_TAXONOMY).pack
    canonical = build_canonical_return(bound, HEADER, pack=pack).canonical
    # Act
    twice = [
        (finding.subject, finding.actual)
        for finding in validate_return(canonical, pack).structure
        if finding.code == "STR007" and finding.subject.startswith("OF08")
    ]
    # Assert
    assert twice == []
