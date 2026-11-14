"""
The defect-injection reachability probe: noise must not move it, a change must.

Pipeline position:
    (no pipeline stage — a contract on ``scripts/defect_injection.py``, the
    nightly ``Nightly Defect Injection`` campaign's reachability probe)

The probe scores a mutant REACHABLE when the digest of every generated template
cell differs from the unmutated baseline. The digest hashed ``str()`` of raw
floats, and the pipeline's parallel sums are not bit-reproducible: two unmutated
captures in one process rendered one Basel 3.1 C 09.01 cell as
``51355833.333333336`` and then ``51355833.33333333``. So the digest moved on
every call and every mutant probed REACHABLE. The three ``expect_unreachable``
mutants (``control-unreachable-output-floor-full``, ``generic-correlation-decay``,
``generic-retail-correlation-decay``) came back reachable night after night, and
no mutant was ever escalated from the narrow probe to the whole RUNS matrix.

Two fixes, two tests each way: floats are hashed at fixed precision
(``canonical_column``), and each baseline is captured twice and refused unless
the captures agree (``stable_baseline``), so if noise ever returns above that
precision, the campaign aborts instead of scoring.

Found while verifying those: ``injected`` restored a target by writing back its
DECODED text, which turns CRLF into LF, and then compared text, so it called the
file restored. ``engine/irb/formulas.py`` is committed with CRLF endings; one
probe run left it dirty, and the campaign refuses to start on a dirty target.

And what the noise had been hiding: the harness skipped the gates for any mutant
the probe called unreachable. The probe sees only the RUNS portfolios' templates,
so with a stable digest 11 of 22 mutants moved nothing there — including two
known defects that a unit-test gate DETECTED the night before. Gates now run on
every mutant; the probe only separates an escape from a dead path among the
mutants no gate caught, and the ratchet judges the controls on the probe's own
result rather than on the verdict.

References:
- scripts/defect_injection.py — ``output_digest``, ``canonical_column``,
  ``stable_baseline``
- docs/development/defect-injection.md
"""

from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path

import pytest
from scripts import defect_injection, injection_ratchet
from scripts.defect_catalogue import CATALOGUE, Mutant

#: The pair measured on two unmutated captures of the Basel 3.1 C 09.01 GB sheet.
_MEASURED_NOISE = (51355833.333333336, 51355833.33333333)


def test_float_reassociation_noise_does_not_move_the_digest() -> None:
    """The measured last-bit difference, and a signed zero, render identically."""
    # Arrange
    before, after = _MEASURED_NOISE

    # Act
    rendered = {
        "noise": (
            defect_injection.canonical_column([before]),
            defect_injection.canonical_column([after]),
        ),
        "signed_zero": (
            defect_injection.canonical_column([0.0]),
            defect_injection.canonical_column([-0.0]),
        ),
    }

    # Assert
    assert before != after, "the measured pair must genuinely differ, or this proves nothing"
    for name, (left, right) in rendered.items():
        assert left == right, f"{name}: {left} != {right}"


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ([51355833.33], [51355833.33 * (1 + 1e-9)]),  # the smallest change a gate could see
        ([1.0e-12], [2.0e-12]),  # magnitude does not matter, figures do
        ([None], [0.0]),  # an empty cell is not a zero
        ([0], [0.0]),  # nor is an integer a float
        (["0"], [0.0]),  # nor a string
        ([1.0, 2.0], [2.0, 1.0]),  # nor is a reordered column the same column
    ],
)
def test_a_change_a_gate_could_see_still_moves_the_digest(
    left: list[object], right: list[object]
) -> None:
    """Fixed precision must not blind the probe to a real mutant's effect."""
    # Act
    rendered_left = defect_injection.canonical_column(left)
    rendered_right = defect_injection.canonical_column(right)

    # Assert
    assert rendered_left != rendered_right


def test_an_unstable_probe_aborts_before_any_mutant_is_scored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two disagreeing captures of the unmutated estate refuse the baseline."""
    # Arrange
    captures = iter(["a" * 64, "b" * 64])
    monkeypatch.setattr(defect_injection, "output_digest", lambda *_: next(captures))

    # Act / Assert
    with pytest.raises(defect_injection.ProbeUnstable, match="not deterministic"):
        defect_injection.stable_baseline()


def test_a_stable_probe_returns_its_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Agreeing captures pass straight through: the check costs one capture, no more."""
    # Arrange
    calls: list[object] = []

    def _capture(*args: object) -> str:
        calls.append(args)
        return "c" * 64

    monkeypatch.setattr(defect_injection, "output_digest", _capture)

    # Act
    baseline = defect_injection.stable_baseline(portfolios=None)

    # Assert
    assert baseline == "c" * 64
    assert calls == [(None,), (None,)]


def test_a_crlf_target_comes_back_byte_for_byte(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The mutant lands in the file's own newline style and the bytes are restored."""
    # Arrange — a CRLF module, declared as the only mutation target.
    target = tmp_path / "pkg" / "mod.py"
    target.parent.mkdir()
    original = b"a = 1\r\nb = 2\r\n"
    target.write_bytes(original)
    monkeypatch.setattr(defect_injection, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(defect_injection, "targets", lambda: frozenset({"pkg/mod.py"}))
    mutant = Mutant(
        id="test-crlf",
        category="generic",
        target="pkg/mod.py",
        old="b = 2",
        new="b = 3",
        summary="a one-line edit to a CRLF file",
        rationale="restoration must be byte-exact",
    )

    # Act
    with defect_injection.injected(mutant):
        mutated = target.read_bytes()
    restored = target.read_bytes()

    # Assert
    assert mutated == b"a = 1\r\nb = 3\r\n"
    assert restored == original


def _gate(name: str = "unit", tier: int = 1) -> defect_injection.Gate:
    return defect_injection.Gate(name, tier, ("true",), legacy=True)


@pytest.mark.parametrize(
    ("reachable", "outcome", "verdict"),
    [
        (False, defect_injection.OUTCOME_RED, defect_injection.VERDICT_DETECTED),
        (True, defect_injection.OUTCOME_RED, defect_injection.VERDICT_DETECTED),
        (True, defect_injection.OUTCOME_GREEN, defect_injection.VERDICT_ESCAPED),
        (False, defect_injection.OUTCOME_GREEN, defect_injection.VERDICT_UNREACHABLE),
    ],
)
def test_a_gate_decides_detection_and_the_probe_only_separates_escapes_from_dead_paths(
    monkeypatch: pytest.MonkeyPatch, reachable: bool, outcome: str, verdict: str
) -> None:
    """A red gate is a detection whatever the probe says; the probe only labels the greens."""
    # Arrange — no file is touched: the probe, the injection and the gate are stubbed.
    mutant = CATALOGUE[0]
    monkeypatch.setattr(
        defect_injection, "probe_reachable", lambda *_args, **_kw: (reachable, "d", 0.0)
    )
    monkeypatch.setattr(defect_injection, "injected", lambda _mutant: nullcontext())
    monkeypatch.setattr(
        defect_injection,
        "run_gate",
        lambda gate, _dir: defect_injection.GateResult(gate.name, gate.tier, outcome, 0, 0.0),
    )

    # Act
    result = defect_injection._score_mutant(
        mutant,
        (_gate(),),
        Path("unused"),
        "d",
        reachability_only=False,
        wide_baseline_digest=None,
    )

    # Assert
    assert (result.verdict, result.reachable) == (verdict, reachable)


def _scorecard(tmp_path: Path, control_reachable: bool) -> Path:
    """A complete legacy scorecard whose unreachable control a GATE caught."""
    results = []
    for mutant in CATALOGUE:
        dead = mutant.expect_unreachable
        results.append(
            {
                "mutant_id": mutant.id,
                "category": mutant.category,
                "summary": mutant.summary,
                "verdict": defect_injection.VERDICT_UNREACHABLE
                if dead
                else defect_injection.VERDICT_DETECTED,
                "reachable": not dead,
                "caught_by": None if dead else "unit",
                "gates": [],
                "note": "",
            }
        )
    control = next(r for r in results if r["mutant_id"] == "control-unreachable-output-floor-full")
    control.update(
        verdict=defect_injection.VERDICT_DETECTED,
        caught_by="contracts",
        reachable=control_reachable,
    )
    path = tmp_path / "scorecard-legacy.json"
    path.write_text(
        json.dumps(
            {
                "ladder": "legacy",
                "interpreter": "uv run",
                "gates": ["unit"],
                "runtime_seconds": 1.0,
                "scorecard": {
                    "mutants_total": len(results),
                    "detection_rate": 1.0,
                    "mean_tier_of_detection": 1.0,
                },
                "results": results,
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize(
    ("control_reachable", "contradicted"),
    [(False, False), (True, True)],
)
def test_the_unreachable_control_is_judged_on_the_probe_not_on_the_verdict(
    tmp_path: Path, control_reachable: bool, contradicted: bool
) -> None:
    """A gate catching the dead-path control is not the probe failing; the probe moving is."""
    # Arrange
    board = injection_ratchet.load_board(_scorecard(tmp_path, control_reachable))

    # Act
    failures = injection_ratchet.trust_failures(board)

    # Assert
    flagged = [f for f in failures if "flagged expect_unreachable came back reachable" in f]
    assert bool(flagged) is contradicted, failures
    if contradicted:
        assert "control-unreachable-output-floor-full" in flagged[0]
