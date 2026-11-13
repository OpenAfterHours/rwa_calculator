"""
The canonical return — one header plus one long fact table, in the supervisor's coordinates.

Pipeline position:
    readers (Parquet / CSV / Excel) | a host application's adapter
        ->  CanonicalReturn(header, facts)
        ->  validate.structure  ->  validate (published rules)  ->  xbrl writer

Key responsibilities:
- Define the ONE shape every source of figures produces and every check and
  writer consumes. Supporting a new input format means writing a reader that
  yields this shape; nothing downstream changes.
- Address every figure the way the regulator does: table code, row code, column
  code and sheet — never by a source's own names for them.
- Normalise what a source hands over (column order, integer-looking codes, a
  missing optional column) into the exact schema, and refuse — loudly, as a
  programming error — a frame that cannot be a fact table at all.

The coordinates
- ``table``: the publisher's table code, e.g. ``OF07.00.01.01``.
- ``sheet``: the code of a FIXED sheet (z) axis, e.g. ``0008``; null when the
  table has none.
- ``open_key``: the member chosen on an OPEN sheet axis — a country, say —
  written as the member's local name (``GB``); null when the table has none.
- ``row`` / ``column``: the publisher's row and column codes. In an open-row
  table there is no published row code: ``row`` is any identifier that is
  unique within the table and sheet, and the row's key values are themselves
  facts, in the key columns.
- ``value`` carries a number; ``text_value`` carries anything else (a string,
  an enumeration member, an ISO date, ``true`` / ``false``). Exactly one of the
  two is set on every fact.
- ``decimals`` is the accuracy a NUMBER is stated to, as XBRL writes it: ``-3``
  is accurate to thousands, ``2`` to pence. Optional — null means "the default
  for the value's type" — and it is what the regulator's interval arithmetic
  reads, so a source that knows its figures are rounded should say so.

Units: a monetary value is in units of the reporting currency, never thousands
or millions. A percentage or ratio is a decimal fraction — 9.31% is ``0.0931``.

Filing indicators say which templates the return reports. Left unset, every
template with a fact is reported and no other is. Set, they are taken as given:
a template may be reported with no facts at all (every cell is then zero to the
regulator's checks), or declared not reported.

What a fact is NOT: a cell that is not reported has NO row here. There is no
"null fact" — an unreported figure and a reported zero are different things,
and only the second one is a fact.

References:
- BoE XBRL Filing Manual v1.0.1 — entity identifier scheme, single reference
  date, single reporting currency
- Bank of England Banking Taxonomy — the table / row / column / sheet codes
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Final

import polars as pl

if TYPE_CHECKING:
    from collections.abc import Mapping

# =============================================================================
# Constants
# =============================================================================

#: The identifier scheme for a Legal Entity Identifier (ISO 17442) — the scheme
#: the BoE Filing Manual requires where the reporting entity has an LEI.
LEI_SCHEME: Final = "http://standards.iso.org/iso/17442"

#: The fact table, in column order.
FACT_SCHEMA: Final = pl.Schema(
    {
        "table": pl.String,
        "sheet": pl.String,
        "open_key": pl.String,
        "row": pl.String,
        "column": pl.String,
        "value": pl.Float64,
        "text_value": pl.String,
        "decimals": pl.Int32,
    }
)

#: Columns a source MUST supply. ``sheet``, ``open_key`` and ``text_value`` are
#: optional: a return with single-sheet numeric tables has none of them. So is
#: ``decimals``.
REQUIRED_FACT_COLUMNS: Final[tuple[str, ...]] = ("table", "row", "column", "value")

#: The coordinate columns — what identifies a cell.
COORDINATE_COLUMNS: Final[tuple[str, ...]] = ("table", "sheet", "open_key", "row", "column")

#: Width the publisher writes row, column and sheet codes at.
CODE_WIDTH: Final = 4

#: The ``decimals`` of a figure stated to be exact — XBRL's ``decimals="INF"``.
DECIMALS_EXACT: Final = 99

# Header field labels, as written to and read from a metadata sheet or file.
_FIELD_ENTITY: Final = "Entity identifier"
_FIELD_SCHEME: Final = "Entity identifier scheme"
_FIELD_NAME: Final = "Entity name"
_FIELD_DATE: Final = "Reference date"
_FIELD_MODULE: Final = "Module"
_FIELD_CURRENCY: Final = "Currency"
_FIELD_BASIS: Final = "Consolidation basis"


# =============================================================================
# Header
# =============================================================================


@dataclass(frozen=True)
class ReturnHeader:
    """Who is reporting, for which date, on which module, in which currency.

    Attributes:
        entity_identifier: The reporting entity's identifier — its LEI where it
            has one.
        reference_date: The single date the return reports as at.
        module: The reporting module (taxonomy entry point), e.g. ``"PRA001"``.
        currency: The single ISO 4217 reporting currency.
        entity_scheme: The identifier scheme; the LEI scheme by default.
        entity_name: A display name. Informational — it is not submitted.
        consolidation_basis: Individual / consolidated. Informational.
    """

    entity_identifier: str
    reference_date: date
    module: str
    currency: str = "GBP"
    entity_scheme: str = LEI_SCHEME
    entity_name: str | None = None
    consolidation_basis: str | None = None

    def as_fields(self) -> dict[str, str]:
        """Ordered ``{label: value}`` pairs, for a metadata sheet or file.

        Optional fields are emitted only when set, so a header round-trips to
        exactly what was supplied.
        """
        fields = {
            _FIELD_ENTITY: self.entity_identifier,
            _FIELD_SCHEME: self.entity_scheme,
            _FIELD_DATE: self.reference_date.isoformat(),
            _FIELD_MODULE: self.module,
            _FIELD_CURRENCY: self.currency,
        }
        if self.entity_name is not None:
            fields[_FIELD_NAME] = self.entity_name
        if self.consolidation_basis is not None:
            fields[_FIELD_BASIS] = self.consolidation_basis
        return fields

    @classmethod
    def from_fields(cls, fields: Mapping[str, str]) -> ReturnHeader:
        """Rebuild a header from ``as_fields`` output (labels are case-insensitive).

        Raises:
            ValueError: a required field is missing or the date is not ISO.
        """
        folded = {key.strip().lower(): str(value).strip() for key, value in fields.items()}

        def required(label: str) -> str:
            value = folded.get(label.lower())
            if not value:
                raise ValueError(f"Return header is missing {label!r}")
            return value

        def optional(label: str) -> str | None:
            return folded.get(label.lower()) or None

        return cls(
            entity_identifier=required(_FIELD_ENTITY),
            reference_date=date.fromisoformat(required(_FIELD_DATE)[:10]),
            module=required(_FIELD_MODULE),
            currency=optional(_FIELD_CURRENCY) or "GBP",
            entity_scheme=optional(_FIELD_SCHEME) or LEI_SCHEME,
            entity_name=optional(_FIELD_NAME),
            consolidation_basis=optional(_FIELD_BASIS),
        )


# =============================================================================
# The return
# =============================================================================


@dataclass(frozen=True)
class CanonicalReturn:
    """A return: its header and its facts (``FACT_SCHEMA``).

    Build one with ``CanonicalReturn.from_frame``, which normalises a source's
    frame onto the schema. The constructor itself trusts what it is given.
    """

    header: ReturnHeader
    facts: pl.DataFrame
    indicators: Mapping[str, bool] | None = None
    """Filing indicators as declared — ``{code: filed}`` — or ``None`` to have
    every template with a fact reported and no other."""

    @classmethod
    def from_frame(
        cls,
        header: ReturnHeader,
        frame: pl.DataFrame,
        indicators: Mapping[str, bool] | None = None,
    ) -> CanonicalReturn:
        """Normalise ``frame`` onto ``FACT_SCHEMA`` and wrap it with ``header``.

        What is normalised:
        - optional columns a source omitted are added as null;
        - codes read as integers (``10`` from a CSV) are restored to the
          publisher's zero-padded form (``0010``) — a spreadsheet or CSV round
          trip is the usual way a leading zero is lost;
        - blank strings become null, so "empty cell" has one representation;
        - a non-finite number (NaN, +/-Inf) is not a reportable figure and is
          dropped to null;
        - rows carrying neither a value nor a text value are removed: an
          unreported cell is not a fact.

        Columns outside the schema are ignored.

        Raises:
            ValueError: a required column is missing. (A frame without a table
                or a value column is not a fact table; that is a programming
                error in the reader, not a condition in the data.)
        """
        missing = [name for name in REQUIRED_FACT_COLUMNS if name not in frame.columns]
        if missing:
            raise ValueError(
                f"Fact table is missing required column(s) {', '.join(missing)}; "
                f"expected at least {', '.join(REQUIRED_FACT_COLUMNS)}"
            )

        present = [name for name in FACT_SCHEMA.names() if name in frame.columns]
        absent = [name for name in FACT_SCHEMA.names() if name not in frame.columns]
        facts = (
            frame.select(present)
            .with_columns(pl.lit(None, dtype=FACT_SCHEMA[name]).alias(name) for name in absent)
            .with_columns(
                _text(pl.col("table")).alias("table"),
                _code(pl.col("sheet"), frame.schema.get("sheet")).alias("sheet"),
                _text(pl.col("open_key")).alias("open_key"),
                _code(pl.col("row"), frame.schema.get("row")).alias("row"),
                _code(pl.col("column"), frame.schema.get("column")).alias("column"),
                _finite(pl.col("value")).alias("value"),
                _text(pl.col("text_value")).alias("text_value"),
                pl.col("decimals").cast(pl.Int32, strict=False).alias("decimals"),
            )
            .select(FACT_SCHEMA.names())
            .cast(FACT_SCHEMA)
            .filter(pl.col("value").is_not_null() | pl.col("text_value").is_not_null())
        )
        return cls(header=header, facts=facts, indicators=indicators)

    @property
    def tables(self) -> tuple[str, ...]:
        """The table codes the return carries facts for, sorted."""
        return tuple(sorted(self.facts["table"].drop_nulls().unique().to_list()))

    def table_facts(self, table: str) -> pl.DataFrame:
        """The facts of one table."""
        return self.facts.filter(pl.col("table") == table)


# =============================================================================
# Private helpers
# =============================================================================


def _text(expr: pl.Expr) -> pl.Expr:
    """A trimmed string, with blank folded to null."""
    text = expr.cast(pl.String).str.strip_chars()
    return pl.when(text.str.len_chars() > 0).then(text).otherwise(None)


def _code(expr: pl.Expr, dtype: pl.DataType | type[pl.DataType] | None) -> pl.Expr:
    """A row / column / sheet code as the publisher writes it.

    Only a column that arrived as a NUMBER is padded: its leading zeros were
    lost in transit and ``10`` can only have been ``0010``. A column that is
    already text is left exactly as given — an open-row identifier is free
    text, and silently rewriting a filer's code would hide a real mistake from
    the structure check whose job is to report it.
    """
    if dtype is not None and dtype.is_numeric():
        return expr.cast(pl.Int64).cast(pl.String).str.zfill(CODE_WIDTH)
    return _text(expr)


def _finite(expr: pl.Expr) -> pl.Expr:
    """A float, with NaN and infinities dropped to null."""
    number = expr.cast(pl.Float64, strict=False)
    return pl.when(number.is_finite()).then(number).otherwise(None)
