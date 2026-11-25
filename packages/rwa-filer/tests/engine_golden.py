"""
The engine golden — order-sensitive digests of everything the rule engine says about the corpus.

Pipeline position:
    engine_corpus.build_corpus / corpus_rulebook
        ->  run_corpus (evaluate_rules, evaluate_rules with every failure,
            trace_rules, validate_return, trace_return — per return)
        ->  golden_from (digests)  ->  tests/boe/data/engine_equivalence.json
        ->  tests/boe/test_engine_equivalence.py (differences against the bank)

Key responsibilities:
- Turn every engine output into a canonical text that keeps ORDER — a mapping is
  its items in its own order, a float is its ``repr`` — so that the same cells
  in another order, or a float one ulp out, is a difference.
- Digest per RULE, not per return: a difference names the return, the output
  and the rule. A rule that is not evaluated because its template is not
  reported, or because none of its cells is, has nothing rule-specific to say
  and shares one digest with the others like it.
- Record what the corpus was (``corpus``), apart from what the engine made of
  it (``returns``), so a changed pack, rule book or generator is not mistaken
  for a changed engine.
- Bank, check and dump. ``rebank`` is the ONLY way the committed file changes.

Re-banking — read before you run it
-----------------------------------
The golden was first banked from the engine as it stood BEFORE the 2026-11
performance work, and it is the equivalence oracle for that work and for every
later change to ``boe/engine.py``, ``validate/returns.py``,
``validate/execution.py`` and ``validate/issue_labels.py``. It may be re-banked
only for a DELIBERATE, EXPLAINED change of behaviour: a defect fixed, a new
taxonomy release packaged, a rule added to the corpus. It may never be re-banked
to make a speed-up pass: a speed-up that moves a digest has changed a verdict,
a recorded break, its order or the trace, and that is the finding. ``rebank``
therefore takes the reason and keeps it in the file::

    uv run python packages/rwa-filer/tests/engine_golden.py --rebank \\
        --reason "boe_b0730 now reads ... (escape log 2027-01-05)"

To see WHAT moved rather than that something did, dump the full canonical text
from two checkouts and diff the folders::

    uv run python packages/rwa-filer/tests/engine_golden.py --dump /tmp/before
    uv run python packages/rwa-filer/tests/engine_golden.py --dump /tmp/after

References:
- docs/plans/rwa-filer-performance-review-2026-11-22.md — "Guards that land with
  the changes"
- .claude/LESSONS.md E1 (never bulk-regenerate a golden to green)
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from functools import cache
from itertools import groupby
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from engine_corpus import (
    MODULE,
    RUN_DATE,
    SEED,
    TAXONOMY,
    build_corpus,
    corpus_release,
    corpus_rulebook,
)
from rwa_filer.boe import engine
from rwa_filer.boe.engine import (
    REASON_NO_DATA,
    REASON_NOT_REPORTED,
    STATUS_FAIL,
    STATUS_NOT_EVALUATED,
    STATUS_PASS,
    evaluate_rules,
    trace_rules,
)
from rwa_filer.validate.returns import trace_return, validate_return

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from rwa_filer.boe.engine import Evaluation, RuleResult, RuleTrace
    from rwa_filer.model import CanonicalReturn
    from rwa_filer.validate.returns import ReturnValidation

# =============================================================================
# Constants
# =============================================================================

GOLDEN_PATH: Final = Path(__file__).parent / "boe" / "data" / "engine_equivalence.json"
GOLDEN_FORMAT: Final = 1

#: Hex digits kept of each SHA-256: 40 bits, against some thousands of digests.
DIGEST_LENGTH: Final = 10
#: The three digests banked per rule, in the order they are written.
RULE_DIGESTS: Final = ("results", "results_every_failure", "trace")

#: Fields left out of the canonical form, by type: the pack and the rule book a
#: validation points at are the corpus's inputs, described once under
#: ``corpus``, not outputs of the validation.
_HANDLES: Final[Mapping[str, frozenset[str]]] = {
    "ReturnValidation": frozenset({"release", "rulebook"}),
}
#: Differences quoted from one list before the rest are counted.
_LIST_DIFFERENCES_QUOTED: Final = 3
#: Not-evaluated reasons that say nothing about the rule beyond "nothing to read".
_QUIET_REASONS: Final = frozenset({REASON_NOT_REPORTED, REASON_NO_DATA})


# =============================================================================
# Public entry points
# =============================================================================


@dataclass(frozen=True)
class Run:
    """Everything the engine says about one corpus return.

    Attributes:
        ret: The return.
        results: ``evaluate_rules`` — the first ``MAX_FAILURES`` breaks per rule.
        every_failure: ``evaluate_rules(max_failures=None)``.
        trace: ``trace_rules``.
        validation: ``validate_return``.
        traced_validation / traced: ``trace_return``'s pair.
    """

    ret: CanonicalReturn
    results: tuple[RuleResult, ...]
    every_failure: tuple[RuleResult, ...]
    trace: RuleTrace
    validation: ReturnValidation
    traced_validation: ReturnValidation
    traced: RuleTrace


def run_corpus(only: Iterable[str] | None = None) -> dict[str, Run]:
    """Run the engine's five entry points over each corpus return, in corpus order."""
    release = corpus_release()
    book = corpus_rulebook()
    rules = book.enforced(MODULE)
    wanted = None if only is None else set(only)
    runs: dict[str, Run] = {}
    for name, item in build_corpus().items():
        if wanted is not None and name not in wanted:
            continue
        ret, accuracy = item.ret, item.accuracy
        how: dict[str, Any] = {
            "release": release,
            "rulebook": book,
            "accuracy": accuracy,
            "submission_date": RUN_DATE,
        }
        traced_validation, traced = trace_return(ret, **how)
        assert traced is not None, "the corpus rule book is never absent"
        pack = release.pack
        runs[name] = Run(
            ret=ret,
            results=tuple(evaluate_rules(ret, pack, rules, accuracy=accuracy)),
            every_failure=tuple(
                evaluate_rules(ret, pack, rules, accuracy=accuracy, max_failures=None)
            ),
            trace=trace_rules(ret, pack, rules, accuracy=accuracy),
            validation=validate_return(ret, **how),
            traced_validation=traced_validation,
            traced=traced,
        )
    return runs


def golden_from(runs: Mapping[str, Run]) -> dict[str, Any]:
    """The digests of ``runs``, in the shape the golden file banks them."""
    release = corpus_release()
    rules = corpus_rulebook().enforced(MODULE)
    return {
        "corpus": {
            "module": MODULE,
            "taxonomy": TAXONOMY,
            "run_date": RUN_DATE.isoformat(),
            "seed": SEED,
            "rules": len(rules),
            # What the returns are evaluated against, by content. A release that
            # is packaged again with a new deny-list entry or a new publisher
            # issue moves these, and is named before any engine output is.
            "rulebook": digest([rule.fingerprint(MODULE) for rule in rules]),
            "deny_list": digest(release.deny_list.entries),
            "issue_register": release.issues.content_sha256[:DIGEST_LENGTH],
            "returns": {
                name: {"facts": run.ret.facts.height, "content": _return_digest(run.ret)}
                for name, run in runs.items()
            },
        },
        "returns": {name: _record(run) for name, run in runs.items()},
    }


def load_golden() -> dict[str, Any]:
    """The banked golden."""
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def differences(banked: Mapping[str, Any], measured: Mapping[str, Any]) -> list[str]:
    """Every place ``measured`` differs from ``banked``, as ``path: banked -> measured``.

    Only the corpus's description and the returns' digests are compared: the
    file's own notes are not the engine's output.
    """
    found: list[str] = []
    for section in ("corpus", "returns"):
        _compare(section, banked.get(section), measured.get(section), found)
    return found


def rebank(reason: str, *, path: Path = GOLDEN_PATH) -> Path:
    """Measure the corpus with the code on the import path and bank it at ``path``.

    For a deliberate, explained change of behaviour ONLY — never to make a
    speed-up pass (see the module docstring). ``reason`` says what changed and
    why; it is kept in the file with every earlier one, so the history of the
    golden is the history of the engine's intended behaviour changes.

    Raises:
        ValueError: ``reason`` is empty.
    """
    if not reason.strip():
        raise ValueError("a re-bank states what changed and why; see engine_golden's docstring")
    history = json.loads(path.read_text(encoding="utf-8"))["banked"] if path.exists() else []
    golden = {
        "format": GOLDEN_FORMAT,
        "_note": (
            "Digests of the rule engine's output on the synthetic corpus "
            "(tests/engine_corpus.py), written by tests/engine_golden.py --rebank and never "
            "by hand. Re-bank only for a deliberate, explained behaviour change - never to "
            "make a speed-up pass. Per rule: " + " | ".join(RULE_DIGESTS) + "."
        ),
        "banked": [
            *history,
            {"reason": reason.strip(), "engine_sha256": _engine_sha256()},
        ],
        **golden_from(run_corpus()),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(golden, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def dump(directory: Path, only: Iterable[str] | None = None) -> None:
    """Write the full canonical text behind every digest under ``directory``, one file each.

    For diffing two checkouts: the golden says that a rule's output moved,
    these files say what moved.
    """
    for name, run in run_corpus(only).items():
        folder = directory / name
        folder.mkdir(parents=True, exist_ok=True)
        sections: dict[str, Sequence[object]] = {
            "results": run.results,
            "results_every_failure": run.every_failure,
            "trace_evaluations": run.trace.evaluations,
            "trace_cells": list(run.trace.cells.items()),
            **_validation_sections("validate", run.validation),
            **_validation_sections("trace_return", run.traced_validation),
            "trace_return_evaluations": run.traced.evaluations,
            "trace_return_cells": list(run.traced.cells.items()),
        }
        for section, items in sections.items():
            lines = [canonical_text(item) for item in items]
            (folder / f"{section}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


# =============================================================================
# The canonical form
# =============================================================================


def canonical_text(value: object) -> str:
    """``value`` as text that keeps order and exact floats.

    A dataclass is its type name and its fields in field order; a mapping is
    its items in ITS order, so two mappings holding the same items in another
    order differ; a tuple and a list are told apart; a float is its ``repr``,
    which round-trips, so one ulp is a difference. Text is quoted as JSON, a
    set is sorted. Anything else is refused rather than guessed at.
    """
    parts: list[str] = []
    _write(value, parts)
    return "".join(parts)


def digest(value: object) -> str:
    """The first ``DIGEST_LENGTH`` hex digits of the SHA-256 of ``value``'s canonical text."""
    return hashlib.sha256(canonical_text(value).encode("utf-8")).hexdigest()[:DIGEST_LENGTH]


def evaluations_by_rule(evaluations: Sequence[Evaluation]) -> dict[str, tuple[Evaluation, ...]]:
    """A trace's evaluations per rule, each rule's in the order the engine made them."""
    found: dict[str, list[Evaluation]] = {}
    for evaluation in evaluations:
        found.setdefault(evaluation.rule_id, []).append(evaluation)
    return {rule_id: tuple(items) for rule_id, items in found.items()}


# =============================================================================
# Private helpers
# =============================================================================


def _write(value: object, out: list[str]) -> None:  # noqa: C901, PLR0912 - one branch per kind
    """Append ``value``'s canonical text to ``out`` (see ``canonical_text``)."""
    kind = type(value)
    if kind is str:
        out.append(json.dumps(value))
    elif value is None or kind is bool or kind is int or kind is float or kind is Decimal:
        out.append(repr(value))
    elif kind is tuple or kind is list:
        opening, closing = ("(", ")") if kind is tuple else ("[", "]")
        out.append(opening)
        for item in value:  # type: ignore[attr-defined]
            _write(item, out)
            out.append(",")
        out.append(closing)
    elif (names := _field_names(kind)) is not None:
        out.append(f"{kind.__name__}(")
        for name in names:
            out.append(f"{name}=")
            _write(getattr(value, name), out)
            out.append(",")
        out.append(")")
    elif isinstance(value, Mapping):
        out.append("{")
        for key, item in value.items():
            _write(key, out)
            out.append(":")
            _write(item, out)
            out.append(",")
        out.append("}")
    elif isinstance(value, (set, frozenset)):
        out.append("set(" + ",".join(sorted(canonical_text(item) for item in value)) + ")")
    elif isinstance(value, date):
        out.append(f"date({value.isoformat()})")
    else:
        raise TypeError(f"no canonical form for {kind.__name__}: {value!r}")


@cache
def _field_names(kind: type) -> tuple[str, ...] | None:
    """A dataclass's field names, less the handles; ``None`` for any other type."""
    if not dataclasses.is_dataclass(kind):
        return None
    left_out = _HANDLES.get(kind.__name__, frozenset())
    return tuple(field.name for field in dataclasses.fields(kind) if field.name not in left_out)


def _record(run: Run) -> dict[str, Any]:
    """One return's digests."""
    traced = _digests_by_rule(run.trace)
    returned = _digests_by_rule(run.traced)
    rules: dict[str, str] = {}
    quiet: list[tuple[str, str, str]] = []
    plain: dict[str, str] = {}
    every_failure = {result.rule_id: result for result in run.every_failure}
    for result in run.results:
        every = every_failure[result.rule_id]
        plain[result.rule_id] = digest(result)
        if _is_quiet(result) and _is_quiet(every) and result.rule_id not in traced:
            quiet.append((result.rule_id, plain[result.rule_id], digest(every)))
            continue
        rules[result.rule_id] = " ".join(
            (plain[result.rule_id], digest(every), traced.get(result.rule_id, digest(())))
        )
    statuses = (STATUS_PASS, STATUS_FAIL, STATUS_NOT_EVALUATED)
    return {
        "statuses": {status: sum(r.status == status for r in run.results) for status in statuses},
        "evaluations": sum(result.evaluations for result in run.results),
        # The per-rule digests below are looked up by rule: the order the three
        # entry points return their results in is pinned here.
        "rules_in_order": digest(
            [
                [result.rule_id for result in results]
                for results in (run.results, run.every_failure, run.trace.results)
            ]
        ),
        "rules": rules,
        "quiet_rules": {"count": len(quiet), "digest": digest(quiet)},
        "trace_results": digest(run.trace.results),
        "trace": _trace_record(run.trace),
        "validate": _validation_record(run.validation, plain),
        "trace_return": {
            "validation": _validation_record(run.traced_validation, plain),
            "trace": _trace_record(run.traced),
            # Only where the deny list took a rule's evaluations out of the trace.
            "evaluations_changed_from_trace_rules": {
                rule_id: returned.get(rule_id, "none")
                for rule_id in dict.fromkeys((*traced, *returned))
                if traced.get(rule_id) != returned.get(rule_id)
            },
        },
    }


def _digests_by_rule(trace: RuleTrace) -> dict[str, str]:
    """The digest of each rule's evaluations, in the order the engine made them."""
    return {
        rule_id: digest(evaluations)
        for rule_id, evaluations in evaluations_by_rule(trace.evaluations).items()
    }


def _is_quiet(result: RuleResult) -> bool:
    """Whether the rule was not evaluated for want of anything to read."""
    return result.status == STATUS_NOT_EVALUATED and result.reason in _QUIET_REASONS


def _trace_record(trace: RuleTrace) -> dict[str, Any]:
    """What of a trace is not one rule's: the rules' order, and the cells in first-read order."""
    runs = [(rule_id, len(list(items))) for rule_id, items in groupby(trace.evaluations, _rule_id)]
    return {
        "evaluations": len(trace.evaluations),
        "rule_order": digest(runs),
        "cells": len(trace.cells),
        "cells_in_order": digest(list(trace.cells.items())),
    }


def _rule_id(evaluation: Evaluation) -> str:
    return evaluation.rule_id


def _validation_record(validation: ReturnValidation, plain: Mapping[str, str]) -> dict[str, Any]:
    """A validation's digests; ``plain`` is each rule's ``evaluate_rules`` result digest."""
    report = validation.report
    assert report is not None, "the corpus rule book is never absent"
    return {
        "status": validation.status,
        "verdict": digest(
            [
                validation.status,
                validation.completeness,
                validation.publisher_issues,
                validation.accuracy,
                validation.accuracy_given,
                validation.deny_date,
                validation.source,
                validation.release.version,
            ]
        ),
        "structure": _listed(validation.structure),
        "release_findings": _listed(validation.release_findings),
        "rule_findings": [
            f"{finding.code} {finding.subject} {digest(finding)}" for finding in validation.rules
        ],
        "issue_notes": [
            f"{note.rule_id} {note.issue_id} {digest(note)}" for note in report.issue_notes
        ],
        "report": digest(replace(report, results=(), issue_notes=())),
        "rules_in_order": digest([result.rule_id for result in report.results]),
        # Only where the Bank's deny list changed what the engine found.
        "results_changed_from_evaluate_rules": {
            result.rule_id: changed
            for result in report.results
            if (changed := digest(result)) != plain[result.rule_id]
        },
    }


def _listed(items: Sequence[object]) -> dict[str, Any]:
    return {"count": len(items), "digest": digest(items)}


def _return_digest(ret: CanonicalReturn) -> str:
    """A return's facts in order, and its declared filing indicators."""
    return digest([ret.facts.rows(), ret.indicators])


def _engine_sha256() -> str:
    """The SHA-256 of ``boe/engine.py`` as imported: which engine a bank was taken from."""
    return hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest()


def _validation_sections(name: str, validation: ReturnValidation) -> dict[str, Sequence[object]]:
    """A validation as ``dump`` writes it: one finding, result or label per line."""
    report = validation.report
    assert report is not None, "the corpus rule book is never absent"
    return {
        f"{name}_findings": validation.findings,
        f"{name}_results": report.results,
        f"{name}_issue_notes": report.issue_notes,
        f"{name}_report": [replace(report, results=(), issue_notes=())],
        f"{name}_verdict": [validation.status, *validation.completeness],
    }


def _compare(path: str, banked: object, measured: object, found: list[str]) -> None:
    """Append every leaf at which the two differ, named by its path.

    A mapping is compared key by key. A list is compared item by item, the
    first few differing items quoted and the rest counted, so one inserted
    finding does not bury the report under every finding after it.
    """
    if isinstance(banked, dict) and isinstance(measured, dict):
        for key in dict.fromkeys((*banked, *measured)):
            _compare(f"{path} / {key}", banked.get(key), measured.get(key), found)
        return
    if isinstance(banked, list) and isinstance(measured, list):
        moved = [
            index
            for index in range(max(len(banked), len(measured)))
            if banked[index : index + 1] != measured[index : index + 1]
        ]
        for index in moved[:_LIST_DIFFERENCES_QUOTED]:
            before, now = banked[index : index + 1], measured[index : index + 1]
            found.append(
                f"{path} / [{index}]: banked {_shown(before[0] if before else None)} "
                f"-> now {_shown(now[0] if now else None)}"
            )
        if len(moved) > _LIST_DIFFERENCES_QUOTED:
            found.append(
                f"{path}: {len(moved) - _LIST_DIFFERENCES_QUOTED} more item(s) differ "
                f"({len(banked)} banked, {len(measured)} now)"
            )
        return
    if banked != measured:
        found.append(f"{path}: banked {_shown(banked)} -> now {_shown(measured)}")


def _shown(value: object) -> str:
    text = "absent" if value is None else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 120 else f"{text[:117]}..."  # noqa: PLR2004 - one line


def _main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n", 1)[0].strip())
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true", help="list differences from the bank")
    action.add_argument("--rebank", action="store_true", help="measure and bank (needs --reason)")
    action.add_argument("--dump", type=Path, metavar="DIR", help="write the canonical text")
    parser.add_argument("--reason", default="", help="what changed and why, for --rebank")
    arguments = parser.parse_args(argv)
    print(f"code under test: {Path(engine.__file__).parent.parent}")
    if arguments.dump is not None:
        dump(arguments.dump)
        print(f"canonical text written under {arguments.dump}")
        return 0
    if arguments.rebank:
        if not arguments.reason.strip():
            parser.error("--rebank needs --reason: what changed, and why")
        print(f"banked {rebank(arguments.reason)}")
        return 0
    moved = differences(load_golden(), golden_from(run_corpus()))
    for line in moved:
        print(line)
    print(f"{len(moved)} difference(s) from {GOLDEN_PATH.name}")
    return 1 if moved else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
