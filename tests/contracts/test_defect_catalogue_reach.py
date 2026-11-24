"""
The defect-injection probe can see every catalogue site: none in dead code, Pillar 3 hashed.

Pipeline position:
    (no pipeline stage — a contract on ``scripts/defect_catalogue.py`` and on the
    reachability probe in ``scripts/defect_injection.py``, the ``Nightly Defect
    Injection`` campaign)

A mutant the catalogue expects to be reachable must move something the probe
hashes, or the nightly lists it under "expectation mismatches" and its verdict
rests on whichever unit test happens to reach its path (P5.76). Four mutants did,
on both ladders, for two different reasons:

- ``generic-scaling-regime-inverted`` edited
  ``engine/irb/formulas.py::calculate_irb_rwa``, a scalar wrapper kept "for
  backward compatibility" that nothing in ``src/`` calls (only the CRR
  expected-output workbook does). No portfolio can reach a function the pipeline
  never calls. That is checkable from the source alone, and is checked here for
  the whole catalogue — by bare name, so as a necessary condition only (see
  ``_uncalled_enclosing_function``).

That check must give the same answer whether or not a mutant is applied. The
campaign's ``contracts`` rung collects this file with one mutant applied, and on
that tree the applied mutant's ``old`` string is gone. A check that located each
site by ``old`` alone raised there on the applied mutant's own case, so every
mutant reaching the rung scored ``DETECTED`` by this file — a detection of the
harness, not of the defect, which leaves ``ESCAPED`` and ``UNREACHABLE``
impossible past tier 3 (``.claude/LESSONS.md`` C12; measured on 19 of the 19
reachable-expected mutants). So every catalogue target is read with any applied
catalogue mutant undone (``_unmutated``), which needs no campaign marker and so
also holds in a scratch copy, and a guard applies each of the 22 mutants in turn
and requires every verdict to stay as it is on the clean tree.
- ``known-p3-empty-class-tuple`` edited a Pillar 3 row, and the probe hashed
  nothing from Pillar 3: ``output_digest`` passed the Pillar 3 bundle to
  ``build_template_index``, which indexes the COREP tables the published rules
  address and drops Pillar 3 by design. Measured on ``rich``: binding CR4/CR5
  row 6 (institutions) to no class moved the digest not at all, with 2,000,000 of
  SA institution exposure in each regime. Every Pillar 3 mutant was therefore
  probe-dead wherever it pointed. The probe now hashes the Pillar 3 bundle too,
  in ``digest_run``, which is tested here directly: a regression there would
  still let a gate score the mutant ``DETECTED``, and show only on the mismatch
  list (``.claude/LESSONS.md`` B9).

The other two (the RGLA sovereign predicate and the CRM benefit cap) sat on paths
no RUNS portfolio exercises — a null ``cp_sovereign_cqs`` and no third-party
deposit anywhere. That is data, not source, so only the probe itself can measure
it; the re-targeted sites are measured in the P5.76 record.

References:
- scripts/defect_catalogue.py; scripts/defect_injection.py — ``output_digest``,
  ``digest_run``, ``pillar3_frames``, ``digest_frame``, ``injected``
- tests/contracts/test_defect_catalogue_applies.py — the per-PR self-test, which
  skips inside a campaign for the same reason this check undoes the mutant
- docs/development/defect-injection.md — "What the first bank was waiting on",
  "Re-targeted under P5.76"
- .claude/LESSONS.md B4 (presence before value), B9, C12 (a vacuous mutation
  reads as "undetected"; a probe that goes red for the wrong reason)
"""

from __future__ import annotations

import ast
import hashlib
import sys
from dataclasses import fields
from functools import cache
from pathlib import Path
from types import UnionType
from typing import Any, NamedTuple, Union, get_args, get_origin, get_type_hints

import polars as pl
import pytest
from scripts import defect_injection
from scripts.defect_catalogue import CATALOGUE, Mutant

from rwa_calc.reporting.pillar3.generator import Pillar3TemplateBundle

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src" / "rwa_calc"

#: Every mutant the catalogue expects to move output. The ``expect_unreachable``
#: controls are dead on purpose and are judged on the probe, not here.
_EXPECTED_REACHABLE: tuple[Mutant, ...] = tuple(m for m in CATALOGUE if not m.expect_unreachable)

#: The two ``Pillar3TemplateBundle`` fields that are not disclosure templates.
#: Spelled out here rather than read from the script, so a template wrongly
#: listed as a non-template there still fails the presence test below.
_NON_TEMPLATE_FIELDS = frozenset({"framework", "errors"})


class _Reference(NamedTuple):
    """One load of a name somewhere under ``src/rwa_calc``."""

    path: str
    line: int


class _StubIndex(NamedTuple):
    """The one part of a filing ``TemplateIndex`` that ``digest_run`` reads."""

    frames: dict[str, dict[str, pl.DataFrame]]


# ---------------------------------------------------------------------------
# A mutant expected to be reachable does not sit in a function nothing calls
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mutant", _EXPECTED_REACHABLE, ids=lambda m: m.id)
def test_no_mutant_expected_reachable_sits_in_a_function_nothing_calls(mutant: Mutant) -> None:
    """The name of the function enclosing a reachable-expected edit is loaded under ``src/``.

    A re-export in an ``__init__`` or a name in ``__all__`` is not a call, and nor
    is a call from inside the function itself: none of them can run it. Matched
    by bare name, so this is necessary, not sufficient — see
    ``_uncalled_enclosing_function`` for the two ways it can be wrong. Read with
    any applied catalogue mutant undone, so the answer is the clean tree's inside
    a campaign too (see the guard below).
    """
    # Arrange
    tree = _working_tree()

    # Act
    dead = _dead_enclosing_functions(tree)[mutant.id]

    # Assert
    assert dead is None, (
        f"{mutant.id} edits {mutant.target}::{dead}, whose name nothing under src/ loads, so "
        "no portfolio can reach it and the probe will call it dead. Re-target it at the live "
        "site that does the same job."
    )


def test_the_dead_code_check_flags_an_uncalled_function_and_passes_a_called_one() -> None:
    """The check discriminates: the same edit is flagged in a dead function only.

    Without this, a check that returned ``None`` for everything would pass the
    parametrised test above on every mutant (``.claude/LESSONS.md`` B9).
    """
    # Arrange
    source = "def live():\n    rate = 1.06\n\n\ndef dead():\n    rate = 1.0\n    return dead()\n"
    references = {
        "live": (_Reference("caller.py", 3),),
        "dead": (_Reference("module.py", 7),),  # its own recursive call only
    }

    # Act
    in_live = _uncalled_enclosing_function(source, "rate = 1.06", "module.py", references)
    in_dead = _uncalled_enclosing_function(source, "rate = 1.0\n", "module.py", references)
    at_module_level = _uncalled_enclosing_function("RATE = 1.0\n", "RATE", "m.py", references)

    # Assert
    assert in_live is None
    assert in_dead == "dead"
    assert at_module_level is None, "a module-level site is the probe's to judge, not this check's"


@pytest.mark.parametrize("applied", CATALOGUE, ids=lambda m: m.id)
def test_applying_a_catalogue_mutant_changes_no_verdict_of_the_dead_code_check(
    applied: Mutant,
) -> None:
    """With any one catalogue mutant applied, the check reads exactly as on the clean tree.

    That is the tree the campaign's ``contracts`` rung collects this file on, one
    mutant at a time. A verdict that moved there, or a check that raised, would
    score the applied mutant ``DETECTED`` by this file whatever the mutant does,
    and nothing past tier 3 could then score ``ESCAPED`` or ``UNREACHABLE``.
    Every mutant is applied, the ``expect_unreachable`` controls included: the
    campaign applies them too.
    """
    # Arrange
    clean = _clean_tree()
    original = clean[applied.target]
    mutated = {**clean, applied.target: original.replace(applied.old, applied.new)}

    # Act
    undone = _unmutated(mutated[applied.target], applied.target)
    verdicts = _dead_enclosing_functions(mutated)

    # Assert
    assert undone == original, f"{applied.id} is not undone exactly, so the check sees it"
    assert verdicts == _dead_enclosing_functions(clean)


def test_the_guard_goes_red_when_the_applied_mutant_is_left_in_place(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without ``_unmutated`` the check breaks on the applied mutant's own case.

    The control for the guard above, and the defect it guards against: a check
    that locates each site by its ``old`` string cannot find the one the campaign
    has just replaced. Before the undo, this file went red on 19 of the 19
    reachable-expected mutants applied in turn, for that reason alone.
    """
    # Arrange
    applied = next(m for m in CATALOGUE if m.id == "known-sovereign-ladder-flattened")
    clean = _clean_tree()
    mutated = {**clean, applied.target: clean[applied.target].replace(applied.old, applied.new)}
    monkeypatch.setattr(sys.modules[__name__], "_unmutated", lambda source, target: source)

    # Act / Assert
    with pytest.raises(ValueError, match=r"is not in src/rwa_calc/engine/sa/rgla\.py"):
        _dead_enclosing_functions(mutated)


# ---------------------------------------------------------------------------
# The probe digest covers Pillar 3
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("half", ["corep", "pillar3"])
def test_a_cell_that_empties_moves_the_run_digest(half: str) -> None:
    """One cell going from 2,000,000 to empty moves ``digest_run``, in either half.

    The ``pillar3`` case is the P5.76 measurement in miniature: CR4 row 6 bound
    to no class reports nothing where it reported the exposure. Before P5.76 the
    probe could not tell those apart, so every Pillar 3 mutant probed dead.
    """
    # Arrange
    schema = {"row_ref": pl.String, "a": pl.Float64}
    populated = pl.DataFrame({"row_ref": ["6"], "a": [2_000_000.0]}, schema=schema)
    emptied = pl.DataFrame({"row_ref": ["6"], "a": [None]}, schema=schema)
    if half == "pillar3":
        runs = [
            (_StubIndex(frames={}), Pillar3TemplateBundle(cr4=frame))
            for frame in (populated, emptied)
        ]
    else:
        runs = [
            (_StubIndex(frames={"c07": {"total": frame}}), Pillar3TemplateBundle())
            for frame in (populated, emptied)
        ]

    # Act
    digests = [_run_digest(index, bundle) for index, bundle in runs]

    # Assert
    assert digests[0] != digests[1]


def test_every_pillar3_template_field_reaches_the_probe() -> None:
    """On a bundle with every template populated, every template field is hashed.

    Presence before value (``.claude/LESSONS.md`` B4). The bundle is built from
    the dataclass's own annotations, so a template added later in a new shape
    (a ``LazyFrame``, a nested per-class dict) is populated here and must reach
    the probe too, or be refused loudly — never skipped.
    """
    # Arrange
    hints = get_type_hints(Pillar3TemplateBundle)
    templates = {spec.name for spec in fields(Pillar3TemplateBundle)} - _NON_TEMPLATE_FIELDS
    bundle = Pillar3TemplateBundle(**{name: _populated(hints[name]) for name in templates})

    # Act
    labels = [label for label, _ in defect_injection.pillar3_frames(bundle)]

    # Assert
    assert {label.split("/")[0] for label in labels} == templates


@pytest.mark.parametrize(
    ("template", "value"),
    [
        pytest.param("cr4", pl.LazyFrame({"a": [1.0]}), id="lazyframe"),
        pytest.param("cr6", {"corporate": {"nested": pl.DataFrame({"a": [1.0]})}}, id="nested"),
    ],
)
def test_a_pillar3_template_the_probe_cannot_hash_is_refused(template: str, value: Any) -> None:
    """A template in a shape the probe cannot read raises, naming the field.

    Skipping it would blind the probe to that template with nothing to show for
    it: a gate would still catch a mutant there and score it ``DETECTED``.
    """
    # Arrange
    bundle = Pillar3TemplateBundle(**{template: value})

    # Act / Assert
    with pytest.raises(TypeError, match=rf"Pillar3TemplateBundle\.{template}\b"):
        list(defect_injection.pillar3_frames(bundle))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_digest(index: _StubIndex, bundle: Pillar3TemplateBundle) -> str:
    """One run's digest through the probe's own ``digest_run``."""
    digest = hashlib.sha256()
    defect_injection.digest_run(digest, "crr", index, bundle)
    return digest.hexdigest()


def _populated(hint: Any) -> Any:
    """A non-empty value of an annotated type, so the field cannot read as absent."""
    if hint is pl.DataFrame:
        return pl.DataFrame({"row_ref": ["1"], "a": [1.0]})
    if hint is pl.LazyFrame:
        return pl.LazyFrame({"row_ref": ["1"], "a": [1.0]})
    if hint in (str, int, float, bool):
        return hint()
    origin, args = get_origin(hint), get_args(hint)
    if origin in (UnionType, Union):
        return _populated(next(arg for arg in args if arg is not type(None)))
    if origin is dict:
        return {"sheet": _populated(args[1])}
    if origin is list:
        return [_populated(args[0])]
    pytest.fail(f"no populated value for a {hint!r} template field: teach _populated the shape")


def _uncalled_enclosing_function(
    source: str,
    old: str,
    target: str,
    references: dict[str, tuple[_Reference, ...]],
) -> str | None:
    """The innermost function around ``old`` when nothing outside it names it, else None.

    ``source`` is the target's clean text: ``old`` must occur in it, or the
    catalogue has drifted and this raises ``ValueError``. ``None`` too for a site
    at module level (a pack entry, a row map): whether that is read is a
    question for the probe.

    Callers are matched by bare name, not resolved through imports, so a
    ``None`` is a necessary condition for a live call, not proof of one. It can
    be wrong both ways:

    - **A silent pass.** A same-named function elsewhere keeps a dead one
      green. ``apply_guarantee_substitution``, which encloses
      ``generic-benefit-cap-inverted``, is defined four times under ``src/``
      (``sa/rw_adjustments``, ``irb/guarantee``, ``irb/transforms``,
      ``slotting/transforms``): were the SA one dead, the others' callers
      would still count.
    - **A false red.** A caller that loads only an import alias is not counted.
      Slotting calls the SA function as ``sa_apply_guarantee_substitution``;
      were that its only caller, it would be flagged.

    It catches what it was written for, a wrapper whose name nothing under
    ``src/`` loads at all. The probe remains the measure of reachability.
    """
    function = _enclosing_function(source, old, target)
    if function is None:
        return None
    span = range(function.lineno, (function.end_lineno or function.lineno) + 1)
    callers = [
        ref
        for ref in references.get(function.name, ())
        if not (ref.path == target and ref.line in span)
    ]
    return None if callers else function.name


@cache
def _enclosing_function(
    source: str, old: str, target: str
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """The innermost function whose lines hold all of ``old``, or None at module level.

    Raises ``ValueError`` when ``old`` is not in ``source``: the catalogue has
    drifted, and the per-PR self-test says where.
    """
    if old not in source:
        raise ValueError(
            f"the catalogue edit {old!r} is not in {target}, so the catalogue has drifted; "
            "tests/contracts/test_defect_catalogue_applies.py reports where"
        )
    start = source[: source.index(old)].count("\n") + 1
    end = start + old.count("\n")
    enclosing = [
        node
        for node in ast.walk(_parsed(source))
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.lineno <= start
        and (node.end_lineno or node.lineno) >= end
    ]
    return max(enclosing, key=lambda node: node.lineno) if enclosing else None


def _dead_enclosing_functions(files: dict[str, str]) -> dict[str, str | None]:
    """Each reachable-expected mutant's id, mapped to the uncalled function it edits, or None.

    ``files`` maps every repo-relative path under ``src/rwa_calc`` to its text.
    Each is read with any applied catalogue mutant undone (``_unmutated``), the
    edit sites and the callers alike, so a tree with one mutant applied gives
    the clean tree's answer.
    """
    clean = {path: _unmutated(text, path) for path, text in files.items()}
    names = {
        function.name
        for mutant in _EXPECTED_REACHABLE
        if (function := _enclosing_function(clean[mutant.target], mutant.old, mutant.target))
    }
    references = _references(clean, names)
    return {
        mutant.id: _uncalled_enclosing_function(
            clean[mutant.target], mutant.old, mutant.target, references
        )
        for mutant in _EXPECTED_REACHABLE
    }


def _unmutated(source: str, target: str) -> str:
    """``source`` with the catalogue mutant applied to ``target``, if one is, undone.

    A mutant counts as applied when its ``new`` occurs exactly once and undoing
    it leaves its ``old`` exactly once — the state ``injected`` leaves behind,
    and the self-test's own condition on a clean tree. Read from the text alone,
    not from the campaign's ``DEFECT_INJECTION_MUTANT`` marker, so a scratch copy
    with a mutant applied by hand reads the same as a campaign gate. Two mutants
    share an ``old`` (the corporate-correlation pair); the one whose ``new`` is
    present is the one undone. The guard proves the undo exact for every
    catalogue mutant.
    """
    for mutant in CATALOGUE:
        if mutant.target != target or source.count(mutant.new) != 1:
            continue
        undone = source.replace(mutant.new, mutant.old)
        if undone.count(mutant.old) == 1:
            return undone
    return source


def _references(files: dict[str, str], names: set[str]) -> dict[str, tuple[_Reference, ...]]:
    """Every load of one of ``names`` in ``files``, as a ``Name`` or an ``Attribute``.

    Import aliases and ``__all__`` strings are not ``Name`` nodes, so a
    re-export alone never counts as a caller — and nor does a load of an alias
    (``import f as g`` then ``g()`` records ``g``, not ``f``).
    """
    return {
        name: tuple(
            _Reference(path, line)
            for path in sorted(files)
            for line in _loaded_names(files[path]).get(name, ())
        )
        for name in sorted(names)
    }


@cache
def _working_tree() -> dict[str, str]:
    """Every ``.py`` file under ``src/rwa_calc`` as it is on disk, by repo-relative path."""
    return {
        path.relative_to(_REPO_ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(_SRC.rglob("*.py"))
    }


@cache
def _clean_tree() -> dict[str, str]:
    """``_working_tree`` with any applied catalogue mutant undone: the tree a campaign started on."""
    return {path: _unmutated(text, path) for path, text in _working_tree().items()}


@cache
def _loaded_names(source: str) -> dict[str, tuple[int, ...]]:
    """The line of every loaded ``Name`` and ``Attribute`` in one file's text, by bare name."""
    found: dict[str, list[int]] = {}
    for node in ast.walk(_parsed(source)):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            found.setdefault(node.id, []).append(node.lineno)
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            found.setdefault(node.attr, []).append(node.lineno)
    return {name: tuple(lines) for name, lines in found.items()}


@cache
def _parsed(source: str) -> ast.Module:
    """One file's syntax tree, parsed once per distinct text."""
    return ast.parse(source)
