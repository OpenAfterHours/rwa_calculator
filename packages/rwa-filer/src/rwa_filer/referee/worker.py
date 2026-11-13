"""
Referee worker — one Arelle session on one instance. The only code that touches Arelle.

Pipeline position:
    runner.run_referee -> (SPEC.json) -> this script, in its own process
        -> Arelle session -> (result JSON at the path the spec names) -> runner

Run as a script, by an interpreter that has Arelle and need not have rwa-filer::

    python -I /path/to/rwa_filer/referee/worker.py SPEC.json

That is why this file imports the standard library only, and reaches Arelle
through ``importlib.import_module``: it must run where rwa-filer is not
installed, and it must not make rwa-filer's own environment — or its type
checker — need Arelle.

Key responsibilities:
- Run one Arelle session: load the instance against the taxonomy packages the
  spec lists, validate it (XBRL 2.1, dimensions, the filing-rule plug-in when
  one is named) and evaluate the formula assertions.
- Harvest the per-assertion verdict counts. They come from the model, not from
  the log: after formula processing Arelle appends ONE dict
  ``{assertion id: (satisfied, notSatisfied, okMsgs, warningMsgs, errorMsgs)}``
  to ``modelXbrl.errors``. An assertion that was never evaluated counts 0 / 0.
- Keep the log small. A large filing produces tens of thousands of evaluation
  messages per run; only the first few per assertion are let through, as
  examples, and they are refused before Arelle builds them.

The spec (JSON object)
    ``instance``, ``packages`` (list of zip paths), ``plugin`` and
    ``disclosure_system`` (both null to skip the filing rules),
    ``function_plugins`` (names of Arelle plug-ins that implement functions the
    formulas call), ``repairs`` (names from ``REPAIRS``), ``formula``
    (false to skip the assertions), ``run_ids`` (``|``-joined assertion ids, or
    null for all), ``skip_loading`` (a file pattern, or null), ``xdg`` (Arelle's
    configuration and cache home), ``max_examples``, ``out``.

The result (JSON object)
    ``assertions`` (``{assertion id: [satisfied, unsatisfied]}``), ``examples``
    (``{assertion id: [{level, text, facts}]}``), ``messages`` (every other
    message of WARNING level or above, ``[{code, level, text}]``) and
    ``timings``.

Exit status: 0 once the result is written. Anything else — Arelle missing, an
exception, a kill — leaves no result, and the runner reports the chunk as lost.

References:
- Arelle (arelle-release 2.47.5): ``arelle.api.Session``, ``RuntimeOptions``,
  ``ValidateFormula`` (the verdict dict), ``ModelXbrl.log`` (``messageCodeFilter``)
- XBRL Formula 1.0 — assertion evaluation counts
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

# =============================================================================
# Constants
# =============================================================================

#: Arelle's message code for an assertion's evaluation message is this prefix
#: followed by the assertion id.
EVALUATION_PREFIX = "message:"

ARELLE_LOGGER = "arelle"
_TIMING = re.compile(r"(loaded|validated) in ([0-9.]+) secs")
_QUIET_LEVELS = ("DEBUG", "INFO")
#: Marks the replacement match filter, so that it is installed once.
_REPAIRED = "repaired_match_any"

#: (seconds since start, level name, message code, text, log refs)
_Record = tuple[float, str, str, str, list[dict[str, Any]]]


# =============================================================================
# Main entry point
# =============================================================================


def main(argv: list[str] | None = None) -> int:
    """Run the session ``SPEC.json`` describes and write its result."""
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1:
        sys.stderr.write("usage: python -I worker.py SPEC.json\n")
        return 2
    spec = json.loads(Path(arguments[0]).read_text(encoding="utf-8"))
    result = run_session(spec)
    Path(spec["out"]).write_text(json.dumps(result), encoding="utf-8")
    return 0


def run_session(spec: dict[str, Any]) -> dict[str, Any]:
    """One Arelle session: load, validate, evaluate; return the result object."""
    session_api = importlib.import_module("arelle.api.Session")
    runtime_options = importlib.import_module("arelle.RuntimeOptions")
    for repair in spec.get("repairs", ()):
        REPAIRS[repair]()
    plugins = [*([spec["plugin"]] if spec["plugin"] else []), *spec.get("function_plugins", ())]
    options = runtime_options.RuntimeOptions(
        entrypointFile=spec["instance"],
        packages=spec["packages"],
        internetConnectivity="offline",
        validate=True,
        keepOpen=True,
        formulaAction=None if spec["formula"] else "none",
        formulaRunIDs=spec["run_ids"],
        plugins="|".join(plugins) or None,
        disclosureSystemName=spec["disclosure_system"],
        skipLoading=spec["skip_loading"],
        xdgConfigHome=spec["xdg"],
        # The taxonomy files are published and immutable; re-validating them on
        # every run is most of the run for a small entry point.
        baseTaxonomyValidationMode="none",
    )
    handler = _Collector(_ExampleLimiter(spec["max_examples"]))
    # A caller-supplied handler bypasses the code that turns on per-object
    # properties in log refs; ModelXbrl reads this attribute off the logger
    # when it is created.
    arelle_logger: Any = logging.getLogger(ARELLE_LOGGER)
    arelle_logger.logRefObjectProperties = True
    assertions: dict[str, tuple[int, int]] = {}
    with session_api.Session() as session:
        session.run(options, logHandler=handler)
        for model in session.get_models():
            assertions.update(harvest_verdicts(model.errors))
    return {
        "assertions": assertions,
        **summarise(handler.records, spec["instance"], spec["max_examples"]),
    }


# =============================================================================
# Supporting public functions
# =============================================================================


def repair_match_any() -> None:
    """Make Arelle's match filter treat a single matched fact as a sequence of one.

    ``ModelMatchFilter.filter`` with ``matchAny="true"`` tests the fact against
    ``any(... for anotherFact in otherFact)``. When the matched variable binds
    one fact at a time, ``otherFact`` is that fact — an XML element — and
    iterating it walks its children, of which a fact has none: nothing ever
    matches. The filter is handed ``(fact,)`` instead. Idempotent.
    """
    formula_objects = importlib.import_module("arelle.ModelFormulaObject")
    fact_type = importlib.import_module("arelle.ModelInstanceObject").ModelFact
    match_filter = formula_objects.ModelMatchFilter
    original = match_filter.filter
    if getattr(original, _REPAIRED, False):
        return

    def filter_(self: Any, context: Any, binding: Any, facts: Any, complement: Any) -> Any:
        other = context.inScopeVars.get(self.variable)
        if not (self.matchAny and isinstance(other, fact_type)):
            return original(self, context, binding, facts, complement)
        context.inScopeVars[self.variable] = (other,)
        try:
            return original(self, context, binding, facts, complement)
        finally:
            context.inScopeVars[self.variable] = other

    setattr(filter_, _REPAIRED, True)
    match_filter.filter = filter_


#: The changes to Arelle's behaviour a spec may ask for, by name.
REPAIRS: dict[str, Any] = {"match_any": repair_match_any}


def harvest_verdicts(errors: list[Any]) -> dict[str, tuple[int, int]]:
    """``{assertion id: (satisfied, unsatisfied)}`` from a model's ``errors`` list.

    The list holds message codes (strings) and, after formula processing, the
    one dict of evaluation counts per assertion; only the dicts are read.
    """
    verdicts: dict[str, tuple[int, int]] = {}
    for item in errors:
        if isinstance(item, dict):
            for assertion_id, counts in item.items():
                verdicts[str(assertion_id)] = (int(counts[0]), int(counts[1]))
    return verdicts


def summarise(records: list[_Record], instance: str, max_examples: int) -> dict[str, Any]:
    """Sort the collected log records into examples, messages and timings."""
    timings: dict[str, Any] = {}
    messages: list[dict[str, str]] = []
    examples: dict[str, list[dict[str, Any]]] = {}
    for _seconds, level, code, text, refs in records:
        if code == "info":
            timed = _TIMING.match(text)
            if timed:
                timings[f"{timed.group(1)}_s"] = float(timed.group(2))
            continue
        if code.startswith(EVALUATION_PREFIX):
            bucket = examples.setdefault(code[len(EVALUATION_PREFIX) :], [])
            if len(bucket) < max_examples:
                bucket.append({"level": level, "text": text, "facts": _fact_refs(refs, instance)})
            continue
        if level in _QUIET_LEVELS:
            if code == "info:profileActivity":
                timings.setdefault("activity", []).append(text.strip())
            continue
        messages.append({"code": code, "level": level, "text": text})
    return {"examples": examples, "messages": messages, "timings": timings}


# =============================================================================
# Private helpers
# =============================================================================


class _ExampleLimiter:
    """Duck-typed ``messageCodeFilter``: only the first N messages per assertion pass.

    Arelle asks ``logger.messageCodeFilter.match(code)`` BEFORE it builds a log
    record, so everything past the first N evaluation messages of an assertion
    costs nothing — no text interpolation, no fact property dumps, no retained
    records. The verdict counts do not come from the log, so nothing is lost.
    Every other message code always passes.
    """

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.seen: dict[str, int] = {}

    def match(self, code: str) -> bool:
        if not code.startswith(EVALUATION_PREFIX):
            return True
        count = self.seen.get(code, 0) + 1
        self.seen[code] = count
        return count <= self.limit


class _Collector(logging.Handler):
    """Keep Arelle's log records, and install the limiter once logging is live."""

    def __init__(self, limiter: _ExampleLimiter) -> None:
        super().__init__()
        self.started = time.monotonic()
        self.limiter = limiter
        self.installed = False
        self.records: list[_Record] = []

    def emit(self, record: logging.LogRecord) -> None:
        if not self.installed:
            # ``Cntlr.startLogging`` resets this attribute, so it can only be
            # set once logging is live; the first record (plug-in activation,
            # long before any evaluation) is early enough.
            arelle_logger: Any = logging.getLogger(ARELLE_LOGGER)
            arelle_logger.messageCodeFilter = self.limiter
            self.installed = True
        try:
            text = record.getMessage()
        except (TypeError, ValueError):
            text = str(record.msg)
        code = getattr(record, "messageCode", "") or ""
        evaluation = code.startswith(EVALUATION_PREFIX)
        refs = list(getattr(record, "refs", []) or []) if evaluation else []
        seconds = round(time.monotonic() - self.started, 2)
        self.records.append((seconds, record.levelname, code, text, refs))


def _fact_refs(refs: list[dict[str, Any]], instance: str) -> list[dict[str, Any]]:
    """Reduce Arelle's log refs to the instance facts an evaluation bound.

    The message text interpolates a SEQUENCE variable (the operand of
    ``sum(...)``) as one arbitrary member, so the bound facts here are the only
    reliable values. The assertion's own ref is kept as its XPath test.
    """
    facts: list[dict[str, Any]] = []
    base = os.path.basename(instance)
    for ref in refs:
        href = str(ref.get("href", ""))
        properties = {str(item[0]): item for item in ref.get("properties", []) if len(item) >= 2}
        if base not in href:
            if "test" in properties:
                facts.append({"assertion_test": str(properties["test"][1])})
            continue
        dimensions: dict[str, str] = {}
        context = properties.get("contextRef")
        if context is not None and len(context) > 2:
            for detail in context[2]:
                if detail[0] == "dimensions" and len(detail) > 2:
                    dimensions = {str(pair[0]): str(pair[1]) for pair in detail[2]}
        facts.append(
            {
                "line": ref.get("sourceLine"),
                "concept": _property(properties, "QName"),
                "contextRef": str(context[1]) if context is not None else None,
                "dimensions": dimensions,
                "decimals": _property(properties, "decimals"),
                "value": _property(properties, "value"),
            }
        )
    return facts


def _property(properties: dict[str, Any], name: str) -> str | None:
    """The value of one named property of a log ref, as text."""
    return str(properties[name][1]) if name in properties else None


if __name__ == "__main__":
    sys.exit(main())
