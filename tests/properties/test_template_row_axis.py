"""
Every leg lands in exactly one row of each template's row axis.

Pipeline position:
    portfolio -> PipelineOrchestrator -> sealed ledger
        -> COREPGenerator / Pillar3Generator -> a row axis that must be a PARTITION

What this proves:
A breakdown row set is a partition of its parent total. An (approach, class) pair
the layout has no row for does not raise, does not warn to the error channel, and
does not break any published validation rule — the rules only check rows that
EXIST. The RWEA is counted in the parent and absent from the breakdown, and the
template still looks internally plausible. This is `.claude/LESSONS.md` B6, and
its own warning is heeded here: none of these tests verifies by reading the row
list, because the missing pair is by definition not in it. Every test computes
the RESIDUAL — parent minus the sum of its parts — and requires `0.00`.

The row groups below are taken from the PUBLISHED template layout (the row
sections in ``reporting/corep/templates.py`` and the CR4 row names), never from
the class-to-row maps the generators use. A test written from the same sentence
as the code under test proves nothing (`LESSONS.md` B3).

Findings recorded here as strict xfails are candidate defects, not accepted
behaviour: ``strict=True`` means a fix turns them red and forces this file to be
updated rather than letting a finding quietly evaporate.

References:
- COREP Annex II, C 02.00 / PS1/26 Annex II, OF 02.00: own funds requirements
- CRR Art. 151(4): retail exposures are A-IRB only
- PS1/26 Art. 128: items associated with particularly high risk
- Pillar 3 CR4: standardised exposure and CRM effects
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.reporting.pillar3.templates import get_cr4_rows, get_cr5_rows
from tests.properties.corpus import CORPUS, EVERYTHING
from tests.properties.portfolios import ExposureSpec, corep_bundle, pillar3_bundle, results_df

MONEY_TOLERANCE = 0.005

REGIME_NAMES: tuple[str, ...] = ("CRR", "B31")

# ---------------------------------------------------------------------------
# Row groups, read off the published layout
# ---------------------------------------------------------------------------

#: C 02.00 row 0060 "Of which: Standardised Approach" and its class breakdown.
#: Rows 0070-0211 are the Art. 112(1)(a)-(q) classes in publication order. Under
#: Basel 3.1 row 0131 is an "Of which: specialised lending" SUB-row of 0130, so it
#: is excluded — a partition sums leaves, never a parent and its child.
C02_SA_TOTAL_ROW = "0060"
C02_SA_CLASS_ROWS: tuple[str, ...] = (
    "0070",  # (a) central governments and central banks
    "0080",  # (b) regional governments and local authorities
    "0090",  # (c) public sector entities
    "0100",  # (d) multilateral development banks
    "0110",  # (e) international organisations
    "0120",  # (f) institutions
    "0130",  # (g) corporates
    "0140",  # (h) retail
    "0150",  # (i) secured by mortgages on immovable property
    "0160",  # (j) exposures in default
    "0170",  # (k) items associated with particularly high risk
    "0180",  # (l) covered bonds
    "0190",  # (n) short-term credit assessments
    "0200",  # (o) collective investment undertakings
    "0210",  # (p) equity
    "0211",  # (q) other items
)

#: C 02.00 approach totals and the class rows that break each of them down.
#: Only leaves: 0271/0290/0295-0297 are Basel 3.1 sub-rows of 0250/0260, and
#: 0350/0355/0356/0380-0410 are sub-rows of 0340/0370.
C02_FIRB_TOTAL_ROW = "0240"
C02_FIRB_CLASS_ROWS: tuple[str, ...] = ("0250", "0260")
C02_AIRB_TOTAL_ROW = "0300"
C02_AIRB_CLASS_ROWS: tuple[str, ...] = ("0310", "0330", "0340", "0370")

#: CR4's footing row. Every other row is a class row.
CR4_TOTAL_ROW = "17"

#: CR4 columns and what each discloses. ``f`` is a RATIO (RWEA density), so it is
#: excluded from the footing identity — a density does not add up across rows.
CR4_ADDITIVE_COLUMNS: tuple[str, ...] = ("a", "b", "c", "d", "e")

#: CR5's non-additive columns. Every other column is a risk-weight bucket or an
#: exposure total. ``bc`` is the exposure-weighted average conversion factor.
CR5_NON_ADDITIVE_COLUMNS: tuple[str, ...] = ("bc",)


# ---------------------------------------------------------------------------
# Reproducer portfolios for the recorded findings
# ---------------------------------------------------------------------------

#: An F-IRB corporate whose turnover is below the SME ceiling, so the classifier
#: seals it as ``corporate_sme`` rather than ``corporate``.
FIRB_SME_CORPORATE: tuple[ExposureSpec, ...] = (
    ExposureSpec(
        entity_type="corporate",
        drawn=10_000_000.0,
        external_cqs=None,
        internal_pd=0.01,
        annual_revenue=20_000_000.0,
    ),
)

#: The same shape above the SME ceiling — the control. If this ever fails too,
#: the finding below is broader than "the SME key is missing".
FIRB_LARGE_CORPORATE: tuple[ExposureSpec, ...] = (
    ExposureSpec(
        entity_type="corporate",
        drawn=10_000_000.0,
        external_cqs=None,
        internal_pd=0.01,
        annual_revenue=900_000_000.0,
    ),
)

#: An A-IRB sovereign. CRR-only: PS1/26 removes the IRB approach for sovereign
#: exposures, so under Basel 3.1 this obligor routes standardised instead.
AIRB_SOVEREIGN: tuple[ExposureSpec, ...] = (
    ExposureSpec(
        entity_type="sovereign",
        drawn=10_000_000.0,
        external_cqs=None,
        internal_pd=0.01,
        firm_lgd=0.45,
    ),
)

#: An F-IRB sovereign — same regime caveat.
FIRB_SOVEREIGN: tuple[ExposureSpec, ...] = (
    ExposureSpec(entity_type="sovereign", drawn=10_000_000.0, external_cqs=None, internal_pd=0.01),
)

#: An obligor the classifier seals as ``high_risk`` (PS1/26 Art. 128, 150% RW).
#: Basel-3.1-only: under CRR this entity type resolves to the ``other`` class.
HIGH_RISK_OBLIGOR: tuple[ExposureSpec, ...] = (
    ExposureSpec(entity_type="high_risk", drawn=4_000_000.0, external_cqs=None),
    ExposureSpec(entity_type="corporate", drawn=5_000_000.0, external_cqs=3),
)

#: A STANDARDISED specialised-lending leg: an obligor with SL metadata but no
#: internal rating, so no model_id attaches, the slotting permission cannot apply
#: and the leg routes standardised while keeping the ``specialised_lending`` class.
#: The corporate anchor is there so the Total row is not the single leg.
SA_SPECIALISED_LENDING: tuple[ExposureSpec, ...] = (
    ExposureSpec(
        entity_type="corporate",
        drawn=7_000_000.0,
        external_cqs=None,
        is_specialised_lending=True,
    ),
    ExposureSpec(entity_type="corporate", drawn=5_000_000.0, external_cqs=3),
)

_CORPUS_CASES = [(name, regime) for name in ("sa_broad", "mitigated") for regime in REGIME_NAMES]


# ---------------------------------------------------------------------------
# C 02.00 — the standardised axis
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("portfolio_name", "regime"), _CORPUS_CASES)
def test_c02_sa_class_rows_partition_the_standardised_total(portfolio_name: str, regime: str):
    """Row 0060 equals the sum of the Art. 112(1) class rows beneath it.

    Row 0060 is an independently-computed approach total (a flat sum over the
    standardised population), and rows 0070-0211 are its published breakdown. A
    non-zero residual means standardised RWEA that the total counts and the
    breakdown does not — invisible to every rule written over the class rows.
    """
    # Arrange
    c02 = corep_bundle(CORPUS[portfolio_name], regime).c_02_00
    assert c02 is not None, "C 02.00 was not emitted at all"

    # Act
    residual = _cell(c02, C02_SA_TOTAL_ROW) - sum(_cell(c02, ref) for ref in C02_SA_CLASS_ROWS)

    # Assert
    assert abs(residual) <= MONEY_TOLERANCE, (
        f"{residual:,.2f} of standardised RWEA under {regime} is counted in row "
        f"{C02_SA_TOTAL_ROW} but absent from its class breakdown"
    )


# ---------------------------------------------------------------------------
# C 02.00 — the IRB axis
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("regime", REGIME_NAMES)
def test_c02_firb_class_rows_partition_the_firb_total_for_a_large_corporate(regime: str):
    """The control case: an F-IRB large corporate reaches row 0260."""
    # Arrange
    c02 = corep_bundle(FIRB_LARGE_CORPORATE, regime).c_02_00
    assert c02 is not None

    # Act
    residual = _cell(c02, C02_FIRB_TOTAL_ROW) - sum(_cell(c02, ref) for ref in C02_FIRB_CLASS_ROWS)

    # Assert
    assert abs(residual) <= MONEY_TOLERANCE, (
        f"{residual:,.2f} of F-IRB RWEA stranded outside rows {C02_FIRB_CLASS_ROWS} under {regime}"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "FINDING: an F-IRB obligor sealed as exposure class 'corporate_sme' reaches no C 02.00 "
        "class row. reporting/corep/c02.py::_firb_rows looks up ('foundation_irb', 'corporate') "
        "and ('foundation_irb', 'specialised_lending') only, so row 0260 omits every SME "
        "corporate while row 0240 counts it. Same shape on the A-IRB side (row 0340). The "
        "module docstring records the 2026-08-01 fix that re-keyed the SA map onto real "
        "ExposureClass values and says it was 'identical for IRB rows' — it was not; the IRB "
        "half is still keyed on a hand-written tuple list. LESSONS.md B6 / B2."
    ),
)
@pytest.mark.parametrize("regime", REGIME_NAMES)
def test_c02_firb_sme_corporate_reaches_a_class_row(regime: str):
    """An F-IRB SME corporate's RWEA appears in the F-IRB class breakdown."""
    # Arrange
    c02 = corep_bundle(FIRB_SME_CORPORATE, regime).c_02_00
    assert c02 is not None

    # Act
    residual = _cell(c02, C02_FIRB_TOTAL_ROW) - sum(_cell(c02, ref) for ref in C02_FIRB_CLASS_ROWS)

    # Assert
    assert abs(residual) <= MONEY_TOLERANCE, (
        f"{residual:,.2f} of F-IRB SME RWEA stranded outside rows {C02_FIRB_CLASS_ROWS} "
        f"under {regime}"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "FINDING: reporting/corep/c02.py:822 reads ('advanced_irb', 'central_government') from "
        "the sealed class map, but no ExposureClass member has the value 'central_government' — "
        "the sovereign class is 'central_govt_central_bank'. Row 0310 'A-IRB - Central "
        "governments and central banks' is therefore ALWAYS zero, and the RWEA strands out of "
        "the A-IRB breakdown while row 0300 counts it. A phantom map key that zero-fills, "
        "exactly LESSONS.md B2. CRR only: PS1/26 removes IRB for sovereigns."
    ),
)
def test_c02_airb_sovereign_reaches_its_class_row():
    """An A-IRB sovereign's RWEA appears in row 0310, the row named for it."""
    # Arrange
    c02 = corep_bundle(AIRB_SOVEREIGN, "CRR").c_02_00
    assert c02 is not None

    # Act
    residual = _cell(c02, C02_AIRB_TOTAL_ROW) - sum(_cell(c02, ref) for ref in C02_AIRB_CLASS_ROWS)

    # Assert
    assert abs(residual) <= MONEY_TOLERANCE, (
        f"{residual:,.2f} of A-IRB sovereign RWEA stranded outside rows {C02_AIRB_CLASS_ROWS}; "
        f"row 0310 carries {_cell(c02, '0310'):,.2f}"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "FINDING: this repository's C 02.00 F-IRB row list has NO central-government row in "
        "either regime (CRR_C02_00_ROW_SECTIONS / B31_C02_00_ROW_SECTIONS give 0250 institutions "
        "and 0260 corporates only), so an F-IRB sovereign's RWEA is counted in row 0240 and "
        "appears in no breakdown row. The pair is legitimate under CRR Art. 147 — a firm may hold "
        "IRB permission for sovereign exposures — so this is a MISSING ROW rather than the "
        "mis-keying the sibling findings describe. "
        "CONFIDENCE CAVEAT: whether the PUBLISHED COREP layout also omits the row is UNVERIFIED. "
        "reporting/corep/templates.py is a hand-maintained Python list and nobody here can read "
        "docs/assets/*.pdf (no pdftoppm — LESSONS.md A2), so 'the published template has no such "
        "row' is an assumption, not a finding. If the published layout HAS the row, this is our "
        "defect and the fix is additive. Check the layout before deciding either way."
    ),
)
def test_c02_firb_sovereign_reaches_a_class_row():
    """An F-IRB sovereign's RWEA appears in the F-IRB class breakdown."""
    # Arrange
    c02 = corep_bundle(FIRB_SOVEREIGN, "CRR").c_02_00
    assert c02 is not None

    # Act
    residual = _cell(c02, C02_FIRB_TOTAL_ROW) - sum(_cell(c02, ref) for ref in C02_FIRB_CLASS_ROWS)

    # Assert
    assert abs(residual) <= MONEY_TOLERANCE, (
        f"{residual:,.2f} of F-IRB sovereign RWEA stranded outside rows {C02_FIRB_CLASS_ROWS}"
    )


# ---------------------------------------------------------------------------
# Pillar 3 CR4 — the standardised class axis
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("portfolio_name", "regime"), _CORPUS_CASES)
def test_pillar3_sa_class_rows_foot_to_the_total_row(portfolio_name: str, regime: str):
    """CR4 and CR5 Total rows equal the sum of their class rows, in every amount.

    Both Total rows are computed over the whole standardised population; the class
    rows are computed per class, off the shared ``SA_DISCLOSURE_CLASSES`` axis. The
    identity is internal to one published template, so a residual is a disclosure
    that does not add up on its own face.
    """
    # Arrange
    bundle = pillar3_bundle(CORPUS[portfolio_name], regime)
    assert bundle.cr4 is not None, "CR4 was not emitted at all"
    assert bundle.cr5 is not None, "CR5 was not emitted at all"

    # Act
    residuals = {
        "cr4": _cr4_residuals(bundle.cr4),
        "cr5": _row_axis_residuals(bundle.cr5, CR5_NON_ADDITIVE_COLUMNS),
    }

    # Assert
    broken = {name: gaps for name, gaps in residuals.items() if gaps}
    assert broken == {}, f"Pillar 3 rows do not foot to the Total row under {regime}: {broken}"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "FINDING: under CRR a STANDARDISED specialised-lending leg reaches no Pillar 3 CR4/CR5 "
        "class row. CRR_CR4_ROWS is SA_DISCLOSURE_CLASSES verbatim, and that list never maps "
        "'specialised_lending' to a row; the Basel 3.1 layout adds row 7a and catches it, so the "
        "IDENTICAL portfolio ties out under B3.1 and strands under CRR. Measured: 7,000,000 of "
        "exposure and 7,000,000 of RWEA counted in the CR4 Total row and absent from every class "
        "row. Reachable with ordinary inputs — an obligor with specialised-lending metadata and "
        "no internal rating cannot attach a slotting permission, so it routes standardised while "
        "keeping the SL class."
    ),
)
def test_sa_specialised_lending_leg_reaches_a_pillar3_class_row():
    """An SA specialised-lending leg appears in the CR4 and CR5 breakdowns under CRR."""
    # Arrange
    bundle = pillar3_bundle(SA_SPECIALISED_LENDING, "CRR")
    assert bundle.cr4 is not None
    assert bundle.cr5 is not None

    # Act
    residuals = {
        "cr4": _cr4_residuals(bundle.cr4),
        "cr5": _row_axis_residuals(bundle.cr5, CR5_NON_ADDITIVE_COLUMNS),
    }

    # Assert
    broken = {name: gaps for name, gaps in residuals.items() if gaps}
    assert broken == {}, (
        f"Pillar 3 rows do not foot to the Total row for an SA specialised-lending leg: {broken}"
    )


def test_sa_specialised_lending_leg_reaches_a_pillar3_class_row_under_basel_3_1():
    """The control: the same portfolio DOES tie out under Basel 3.1, via row 7a.

    Proves the CRR failure above is a layout gap in one regime rather than a
    classifier or ledger defect — the leg, the amounts and the class are identical.
    """
    # Arrange
    bundle = pillar3_bundle(SA_SPECIALISED_LENDING, "B31")
    assert bundle.cr4 is not None
    assert bundle.cr5 is not None

    # Act
    residuals = {
        "cr4": _cr4_residuals(bundle.cr4),
        "cr5": _row_axis_residuals(bundle.cr5, CR5_NON_ADDITIVE_COLUMNS),
    }

    # Assert
    broken = {name: gaps for name, gaps in residuals.items() if gaps}
    assert broken == {}, f"the Basel 3.1 control no longer ties out either: {broken}"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "FINDING: a leg sealed as exposure class 'high_risk' (PS1/26 Art. 128, 150% RW) reaches "
        "NO Pillar 3 class row under Basel 3.1, on CR4 AND CR5. Root cause: "
        "reporting/pillar3/templates.py::SA_DISCLOSURE_CLASSES maps row 11 'Items associated "
        "with particularly high risk' to an EMPTY tuple, so no sealed class ever matches it. "
        "Both templates' Total rows are computed over the whole standardised population and DO "
        "count the leg, so neither adds up on its own face: measured 4,000,000 of exposure and "
        "6,000,000 of RWEA missing from CR4's breakdown, and the whole 4,000,000 missing from "
        "CR5's 150% risk-weight column. The same portfolio reaches its C 07.00 'high_risk' sheet "
        "correctly, so the ledger is right and the Pillar 3 row axis has not kept up. CRR is "
        "unaffected: there this obligor resolves to 'other', which HAS a row."
    ),
)
def test_high_risk_leg_reaches_a_pillar3_class_row():
    """A high-risk-item leg's exposure and RWEA appear in the CR4 and CR5 breakdowns."""
    # Arrange
    bundle = pillar3_bundle(HIGH_RISK_OBLIGOR, "B31")
    assert bundle.cr4 is not None
    assert bundle.cr5 is not None

    # Act
    residuals = {
        "cr4": _cr4_residuals(bundle.cr4),
        "cr5": _row_axis_residuals(bundle.cr5, CR5_NON_ADDITIVE_COLUMNS),
    }

    # Assert
    broken = {name: gaps for name, gaps in residuals.items() if gaps}
    assert broken == {}, (
        f"Pillar 3 rows do not foot to the Total row for a high-risk obligor: {broken}"
    )


def test_the_pillar3_sa_row_axis_is_a_partition():
    """No exposure class is claimed by two rows of the same template.

    The footing tests above sum every non-Total row as if it were a leaf. That is
    only sound while the row set is a PARTITION — if a parent row and an "of which"
    sub-row both claimed a class, the sum would double-count it and the footing
    identity would fail on a sound template (`LESSONS.md` E4, the hierarchical PD
    scale, in a new place). This asserts the assumption rather than relying on it.

    It currently holds only narrowly: Basel 3.1 row 7a is LABELLED
    "Of which: specialised lending" but row 7 "Corporates" does not include the
    ``specialised_lending`` class, so 7a is that class's sole home rather than a
    subset of its parent. Worth knowing — the label and the keying disagree.
    """
    # Arrange
    claims: dict[str, list[str]] = {}
    for framework in ("CRR", "BASEL_3_1"):
        for template, rows in (
            ("cr4", get_cr4_rows(framework)),
            ("cr5", get_cr5_rows(framework)),
        ):
            for row in rows:
                for exposure_class in row.exposure_classes:
                    claims.setdefault(f"{framework}/{template}/{exposure_class}", []).append(
                        row.ref
                    )

    # Act
    contested = {key: refs for key, refs in claims.items() if len(refs) > 1}

    # Assert
    assert contested == {}, (
        f"an exposure class is claimed by more than one row, so summing the non-Total rows "
        f"double-counts it: {contested}"
    )


@pytest.mark.parametrize("regime", REGIME_NAMES)
def test_every_standardised_leg_reaches_a_c07_sheet(regime: str):
    """No standardised leg's exposure value is missing from the C 07.00 sheet set.

    C 07.00 is published one sheet per Art. 112(1) class. A class with no sheet
    code resolves to no bundle key and its exposure simply never appears — which
    reads exactly like a firm that holds none. The residual distinguishes the two.

    Run over the WHOLE corpus at once plus the high-risk obligor, because this is
    a coverage question: the residual can only see a class the portfolio contains,
    so the widest available book is the right subject.
    """
    # Arrange
    portfolio = EVERYTHING + HIGH_RISK_OBLIGOR
    df = results_df(portfolio, regime)
    expected = float(
        df.filter(pl.col("reporting_approach") == "standardised")["ead_final"].fill_null(0.0).sum()
    )

    # Act
    sheets = corep_bundle(portfolio, regime).c07_00 or {}
    published = sum(_c07_total_exposure_value(frame) for frame in sheets.values())

    # Assert
    assert abs(published - expected) <= MONEY_TOLERANCE, (
        f"{expected - published:,.2f} of standardised exposure value reaches no C 07.00 sheet "
        f"under {regime}"
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _cell(frame: pl.DataFrame, row_ref: str, column: str = "0010") -> float:
    """One C 02.00 cell, with an unpublished cell read as zero."""
    row = frame.filter(pl.col("row_ref") == row_ref)
    if row.height == 0:
        return 0.0
    value = row[column][0]
    return float(value) if value is not None else 0.0


def _cr4_residuals(cr4: pl.DataFrame) -> dict[str, float]:
    """``{column: Total - sum(class rows)}`` for every CR4 column where it is non-zero."""
    return _row_axis_residuals(
        cr4, non_additive=tuple(c for c in cr4.columns if c not in CR4_ADDITIVE_COLUMNS)
    )


def _row_axis_residuals(frame: pl.DataFrame, non_additive: tuple[str, ...]) -> dict[str, float]:
    """``{column: Total - sum(class rows)}`` over every additive numeric column.

    ``non_additive`` names the columns that are ratios rather than amounts (a
    density, a weighted-average conversion factor); a ratio does not add up across
    rows, so including one would manufacture a residual on a sound template.
    """
    body = frame.filter(pl.col("row_ref") != CR4_TOTAL_ROW)
    total = frame.filter(pl.col("row_ref") == CR4_TOTAL_ROW)
    residuals: dict[str, float] = {}
    for column, dtype in frame.schema.items():
        if column in non_additive or dtype not in (pl.Float32, pl.Float64):
            continue
        published_total = total[column][0] if total.height else None
        residual = float(published_total or 0.0) - float(body[column].fill_null(0.0).sum())
        if abs(residual) > MONEY_TOLERANCE:
            residuals[column] = residual
    return residuals


def _c07_total_exposure_value(frame: pl.DataFrame) -> float:
    """Row 0010 ("Total exposures"), column 0200 ("Exposure value") of one sheet."""
    row = frame.filter(pl.col("row_ref") == "0010")
    if row.height == 0:
        return 0.0
    value = row["0200"][0]
    return float(value) if value is not None else 0.0
