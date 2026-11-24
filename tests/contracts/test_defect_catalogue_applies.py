"""
The defect-injection catalogue must still apply to the tree every PR leaves behind.

Pipeline position:
    (no pipeline stage — a per-PR contract on ``scripts/defect_catalogue.py``, the
    mutant list the nightly ``Nightly Defect Injection`` campaign walks)

Each catalogue mutant names an ``old`` string that must occur exactly once in its
``target``. When a refactor moves that string, the mutant no longer applies and
the nightly dies at its first step, ``defect_injection.py --self-test``, about 13
seconds in. Nothing per-PR ran that step, so the drift was invisible until the
next night: the CCF carrier ladder left ``corep/c07.py`` for
``corep/ccf_buckets.py`` and the corporate correlation moved into
``engine/irb/formulas.py::_corporate_correlation_expr_from_pd``, and the nightly
died in the self-test on five consecutive nights (2026-11-17 to 2026-11-21, run
44891852087: ``FAIL lessons-b1-dead-carrier: 'old' string not found in
src/rwa_calc/reporting/corep/c07.py``).

While the detection-rate baseline was un-banked that only kept an always-red
nightly red. Once the baseline is banked, the same drift turns the real gate red
with no PR to blame. So the self-test runs here, in the dev loop and in CI's
``test`` job, on the change that moves the string — whose author is the one who
knows where it went. The fix is to re-target the mutant in
``scripts/defect_catalogue.py`` (and to bank the re-measured verdict after the
next campaign), never to restore the old source.

The one place it must NOT run is inside the campaign. The campaign's
``contracts`` rung collects this file while a mutant is applied, and on that tree
the applied mutant's ``old`` string is gone by construction. Scored there, the
self-test went red on every mutant that reached the rung — a detection of the
harness, not of the defect — so ESCAPED and UNREACHABLE became impossible
verdicts and the banked board went stale on the first night. ``injected`` names
the applied mutant in ``DEFECT_INJECTION_MUTANT`` and the self-test skips under
it; the nightly has already run the same check on the clean tree as its first
step, and ``injected`` refuses a mutant whose ``old`` string is not unique.

References:
- scripts/defect_injection.py — ``self_test``, ``injected``, ``mutant_under_campaign``
- docs/development/defect-injection.md — "Adding a mutant", "Catalogue drift"
- .claude/LESSONS.md B9 — an alarm that always fires carries no information
- .claude/LESSONS.md C12 — a probe that goes red for the wrong reason
"""

from __future__ import annotations

import dataclasses
import sys
from typing import TYPE_CHECKING

import pytest
from scripts import defect_injection
from scripts.defect_catalogue import Mutant

if TYPE_CHECKING:
    from pathlib import Path

#: A stand-in target: one line that occurs once, one that occurs twice.
_TARGET = "src/target.py"
_SOURCE = "WEIGHT = 0.5\nCAP = min(a, b)\nFLOOR = max(a, b)\nCAP = min(a, b)\n"

#: The sound mutant each drift is derived from. It applies to ``_SOURCE``.
_SOUND = Mutant(
    id="drift-probe",
    category="generic",
    target=_TARGET,
    old="WEIGHT = 0.5",
    new="WEIGHT = 0.6",
    summary="stand-in",
    rationale="stand-in",
)


def test_every_catalogue_mutant_still_applies_to_this_tree(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The nightly's first step, run on every change instead of once a night.

    Skipped only inside a campaign gate, where the applied mutant is drift by
    construction (see the module docstring).
    """
    # Arrange
    applied = defect_injection.mutant_under_campaign()
    if applied is not None:
        pytest.skip(
            f"a defect-injection campaign has {applied.id} applied to this tree; the "
            "nightly ran this self-test on the clean tree before applying it"
        )

    # Act
    exit_code = defect_injection.self_test()
    report = capsys.readouterr().out

    # Assert
    assert exit_code == 0, (
        "the defect-injection catalogue no longer applies to this tree, so tonight's "
        "campaign will die in its self-test. Re-target each failing mutant in "
        "scripts/defect_catalogue.py at the code's new home (docs/development/"
        f"defect-injection.md, 'Adding a mutant'):\n{report}"
    )


@pytest.mark.parametrize(
    ("drifted", "expected"),
    [
        # The observed shape: the code moved and the `old` string went with it.
        pytest.param(
            dataclasses.replace(_SOUND, old="WEIGHT = 0.50"),
            "'old' string not found in",
            id="absent",
        ),
        # The edit would land on whichever copy comes first, not the intended one.
        pytest.param(
            dataclasses.replace(_SOUND, old="CAP = min(a, b)", new="CAP = max(a, b)"),
            "it must be unique",
            id="duplicated",
        ),
        # A mutant that changes nothing scores as a detection of nothing.
        pytest.param(
            dataclasses.replace(_SOUND, new=_SOUND.old),
            "replacement is a no-op",
            id="no-op",
        ),
        # The target itself is gone.
        pytest.param(
            dataclasses.replace(_SOUND, target="src/moved.py"),
            "does not exist",
            id="target-gone",
        ),
    ],
)
def test_a_drifted_mutant_fails_the_self_test(
    drifted: Mutant,
    expected: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The gate above can fail: each way a mutant stops applying is reported red."""
    # Arrange
    _plant_tree(tmp_path, monkeypatch, _SOURCE)
    assert defect_injection.self_test() == 0, "the sound mutant must pass, or this proves nothing"
    capsys.readouterr()
    monkeypatch.setattr(defect_injection, "CATALOGUE", (drifted,))

    # Act
    exit_code = defect_injection.self_test()
    report = capsys.readouterr().out

    # Assert
    assert exit_code == 1, report
    assert f"FAIL {drifted.id}: " in report
    assert expected in report


def test_the_self_test_is_not_scored_on_a_campaigns_mutated_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Inside ``injected``, the per-PR self-test skips instead of failing the gate.

    This is the state the campaign's ``contracts`` rung runs it in. Before the
    marker it failed there on the applied mutant's own missing ``old`` string, so
    every mutant that reached that rung scored DETECTED by this file.
    """
    # Arrange
    _plant_tree(tmp_path, monkeypatch, _SOURCE)

    # Act
    with defect_injection.injected(_SOUND), pytest.raises(pytest.skip.Exception) as skipped:
        test_every_catalogue_mutant_still_applies_to_this_tree(capsys)

    # Assert
    assert f"has {_SOUND.id} applied to this tree" in str(skipped.value)


def test_the_same_mutated_bytes_outside_a_campaign_are_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The control for the test above: only the campaign's marker makes it skip.

    The tree holds exactly the bytes ``injected`` writes, but nothing applied them,
    so it is drift and the self-test must still go red.
    """
    # Arrange
    _plant_tree(tmp_path, monkeypatch, _SOURCE.replace(_SOUND.old, _SOUND.new))
    assert defect_injection.mutant_under_campaign() is None, "no campaign marker is set here"

    # Act / Assert — a skip is a BaseException that pytest.raises lets through, and
    # a skipped guard reads as a pass in CI, so a skip here is turned into a failure.
    try:
        with pytest.raises(AssertionError, match=f"FAIL {_SOUND.id}: 'old' string not found"):
            test_every_catalogue_mutant_still_applies_to_this_tree(capsys)
    except pytest.skip.Exception as skipped:
        pytest.fail(f"the self-test skipped outside a campaign: {skipped}")


def test_injected_names_its_mutant_to_every_gate_and_only_while_applied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A gate spawned by ``run_gate`` inherits the marker inside ``injected``, not after it."""
    # Arrange
    _plant_tree(tmp_path, monkeypatch, _SOURCE)
    monkeypatch.setenv(defect_injection.INTERPRETER_ENV_VAR, sys.executable)
    # Green only when the spawned gate inherits the marker naming _SOUND.
    reads_marker = (
        "import os, sys; sys.exit(0 if os.environ.get("
        f"{defect_injection.MUTANT_ENV_VAR!r}) == {_SOUND.id!r} else 1)"
    )
    probe = defect_injection.Gate(
        "marker-probe", 4, ("uv", "run", "python", "-c", reads_marker), legacy=True
    )

    # Act
    with defect_injection.injected(_SOUND):
        inside = defect_injection.run_gate(probe, tmp_path)
    after = defect_injection.run_gate(probe, tmp_path)

    # Assert
    assert (inside.outcome, after.outcome) == (
        defect_injection.OUTCOME_GREEN,
        defect_injection.OUTCOME_RED,
    ), (inside.excerpt, after.excerpt)


def test_a_marker_naming_no_catalogue_mutant_does_not_skip_the_self_test(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A stray or misspelt marker is refused, so it cannot switch the self-test off."""
    # Arrange
    monkeypatch.setenv(defect_injection.MUTANT_ENV_VAR, "no-such-mutant")

    # Act / Assert — a skip would pass in CI, so it is turned into a failure.
    try:
        with pytest.raises(ValueError, match="names no mutant"):
            test_every_catalogue_mutant_still_applies_to_this_tree(capsys)
    except pytest.skip.Exception as skipped:
        pytest.fail(f"a marker naming no catalogue mutant switched the self-test off: {skipped}")


def _plant_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str) -> None:
    """Point the harness at a one-file tree whose catalogue is ``_SOUND`` alone.

    The marker is cleared, so a test run inside a real campaign gate starts from
    the same state as one run anywhere else.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / _TARGET).write_text(source, encoding="utf-8")
    monkeypatch.setattr(defect_injection, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(defect_injection, "CATALOGUE", (_SOUND,))
    monkeypatch.setattr(defect_injection, "targets", lambda: frozenset({_TARGET}))
    monkeypatch.delenv(defect_injection.MUTANT_ENV_VAR, raising=False)
