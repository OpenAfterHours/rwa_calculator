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
- Run the workers in a pool — the chunks of one instance, or of many
  (``prepare_referee`` then ``run_referees``) — as many at once as fit in the
  memory available at their cap (``resolve_jobs``), each under its own guard
  that kills it above a resident-memory cap or a timeout. The results are
  merged in plan order, so they do not depend on the order workers finish in.
- Reuse a worker's result when nothing it depends on has changed
  (``cache_dir``): the key is a SHA-256 over the bytes Arelle reads — the
  instance, the taxonomy package, the overlay's members, the filing-rule
  plug-in — the spec's settings, every distribution installed beside Arelle
  (Arelle's own dependencies are not pinned by its release), the Python
  version and locale, and this package's worker, planner and runner, and never
  over a path. A hit skips the worker
  only. A worker that did not finish is never stored, nor one that finished
  with an assertion unanswered or an error or exception logged; an entry that
  does not read back whole, as a result, is ignored and recomputed.
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
timeout is the only limit, and a log line says so, and the automatic number of
workers at once is one.

References:
- Arelle (arelle-release 2.47.5) — the reference XBRL processor
- XBRL Formula 1.0; XBRL Taxonomy Packages 1.0
- BoE XBRL Filing Manual v1.0.1 — the filing rules ``validate/EBA`` implements
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import json
import logging
import math
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from rwa_filer.referee import plan as _plan_module
from rwa_filer.referee.plan import (
    TABLES_INDICATED,
    TaxonomyModule,
    read_instance_header,
    rule_id,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

#: Environment variable naming a Python interpreter that has ``arelle-release``.
ENV_ARELLE_PYTHON: Final = "RWA_FILER_ARELLE_PYTHON"
#: Environment variable naming the folder of the worker-result cache, for a
#: caller that asks ``referee_cache_dir`` where it is.
ENV_REFEREE_CACHE: Final = "RWA_FILER_REFEREE_CACHE"

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

#: Memory the automatic number of workers leaves free of their caps, in GB.
#: The kernel's ``MemAvailable`` already nets off what is in use, this process
#: included; the headroom is for what is not yet: the merge and progress files
#: this process writes while the pool runs, the page cache the workers read the
#: taxonomy package through, and the allocation of each worker between two
#: samples of the guard (``_POLL_SECONDS``) before it is killed at its cap.
MEMORY_HEADROOM_GB: Final = 1.5

_PROC: Final = Path("/proc")
#: The spec's members that name a file. The key reads each file's bytes, and
#: never the name.
_SPEC_PATHS: Final = frozenset({"instance", "packages", "plugin", "xdg"})
#: Asks the interpreter the workers run under what it runs Arelle with: the
#: Python version and every installed distribution, ``name==version``, sorted.
#: Arelle's verdicts depend on its own dependencies (lxml, regex, pyparsing,
#: isodate, numpy...), which an ``arelle-release==X`` install leaves unpinned:
#: a new release of any of them is a new identity, so nothing stored under the
#: old one is reused.
_IDENTITY_PROBE: Final = (
    "import json, sys; from importlib import metadata; "
    "names = {(d.metadata['Name'] or '').lower(): d.version for d in metadata.distributions()}; "
    "print(json.dumps({'arelle-release': names.get('arelle-release'), 'python': sys.version, "
    "'distributions': sorted(f'{name}=={version}' for name, version in names.items())}))"
)
#: The environment the workers inherit that can change the text Arelle writes.
_LOCALE_VARIABLES: Final = ("LANG", "LC_ALL", "LC_MESSAGES")
#: A cache entry's file: a digest line, then the worker's raw result.
_ENTRY_SUFFIX: Final = ".entry"
_DIGEST_PREFIX: Final = b"sha256:"
_HASH_BLOCK: Final = 1 << 20
_POLL_SECONDS: Final = 0.5
_INTERRUPTED: Final = "killed: run interrupted"
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
    jobs: int | None = None,
    cache_dir: Path | None = None,
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
        jobs: Workers run at once; ``None`` for as many as fit (``resolve_jobs``).
        cache_dir: Where workers' results are stored and reused from; ``None``
            to run every worker and store nothing.

    Raises:
        RefereeUnavailableError: no interpreter with Arelle could be located.
        RefereePlanError: the instance has no ``schemaRef``, or names an entry
            point the package does not hold.

    A worker that is killed or fails does not raise: its rules are reported in
    ``RefereeResult.lost`` and ``complete`` is false.
    """
    interpreter = find_arelle_python(python)
    with contextlib.ExitStack() as stack:
        if workdir is None:
            workdir = Path(
                stack.enter_context(tempfile.TemporaryDirectory(prefix="rwa_filer_referee_"))
            )
        prepared = prepare_referee(
            instance,
            taxonomy_package,
            workdir=workdir,
            chunk_mb=chunk_mb,
            formulas=formulas,
            filing_rules=filing_rules,
            rules=rules,
            max_examples=max_examples,
        )
        (result,) = run_referees(
            [prepared],
            python=interpreter,
            jobs=jobs,
            max_rss_gb=max_rss_gb,
            timeout=timeout,
            cache_dir=cache_dir,
        )
    return result


# =============================================================================
# Running many instances through one pool
# =============================================================================


@dataclass(frozen=True)
class PreparedReferee:
    """One instance, planned and laid out on disk: what each of its workers is handed.

    Made by ``prepare_referee``; run, with any others, by ``run_referees``.

    Attributes:
        instance: The instance, resolved.
        folder: Where its overlays, specs, results and ``progress.json`` are.
        schema_ref: The instance's entry point.
        indicators: The templates the instance files.
        specs: One worker spec per chunk, in plan order.
    """

    instance: Path
    folder: Path
    schema_ref: str
    indicators: frozenset[str]
    specs: tuple[Mapping[str, Any], ...]
    module: TaxonomyModule
    plan: _Plan


def prepare_referee(
    instance: Path,
    taxonomy_package: Path,
    *,
    workdir: Path,
    chunk_mb: float = 120.0,
    formulas: bool = True,
    filing_rules: bool = True,
    rules: str | None = None,
    max_examples: int = 2,
) -> PreparedReferee:
    """Plan the run on ``instance`` and write what its workers need to ``workdir``.

    The arguments are ``run_referee``'s. Nothing is run: the overlays and the
    specs are written, and the workers wait for ``run_referees``.

    Raises:
        RefereePlanError: the instance has no ``schemaRef``, or names an entry
            point the package does not hold.
    """
    instance = instance.resolve()
    schema_ref, indicators = read_instance_header(instance)
    module = TaxonomyModule.read(taxonomy_package.resolve(), schema_ref)
    plan = _plan(module, indicators, chunk_mb=chunk_mb, formulas=formulas, rules=rules)
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
    folder = workdir.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    specs: list[dict[str, Any]] = []
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
            # One configuration home per worker: workers of one instance may
            # run at once, and none should read what another wrote.
            "xdg": str(folder / f"xdg{index}"),
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
        specs.append(spec)
    return PreparedReferee(
        instance=instance,
        folder=folder,
        schema_ref=schema_ref,
        indicators=indicators,
        specs=tuple(specs),
        module=module,
        plan=plan,
    )


def run_referees(
    prepared: Sequence[PreparedReferee],
    *,
    python: Path | None = None,
    jobs: int | None = None,
    max_rss_gb: float = 9.0,
    timeout: float = 3600.0,
    cache_dir: Path | None = None,
) -> tuple[RefereeResult, ...]:
    """Run every worker of every prepared instance through ONE pool; a result each.

    Workers are started in plan order — the first instance's chunks, then the
    next's — and ``jobs`` of them run at once, each under its own guard. Each
    instance's results are merged in plan order however the workers finish,
    and its ``progress.json`` is rewritten as each of its workers ends.

    Args:
        prepared: The instances, from ``prepare_referee``.
        python: An interpreter that has Arelle (``find_arelle_python``).
        jobs: Workers run at once; ``None`` for as many as fit (``resolve_jobs``).
        max_rss_gb: The resident memory one worker is held to.
        timeout: Seconds one worker may run before it is killed.
        cache_dir: Where workers' results are stored and reused from; ``None``
            to run every worker and store nothing. A reused result is the
            worker's own, byte for byte, so the merge cannot tell it apart.

    Returns:
        One result per prepared instance, in the order given.

    Raises:
        RefereeUnavailableError: no interpreter with Arelle could be located.
        ValueError: ``jobs`` is less than one.

    An interrupt (SIGINT; SIGTERM too, inside ``interrupt_on_sigterm``), or
    any other exception, kills the workers that are running and starts no
    other before it propagates: the pool is waited on half a second at a time,
    so a signal is acted on within about that, and each worker's guard sees
    the cancellation at its next sample.
    """
    interpreter = find_arelle_python(python)
    guard = _guard(max_rss_gb, timeout)
    workers = resolve_jobs(jobs, max_rss_gb)
    cache = _open_cache(cache_dir, interpreter)
    tasks = [
        (which, index) for which, item in enumerate(prepared) for index in range(len(item.specs))
    ]
    logger.info(
        "referee: %d worker(s) for %d instance(s), %d at a time",
        len(tasks),
        len(prepared),
        workers,
    )
    finished: list[dict[int, _Outcome]] = [{} for _ in prepared]
    cancel = threading.Event()
    futures: dict[Future[_Outcome], tuple[int, int]] = {}
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="referee") as pool:
        try:
            for which, index in tasks:
                future = pool.submit(
                    _run_chunk, prepared[which], index, interpreter, guard, cancel, cache
                )
                futures[future] = (which, index)
            pending = set(futures)
            while pending:
                # Never an unbounded wait: a signal handler runs only when this
                # thread runs Python, and a signal the kernel hands to another
                # thread (polars keeps several) does not wake a blocked wait.
                done, pending = wait(pending, timeout=_POLL_SECONDS, return_when=FIRST_COMPLETED)
                for future in sorted(done, key=futures.__getitem__):
                    which, index = futures[future]
                    finished[which][index] = future.result()
                    # Survive an interrupted run: what has been measured so far is on disk.
                    _write_progress(prepared[which], finished[which])
        except BaseException:
            cancel.set()
            for future in futures:
                future.cancel()
            raise
    return tuple(
        _merge(item, [finished[which][index] for index in range(len(item.specs))])
        for which, item in enumerate(prepared)
    )


def resolve_jobs(jobs: int | None, max_rss_gb: float) -> int:
    """How many workers run at once: ``jobs`` as given, or, for ``None``, as many as fit.

    As many as fit is ``max(1, min(CPUs, floor((MemAvailable - headroom) /
    max_rss_gb)))``. A worker may grow to its cap before the guard kills it, so
    it is the cap, not a typical peak, that is budgeted: the workers at once
    cannot together take the memory this process and the system need. The
    headroom is ``MEMORY_HEADROOM_GB``. Where ``/proc/meminfo`` gives no
    ``MemAvailable`` it is one, as the memory guard cannot run there either.

    Raises:
        ValueError: ``jobs`` is less than one.
    """
    if jobs is not None:
        if jobs < 1:
            raise ValueError(f"jobs must be at least 1, not {jobs}")
        available = _available_memory_gb()
        if available is not None and jobs * max_rss_gb > available - MEMORY_HEADROOM_GB:
            logger.warning(
                "referee: %d worker(s) at %.1f GB each can outgrow the %.1f GB available "
                "less %.1f GB headroom",
                jobs,
                max_rss_gb,
                available,
                MEMORY_HEADROOM_GB,
            )
        return jobs
    available = _available_memory_gb()
    if available is None:
        return 1
    fit = math.floor((available - MEMORY_HEADROOM_GB) / max_rss_gb)
    return max(1, min(_cpu_count(), fit))


@contextlib.contextmanager
def interrupt_on_sigterm() -> Iterator[None]:
    """While inside, SIGTERM ends a run as an interrupt does: its workers are killed.

    A worker runs in a session of its own, so no signal to the run reaches it,
    and SIGTERM's default action ends the run at once and leaves every worker
    it was running — several GB each — behind. Inside this block SIGTERM
    raises ``SystemExit(128 + SIGTERM)`` instead, which ``run_referees`` meets
    as any other exception: it kills its workers and propagates. CI's cancel
    sends SIGINT and then SIGTERM, so both must be heard.

    A no-op off the main thread, where a handler cannot be installed, and
    where there is no SIGTERM. The previous handler is restored on the way out.
    """
    if threading.current_thread() is not threading.main_thread() or not hasattr(signal, "SIGTERM"):
        yield
        return
    previous = signal.signal(signal.SIGTERM, _exit_on_signal)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def referee_cache_dir(default: Path) -> Path:
    """The worker-result cache folder: ``RWA_FILER_REFEREE_CACHE`` if set, else ``default``."""
    configured = os.environ.get(ENV_REFEREE_CACHE)
    return Path(configured) if configured else default


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
        cached: The result was reused from the cache and no worker ran; the
            Arelle timings are those of the run that stored it.
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
    cached: bool = False

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
    prepared: PreparedReferee,
    index: int,
    interpreter: Path,
    guard: _Guard,
    cancel: threading.Event,
    cache: _ResultCache | None = None,
) -> _Outcome:
    """Write the spec, run one guarded worker on it, and read back its result.

    The worker is handed the spec as its standard input and the result file as
    its standard output, and names no file itself. The result file is opened
    afresh, so a result an earlier run left behind is never read. With a
    cache, a stored result for the same key is written to the result file in
    the worker's place, and a worker that finished has its result stored —
    unless ``_not_storable`` finds a reason not to.
    """
    files = prepared.plan.chunks[index]
    module = prepared.module
    out = prepared.folder / f"chunk{index}.json"
    spec_path = out.with_suffix(".spec.json")
    spec_path.write_text(json.dumps(prepared.specs[index]), encoding="utf-8")
    stderr_path = out.with_suffix(".stderr.txt")
    key = cache.key(prepared.specs[index]) if cache is not None else None
    stored = cache.read(key) if cache is not None and key is not None else None
    if stored is not None:
        return _reused(prepared, index, key or "", stored, out, stderr_path)
    run = _run_guarded(
        [str(interpreter), "-I", str(WORKER_SCRIPT)], spec_path, out, stderr_path, guard, cancel
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
        result = _read_result(out)
        status = CHUNK_OK if result is not None else "worker wrote an unreadable result"
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
        refused = _not_storable(result, prepared, index) if result is not None else "no result"
        if cache is not None and key is not None:
            if refused is None:
                cache.write(key, out.read_bytes())
            else:
                logger.info("referee cache: worker %d not stored: %s", index, refused)
    else:
        logger.warning(
            "referee: worker %d lost with its %d assertion(s): %s",
            index,
            stat.assertions,
            status,
        )
    return _Outcome(stat=stat, files=files, result=result)


def _run_guarded(
    command: Sequence[str],
    stdin_path: Path,
    stdout_path: Path,
    stderr_path: Path,
    guard: _Guard,
    cancel: threading.Event | None = None,
) -> _WorkerRun:
    """Run one worker; kill it, and all it started, above the memory cap or timeout.

    Its standard streams are the three files named; the output file is truncated.

    The worker gets its own session so that the whole process group can be
    killed, which also means an interrupt of this process does not reach it:
    whatever ends the wait, a worker still running is killed on the way out.
    Run on a pool thread, the wait is ended by ``cancel``, which the thread
    that is interrupted sets; a worker whose turn comes after that is never
    launched.
    """
    started = time.monotonic()
    if cancel is not None and cancel.is_set():
        return _WorkerRun(wall_s=0.0, peak_rss_mb=None, returncode=None, killed=_INTERRUPTED)
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
                if killed is None and cancel is not None and cancel.is_set():
                    killed = _INTERRUPTED
        finally:
            if process.poll() is None:
                _kill(process)
    return _WorkerRun(
        wall_s=round(time.monotonic() - started, 1),
        peak_rss_mb=peak_kb // 1024 if guard.max_rss_kb is not None else None,
        returncode=process.returncode,
        killed=killed,
    )


def _exit_on_signal(signum: int, _frame: object) -> None:
    """A signal handler: end the run as ``SystemExit`` with the shell's status for it."""
    raise SystemExit(128 + signum)


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


def _read_result(path: Path) -> Mapping[str, Any] | None:
    """A worker's result file, if it reads as a result; None if it does not."""
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    return result if _is_result(result) else None


def _last_line(path: Path) -> str:
    """The last non-blank line a worker wrote to stderr — usually its exception."""
    lines = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    return lines[-1].strip()[:_STATUS_TAIL_CHARS] if lines else ""


def _write_progress(prepared: PreparedReferee, finished: Mapping[int, _Outcome]) -> None:
    """Rewrite an instance's ``progress.json``: its workers that have ended, in plan order."""
    (prepared.folder / "progress.json").write_text(
        json.dumps(
            {
                "chunks_planned": len(prepared.specs),
                "chunks": [asdict(finished[index].stat) for index in sorted(finished)],
            },
            indent=1,
        ),
        encoding="utf-8",
    )


def _available_memory_gb() -> float | None:
    """The kernel's estimate of memory available to new processes, in GB, if it gives one."""
    try:
        text = (_PROC / "meminfo").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / _KB_PER_GB
    return None


def _cpu_count() -> int:
    """The CPUs this process may run on."""
    if hasattr(os, "sched_getaffinity"):
        return len(os.sched_getaffinity(0))
    return os.cpu_count() or 1


def _reused(
    prepared: PreparedReferee,
    index: int,
    key: str,
    stored: bytes,
    out: Path,
    stderr_path: Path,
) -> _Outcome:
    """The outcome of a worker whose result the cache held: written as the worker would."""
    files = prepared.plan.chunks[index]
    out.write_bytes(stored)
    stderr_path.write_text(f"referee cache: result {key} reused; no worker ran\n", "utf-8")
    result = json.loads(stored)
    timings = result["timings"]
    stat = ChunkStat(
        index=index,
        assertions=len(files),
        assertion_xml_mb=round(
            sum(prepared.module.assertions[file].size for file in files) / _BYTES_PER_MB, 1
        ),
        status=CHUNK_OK,
        wall_s=0.0,
        peak_rss_mb=None,
        returncode=None,
        loaded_s=timings.get("loaded_s"),
        validated_s=timings.get("validated_s"),
        cached=True,
    )
    logger.info("referee: worker %d reused from the cache (%s)", index, key[:12])
    return _Outcome(stat=stat, files=files, result=result)


# =============================================================================
# Private helpers — the worker-result cache
# =============================================================================


class _ResultCache:
    """Workers' raw results by key, one file each, under ``folder/<2 hex>/<key>.entry``.

    An entry is a line ``sha256:<digest of the rest>`` and then the result,
    byte for byte (``_seal``): an entry whose digest does not match what
    follows — cut short, edited — is never read back.

    The key is a SHA-256 over what a worker's result depends on — the bytes of
    every file it reads (instance, packages, plug-in), the spec's other
    settings, the worker interpreter's identity (every installed distribution,
    the Python version, the locale) and this package's referee code — and over
    no path. Thread-safe: each entry is written to a temporary file and renamed,
    and a key is read and written by one worker only.
    """

    def __init__(self, folder: Path, *, arelle: str) -> None:
        self.folder = folder
        self.arelle = arelle
        self._package_digests: dict[str, str] = {}
        self._lock = threading.Lock()

    def key(self, spec: Mapping[str, Any]) -> str:
        """The key of the worker ``spec`` describes."""
        official, *overlays = spec["packages"]
        payload = {
            "arelle": self.arelle,
            "code": _code_sha256(),
            "instance": _file_sha256(Path(spec["instance"])),
            "packages": [
                self._package_sha256(Path(official)),
                *(_zip_members_sha256(Path(overlay)) for overlay in overlays),
            ],
            "plugin": _file_sha256(Path(spec["plugin"])) if spec["plugin"] else None,
            "spec": {name: value for name, value in spec.items() if name not in _SPEC_PATHS},
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def read(self, key: str) -> bytes | None:
        """The stored result for ``key``, if there is one and it reads back as a result."""
        path = self._path(key)
        try:
            content = _unseal(path.read_bytes())
        except OSError:
            return None
        try:
            readable = content is not None and _is_result(json.loads(content))
        except ValueError:
            readable = False
        if not readable:
            logger.warning("referee cache: ignoring an unreadable entry %s", path.name)
            return None
        with contextlib.suppress(OSError):
            os.utime(path)  # last used: a reader may prune what no run uses
        return content

    def write(self, key: str, content: bytes) -> None:
        """Store ``content`` under ``key``, whole or not at all; a failure is logged only."""
        path = self._path(key)
        temporary: str | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(
                dir=path.parent, prefix=f".{key[:12]}.", suffix=".tmp"
            )
            with os.fdopen(handle, "wb") as stream:
                stream.write(_seal(content))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            temporary = None
        except OSError as exc:
            logger.warning("referee cache: could not store %s: %s", path.name, exc)
        finally:
            if temporary is not None:
                with contextlib.suppress(OSError):
                    os.unlink(temporary)

    def _path(self, key: str) -> Path:
        return self.folder / key[:2] / f"{key}{_ENTRY_SUFFIX}"

    def _package_sha256(self, package: Path) -> str:
        """A taxonomy package's digest; read once per run, as every worker names it."""
        name = str(package.resolve())
        with self._lock:
            if name not in self._package_digests:
                self._package_digests[name] = _file_sha256(package)
            return self._package_digests[name]


def _seal(content: bytes) -> bytes:
    """A cache entry as stored: a line with the SHA-256 of ``content``, then ``content``."""
    return _DIGEST_PREFIX + hashlib.sha256(content).hexdigest().encode("ascii") + b"\n" + content


def _unseal(entry: bytes) -> bytes | None:
    """The content of a cache entry, if its digest line matches it; else None."""
    header, newline, content = entry.partition(b"\n")
    expected = _DIGEST_PREFIX + hashlib.sha256(content).hexdigest().encode("ascii")
    return content if newline and header == expected else None


def _open_cache(cache_dir: Path | None, interpreter: Path) -> _ResultCache | None:
    """The cache for this run, or ``None`` — asked for none, or no Arelle to key it by."""
    if cache_dir is None:
        return None
    arelle = _arelle_identity(interpreter)
    if arelle is None:
        logger.warning(
            "referee cache: the Arelle release of %s cannot be read, so no result is "
            "stored or reused in this run",
            interpreter,
        )
        return None
    logger.info("referee cache: %s", cache_dir)
    return _ResultCache(cache_dir, arelle=arelle)


def _arelle_identity(interpreter: Path) -> str | None:
    """What the workers run Arelle with — every distribution, Python, locale; None if unknown.

    None also where the interpreter has no ``arelle-release``: there is no
    Arelle to key a result by.
    """
    probe = _probe_interpreter(interpreter)
    if probe is None or not probe.get("arelle-release"):
        return None
    locale = {name: os.environ.get(name) for name in _LOCALE_VARIABLES}
    return json.dumps({"probe": probe, "locale": locale}, sort_keys=True)


def _probe_interpreter(interpreter: Path) -> dict[str, Any] | None:
    """``_IDENTITY_PROBE``'s answer from ``interpreter`` (isolated, as a worker is); None if none."""
    done = subprocess.run(  # noqa: S603 - the interpreter the caller named, a fixed probe
        [str(interpreter), "-I", "-c", _IDENTITY_PROBE],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        return None
    try:
        probe = json.loads(done.stdout)
    except ValueError:
        return None
    return probe if isinstance(probe, dict) else None


def _code_sources() -> list[Path]:
    """The referee code a worker's result depends on: the worker, the planner, the runner."""
    return [Path(WORKER_SCRIPT), Path(_plan_module.__file__), Path(__file__)]


def _code_sha256() -> str:
    """One digest over the referee code a worker's result depends on."""
    digest = hashlib.sha256()
    for source in _code_sources():
        digest.update(hashlib.sha256(source.read_bytes()).digest())
    return digest.hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(_HASH_BLOCK):
            digest.update(block)
    return digest.hexdigest()


def _zip_members_sha256(path: Path) -> str:
    """A digest of an archive's members, names and contents; not of the archive's bytes.

    An overlay is written afresh for every run, with the time in each member's
    header, so its bytes differ from run to run while what Arelle reads does not.
    """
    digest = hashlib.sha256()
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            digest.update(name.encode("utf-8") + b"\0")
            digest.update(hashlib.sha256(archive.read(name)).digest())
    return digest.hexdigest()


def _is_result(value: Any) -> bool:
    """Whether ``value`` has the shape of a worker's result, as the merge reads it."""
    if not isinstance(value, dict):
        return False
    assertions, examples = value.get("assertions"), value.get("examples")
    messages, timings = value.get("messages"), value.get("timings")
    if not (
        isinstance(assertions, dict)
        and isinstance(examples, dict)
        and isinstance(messages, list)
        and isinstance(timings, dict)
    ):
        return False
    counts_ok = all(
        isinstance(counts, list)
        and len(counts) == 2
        and all(isinstance(count, int) for count in counts)
        for counts in assertions.values()
    )
    messages_ok = all(
        isinstance(message, dict)
        and all(isinstance(message.get(field), str) for field in ("code", "level", "text"))
        for message in messages
    )
    examples_ok = all(
        isinstance(items, list) and all(_is_example(item) for item in items)
        for items in examples.values()
    )
    return counts_ok and messages_ok and examples_ok


def _is_example(value: Any) -> bool:
    """Whether ``value`` has the shape of one evaluation example, as the merge reads it."""
    return (
        isinstance(value, dict)
        and isinstance(value.get("level"), str)
        and isinstance(value.get("text"), str)
        and isinstance(value.get("facts"), list)
        and all(isinstance(fact, dict) for fact in value["facts"])
    )


def _not_storable(result: Mapping[str, Any], prepared: PreparedReferee, index: int) -> str | None:
    """Why a finished worker's result must not be stored, or None if it may be.

    Stored, a result is replayed by every run until a keyed input changes, so
    anything that may not happen again is refused: an assertion the worker was
    given and returned nothing for (the merge loses the rule), and a message at
    an error level or naming an exception — the form in which Arelle reports
    what it caught, a ``MemoryError`` among them. What the merge drops as noise
    or as a known false positive cannot change a result, and does not count.
    """
    assertions = prepared.module.assertions
    unanswered = sum(
        1
        for file in prepared.plan.chunks[index]
        if assertions[file].assertion_id not in result["assertions"]
    )
    if unanswered:
        return f"{unanswered} assertion(s) without a verdict"
    for message in result["messages"]:
        code, level = message["code"], message["level"]
        if code in NOISE_CODES or code in KNOWN_FALSE_POSITIVE_CODES:
            continue
        if level in ERROR_LEVELS or "exception" in code.lower():
            return f"[{code}] at {level}"
    return None


# =============================================================================
# Private helpers — merging
# =============================================================================


def _merge(prepared: PreparedReferee, outcomes: Sequence[_Outcome]) -> RefereeResult:
    """One result from every worker's, in plan order: verdicts by rule id, messages once each."""
    plan, module = prepared.plan, prepared.module
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
        schema_ref=prepared.schema_ref,
        filing_indicators=tuple(sorted(prepared.indicators)),
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
