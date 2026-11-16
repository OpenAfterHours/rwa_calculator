"""
Evidence identity — what a validation result was computed from, as fingerprints.

Pipeline position:
    file  ->  source_identity  ->  SourceIdentity  ->  validate_return(source=...)
    CanonicalReturn + ReturnValidation  ->  identity_record
        ->  the ``identity`` block of the validation report and the evidence export

Key responsibilities:
- Name every input a verdict depends on — the return's facts, the taxonomy pack,
  the rule book, the Bank's deny-list entries in force, the accuracy the
  comparisons allowed for, and the engine version — by a SHA-256 a second run
  can reproduce.
- Give the whole a single ``evidence_id``: two runs with the same id ran the
  same checks on the same figures, so their results can be compared before any
  detail is read. The file a return came from is recorded but is not part of
  the id: the same facts re-exported to another format are the same input. Nor
  is the date the deny list was applied for, nor its file: what the id covers
  is the entries in force for the module, so a run a day later is the same run
  unless the Bank's gateway changed in between.
- Keep every digest one function (``boe.catalogue.canonical_sha256``), so a
  value hashed in two places gives one answer.

References:
- docs/plans/rwa-filer-evidence-export.md — the design this implements
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from rwa_filer import __version__
from rwa_filer.boe.catalogue import canonical_sha256
from rwa_filer.model import FACT_SCHEMA

if TYPE_CHECKING:
    from pathlib import Path

    from rwa_filer.model import CanonicalReturn
    from rwa_filer.validate.returns import ReturnValidation

#: The package that computed a result, as the identity names it.
GENERATOR_PACKAGE: Final = "rwa-filer"
#: How ``accuracy.source`` says the run's accuracy was chosen.
ACCURACY_DEFAULT: Final = "default"
ACCURACY_GIVEN: Final = "given"

#: Bytes read at a time when a source file is hashed.
_CHUNK: Final = 1 << 20


# =============================================================================
# Public entry points
# =============================================================================


@dataclass(frozen=True)
class SourceIdentity:
    """The file a return was read from.

    Attributes:
        file: Its name (not its path: where a file sits is not what it holds).
        format: ``parquet``, ``csv``, ``xlsx``, ``xbrl`` or ``zip``.
        sha256: The SHA-256 of its bytes.
    """

    file: str
    format: str
    sha256: str


def source_identity(path: Path) -> SourceIdentity:
    """Fingerprint the file at ``path``.

    Raises:
        OSError: the file cannot be read.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return SourceIdentity(
        file=path.name, format=path.suffix.lower().lstrip("."), sha256=digest.hexdigest()
    )


def identity_record(ret: CanonicalReturn, validation: ReturnValidation) -> dict[str, Any]:
    """The ``identity`` block: every input of the verdict, fingerprinted.

    ``evidence_id`` covers the generator, the facts and header, the taxonomy
    pack, the rule book, the deny-list entries in force and the accuracy's
    value — not the source file's name, format or bytes, nor whether the
    accuracy was the default, nor the deny list's file and the date it was
    applied for, which are recorded beside it.
    """
    info = validation.pack.info
    rulebook = validation.rulebook
    accuracy = validation.accuracy
    record: dict[str, Any] = {
        "generator": {"package": GENERATOR_PACKAGE, "version": __version__},
        "input": {
            "file": validation.source.file if validation.source else None,
            "format": validation.source.format if validation.source else None,
            "file_sha256": validation.source.sha256 if validation.source else None,
            "facts_sha256": facts_sha256(ret),
            "facts": ret.facts.height,
            "header": ret.header.as_fields(),
        },
        "taxonomy": {
            "module": info.module,
            "version": info.version,
            "pack": info.key,
            "entry_point": info.entry_point,
            "sha256": validation.pack.content_sha256,
        },
        "rulebook": None
        if rulebook is None
        else {
            "file": rulebook.file,
            "framework_version": rulebook.framework_version,
            "taxonomy": rulebook.taxonomy,
            "sha256": rulebook.content_sha256 or None,
            "workbook_sha256": rulebook.source.get("sha256"),
            "formulas_package_sha256": (rulebook.source.get("formulas") or {}).get(
                "package_sha256"
            ),
            "rules_loaded": len(rulebook.rules),
            "rules_enforced": len(rulebook.enforced(info.module)),
        },
        "settings": {
            "accuracy": {
                "monetary_decimals": accuracy.monetary_decimals,
                "percentage_decimals": accuracy.percentage_decimals,
                "source": ACCURACY_GIVEN if validation.accuracy_given else ACCURACY_DEFAULT,
            }
        },
        "deny_list": _deny_identity(validation),
    }
    identified = {
        **{key: record[key] for key in ("generator", "taxonomy", "rulebook")},
        "input": {key: record["input"][key] for key in ("facts_sha256", "facts", "header")},
        # The accuracy's value is an input; how it was chosen is not.
        "accuracy": [accuracy.monetary_decimals, accuracy.percentage_decimals],
    }
    if record["deny_list"] is not None:
        # What the gateway ran is an input; the day it was worked out on is not.
        identified["deny_list"] = record["deny_list"]["in_force"]
    return {"evidence_id": canonical_sha256(identified), **record}


def facts_sha256(ret: CanonicalReturn) -> str:
    """SHA-256 of the return's content, independent of row order and file format.

    The header, the declared filing indicators and every fact, sorted by its
    coordinates, each written as canonical JSON on its own line.
    """
    digest = hashlib.sha256()
    preamble = {
        "header": ret.header.as_fields(),
        "indicators": None if ret.indicators is None else dict(sorted(ret.indicators.items())),
    }
    digest.update(_line(preamble))
    columns = list(FACT_SCHEMA.names())
    facts = ret.facts.select(columns).sort(columns, nulls_last=False)
    for row in facts.iter_rows():
        digest.update(_line(list(row)))
    return digest.hexdigest()


# =============================================================================
# Private helpers
# =============================================================================


def _deny_identity(validation: ReturnValidation) -> dict[str, Any] | None:
    """The deny list applied: its file, the date, and the entries in force for the module."""
    day = validation.deny_date
    if day is None:
        return None
    deny_list = validation.release.deny_list
    in_force = deny_list.in_force(validation.pack.info.module, day)
    return {
        "release": deny_list.release,
        "file": deny_list.file,
        "sha256": deny_list.content_sha256 or None,
        "applied_on": day.isoformat(),
        "in_force": [in_force[rule_id].record() for rule_id in sorted(in_force)],
    }


def _line(content: object) -> bytes:
    text = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return (text + "\n").encode("utf-8")
