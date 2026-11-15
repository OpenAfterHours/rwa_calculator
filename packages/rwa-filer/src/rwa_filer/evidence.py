"""
The evidence export — everything a validation executed, as one versioned file.

Pipeline position:
    CanonicalReturn  ->  collect_evidence  ->  validate.returns.trace_return
        ->  Evidence (the verdict and every evaluation behind it, from ONE pass)
        ->  write_evidence  ->  <name>.evidence.jsonl[.gz]
    <name>.evidence.jsonl[.gz]  ->  read_evidence  ->  EvidenceDocument

Key responsibilities:
- Record every enforced rule's outcome, passes included; every evaluation,
  satisfied or not, uncapped; every comparison an evaluation executed, with
  each operand's value and rounding allowance, the difference, the tolerance
  the ``i`` prefix allowed and how far outside it the difference fell; every
  reported cell read, once, with the ``decimals`` it was compared at and where
  that came from; every cell read at its default; and every fact a structure
  or reading finding is about.
- Never recompute: the evidence is captured inside the evaluation that reached
  the verdict (``trace_return``), so it cannot describe a different run.
- Identify itself: the header carries the same ``identity`` block as the
  validation report — fingerprints of the facts, the taxonomy pack, the rule
  book and the accuracy — and the trailer a SHA-256 over every line before it,
  so a truncated or altered file is detected on reading.
- Write deterministic bytes: the same inputs give the same file, unless a
  creation time is asked for.

Format: JSON Lines, one record per line, each with a ``record`` field —
``header``, then ``cell``, ``rule``, ``evaluation``, ``finding`` and
``structure_exception`` records in that order, then one ``trailer``. A path
ending ``.gz`` is gzip-compressed. ``schemas/evidence-1.schema.json`` (shipped
in the wheel) is the contract: within a major version, changes only add.

References:
- docs/plans/rwa-filer-evidence-export.md — the design this implements
- rwa_filer.boe.engine — ``Comparison`` states the interval semantics
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import math
from collections import Counter
from dataclasses import dataclass, field
from typing import IO, TYPE_CHECKING, Any, Final

from rwa_filer.validate.identity import identity_record, source_identity
from rwa_filer.validate.report import (
    cause_record,
    finding_record,
    rule_record,
)
from rwa_filer.validate.returns import trace_return

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
    from datetime import datetime
    from pathlib import Path

    from rwa_filer.boe.catalogue import Rule, RuleBook
    from rwa_filer.boe.engine import (
        Accuracy,
        CellAddress,
        CellFact,
        Comparison,
        DefaultedCell,
        Evaluation,
        Operand,
        RuleResult,
        RuleTrace,
    )
    from rwa_filer.model import CanonicalReturn
    from rwa_filer.taxonomy.pack import TaxonomyPack
    from rwa_filer.validate.checker import FactPosition, Finding
    from rwa_filer.validate.identity import SourceIdentity
    from rwa_filer.validate.returns import ReturnValidation

__all__ = [
    "EVIDENCE_SCHEMA_NAME",
    "EVIDENCE_SCHEMA_VERSION",
    "RECORD_CELL",
    "RECORD_EVALUATION",
    "RECORD_FINDING",
    "RECORD_HEADER",
    "RECORD_RULE",
    "RECORD_STRUCTURE_EXCEPTION",
    "RECORD_TRAILER",
    "Evidence",
    "EvidenceDocument",
    "EvidenceFile",
    "collect_evidence",
    "read_evidence",
    "write_evidence",
]

logger = logging.getLogger(__name__)

#: The file's name and version (the header's ``schema``). The major version
#: changes when a field is renamed, removed or changes meaning.
EVIDENCE_SCHEMA_NAME: Final = "rwa-filer/evidence"
EVIDENCE_SCHEMA_VERSION: Final = "1.0"

RECORD_HEADER: Final = "header"
RECORD_CELL: Final = "cell"
RECORD_RULE: Final = "rule"
RECORD_EVALUATION: Final = "evaluation"
RECORD_FINDING: Final = "finding"
RECORD_STRUCTURE_EXCEPTION: Final = "structure_exception"
RECORD_TRAILER: Final = "trailer"
#: The body's record types, in the order they are written.
BODY_RECORDS: Final = (
    RECORD_CELL,
    RECORD_RULE,
    RECORD_EVALUATION,
    RECORD_FINDING,
    RECORD_STRUCTURE_EXCEPTION,
)

_GZIP_SUFFIX: Final = ".gz"


# =============================================================================
# Public entry points
# =============================================================================


@dataclass(frozen=True)
class Evidence:
    """A validation and every evaluation behind it, from one pass.

    Attributes:
        ret: The return validated.
        validation: The verdict — the same object ``validate_return`` returns.
        trace: Every evaluation the rules made; ``None`` when no rule book
            covers the module, so no rule ran.
    """

    ret: CanonicalReturn
    validation: ReturnValidation
    trace: RuleTrace | None

    @property
    def identity(self) -> dict[str, Any]:
        """The ``identity`` block the report and the file share."""
        return identity_record(self.ret, self.validation)


@dataclass(frozen=True)
class EvidenceFile:
    """What ``write_evidence`` wrote.

    Attributes:
        path: The file.
        sha256: The SHA-256 of its bytes, as written (compressed, for ``.gz``).
        content_sha256: The trailer's digest: over every line before it.
        evidence_id: The identity block's ``evidence_id``.
        records: How many records of each type it holds.
    """

    path: Path
    sha256: str
    content_sha256: str
    evidence_id: str
    records: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceDocument:
    """An evidence file, read back and checked complete. Records are plain dicts."""

    header: Mapping[str, Any]
    cells: tuple[Mapping[str, Any], ...]
    rules: tuple[Mapping[str, Any], ...]
    evaluations: tuple[Mapping[str, Any], ...]
    findings: tuple[Mapping[str, Any], ...]
    structure_exceptions: tuple[Mapping[str, Any], ...]
    trailer: Mapping[str, Any]


def collect_evidence(
    ret: CanonicalReturn,
    pack: TaxonomyPack | None = None,
    *,
    rulebook: RuleBook | None = None,
    accuracy: Accuracy | None = None,
    source_findings: Sequence[Finding] = (),
    source: SourceIdentity | None = None,
) -> Evidence:
    """Validate ``ret`` as ``validate_return`` does, keeping everything it executed.

    The arguments are ``validate_return``'s. Never raises for a condition in
    the data.

    Raises:
        PackNotFoundError: no ``pack`` was given and none is packaged.
    """
    validation, trace = trace_return(
        ret,
        pack,
        rulebook=rulebook,
        accuracy=accuracy,
        source_findings=source_findings,
        source=source,
    )
    return Evidence(ret=ret, validation=validation, trace=trace)


def write_evidence(
    evidence: Evidence, path: Path, *, generated_at: datetime | None = None
) -> EvidenceFile:
    """Write ``evidence`` to ``path`` as JSON Lines (gzip-compressed for ``.gz``).

    Args:
        evidence: What to write.
        path: The file; its directory is created.
        generated_at: Recorded in the header. Left out, the file is the same
            bytes for the same inputs.

    Returns:
        An ``EvidenceFile`` with the file's checksum and record counts.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    counts: Counter[str] = Counter()
    identity = evidence.identity
    with path.open("wb") as raw:
        stream = _compressed(raw) if path.suffix == _GZIP_SUFFIX else raw
        try:
            for record in _records(evidence, identity, generated_at):
                line = _line(record)
                digest.update(line)
                counts[record["record"]] += 1
                stream.write(line)
            body = {name: counts[name] for name in BODY_RECORDS}
            stream.write(
                _line(
                    {
                        "record": RECORD_TRAILER,
                        "counts": body,
                        "content_sha256": digest.hexdigest(),
                    }
                )
            )
        finally:
            if stream is not raw:
                stream.close()
    written = EvidenceFile(
        path=path,
        sha256=source_identity(path).sha256,
        content_sha256=digest.hexdigest(),
        evidence_id=identity["evidence_id"],
        records={name: counts[name] for name in BODY_RECORDS},
    )
    logger.info(
        "evidence written: %s (%d evaluation(s), %d cell(s))",
        path.name,
        counts[RECORD_EVALUATION],
        counts[RECORD_CELL],
    )
    return written


def read_evidence(path: Path) -> EvidenceDocument:
    """Read an evidence file back, refusing one that is incomplete or altered.

    Raises:
        ValueError: the file is not an evidence file of a version this package
            reads, its records are out of order, it has no trailer, or the
            trailer's digest or counts do not match what precedes it.
    """
    opener = gzip.open if path.suffix == _GZIP_SUFFIX else open
    digest = hashlib.sha256()
    header: dict[str, Any] | None = None
    trailer: dict[str, Any] | None = None
    body: dict[str, list[dict[str, Any]]] = {name: [] for name in BODY_RECORDS}
    stage = 0
    with opener(path, "rb") as handle:
        for number, line in enumerate(handle, start=1):
            if trailer is not None:
                raise ValueError(f"{path.name}: line {number} follows the trailer")
            record = json.loads(line)
            kind = record.get("record")
            if kind == RECORD_TRAILER:
                trailer = record
                continue
            digest.update(line)
            if number == 1:
                header = _checked_header(path, record)
                continue
            if kind not in body:
                raise ValueError(f"{path.name}: line {number} is not an evidence record")
            position = BODY_RECORDS.index(kind)
            if position < stage:
                raise ValueError(f"{path.name}: line {number} ({kind}) is out of order")
            stage = position
            body[kind].append(record)
    if header is None or trailer is None:
        raise ValueError(f"{path.name}: not a complete evidence file (no header or no trailer)")
    _check_trailer(path, header, trailer, body, digest.hexdigest())
    return EvidenceDocument(
        header=header,
        cells=tuple(body[RECORD_CELL]),
        rules=tuple(body[RECORD_RULE]),
        evaluations=tuple(body[RECORD_EVALUATION]),
        findings=tuple(body[RECORD_FINDING]),
        structure_exceptions=tuple(body[RECORD_STRUCTURE_EXCEPTION]),
        trailer=trailer,
    )


# =============================================================================
# Private helpers — the records
# =============================================================================


def _records(
    evidence: Evidence, identity: Mapping[str, Any], generated_at: datetime | None
) -> Iterator[dict[str, Any]]:
    """Every record but the trailer, in file order."""
    validation = evidence.validation
    trace = evidence.trace
    facts = trace.cells if trace is not None else {}
    cells = _numbered(facts)
    findings = validation.findings
    counts = {
        RECORD_CELL: len(cells),
        RECORD_RULE: len(trace.results) if trace is not None else 0,
        RECORD_EVALUATION: len(trace.evaluations) if trace is not None else 0,
        RECORD_FINDING: len(findings),
        RECORD_STRUCTURE_EXCEPTION: sum(len(finding.positions) for finding in findings),
    }
    yield {
        "record": RECORD_HEADER,
        "schema": {"name": EVIDENCE_SCHEMA_NAME, "version": EVIDENCE_SCHEMA_VERSION},
        "generated_at": generated_at.isoformat(timespec="seconds") if generated_at else None,
        "identity": identity,
        "status": validation.status,
        "submittable": validation.is_submittable,
        "completeness": [cause_record(cause) for cause in validation.completeness],
        "counts": counts,
    }
    for address, number in cells.items():
        yield _cell_record(number, facts[address])
    if trace is not None:
        module = validation.pack.info.module
        rules = (
            {rule.rule_id: rule for rule in validation.rulebook.rules}
            if validation.rulebook
            else {}
        )
        for result in trace.results:
            yield _rule_record(result, rules.get(result.rule_id), module)
        sequence: Counter[str] = Counter()
        for evaluation in trace.evaluations:
            yield _evaluation_record(evaluation, sequence[evaluation.rule_id], cells)
            sequence[evaluation.rule_id] += 1
    for index, finding in enumerate(findings):
        yield {"record": RECORD_FINDING, "index": index, **finding_record(finding)}
    for index, finding in enumerate(findings):
        for position in finding.positions:
            yield {
                "record": RECORD_STRUCTURE_EXCEPTION,
                "finding": index,
                "code": finding.code,
                "position": _position_record(position),
            }


def _numbered(cells: Mapping[CellAddress, CellFact]) -> dict[CellAddress, int]:
    """Each reported cell's id: its place in coordinate order."""
    ordered = sorted(
        cells,
        key=lambda address: (
            address.table,
            address.sheet or "",
            address.open_key or "",
            address.row,
            address.column,
        ),
    )
    return {address: number for number, address in enumerate(ordered)}


def _cell_record(number: int, fact: CellFact) -> dict[str, Any]:
    address = fact.address
    return {
        "record": RECORD_CELL,
        "id": number,
        "table": address.table,
        "sheet": address.sheet,
        "open_key": address.open_key,
        "row": address.row,
        "column": address.column,
        "datapoint": fact.datapoint,
        "metric": fact.metric,
        "data_type": fact.data_type,
        "value": _plain(fact.value),
        "decimals": fact.decimals,
        "decimals_source": fact.decimals_source,
        "allowance": _finite(fact.allowance),
    }


def _rule_record(result: RuleResult, rule: Rule | None, module: str) -> dict[str, Any]:
    outcome = rule_record(result, rule.fingerprint(module) if rule is not None else None)
    # Every unsatisfied evaluation is an evaluation record: the first few the
    # summary report keeps would only repeat some of them here.
    del outcome["failures"]
    return {
        "record": RECORD_RULE,
        **outcome,
        "label": rule.label if rule is not None else None,
        "expression": rule.expression if rule is not None else None,
        "scope": rule.scope if rule is not None else None,
        "where": rule.where if rule is not None else None,
        "join": rule.join if rule is not None else None,
    }


def _evaluation_record(
    evaluation: Evaluation, sequence: int, cells: Mapping[CellAddress, int]
) -> dict[str, Any]:
    return {
        "record": RECORD_EVALUATION,
        "rule_id": evaluation.rule_id,
        "seq": sequence,
        "place": dict(evaluation.place),
        "holds": evaluation.holds,
        "relation": evaluation.relation,
        "left_value": _finite(evaluation.left_value),
        "right_value": _finite(evaluation.right_value),
        "left": _side(evaluation.left, cells),
        "right": _side(evaluation.right, cells),
        "comparisons": [_comparison_record(item, cells) for item in evaluation.comparisons],
    }


def _side(addresses: Sequence[CellAddress], cells: Mapping[CellAddress, int]) -> dict[str, Any]:
    """The cells one side read: reported ones by id, the rest by address."""
    return {
        "cells": [cells[address] for address in addresses if address in cells],
        "unreported": [_address(address) for address in addresses if address not in cells],
    }


def _comparison_record(comparison: Comparison, cells: Mapping[CellAddress, int]) -> dict[str, Any]:
    return {
        "operator": comparison.operator,
        "interval": comparison.interval,
        "branch": comparison.branch,
        "holds": comparison.holds,
        "difference": _finite(comparison.difference),
        "tolerance": _finite(comparison.tolerance),
        "excess": _finite(comparison.excess),
        "left": _operand_record(comparison.left, cells),
        "right": _operand_record(comparison.right, cells),
    }


def _operand_record(operand: Operand, cells: Mapping[CellAddress, int]) -> dict[str, Any]:
    return {
        "value": _plain(operand.value),
        "allowance": _finite(operand.allowance),
        "cells": [cells[address] for address in operand.cells],
        "defaulted": [_defaulted_record(item) for item in operand.defaulted],
    }


def _defaulted_record(cell: DefaultedCell) -> dict[str, Any]:
    return {
        "reference": cell.reference,
        "default": cell.default,
        "default_value": cell.default_value,
        "address": None if cell.address is None else _address(cell.address),
    }


def _position_record(position: FactPosition) -> dict[str, Any]:
    return {
        "table": position.table,
        "sheet": position.sheet,
        "open_key": position.open_key,
        "row": position.row,
        "column": position.column,
        "value": _finite(position.value),
        "text_value": position.text_value,
        "detail": position.detail,
        "source_ref": position.source_ref,
    }


def _address(address: CellAddress) -> dict[str, Any]:
    return {
        "table": address.table,
        "sheet": address.sheet,
        "open_key": address.open_key,
        "row": address.row,
        "column": address.column,
    }


# =============================================================================
# Private helpers — bytes
# =============================================================================


def _plain(value: object) -> float | str | bool | None:
    """A value JSON can carry: a non-finite number becomes ``None``."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, (int, float)):
        return _finite(float(value))
    return str(value)


def _finite(value: float | None) -> float | None:
    """``value``, or ``None`` for NaN and infinities, which JSON cannot carry."""
    if value is None or not math.isfinite(value):
        return None
    return value


def _line(record: Mapping[str, Any]) -> bytes:
    text = json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return (text + "\n").encode("utf-8")


def _compressed(raw: IO[bytes]) -> gzip.GzipFile:
    """A gzip stream over ``raw`` that records no name or time, so its bytes repeat."""
    return gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0)


def _checked_header(path: Path, record: Mapping[str, Any]) -> dict[str, Any]:
    if record.get("record") != RECORD_HEADER:
        raise ValueError(f"{path.name}: the first record is not an evidence header")
    schema = record.get("schema") or {}
    major = EVIDENCE_SCHEMA_VERSION.split(".", 1)[0]
    if (
        schema.get("name") != EVIDENCE_SCHEMA_NAME
        or str(schema.get("version", "")).split(".", 1)[0] != major
    ):
        raise ValueError(
            f"{path.name}: schema {schema.get('name')!r} {schema.get('version')!r} is not "
            f"{EVIDENCE_SCHEMA_NAME} {major}.x"
        )
    return dict(record)


def _check_trailer(
    path: Path,
    header: Mapping[str, Any],
    trailer: Mapping[str, Any],
    body: Mapping[str, list[dict[str, Any]]],
    content_sha256: str,
) -> None:
    if trailer.get("content_sha256") != content_sha256:
        raise ValueError(f"{path.name}: the content does not match the trailer's digest")
    found = {name: len(records) for name, records in body.items()}
    for claimed, where in ((header.get("counts"), "header"), (trailer.get("counts"), "trailer")):
        if claimed != found:
            raise ValueError(
                f"{path.name}: the {where} counts {claimed} but the file holds {found}"
            )
