"""
The sheet (z-axis) index map — the highest-risk surface in the evaluator.

Pipeline position:
    publisher z-code -> SHEET_INDEX_MAPS -> our per-exposure-class sheet keys

Why this file exists: every other kind of mistake in this module surfaces as an
error or a skip. A wrong entry HERE surfaces as a plausible finding — the rule is
evaluated cleanly, against the wrong population, and the resulting break (or
absence of one) looks exactly like a real result. There is no runtime signal.

The supervisory z-axis is a positional index into the regulation's exposure-class
list, while our bundles key sheets by class NAME, and our classes are in places a
COARSER partition than the DPM's. So the map carries two obligations, both
pinned below:

- every ``bundle_keys`` entry names a class this project can actually emit — a
  typo there silently maps a code onto nothing and skips the rule forever;
- a scoped subset of codes resolves only when it is CLOSED under the mapping,
  because a sheet we would evaluate may carry exposures the rule never scoped.

References:
- CRR Art. 112(1)(a)-(q) — the SA classes indexed by the C 07.00 z-axis
- CRR Art. 147(2) / COREP Annex II §3.3.2 — the IRB sub-class list (C 08.01)
- PRA PS1/26 Annex II OF 07.00 / OF 09.01 / OF 09.02
"""

from __future__ import annotations

import pytest

from rwa_calc.domain.enums import ExposureClass
from rwa_calc.reporting.validations.scope import (
    SHEET_INDEX_MAPS,
    SKIP_SHEET_SCOPE_NOT_CLOSED,
    resolve_sheet_codes,
)

MAP_NAMES = sorted(SHEET_INDEX_MAPS)

#: Every class value this project can key a template sheet by.
EMITTABLE_CLASSES = {member.value for member in ExposureClass}


# ---------------------------------------------------------------------------
# Every mapped key is a class we can actually emit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("map_name", MAP_NAMES)
def test_every_mapped_bundle_key_is_a_real_exposure_class(map_name: str) -> None:
    """A ``bundle_keys`` typo would silently map a z-code onto nothing.

    The failure mode is invisible: the code resolves to a sheet name no generator
    produces, ``resolve_sheet_codes`` reports ``sheet_not_emitted``, and the rule
    is skipped forever without anyone learning that a real class went unchecked.
    """
    # Arrange
    sheet_map = SHEET_INDEX_MAPS[map_name]

    # Act
    unknown = sorted(
        {
            key
            for entry in sheet_map.values()
            for key in entry.bundle_keys
            if key not in EMITTABLE_CLASSES
        }
    )

    # Assert
    assert unknown == [], f"{map_name} maps onto class name(s) that do not exist: {unknown}"


@pytest.mark.parametrize("map_name", MAP_NAMES)
def test_every_sheet_code_records_where_it_came_from(map_name: str) -> None:
    """An entry with no provenance cannot be re-derived, only re-guessed."""
    # Arrange
    sheet_map = SHEET_INDEX_MAPS[map_name]

    # Act
    unsourced = sorted(code for code, entry in sheet_map.items() if not entry.source.strip())

    # Assert
    assert unsourced == []


@pytest.mark.parametrize("map_name", MAP_NAMES)
def test_every_sheet_code_carries_a_label(map_name: str) -> None:
    """The label is what a reader triaging a skip sees instead of a bare code."""
    # Arrange
    sheet_map = SHEET_INDEX_MAPS[map_name]

    # Act
    unlabelled = sorted(code for code, entry in sheet_map.items() if not entry.label.strip())

    # Assert
    assert unlabelled == []


@pytest.mark.parametrize("map_name", MAP_NAMES)
def test_each_sheet_code_is_indexed_under_its_own_code(map_name: str) -> None:
    """The dict key and the entry's own ``code`` must agree, or lookups lie."""
    # Arrange
    sheet_map = SHEET_INDEX_MAPS[map_name]

    # Act
    mismatched = sorted(code for code, entry in sheet_map.items() if entry.code != code)

    # Assert
    assert mismatched == []


# ---------------------------------------------------------------------------
# Closure — the property that stops a rule being judged on the wrong population
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("map_name", MAP_NAMES)
def test_any_single_code_sharing_a_sheet_is_refused_on_its_own(map_name: str) -> None:
    """A code that shares one of our sheets never resolves alone.

    This is the closure property stated as an invariant over the whole map rather
    than on one example: wherever two publisher codes land on the same sheet of
    ours (the DPM's SME / non-SME pair against our single ``retail_mortgage``,
    or its F-IRB / A-IRB pair against one class sheet), neither may be evaluated
    without the other, because the sheet carries both populations.
    """
    # Arrange
    sheet_map = SHEET_INDEX_MAPS[map_name]
    shared = [
        code
        for code, entry in sheet_map.items()
        if entry.bundle_keys
        and any(
            other != code and set(sheet_map[other].bundle_keys) & set(entry.bundle_keys)
            for other in sheet_map
        )
    ]

    # Act
    resolved_alone = [
        code
        for code in shared
        if resolve_sheet_codes((code,), sheet_map, sheet_map[code].bundle_keys).skip_reason
        != SKIP_SHEET_SCOPE_NOT_CLOSED
    ]

    # Assert
    assert resolved_alone == [], (
        f"{map_name}: code(s) {resolved_alone} resolve alone despite sharing one of our "
        "sheets with another code - the rule would be judged on a wider population"
    )


@pytest.mark.parametrize("map_name", ["c08", "of08"])
def test_the_irb_maps_actually_exercise_the_closure_property(map_name: str) -> None:
    """The IRB axes pair sheets, so closure is a live constraint there, not theory.

    Both regimes give each non-retail IRB class an F-IRB and an A-IRB z-code that
    land on ONE class sheet of ours. The SA maps have no such pairing — each code
    owns its keys — which is why the invariant above is vacuous for ``c07``/
    ``of07`` and must not be assumed to bite everywhere.
    """
    # Arrange
    sheet_map = SHEET_INDEX_MAPS[map_name]

    # Act
    shared = [
        code
        for code, entry in sheet_map.items()
        if entry.bundle_keys
        and any(
            other != code and set(sheet_map[other].bundle_keys) & set(entry.bundle_keys)
            for other in sheet_map
        )
    ]

    # Assert
    assert shared, f"{map_name} no longer pairs any sheet - closure is now untested here"


def test_the_crr_and_basel_maps_disagree_where_the_regimes_do() -> None:
    """The IRB z-axis is genuinely a DIFFERENT axis between the two regimes.

    PS1/26 withdraws the IRB approach for sovereigns and re-cuts corporates and
    retail, so ``c08`` and ``of08`` are not the same list. Asserting they differ
    guards against someone "tidying" one into the other.
    """
    # Arrange
    crr_codes = set(SHEET_INDEX_MAPS["c08"])
    b31_codes = set(SHEET_INDEX_MAPS["of08"])

    # Act / Assert
    assert crr_codes != b31_codes


def test_the_sa_maps_agree_on_the_article_112_letters() -> None:
    """C 07.00 and OF 07.00 keep the Art. 112(1) ordering; only class (n) is withdrawn."""
    # Arrange
    crr_codes = set(SHEET_INDEX_MAPS["c07"])
    b31_codes = set(SHEET_INDEX_MAPS["of07"])

    # Act
    withdrawn = crr_codes - b31_codes

    # Assert: 0014 is Art. 112(1)(n), short-term assessments, withdrawn by PS1/26.
    assert (withdrawn, b31_codes - crr_codes) == ({"0014"}, set())
