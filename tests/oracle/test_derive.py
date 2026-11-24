"""
Regeneration tests for ``tests/oracle/derive.py``.

Pipeline position:
    (none) -- harness tooling. ``derive.py`` writes ``expected_values.json``;
    ``test_oracle.py`` reads it.

Key responsibilities:
- Pin that regenerating the oracle file is clean: running ``derive.py`` over
  the committed file reproduces it text-for-text (key order, ``1`` vs ``1.0``
  and ``true`` vs ``1`` all count), so a regeneration diff always means a
  derivation changed and never means the interpreter did.
- Pin the float-noise splice that makes that possible. Where a freshly derived
  float differs from the committed one by no more than
  ``derive.FLOAT_NOISE_RELATIVE`` (relative), the committed value is kept;
  every other difference -- a real value move, a non-float leaf, an added or
  removed record or key -- is written as computed.

- Pin both of those whichever interpreter runs the suite. The gate is run
  under each normal-CDF form the standard library has used, and the splice's
  wiring is pinned on a file built from this interpreter's own output, so
  neither depends on which interpreter wrote the committed file.

Why: the standard library's normal CDF is computed differently across Python
versions (``0.5 * (1 + erf(x))`` up to 3.13, ``0.5 * erfc(-x)`` from 3.14), so
the IRB conditional PDs (and the risk weights and RWAs built on them) move in
their last bits from one interpreter family to the other. Before the splice
every regeneration on the other family rewrote untouched records, and the only
way to avoid an unexplained diff was to hand-restore them, which the README
update protocol forbids.

These tests deliberately name no regulatory article: the confidence matrix
scans the test tree as text, and nothing here is evidence about a rule.
"""

from __future__ import annotations

import copy
import json
import math
import statistics
from pathlib import Path
from typing import Any

import pytest

from tests.oracle import derive

HERE = Path(__file__).parent
JSON_PATH = HERE / "expected_values.json"

#: A leaf at the small end of the published range (an IRB risk weight) and one
#: at the large end (an RWA). Perturbing both pins that the threshold is
#: RELATIVE: any absolute threshold loose enough to keep last-bit drift on the
#: large leaf swallows a real 1e-9 move on the small one.
_SMALL = 0.031415926535897934
_LARGE = 1234567.8901234567

#: The smallest relative move the splice must still write: the oracle test
#: tolerance with five orders of magnitude of headroom below it, read from the
#: committed file so it follows the tolerance the oracle tests compare at.
_HEADROOM_FLOOR_MOVE = json.loads(JSON_PATH.read_text())["tolerance_relative"] / 1e5

#: The normal-CDF forms the gate runs under: the interpreter's own, then each
#: form the standard library has used (``erf`` in CPython 3.11 to 3.13,
#: ``erfc`` from 3.14). The committed file was written under one of the two, so
#: one patched case always regenerates it under the other family and so always
#: exercises the splice, whichever interpreter runs the suite.
_CDF_FORMS = ["interpreter", "erf-form", "erfc-form"]

#: The leaf the wiring tests move: a CRR F-IRB corporate risk weight, which is
#: built on the conditional PD and so is a leaf that drifts between families.
_IRB_RECORD = "ORC-084"
_IRB_KEY = "risk_weight"


def _record(oracle_id: str = "ORC-900", **expected: Any) -> dict[str, Any]:
    """A minimal oracle-shaped record; ``expected`` defaults to the two magnitudes."""
    return {
        "exposure_id": oracle_id,
        "framework": "CRR",
        "inputs": {"ead": 1000000.0, "is_sme": False},
        "expected": expected or {"risk_weight": _SMALL, "rwa": _LARGE},
        "unasserted": ["rwa"],
    }


def _ulps_up(value: float, count: int) -> float:
    """``value`` moved ``count`` representable doubles towards +inf."""
    for _ in range(count):
        value = math.nextafter(value, math.inf)
    return value


# =============================================================================
# The gate: regenerating the committed file is clean
# =============================================================================


@pytest.mark.parametrize("cdf_form", _CDF_FORMS)
def test_regeneration_reproduces_the_committed_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cdf_form: str
) -> None:
    """Running derive.py over the committed oracle file leaves it unchanged.

    Run under the interpreter's own normal CDF and under each form the standard
    library has used, so the file regenerates cleanly on either interpreter
    family whichever one wrote it. Compared as text, not as parsed dicts: dict
    equality ignores key order and treats 1, 1.0 and True as equal, and each of
    those is a diff the writer would produce. If this fails, either a
    derivation module (or the doc) was edited without re-running
    ``uv run python tests/oracle/derive.py`` -- run it, review the diff and
    commit the regenerated file with the edit -- or a derivation now moves a
    value by more than float noise under this CDF form, which is a real change
    to explain.
    """
    # Arrange
    _use_normal_cdf(monkeypatch, cdf_form)
    committed_text = JSON_PATH.read_text()
    target = tmp_path / "expected_values.json"
    target.write_text(committed_text)

    # Act
    derive.regenerate(target)

    # Assert
    regenerated = target.read_text()
    assert regenerated == committed_text, _first_differing_lines(committed_text, regenerated)


def test_regeneration_keeps_a_committed_float_that_differs_only_by_float_noise(
    tmp_path: Path,
) -> None:
    """A committed IRB float a few ULP from the derived one survives regeneration.

    Pins the wiring -- ``regenerate`` reads the file, ``build_payload`` splices
    against it -- on every interpreter. The file on disk is this interpreter's
    own derivation output with one leaf moved, so there is exactly one leaf to
    keep whichever interpreter runs this and whatever the committed file holds.
    """
    # Arrange
    derived = derive.build_payload(None)[0]
    value = _expected(derived)[_IRB_KEY]
    assert type(value) is float, f"{_IRB_RECORD} {_IRB_KEY} is no longer a float leaf"
    on_disk = copy.deepcopy(derived)
    _expected(on_disk)[_IRB_KEY] = _ulps_up(value, 3)
    on_disk_text = derive.render(on_disk)
    target = tmp_path / "expected_values.json"
    target.write_text(on_disk_text)

    # Act
    _, preserved = derive.regenerate(target)

    # Assert
    regenerated = target.read_text()
    assert regenerated == on_disk_text, _first_differing_lines(on_disk_text, regenerated)
    assert preserved == 1


def test_regeneration_overwrites_a_committed_float_that_differs_by_a_real_move(
    tmp_path: Path,
) -> None:
    """A committed IRB float 1e-9 (relative) from the derived one is rewritten."""
    # Arrange
    derived = derive.build_payload(None)[0]
    value = _expected(derived)[_IRB_KEY]
    on_disk = copy.deepcopy(derived)
    _expected(on_disk)[_IRB_KEY] = value * (1.0 + 1e-9)
    target = tmp_path / "expected_values.json"
    target.write_text(derive.render(on_disk))

    # Act
    _, preserved = derive.regenerate(target)

    # Assert
    regenerated = target.read_text()
    derived_text = derive.render(derived)
    assert regenerated == derived_text, _first_differing_lines(derived_text, regenerated)
    assert preserved == 0


def test_regeneration_without_a_committed_file_writes_every_value_as_computed(
    tmp_path: Path,
) -> None:
    """With nothing to splice against, the file is the plain derivation output."""
    # Arrange
    target = tmp_path / "expected_values.json"

    # Act
    payload, preserved = derive.regenerate(target)

    # Assert
    assert preserved == 0
    assert target.read_text() == derive.render(derive.build_payload(None)[0])
    assert payload["oracles"] == derive.build_payload(None)[0]["oracles"]


def test_float_noise_threshold_sits_far_below_the_oracle_tolerance() -> None:
    """A threshold near the 1e-6 test tolerance would swallow real corrections.

    The splice keeps a committed value only when the fresh one is within
    ``FLOAT_NOISE_RELATIVE``; at anything close to the tolerance the oracle
    tests compare at, a genuine derivation fix could be silently discarded and
    a stale expected value kept. Five orders of magnitude of headroom is the
    floor. This test reads the constant only; the ``tolerance-over-1e5`` case
    of ``test_a_real_value_move_is_written`` holds the splice itself to the
    same floor, so a comparison that stops using the constant fails there.
    """
    # Arrange
    tolerance = json.loads(JSON_PATH.read_text())["tolerance_relative"]

    # Act
    headroom = tolerance / derive.FLOAT_NOISE_RELATIVE

    # Assert
    assert headroom >= 1e5, (
        f"FLOAT_NOISE_RELATIVE={derive.FLOAT_NOISE_RELATIVE} leaves only "
        f"{headroom:.0f}x headroom below the oracle tolerance {tolerance}"
    )


# =============================================================================
# The splice: float noise is kept, everything else is written
# =============================================================================


@pytest.mark.parametrize("ulps", [1, 20])
@pytest.mark.parametrize("key", ["risk_weight", "rwa"])
def test_last_bit_drift_keeps_the_committed_float(key: str, ulps: int) -> None:
    """A fresh float a few ULP from the committed one keeps the committed bytes."""
    # Arrange
    committed = [_record()]
    fresh = copy.deepcopy(committed)
    fresh[0]["expected"][key] = _ulps_up(committed[0]["expected"][key], ulps)

    # Act
    spliced, preserved = derive.splice_float_noise(committed, fresh)

    # Assert
    assert spliced[0]["expected"][key] == committed[0]["expected"][key]
    assert repr(spliced[0]["expected"][key]) == repr(committed[0]["expected"][key])
    assert preserved == 1


@pytest.mark.parametrize(
    "relative_move",
    [1e-9, _HEADROOM_FLOOR_MOVE],
    ids=["1e-9", "tolerance-over-1e5"],
)
@pytest.mark.parametrize("key", ["risk_weight", "rwa"])
def test_a_real_value_move_is_written(key: str, relative_move: float) -> None:
    """A move at or above the headroom floor is a derivation change, at either magnitude.

    The second case is the behavioural half of
    ``test_float_noise_threshold_sits_far_below_the_oracle_tolerance``: that
    test reads the constant, this one reads what the splice does. A move of the
    oracle tolerance divided by 1e5 must be written, so a splice that stops
    using ``FLOAT_NOISE_RELATIVE`` -- ``math.isclose`` with its default
    ``rel_tol=1e-9``, say -- and loosens the effective threshold fails here even
    though the constant is unchanged.
    """
    # Arrange
    committed = [_record()]
    fresh = copy.deepcopy(committed)
    moved = committed[0]["expected"][key] * (1.0 + relative_move)
    assert moved != committed[0]["expected"][key], "the move is below float resolution"
    fresh[0]["expected"][key] = moved

    # Act
    spliced, preserved = derive.splice_float_noise(committed, fresh)

    # Assert
    assert spliced[0]["expected"][key] == moved
    assert preserved == 0


@pytest.mark.parametrize(
    ("committed_value", "fresh_value"),
    [
        (True, False),
        (False, 0),
        (True, 1.0),
        (1, 2),
        (1.0, 1),
        (1, 1.0),
        ("corporate", "institution"),
        (None, 0.0),
    ],
    ids=[
        "bool-flip",
        "bool-to-int",
        "bool-to-float",
        "int-change",
        "float-to-int",
        "int-to-float",
        "string-change",
        "null-to-float",
    ],
)
def test_a_non_float_change_is_written_exactly(committed_value: Any, fresh_value: Any) -> None:
    """Only float-against-float differences are ever treated as noise.

    ``bool`` subclasses ``int`` and ``1 == 1.0 == True`` in Python, so a
    splice that compared with ``==`` or ``isinstance(x, int)`` would keep the
    committed leaf here and the file would silently disagree with derive.py.
    """
    # Arrange
    committed = [_record(value=committed_value)]
    fresh = [_record(value=fresh_value)]

    # Act
    spliced, preserved = derive.splice_float_noise(committed, fresh)

    # Assert
    written = spliced[0]["expected"]["value"]
    assert type(written) is type(fresh_value)
    assert json.dumps(written) == json.dumps(fresh_value)
    assert preserved == 0


def test_records_follow_the_fresh_set_added_and_removed() -> None:
    """Records are matched by identifier; the fresh set decides membership and order.

    The records carry distinct values and the insertion shifts every position,
    so pairing records by index instead of by identifier writes the drifted
    value of ORC-900 instead of keeping the committed one.
    """
    # Arrange
    committed = [
        _record("ORC-900", rwa=_LARGE),
        _record("ORC-901", rwa=_LARGE * 1.5),
        _record("ORC-902", rwa=_LARGE * 3.0),
    ]
    fresh = [
        _record("ORC-899", rwa=_LARGE * 2.0),
        _record("ORC-900", rwa=_ulps_up(_LARGE, 1)),
        _record("ORC-901", rwa=_LARGE * 1.5),
    ]
    assert fresh[1]["expected"]["rwa"] != committed[0]["expected"]["rwa"], "no drift to splice"

    # Act
    spliced, preserved = derive.splice_float_noise(committed, fresh)

    # Assert
    assert [record["exposure_id"] for record in spliced] == ["ORC-899", "ORC-900", "ORC-901"]
    assert [record["expected"]["rwa"] for record in spliced] == [
        _LARGE * 2.0,
        _LARGE,
        _LARGE * 1.5,
    ]
    assert preserved == 1


def test_keys_and_lists_follow_the_fresh_record() -> None:
    """An added key appears, a removed one goes, key order and list contents are fresh."""
    # Arrange
    committed = [_record()]
    fresh = [
        {
            "exposure_id": "ORC-900",
            "expected": {"rwa": _LARGE, "risk_weight": _SMALL},
            "inputs": {"ead": 1000000.0, "is_sme": False, "collateral": []},
            "unasserted": ["rwa", "risk_weight"],
        }
    ]

    # Act
    spliced, preserved = derive.splice_float_noise(committed, fresh)

    # Assert
    assert json.dumps(spliced) == json.dumps(fresh)
    assert preserved == 0


def test_floats_inside_nested_lists_are_spliced() -> None:
    """Collateral and guarantee inputs are lists of dicts; their floats get the same rule."""
    # Arrange
    committed = [_record()]
    committed[0]["inputs"]["collateral"] = [{"market_value": _LARGE, "haircut": _SMALL}]
    fresh = copy.deepcopy(committed)
    fresh[0]["inputs"]["collateral"][0]["market_value"] = _ulps_up(_LARGE, 3)
    fresh[0]["inputs"]["collateral"][0]["haircut"] = _SMALL * 2.0

    # Act
    spliced, preserved = derive.splice_float_noise(committed, fresh)

    # Assert
    assert spliced[0]["inputs"]["collateral"][0] == {
        "market_value": _LARGE,
        "haircut": _SMALL * 2.0,
    }
    assert preserved == 1


# =============================================================================
# Private helpers
# =============================================================================


def _use_normal_cdf(monkeypatch: pytest.MonkeyPatch, cdf_form: str) -> None:
    """Make ``statistics.NormalDist.cdf`` compute ``cdf_form`` for this test.

    Each patched form is the standard library's own formula for that family
    (verified bit for bit against CPython 3.11 to 3.14), written against the
    public ``mean`` and ``stdev``.
    """
    if cdf_form == "interpreter":
        return
    forms = {"erf-form": _erf_form_cdf, "erfc-form": _erfc_form_cdf}
    monkeypatch.setattr(statistics.NormalDist, "cdf", forms[cdf_form])


def _erf_form_cdf(dist: statistics.NormalDist, x: float) -> float:
    """``NormalDist.cdf`` as CPython 3.11 to 3.13 compute it."""
    return 0.5 * (1.0 + math.erf((x - dist.mean) / (dist.stdev * math.sqrt(2.0))))


def _erfc_form_cdf(dist: statistics.NormalDist, x: float) -> float:
    """``NormalDist.cdf`` as CPython 3.14 computes it."""
    return 0.5 * math.erfc((dist.mean - x) / (dist.stdev * math.sqrt(2.0)))


def _expected(payload: dict[str, Any]) -> dict[str, Any]:
    """The ``expected`` block of the wiring tests' IRB record in ``payload``."""
    (record,) = [o for o in payload["oracles"] if o["exposure_id"] == _IRB_RECORD]
    return record["expected"]


def _first_differing_lines(expected: str, actual: str, limit: int = 12) -> str:
    """The first few differing lines, so a failure names the records that moved."""
    pairs = [
        (number, want, got)
        for number, (want, got) in enumerate(
            zip(expected.splitlines(), actual.splitlines(), strict=False), start=1
        )
        if want != got
    ]
    lines = [f"line {n}: committed {w.strip()!r} -> regenerated {g.strip()!r}" for n, w, g in pairs]
    if len(expected.splitlines()) != len(actual.splitlines()):
        lines.append("(the line counts differ as well)")
    return (
        "\nRegenerating expected_values.json would change it:\n  "
        + "\n  ".join(lines[:limit])
        + "\nRe-run: uv run python tests/oracle/derive.py, review, and commit the result."
    )
