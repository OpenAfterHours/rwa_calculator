"""
Arelle referee — a second opinion on a written XBRL instance, rule by rule.

Pipeline position:
    xbrl.writer.write_instance -> <name>.xbrl -> run_referee -> RefereeResult
        (set beside the verdicts of rwa-filer's own rule engine)

Key responsibilities:
- Locate an interpreter that has Arelle (``find_arelle_python``). Arelle is an
  optional external tool: this module never imports it, and runs it only as a
  subprocess — ``<python> -I worker.py < SPEC.json > RESULT.json``. The runner
  opens every file a worker uses; the worker is handed streams, never a path.
- Plan the run. A small entry point is validated untrimmed against the official
  entry point in one worker (``MODE_FULL``). A large one is run in chunks, each
  against an overlay package that trims the entry point to that chunk's
  assertions (``MODE_TRIM``; see ``plan``).
- Run the workers strictly one at a time, each under a guard that kills it
  above a resident-memory cap or a timeout.
- Merge what the workers report into one result: a verdict per published rule
  id, the processor's other messages (de-duplicated, known noise removed), the
  rules that were not run because the instance does not file their templates,
  and the rules that were lost with a killed or failed worker.

What a verdict means
    The counts are EVALUATIONS, not cells: a rule with a scope is evaluated
    once per combination of the facts it binds. ``NEVER_FIRED`` is a rule that
    was loaded with its filing-indicator precondition met and still produced
    no evaluation — typically because none of the facts it binds is reported.
    ``skipped`` is a rule whose filing-indicator precondition is false for this
    instance, which a processor does not evaluate at all. The two are reported
    apart in both modes, so a result does not depend on how the run was split.

What the referee cannot say
    Only rules published as XBRL assertions are refereed, and the filing rules
    only as far as Arelle's ``validate/EBA`` plug-in implements them. It does
    not check the entity identifier, the ``instance-generator`` instruction,
    or whether a fact belongs to a filed template.

Known limit
    Trimming bounds the memory Arelle needs to LOAD a chunk; the memory it
    needs to EVALUATE one grows with the instance. A return of a few thousand
    facts ran in under 4 GB per 120 MB chunk, but the Bank's own 61,428-fact
    PRA001 sample outgrew a 9 GB cap during formula evaluation in two of its
    first three chunks. Such a run does not fail silently: the killed workers'
    rules are in ``RefereeResult.lost`` and ``complete`` is false. A smaller
    ``chunk_mb`` lowers the load, not the evaluation.

The memory guard reads ``/proc`` and so works on Linux only. Elsewhere the
timeout is the only limit, and a log line says so.

References:
- Arelle (arelle-release 2.47.5) — the reference XBRL processor
- XBRL Formula 1.0; XBRL Taxonomy Packages 1.0
- BoE XBRL Filing Manual v1.0.1 — the filing rules ``validate/EBA`` implements
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import logging
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from rwa_filer.referee.plan import (
    TABLES_INDICATED,
    TaxonomyModule,
    read_instance_header,
    rule_id,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

#: Environment variable naming a Python interpreter that has ``arelle-release``.
ENV_ARELLE_PYTHON: Final = "RWA_FILER_ARELLE_PYTHON"

#: The script each worker process runs. A module attribute rather than a
#: parameter of ``run_referee`` so that tests can put a fake worker in its
#: place (``monkeypatch.setattr(runner, "WORKER_SCRIPT", path)``) without the
#: public signature carrying a test-only argument.
WORKER_SCRIPT: Final = Path(__file__).with_name("worker.py")

#: The filing-rule plug-in handed to Arelle, by file path.
FILING_RULES_PLUGIN: Final = Path(__file__).with_name("boe_shim.py")
#: The disclosure system that turns the plug-in's checks on.
DISCLOSURE_SYSTEM: Final = "eba"
#: Arelle plug-ins that implement functions the published formulas call. The
#: registry's math functions (``xfm:log`` — rules ``boe_b0599`` and
#: ``boe_b0600``) ship with Arelle as a plug-in that is OFF by default, and
#: without it those two assertions do not compile. Measured on arelle-release
#: 2.47.5: one assertion that does not compile stops every assertion of the
#: session — 689 rules came back with no verdict and no error exit.
FUNCTION_PLUGINS: Final = ("functionsMath",)
#: What the worker changes in Arelle's behaviour, named in every result.
#: ``match_any``: Arelle's match filter with ``matchAny="true"`` iterates the
#: matched variable's value as a sequence; bound to a single fact, that walks
#: the fact element's (absent) children and matches nothing, so the twelve
#: ``boe_b0919`` join rules are unsatisfied whatever is reported. The worker
#: hands the filter the single fact as a sequence of one, which is what the
#: specification's sequence semantics give. Measured: with it each of the
#: twelve is evaluated once and holds, as the native engine finds.
ARELLE_REPAIRS: Final = ("match_any",)

MODE_FULL: Final = "full"
MODE_TRIM: Final = "trim"
#: Entry points with less taxonomy XML than this run untrimmed.
AUTO_FULL_LIMIT_MB: Final = 60.0

VERDICT_PASS: Final = "PASS"
VERDICT_FAIL: Final = "FAIL"
VERDICT_NEVER_FIRED: Final = "NEVER_FIRED"

#: ``ChunkStat.status`` of a worker that ran to the end and wrote its result.
CHUNK_OK: Final = "ok"

#: Message codes that say nothing about the instance. The overlay package
#: overlaps the official one on purpose, and Arelle notes it.
NOISE_CODES: Final = frozenset({"tpe:packageRewriteOverlap"})

#: Filing-rule codes that are raised FALSELY on Bank of England instances, and
#: so are not reported. EBA.3.1 ("there MUST be only one currency"): measured
#: on arelle-release 2.47.5, ``validate/EBA`` raises it on the Bank's own
#: MRL003 sample instance, which reports in GBP, EUR and USD, with the stock
#: plug-in and with the shim alike. Dropping the code hides a genuine breach as
#: well, so the single-currency rule must be checked natively, not here.
KNOWN_FALSE_POSITIVE_CODES: Final = frozenset({"EBA.3.1"})

#: Arelle's level names at which a message means the instance is not accepted.
#: ``ERROR-SEMANTIC`` ranks numerically just under ``ERROR`` and is an error
#: all the same.
ERROR_LEVELS: Final = frozenset({"ERROR", "ERROR-SEMANTIC", "CRITICAL"})

#: Table rendering linkbases are only for viewing. Skipping them saves a long
#: table-compilation step, and a trimmed entry point no longer reaches them
#: through assertion sets or the module presentation anyway.
_SKIP_RENDERING: Final = "*-rend.xml"

_PROC: Final = Path("/proc")
_POLL_SECONDS: Final = 0.5
_KB_PER_GB: Final = 1024 * 1024
_BYTES_PER_MB: Final = 1e6
_STATUS_TAIL_CHARS: Final = 300


# =============================================================================
# Public entry point
# =============================================================================


def run_referee(
    instance: Path,
    taxonomy_package: Path,
    *,
    python: Path | None = None,
    chunk_mb: float = 120.0,
    max_rss_gb: float = 9.0,
    timeout: float = 3600.0,
    workdir: Path | None = None,
    formulas: bool = True,
    filing_rules: bool = True,
    rules: str | None = None,
    max_examples: int = 2,
) -> RefereeResult:
    """Run Arelle on ``instance`` and return its verdict on every rule it evaluated.

    Args:
        instance: The XBRL instance. It is read, never modified.
        taxonomy_package: The taxonomy package zip that holds the instance's
            entry point (its ``schemaRef``).
        python: An interpreter that has Arelle; see ``find_arelle_python`` for
            where one is looked for when this is omitted.
        chunk_mb: Trimmed runs only — the most assertion XML one worker loads.
            Resident memory is roughly 1.5 GB plus 18 MB per MB.
        max_rss_gb: A worker using more resident memory than this is killed.
        timeout: Seconds one worker may run before it is killed.
        workdir: Where the overlays and each chunk's spec, result and stderr
            are written, with a ``progress.json`` rewritten after every chunk.
            Kept when given; a temporary directory, removed afterwards, when not.
        formulas: Evaluate the taxonomy's assertions. ``False`` checks only
            XBRL validity, dimensions and the filing rules, in one quick worker.
        filing_rules: Run the filing-rule plug-in (the EBA disclosure system).
        rules: A regular expression searched in each RULE id (``boe_b0021``,
            not the assertion id); only matching rules are run and reported.
        max_examples: Evaluation messages kept per rule, with the facts bound.

    Raises:
        RefereeUnavailableError: no interpreter with Arelle could be located.
        RefereePlanError: the instance has no ``schemaRef``, or names an entry
            point the package does not hold.

    A worker that is killed or fails does not raise: its rules are reported in
    ``RefereeResult.lost`` and ``complete`` is false.
    """
    interpreter = find_arelle_python(python)
    instance = instance.resolve()
    schema_ref, indicators = read_instance_header(instance)
    module = TaxonomyModule.read(taxonomy_package.resolve(), schema_ref)
    plan = _plan(module, indicators, chunk_mb=chunk_mb, formulas=formulas, rules=rules)
    guard = _guard(max_rss_gb, timeout)
    logger.info(
        "referee: %s against %s, %s mode: %d assertion(s) in %d worker(s), "
        "%d skipped for a false filing-indicator precondition",
        instance.name,
        module.name,
        plan.mode,
        sum(len(files) for files in plan.chunks),
        len(plan.chunks),
        len(plan.skipped),
    )
    with contextlib.ExitStack() as stack:
        if workdir is None:
            workdir = Path(
                stack.enter_context(tempfile.TemporaryDirectory(prefix="rwa_filer_referee_"))
            )
        folder = workdir.resolve()
        folder.mkdir(parents=True, exist_ok=True)
        outcomes: list[_Outcome] = []
        for index, files in enumerate(plan.chunks):
            spec: dict[str, Any] = {
                "instance": str(instance),
                "packages": [str(module.package)],
                "plugin": str(FILING_RULES_PLUGIN) if filing_rules else None,
                "function_plugins": list(FUNCTION_PLUGINS),
                "repairs": list(ARELLE_REPAIRS),
                "disclosure_system": DISCLOSURE_SYSTEM if filing_rules else None,
                "formula": formulas,
                "run_ids": None,
                "skip_loading": None,
                "xdg": str(folder / "xdg"),
                "max_examples": max_examples,
                "chunk": index,
            }
            if plan.mode == MODE_TRIM:
                overlay = module.write_overlay(
                    folder / f"overlay{index}.zip", files, indicators, tables=TABLES_INDICATED
                )
                spec["packages"].append(str(overlay))
                spec["skip_loading"] = _SKIP_RENDERING
            elif plan.wanted is not None:
                # The official entry point loads every assertion, so restrict
                # the evaluation instead. Arelle matches on ASSERTION ids.
                spec["run_ids"] = (
                    "|".join(module.assertions[file].assertion_id for file in files) or None
                )
            outcomes.append(_run_chunk(index, folder, files, spec, module, interpreter, guard))
            # Survive an interrupted run: what has been measured so far is on disk.
            (folder / "progress.json").write_text(
                json.dumps(
                    {
                        "chunks_planned": len(plan.chunks),
                        "chunks": [asdict(outcome.stat) for outcome in outcomes],
                    },
                    indent=1,
                ),
                encoding="utf-8",
            )
    return _merge(plan, module, outcomes, schema_ref, indicators)


# =============================================================================
# The result
# =============================================================================


@dataclass(frozen=True)
class RuleExample:
    """One evaluation message of a rule, with the facts the evaluation bound.

    Attributes:
        level: Arelle's level for the message — the rule's published severity.
        text: The message. A ``sum(...)`` operand is printed as ONE arbitrary
            member of the sequence, so read the values from ``facts``.
        facts: The bound facts (``line``, ``concept``, ``contextRef``,
            ``dimensions``, ``decimals``, ``value``), preceded by the
            assertion's XPath test as ``{"assertion_test": ...}``.
    """

    level: str
    text: str
    facts: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class RuleVerdict:
    """Arelle's verdict on one published rule.

    Attributes:
        rule_id: The published rule id, e.g. ``boe_b0021`` or ``v0718_m``.
        satisfied: Evaluations of the rule that held.
        unsatisfied: Evaluations that did not.
        examples: The first few evaluation messages. The taxonomy attaches a
            message to an UNSATISFIED evaluation only.
    """

    rule_id: str
    satisfied: int
    unsatisfied: int
    examples: tuple[RuleExample, ...] = ()

    @property
    def status(self) -> str:
        """``VERDICT_FAIL`` if any evaluation failed, else PASS or NEVER_FIRED."""
        if self.unsatisfied > 0:
            return VERDICT_FAIL
        return VERDICT_PASS if self.satisfied > 0 else VERDICT_NEVER_FIRED


@dataclass(frozen=True)
class RefereeMessage:
    """A message that is not a rule evaluation: XBRL validity or a filing rule."""

    code: str
    level: str
    text: str


@dataclass(frozen=True)
class ChunkStat:
    """How one worker ran.

    Attributes:
        index: The worker's position in the run.
        assertions: Assertions the worker was to evaluate.
        assertion_xml_mb: Their XML, in MB — what the chunking weighed.
        status: ``CHUNK_OK``, or why the worker's rules were lost.
        wall_s: Seconds from launch to exit.
        peak_rss_mb: Highest resident memory sampled, worker and descendants;
            ``None`` where it cannot be measured.
        returncode: The worker's exit status; negative when it was killed.
        loaded_s: Seconds Arelle reported loading the instance and taxonomy.
        validated_s: Seconds Arelle reported validating.
    """

    index: int
    assertions: int
    assertion_xml_mb: float
    status: str
    wall_s: float
    peak_rss_mb: int | None
    returncode: int | None
    loaded_s: float | None = None
    validated_s: float | None = None

    @property
    def ok(self) -> bool:
        """Whether the worker ran to the end and its result was read."""
        return self.status == CHUNK_OK


@dataclass(frozen=True)
class RefereeResult:
    """What Arelle made of one instance.

    Attributes:
        rules: A verdict per rule that was run, by rule id, sorted.
        messages: Every other message of WARNING level or above, in the order
            first seen, without duplicates and without known noise.
        skipped: Rule ids not run because their filing-indicator precondition
            is false for this instance.
        lost: Rule ids in chunks whose worker was killed or failed, and rule
            ids a finished worker returned no verdict for.
        chunks: One entry per worker.
        schema_ref: The instance's entry point.
        filing_indicators: The templates the instance files, sorted.
        mode: ``MODE_FULL`` or ``MODE_TRIM``.
    """

    rules: Mapping[str, RuleVerdict]
    messages: tuple[RefereeMessage, ...]
    skipped: tuple[str, ...]
    lost: tuple[str, ...]
    chunks: tuple[ChunkStat, ...]
    schema_ref: str
    filing_indicators: tuple[str, ...]
    mode: str

    @property
    def complete(self) -> bool:
        """Whether every worker ran to the end, so that no rule was lost."""
        return not self.lost and all(chunk.ok for chunk in self.chunks)

    @property
    def errors(self) -> tuple[RefereeMessage, ...]:
        """The messages at an error level: the instance is not valid XBRL as filed."""
        return tuple(message for message in self.messages if message.level in ERROR_LEVELS)

    def to_record(self) -> dict[str, Any]:
        """The result as a JSON-ready dict."""
        return {
            "complete": self.complete,
            "mode": self.mode,
            "schema_ref": self.schema_ref,
            "filing_indicators": list(self.filing_indicators),
            "rules": {
                rule: {
                    "status": verdict.status,
                    "satisfied": verdict.satisfied,
                    "unsatisfied": verdict.unsatisfied,
                    "examples": [
                        {
                            "level": example.level,
                            "text": example.text,
                            "facts": [dict(fact) for fact in example.facts],
                        }
                        for example in verdict.examples
                    ],
                }
                for rule, verdict in self.rules.items()
            },
            "messages": [asdict(message) for message in self.messages],
            "skipped": list(self.skipped),
            "lost": list(self.lost),
            "arelle_repairs": list(ARELLE_REPAIRS),
            "chunks": [asdict(chunk) for chunk in self.chunks],
        }


# =============================================================================
# Locating Arelle
# =============================================================================


class RefereeUnavailableError(RuntimeError):
    """No Python interpreter that has Arelle could be located."""


def find_arelle_python(explicit: Path | None = None) -> Path:
    """The interpreter the workers run under.

    In order: ``explicit``; the ``RWA_FILER_ARELLE_PYTHON`` environment
    variable; the current interpreter, if Arelle is installed in it. The path
    is returned as given — resolving a virtual environment's ``python`` link
    would lose the environment.

    Raises:
        RefereeUnavailableError: none of the three applies.
    """
    if explicit is not None:
        return explicit
    configured = os.environ.get(ENV_ARELLE_PYTHON)
    if configured:
        return Path(configured)
    if importlib.util.find_spec("arelle") is not None:
        return Path(sys.executable)
    raise RefereeUnavailableError(
        "The referee needs the Arelle XBRL processor, which is not installed. Either "
        'run the command with the rwa-filer[arelle] extra: uvx "rwa-filer[arelle]@latest" '
        'referee ... (in a uv project: uv add "rwa-filer[arelle]"), or point the '
        f"{ENV_ARELLE_PYTHON} environment variable at a Python interpreter that has "
        "the arelle-release package."
    )


# =============================================================================
# Private helpers — planning
# =============================================================================


@dataclass(frozen=True)
class _Plan:
    """What will be run: one tuple of assertion files per worker."""

    mode: str
    chunks: tuple[tuple[str, ...], ...]
    skipped: tuple[str, ...]
    wanted: re.Pattern[str] | None


def _plan(
    module: TaxonomyModule,
    indicators: frozenset[str],
    *,
    chunk_mb: float,
    formulas: bool,
    rules: str | None,
) -> _Plan:
    """Choose the mode, select the assertions that can fire, and chunk them."""
    mode = MODE_FULL if module.xml_mb <= AUTO_FULL_LIMIT_MB else MODE_TRIM
    wanted = re.compile(rules) if rules is not None else None
    if not formulas:
        return _Plan(mode, ((),), (), wanted)
    kept, dropped = module.select(indicators)
    if wanted is not None:
        kept = [file for file in kept if wanted.search(module.assertions[file].rule_id)]
        dropped = [file for file in dropped if wanted.search(module.assertions[file].rule_id)]
    chunks = module.chunk(kept, chunk_mb) if mode == MODE_TRIM else [kept]
    return _Plan(
        mode=mode,
        chunks=tuple(tuple(files) for files in chunks) or ((),),
        skipped=tuple(sorted(module.assertions[file].rule_id for file in dropped)),
        wanted=wanted,
    )


# =============================================================================
# Private helpers — running one worker under a guard
# =============================================================================


@dataclass(frozen=True)
class _Guard:
    """The limits a worker is held to. ``max_rss_kb`` is None where unmeasurable."""

    max_rss_kb: int | None
    timeout: float


@dataclass(frozen=True)
class _WorkerRun:
    """How a guarded worker process ended."""

    wall_s: float
    peak_rss_mb: int | None
    returncode: int | None
    killed: str | None


@dataclass(frozen=True)
class _Outcome:
    """One worker's statistics, the files it answered for, and its result if any."""

    stat: ChunkStat
    files: tuple[str, ...]
    result: Mapping[str, Any] | None


def _guard(max_rss_gb: float, timeout: float) -> _Guard:
    """The guard this platform can enforce; says so when memory is not part of it."""
    if (_PROC / "self" / "status").is_file():
        return _Guard(max_rss_kb=int(max_rss_gb * _KB_PER_GB), timeout=timeout)
    logger.warning(
        "referee: no /proc on this platform, so the %.1f GB memory cap is not enforced; "
        "each worker is held to the %.0f s timeout only",
        max_rss_gb,
        timeout,
    )
    return _Guard(max_rss_kb=None, timeout=timeout)


def _run_chunk(
    index: int,
    folder: Path,
    files: tuple[str, ...],
    spec: Mapping[str, Any],
    module: TaxonomyModule,
    interpreter: Path,
    guard: _Guard,
) -> _Outcome:
    """Write the spec, run one guarded worker on it, and read back its result.

    The worker is handed the spec as its standard input and the result file as
    its standard output, and names no file itself. The result file is opened
    afresh, so a result an earlier run left behind is never read.
    """
    out = folder / f"chunk{index}.json"
    spec_path = out.with_suffix(".spec.json")
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    stderr_path = out.with_suffix(".stderr.txt")
    run = _run_guarded(
        [str(interpreter), "-I", str(WORKER_SCRIPT)], spec_path, out, stderr_path, guard
    )
    result: Mapping[str, Any] | None = None
    if run.killed is not None:
        status = run.killed
    elif run.returncode != 0:
        tail = _last_line(stderr_path)
        status = f"worker exit {run.returncode}" + (f": {tail}" if tail else "")
    elif out.stat().st_size == 0:
        status = "worker wrote no result"
    else:
        result = json.loads(out.read_text(encoding="utf-8"))
        status = CHUNK_OK
    timings = result["timings"] if result is not None else {}
    stat = ChunkStat(
        index=index,
        assertions=len(files),
        assertion_xml_mb=round(
            sum(module.assertions[file].size for file in files) / _BYTES_PER_MB, 1
        ),
        status=status,
        wall_s=run.wall_s,
        peak_rss_mb=run.peak_rss_mb,
        returncode=run.returncode,
        loaded_s=timings.get("loaded_s"),
        validated_s=timings.get("validated_s"),
    )
    if stat.ok:
        logger.info(
            "referee: worker %d ok: %d assertion(s), %.1f s, peak %s MB",
            index,
            stat.assertions,
            stat.wall_s,
            stat.peak_rss_mb,
        )
    else:
        logger.warning(
            "referee: worker %d lost with its %d assertion(s): %s",
            index,
            stat.assertions,
            status,
        )
    return _Outcome(stat=stat, files=files, result=result)


def _run_guarded(
    command: Sequence[str], stdin_path: Path, stdout_path: Path, stderr_path: Path, guard: _Guard
) -> _WorkerRun:
    """Run one worker; kill it, and all it started, above the memory cap or timeout.

    Its standard streams are the three files named; the output file is truncated.

    The worker gets its own session so that the whole process group can be
    killed, which also means an interrupt of this process does not reach it:
    whatever ends the wait, a worker still running is killed on the way out.
    """
    started = time.monotonic()
    peak_kb = 0
    killed: str | None = None
    with (
        stdin_path.open("rb") as stdin,
        stdout_path.open("wb") as stdout,
        stderr_path.open("wb") as stderr,
    ):
        process = subprocess.Popen(
            command, stdin=stdin, stdout=stdout, stderr=stderr, start_new_session=True
        )
        try:
            while killed is None:
                try:
                    process.wait(timeout=_POLL_SECONDS)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if guard.max_rss_kb is not None:
                    resident_kb = _tree_rss_kb(process.pid)
                    peak_kb = max(peak_kb, resident_kb)
                    if resident_kb > guard.max_rss_kb:
                        killed = (
                            f"killed: rss {resident_kb // 1024} MB > "
                            f"cap {guard.max_rss_kb // 1024} MB"
                        )
                if killed is None and time.monotonic() - started > guard.timeout:
                    killed = f"killed: timeout {guard.timeout:g}s"
        finally:
            if process.poll() is None:
                _kill(process)
    return _WorkerRun(
        wall_s=round(time.monotonic() - started, 1),
        peak_rss_mb=peak_kb // 1024 if guard.max_rss_kb is not None else None,
        returncode=process.returncode,
        killed=killed,
    )


def _kill(process: subprocess.Popen[bytes]) -> None:
    """Kill a worker and everything it started, and reap it."""
    if sys.platform == "win32":
        process.kill()
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    process.wait()


def _tree_rss_kb(root: int) -> int:
    """Resident memory, in kB, of process ``root`` and all of its descendants."""
    children: dict[int, list[int]] = {}
    resident: dict[int, int] = {}
    for entry in _PROC.iterdir():
        if not entry.name.isdigit():
            continue
        parent = rss = 0
        try:
            for line in (entry / "status").read_text(encoding="utf-8").splitlines():
                if line.startswith("PPid:"):
                    parent = int(line.split()[1])
                elif line.startswith("VmRSS:"):
                    rss = int(line.split()[1])
        except (OSError, ValueError):
            continue  # the process ended between the listing and the read
        children.setdefault(parent, []).append(int(entry.name))
        resident[int(entry.name)] = rss
    total = 0
    pending = [root]
    while pending:
        pid = pending.pop()
        total += resident.get(pid, 0)
        pending.extend(children.get(pid, ()))
    return total


def _last_line(path: Path) -> str:
    """The last non-blank line a worker wrote to stderr — usually its exception."""
    lines = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    return lines[-1].strip()[:_STATUS_TAIL_CHARS] if lines else ""


# =============================================================================
# Private helpers — merging
# =============================================================================


def _merge(
    plan: _Plan,
    module: TaxonomyModule,
    outcomes: Sequence[_Outcome],
    schema_ref: str,
    indicators: frozenset[str],
) -> RefereeResult:
    """One result from every worker's: verdicts by rule id, messages once each."""
    verdicts: dict[str, RuleVerdict] = {}
    messages: dict[RefereeMessage, None] = {}
    lost: list[str] = []
    for outcome in outcomes:
        if outcome.result is None:
            lost.extend(module.assertions[file].rule_id for file in outcome.files)
            continue
        # A worker that ran to the end and says nothing about an assertion it
        # was given did not evaluate it: a formula of the session failed to
        # compile and Arelle evaluated none of them. Silence is not "never
        # fired" — the rule is lost, and the run is not complete.
        answered = outcome.result["assertions"]
        unanswered = [
            module.assertions[file].rule_id
            for file in outcome.files
            if module.assertions[file].assertion_id not in answered
        ]
        if unanswered:
            logger.warning(
                "referee: worker %d returned no verdict for %d of its %d assertion(s)",
                outcome.stat.index,
                len(unanswered),
                len(outcome.files),
            )
            lost.extend(unanswered)
        examples = outcome.result["examples"]
        for assertion_id, (satisfied, unsatisfied) in answered.items():
            rule = rule_id(assertion_id)
            if plan.wanted is not None and not plan.wanted.search(rule):
                continue
            verdicts[rule] = RuleVerdict(
                rule_id=rule,
                satisfied=satisfied,
                unsatisfied=unsatisfied,
                examples=tuple(
                    RuleExample(example["level"], example["text"], tuple(example["facts"]))
                    for example in examples.get(assertion_id, ())
                ),
            )
        for message in outcome.result["messages"]:
            if message["code"] in NOISE_CODES or message["code"] in KNOWN_FALSE_POSITIVE_CODES:
                logger.debug("referee: dropped [%s] %s", message["code"], message["text"])
                continue
            messages.setdefault(RefereeMessage(message["code"], message["level"], message["text"]))
    # An untrimmed run loads every assertion, and Arelle counts 0 / 0 for one
    # whose precondition is false. Report those as skipped, as a trimmed run
    # does — but never over a verdict Arelle did reach.
    skipped = tuple(
        rule
        for rule in plan.skipped
        if rule not in verdicts or verdicts[rule].status == VERDICT_NEVER_FIRED
    )
    rules = {rule: verdicts[rule] for rule in sorted(verdicts.keys() - set(skipped))}
    result = RefereeResult(
        rules=rules,
        messages=tuple(messages),
        skipped=skipped,
        lost=tuple(sorted(lost)),
        chunks=tuple(outcome.stat for outcome in outcomes),
        schema_ref=schema_ref,
        filing_indicators=tuple(sorted(indicators)),
        mode=plan.mode,
    )
    logger.info(
        "referee: %s: %d rule(s) evaluated, %d with unsatisfied evaluations, %d skipped, "
        "%d lost, %d message(s)",
        "complete" if result.complete else "INCOMPLETE",
        len(rules),
        sum(1 for verdict in rules.values() if verdict.status == VERDICT_FAIL),
        len(skipped),
        len(result.lost),
        len(result.messages),
    )
    return result
