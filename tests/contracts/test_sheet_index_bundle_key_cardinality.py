"""
One published sheet code addresses AT MOST ONE of our sheets — an invariant.

Pipeline position:
    published rule (scoped ``sheets: s0008``)
        -> validations/scope.py::resolve_sheet_codes
        -> our per-exposure-class sheet key(s)
        -> the evaluator aggregates the rule's reference ACROSS every key returned

Why this file exists — the mechanism, not the tidiness
------------------------------------------------------
``resolve_sheet_codes`` accumulates **every** ``bundle_key`` a requested z-code
names, and the evaluator then sums the rule's reference over all of them. So a
``SheetCode`` carrying two keys does not merely describe our axis loosely: it
makes a published rule true of a figure **that appears in no submitted
workbook**.

That is not hypothetical. Before ``eb546935`` (PR #497), ``_C07_SHEETS`` z0008
held ``("corporate", "corporate_sme")``, z0009 held ``("retail_other",
"retail_qrre")`` and z0010 held the three mortgage classes, with the same three
shapes on the ``_OF07_SHEETS`` twin. The engine was emitting two partial sheets
for Art. 112(1)(g) and no total for the letter — a real, submittable defect —
and the live EBA **ERROR** rule ``v4240_i``
(``{C 02.00, r0130, c0010} == {C 07.00.a, r0010, c0220, s0008}``) **passed**,
because scope resolution silently re-assembled the letter's total by summing
our two sheets. The review that filed P5.65 measured the whole register pre- and
post-fix and reports 27 broken / 4 uncovered / 188 vacuous in BOTH states — not
one rule outcome moved. The multi-key mapping did not merely fail to catch the
defect, it MASKED it.

So when this file fails, the fix is to correct the sheet axis — merge the
engine sub-classes onto the one key the publisher's letter addresses, as
``corep/templates.py::C07_00_SA_SHEET_MAP`` now does — and **never** to relax
the invariant by adding a second key to the entry. Adding the key makes the
supervisory rule green again while leaving the workbook wrong, which is exactly
the state PR #497 found the estate in.

The reverse shape is legal and is asserted here too
---------------------------------------------------
Several z-codes mapping onto ONE of our sheets is the opposite direction and is
legitimate: the DPM's Art. 147(2)(d) axis is FINER than ours (z0013 SME and
z0014 non-SME both address our single ``retail_mortgage`` sheet), and the
existing ``sheet_scope_not_closed`` guard is what makes it safe — neither code
may be evaluated without the other. A "simplification" that forced a 1:1
z-code <-> sheet mapping would break the IRB templates, so this file pins that
shape as permitted, with an adequacy assertion that the estate still contains
one (``.claude/LESSONS.md`` C11 — a test whose fixture can no longer express
the condition has to say so rather than pass).

Scope of this file, stated precisely
------------------------------------
Limbs 1-3 read ``SHEET_INDEX_MAPS`` from the module that owns it and assert a
property of that data structure — they do not read ``scripts/arch_check.py`` at
all, so they stand whatever the script does. P5.65 graduates the same invariant
into the arch gate as well, and the two halves measure genuinely different
things: the arch check parses ``SheetCode(...)`` LITERALS out of the source,
while limbs 1-3 read the mapping the evaluator actually resolves — so a map
assembled at import time from something the AST cannot see is caught here and
not there, and a literal in a module nothing imports is caught there and not
here.

The final section tests that arch check as a BLACK BOX: it calls the shipped
function over fixed source and reads its findings. The must-flag input is the
real pre-fix ``scope.py``, vendored beside this file, whose correct verdict is
human-judged (six violations). Two must-not-flag inputs run through the
identical harness, so the file's CONTENT is the only thing that differs: the
current ``scope.py``, and a small sample carrying all three legal cardinalities
— one key, no keys, and two z-codes sharing one key — so a check that banned
the finer Art. 147(2)(d) IRB axis fails on the case it broke rather than
somewhere downstream. It also asserts the check is dispatched by ``main()``,
because a guard built and never called is this estate's dominant meta-pattern
— it is why ``arch_check`` grew check 20.

The behavioural closure guard lives next door in
``tests/unit/reporting/validations/test_sheet_index_map.py``; this file owns the
CARDINALITY direction, which that file does not check.

References:
- CRR Art. 112(1)(a)-(q) — the SA classes indexed by the C 07.00 z-axis
- CRR Art. 147(2)(d) / COREP Annex II §3.3.2 — the finer IRB sub-class axis
- PRA PS1/26 Annex II (OF 07.00 / OF 09.01 instructions)
- EBA ``v4240_i`` (ERROR, live) — the rule the multi-key mapping satisfied
- IMPLEMENTATION_PLAN.md P5.65; ``.claude/LESSONS.md`` B2 / B3 / C11
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

from rwa_calc.reporting.validations.scope import (
    SHEET_INDEX_MAPS,
    SKIP_SHEET_SCOPE_NOT_CLOSED,
    SheetCode,
    resolve_sheet_codes,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

MAP_NAMES: Final = sorted(SHEET_INDEX_MAPS)


# ---------------------------------------------------------------------------
# THE predicate. Limb 1 runs it over the live maps, limb 3 over a planted
# violation, so the two limbs cannot disagree about what "a violation" is.
# ---------------------------------------------------------------------------


def _multi_key_codes(sheet_map: Mapping[str, SheetCode]) -> dict[str, tuple[str, ...]]:
    """Every z-code in ``sheet_map`` that addresses more than one of our sheets."""
    return {
        code: entry.bundle_keys for code, entry in sheet_map.items() if len(entry.bundle_keys) > 1
    }


def _codes_by_bundle_key(sheet_map: Mapping[str, SheetCode]) -> dict[str, list[str]]:
    """``{our sheet key: [z-codes addressing it]}`` — the reverse direction."""
    by_key: dict[str, list[str]] = {}
    for code, entry in sorted(sheet_map.items()):
        for key in entry.bundle_keys:
            by_key.setdefault(key, []).append(code)
    return by_key


# ---------------------------------------------------------------------------
# The planted violation (limb 3).
#
# Built in-test from the real ``SheetCode`` dataclass rather than by
# monkeypatching ``SHEET_INDEX_MAPS``: the map is a module-level ``Final`` read
# by the live evaluator and by the sibling suites in the same worker, and
# ``src/`` belongs to another agent on this branch — a mutation that leaked
# would redden files this test knows nothing about. Constructing the structure
# costs nothing, because the property under test is a property OF the structure.
#
# The three offending entries are transcribed VERBATIM from
# ``git show eb546935^:src/rwa_calc/reporting/validations/scope.py`` (lines
# 143-166), so the sample is the defect that shipped rather than one invented to
# make the point. z0007 is carried unchanged alongside them as the single-key
# control: without it the sample could be satisfied by a predicate that flags
# every entry.
# ---------------------------------------------------------------------------

_PRE_FIX_C07_SAMPLE: Final[Mapping[str, SheetCode]] = {
    entry.code: entry
    for entry in (
        SheetCode("0007", "Art. 112(1)(f) institutions", ("institution",), "CRR Art. 112(1)(f)"),
        SheetCode(
            "0008",
            "Art. 112(1)(g) corporates (incl. SME of-which)",
            ("corporate", "corporate_sme"),
            "CRR Art. 112(1)(g); v4240_i vs C 02.00 r0130",
        ),
        SheetCode(
            "0009",
            "Art. 112(1)(h) retail (incl. QRRE of-which)",
            ("retail_other", "retail_qrre"),
            "CRR Art. 112(1)(h); v4241_i vs C 02.00 r0140",
        ),
        SheetCode(
            "0010",
            "Art. 112(1)(i) secured by mortgages on immovable property",
            ("retail_mortgage", "residential_mortgage", "commercial_mortgage"),
            "COREP Annex II C 07.00 row 0040 + para 62 rank 6; v7477_m",
        ),
    )
}

#: The z-code whose multi-key entry satisfied ``v4240_i`` against a figure in no
#: workbook, and the two sheets it summed.
_MASKED_CODE: Final = "0008"
_MASKED_KEYS: Final = ("corporate", "corporate_sme")


# ---------------------------------------------------------------------------
# Limb 1 — the invariant holds now
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("map_name", MAP_NAMES)
def test_every_sheet_code_addresses_at_most_one_of_our_sheets(map_name: str) -> None:
    """No ``SheetCode`` carries two ``bundle_keys`` — the graduated invariant.

    A second key makes ``resolve_sheet_codes`` hand the evaluator two sheets for
    one published z-code, and the rule is then judged on their SUM. The remedy
    is always to fix the sheet axis so the letter has one total sheet; adding
    the key back turns the rule green over a workbook that is still wrong.
    """
    # Arrange
    sheet_map = SHEET_INDEX_MAPS[map_name]

    # Act
    offenders = _multi_key_codes(sheet_map)

    # Assert
    assert offenders == {}, (
        f"{map_name}: sheet code(s) address more than one of our sheets: {offenders}. "
        "resolve_sheet_codes returns every key and the evaluator sums the rule's "
        "reference across them, so a published rule is satisfied against a figure "
        "that appears in NO submitted workbook - which is how the Art. 112(1) class "
        "axis defect (PR #497) passed the live ERROR rule v4240_i. Fix the sheet "
        "axis so the publisher's class has ONE total sheet (see "
        "corep/templates.py::C07_00_SA_SHEET_MAP); do not add the second key back"
    )


@pytest.mark.parametrize("map_name", MAP_NAMES)
def test_the_invariant_is_measured_over_a_populated_map(map_name: str) -> None:
    """Adequacy: an empty map, or one whose entries name no sheet, passes limb 1
    for free. Assert the population is real, so limb 1 cannot go vacuous by the
    maps being emptied (``.claude/LESSONS.md`` C11)."""
    # Arrange
    sheet_map = SHEET_INDEX_MAPS[map_name]

    # Act
    single_key = [code for code, entry in sheet_map.items() if len(entry.bundle_keys) == 1]

    # Assert
    assert single_key, (
        f"{map_name} holds no entry that addresses a sheet of ours at all "
        f"({len(sheet_map)} code(s) declared), so the cardinality invariant is "
        "vacuous here - the map has been emptied rather than kept clean"
    )


def test_all_four_published_axes_are_covered() -> None:
    """Adequacy: the four known axes are still declared, so the parametrisation
    above still measures them.

    A SUPERSET, deliberately: the limbs above are parametrised over whatever
    ``SHEET_INDEX_MAPS`` declares, so a fifth axis is covered the moment it is
    added and must not fail here. What this catches is an axis DISAPPEARING —
    every rule scoped to its z-codes then resolves to nothing and scores
    NOT_EVALUATED, and because the supervisory gate fails open that loss is
    invisible everywhere else.
    """
    # Arrange / Act / Assert
    missing = sorted({"c07", "of07", "c08", "of08"} - set(MAP_NAMES))
    assert not missing, (
        f"SHEET_INDEX_MAPS no longer declares {missing} (it declares {MAP_NAMES}). "
        "Those axes' rules are no longer addressable at all, and the supervisory "
        "gate reports that as NOT_EVALUATED rather than as a break"
    )


# ---------------------------------------------------------------------------
# Limb 2 — the reverse shape is legal, and must stay legal
# ---------------------------------------------------------------------------


def test_several_sheet_codes_may_share_one_of_our_sheets() -> None:
    """Many z-codes -> ONE of our sheets is the publisher being FINER than us.

    Art. 147(2)(d) splits retail secured by immovable property into SME (z0013)
    and non-SME (z0014); we emit one ``retail_mortgage`` sheet. That is the
    documented, safe direction — ``resolve_sheet_codes`` refuses to evaluate
    either code alone — and the invariant above must not be read as "one z-code
    per sheet, one sheet per z-code". Forcing a 1:1 axis would break the IRB
    templates.
    """
    # Arrange
    shared: dict[str, dict[str, list[str]]] = {
        map_name: {
            key: codes
            for key, codes in _codes_by_bundle_key(SHEET_INDEX_MAPS[map_name]).items()
            if len(codes) > 1
        }
        for map_name in MAP_NAMES
    }

    # Act
    present = {map_name: groups for map_name, groups in shared.items() if groups}

    # Assert — adequacy first: the shape must still exist somewhere, or this
    # test permits a case the estate no longer has and proves nothing.
    assert present, (
        "no sheet of ours is addressed by more than one z-code anywhere in "
        "SHEET_INDEX_MAPS, so the many-to-one shape this test permits is no "
        "longer exercised. Either the IRB axes were re-cut 1:1 - which would "
        "collapse the DPM's SME / non-SME and F-IRB / A-IRB pairs onto codes "
        "they do not mean - or the maps were emptied. Re-point this test at "
        "whatever the finer axis has become; do not delete it"
    )
    for map_name, groups in present.items():
        offenders = _multi_key_codes(SHEET_INDEX_MAPS[map_name])
        assert offenders == {}, (
            f"{map_name}: the cardinality invariant flagged {sorted(offenders)} while "
            f"legitimately sharing sheet(s) {sorted(groups)} between codes. The two "
            "directions are not the same property: several codes on one sheet is the "
            "publisher being finer than us (safe, guarded by sheet_scope_not_closed); "
            "several sheets on one code is us summing sheets the publisher never asked "
            "us to add together"
        )


def test_a_closed_set_of_shared_codes_still_resolves_to_the_shared_sheet() -> None:
    """The finer axis is not merely tolerated — it must keep RESOLVING.

    Requesting the whole SME / non-SME pair is closed under the mapping, so it
    yields our one ``retail_mortgage`` sheet and the rule is evaluated. A change
    that made the invariant true by splitting the sheet per z-code would leave
    this green while emitting sheets no C 08.xx generator produces, so the
    resolution is asserted on the LIVE map rather than assumed.
    """
    # Arrange
    sheet_map = SHEET_INDEX_MAPS["c08"]
    pairs = {key: codes for key, codes in _codes_by_bundle_key(sheet_map).items() if len(codes) > 1}
    assert pairs, "c08 no longer pairs any sheet - the IRB axis is no longer finer than ours"
    key, codes = sorted(pairs.items())[0]

    # Act
    resolution = resolve_sheet_codes(codes, sheet_map, (key,))

    # Assert
    assert (resolution.skip_reason, resolution.sheets) == (None, (key,)), (
        f"c08: the closed code set {codes} no longer resolves to our {key!r} sheet "
        f"(skip_reason={resolution.skip_reason!r}, sheets={resolution.sheets}); every "
        "published rule scoped to those codes now scores NOT_EVALUATED, and the "
        "supervisory gate fails OPEN so nothing else would report it"
    )


def test_one_code_of_a_shared_pair_is_refused_as_not_closed() -> None:
    """The guard that MAKES the reverse shape safe, pinned beside the shape.

    Our sheet carries both populations, so evaluating one z-code alone would
    judge the rule on the wider set. ``sheet_scope_not_closed`` is why several
    codes per sheet is acceptable where several sheets per code is not — the
    two are asserted in one file so neither can be "simplified" without the
    other being read.
    """
    # Arrange
    sheet_map = SHEET_INDEX_MAPS["c08"]
    pairs = {key: codes for key, codes in _codes_by_bundle_key(sheet_map).items() if len(codes) > 1}
    assert pairs, "c08 no longer pairs any sheet - the closure guard is untested here"
    key, codes = sorted(pairs.items())[0]

    # Act
    resolution = resolve_sheet_codes(codes[:1], sheet_map, (key,))

    # Assert
    assert resolution.skip_reason == SKIP_SHEET_SCOPE_NOT_CLOSED, (
        f"c08: code {codes[0]} resolved alone (skip_reason="
        f"{resolution.skip_reason!r}) although our {key!r} sheet also carries "
        f"{list(codes[1:])}. Without this refusal, several codes per sheet stops "
        "being a safe shape and becomes the same defect class as several sheets "
        "per code"
    )


# ---------------------------------------------------------------------------
# Limb 3 — the invariant discriminates, and the harm it prevents is real
# ---------------------------------------------------------------------------


def test_the_predicate_flags_the_axis_that_actually_shipped() -> None:
    """The pre-PR-#497 ``_C07_SHEETS`` entries are caught by the same predicate.

    Limb 1 is only evidence while it can go red. This runs the identical
    ``_multi_key_codes`` over the three multi-key entries as they stood at
    ``eb546935^``, verbatim, plus a single-key control — so a predicate that
    flagged everything, or nothing, fails here.
    """
    # Arrange — adequacy: the sample carries both shapes, or it discriminates
    # nothing (LESSONS C11).
    cardinalities = {len(entry.bundle_keys) for entry in _PRE_FIX_C07_SAMPLE.values()}
    assert cardinalities == {1, 2, 3}, (
        f"the planted sample no longer holds single- AND multi-key entries "
        f"(cardinalities {sorted(cardinalities)}); with only one shape present it "
        "cannot tell a working predicate from one that flags every entry"
    )

    # Act
    offenders = _multi_key_codes(_PRE_FIX_C07_SAMPLE)

    # Assert
    assert sorted(offenders) == ["0008", "0009", "0010"], (
        "the predicate did not flag the multi-key entries that shipped in "
        f"_C07_SHEETS before eb546935 (flagged {sorted(offenders)}), so limb 1 "
        "would have passed over the defect it exists to catch"
    )
    assert "0007" not in offenders, (
        "the predicate flagged the single-key control z0007, so it does not "
        "measure cardinality at all and limb 1's green is meaningless"
    )


def test_a_multi_key_code_makes_the_evaluator_sum_two_of_our_sheets() -> None:
    """The harm, measured: same code, same emitted sheets, only the MAP differs.

    This is the mechanism the invariant exists to stop. Holding the requested
    z-code and the emitted sheet set fixed and varying nothing but the map (the
    isolating-single-variable rule — LESSONS graduation ledger, 2026-08-29), the
    pre-fix entry hands the evaluator BOTH ``corporate`` and ``corporate_sme``
    while the live entry hands it one. ``v4240_i`` compares C 02.00 r0130 against
    the result: with two sheets it is compared against their sum, a figure that
    is in no submitted workbook.
    """
    # Arrange
    emitted = _MASKED_KEYS

    # Act
    before = resolve_sheet_codes((_MASKED_CODE,), _PRE_FIX_C07_SAMPLE, emitted)
    after = resolve_sheet_codes((_MASKED_CODE,), SHEET_INDEX_MAPS["c07"], emitted)

    # Assert
    assert before.sheets == _MASKED_KEYS, (
        f"the pre-fix z{_MASKED_CODE} entry resolved to {before.sheets} "
        f"(skip_reason={before.skip_reason!r}) rather than both sheets, so this test "
        "no longer demonstrates the summing that masked the defect"
    )
    assert len(after.sheets) == 1, (
        f"z{_MASKED_CODE} on the LIVE c07 map resolves to {after.sheets} - more than "
        "one sheet for one Art. 112(1) letter is the defect state, and every rule "
        "scoped to that code is now judged on a sum the publisher never asked for"
    )


# ---------------------------------------------------------------------------
# The arch-gate half of the graduation — a BLACK-BOX test of the shipped check
#
# The limbs above assert the invariant over the live maps. These assert the
# other half of P5.65: that ``scripts/arch_check.py`` carries a check which
# actually FINDS this defect, and that the gate runs it. They import and call
# the shipped function and read its findings — they do not re-derive its scan,
# and they do not inspect its source text. An earlier version of this section
# asserted only that some ``check_*`` function's source contained the substring
# ``bundle_key``; a check whose body was ``return []`` with the word in its
# docstring passed it, which is no gate at all.
#
# The must-flag input is not invented: it is ``scope.py`` exactly as it stood
# before the fix, whose correct verdict is human-judged and known. It is
# VENDORED rather than read through ``git show`` — the test then needs no git
# invocation, no history depth, and no network, and it behaves identically in a
# shallow CI clone and in a worktree. The ``.py.txt`` extension is load-bearing
# twice over: pytest does not collect it, ruff does not lint 1,100 lines of
# superseded source, and ``generate_confidence_matrix.py`` (which text-scans
# ``tests/**/*.py`` for article references) does not credit its citations to the
# test estate.
# ---------------------------------------------------------------------------

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
ARCH_CHECK_PATH: Final = REPO_ROOT / "scripts" / "arch_check.py"
SRC_ROOT: Final = REPO_ROOT / "src" / "rwa_calc"
LIVE_SCOPE_PATH: Final = SRC_ROOT / "reporting" / "validations" / "scope.py"

#: ``git show eb546935^:src/rwa_calc/reporting/validations/scope.py``, verbatim.
PRE_FIX_SAMPLE_PATH: Final = (
    Path(__file__).parent / "data" / "scope_pre_art112_class_axis_fix.py.txt"
)

#: A must-NOT-flag sample carrying all three legal cardinalities at once: an
#: entry with one key, an entry with none (a code we understand but do not
#: model — a skip, never a zero), and the many-to-one shape limb 2 protects, in
#: which two z-codes address one sheet of ours because the DPM's Art. 147(2)(d)
#: axis is finer than ours. The live control below carries these shapes too,
#: but only incidentally; stating them here means a check that banned the finer
#: IRB axis fails on the case it broke rather than somewhere downstream.
SAMPLE_LEGAL_CARDINALITIES: Final = '''\
"""Sample: every cardinality a SheetCode may legally carry."""

from __future__ import annotations

from typing import Final

from rwa_calc.reporting.validations.scope import SheetCode

_SAMPLE_SHEETS: Final[tuple[SheetCode, ...]] = (
    SheetCode("0001", "Total", (), "sample: understood, not modelled"),
    SheetCode("0006", "Art. 147(2)(b) institutions", ("institution",), "sample: one key"),
    SheetCode("0013", "Art. 147(2)(d) retail RE, SME", ("retail_mortgage",), "sample: finer axis"),
    SheetCode("0014", "Art. 147(2)(d) retail RE, non-SME", ("retail_mortgage",), "sample: finer axis"),
)
'''

#: The check's public entry point. Hardcoded, like ``_CHECK_NAME`` in the
#: sibling ``test_nested_window_gate.py``: the callable IS the contract, and a
#: rename should reach this file. Its private helpers are deliberately NOT named
#: anywhere here, so the check may be restructured freely.
_CHECK_NAME: Final = "check_sheet_code_single_bundle_key"

#: A check known to be registered today — adequacy control on the registration
#: extraction, so that assertion cannot pass for the wrong reason.
_KNOWN_REGISTERED_CHECK: Final = "check_no_polars_namespace_registrations"

#: ``(map identifier, z-code, the keys the entry wrongly gathered)`` for every
#: violation the pre-fix module contains. HUMAN-JUDGED by reading that source,
#: not produced by any scanner: six entries, three on each SA axis. The IRB
#: axes (``_C08_SHEETS`` / ``_OF08_SHEETS``) are clean in that revision too —
#: they carry the legitimate many-to-one shape limb 2 protects — so a check
#: that flagged six of the wrong things, or eight, fails here.
_EXPECTED_PRE_FIX_FINDINGS: Final[tuple[tuple[str, str, tuple[str, ...]], ...]] = (
    ("_C07_SHEETS", "0008", ("corporate", "corporate_sme")),
    ("_C07_SHEETS", "0009", ("retail_other", "retail_qrre")),
    (
        "_C07_SHEETS",
        "0010",
        ("retail_mortgage", "residential_mortgage", "commercial_mortgage"),
    ),
    ("_OF07_SHEETS", "0008", ("corporate", "corporate_sme")),
    ("_OF07_SHEETS", "0009", ("retail_other", "retail_qrre")),
    (
        "_OF07_SHEETS",
        "0010",
        ("retail_mortgage", "residential_mortgage", "commercial_mortgage"),
    ),
)


#: The map identifier and z-code a finding is ABOUT, read from its identifying
#: head. Matching the whole finding does not work and the reason is worth
#: recording: the check's remediation prose cites ``C 07.00 z0008 ... corporate
#: + corporate_sme`` as the worked example, so every finding contains that code
#: and those keys. A naive substring match therefore reports three matches for
#: one entry and would pass a check that flagged the wrong rows.
_FINDING_IDENTITY: Final = re.compile(r"(?P<map_name>_\w*SHEETS)\D*['\"](?P<code>\d{4})['\"]")


def _identifying_head(finding: str) -> str:
    """The part of a finding that IDENTIFIES the entry, before it explains itself.

    The contract asserted here is that a finding says WHAT is wrong before it
    says why — everything up to the first sentence break. A check that led with
    the explanation would fail the parse loudly rather than silently matching
    its own worked example.
    """
    return finding.split(". ", 1)[0]


def _load_arch_check():
    """Load ``scripts/arch_check.py`` by path, without polluting ``sys.path``."""
    spec = importlib.util.spec_from_file_location("_arch_check_p565", ARCH_CHECK_PATH)
    assert spec is not None and spec.loader is not None, f"cannot load {ARCH_CHECK_PATH}"
    module = importlib.util.module_from_spec(spec)
    sys.modules["_arch_check_p565"] = module
    spec.loader.exec_module(module)
    return module


def _cardinality_check():
    """The shipped check callable, failing on an ASSERTION when it is absent."""
    check = getattr(_load_arch_check(), _CHECK_NAME, None)
    assert check is not None, (
        f"scripts/arch_check.py does not define {_CHECK_NAME}(path: Path) -> list[str]. "
        "P5.65 graduates the one-bundle_key-per-sheet-code invariant into the arch "
        "gate; the limbs above still gate it in-suite, but only for whoever runs "
        "pytest. If the check was RENAMED, repoint _CHECK_NAME"
    )
    return check


def _run_check_over(source: str, tmp_path: Path) -> list[str]:
    """Run the shipped check over a throwaway package root holding ``source``.

    The sample is written to the sheet maps' real location inside the root the
    check is handed, because "where the maps live" is part of the check's input
    contract rather than an internal of it. A layout the check cannot find is
    not silently empty: it reports its own lost population, which every
    assertion below would fail on.
    """
    target = tmp_path / "reporting" / "validations"
    target.mkdir(parents=True, exist_ok=True)
    (target / "scope.py").write_text(source, encoding="utf-8")
    findings = _cardinality_check()(tmp_path)
    assert isinstance(findings, list), (
        f"{_CHECK_NAME} must return a list of finding strings, got {type(findings)!r}"
    )
    return findings


def test_check_22_flags_every_multi_key_entry_in_the_axis_that_shipped(tmp_path: Path) -> None:
    """The shipped check finds all six violations in the real pre-fix module.

    This is the check's discriminating power, measured on the source that
    actually reached production rather than on a sample written to suit it. Six
    is the whole verdict: the three ``_C07_SHEETS`` entries and their
    ``_OF07_SHEETS`` twins, with the two IRB axes clean.
    """
    # Arrange — adequacy: the vendored sample must still CONTAIN the six
    # offending literals, or it can no longer express the condition and this
    # test would report a green check as proven (LESSONS C11).
    assert PRE_FIX_SAMPLE_PATH.is_file(), (
        f"{PRE_FIX_SAMPLE_PATH} is missing - the must-flag sample is vendored, "
        "regenerate it with `git show eb546935^:src/rwa_calc/reporting/validations/scope.py`"
    )
    source = PRE_FIX_SAMPLE_PATH.read_text(encoding="utf-8")
    for _map_name, code, keys in _EXPECTED_PRE_FIX_FINDINGS:
        literal = ", ".join(f'"{key}"' for key in keys)
        assert literal in source, (
            f"the vendored sample no longer declares ({literal}) for z{code}, so it "
            "is not the pre-fix module any more and cannot prove the check flags it"
        )

    # Act
    findings = _run_check_over(source, tmp_path)

    # Assert
    assert len(findings) == len(_EXPECTED_PRE_FIX_FINDINGS), (
        f"expected {len(_EXPECTED_PRE_FIX_FINDINGS)} findings on the pre-fix sheet "
        f"axis, got {len(findings)}:\n" + "\n".join(findings)
    )
    identified = {}
    for finding in findings:
        head = _identifying_head(finding)
        match = _FINDING_IDENTITY.search(head)
        assert match is not None, (
            f"a finding no longer identifies its entry before explaining the rule, so "
            f"this test cannot tell WHICH entry it is about: {head!r}. Repoint "
            "_FINDING_IDENTITY at the new message shape"
        )
        identified[(match["map_name"], match["code"])] = head

    assert sorted(identified) == sorted((m, c) for m, c, _keys in _EXPECTED_PRE_FIX_FINDINGS), (
        "the check flagged a different set of entries than the pre-fix module "
        f"contains: {sorted(identified)}"
    )
    for map_name, code, keys in _EXPECTED_PRE_FIX_FINDINGS:
        head = identified[(map_name, code)]
        unnamed = [key for key in keys if key not in head]
        assert not unnamed, (
            f"the finding for {map_name} z{code} does not name the key(s) {unnamed} it "
            f"gathered, so a reader cannot see WHICH sheets are being summed: {head!r}"
        )


def test_check_22_permits_every_legal_cardinality(tmp_path: Path) -> None:
    """One key, no keys, and SEVERAL CODES ON ONE KEY are all left alone.

    The last of those is the direction that would cost real work if the check
    got it wrong: banning the finer Art. 147(2)(d) IRB axis would demand a
    rewrite of `_C08_SHEETS` / `_OF08_SHEETS` that the DPM does not support.
    """
    # Arrange — adequacy: the sample must still CARRY the shapes it exists to
    # clear, or it clears nothing (LESSONS C11).
    assert SAMPLE_LEGAL_CARDINALITIES.count('("retail_mortgage",)') == 2, (
        "the sample no longer gives two z-codes the same single bundle key, so it "
        "cannot show that the many-to-one shape is permitted"
    )
    assert '(), "sample' in SAMPLE_LEGAL_CARDINALITIES, (
        "the sample no longer carries an empty-tuple entry, so the 'understood but "
        "not modelled' cardinality is untested"
    )

    # Act
    findings = _run_check_over(SAMPLE_LEGAL_CARDINALITIES, tmp_path)

    # Assert
    assert findings == [], (
        "a legal sheet-code cardinality was flagged. One key is the norm, an empty "
        "tuple is a skip, and several codes sharing one of our keys is the publisher "
        "being finer than us - guarded at runtime by sheet_scope_not_closed, not by "
        "widening or splitting the map:\n" + "\n".join(findings)
    )


def test_check_22_passes_the_corrected_axis(tmp_path: Path) -> None:
    """The same harness, the same layout, the CURRENT module: no findings.

    Only the file's contents differ from the test above, so a check that
    returned findings unconditionally — or one whose harness never located the
    maps — cannot pass both. A check that flagged this would also ban the fix
    that PR #497 shipped.
    """
    # Arrange
    assert LIVE_SCOPE_PATH.is_file(), f"{LIVE_SCOPE_PATH} has moved - repoint the control"
    source = LIVE_SCOPE_PATH.read_text(encoding="utf-8")

    # Act
    findings = _run_check_over(source, tmp_path)

    # Assert
    assert findings == [], "the corrected sheet axis was flagged by the arch check:\n" + "\n".join(
        findings
    )


def test_check_22_is_clean_on_the_real_package_root() -> None:
    """The durable gate: the invariant holds across the whole shipped package.

    The two tests above run the check on one file in a synthetic tree; this
    runs it exactly as ``uv run python scripts/arch_check.py`` does, so a
    multi-key entry added to a sheet map in some other module is caught too.
    """
    # Arrange
    check = _cardinality_check()

    # Act
    findings = check(SRC_ROOT)

    # Assert
    assert findings == [], (
        "a SheetCode addresses more than one of our sheets. resolve_sheet_codes "
        "returns EVERY key for a scoped z-code and the evaluator sums the rule's "
        "reference across them, so the published rule is judged on a figure in no "
        "submitted workbook. Fix the sheet axis, never widen the map:\n" + "\n".join(findings)
    )


def test_check_22_is_registered_in_the_arch_check_run() -> None:
    """The check is dispatched by ``main()``, not merely defined.

    A check function nobody calls is a guard built and never wired — the pattern
    that produced ``arch_check`` check 20 — and it fails in the direction that
    matters, reading as a clean estate. Asserted by parsing ``main()`` so a
    mention in a comment or a docstring cannot satisfy it.
    """
    # Arrange — establish the check EXISTS first, so a failure below can only
    # mean "defined but never dispatched" and its message cannot mislead.
    _cardinality_check()
    tree = ast.parse(ARCH_CHECK_PATH.read_text(encoding="utf-8"))
    main_fn = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "main"), None
    )
    assert main_fn is not None, "scripts/arch_check.py no longer defines main()"

    # Act
    referenced = {n.id for n in ast.walk(main_fn) if isinstance(n, ast.Name)}

    # Assert — adequacy first: the extraction still sees a known registration.
    assert _KNOWN_REGISTERED_CHECK in referenced, (
        f"{_KNOWN_REGISTERED_CHECK} is registered today but this test cannot see it, "
        "so main() no longer dispatches checks as bare name references and this "
        "assertion has stopped measuring registration - repoint it"
    )
    assert _CHECK_NAME in referenced, (
        f"{_CHECK_NAME} is not referenced in scripts/arch_check.py::main(), so "
        "`uv run python scripts/arch_check.py` never runs it - the check exists and "
        "the gate is still blind to the defect it was written for"
    )
