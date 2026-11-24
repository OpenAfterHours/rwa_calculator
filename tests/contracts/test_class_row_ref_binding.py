"""
Each row ref a module-level reporting class map declares is a row of its reader's template.

Pipeline position:
    corep/templates.py, corep/c02_rows.py, corep/sheet_labels.py,
    pillar3/templates.py and pillar3/cr7.py (class maps and row lists, read as
    constants)
        -> these assertions

Key responsibilities:
- The REFS half of the class-map contract: bind each map between exposure
  classes and row refs to the ONE template that reads it, per regime, and
  require every ref it declares to be a row that template's reader actually
  fills. Two shapes are bound. CLASS-keyed, class -> ref:
  ``C02_00_SA_CLASS_MAP``. ROW-keyed, ref -> the classes that row aggregates:
  the C 08.07 unions, ``CMS2_SA_CLASS_MAP`` and the CR7 row predicates. The
  KEYS half (every class key is an ``ExposureClass`` member or a C 07.00 sheet
  key) is ``tests/conformance/test_reporting_class_keys.py``, by estate-wide
  discovery; it is not rebuilt here.
- The converse, for the two row sets meant to be bound row by row: each
  C 02.00 / OF 02.00 Article 112(1) class row is reached by some class, and
  each CR7 row, total included, has a predicate. A row left out renders empty
  (C 02.00) or null (CR7).
- Require the class maps on the SHEET (z) axis to carry no row ref at all: on
  that axis a class gets a sheet, not a row.
- Keep the explicit tables complete. Two inventories scan every MODULE-LEVEL
  mapping in ``rwa_calc.reporting``: one for class-keyed maps, one for
  row-keyed maps whose values carry a class. Each map found must be classified
  here -- bound to its template, on the sheet axis, or excused with its reason.
  A map in a BOUND table must also name the test that binds it (``BOUND_BY``):
  listing it is not a check by itself. A map nested inside another constant,
  or built inside a function, is not scanned.
- Prove each check can fail, on planted maps.

What else sees these defects. Measured by mutating the real maps in memory
(never on disk) and running ``tests/unit/reporting/corep/test_c02_00*.py``,
``test_of02_01``, ``test_templates``, every ``test_c08*`` unit file,
``tests/contracts/test_c07_art112_sheet_axis``, ``test_of02_published_cells``,
``test_c02_sa_ccr_approach_sync``, every ``*c08*`` / ``*of08*`` contract file,
``tests/conformance/test_reporting_class_keys`` and ``tests/unit/reporting/pillar3``.
Files outside that set were not run, except where a bullet names its own set:
- C 02.00: CIU (a single-class letter) moved to "0205", to CRR slot row 0190
  or to OF 02.00 slot row 0131 IS caught behaviourally, in both regimes. CRR:
  the EBA identity ``v0207_m`` (r0060 = the sum of the class rows),
  ``test_c02_00_published_rows::TestCrrStructure::test_the_published_identity_holds[v0207_m]``.
  Basel 3.1: ``test_of02_published_cells::test_no_cell_of_a_computed_row_is_left_empty``,
  which finds row 0200 left empty. Both catch a misroute only while
  ``tests/unit/reporting/corep/_c02_frames.py`` carries a leg of the moved
  class; it carries one per SA class today. So this file's unique C 02.00
  coverage is the structural form. It holds for any class, including one no
  frame carries, and it names the class and the reason.
- C 08.07: re-keying an EXISTING union (CRR 0090 -> 0095, OF 08.07 0210 -> 0215)
  is caught behaviourally by ``test_c08_07`` and, for OF 08.07, by
  ``test_c08_dpm_conformance``. A union added on a row that binds its own class
  (CRR 0050, OF 08.07 0180) is never read and changes no output, so only the
  check here sees it.
- CMS2: moving a ``CMS2_SA_CLASS_MAP`` key off its row (0043 -> 0044,
  0053 -> 0055) is seen by the check here and by nothing else in the set:
  ``cms2.py`` falls back to the row's own classes, which equal the moved entry.
- CR7, measured over ``tests/unit/reporting/pillar3``, ``tests/unit/test_pillar3.py``,
  ``tests/unit/reporting/test_lineage.py`` and the three
  ``tests/acceptance/reporting`` files that read CR7 (``test_lineage_tieout``,
  ``test_funded_protection_coverage``, ``test_irb_shapes_template_coverage``):
  moving the Basel 3.1 row 6 predicate (A-IRB retail) to "16" is seen by the
  checks here and by nothing else in that set, although it empties a cell the
  set computes: row 6 column b of ``test_cr6_cr7._make_mixed_data`` falls from
  2,700.0 to null. Moving the CRR row 8 predicate to "18" is also caught by one
  value test,
  ``test_cr6_cr7::TestCR7Generation::test_cr7_crr_row8_is_airb_retail_mortgage``.
  DELETING either predicate empties the same cell (CRR row 8: 1,500.0 to null)
  and leaves no key to check, so only ``test_every_cr7_row_has_a_predicate``
  here sees the Basel 3.1 deletion; the CRR one is also caught by that value
  test. A plant of either kind must rebuild ``cr7._CR7_SPECS``, which is built
  from the maps at import.
- Sheet axis: the retired shape planted on the Pillar 3 class axis,
  ``IRB_EXPOSURE_CLASSES['corporate']`` -> "0030" or -> "7", is seen by the
  check here and by nothing else in the set. The tuple form
  ``("0030", "Corporates")`` is also caught, incidentally, by
  ``test_cr9_cr10::TestCR9ExcelExport::test_export_includes_cr9_sheets``.
  Before that map was classified and ``_ROW_REF`` widened, all three plants
  left this file green.

Why a per-template binding and never "the ref exists in SOME template". The
row-code namespace is dense: the retired IRB class map put ``corporate`` on
"0030" and its retired SA twin put ``equity`` on "0110", both on the sheet axis,
and both codes are live rows today -- 0030 is C 08.01 "Off balance sheet items
subject to credit risk", 0110 is C 02.00 "International Organisations". A check
that a ref exists somewhere passes the very defect it was asked to catch;
``test_the_c02_check_is_not_the_some_live_template_form`` and
``test_the_sheet_axis_check_rejects_a_planted_row_ref`` pin that.

Why a value that is wrong is silent at runtime (``.claude/LESSONS.md`` B2, B9):
- ``C02_00_SA_CLASS_MAP`` -> C 02.00 / OF 02.00 rows 0070-0211. COREP Annex II
  §1.3.1 and PS1/26 Annex II §1.3.1 mark each of them "See CR SA template", one
  row per Article 112(1) class. ``c02.py::_sa_class_rows`` accumulates by ref.
  ``_cells`` writes the class rows first and then lets every ``Slot`` overwrite
  a colliding ref. ``_build_rows`` lays out published rows only. So a ref that
  names no row is dropped, and one that collides with a slot loses to it. Only
  the first leaves a trace, the row 0060 residual WARNING of
  ``c02.py::_warn_if_a_breakdown_strands``. A slot collision leaves NONE: that
  net counts every class-row amount whose ref is in the layout, and a slot's
  row is in the layout. Measured on the CRR book of
  ``tests/unit/reporting/corep/_c02_frames.py``: CIU -> "0205" logs a 30.00
  residual on row 0060; CIU -> "0190" (the short-term slot) leaves row 0200
  empty and row 0190 at 0.0, and logs no warning.
- ``CRR_C08_07_ROW_UNIONS`` / ``B31_C08_07_ROW_UNIONS`` -> C 08.07 / OF 08.07.
  ``c08_07.py::_c08_07_spec`` consults a union only for a row whose own class
  binding is ``None``. A key that names no row is never read, and the row it
  meant renders structurally null. A key on a singly-bound row is shadowed.
- ``CMS2_SA_CLASS_MAP`` -> UKB CMS2 (Basel 3.1 only). ``cms2.py::_class_row_cells``
  reads it for rows that carry classes and falls back to the row's own classes,
  so a key on any other row is a dead entry.
- ``cr7.py::_CRR_ROW_PREDICATES`` / ``_B31_ROW_PREDICATES`` -> UK CR7 / UKB CR7.
  ``build_cr7_spec`` looks each row's predicate up with
  ``predicates.get(row.ref)`` and skips a row that has none. A key that names no
  row is therefore never read, and the row it meant renders null (the
  template's ``empty_cell="null"``); a row whose key is deleted renders null
  the same way.

Why explicit tables, and what keeps them complete. Discovery cannot tell which
template a map's refs address, and a binding check is meaningless without that.
The sheet-axis limb is scoped to its maps BY NAME, because the estate holds
legitimate z-codes elsewhere (``filing/sheet_maps.py``;
``c09.py::_OF09_02_ROW_SHEET_CODES``, keyed partly on a class value). A blanket
scan would flag them. An explicit table goes stale silently: the Pillar 3 twin
of ``IRB_EXPOSURE_CLASS_LABELS`` was missing from the class-keyed table, and the
CR7 predicates from the row-keyed one, until a scan found each. So
``test_every_class_keyed_map_in_reporting_is_classified`` and
``test_every_row_keyed_class_map_in_reporting_is_classified`` scan every
module-level mapping in ``rwa_calc.reporting`` and require each map they find
to be classified here, by identity. The class-keyed scan reads KEYS directly
rather than reusing ``test_reporting_class_keys._discover_class_groups``. That
discovery keeps one best-fitting slot per collection, so a class-keyed map whose
values fit better is reported under its values.

References:
- COREP Annex II §1.3.1 (C 02.00 rows 0070-0211); PS1/26 Annex II §1.3.1
  (OF 02.00: the same rows, plus of-which row 0131, and no row 0190)
- PS1/26 Annex II §3.3.10.2 (OF 08.07 rows 0180-0260)
- ``.claude/LESSONS.md`` B2 (an unmatched key zero-fills), B3 (a test that
  shares production's assumption validates nothing), B9 (a log line is not a gate)
"""

from __future__ import annotations

import dataclasses
import importlib
import pkgutil
import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import pytest

import rwa_calc.reporting
from rwa_calc.domain.enums import ExposureClass
from rwa_calc.reporting.cellspec import RowPredicate
from rwa_calc.reporting.corep import c02_rows
from rwa_calc.reporting.corep.c02_rows import Slot, get_c02_00_cells, get_c02_00_layout
from rwa_calc.reporting.corep.c07 import _RE_ROW_FILTERS
from rwa_calc.reporting.corep.sheet_labels import (
    B31_C07_00_SA_SHEET_LABELS,
    CRR_C07_00_SA_SHEET_LABELS,
)
from rwa_calc.reporting.corep.templates import (
    C02_00_SA_CLASS_MAP,
    C07_00_SA_SHEET_MAP,
    C07_00_TOTAL_SHEET_KEY,
    C09_01_SA_CLASS_MAP,
    IRB_EXPOSURE_CLASS_LABELS,
    get_c08_07_row_unions,
    get_c08_07_rows,
    get_irb_row_sections,
    get_sa_row_sections,
)
from rwa_calc.reporting.pillar3.cr7 import (
    _B31_ROW_PREDICATES,
    _CRR_ROW_PREDICATES,
    build_cr7_spec,
)
from rwa_calc.reporting.pillar3.ov1 import _APPROACH_REFS
from rwa_calc.reporting.pillar3.templates import (
    CMS2_ROWS,
    CMS2_SA_CLASS_MAP,
    SA_DISCLOSURE_CLASSES,
    get_cr7_rows,
)
from rwa_calc.reporting.pillar3.templates import (
    IRB_EXPOSURE_CLASSES as P3_IRB_EXPOSURE_CLASSES,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Sequence

    from rwa_calc.reporting.pillar3.templates import P3Row

FRAMEWORKS = ("CRR", "BASEL_3_1")

#: Every figure C 02.00 places by ``Slot`` -- read off the module, so a slot
#: added tomorrow is a collision candidate without anyone listing it here.
SLOTS: tuple[Slot, ...] = tuple(v for v in vars(c02_rows).values() if isinstance(v, Slot))

#: The class maps on the sheet (z) axis. Here a class gets a sheet, so a value
#: shaped like a row ref is the retired ``(ref, name)`` defect returning. The
#: Pillar 3 map is the per-class axis of CR6 / CR6-A / CR7-A (one spec and one
#: sheet per class: ``cr6.py::_CR6_SPECS``, ``pillar3/generator.py``), the twin
#: of the COREP ``IRB_EXPOSURE_CLASS_LABELS``.
SHEET_AXIS_MAPS: dict[str, Mapping[str, Any]] = {
    "corep.C07_00_SA_SHEET_MAP": C07_00_SA_SHEET_MAP,
    "corep.IRB_EXPOSURE_CLASS_LABELS": IRB_EXPOSURE_CLASS_LABELS,
    "corep.CRR_C07_00_SA_SHEET_LABELS": CRR_C07_00_SA_SHEET_LABELS,
    "corep.B31_C07_00_SA_SHEET_LABELS": B31_C07_00_SA_SHEET_LABELS,
    "pillar3.IRB_EXPOSURE_CLASSES": P3_IRB_EXPOSURE_CLASSES,
}

#: The class-keyed maps on the ROW axis, each bound to its template by a test below.
ROW_AXIS_MAPS: dict[str, Mapping[str, Any]] = {
    "corep.C02_00_SA_CLASS_MAP": C02_00_SA_CLASS_MAP,
}

#: Class-keyed maps that address no row and no sheet by a code, each with the
#: reason no ref check applies.
NO_REF_CLASS_MAPS: dict[str, tuple[Mapping[str, Any], str]] = {
    "corep.C09_01_SA_CLASS_MAP": (
        C09_01_SA_CLASS_MAP,
        "values are C 09.01 / OF 09.01 row FILTER KEYS (each row's "
        "exposure_class_value), not row refs: c09.py::_c09_01_row_pred inverts the "
        "map per row key. Under Basel 3.1 its 'retail_mortgage' value keys no row; "
        "OF 09.01 row 0090 ('real_estate') is served by _C09_01_RE_CLASSES instead.",
    ),
}

#: The CR7 row predicates per regime, as ``cr7.py::build_cr7_spec`` selects
#: them. ``test_every_cr7_row_predicate_key_is_a_cr7_row_of_its_regime`` checks
#: that every predicate the built spec reads is this map's entry, by identity.
#: A reader switched to a SHALLOW copy shares those entries and passes that; the
#: row-keyed inventory catches it instead, as an unclassified map.
CR7_ROW_PREDICATES: dict[str, Mapping[str, RowPredicate]] = {
    "CRR": _CRR_ROW_PREDICATES,
    "BASEL_3_1": _B31_ROW_PREDICATES,
}

#: The ROW-keyed class maps (row ref -> the classes that row aggregates), each
#: bound to its template by a test below.
ROW_KEYED_MAPS: dict[str, Mapping[str, Any]] = {
    "corep.CRR_C08_07_ROW_UNIONS": get_c08_07_row_unions("CRR"),
    "corep.B31_C08_07_ROW_UNIONS": get_c08_07_row_unions("BASEL_3_1"),
    "pillar3.CMS2_SA_CLASS_MAP": CMS2_SA_CLASS_MAP,
    "pillar3.cr7._CRR_ROW_PREDICATES": CR7_ROW_PREDICATES["CRR"],
    "pillar3.cr7._B31_ROW_PREDICATES": CR7_ROW_PREDICATES["BASEL_3_1"],
}

#: Row-keyed maps whose values carry a class-shaped string that is not a class,
#: each with the reason no class binding applies.
NO_CLASS_ROW_KEYED_MAPS: dict[str, tuple[Mapping[str, Any], str]] = {
    "pillar3.ov1._APPROACH_REFS": (
        _APPROACH_REFS,
        "values are APPROACH labels, read as RowPredicate(approaches=...) over the "
        "post-substitution approach: its 'equity' is ApproachType.EQUITY, which shares "
        "its spelling with ExposureClass.EQUITY. OV1 splits row 1 by approach, never "
        "by class.",
    ),
    "corep.c07._RE_ROW_FILTERS": (
        _RE_ROW_FILTERS,
        "values are PS1/26 Art. 124 real-estate LIMBS (ReRow: regulatory / other / "
        "adc, residential / commercial, materially dependent, SME), not classes: "
        "ReRow('other') is the Art. 124J 'other real estate' limb, which shares its "
        "spelling with ExposureClass.OTHER. Its keys are bound to the Basel 3.1 "
        "OF 07.00 rows by test_every_re_limb_key_is_an_of07_row.",
    ),
}

#: Every row-axis or row-keyed map this file binds, by its name in the tables
#: above, and the test that binds it. Listing a map in ``ROW_AXIS_MAPS`` or
#: ``ROW_KEYED_MAPS`` does not by itself check anything: each binding test reads
#: its own map. ``test_every_bound_table_entry_names_its_binding_test`` holds the
#: tables and this register in step, so a map added to a bound table with no
#: binding test reddens it.
BOUND_BY: dict[str, str] = {
    "corep.C02_00_SA_CLASS_MAP": "test_every_c02_sa_class_ref_is_a_class_row_of_its_regime",
    "corep.CRR_C08_07_ROW_UNIONS": "test_every_c08_07_union_key_is_an_unbound_row_of_its_regime",
    "corep.B31_C08_07_ROW_UNIONS": "test_every_c08_07_union_key_is_an_unbound_row_of_its_regime",
    "pillar3.CMS2_SA_CLASS_MAP": "test_every_cms2_class_map_key_is_a_cms2_class_row",
    "pillar3.cr7._CRR_ROW_PREDICATES": "test_every_cr7_row_predicate_key_is_a_cr7_row_of_its_regime",
    "pillar3.cr7._B31_ROW_PREDICATES": "test_every_cr7_row_predicate_key_is_a_cr7_row_of_its_regime",
    "corep.c07._RE_ROW_FILTERS": "test_every_re_limb_key_is_an_of07_row",
}

#: A code of any template in the estate, at any width: COREP's 4-digit row,
#: column and sheet codes, the 3-digit legacy column codes in
#: ``corep/templates.py`` (``C07_COLUMNS``), and Pillar 3's row numbers with
#: their letter suffix and UK prefix (``SA_DISCLOSURE_CLASSES`` rows "1".."16",
#: CR5 "9f", OV1 "UK4a"). No sheet-axis map holds a string of that shape at all,
#: so the wide form costs nothing.
_ROW_REF = re.compile(r"(?:UK)?\d+[a-z]?")

#: The vocabulary a class-keyed map is keyed on: the engine classes and the
#: C 07.00 sheet keys (``retail``, ``real_estate``) that merge them.
_CLASS_KEYS: frozenset[str] = frozenset(m.value for m in ExposureClass) | frozenset(
    C07_00_SA_SHEET_MAP.values()
)

#: A module-level mapping is CLASS-KEYED when at least this many of its keys
#: are in ``_CLASS_KEYS`` and they are at least this share of its keys (the
#: C 07.00 Total sheet key is on the sheet axis and counts for neither). At HEAD
#: the seven class-keyed maps score 1.0, and the nearest other mappings
#: (``pillar3.templates.CRR_CR10_SUBTEMPLATES``,
#: ``c09.py::_C09_01_SME_PARENT_KEYS`` and ``_OF09_02_ROW_SHEET_CODES``) hold
#: one class key each. The bar errs toward inclusion: a false positive costs a
#: line in a table above, and a false negative is the stale table this guard
#: exists to stop.
_MIN_CLASS_KEYS = 2
_MIN_CLASS_SHARE = 0.5

#: A module-level mapping is ROW-KEYED when at least this share of its keys are
#: shaped like a row ref (``_ROW_REF``) and its values carry a string in
#: ``_CLASS_KEYS``, read through tuples, sets, mappings and dataclass fields (the
#: CR7 values are ``RowPredicate`` instances). No count floor: CRR C 08.07 has one
#: union. At HEAD 23 module-level mappings have row-shaped keys, and six of them
#: carry a class: the five bound in ``ROW_KEYED_MAPS`` and OV1's
#: ``_APPROACH_REFS``.
_MIN_ROW_KEY_SHARE = 0.5


# =============================================================================
# The estate's maps, bound to their templates
# =============================================================================


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_every_c02_sa_class_ref_is_a_class_row_of_its_regime(framework: str) -> None:
    """Each class's C 02.00 / OF 02.00 ref is an Article 112(1) class row there.

    Arrange: the regime's class rows -- the published rows between row 0060 and
    the IRB block, less every row a ``Slot`` owns.
    Act: check each ref of the regime-shared map against them.
    Assert: none names no row, collides with a slot, or falls outside the band.
    """
    # Arrange
    band = _c02_class_rows(framework)
    assert band, f"{framework}: found no C 02.00 class rows -- the check would be vacuous"

    # Act
    violations = _c02_ref_violations(C02_00_SA_CLASS_MAP, framework)

    # Assert
    assert not violations, f"{framework}: C02_00_SA_CLASS_MAP refs that miss: {violations}"


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_every_c02_class_row_is_reached_by_some_class(framework: str) -> None:
    """No Article 112(1) class row is left with no class routed to it.

    The other direction of the binding. ``_sa_class_rows`` creates a cell only
    for a ref the map names, so a class row no class reaches is laid out EMPTY
    while row 0060 still counts its RWEA.
    """
    # Arrange
    assert _c02_class_rows(framework), (
        f"{framework}: found no C 02.00 class rows -- the check would be vacuous"
    )

    # Act
    unreached = _c02_unreached(C02_00_SA_CLASS_MAP, framework)

    # Assert
    assert not unreached, f"{framework}: C 02.00 class rows no class is routed to: {unreached}"


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_every_c08_07_union_key_is_an_unbound_row_of_its_regime(framework: str) -> None:
    """Each display-aggregate key is a C 08.07 / OF 08.07 row the union is what binds."""
    # Arrange
    unions = get_c08_07_row_unions(framework)
    assert unions, f"{framework}: no C 08.07 row unions -- the check would be vacuous"

    # Act
    violations = _union_violations(unions, get_c08_07_rows(framework))

    # Assert
    assert not violations, f"{framework}: C 08.07 row-union keys that miss: {violations}"


def test_every_cms2_class_map_key_is_a_cms2_class_row() -> None:
    """Each ``CMS2_SA_CLASS_MAP`` key is a CMS2 row that reads it (Basel 3.1 only)."""
    # Arrange
    assert CMS2_SA_CLASS_MAP, "CMS2_SA_CLASS_MAP is empty -- the check would be vacuous"

    # Act
    violations = _cms2_violations(CMS2_SA_CLASS_MAP, CMS2_ROWS)

    # Assert
    assert not violations, f"CMS2_SA_CLASS_MAP keys that miss: {violations}"


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_every_cr7_row_predicate_key_is_a_cr7_row_of_its_regime(framework: str) -> None:
    """Each CR7 predicate key is a row of that regime's CR7.

    Arrange: the regime's predicate map, and a check that every predicate the
    built spec reads is that map's entry for its row, by identity -- so the
    regime pairing above is the reader's, not this file's guess (see
    ``CR7_ROW_PREDICATES`` for the copy this cannot see).
    Act: check every key against the regime's CR7 rows.
    Assert: none names no row.
    """
    # Arrange
    predicates = CR7_ROW_PREDICATES[framework]
    read = {ref: cell.predicate for (ref, _col), cell in build_cr7_spec(framework).cells.items()}
    assert read, f"{framework}: the CR7 spec reads no predicate -- the check would be vacuous"
    assert all(predicate is predicates.get(ref) for ref, predicate in read.items()), (
        f"{framework}: build_cr7_spec no longer reads this map -- rebind CR7_ROW_PREDICATES"
    )

    # Act
    violations = _cr7_violations(predicates, get_cr7_rows(framework))

    # Assert
    assert not violations, f"{framework}: CR7 row-predicate keys that miss: {violations}"


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_every_cr7_row_has_a_predicate(framework: str) -> None:
    """Every row of the regime's CR7 has a predicate, its total row included.

    The other direction of the CR7 binding, and the absence form of LESSONS B2.
    ``build_cr7_spec`` skips a row with no predicate, and the template's
    ``empty_cell="null"`` renders it null. No CR7 row is meant to lack one, so
    this is exact presence with no allowlist.
    """
    # Arrange
    rows = get_cr7_rows(framework)
    assert rows, f"{framework}: found no CR7 rows -- the check would be vacuous"

    # Act
    unpredicated = _cr7_unpredicated(CR7_ROW_PREDICATES[framework], rows)

    # Assert
    assert not unpredicated, (
        f"{framework}: CR7 rows with no predicate, rendered null: {unpredicated}"
    )


@pytest.mark.parametrize("name", sorted(SHEET_AXIS_MAPS))
def test_no_sheet_axis_class_map_carries_a_row_ref(name: str) -> None:
    """A class map on the z-axis holds no key or value shaped like a row ref."""
    # Arrange
    mapping = SHEET_AXIS_MAPS[name]
    assert list(_strings_in(mapping)), f"{name} holds no strings -- the check would be vacuous"

    # Act
    refs = _row_refs(mapping)

    # Assert
    assert not refs, f"{name} (sheet axis: a class gets a sheet, not a row) carries refs {refs}"


def test_every_re_limb_key_is_an_of07_row() -> None:
    """Each ``c07._RE_ROW_FILTERS`` key is a Basel 3.1 OF 07.00 row (PS1/26 Annex II).

    ``c07.py`` reads the map with ``if ref in _RE_ROW_FILTERS``, so a key that
    names no row is never read and the row it meant renders without its limb
    filter. The rows 0330-0360 exist on OF 07.00 only; none is a CRR C 07.00 row.
    """
    # Arrange
    assert _RE_ROW_FILTERS, "_RE_ROW_FILTERS is empty -- the check would be vacuous"
    b31_rows = {row.ref for section in get_sa_row_sections("BASEL_3_1") for row in section.rows}
    crr_rows = {row.ref for section in get_sa_row_sections("CRR") for row in section.rows}

    # Act
    missing = sorted(set(_RE_ROW_FILTERS) - b31_rows)
    on_crr = sorted(set(_RE_ROW_FILTERS) & crr_rows)

    # Assert
    assert not missing, f"_RE_ROW_FILTERS keys that are not OF 07.00 rows: {missing}"
    assert not on_crr, f"_RE_ROW_FILTERS keys that are CRR C 07.00 rows: {on_crr}"


def _unbound_table_entries(
    tables: Mapping[str, Any], bound_by: Mapping[str, str], namespace: Mapping[str, Any]
) -> list[str]:
    """Every bound-table entry with no binding test, or naming a test that does not exist."""
    problems = [f"{name}: no binding test" for name in tables if name not in bound_by]
    problems += [
        f"{name}: names missing test {test}"
        for name, test in bound_by.items()
        if not callable(namespace.get(test))
    ]
    return sorted(problems)


def test_every_bound_table_entry_names_its_binding_test() -> None:
    """Each map in a bound table names a binding test that exists in this module."""
    # Arrange
    bound_tables = {
        **ROW_AXIS_MAPS,
        **ROW_KEYED_MAPS,
        "corep.c07._RE_ROW_FILTERS": _RE_ROW_FILTERS,
    }

    # Act
    problems = _unbound_table_entries(bound_tables, BOUND_BY, globals())

    # Assert
    assert not problems, f"bound-table entries with no binding: {problems}"
    assert set(BOUND_BY) == set(bound_tables), (
        f"BOUND_BY names maps no bound table holds: {sorted(set(BOUND_BY) - set(bound_tables))}"
    )


def test_the_bound_table_check_rejects_an_entry_with_no_binding_test() -> None:
    """A map added to ``ROW_KEYED_MAPS`` with no binding test is reported, by name."""
    # Arrange
    planted = {**ROW_KEYED_MAPS, "pillar3.PLANTED_ROW_MAP": {"0010": "corporate"}}
    misnamed = {**BOUND_BY, "pillar3.cr7._CRR_ROW_PREDICATES": "test_that_does_not_exist"}

    # Act
    unbound = _unbound_table_entries(planted, BOUND_BY, globals())
    renamed = _unbound_table_entries(ROW_KEYED_MAPS, misnamed, globals())

    # Assert
    assert unbound == ["pillar3.PLANTED_ROW_MAP: no binding test"]
    assert renamed == [
        "pillar3.cr7._CRR_ROW_PREDICATES: names missing test test_that_does_not_exist"
    ]


def test_the_re_limb_check_rejects_a_key_that_names_no_row() -> None:
    """A ``_RE_ROW_FILTERS`` key moved off its row (0332 -> 0335) is not an OF 07.00 row."""
    # Arrange
    b31_rows = {row.ref for section in get_sa_row_sections("BASEL_3_1") for row in section.rows}
    planted = {("0335" if key == "0332" else key) for key in _RE_ROW_FILTERS}

    # Act
    missing = sorted(planted - b31_rows)

    # Assert
    assert missing == ["0335"]


def test_every_class_keyed_map_in_reporting_is_classified() -> None:
    """Every module-level map keyed on exposure classes is in one of the tables above.

    The tables are explicit, so they go stale silently: a class-keyed map in
    none of them is checked by nothing here. Classification is BY IDENTITY, so
    a per-regime copy of a bound map (``dict(C02_00_SA_CLASS_MAP)``) that a
    reader switched to is a new map to classify, not the one already bound.

    Arrange: every map the tables classify.
    Act: scan every module of ``rwa_calc.reporting`` for class-keyed mappings.
    Assert: each one found is classified, and each one classified is found -- so
    the scan's bar is not set above the maps it exists to find.
    """
    # Arrange
    classified = _class_keyed_classified()

    # Act
    found = _maps_where(_is_class_keyed, _reporting_namespaces())
    unclassified = _unclassified(found, classified)
    unseen = sorted(name for name, mapping in classified.items() if id(mapping) not in found)

    # Assert
    assert not unclassified, (
        f"class-keyed maps this file does not classify: {unclassified} -- add each to "
        "ROW_AXIS_MAPS (and bind it to its template), SHEET_AXIS_MAPS, or "
        "NO_REF_CLASS_MAPS with its reason"
    )
    assert not unseen, f"classified maps the scan does not see as class-keyed: {unseen}"


def test_every_row_keyed_class_map_in_reporting_is_classified() -> None:
    """Every module-level map from row refs to classes is in one of the tables above.

    The row-keyed twin of the class-keyed inventory, and classified the same
    way, by identity. A reader that looks a row up by its ref never reads a key
    that names no row, so a row-keyed map in no table here hides that defect
    from every check: the CR7 predicates did until this scan found them.

    Arrange: every row-keyed map the tables classify.
    Act: scan every module of ``rwa_calc.reporting`` for row-keyed mappings
    whose values carry a class.
    Assert: each one found is classified, and each one classified is found.
    """
    # Arrange
    classified = _row_keyed_classified()

    # Act
    found = _maps_where(_is_row_keyed, _reporting_namespaces())
    unclassified = _unclassified(found, classified)
    unseen = sorted(name for name, mapping in classified.items() if id(mapping) not in found)

    # Assert
    assert not unclassified, (
        f"row-keyed class maps this file does not classify: {unclassified} -- add each "
        "to ROW_KEYED_MAPS (and bind it to its template) or to NO_CLASS_ROW_KEYED_MAPS "
        "with its reason"
    )
    assert not unseen, f"classified maps the scan does not see as row-keyed: {unseen}"


# =============================================================================
# Adequacy: each check rejects a plant
# =============================================================================
#
# Each plant goes through the helper its estate test uses, so a check that loses
# its power reddens these. Except as listed below, each is checked ON ITS OWN,
# or, where the check needs a whole map (C 02.00 reach, CR7 presence), on a
# SYNTHETIC complete map, and never merged into the estate's map: a defect in a
# real map's contents reddens the estate tests above and leaves these green.
# Three kinds of plant read real state, on purpose:
# - The Pillar 3 sheet-axis plant IS merged, into ``IRB_EXPOSURE_CLASSES``, to
#   show the check picks one bad entry out of the real ones. A row ref under any
#   key of that map but ``corporate``, the key the plant overwrites, reddens it
#   as well.
# - The two inventory plants hold real maps by identity (the classified
#   original, to show it is not reported, and a copy of it) and classify against
#   this file's tables. They read a map's shape, not its refs, so a real map
#   whose contents go wrong leaves them green while it stays class-keyed or
#   row-keyed; an edit to the tables reddens them.
# - Every precondition (CIU's row 0200 is a class row; "0030" is a C 08.01 row;
#   the deleted CR7 row exists) reads a real TEMPLATE's rows, so a template
#   change that moves a plant off its target reddens it and says so.


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_c02_check_rejects_a_ref_that_names_no_row(framework: str) -> None:
    """Class (o) CIU moved to "0205", which is no row of either template.

    Row 0200 has no partner in ``test_c02_00``'s row-to-sheet identity, and
    CIU is a single-class letter, so neither that test nor the sheet-axis
    straddle check in ``test_c07_art112_sheet_axis`` sees this plant. Two
    behavioural tests do, and only while a frame carries a CIU leg. CRR: the
    ``v0207_m`` identity in ``test_c02_00_published_rows``. Basel 3.1: the
    empty-cell check in ``test_of02_published_cells``. See the module docstring.

    The reach check is measured on a SYNTHETIC complete map -- one stand-in
    class per class row, and CIU on its published row 0200 -- never on
    ``C02_00_SA_CLASS_MAP``, so a defect in the real map leaves this test green.
    """
    # Arrange
    band = _c02_class_rows(framework)
    assert "0200" in band, f"{framework}: row 0200 (CIU) must be a class row for this plant"
    complete = {f"class of {ref}": ref for ref in band - {"0200"}} | {"ciu": "0200"}
    assert set(complete.values()) == band, "the synthetic map must reach every class row"
    planted = {"ciu": "0205"}

    # Act
    violations = _c02_ref_violations(planted, framework)
    unreached = _c02_unreached({**complete, **planted}, framework)

    # Assert
    assert set(violations) == {"ciu"}, violations
    assert "names no C 02.00 row" in violations["ciu"]
    assert unreached == ["0200"], "the plant must leave exactly CIU's own row unreached"


@pytest.mark.parametrize(
    ("framework", "slot"),
    [
        ("CRR", c02_rows.SA_SHORT_TERM_ASSESSMENT),
        ("BASEL_3_1", c02_rows.SA_SPECIALISED_LENDING),
    ],
)
def test_the_c02_check_rejects_a_ref_that_a_slot_overwrites(framework: str, slot: Slot) -> None:
    """CIU moved onto the one slot-owned row inside the regime's class block.

    CRR row 0190 (short-term assessment) and OF 02.00 row 0131 (of which:
    specialised lending) sit among the class rows but are written by a ``Slot``,
    which ``c02.py::_cells`` lets overwrite a class row of the same ref. Unlike
    a ref that names no row, this escapes the generator's row 0060 residual net,
    which counts every class row the layout holds (module docstring; measured
    for the CRR case).
    """
    # Arrange
    ref = slot.ref(framework)
    assert ref is not None
    planted = {"ciu": ref}

    # Act
    violations = _c02_ref_violations(planted, framework)

    # Assert
    assert set(violations) == {"ciu"}, violations
    assert slot.name in violations["ciu"]


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_the_c02_check_is_not_the_some_live_template_form(framework: str) -> None:
    """The retired map's ``corporate`` -> "0030" is rejected for C 02.00.

    "0030" is a live row elsewhere -- C 08.01 "Off balance sheet items subject
    to credit risk", in both regimes -- so a check that a ref exists in some
    template would have passed it. This one binds the ref to C 02.00.
    """
    # Arrange
    planted = {"corporate": "0030"}
    c08_01_rows = {row.ref for section in get_irb_row_sections(framework) for row in section.rows}
    assert "0030" in c08_01_rows, "the plant must be a live row of ANOTHER template"

    # Act
    violations = _c02_ref_violations(planted, framework)

    # Assert
    assert set(violations) == {"corporate"}, violations


@pytest.mark.parametrize(
    ("framework", "planted_key"),
    [("CRR", "0095"), ("BASEL_3_1", "0215")],
)
def test_the_c08_07_check_rejects_a_union_key_that_names_no_row(
    framework: str, planted_key: str
) -> None:
    """A union keyed beside its row (CRR retail 0090, OF 08.07 corporates 0210).

    The row it meant would render structurally null and the union is never read.
    """
    # Arrange
    unions = {planted_key: frozenset({"corporate", "corporate_sme"})}

    # Act
    violations = _union_violations(unions, get_c08_07_rows(framework))

    # Assert
    assert set(violations) == {planted_key}, violations
    assert "names no row" in violations[planted_key]


@pytest.mark.parametrize(
    ("framework", "planted_key"),
    [("CRR", "0050"), ("BASEL_3_1", "0180")],
)
def test_the_c08_07_check_rejects_a_union_a_class_binding_shadows(
    framework: str, planted_key: str
) -> None:
    """A union keyed on a row that binds its own class is never read."""
    # Arrange
    unions = {planted_key: frozenset({"corporate", "corporate_sme"})}

    # Act
    violations = _union_violations(unions, get_c08_07_rows(framework))

    # Assert
    assert set(violations) == {planted_key}, violations
    assert "shadowed" in violations[planted_key]


@pytest.mark.parametrize(
    ("planted_key", "reason"),
    [("0055", "names no row"), ("0041", "carries no class")],
)
def test_the_cms2_check_rejects_a_key_on_no_class_row(planted_key: str, reason: str) -> None:
    """A key on no row, and a key on a row with no classes, are both dead entries."""
    # Arrange
    planted = {planted_key: ("retail_other",)}

    # Act
    violations = _cms2_violations(planted, CMS2_ROWS)

    # Assert
    assert set(violations) == {planted_key}, violations
    assert reason in violations[planted_key]


@pytest.mark.parametrize(
    ("framework", "row", "moved_to"),
    [("CRR", "8", "18"), ("BASEL_3_1", "6", "16")],
)
def test_the_cr7_check_rejects_a_predicate_moved_off_its_row(
    framework: str, row: str, moved_to: str
) -> None:
    """The regime's A-IRB retail predicate keyed on its row, and beside it.

    CRR row 8 is "Retail -- Secured by immovable property", Basel 3.1 row 6
    "Retail". ``build_cr7_spec`` would never read the entry moved beside it,
    and the row it left would render null.
    """
    # Arrange
    retail = RowPredicate(approaches_origin=("advanced_irb",), classes_origin=("retail_mortgage",))
    planted = {row: retail, moved_to: retail}

    # Act
    violations = _cr7_violations(planted, get_cr7_rows(framework))

    # Assert
    assert set(violations) == {moved_to}, violations
    assert "names no row" in violations[moved_to]


@pytest.mark.parametrize(("framework", "row"), [("CRR", "8"), ("BASEL_3_1", "6")])
def test_the_cr7_presence_check_rejects_a_row_with_no_predicate(framework: str, row: str) -> None:
    """The regime's A-IRB retail row with its predicate deleted.

    A synthetic map -- a predicate on every CR7 row but one -- so a defect in
    the real predicate maps leaves this test green.
    """
    # Arrange
    rows = get_cr7_rows(framework)
    assert row in {r.ref for r in rows}, f"{framework}: the plant must delete a real CR7 row"
    planted = {r.ref: RowPredicate() for r in rows if r.ref != row}

    # Act
    unpredicated = _cr7_unpredicated(planted, rows)

    # Assert
    assert unpredicated == [row]


@pytest.mark.parametrize("planted_value", [("0110", "Equity"), "0110"])
def test_the_sheet_axis_check_rejects_a_planted_row_ref(planted_value: object) -> None:
    """The retired ``(ref, name)`` shape: ``equity`` -> "0110", bare or in a tuple.

    "0110" is a live C 02.00 class row in both regimes (International
    Organisations), so only a no-ref-at-all rule rejects it on the sheet axis.
    """
    # Arrange
    planted = {"equity": planted_value}
    assert all("0110" in get_c02_00_cells(framework) for framework in FRAMEWORKS)

    # Act
    refs = _row_refs(planted)

    # Assert
    assert refs == ["0110"]


@pytest.mark.parametrize(
    ("planted_value", "ref"),
    [
        ("0030", "0030"),
        (("0030", "Corporates"), "0030"),
        ("7", "7"),
        (("7", "Corporates"), "7"),
    ],
)
def test_the_sheet_axis_check_rejects_a_row_ref_on_the_pillar3_class_axis(
    planted_value: object, ref: str
) -> None:
    """The retired shape on the Pillar 3 class axis, at COREP and Pillar 3 widths.

    "7" is the Pillar 3 SA disclosure row for corporates. A 4-digit pattern
    cannot see it, which is why ``_ROW_REF`` takes any width.
    """
    # Arrange
    planted = {**P3_IRB_EXPOSURE_CLASSES, "corporate": planted_value}
    assert "7" in {row_ref for row_ref, _label, _classes in SA_DISCLOSURE_CLASSES}

    # Act
    refs = _row_refs(planted)

    # Assert
    assert refs == [ref]


def test_the_inventory_flags_a_class_keyed_map_it_does_not_classify() -> None:
    """A per-regime copy of a bound map, and a map keyed on sheet keys, are flagged.

    The copy is the shape a future per-regime C 02.00 map takes. If ``c02.py``
    read it instead of the map bound above, every test in this file would still
    check the map ``c02.py`` no longer reads. A mapping with one class key among
    others (the ``_OF09_02_ROW_SHEET_CODES`` shape) is not class-keyed.
    """
    # Arrange
    planted = {
        "C02_00_SA_CLASS_MAP": C02_00_SA_CLASS_MAP,
        "B31_C02_00_SA_CLASS_MAP": dict(C02_00_SA_CLASS_MAP),
        "OF07_SHEET_TITLES": {key: key.title() for key in set(C07_00_SA_SHEET_MAP.values())},
        "ROW_SHEET_CODES": {"corporate_sme": "0024", "retail_sme": "0025", "other_sme": "0026"},
    }

    # Act
    found = _maps_where(_is_class_keyed, [("planted", planted)])
    unclassified = _unclassified(found, _class_keyed_classified())

    # Assert
    assert unclassified == ["planted::B31_C02_00_SA_CLASS_MAP", "planted::OF07_SHEET_TITLES"]


def test_the_row_keyed_inventory_flags_a_row_keyed_class_map_it_does_not_classify() -> None:
    """A copy of a bound predicate map, and Pillar 3-shaped union keys, are flagged.

    The copy carries its classes only inside ``RowPredicate`` fields, so this
    proves the scan reads through dataclasses; the union proves it reads the
    suffixed and UK-prefixed row shapes. A row-keyed map of labels carries no
    class and is not flagged, and the classified original is not reported.
    """
    # Arrange
    planted = {
        "_B31_ROW_PREDICATES": _B31_ROW_PREDICATES,
        "_B31_CR7A_ROW_PREDICATES": dict(_B31_ROW_PREDICATES),
        "_ROW_UNIONS": {"UK4a": frozenset({"corporate"}), "9f": frozenset({"retail_other"})},
        "_ROW_LABELS": {"0010": "Corporates", "0020": "Institutions"},
    }

    # Act
    found = _maps_where(_is_row_keyed, [("planted", planted)])
    unclassified = _unclassified(found, _row_keyed_classified())

    # Assert
    assert unclassified == ["planted::_B31_CR7A_ROW_PREDICATES", "planted::_ROW_UNIONS"]


# =============================================================================
# Private helpers
# =============================================================================


def _c02_class_rows(framework: str) -> set[str]:
    """The regime's Article 112(1) class rows of C 02.00 / OF 02.00.

    The published rows strictly between ``SA_CLASSES`` (row 0060, their sum) and
    ``IRB`` (row 0240) in published order, less every row a ``Slot`` owns --
    read off the layout and the slot table, never typed out.
    """
    order = [row.ref for _section, rows in get_c02_00_layout(framework) for row in rows]
    first = order.index(str(c02_rows.SA_CLASSES.ref(framework)))
    last = order.index(str(c02_rows.IRB.ref(framework)))
    return set(order[first + 1 : last]) - set(_slot_rows(framework))


def _slot_rows(framework: str) -> dict[str, str]:
    """Row code -> the name of the ``Slot`` that writes it, under ``framework``."""
    return {ref: slot.name for slot in SLOTS if (ref := slot.ref(framework)) is not None}


def _c02_ref_violations(class_map: Mapping[str, str], framework: str) -> dict[str, str]:
    """Class -> why its ref is not an Article 112(1) class row under ``framework``."""
    layout = get_c02_00_cells(framework)
    slots = _slot_rows(framework)
    band = _c02_class_rows(framework)
    violations: dict[str, str] = {}
    for exposure_class, ref in class_map.items():
        if ref not in layout:
            violations[exposure_class] = f"{ref} names no C 02.00 row ({framework})"
        elif ref in slots:
            violations[exposure_class] = (
                f"{ref} is the row of slot {slots[ref]!r}, which overwrites it ({framework})"
            )
        elif ref not in band:
            violations[exposure_class] = f"{ref} is not an Article 112(1) class row ({framework})"
    return violations


def _c02_unreached(class_map: Mapping[str, str], framework: str) -> list[str]:
    """Every Article 112(1) class row under ``framework`` that no class of the map reaches."""
    return sorted(_c02_class_rows(framework) - set(class_map.values()))


def _union_violations(
    unions: Mapping[str, frozenset[str]], row_defs: Sequence[tuple[str, str, str | None]]
) -> dict[str, str]:
    """Row key -> why the C 08.07 reader would never apply that union."""
    bindings = {ref: exposure_class for ref, _name, exposure_class in row_defs}
    violations: dict[str, str] = {}
    for ref in unions:
        if ref not in bindings:
            violations[ref] = f"{ref} names no row"
        elif bindings[ref] is not None:
            violations[ref] = f"{ref} binds {bindings[ref]!r} itself, so the union is shadowed"
    return violations


def _cms2_violations(
    class_map: Mapping[str, tuple[str, ...]], rows: Sequence[P3Row]
) -> dict[str, str]:
    """Row key -> why ``cms2.py::_class_row_cells`` would never read that entry."""
    refs = {row.ref for row in rows}
    class_rows = {row.ref for row in rows if row.exposure_classes and not row.is_total}
    violations: dict[str, str] = {}
    for ref in class_map:
        if ref not in refs:
            violations[ref] = f"{ref} names no row"
        elif ref not in class_rows:
            violations[ref] = f"{ref} carries no class binding, so the entry is never read"
    return violations


def _cr7_violations(predicates: Mapping[str, object], rows: Sequence[P3Row]) -> dict[str, str]:
    """Row key -> why ``cr7.py::build_cr7_spec`` would never read that predicate."""
    refs = {row.ref for row in rows}
    return {
        ref: f"{ref} names no row, so build_cr7_spec never reads it"
        for ref in predicates
        if ref not in refs
    }


def _cr7_unpredicated(predicates: Mapping[str, object], rows: Sequence[P3Row]) -> list[str]:
    """Every CR7 row, in template order, that ``build_cr7_spec`` would skip for want of a key."""
    return [row.ref for row in rows if row.ref not in predicates]


def _row_refs(value: object) -> list[str]:
    """Every string in ``value`` shaped like a template code, sorted."""
    return sorted(s for s in _strings_in(value) if _ROW_REF.fullmatch(s))


def _strings_in(value: object) -> Iterator[str]:
    """Every string in ``value``: keys, values, members and dataclass fields."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield from _strings_in(key)
            yield from _strings_in(item)
    elif isinstance(value, (tuple, list, set, frozenset)):
        for item in value:
            yield from _strings_in(item)
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        for field in dataclasses.fields(value):
            yield from _strings_in(getattr(value, field.name))


def _class_keyed_classified() -> dict[str, Mapping[str, Any]]:
    """Every class-keyed map this file classifies, by its name in the tables above."""
    return {
        **SHEET_AXIS_MAPS,
        **ROW_AXIS_MAPS,
        **{name: mapping for name, (mapping, _reason) in NO_REF_CLASS_MAPS.items()},
    }


def _row_keyed_classified() -> dict[str, Mapping[str, Any]]:
    """Every row-keyed map this file classifies, by its name in the tables above."""
    return {
        **ROW_KEYED_MAPS,
        **{name: mapping for name, (mapping, _reason) in NO_CLASS_ROW_KEYED_MAPS.items()},
    }


def _reporting_namespaces() -> Iterator[tuple[str, Mapping[str, Any]]]:
    """``(module name, module namespace)`` for every module of ``rwa_calc.reporting``."""
    for info in pkgutil.walk_packages(rwa_calc.reporting.__path__, prefix="rwa_calc.reporting."):
        yield info.name, vars(importlib.import_module(info.name))


def _maps_where(
    shape: Callable[[Mapping[Any, Any]], bool],
    namespaces: Iterable[tuple[str, Mapping[str, Any]]],
) -> dict[int, list[str]]:
    """Identity of each mapping of the given ``shape`` -> every ``module::name`` bound to it.

    Keyed by identity because one map is re-exported through several modules
    (``corep/__init__.py``, every reader that imports it).
    """
    found: dict[int, list[str]] = {}
    for origin, namespace in namespaces:
        for attribute, value in namespace.items():
            if isinstance(value, Mapping) and shape(value):
                found.setdefault(id(value), []).append(f"{origin}::{attribute}")
    return found


def _is_class_keyed(mapping: Mapping[Any, Any]) -> bool:
    """Whether a mapping's keys are exposure classes or C 07.00 sheet keys."""
    keys = {key for key in mapping if isinstance(key, str)} - {C07_00_TOTAL_SHEET_KEY}
    hits = len(keys & _CLASS_KEYS)
    return hits >= _MIN_CLASS_KEYS and hits >= _MIN_CLASS_SHARE * len(keys)


def _is_row_keyed(mapping: Mapping[Any, Any]) -> bool:
    """Whether a mapping is keyed on row refs and its values carry a class."""
    keys = [key for key in mapping if isinstance(key, str)]
    row_keys = [key for key in keys if _ROW_REF.fullmatch(key)]
    if not row_keys or len(row_keys) < _MIN_ROW_KEY_SHARE * len(keys):
        return False
    return any(s in _CLASS_KEYS for item in mapping.values() for s in _strings_in(item))


def _unclassified(found: Mapping[int, list[str]], classified: Mapping[str, Any]) -> list[str]:
    """Every ``module::name`` found that the given table does not hold."""
    known = {id(mapping) for mapping in classified.values()}
    return sorted(name for key, names in found.items() if key not in known for name in names)
