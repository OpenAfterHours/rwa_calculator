"""
Readers — turn a file into a canonical return.

Pipeline position:
    file (.parquet / .csv / .xlsx)  ->  read_return  ->  CanonicalReturn
        ->  validate.validate_return

Key responsibilities:
- Read each supported file format into the one canonical shape
  (``rwa_filer.model``). A reader's whole job is coordinates and types; it makes
  no judgment about the figures.
- Never lose a fact silently. A cell a reader cannot make sense of is kept, as
  text, so the structure check reports it — a reader that dropped it would turn
  a filer's typo into an unreported figure.

Module map:
- ``tabular`` — long-format fact tables: Parquet and CSV
- ``excel``   — the workbook layout (one worksheet per table and sheet), and
                the blank-template writer that produces it

References:
- rwa_filer.model — the canonical fact schema
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from rwa_filer.model import LEI_SCHEME, ReturnHeader
from rwa_filer.readers.tabular import read_csv, read_parquet

if TYPE_CHECKING:
    from datetime import date
    from pathlib import Path

    from rwa_filer.model import CanonicalReturn
    from rwa_filer.taxonomy.pack import TaxonomyPack
    from rwa_filer.validate.checker import Finding

__all__ = [
    "INSTANCE_SUFFIXES",
    "SUPPORTED_SUFFIXES",
    "HeaderFields",
    "SourceReading",
    "carries_header",
    "load_source",
    "open_source",
    "read_csv",
    "read_parquet",
    "read_return",
]

#: File suffixes ``read_return`` understands.
SUPPORTED_SUFFIXES: tuple[str, ...] = (".parquet", ".csv", ".xlsx")

#: An XBRL instance, bare or zipped — read by ``load_source``.
INSTANCE_SUFFIXES: tuple[str, ...] = (".xbrl", ".zip")


@dataclass(frozen=True)
class SourceReading:
    """A return read from a file, with what the reading itself established.

    Attributes:
        ret: The return.
        pack: The taxonomy the source names for itself — an XBRL instance does,
            in its ``schemaRef`` — or ``None`` where the source names none and
            the pack follows from the header.
        findings: What the source holds that could not be read as part of the
            module. Empty for a fact table or workbook, whose every cell is
            checked by the structure checks instead.
    """

    ret: CanonicalReturn
    pack: TaxonomyPack | None = None
    findings: tuple[Finding, ...] = ()


@dataclass(frozen=True)
class HeaderFields:
    """Return-header fields a person supplies beside a file, each optional.

    A fact table needs the first three: it carries no header of its own. A
    workbook or an instance carries one, and any field given here overrides it.
    """

    entity: str | None = None
    reference_date: date | None = None
    module: str | None = None
    currency: str | None = None
    entity_scheme: str | None = None


def carries_header(path: Path) -> bool:
    """Whether a file of this type states its own return header."""
    suffix = path.suffix.lower()
    return suffix == ".xlsx" or suffix in INSTANCE_SUFFIXES


def open_source(path: Path, fields: HeaderFields | None = None) -> SourceReading:
    """Read a file a person named, as ``rwa-filer validate`` and the dashboard do.

    Checks the file exists and is of a supported type, reads it, and applies any
    header field given over the header the file states.

    Raises:
        ValueError: the file is missing, of an unsupported type, lacks a header
            it needs, or is not readable as what its suffix says it is.
    """
    fields = fields or HeaderFields()
    suffix = path.suffix.lower()
    if not path.is_file():
        raise ValueError(f"file not found: {path}")
    if suffix not in (*SUPPORTED_SUFFIXES, *INSTANCE_SUFFIXES):
        accepted = ", ".join((*SUPPORTED_SUFFIXES, *INSTANCE_SUFFIXES))
        raise ValueError(f"unsupported file type {path.suffix!r}; expected one of {accepted}")
    source = load_source(path, _header(fields, required=not carries_header(path)))
    overrides = {
        "entity_identifier": fields.entity,
        "reference_date": fields.reference_date,
        "module": fields.module,
        "currency": fields.currency,
        "entity_scheme": fields.entity_scheme,
    }
    changed = {name: value for name, value in overrides.items() if value}
    if not changed:
        return source
    ret = source.ret
    return replace(source, ret=replace(ret, header=replace(ret.header, **changed)))


def load_source(path: Path, header: ReturnHeader | None = None) -> SourceReading:
    """Read any supported file: a fact table, a workbook, or an XBRL instance.

    Args:
        path: ``.parquet`` / ``.csv`` / ``.xlsx`` (see ``read_return``), or a
            ``.xbrl`` instance, or a ``.zip`` holding one.
        header: Required for Parquet and CSV. An instance carries its own.

    Raises:
        ValueError: the suffix is not supported, a tabular file was given
            without a header, or an instance is not readable as one.
    """
    if path.suffix.lower() not in INSTANCE_SUFFIXES:
        return SourceReading(ret=read_return(path, header))
    from rwa_filer.xbrl.reader import read_instance

    reading = read_instance(path)
    return SourceReading(ret=reading.ret, pack=reading.pack, findings=reading.findings)


def read_return(path: Path, header: ReturnHeader | None = None) -> CanonicalReturn:
    """Read ``path`` into a canonical return, choosing the reader by suffix.

    Args:
        path: A ``.parquet`` or ``.csv`` long-format fact table, or a ``.xlsx``
            workbook in the template layout.
        header: Who is reporting and for which date. REQUIRED for Parquet and
            CSV, which carry facts only. A workbook carries its own header on
            its ``Return`` sheet; pass one to override it.

    Raises:
        ValueError: the suffix is not supported, or a tabular file was given
            without a header. (Usage errors — not conditions in the data.)
    """
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        from rwa_filer.readers.excel import read_workbook

        return read_workbook(path, header)
    if suffix not in (".parquet", ".csv"):
        supported = ", ".join(SUPPORTED_SUFFIXES)
        raise ValueError(f"Unsupported file type {suffix!r}; expected one of {supported}")
    if header is None:
        raise ValueError(
            f"{path.name} carries facts only: supply the return header "
            "(entity identifier, reference date, module)"
        )
    return read_parquet(path, header) if suffix == ".parquet" else read_csv(path, header)


def _header(fields: HeaderFields, *, required: bool) -> ReturnHeader | None:
    """A header from ``fields``, or ``None`` when the file supplies its own.

    Raises:
        ValueError: the file needs a header and the three required fields were
            not all given.
    """
    if not (fields.entity and fields.reference_date and fields.module):
        if required:
            raise ValueError(
                "a fact table carries no header: --entity, --reference-date and --module "
                "are all required"
            )
        return None
    return ReturnHeader(
        entity_identifier=fields.entity,
        reference_date=fields.reference_date,
        module=fields.module,
        currency=fields.currency or "GBP",
        entity_scheme=fields.entity_scheme or LEI_SCHEME,
    )
