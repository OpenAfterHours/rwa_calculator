"""
P1.366 — a CRR IRB non-named MDB reports on the INSTITUTIONS rows and sheets.

Pipeline position:
    reporting_crr_irb_mdb_portfolio -> PipelineOrchestrator -> COREP + Pillar 3

Key assertion:
    CRR Art. 147(4)(c) (legislation.gov.uk, verbatim): "exposures to multilateral
    development banks which are not assigned a 0 % risk weight under Article 117"
    are assigned to "the class laid down in point (b) of paragraph 2" —
    institutions. The CRR IRB templates are laid out on the Art. 147(2) classes:
    COREP Annex II §3.3.2 reports CR IRB 1-5 separately for "Institutions (point
    (b) of Article 147(2) CRR)", C 09.02 row 0020 is "Institutions — Point (b) of
    Article 147(2) CRR", and C 02.00 rows 0270 / 0330 are the F-IRB / A-IRB
    institutions of-which rows ("See CR IRB template").

    Before the fix the MDB legs carried the Art. 112(1)(d) SA label ``mdb`` onto
    the IRB templates, measured on this portfolio:

    - C 08.01-08.05 emitted an ``mdb`` sheet no published sheet code addresses;
    - C 09.02 row 0020 col 0010 held 3,000,000 (the institution alone) against
      row 0150's 7,500,000, so ``v6052_m`` (ERROR) failed by the MDB exposure;
    - C 02.00 row 0250 exceeded its breakdown by 2,445,247.68 and row 0310 by
      1,394,813.62 (row 0330 read 0.00);
    - Pillar 3 CR7 row 3 read 3,138,330.64 against an F-IRB subtotal of
      5,888,607.80, and CR7-A's F-IRB institutions row 3,000,000 against 5,500,000.

    Every assertion here is ABSOLUTE (a cell against the fixture's own legs, or a
    published identity against its parts), and each fails on the unfixed engine.
    C 09.02 ties to C 08.01 through live rules (``v0420_m`` / ``v0421_m`` /
    ``v0423_m``: C 09.02 r0020 = C 08.01 institutions), and those held BEFORE the
    fix only because both templates dropped the MDB alike — so the tie-outs alone
    could never have told the two states apart (LESSONS C2). C 02.00 r0270 / r0330
    against C 08.01 has no live rule: ``v4246_i`` / ``v4251_i`` are NOT_EVALUATED
    on this run (``sheet_scope_not_closed`` — the CRR C 08 class sheet carries
    both the F-IRB and the A-IRB sheet codes), so only the absolute assertions
    here hold that tie.

    Controls: the genuine institution leg survives (two-leg, LESSONS B5); the IRB
    guaranteed slice stays in its guarantor's ``corporate`` class on the post
    basis; the SA MDB stays on C 07.00's ``mdb`` sheet; and the Basel 3.1 run of
    the same bundle — where PS1/26 Art. 147(3)(f) + 147A(1)(a) route every MDB to
    SA — is a no-op of the projection.

References:
- CRR Art. 147(3)(b), 147(4)(c); CRR Art. 117(2)
- PS1/26 Art. 147(3)(f), 147A(1)(a)
- COREP Annex II §3.3.2; C 09.02 row 0020; C 02.00 rows 0250-0330
- EBA v3.0 rules v6052_m, v0420_m, v4246_i, v4251_i
- tests/fixtures/reporting_crr_irb_mdb_portfolio.py
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl
import pytest
from tests.fixtures.reporting_crr_irb_mdb_portfolio import (
    CRR_INSTITUTION_ORIGIN_LEGS,
    CRR_IRB_MDB_LEGS,
    DRAWN_INST,
    DRAWN_MDB_AIRB,
    DRAWN_MDB_FIRB,
    DRAWN_MDB_GTD,
    DRAWN_MDB_SA,
    GUARANTEED_MDB_GTD,
    LN_INST,
    LN_MDB_AIRB,
    LN_MDB_FIRB,
    LN_MDB_GTD_GUARANTEED,
    LN_MDB_GTD_RETAINED,
    LN_MDB_SA,
    build_reporting_crr_irb_mdb_bundle,
)

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.pillar3.generator import Pillar3Generator

if TYPE_CHECKING:
    from rwa_calc.reporting.corep.generator import COREPTemplateBundle
    from rwa_calc.reporting.pillar3.generator import Pillar3TemplateBundle

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_INSTITUTION = "institution"
_MDB = "mdb"
_CORPORATE = "corporate"

#: Every origin-basis institutions leg's original exposure: the two MDBs, the
#: genuine institution and the whole of the guaranteed MDB loan.
_INSTITUTION_ORIGIN_EXPOSURE = DRAWN_MDB_FIRB + DRAWN_MDB_AIRB + DRAWN_INST + DRAWN_MDB_GTD

#: The same less the slice substituted to the corporate guarantor — the
#: post-substitution institutions exposure.
_INSTITUTION_POST_EXPOSURE = _INSTITUTION_ORIGIN_EXPOSURE - GUARANTEED_MDB_GTD

#: The C 08 templates whose CRR sheets are keyed on the Art. 147 class.
_C08_TEMPLATES = ("c08_01", "c08_02", "c08_03", "c08_04", "c08_05")

_RTOL = 1e-9


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _Run:
    """One pipeline run of the portfolio, with its sealed results and templates."""

    def __init__(self, config: CalculationConfig, framework: str) -> None:
        result = PipelineOrchestrator().run_with_data(build_reporting_crr_irb_mdb_bundle(), config)
        self.results: pl.DataFrame = result.results.collect()
        self.corep: COREPTemplateBundle = COREPGenerator().generate_from_lazyframe(
            result.results,
            framework=framework,
            output_floor_summary=result.output_floor_summary,
        )
        self.pillar3: Pillar3TemplateBundle = Pillar3Generator().generate_from_lazyframe(
            result.results, framework=framework
        )

    def leg(self, reference: str) -> dict[str, object]:
        """The sealed row of one exposure leg."""
        rows = self.results.filter(pl.col("exposure_reference") == reference).to_dicts()
        assert len(rows) == 1, f"{reference}: expected one sealed leg, found {len(rows)}"
        return rows[0]

    def rwea(self, *references: str) -> float:
        """Summed final RWEA of the named legs (CRR: no output floor)."""
        return float(
            self.results.filter(pl.col("exposure_reference").is_in(list(references)))[
                "rwa_final"
            ].sum()
        )


@pytest.fixture(scope="module")
def crr_run() -> _Run:
    """The registered CRR run: IRB permission, the gate's reporting date."""
    return _Run(
        CalculationConfig.crr(
            reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.IRB
        ),
        "CRR",
    )


@pytest.fixture(scope="module")
def b31_run() -> _Run:
    """The same bundle under Basel 3.1 — the negative control."""
    return _Run(
        CalculationConfig.basel_3_1(
            reporting_date=date(2027, 6, 1),
            permission_mode=PermissionMode.IRB,
            enforce_retail_granularity=False,
        ),
        "BASEL_3_1",
    )


# ---------------------------------------------------------------------------
# Fixture adequacy (LESSONS C11) — passes on either engine
# ---------------------------------------------------------------------------


def test_fixture_reaches_the_crr_irb_mdb_population(crr_run: _Run) -> None:
    """The book holds what the assertions below need, or they prove nothing:
    four IRB legs of a non-named MDB (one A-IRB) still labelled ``mdb`` by the
    engine with IRB class ``institution``, a live genuine-institution control, an
    IRB-guarantor slice whose post class is the guarantor's, and an SA MDB."""
    # Arrange / Act
    approaches = {ref: crr_run.leg(ref)["approach_applied"] for ref in CRR_INSTITUTION_ORIGIN_LEGS}
    guaranteed = crr_run.leg(LN_MDB_GTD_GUARANTEED)

    # Assert
    assert approaches == CRR_INSTITUTION_ORIGIN_LEGS
    for ref in CRR_IRB_MDB_LEGS:
        leg = crr_run.leg(ref)
        assert (leg["exposure_class_applied"], leg["exposure_class_irb"]) == (_MDB, _INSTITUTION), (
            f"{ref} no longer carries the Art. 112 label on its IRB leg - the fixture "
            "would not exercise the Art. 147 relabel"
        )
    assert crr_run.leg(LN_INST)["exposure_class_applied"] == _INSTITUTION
    assert guaranteed["is_guarantee_beneficial"] is True
    assert guaranteed["guarantor_approach"] == "irb", (
        "the guarantor no longer routes IRB - the post-twin guard would be an SA "
        "substitution and prove nothing about the IRB branch"
    )
    assert crr_run.leg(LN_MDB_SA)["approach_applied"] == "standardised"


# ---------------------------------------------------------------------------
# The sealed projection
# ---------------------------------------------------------------------------


def test_crr_irb_mdb_legs_report_in_the_institutions_class(crr_run: _Run) -> None:
    """Origin basis: every IRB institutions leg (MDBs included) is ``institution``.
    Post basis: the same, except the IRB-guarantor slice, which is ``corporate``.
    The SA MDB keeps ``mdb`` on both twins."""
    # Arrange / Act
    projection = {
        row["exposure_reference"]: (row["reporting_class_origin"], row["reporting_class"])
        for row in crr_run.results.iter_rows(named=True)
    }

    # Assert
    assert projection == {
        LN_MDB_FIRB: (_INSTITUTION, _INSTITUTION),
        LN_MDB_AIRB: (_INSTITUTION, _INSTITUTION),
        LN_INST: (_INSTITUTION, _INSTITUTION),
        LN_MDB_GTD_GUARANTEED: (_INSTITUTION, _CORPORATE),
        LN_MDB_GTD_RETAINED: (_INSTITUTION, _INSTITUTION),
        LN_MDB_SA: (_MDB, _MDB),
    }


# ---------------------------------------------------------------------------
# COREP
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("template", _C08_TEMPLATES)
def test_c08_emits_the_institutions_sheet_and_no_mdb_sheet(crr_run: _Run, template: str) -> None:
    """``mdb`` is outside the C 08 sheet axis (no published sheet code names it);
    the MDB legs belong on the Art. 147(2)(b) institutions sheet."""
    # Arrange / Act
    sheets = getattr(crr_run.corep, template)

    # Assert
    assert _INSTITUTION in sheets, f"{template}: institutions sheet not emitted"
    assert _MDB not in sheets, f"{template}: emitted an 'mdb' sheet: {sorted(sheets)}"


def test_c08_01_institutions_sheet_holds_every_institution_leg(crr_run: _Run) -> None:
    """C 08.01 r0010 col 0020 (original exposure) on the institutions sheet is the
    whole origin-basis institutions book, MDBs included."""
    # Arrange
    sheet = crr_run.corep.c08_01[_INSTITUTION]

    # Act
    original_exposure = _cell(sheet, "0010", "0020")

    # Assert
    assert original_exposure == pytest.approx(_INSTITUTION_ORIGIN_EXPOSURE, rel=_RTOL)


def test_c09_02_row_0020_holds_the_mdb_legs_and_row_0150_foots(crr_run: _Run) -> None:
    """C 09.02 row 0020 carries every institutions leg on both bases, and row 0150
    = rows 0010 + 0020 + 0030 + 0060 + 0140 (``v6052_m``, ERROR) holds on the
    origin (col 0010) and post-substitution (col 0105) exposure columns."""
    # Arrange
    sheet = crr_run.corep.c09_02["TOTAL"]

    # Act
    origin_0020 = _cell(sheet, "0020", "0010")
    post_0020 = _cell(sheet, "0020", "0105")
    post_0030 = _cell(sheet, "0030", "0105")

    # Assert
    assert origin_0020 == pytest.approx(_INSTITUTION_ORIGIN_EXPOSURE, rel=_RTOL)
    assert post_0020 == pytest.approx(_INSTITUTION_POST_EXPOSURE, rel=_RTOL)
    assert post_0030 == pytest.approx(GUARANTEED_MDB_GTD, rel=_RTOL)
    for column in ("0010", "0105"):
        parts = sum(_cell(sheet, row, column) for row in ("0010", "0020", "0030", "0060", "0140"))
        assert _cell(sheet, "0150", column) == pytest.approx(parts, rel=_RTOL), column


def test_c02_00_firb_institutions_row_holds_the_mdb_rwea(crr_run: _Run) -> None:
    """C 02.00 row 0270 (F-IRB institutions) is the post-substitution F-IRB
    institutions RWEA, so row 0250 strands nothing: 0250 = 0260 + ... + 0300."""
    # Arrange
    c02 = crr_run.corep.c_02_00
    assert c02 is not None
    expected = crr_run.rwea(LN_MDB_FIRB, LN_INST, LN_MDB_GTD_RETAINED)

    # Act
    row_0270 = _cell(c02, "0270", "0010")
    breakdown = sum(
        _cell(c02, row, "0010")
        for row in _present_rows(c02, ("0260", "0270", "0280", "0290", "0300"))
    )

    # Assert
    assert row_0270 == pytest.approx(expected, rel=_RTOL)
    assert _cell(c02, "0250", "0010") == pytest.approx(breakdown, rel=_RTOL)


def test_c02_00_airb_institutions_row_holds_the_mdb_rwea(crr_run: _Run) -> None:
    """C 02.00 row 0330 (A-IRB institutions) carries the A-IRB MDB's RWEA, and with
    no other A-IRB leg in the book it equals row 0310."""
    # Arrange
    c02 = crr_run.corep.c_02_00
    assert c02 is not None

    # Act
    row_0330 = _cell(c02, "0330", "0010")

    # Assert
    assert row_0330 == pytest.approx(crr_run.rwea(LN_MDB_AIRB), rel=_RTOL)
    assert row_0330 > 0.0
    assert _cell(c02, "0310", "0010") == pytest.approx(row_0330, rel=_RTOL)


def test_sa_mdb_stays_on_the_c07_mdb_sheet(crr_run: _Run) -> None:
    """On SA ``mdb`` is the correct Art. 112(1)(d) class: the C 07.00 ``mdb`` sheet
    is emitted and carries the SA MDB's original exposure (col 0010)."""
    # Arrange / Act
    sheets = crr_run.corep.c07_00

    # Assert
    assert _MDB in sheets, f"C 07.00 'mdb' sheet not emitted: {sorted(sheets)}"
    assert _cell(sheets[_MDB], "0010", "0010") == pytest.approx(DRAWN_MDB_SA, rel=_RTOL)


# ---------------------------------------------------------------------------
# Pillar 3
# ---------------------------------------------------------------------------


def test_cr6_institutions_sheet_holds_the_mdb_legs(crr_run: _Run) -> None:
    """CR6 col b (original on-balance-sheet gross exposure) on the institutions
    sheet's Total row is the whole origin-basis institutions book; no ``mdb`` sheet."""
    # Arrange
    sheets = crr_run.pillar3.cr6

    # Act
    total_row = sheets[_INSTITUTION].filter(pl.col("row_ref") == "18")

    # Assert
    assert _MDB not in sheets
    assert total_row["row_name"].item() == "Total"
    assert total_row["b"].item() == pytest.approx(_INSTITUTION_ORIGIN_EXPOSURE, rel=_RTOL)


def test_cr7_institutions_row_is_the_whole_firb_book(crr_run: _Run) -> None:
    """Every F-IRB leg in the book is an institutions leg on the origin basis, so
    CR7 row 3 equals the F-IRB subtotal (row 1)."""
    # Arrange
    cr7 = crr_run.pillar3.cr7
    assert cr7 is not None

    # Act
    row_1 = _cell(cr7, "1", "a")
    row_3 = _cell(cr7, "3", "a")

    # Assert
    assert row_3 == pytest.approx(row_1, rel=_RTOL)
    assert row_3 == pytest.approx(
        crr_run.rwea(LN_MDB_FIRB, LN_INST, LN_MDB_GTD_GUARANTEED, LN_MDB_GTD_RETAINED), rel=_RTOL
    )


def test_cr7a_firb_institutions_row_holds_the_mdb_exposure(crr_run: _Run) -> None:
    """CR7-A F-IRB row 2 (institutions) col a carries every F-IRB institutions leg."""
    # Arrange
    sheet = crr_run.pillar3.cr7a["foundation_irb"]

    # Act
    institutions = _cell(sheet, "2", "a")

    # Assert
    assert institutions == pytest.approx(DRAWN_MDB_FIRB + DRAWN_INST + DRAWN_MDB_GTD, rel=_RTOL)


# ---------------------------------------------------------------------------
# Basel 3.1 negative control
# ---------------------------------------------------------------------------


def test_basel_3_1_routes_every_mdb_to_sa_and_the_projection_is_a_no_op(b31_run: _Run) -> None:
    """PS1/26 Art. 147(3)(f) + 147A(1)(a): every MDB is Standardised, so the origin
    class twin equals the applied class on every row and no MDB reaches C 08."""
    # Arrange
    mdb_rows = b31_run.results.filter(pl.col("cp_entity_type") == _MDB)

    # Act
    approaches = set(mdb_rows["approach_applied"].to_list())
    relabelled = b31_run.results.filter(
        pl.col("reporting_class_origin") != pl.col("exposure_class_applied")
    )

    # Assert
    assert approaches == {"standardised"}
    assert relabelled.height == 0
    assert _MDB not in b31_run.corep.c08_01


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _cell(frame: pl.DataFrame, row: str, column: str) -> float:
    """One cell as a float; a null (an unreported cell) reads as 0.0 for sums."""
    value = frame.filter(pl.col("row_ref") == row)[column].item()
    return 0.0 if value is None else float(value)


def _present_rows(frame: pl.DataFrame, rows: tuple[str, ...]) -> list[str]:
    """The subset of ``rows`` the template emits (CRR C 02.00 has no row 0290)."""
    emitted = set(frame["row_ref"].to_list())
    return [row for row in rows if row in emitted]
