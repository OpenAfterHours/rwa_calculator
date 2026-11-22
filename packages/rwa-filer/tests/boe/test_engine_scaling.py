"""
Scaling gate for the Bank of England rule engine: cost in the size of an open axis.

Pipeline position:
    CanonicalReturn + TaxonomyPack + rules  ->  boe.engine.evaluate_rules
    This file drives ``evaluate_rules`` directly on a PRA001 return built from
    the packaged v4.1.1 taxonomy pack, at two country counts.

Key responsibilities:
- Pin the ASYMPTOTIC SHAPE of rule evaluation in the number of members a
  return reports on an open sheet axis (countries on OF 09.01 / OF 09.02), not a
  single wall-clock number, so an evaluation that goes quadratic in the axis
  fails here rather than in a reporter's run.
- Keep the measured path live: assert the summed rules both run and run once per
  column and country, so the timing is not measuring blocked or empty rules
  (LESSONS B4 / C11).

The escape this closes
----------------------
Each rule of the form "row total = isum(listed rows)" over OF 09.01 / OF 09.02
(``boe_b0730``, ``boe_b0731``, ``boe_b0783``, ``boe_b0785``, ``boe_b0786``) is
evaluated once per column and country, and its summed reference reads the listed
rows at that column and country. The engine used to find those cells by
scanning every cell the reference could read, at every evaluation, and joined
the references' places pair by pair. Both evaluations and cells grow with the
country count, so the cost grew with its square: on the ``rich`` portfolio with
its country facts copied out, the whole PRA001 rule book took 0.2 s at 2
countries, 12 s at 100 and 49 s at 200. Every fixture return reports at most two
countries, where the cost is invisible, so no gate measured it.

Why a RATIO and not only an absolute budget
-------------------------------------------
The same reasoning as ``tests/unit/classifier/test_p1_320_qrre_aggregate_scaling.py``
at the root: an absolute threshold measures this box on this day and has to be
loose enough for a loaded CI worker; the defect is a change of SHAPE, and a
ratio across two sizes measures shape. The budget is a coarse second line.

Measured in a 4-core Linux container, best of 3, on this file's return (the 44
rules that read OF 09.01 / OF 09.02 alone):

=================  ===============  ==================
countries          scan (defect)    indexed (fixed)
=================  ===============  ==================
10                 1.15 - 1.22 s    0.20 - 0.22 s
40                 16.1 - 17.6 s    0.73 - 0.87 s
ratio (4x)         13.2x - 14.4x    3.7x - 4.0x
=================  ===============  ==================

so ``MAX_SCALING_RATIO = 8.0`` sits close to the geometric midpoint, with about
2x headroom below it for the fixed form and about 1.7x above it for the defect.

References:
- Bank of England Banking Taxonomy v4.1.1 (PRA001) — OF 09.01 / OF 09.02 and
  their validation rules
- docs/development/escape-log.md, 2026-11-20
"""

from __future__ import annotations

import time
from datetime import date
from functools import cache
from typing import TYPE_CHECKING

import polars as pl

from pack_builders import VALID_LEI
from rwa_filer.boe.engine import STATUS_PASS, evaluate_rules
from rwa_filer.model import CanonicalReturn, ReturnHeader
from rwa_filer.release import resolve_release

if TYPE_CHECKING:
    from rwa_filer.boe.catalogue import Rule
    from rwa_filer.boe.engine import RuleResult
    from rwa_filer.release import Release

MODULE = "PRA001"
TAXONOMY = "4.1.1"
#: The two geographical-breakdown tables, each with an open country axis.
TABLES = ("OF09.01.01.01", "OF09.02.01.01")
#: Rules of the "total = isum(listed rows)" shape, iterated per column and country.
SUMMED_RULES = ("boe_b0730", "boe_b0731", "boe_b0783", "boe_b0785", "boe_b0786")

SMALL = 10
LARGE = 40
#: Linear cost gives about 4x for 4x the countries, quadratic about 16x.
MAX_SCALING_RATIO = 8.0
#: A coarse second line at LARGE countries; the ratio is the guard.
BUDGET_SECONDS = 5.0
REPEATS = 3


def test_rule_evaluation_scales_linearly_in_the_number_of_countries() -> None:
    """Four times the countries may cost no more than eight times the time."""
    # Arrange
    release = _release()
    rules = _rules()
    small, large = _geographical_return(SMALL), _geographical_return(LARGE)

    # Adequacy: the summed rules run, once per column and country, at both sizes.
    small_results = _summed(evaluate_rules(small, release.pack, rules))
    large_results = _summed(evaluate_rules(large, release.pack, rules))
    missing = sorted(set(SUMMED_RULES) - set(small_results))
    assert not missing, (
        f"summed rule(s) {missing} not in the rule book - the return no longer exercises "
        "the path this test times"
    )
    for rule_id in SUMMED_RULES:
        assert small_results[rule_id].status == STATUS_PASS, (
            f"{rule_id} was not evaluated ({small_results[rule_id].reason}) - "
            "timing it would time nothing"
        )
        assert large_results[rule_id].evaluations == 4 * small_results[rule_id].evaluations > 0, (
            f"{rule_id}: {small_results[rule_id].evaluations} evaluations at {SMALL} countries, "
            f"{large_results[rule_id].evaluations} at {LARGE} - not one per column and country"
        )

    # Act
    small_seconds = _best_time(small, release, rules)
    large_seconds = _best_time(large, release, rules)

    # Assert
    ratio = large_seconds / small_seconds
    assert ratio < MAX_SCALING_RATIO, (
        f"{LARGE} countries took {large_seconds:.3f}s against {small_seconds:.3f}s for {SMALL}: "
        f"{ratio:.1f}x for 4x the countries. Rule evaluation has gone super-linear in the size "
        "of an open axis - look for a scan of every cell inside the per-evaluation loop"
    )
    assert large_seconds < BUDGET_SECONDS, (
        f"{LARGE} countries took {large_seconds:.2f}s, over the {BUDGET_SECONDS}s budget"
    )


# =============================================================================
# Helpers
# =============================================================================


@cache
def _release() -> Release:
    """The packaged PRA001 release, loaded once."""
    return resolve_release(MODULE, TAXONOMY)


@cache
def _rules() -> tuple[Rule, ...]:
    """The enforced rules that read the geographical breakdown tables alone."""
    rulebook = _release().rulebook
    assert rulebook is not None, f"taxonomy {TAXONOMY} packages no rule book for {MODULE}"
    return tuple(rule for rule in rulebook.enforced(MODULE) if set(rule.tables) <= set(TABLES))


def _geographical_return(countries: int) -> CanonicalReturn:
    """Every cell of OF 09.01 and OF 09.02 reported at zero, for ``countries`` countries."""
    pack = _release().pack
    frames = []
    for table in TABLES:
        axis = pack.tables[table].open_axis
        assert axis is not None, f"{table} has no open axis in taxonomy {TAXONOMY}"
        members = axis.members[:countries]
        assert len(members) == countries, f"{table} has only {len(axis.members)} members"
        cells = pack.cells.filter(pl.col("table") == table).select("table", "row", "column")
        frames.append(
            cells.join(pl.DataFrame({"open_key": members}), how="cross").with_columns(
                pl.lit(0.0).alias("value")
            )
        )
    header = ReturnHeader(VALID_LEI, date(2027, 3, 31), MODULE)
    return CanonicalReturn.from_frame(header, pl.concat(frames))


def _summed(results: list[RuleResult]) -> dict[str, RuleResult]:
    """The summed rules' results, by rule."""
    return {result.rule_id: result for result in results if result.rule_id in SUMMED_RULES}


def _best_time(ret: CanonicalReturn, release: Release, rules: tuple[Rule, ...]) -> float:
    """The fastest of ``REPEATS`` evaluations, in seconds."""
    best = float("inf")
    for _ in range(REPEATS):
        started = time.perf_counter()
        evaluate_rules(ret, release.pack, rules)
        best = min(best, time.perf_counter() - started)
    return best
