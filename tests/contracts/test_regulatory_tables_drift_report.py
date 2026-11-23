"""
Stale-skill diagnostics for the regulatory-tables generator (P5.57).

``scripts/generate_regulatory_tables.py --check`` used to name only the stale
*file*. One region, ``regime-divergence`` in the basel31 skill's
``what-changed.md``, has computed membership: every simple-shape entry carried by
both packs whose values differ joins it with no author action. So a routine new
on/off ``Feature`` restaged a ``.claude/skills`` file its author never named, and
where ``.claude/`` could not be written the item blocked on a freshness failure
that did not say which entry caused it (five items by 2026-08-15).

These tests pin the diagnostic, not the membership rule. The generator must name
each entry that entered, left or changed inside a stale region, say when that
region's membership is computed, and say that the ``.agents/skills`` mirror has
to follow - in ``--check`` and, before any write, in a write. Each alarm is
paired with the unchanged case it must stay quiet on (LESSONS B9).

Every probe lives in memory and no test here writes a file: the one test that
runs a write first makes every write-mode open raise. The in-memory tests
compare a probed render with a fresh render of the unmodified packs, not with
the files on disk, so they depend only on the generator. A tree with a pending
regeneration fails ``test_docs_freshness``, not these, and the two ``main()``
tests are the ones that read the committed files.

The probe citation deliberately names no real instrument: the confidence matrix
text-scans ``tests/`` for framework-tagged article strings, and a probe article
written in that form would publish a fake row there.

References:
- IMPLEMENTATION_PLAN.md P5.57 (both copies)
- tests/contracts/test_docs_freshness.py (the freshness gate that relays this report)
"""

from __future__ import annotations

import builtins
import dataclasses
import functools
import io
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from rwa_calc.rulebook.model import Citation, Feature

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import generate_regulatory_tables as grt  # noqa: E402

if TYPE_CHECKING:
    from datetime import date

    from rwa_calc.rulebook.model import RuleEntry
    from rwa_calc.rulebook.resolve import ResolvedRulepack

PROBE = "zz_probe_feature"
PROBE_CITATION = Citation("PROBE", "0")
WHAT_CHANGED = REPO_ROOT / ".claude" / "skills" / "basel31" / "references" / "what-changed.md"
CRR_SA_RISK_WEIGHTS = REPO_ROOT / ".claude" / "skills" / "crr" / "references" / "sa-risk-weights.md"


def _fragment(fragment_id: str) -> grt.Fragment:
    return next(f for f in grt.FRAGMENTS if f.fragment_id == fragment_id)


def _with_entry(
    packs: dict[str, ResolvedRulepack], regime: str, entry: RuleEntry
) -> dict[str, ResolvedRulepack]:
    pack = packs[regime]
    widened = dataclasses.replace(pack, entries={**pack.entries, entry.name: entry})
    return {**packs, regime: widened}


def _with_probe(crr_on: bool, b31_on: bool) -> dict[str, ResolvedRulepack]:
    packs = grt.resolve_packs()
    packs = _with_entry(packs, "crr", Feature(PROBE, crr_on, PROBE_CITATION))
    return _with_entry(packs, "b31", Feature(PROBE, b31_on, PROBE_CITATION))


@functools.cache
def _fresh_render() -> dict[Path, str]:
    """Every target as a fresh render of the unmodified packs - the probes' baseline."""
    return grt.render_targets()


def _install_probe_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every resolve inside ``main()`` carry a CRR-off / B31-on probe Feature."""
    real_resolve = grt.resolve

    def resolve_with_probe(regime_id: str, on: date) -> ResolvedRulepack:
        pack = real_resolve(regime_id, on)
        probe = Feature(PROBE, regime_id == "b31", PROBE_CITATION)
        return dataclasses.replace(pack, entries={**pack.entries, PROBE: probe})

    monkeypatch.setattr(grt, "resolve", resolve_with_probe)


def _refuse_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every write-mode open raise, as it does where ``.claude/`` is read-only.

    Both ``io.open`` (behind ``Path.open``, ``read_text`` and ``write_text``)
    and the builtin are wrapped, so no route the generator could take to a
    target writes it. Reads pass straight through.
    """
    real_io_open = io.open
    real_builtin_open = builtins.open

    def guard(real: Any) -> Any:
        def refusing_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
            if any(flag in mode for flag in "wax+"):
                raise PermissionError(13, "Permission denied (probe)", str(file))
            return real(file, mode, *args, **kwargs)

        return refusing_open

    monkeypatch.setattr(io, "open", guard(real_io_open))
    monkeypatch.setattr(builtins, "open", guard(real_builtin_open))


def _targets_on_disk() -> dict[Path, str]:
    return {path: path.read_text(encoding="utf-8") for path in grt.TARGET_PATHS}


# =============================================================================
# The quiet case — an alarm that fires on an unchanged tree carries nothing
# =============================================================================


def test_unchanged_packs_report_no_drift() -> None:
    """Unprobed packs read against their own render yield no drift, so the probes' drift is theirs."""
    # Arrange
    packs = grt.resolve_packs()

    # Act
    drifts = grt.skill_drift(_fresh_render(), packs)

    # Assert
    assert drifts == [], (
        "two renders of the same packs differ, so the render or the region reader "
        "is not deterministic and every drift asserted below is noise: "
        f"{[(d.fragment.fragment_id, d.entered, d.left, d.changed) for d in drifts]}"
    )


def test_identical_feature_does_not_enter_the_computed_region() -> None:
    """A feature with one value under both regimes is not a divergence."""
    # Arrange
    packs = _with_probe(crr_on=True, b31_on=True)
    committed = _fresh_render()[WHAT_CHANGED]

    # Act
    drift = grt.fragment_drift(_fragment("regime-divergence"), committed, packs)

    # Assert
    assert (drift.region_differs, drift.entered) == (False, ())


@pytest.mark.parametrize("fragment", grt.FRAGMENTS, ids=lambda f: f.fragment_id)
def test_reader_recovers_every_entry_a_region_renders(fragment: grt.Fragment) -> None:
    """Against an empty file, every rendered entry reads back as entered - none is missed.

    The entered/left/changed sets are only as good as the reader that pulls entry
    names out of a region. Many regions mix shapes (comparison rows beside
    lookup, banded, decision and formula blocks whose own rows also open with a
    backticked name), so this checks the reader against the spec on every region
    the generator writes, not on a hand-built sample. Removing the reader's
    table-scope guard misreads 21 of the 33 regions (measured 2026-11-23).
    """
    # Arrange
    packs = grt.resolve_packs()
    expected = tuple(dict.fromkeys(fragment.entries))

    # Act
    drift = grt.fragment_drift(fragment, "", packs)

    # Assert
    if fragment.entries:
        assert drift.entered == expected
    else:
        assert drift.entered, "the computed region rendered no entry at all"
        assert list(drift.entered) == sorted(drift.entered)


# =============================================================================
# Entered / left / changed — each named, by entry
# =============================================================================


@pytest.mark.parametrize(
    ("crr_on", "b31_on"),
    [
        pytest.param(False, True, id="crr-off-b31-on"),
        pytest.param(True, False, id="crr-on-b31-off"),
    ],
)
def test_divergent_feature_is_named_as_entering_the_computed_region(
    crr_on: bool, b31_on: bool
) -> None:
    """The routine new Feature that restaged what-changed.md is named, and flagged as computed."""
    # Arrange
    packs = _with_probe(crr_on=crr_on, b31_on=b31_on)
    committed = _fresh_render()[WHAT_CHANGED]

    # Act
    drift = grt.fragment_drift(_fragment("regime-divergence"), committed, packs)

    # Assert
    assert drift.region_differs, "the probe did not change the region - nothing to diagnose"
    assert (drift.entered, drift.left, drift.changed) == ((PROBE,), (), ())
    assert drift.computed_membership


def test_entry_whose_values_converge_is_named_as_leaving_the_computed_region() -> None:
    """A divergence that closes takes its row with it, and that is named too."""
    # Arrange
    packs = grt.resolve_packs()
    committed = _fresh_render()[WHAT_CHANGED]
    assert "| `output_floor` | off | on |" in committed, (
        "output_floor is no longer an off/on row of the rendered region - pick "
        "another divergent Feature, or this test converges nothing"
    )
    crr_floor = packs["crr"].entries["output_floor"]
    converged = _with_entry(packs, "b31", dataclasses.replace(crr_floor))

    # Act
    drift = grt.fragment_drift(_fragment("regime-divergence"), committed, converged)

    # Assert
    assert (drift.entered, drift.left, drift.changed) == ((), ("output_floor",), ())


def test_note_only_edit_to_a_curated_structured_entry_is_named_as_changed() -> None:
    """A structured entry renders its citation note, so a note edit restages it - and is named.

    This is the P1.310 case: ``mdb_risk_weights_table_2b``'s note change restaged
    the crr SA skill file. The region's membership is curated, so the entry can
    only have changed, never entered.
    """
    # Arrange
    packs = grt.resolve_packs()
    table = packs["crr"].entries["mdb_risk_weights_table_2b"]
    renoted = dataclasses.replace(
        table, citation=dataclasses.replace(table.citation, note="probe note")
    )
    edited = _with_entry(packs, "crr", renoted)
    committed = _fresh_render()[CRR_SA_RISK_WEIGHTS]

    # Act
    drift = grt.fragment_drift(_fragment("crr-sa-public-sector"), committed, edited)
    report = "\n".join(grt.format_drift([drift]))

    # Assert
    assert (drift.entered, drift.left, drift.changed) == ((), (), ("mdb_risk_weights_table_2b",))
    assert not drift.computed_membership
    assert "~ `mdb_risk_weights_table_2b` changed" in report
    assert "computed membership" not in report, (
        "a curated region was reported as computed - an alarm that fires on every "
        "region tells the author nothing (LESSONS B9)"
    )


def test_reordered_region_is_reported_as_moved_with_no_entry_named() -> None:
    """Entries that only change places still restage the region, and the report says so.

    Comparing entry blocks alone would call this region unchanged and drop it
    from the report while the freshness gate still fails on it.
    """
    # Arrange
    fragment = _fragment("b31-sa-corporate")
    reordered = dataclasses.replace(fragment, entries=tuple(reversed(fragment.entries)))
    committed = _fresh_render()[fragment.path]

    # Act
    drift = grt.fragment_drift(reordered, committed, grt.resolve_packs())
    report = "\n".join(grt.format_drift([drift]))

    # Assert
    assert (drift.region_differs, drift.entered, drift.left, drift.changed) == (
        True,
        (),
        (),
        (),
    )
    assert "(no entry entered, left or changed - only order or layout moved)" in report


# =============================================================================
# The report the freshness gate relays
# =============================================================================


def test_report_names_the_region_the_entry_and_the_mirror_step() -> None:
    """The rendered report carries everything an author who cannot write .claude/ needs."""
    # Arrange
    drifts = grt.skill_drift(_fresh_render(), _with_probe(crr_on=False, b31_on=True))

    # Act
    report = "\n".join(grt.format_drift(drifts))

    # Assert
    assert ".claude/skills/basel31/references/what-changed.md" in report
    assert "regime-divergence" in report
    assert "computed membership" in report
    assert f"+ `{PROBE}` entered" in report
    assert "uv run python scripts/sync_agent_skills.py" in report


def test_report_is_empty_when_nothing_drifted() -> None:
    """No drift, no report - the mirror reminder must not fire on a fresh tree."""
    # Arrange
    drifts = grt.skill_drift(_fresh_render(), grt.resolve_packs())

    # Act
    report = grt.format_drift(drifts)

    # Assert
    assert report == []


def test_check_names_the_entry_that_entered_the_computed_region(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--check`` itself - what test_docs_freshness relays - names the entry, not just the file."""
    # Arrange
    _install_probe_resolve(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["generate_regulatory_tables.py", "--check"])
    before = WHAT_CHANGED.read_text(encoding="utf-8")

    # Act
    exit_code = grt.main()
    stderr = capsys.readouterr().err

    # Assert
    assert exit_code == 1, f"--check did not find the probe stale:\n{stderr}"
    assert ".claude/skills/basel31/references/what-changed.md" in stderr
    assert f"+ `{PROBE}` entered" in stderr
    assert "uv run python scripts/sync_agent_skills.py" in stderr
    assert WHAT_CHANGED.read_text(encoding="utf-8") == before, "--check wrote a target"


def test_refused_write_still_names_the_entry_that_entered(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Where ``.claude/`` cannot be written, a write still names what moved before it fails.

    That is the environment the diagnostic exists for: the write raises on its
    first refused target, so a report printed after the write loop never
    appears. Every write-mode open raises here, so the run cannot change a file.
    """
    # Arrange
    _install_probe_resolve(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["generate_regulatory_tables.py"])
    before = _targets_on_disk()
    _refuse_writes(monkeypatch)

    # Act
    with pytest.raises(PermissionError):
        grt.main()
    stderr = capsys.readouterr().err

    # Assert
    assert ".claude/skills/basel31/references/what-changed.md" in stderr
    assert f"+ `{PROBE}` entered" in stderr
    assert "uv run python scripts/sync_agent_skills.py" in stderr
    assert _targets_on_disk() == before, "a refused write changed a target"
