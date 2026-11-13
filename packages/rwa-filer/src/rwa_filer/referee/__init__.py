"""
Referee — the Arelle XBRL processor's verdict on a written instance, rule by rule.

Pipeline position:
    xbrl.writer.write_instance -> <name>.xbrl -> referee.run_referee -> RefereeResult
        (set beside the verdicts of rwa-filer's own rule engine)

rwa-filer evaluates the published rules itself, from its own reading of them.
The referee asks an independent implementation the same question: it runs
Arelle, the reference open-source XBRL processor, on the instance against the
publisher's taxonomy package, where the same rules are XBRL formula assertions,
and returns what Arelle concluded for each rule — satisfied, unsatisfied, never
fired — together with its XBRL-validity and filing-rule messages. A
disagreement between the two is a finding: one of them has misread a rule.

Arelle is OPTIONAL, and nothing in rwa-filer imports it. It is run only as a
subprocess, under the first interpreter found by:

1. the ``python`` argument of ``run_referee``;
2. the ``RWA_FILER_ARELLE_PYTHON`` environment variable — a Python interpreter
   that has the ``arelle-release`` package, typically a virtual environment of
   its own;
3. the current interpreter, if Arelle is installed in it.

With none of the three, ``run_referee`` raises ``RefereeUnavailableError``
saying how to get one. The taxonomy package is the publisher's zip, which is
not redistributed here.

Module map:
- ``runner`` — ``run_referee``: plan the run, launch one guarded worker per
  chunk, merge the workers' results into a ``RefereeResult``
- ``plan`` — pure standard library: read an entry point out of the taxonomy
  package, select the assertions an instance can fire, chunk them, and write
  the overlay package that trims the entry point to one chunk
- ``worker`` — the script a worker process runs, and the only code that
  touches Arelle; standard library only, so it runs under an interpreter that
  does not have rwa-filer
- ``boe_shim`` — the filing-rule plug-in Arelle is handed, by file path: the
  stock ``validate/EBA`` plug-in with a date switch that misfires on Bank of
  England entry points turned off
- ``differential`` — ``compare``: the native rule engine's results set beside
  the referee's, rule by rule; a disagreement is a finding
- ``report`` — the run and the comparison as text and as a record, and the one
  answer to "does this run support the instance?"

The referee is not stock Arelle in two respects, both measured and both named
in every result (``runner.FUNCTION_PLUGINS``, ``runner.ARELLE_REPAIRS``): it
loads the math-functions plug-in two published rules need, and it corrects a
match filter that otherwise never matches a single fact.

References:
- Arelle (arelle-release) — https://arelle.org
- XBRL Formula 1.0 — the form the published validation rules take in a taxonomy
- Bank of England Banking Taxonomy; BoE XBRL Filing Manual v1.0.1
"""

from __future__ import annotations

from rwa_filer.referee.differential import Differential, RuleComparison, compare
from rwa_filer.referee.plan import RefereePlanError
from rwa_filer.referee.runner import (
    ENV_ARELLE_PYTHON,
    VERDICT_FAIL,
    VERDICT_NEVER_FIRED,
    VERDICT_PASS,
    ChunkStat,
    RefereeMessage,
    RefereeResult,
    RefereeUnavailableError,
    RuleExample,
    RuleVerdict,
    find_arelle_python,
    run_referee,
)

__all__ = [
    "ENV_ARELLE_PYTHON",
    "VERDICT_FAIL",
    "VERDICT_NEVER_FIRED",
    "VERDICT_PASS",
    "ChunkStat",
    "Differential",
    "RefereeMessage",
    "RefereePlanError",
    "RefereeResult",
    "RefereeUnavailableError",
    "RuleComparison",
    "RuleExample",
    "RuleVerdict",
    "compare",
    "find_arelle_python",
    "run_referee",
]
