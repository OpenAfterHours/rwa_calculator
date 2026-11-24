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

And three defects that corrupted the published scorecard (P5.46). A mutant no
gate caught while a gate TIMED OUT was scored ``ESCAPED`` (or ``UNREACHABLE`` when
the probe called it dead) — an escape resting on a gate that never finished; it
is now ``UNPROVEN``, outside the rate and every list but its own, and still a
trust failure in the ratchet. ``--resume`` overwrote ``--out`` with only the
mutants it had just run; it now writes the union, re-measures anything unsettled,
and refuses a file measured on another ladder, gate list, interpreter, mode,
commit or digest. And the scorecard was written once, at the end, into a
directory nothing had checked: an unwritable ``--out`` is now refused before
anything runs, and the file is replaced after every scored mutant -- written
beside ``--out`` and renamed over it, so an interrupt mid-write cannot leave a
file ``--resume`` refuses. A resume narrower than the earlier file (a campaign
chunked by ``--categories``) keeps every earlier result, and a run WITHOUT
``--resume`` merges nothing.

References:
- scripts/defect_injection.py — ``output_digest``, ``canonical_column``,
  ``stable_baseline``, ``_score_mutant``, ``scorecard``, ``is_settled``,
  ``refuse_incompatible``, ``earlier_to_merge``, ``resume_plan``, ``main``
- docs/development/defect-injection.md
"""

from __future__ import annotations

import json
import os
import sys
from contextlib import nullcontext
from dataclasses import asdict
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


# =============================================================================
# P5.46 — a timed-out gate, --resume, and a scorecard that survives an abort
# =============================================================================

_RED = defect_injection.OUTCOME_RED
_GREEN = defect_injection.OUTCOME_GREEN
_TIMEOUT = defect_injection.OUTCOME_TIMEOUT
_NARROW, _WIDE, _COMMIT = "n" * 64, "w" * 64, "c" * 40


def _stub_ladder(
    monkeypatch: pytest.MonkeyPatch, reachable: bool, outcomes: dict[str, str]
) -> None:
    """Stub the probe, the injection and each named gate's outcome; no file is touched."""
    monkeypatch.setattr(
        defect_injection, "probe_reachable", lambda *_args, **_kw: (reachable, "d", 0.0)
    )
    monkeypatch.setattr(defect_injection, "injected", lambda _mutant: nullcontext())
    monkeypatch.setattr(
        defect_injection,
        "run_gate",
        lambda gate, _dir: defect_injection.GateResult(
            gate.name, gate.tier, outcomes[gate.name], None, 0.0
        ),
    )


def _score(mutant: Mutant, gate_names: tuple[str, ...]) -> defect_injection.MutantResult:
    return defect_injection._score_mutant(
        mutant,
        tuple(_gate(name, tier) for tier, name in enumerate(gate_names)),
        Path("unused"),
        "d",
        reachability_only=False,
        wide_baseline_digest=None,
    )


@pytest.mark.parametrize(
    ("reachable", "ladder"),
    [
        (True, (("unit", _TIMEOUT),)),
        (False, (("unit", _TIMEOUT),)),
        (True, (("arch_check", _GREEN), ("unit", _TIMEOUT))),
        (False, (("unit", _TIMEOUT), ("contracts", _GREEN))),
    ],
    ids=["reachable-only-gate", "probe-dead-only-gate", "reachable-last-gate", "probe-dead-first"],
)
def test_a_mutant_no_gate_caught_is_unproven_while_any_gate_timed_out(
    monkeypatch: pytest.MonkeyPatch, reachable: bool, ladder: tuple[tuple[str, str], ...]
) -> None:
    """A gate that never finished licenses neither ESCAPED nor UNREACHABLE.

    The probe-dead rows matter as much as the reachable ones: a gate can catch a
    mutant the probe calls dead, so a dead path with a timed-out gate is as
    unproven as an escape with one.
    """
    # Arrange
    _stub_ladder(monkeypatch, reachable, dict(ladder))

    # Act
    result = _score(CATALOGUE[0], tuple(name for name, _ in ladder))

    # Assert
    assert result.verdict not in (
        defect_injection.VERDICT_ESCAPED,
        defect_injection.VERDICT_UNREACHABLE,
    ), f"a timed-out gate was scored as a measurement: {result.verdict}"
    assert result.verdict == defect_injection.VERDICT_UNPROVEN
    assert (result.reachable, result.caught_by) == (reachable, None)


def test_a_red_gate_after_a_timed_out_one_is_still_a_detection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A timeout does not stop the ladder, and a later red rung is a measured catch."""
    # Arrange
    _stub_ladder(monkeypatch, True, {"unit": _TIMEOUT, "contracts": _RED})

    # Act
    result = _score(CATALOGUE[0], ("unit", "contracts"))

    # Assert
    assert (result.verdict, result.caught_by) == (defect_injection.VERDICT_DETECTED, "contracts")


def test_an_unproven_mutant_stays_out_of_the_escape_list_and_the_rate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only a mutant every gate FINISHED green on is published as an escape."""
    # Arrange — two mutants no gate caught; for the second the only gate timed out.
    real, timed_out = CATALOGUE[0], CATALOGUE[1]
    _stub_ladder(monkeypatch, True, {"unit": _GREEN})
    escaped = _score(real, ("unit",))
    _stub_ladder(monkeypatch, True, {"unit": _TIMEOUT})
    unproven = _score(timed_out, ("unit",))

    # Act
    board = defect_injection.scorecard([escaped, unproven])

    # Assert
    assert [entry["id"] for entry in board["escaped_list"]] == [real.id]
    assert (board["scored"], board["escaped"], board["detection_rate"]) == (1, 1, 0.0)
    assert board["unreachable_list"] == []
    assert board["unproven_list"] == [
        {
            "id": timed_out.id,
            "category": timed_out.category,
            "summary": timed_out.summary,
            "timed_out": ["unit"],
        }
    ]


def test_the_ratchet_refuses_an_unproven_mutant_rather_than_banking_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The new verdict is a trust failure, never something the ratchet can bank."""
    # Arrange — a complete scorecard, one entry replaced by a harness-scored timeout.
    _stub_ladder(monkeypatch, True, {"unit": _TIMEOUT})
    mutant = next(m for m in CATALOGUE if not m.expect_unreachable)
    path = _scorecard(tmp_path, control_reachable=False)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["results"] = [
        asdict(_score(mutant, ("unit",))) if entry["mutant_id"] == mutant.id else entry
        for entry in payload["results"]
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")
    board = injection_ratchet.load_board(path)

    # Act
    failures = injection_ratchet.trust_failures(board)

    # Assert
    assert mutant.id not in board.escaped
    assert any(f"{mutant.id}={defect_injection.VERDICT_UNPROVEN}" in f for f in failures), failures


def _result(mutant: Mutant, verdict: str, *outcomes: str) -> defect_injection.MutantResult:
    """A scored mutant, with one ``unit`` gate per outcome given."""
    return defect_injection.MutantResult(
        mutant.id,
        mutant.category,
        mutant.summary,
        verdict,
        reachable=True,
        caught_by="unit" if verdict == defect_injection.VERDICT_DETECTED else None,
        gates=[defect_injection.GateResult("unit", 3, outcome, None, 0.0) for outcome in outcomes],
    )


def _write_earlier(
    path: Path, results: list[defect_injection.MutantResult], **overrides: object
) -> None:
    """An earlier ``--ladder legacy`` scorecard from this commit and this estate."""
    payload = {
        "ladder": "legacy",
        "interpreter": "uv run",
        "gates": [gate.name for gate in defect_injection.ladder_for("legacy")[1]],
        "reachability_only": False,
        "commit": _COMMIT,
        "baseline_digest": _NARROW,
        "wide_baseline_digest": _WIDE,
        "runtime_seconds": 10.0,
        "scorecard": defect_injection.scorecard(results),
        "results": [asdict(result) for result in results],
        **overrides,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _stub_main(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *argv: str) -> list[str]:
    """Stub everything ``main()`` measures with; returns the order things were touched."""
    touched: list[str] = []
    monkeypatch.delenv(defect_injection.INTERPRETER_ENV_VAR, raising=False)
    monkeypatch.setattr(defect_injection, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(defect_injection, "_ALLOWED_ROOT", tmp_path)
    monkeypatch.setattr(
        defect_injection, "assert_targets_clean", lambda: touched.append("assert_targets_clean")
    )
    monkeypatch.setattr(defect_injection, "preflight", lambda: touched.append("preflight"))
    monkeypatch.setattr(
        defect_injection,
        "stable_baseline",
        lambda portfolios=("rich",): _WIDE if portfolios is None else _NARROW,
    )
    monkeypatch.setattr(defect_injection, "_prepare_gate_baselines", lambda *_args: None)
    monkeypatch.setattr(defect_injection, "head_commit", lambda: _COMMIT, raising=False)
    _set_argv(monkeypatch, *argv)
    return touched


def _set_argv(monkeypatch: pytest.MonkeyPatch, *argv: str) -> None:
    """The command line the next ``main()`` call parses."""
    monkeypatch.setattr(sys, "argv", ["defect_injection.py", "--ladder", "legacy", *argv])


def _stub_campaign(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Replace the ladder walk: every mutant asked for is DETECTED. Returns what was asked."""
    asked: list[list[str]] = []

    def _campaign(
        mutants: list[Mutant], *_args: object, **_kw: object
    ) -> list[defect_injection.MutantResult]:
        asked.append([mutant.id for mutant in mutants])
        return [_result(m, defect_injection.VERDICT_DETECTED, _RED) for m in mutants]

    monkeypatch.setattr(defect_injection, "run_campaign", _campaign)
    return asked


def test_resume_writes_the_union_of_the_earlier_and_the_new_results(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A resumed scorecard is the whole campaign, not the tail of it."""
    # Arrange
    a, b, c = CATALOGUE[0], CATALOGUE[1], CATALOGUE[2]
    out = tmp_path / "scorecard.json"
    _write_earlier(
        out,
        [
            _result(a, defect_injection.VERDICT_DETECTED, _RED),
            _result(b, defect_injection.VERDICT_ESCAPED, _GREEN),
        ],
    )
    _stub_main(monkeypatch, tmp_path, "--mutants", a.id, b.id, c.id, "--out", str(out), "--resume")
    asked = _stub_campaign(monkeypatch)

    # Act
    code = defect_injection.main()

    # Assert
    written = json.loads(out.read_text(encoding="utf-8"))
    verdicts = {entry["mutant_id"]: entry["verdict"] for entry in written["results"]}
    assert code == 0
    assert asked == [[c.id]], "a settled verdict must not be re-measured"
    assert verdicts == {
        a.id: defect_injection.VERDICT_DETECTED,
        b.id: defect_injection.VERDICT_ESCAPED,
        c.id: defect_injection.VERDICT_DETECTED,
    }
    assert (written["scorecard"]["mutants_total"], written["scorecard"]["detected"]) == (3, 2)
    assert [entry["id"] for entry in written["scorecard"]["escaped_list"]] == [b.id]


@pytest.mark.parametrize(
    ("verdict", "outcomes"),
    [
        (defect_injection.VERDICT_ERROR, ()),
        ("UNPROVEN", (_GREEN, _TIMEOUT)),
        # What a pre-fix harness wrote for a timed-out gate: an escape resting on it.
        (defect_injection.VERDICT_ESCAPED, (_TIMEOUT,)),
        (defect_injection.VERDICT_UNREACHABLE, (_TIMEOUT,)),
        # A real catch, but the ratchet refuses ANY timeout: kept, it could never clear.
        (defect_injection.VERDICT_DETECTED, (_TIMEOUT, _RED)),
    ],
    ids=[
        "error",
        "unproven",
        "escaped-on-a-timeout",
        "unreachable-on-a-timeout",
        "detected-after-a-timeout",
    ],
)
def test_resume_re_measures_a_verdict_that_was_never_settled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, verdict: str, outcomes: tuple[str, ...]
) -> None:
    """Only a verdict every gate finished on is skipped; anything else runs again."""
    # Arrange
    a, b = CATALOGUE[0], CATALOGUE[1]
    out = tmp_path / "scorecard.json"
    _write_earlier(
        out,
        [_result(a, defect_injection.VERDICT_DETECTED, _RED), _result(b, verdict, *outcomes)],
    )
    _stub_main(monkeypatch, tmp_path, "--mutants", a.id, b.id, "--out", str(out), "--resume")
    asked = _stub_campaign(monkeypatch)

    # Act
    code = defect_injection.main()

    # Assert
    written = json.loads(out.read_text(encoding="utf-8"))
    verdicts = {entry["mutant_id"]: entry["verdict"] for entry in written["results"]}
    assert code == 0
    assert asked == [[b.id]]
    assert verdicts == {
        a.id: defect_injection.VERDICT_DETECTED,
        b.id: defect_injection.VERDICT_DETECTED,
    }


@pytest.mark.parametrize(
    ("key", "value", "known_before_measuring"),
    [
        ("ladder", "full", True),
        ("gates", ["unit"], True),
        ("interpreter", "/elsewhere/python", True),
        ("reachability_only", True, True),
        ("commit", "d" * 40, True),
        # The digests exist only once the baselines are captured.
        ("baseline_digest", "x" * 64, False),
        ("wide_baseline_digest", "y" * 64, False),
    ],
)
def test_resume_refuses_to_merge_a_scorecard_measured_on_something_else(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    key: str,
    value: object,
    known_before_measuring: bool,
) -> None:
    """Merging measurements of two estates would publish one bankable-looking fiction."""
    # Arrange
    a, b = CATALOGUE[0], CATALOGUE[1]
    out = tmp_path / "scorecard.json"
    _write_earlier(out, [_result(a, defect_injection.VERDICT_DETECTED, _RED)], **{key: value})
    before = out.read_bytes()
    touched = _stub_main(
        monkeypatch, tmp_path, "--mutants", a.id, b.id, "--out", str(out), "--resume"
    )
    asked = _stub_campaign(monkeypatch)

    # Act
    code = defect_injection.main()

    # Assert
    assert code != 0
    assert asked == []
    assert out.read_bytes() == before
    assert ("preflight" in touched) is not known_before_measuring, (
        "a mismatch knowable from the file alone must be refused before anything is spawned"
    )


#: Every field a scorecard records about how it was measured, written out rather
#: than read from the harness: a key dropped there must not drop its row here.
_PROVENANCE = (
    "ladder",
    "interpreter",
    "gates",
    "reachability_only",
    "commit",
    "baseline_digest",
    "wide_baseline_digest",
)

#: What a scorecard written before ``--resume`` merged does not record at all.
_RECORDED_ONLY_SINCE_RESUME_MERGED = ("reachability_only", "commit", "wide_baseline_digest")


def _probe_results(*mutants: Mutant) -> list[defect_injection.MutantResult]:
    """What a ``--reachability-only`` run scores: a probe verdict, and no gate at all."""
    return [
        defect_injection.MutantResult(
            mutant.id,
            mutant.category,
            mutant.summary,
            defect_injection.VERDICT_UNREACHABLE if mutant.expect_unreachable else "PROBED",
            reachable=not mutant.expect_unreachable,
        )
        for mutant in mutants
    ]


@pytest.mark.parametrize(
    ("probe_only_earlier", "missing"),
    [
        # Exactly what the pre-fix harness wrote, from each mode. The probe-only
        # one holds an UNREACHABLE with no gates: kept by a gated resume, it would
        # be banked as a verdict that never faced a gate.
        (True, _RECORDED_ONLY_SINCE_RESUME_MERGED),
        (False, _RECORDED_ONLY_SINCE_RESUME_MERGED),
        # And any one provenance field absent: absent is never the same as matching.
        *((False, (key,)) for key in _PROVENANCE),
    ],
    ids=[
        "pre-fix-reachability-only",
        "pre-fix-gated",
        *(f"no-{key}" for key in _PROVENANCE),
    ],
)
def test_resume_refuses_a_scorecard_that_does_not_record_how_it_was_measured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    probe_only_earlier: bool,
    missing: tuple[str, ...],
) -> None:
    """A field the earlier file does not record cannot be shown to match, so it is refused."""
    # Arrange — an earlier file holding verdicts a resume would otherwise keep.
    reachable = next(m for m in CATALOGUE if not m.expect_unreachable)
    control = next(m for m in CATALOGUE if m.expect_unreachable)
    out = tmp_path / "scorecard.json"
    _write_earlier(
        out,
        _probe_results(reachable, control)
        if probe_only_earlier
        else [_result(reachable, defect_injection.VERDICT_DETECTED, _RED)],
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    for key in missing:
        del payload[key]
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    before = out.read_bytes()
    _stub_main(
        monkeypatch, tmp_path, "--mutants", reachable.id, control.id, "--out", str(out), "--resume"
    )
    asked = _stub_campaign(monkeypatch)

    # Act
    code = defect_injection.main()

    # Assert
    assert code != 0, "an earlier verdict was carried into the merge as settled"
    assert asked == []
    assert out.read_bytes() == before


def test_resume_checks_every_field_these_rows_cover() -> None:
    """A provenance field added to the harness needs a row above, and one dropped is caught."""
    # Arrange / Act
    checked = defect_injection.PROVENANCE_KEYS

    # Assert
    assert checked == _PROVENANCE


def test_a_reachability_only_resume_keeps_its_probe_verdicts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``PROBED`` and ``UNREACHABLE`` settle a probe-only run: only the missing are probed."""
    # Arrange — an earlier probe-only file holding two of the three selected mutants.
    reachable = [m for m in CATALOGUE if not m.expect_unreachable][:2]
    control = next(m for m in CATALOGUE if m.expect_unreachable)
    out = tmp_path / "scorecard.json"
    _write_earlier(out, _probe_results(reachable[0], control), reachability_only=True)
    selected = (reachable[0].id, control.id, reachable[1].id)
    _stub_main(
        monkeypatch,
        tmp_path,
        "--reachability-only",
        "--resume",
        "--out",
        str(out),
        "--mutants",
        *selected,
    )
    asked = _stub_campaign(monkeypatch)

    # Act
    code = defect_injection.main()

    # Assert
    assert code == 0
    assert asked == [[reachable[1].id]]


@pytest.mark.parametrize("existing_directory", [False, True], ids=["parent-missing", "a-directory"])
def test_an_out_that_cannot_be_a_file_is_refused_before_anything_is_measured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, existing_directory: bool
) -> None:
    """Hours of measurement must not end in a write that cannot happen."""
    # Arrange — --out in a directory that does not exist, or --out IS a directory.
    out = tmp_path / "scorecards" if existing_directory else tmp_path / "missing" / "x.json"
    if existing_directory:
        out.mkdir()
    touched = _stub_main(monkeypatch, tmp_path, "--mutants", CATALOGUE[0].id, "--out", str(out))
    asked = _stub_campaign(monkeypatch)

    # Act
    code = defect_injection.main()

    # Assert
    assert code != 0
    assert (touched, asked) == ([], [])
    created = sorted(path.name for path in tmp_path.iterdir())
    assert created == (["scorecards"] if existing_directory else []), "nothing may be created"


@pytest.mark.skipif(
    not hasattr(os, "geteuid") or os.geteuid() == 0,
    reason="mode bits bind only a non-root POSIX user: root writes through them",
)
@pytest.mark.parametrize("read_only", ["file", "directory", "directory-of-a-writable-file"])
def test_a_read_only_out_is_refused_before_anything_is_measured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, read_only: str
) -> None:
    """An existing scorecard, or a directory, the harness may not write is refused up front.

    A writable scorecard in a read-only directory is refused too: every checkpoint
    is created beside ``--out`` and renamed over it, which the directory must allow.
    """
    # Arrange — a read-only earlier scorecard, or a read-only directory to write one into.
    directory = tmp_path / "scorecards"
    directory.mkdir()
    out = directory / "scorecard.json"
    if read_only != "directory":
        out.write_text("{}\n", encoding="utf-8")
    if read_only == "file":
        out.chmod(0o444)
    else:
        directory.chmod(0o555)
    touched = _stub_main(monkeypatch, tmp_path, "--mutants", CATALOGUE[0].id, "--out", str(out))
    asked = _stub_campaign(monkeypatch)

    # Act
    code = defect_injection.main()

    # Assert
    assert code != 0
    assert (touched, asked) == ([], [])


class _Abort(RuntimeError):
    """Stands in for anything that kills a campaign part-way: a crash, a Ctrl-C."""


def _score_until(monkeypatch: pytest.MonkeyPatch, abort_on: str | None) -> list[str]:
    """Stub per-mutant scoring under the REAL ladder walk and checkpoint.

    Every mutant is DETECTED until ``abort_on``, which raises ``_Abort``. Returns the
    ids scored, the aborted one included.
    """
    scored: list[str] = []

    def _score_or_abort(mutant: Mutant, *_args: object, **_kw: object) -> object:
        scored.append(mutant.id)
        if mutant.id == abort_on:
            raise _Abort(mutant.id)
        return _result(mutant, defect_injection.VERDICT_DETECTED, _RED)

    monkeypatch.setattr(defect_injection, "_score_mutant", _score_or_abort)
    return scored


def _written_ids(out: Path) -> tuple[list[str], int]:
    """The mutant ids the scorecard at ``out`` holds, and the total its board counts."""
    written = json.loads(out.read_text(encoding="utf-8"))
    ids = [entry["mutant_id"] for entry in written["results"]]
    return ids, written["scorecard"]["mutants_total"]


def test_every_scored_mutant_is_on_disk_before_the_next_one_starts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A campaign that dies on mutant N keeps mutants 1..N-1, ready for --resume.

    It dies on the THIRD mutant: by then "every result so far" and "the latest
    result" are different lists, so a checkpoint holding only the latest fails.
    """
    # Arrange
    a, b, c = CATALOGUE[0], CATALOGUE[1], CATALOGUE[2]
    out = tmp_path / "scorecard.json"
    _stub_main(monkeypatch, tmp_path, "--mutants", a.id, b.id, c.id, "--out", str(out))
    scored = _score_until(monkeypatch, abort_on=c.id)

    # Act
    with pytest.raises(_Abort):
        defect_injection.main()

    # Assert
    assert scored == [a.id, b.id, c.id]
    assert _written_ids(out) == ([a.id, b.id], 2)


def test_a_checkpoint_interrupted_mid_write_leaves_the_previous_one_whole(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The scorecard is replaced whole, never rewritten in place.

    Written in place, an interrupt between truncating ``--out`` and finishing the
    write leaves a file ``--resume`` cannot read, and every measured result goes
    with it. Each checkpoint is written beside ``--out`` and renamed over it, so
    an interrupt at the rename -- the last moment before the new one lands --
    leaves the previous checkpoint readable.
    """
    # Arrange — the second checkpoint (A and B) is interrupted at its rename.
    a, b, c = CATALOGUE[0], CATALOGUE[1], CATALOGUE[2]
    out = tmp_path / "scorecard.json"
    _stub_main(monkeypatch, tmp_path, "--mutants", a.id, b.id, c.id, "--out", str(out))
    _score_until(monkeypatch, abort_on=None)
    renames: list[str] = []
    real_replace = os.replace

    def _interrupt_second(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        if Path(dst) == out:
            renames.append(Path(src).name)
            if len(renames) == 2:
                raise _Abort("interrupted mid-checkpoint")
        real_replace(src, dst)

    monkeypatch.setattr(defect_injection.os, "replace", _interrupt_second)

    # Act
    with pytest.raises(_Abort):
        defect_injection.main()

    # Assert — the file --resume reads is the first checkpoint, whole.
    earlier = defect_injection.read_earlier(out)
    assert len(renames) == 2
    assert out.name not in renames, "each checkpoint is written beside --out, not into it"
    assert earlier is not None
    assert [result.mutant_id for result in earlier.results] == [a.id]


def test_a_resumed_campaign_that_dies_keeps_the_earlier_results_and_the_new_ones(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The checkpoint a RESUMED run writes is the union too, not this run's tail.

    Otherwise a resume that dies part-way overwrites the earlier file with only
    what it has just measured -- the truncation ``--resume`` was fixed to stop.
    """
    # Arrange — the earlier file holds A and B; this run measures C, then dies on D.
    a, b, c, d = CATALOGUE[0], CATALOGUE[1], CATALOGUE[2], CATALOGUE[3]
    out = tmp_path / "scorecard.json"
    _write_earlier(
        out,
        [
            _result(a, defect_injection.VERDICT_DETECTED, _RED),
            _result(b, defect_injection.VERDICT_ESCAPED, _GREEN),
        ],
    )
    selection = ("--mutants", a.id, b.id, c.id, d.id, "--out", str(out), "--resume")
    _stub_main(monkeypatch, tmp_path, *selection)
    scored = _score_until(monkeypatch, abort_on=d.id)

    # Act
    with pytest.raises(_Abort):
        defect_injection.main()

    # Assert
    assert scored == [c.id, d.id]
    assert _written_ids(out) == ([a.id, b.id, c.id], 3)


def test_resume_finishes_a_campaign_the_harness_itself_left_part_way(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``main()`` resumes the file ``main()`` wrote, measuring only what it never finished.

    No hand-written scorecard: what is read back is exactly what the harness
    checkpointed, so a provenance key the writer drops, or a checkpoint holding
    less than every result so far, fails here rather than on the first real resume.
    """
    # Arrange — a first run over A, B and C dies on C, leaving its own checkpoint.
    a, b, c = CATALOGUE[0], CATALOGUE[1], CATALOGUE[2]
    out = tmp_path / "scorecard.json"
    selection = ("--mutants", a.id, b.id, c.id, "--out", str(out))
    _stub_main(monkeypatch, tmp_path, *selection)
    _score_until(monkeypatch, abort_on=c.id)
    with pytest.raises(_Abort):
        defect_injection.main()
    _set_argv(monkeypatch, *selection, "--resume")
    scored = _score_until(monkeypatch, abort_on=None)

    # Act
    code = defect_injection.main()

    # Assert
    assert code == 0
    assert scored == [c.id], "only the mutant the first run never finished is measured"
    assert _written_ids(out) == ([a.id, b.id, c.id], 3)


@pytest.mark.parametrize(
    "earlier_c_outcome",
    [None, _TIMEOUT],
    ids=["disjoint-from-the-earlier-file", "narrowed-to-the-one-a-gate-timed-out-on"],
)
def test_resume_keeps_the_earlier_results_this_run_did_not_select(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, earlier_c_outcome: str | None
) -> None:
    """A resume narrower than the earlier file still writes the whole file back.

    The other resume rows select a superset of the earlier file, where "the
    union" and "this run's selection" are one list. Here the earlier file holds
    A and B -- and, narrowed, a C a gate timed out on, the re-run the ratchet's
    own TIMEOUT message asks for -- and this run selects only C. Keeping only the
    selected earlier results would erase A and B.
    """
    # Arrange
    a, b, c = CATALOGUE[0], CATALOGUE[1], CATALOGUE[2]
    out = tmp_path / "scorecard.json"
    earlier = [
        _result(a, defect_injection.VERDICT_DETECTED, _RED),
        _result(b, defect_injection.VERDICT_ESCAPED, _GREEN),
    ]
    if earlier_c_outcome is not None:
        # The literal, as the other UNPROVEN rows: the unfixed harness has no constant.
        earlier.append(_result(c, "UNPROVEN", earlier_c_outcome))
    _write_earlier(out, earlier)
    _stub_main(monkeypatch, tmp_path, "--mutants", c.id, "--out", str(out), "--resume")
    asked = _stub_campaign(monkeypatch)

    # Act
    code = defect_injection.main()

    # Assert
    written = json.loads(out.read_text(encoding="utf-8"))
    verdicts = {entry["mutant_id"]: entry["verdict"] for entry in written["results"]}
    assert code == 0
    assert asked == [[c.id]]
    assert verdicts == {
        a.id: defect_injection.VERDICT_DETECTED,
        b.id: defect_injection.VERDICT_ESCAPED,
        c.id: defect_injection.VERDICT_DETECTED,
    }
    assert written["scorecard"]["mutants_total"] == 3
    assert [entry["id"] for entry in written["scorecard"]["escaped_list"]] == [b.id]


def test_a_campaign_chunked_by_category_resumes_into_one_scorecard(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """LESSONS G: a campaign too long for one window is chunked with ``--categories``.

    Each later chunk resumes into the same ``--out`` and selects only its own
    category, so none of the earlier chunk's mutants is in its selection. The
    file it leaves must hold every chunk, under the REAL ladder walk and
    checkpoint.
    """
    # Arrange — chunk 1 measures the known defects into a fresh --out.
    chunks = ("known_defect", "lessons")
    out = tmp_path / "scorecard.json"
    _stub_main(monkeypatch, tmp_path, "--categories", chunks[0], "--out", str(out))
    _score_until(monkeypatch, abort_on=None)
    first = defect_injection.main()
    _set_argv(monkeypatch, "--categories", chunks[1], "--out", str(out), "--resume")
    scored = _score_until(monkeypatch, abort_on=None)

    # Act
    second = defect_injection.main()

    # Assert
    both = [mutant.id for mutant in CATALOGUE if mutant.category in chunks]
    assert (first, second) == (0, 0)
    assert scored == [mutant.id for mutant in CATALOGUE if mutant.category == chunks[1]]
    assert _written_ids(out) == (both, len(both))


def test_a_run_without_resume_replaces_a_compatible_scorecard_rather_than_merging(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without ``--resume`` the earlier file -- even one this run could merge -- is replaced.

    Re-running ``--mutants A`` to see whether a new, uncommitted test now catches
    an escape must measure A. A run that merged anyway would keep the old
    ``ESCAPED`` as settled, measure nothing, and report the escape as still open.
    """
    # Arrange — same ladder, gates, interpreter, mode, commit and digests as this run.
    a, b = CATALOGUE[0], CATALOGUE[1]
    out = tmp_path / "scorecard.json"
    _write_earlier(
        out,
        [
            _result(a, defect_injection.VERDICT_ESCAPED, _GREEN),
            _result(b, defect_injection.VERDICT_DETECTED, _RED),
        ],
    )
    _stub_main(monkeypatch, tmp_path, "--mutants", a.id, "--out", str(out))
    asked = _stub_campaign(monkeypatch)

    # Act
    code = defect_injection.main()

    # Assert
    written = json.loads(out.read_text(encoding="utf-8"))
    assert code == 0
    assert asked == [[a.id]], "every selected mutant is measured"
    assert [(entry["mutant_id"], entry["verdict"]) for entry in written["results"]] == [
        (a.id, defect_injection.VERDICT_DETECTED)
    ], "nothing is carried from the earlier file"
    assert written["scorecard"]["mutants_total"] == 1
