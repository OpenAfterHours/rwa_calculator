"""
Structure checks — is every fact something the taxonomy lets a firm report?

Pipeline position:
    CanonicalReturn + TaxonomyPack  ->  check_structure  ->  list[Finding]
        (then, on a structurally sound return)  ->  the published rules

Key responsibilities:
- Check a return against the taxonomy's own shape BEFORE any arithmetic rule
  runs: every fact must address a table the module has, a cell the regulator
  accepts, a sheet that exists, and carry a value of the metric's type.
- Report what is wrong in the filer's coordinates — table, sheet, row, column —
  rolled up to one finding per kind of problem per table, with a count and the
  first few cells, so 400 facts on a misnamed sheet are one finding, not 400.
- Catch the conditions the regulator's gateway rejects a whole file for and
  that no published arithmetic rule looks at: a figure in a greyed-out cell, the
  same cell reported twice, one data point reported with two different values.

Why this runs first: a published rule that sums a row cannot tell a figure in
the wrong cell from a correct one — it only sees that its own cells are empty,
and is then NOT_EVALUATED. Structure errors would otherwise surface as silence.

Every finding here is Error severity. These are not judgments about the
figures; they are facts the regulator's schema validation rejects on upload.

References:
- BoE XBRL Filing Manual v1.0.1 — no facts outside the reported tables, no
  duplicate or inconsistent facts, one entity identifier, one currency
- Bank of England Banking Taxonomy — hypercubes define the reportable cells
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import TYPE_CHECKING, Final

import polars as pl

from rwa_filer.model import COORDINATE_COLUMNS, LEI_SCHEME
from rwa_filer.rules.catalogue import SEVERITY_ERROR
from rwa_filer.taxonomy.pack import DIMENSION_EXPLICIT
from rwa_filer.validate.checker import Finding

if TYPE_CHECKING:
    from collections.abc import Callable

    from rwa_filer.model import CanonicalReturn
    from rwa_filer.taxonomy.pack import OpenKey, Table, TaxonomyPack

logger = logging.getLogger(__name__)

# =============================================================================
# Finding codes
# =============================================================================

#: The return names a table the module does not have.
FINDING_UNKNOWN_TABLE: Final = "STR001"
#: A fact sits in a cell the taxonomy does not accept (unknown row/column, or a
#: greyed-out cell).
FINDING_CELL_NOT_REPORTABLE: Final = "STR002"
#: A fact names a sheet the table does not have, or omits one it needs.
FINDING_SHEET_INVALID: Final = "STR003"
#: A fact's open-axis member is not one the table accepts, or is missing/unexpected;
#: or a row of an open-row table has a key that is missing or not of the key's type.
FINDING_OPEN_KEY_INVALID: Final = "STR004"
#: The same cell is reported more than once, or two rows of an open-row table
#: carry the same key.
FINDING_DUPLICATE_FACT: Final = "STR005"
#: A fact's value is not of the metric's type.
FINDING_VALUE_TYPE: Final = "STR006"
#: One data point is reported in two cells with different values.
FINDING_INCONSISTENT_DATAPOINT: Final = "STR007"
#: The header is not something the regulator accepts.
FINDING_HEADER_INVALID: Final = "STR008"
#: The return carries no facts at all.
FINDING_EMPTY_RETURN: Final = "STR009"
#: A declared filing indicator the module does not have, or a fact in a template
#: that is not declared as reported.
FINDING_INDICATOR_INVALID: Final = "STR010"

STRUCTURE_REFERENCE: Final = (
    "BoE XBRL Filing Manual; Bank of England Banking Taxonomy (reportable cells)"
)

#: Cells quoted on a finding. The count is always the full number.
MAX_EXAMPLES: Final = 5

#: Working column that identifies one input fact through the joins.
_FACT_INDEX: Final = "_fact"
_KEY_TEXT: Final = "_key_text"

#: Column ``resolve_datapoints`` adds: the fact is a key of an open-row table.
IS_KEY: Final = "is_key"

_LEI = re.compile(r"^[A-Z0-9]{18}[0-9]{2}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_BOOLEANS: Final[frozenset[str]] = frozenset({"true", "false"})


# =============================================================================
# Public entry point
# =============================================================================


def check_structure(ret: CanonicalReturn, pack: TaxonomyPack) -> list[Finding]:
    """Check ``ret`` against ``pack``'s tables, cells and types.

    Returns:
        ``STR001``–``STR010`` findings, header problems first. Empty when the
        return is structurally something the module accepts. Never raises for a
        condition in the data.
    """
    findings = _check_header(ret, pack)
    facts = ret.facts
    if facts.is_empty():
        findings.append(
            _finding(
                FINDING_EMPTY_RETURN,
                "The return carries no facts, so there is nothing to validate or submit.",
                subject=ret.header.module,
                expected="at least one reported fact",
                actual="0 facts",
            )
        )
        return findings

    known = facts.filter(pl.col("table").is_in(list(pack.tables)))
    findings.extend(_unknown_tables(facts, pack))
    findings.extend(_duplicates(known))

    # Each fact is reported under its ROOT cause only. A fact on a sheet the
    # table does not have is also, trivially, in no reportable cell — saying so
    # twice would send a reader to fix a row code that is correct.
    resolved = _resolve_cells(known.with_row_index(_FACT_INDEX), pack)
    bad_sheet = _sheet_offenders(resolved, pack)
    bad_key = _open_key_offenders(resolved, pack)
    misplaced = pl.concat([bad_sheet, bad_key], how="vertical")[_FACT_INDEX].to_list()
    findings.extend(_sheet_findings(bad_sheet, pack))
    findings.extend(_open_key_findings(bad_key, pack))
    placed = resolved.filter(~pl.col(_FACT_INDEX).is_in(misplaced))
    findings.extend(_cell_findings(placed))
    findings.extend(_row_key_findings(placed, pack))
    findings.extend(_type_findings(resolved, pack))
    findings.extend(_inconsistent_datapoints(resolved, pack))
    findings.extend(_indicator_findings(ret, known, pack))
    logger.info(
        "structure check (%s %s): %d facts, %d finding(s)",
        pack.info.module,
        pack.info.version,
        facts.height,
        len(findings),
    )
    return findings


def resolve_datapoints(ret: CanonicalReturn, pack: TaxonomyPack) -> pl.DataFrame:
    """The return's facts with the data point each one maps to.

    Adds two columns to the fact table. ``datapoint`` is the index of the data
    point the cell reports, null where the cell is not reportable. ``is_key``
    marks a fact in a key column of an open-row table: it reports no data point
    of its own — it is the member the row's other facts are reported under.
    The XBRL writer and the coverage ratchets both read this.
    """
    known = ret.facts.filter(pl.col("table").is_in(list(pack.tables)))
    return _resolve_cells(known, pack).select(*ret.facts.columns, "datapoint", IS_KEY)


def filing_indicators(ret: CanonicalReturn, pack: TaxonomyPack) -> dict[str, bool]:
    """Which templates the return reports: ``{filing indicator code: filed}``.

    As declared on the return where it declares them. Otherwise every template
    with a fact is reported and no other is mentioned — a template the return
    says nothing about is "unknown" to the regulator, not zero.
    """
    if ret.indicators is not None:
        return dict(sorted(ret.indicators.items()))
    return dict.fromkeys(
        sorted(
            {pack.tables[table].filing_indicator for table in ret.tables if table in pack.tables}
        ),
        True,
    )


def key_text() -> pl.Expr:
    """A key fact's value as the text it is written as.

    A key may arrive as text or — an obligor-grade number, say — as a number;
    a whole number is written without a decimal point.
    """
    whole = pl.col("value").is_not_null() & (pl.col("value") == pl.col("value").round(0))
    return (
        pl.when(pl.col("text_value").is_not_null())
        .then(pl.col("text_value").str.strip_chars())
        .when(whole)
        .then(pl.col("value").cast(pl.Int64, strict=False).cast(pl.String))
        .otherwise(pl.col("value").cast(pl.String))
    )


def is_valid_lei(identifier: str) -> bool:
    """Whether ``identifier`` is a well-formed LEI with correct check digits.

    ISO 17442: 18 alphanumerics then two check digits, valid when the whole
    string, letters mapped to 10..35, is congruent to 1 modulo 97 (ISO 7064).
    """
    if not _LEI.match(identifier):
        return False
    return int("".join(str(int(char, 36)) for char in identifier)) % 97 == 1


def local_name(qname: str) -> str:
    """The part of a QName after its prefix (``eba_GA:GB`` -> ``GB``)."""
    return qname.rsplit(":", 1)[-1]


# =============================================================================
# Private helpers — resolution
# =============================================================================


def _resolve_cells(facts: pl.DataFrame, pack: TaxonomyPack) -> pl.DataFrame:
    """Join facts to the pack's reportable cells.

    A closed-row table matches on (table, row, column, sheet); an open-row
    table has no published row code, so its facts match on (table, column,
    sheet) and keep their own row identifier. ``sheet`` is null on both sides
    for a table with no fixed sheet axis, so the join treats nulls as equal.

    A fact in a KEY column of an open-row table is marked ``is_key`` and has no
    data point: the key is the dimension member the row is reported under.
    """
    open_tables = [code for code, table in pack.tables.items() if table.open_rows]
    cells = pack.cells.select("table", "row", "column", "sheet", "datapoint")
    keys = pl.DataFrame(
        [(code, key, True) for code in open_tables for key in pack.tables[code].key_codes],
        schema={"table": pl.String, "column": pl.String, IS_KEY: pl.Boolean},
        orient="row",
    )

    closed = (
        facts.filter(~pl.col("table").is_in(open_tables))
        .join(cells, on=["table", "row", "column", "sheet"], how="left", nulls_equal=True)
        .with_columns(pl.lit(False).alias(IS_KEY))
    )
    opened = (
        facts.filter(pl.col("table").is_in(open_tables))
        .join(cells.drop("row"), on=["table", "column", "sheet"], how="left", nulls_equal=True)
        .join(keys, on=["table", "column"], how="left")
        .with_columns(pl.col(IS_KEY).fill_null(False))
    )
    return pl.concat([closed, opened.select(closed.columns)], how="vertical")


# =============================================================================
# Private helpers — the checks
# =============================================================================


def _check_header(ret: CanonicalReturn, pack: TaxonomyPack) -> list[Finding]:
    """Header problems the regulator rejects a file for."""
    header = ret.header
    findings: list[Finding] = []
    if header.module.upper() != pack.info.module.upper():
        findings.append(
            _finding(
                FINDING_HEADER_INVALID,
                f"The return is for module {header.module!r} but is being checked against "
                f"the {pack.info.module} taxonomy pack.",
                subject="module",
                expected=pack.info.module,
                actual=header.module,
            )
        )
    if not pack.info.applies_to(header.reference_date):
        findings.append(
            _finding(
                FINDING_HEADER_INVALID,
                f"Reference date {header.reference_date.isoformat()} is outside the validity "
                f"of taxonomy {pack.info.version} (from {pack.info.valid_from.isoformat()}).",
                subject="reference_date",
                expected=f"on or after {pack.info.valid_from.isoformat()}",
                actual=header.reference_date.isoformat(),
            )
        )
    if header.entity_scheme == LEI_SCHEME and not is_valid_lei(header.entity_identifier):
        findings.append(
            _finding(
                FINDING_HEADER_INVALID,
                f"Entity identifier {header.entity_identifier!r} is not a valid LEI "
                "(20 characters, ISO 17442 check digits).",
                subject="entity_identifier",
                expected="a valid ISO 17442 LEI",
                actual=header.entity_identifier,
            )
        )
    if not _CURRENCY.match(header.currency):
        findings.append(
            _finding(
                FINDING_HEADER_INVALID,
                f"Reporting currency {header.currency!r} is not an ISO 4217 code.",
                subject="currency",
                expected="a three-letter ISO 4217 code",
                actual=header.currency,
            )
        )
    return findings


def _unknown_tables(facts: pl.DataFrame, pack: TaxonomyPack) -> list[Finding]:
    counts = (
        facts.filter(~pl.col("table").is_in(list(pack.tables)) | pl.col("table").is_null())
        .group_by("table")
        .len()
        .sort("table")
    )
    return [
        _finding(
            FINDING_UNKNOWN_TABLE,
            f"Table {table!r} is not part of module {pack.info.module} "
            f"(taxonomy {pack.info.version}); {count} fact(s) address it.",
            subject=str(table),
            expected=f"a {pack.info.module} table code",
            actual=f"{count} fact(s)",
        )
        for table, count in counts.iter_rows()
    ]


def _duplicates(facts: pl.DataFrame) -> list[Finding]:
    duplicated = (
        facts.group_by(COORDINATE_COLUMNS)
        .len()
        .filter(pl.col("len") > 1)
        .sort(COORDINATE_COLUMNS, nulls_last=False)
    )
    return _roll_up(
        duplicated,
        FINDING_DUPLICATE_FACT,
        lambda table, count: (
            f"{count} cell(s) of {table} are reported more than once. A duplicate fact "
            "rejects the file even when the values agree."
        ),
        expected="each cell reported once",
    )


def _sheet_offenders(resolved: pl.DataFrame, pack: TaxonomyPack) -> pl.DataFrame:
    """Facts naming a sheet the table does not have, or omitting one it needs."""
    rows: list[pl.DataFrame] = []
    for code, table in pack.tables.items():
        part = resolved.filter(pl.col("table") == code)
        if part.is_empty():
            continue
        valid = table.sheet_codes
        bad = (
            part.filter(pl.col("sheet").is_null() | ~pl.col("sheet").is_in(valid))
            if valid
            else part.filter(pl.col("sheet").is_not_null())
        )
        rows.append(bad)
    return pl.concat(rows, how="vertical") if rows else resolved.clear()


def _sheet_findings(offending: pl.DataFrame, pack: TaxonomyPack) -> list[Finding]:
    return _roll_up(
        offending,
        FINDING_SHEET_INVALID,
        lambda table, count: (
            f"{count} fact(s) of {table} name a sheet the table does not have: "
            f"{_sheet_expectation(pack.tables[table])}."
        ),
        expected="a published sheet code",
    )


def _sheet_expectation(table: Table) -> str:
    codes = table.sheet_codes
    if not codes:
        return "the table has no sheet axis, so `sheet` must be empty"
    return f"`sheet` must be one of {', '.join(codes)}"


def _open_key_offenders(resolved: pl.DataFrame, pack: TaxonomyPack) -> pl.DataFrame:
    """Facts whose open-axis member the table does not accept, is missing or unexpected."""
    rows: list[pl.DataFrame] = []
    for code, table in pack.tables.items():
        part = resolved.filter(pl.col("table") == code)
        if part.is_empty():
            continue
        axis = table.open_axis
        if axis is None:
            rows.append(part.filter(pl.col("open_key").is_not_null()))
            continue
        accepted = {local_name(member) for member in axis.members} | set(axis.members)
        missing = pl.col("open_key").is_null() & pl.lit(not axis.default_allowed)
        rows.append(part.filter(missing | ~pl.col("open_key").is_in(sorted(accepted))))
    return pl.concat(rows, how="vertical") if rows else resolved.clear()


def _open_key_findings(offending: pl.DataFrame, pack: TaxonomyPack) -> list[Finding]:
    return _roll_up(
        offending,
        FINDING_OPEN_KEY_INVALID,
        lambda table, count: (
            f"{count} fact(s) of {table} carry an `open_key` the table does not accept: "
            f"{_open_key_expectation(pack.tables[table])}."
        ),
        expected="an accepted open-axis member",
    )


def _open_key_expectation(table: Table) -> str:
    axis = table.open_axis
    if axis is None:
        return "the table has no open sheet axis, so `open_key` must be empty"
    return (
        f"`open_key` must be a member of {axis.dimension} "
        f"({len(axis.members)} accepted, e.g. {', '.join(local_name(m) for m in axis.members[:3])})"
    )


def _cell_findings(resolved: pl.DataFrame) -> list[Finding]:
    """A fact, on a valid sheet, in a cell the taxonomy does not accept."""
    offending = resolved.filter(pl.col("datapoint").is_null() & ~pl.col(IS_KEY))
    return _roll_up(
        offending,
        FINDING_CELL_NOT_REPORTABLE,
        lambda table, count: (
            f"{count} fact(s) of {table} sit in a cell the taxonomy does not accept "
            "(an unknown row or column code, or a greyed-out cell)."
        ),
        expected="a reportable cell",
    )


def _row_key_findings(resolved: pl.DataFrame, pack: TaxonomyPack) -> list[Finding]:
    """Open-row tables: every row has each key, of the key's type, and no key repeats.

    A row's key is what its facts are reported under — an obligor grade, a
    counterparty. A row with a figure and no key has nowhere to be written; a
    key of the wrong type is not a member the dimension accepts; and two rows
    with the same key are the same facts reported twice.
    """
    row_id = ["table", "sheet", "open_key", "row"]
    unkeyed: list[pl.DataFrame] = []
    invalid: list[pl.DataFrame] = []
    repeated: list[pl.DataFrame] = []
    for code, table in pack.tables.items():
        if not table.open_rows:
            continue
        part = resolved.filter(pl.col("table") == code)
        if part.is_empty():
            continue
        keys = part.filter(pl.col(IS_KEY)).with_columns(key_text().alias(_KEY_TEXT))
        data = part.filter(~pl.col(IS_KEY))
        for key in table.open_keys:
            given = keys.filter(pl.col("column") == key.code)
            invalid.append(given.filter(~_key_is_valid(key)).drop(_KEY_TEXT))
            unkeyed.append(
                data.join(given.select(row_id).unique(), on=row_id, how="anti", nulls_equal=True)
            )
        signature = (
            keys.sort("column")
            .group_by(row_id, maintain_order=True)
            .agg(pl.col(_KEY_TEXT).str.join("\x1f").alias(_KEY_TEXT), pl.len().alias("keys"))
            .filter(pl.col("keys") == len(table.open_keys))
        )
        clashing = signature.filter(
            pl.len().over("table", "sheet", "open_key", _KEY_TEXT) > 1
        ).select(row_id)
        repeated.append(
            keys.drop(_KEY_TEXT).join(clashing, on=row_id, how="inner", nulls_equal=True)
        )

    def gather(frames: list[pl.DataFrame]) -> pl.DataFrame:
        return pl.concat(frames, how="vertical") if frames else resolved.clear()

    return [
        *_roll_up(
            gather(unkeyed),
            FINDING_OPEN_KEY_INVALID,
            lambda table, count: (
                f"{count} fact(s) of {table} sit in a row with no key. Every row of this "
                f"table is identified by {_key_expectation(pack.tables[table])}."
            ),
            expected="a value in every key column of the row",
        ),
        *_roll_up(
            gather(invalid),
            FINDING_OPEN_KEY_INVALID,
            lambda table, count: (
                f"{count} row key(s) of {table} are not of the key's type: "
                f"{_key_expectation(pack.tables[table])}."
            ),
            expected="a key of the key column's type",
        ),
        *_roll_up(
            gather(repeated),
            FINDING_DUPLICATE_FACT,
            lambda table, count: (
                f"{count} row key(s) of {table} repeat a key another row of the same sheet "
                "carries. Two rows with one key are the same facts reported twice."
            ),
            expected="a key that is unique within the table and sheet",
        ),
    ]


def _key_is_valid(key: OpenKey) -> pl.Expr:
    """Whether a key fact's text (``_KEY_TEXT``) is acceptable for ``key``."""
    text = pl.col(_KEY_TEXT)
    present = text.is_not_null() & (text.str.len_chars() > 0)
    if key.kind == DIMENSION_EXPLICIT:
        if not key.members:
            return present
        accepted = sorted({local_name(member) for member in key.members} | set(key.members))
        return present & text.is_in(accepted)
    if key.typed_type == "integer":
        return present & text.str.contains(r"^-?[0-9]+$")
    if key.typed_type == "date":
        return present & text.map_elements(_is_iso_date, pl.Boolean)
    return present


def _key_expectation(table: Table) -> str:
    parts = []
    for key in table.open_keys:
        if key.kind == DIMENSION_EXPLICIT:
            kind = "a member of " + key.dimension
        else:
            kind = {"integer": "a whole number", "date": "an ISO date"}.get(
                key.typed_type or "", "text"
            )
        parts.append(f"column {key.code} ({key.label}: {kind})")
    return " and ".join(parts)


def _type_findings(resolved: pl.DataFrame, pack: TaxonomyPack) -> list[Finding]:
    """A value that is not of its metric's type."""
    mapped = resolved.filter(pl.col("datapoint").is_not_null())
    if mapped.is_empty():
        return []
    types = pl.DataFrame(
        {
            "datapoint": list(range(len(pack.datapoints))),
            "data_type": [
                pack.metrics[point.metric].data_type if point.metric in pack.metrics else "unknown"
                for point in pack.datapoints
            ],
        },
        schema={"datapoint": pl.UInt32, "data_type": pl.String},
    )
    typed = mapped.join(types, on="datapoint", how="left")
    numeric = pl.col("data_type").is_in(["monetary", "percentage", "integer", "decimal"])
    text = pl.col("text_value")
    wrong = (
        (numeric & pl.col("value").is_null())
        | (~numeric & text.is_null())
        | (
            (pl.col("data_type") == "integer")
            & pl.col("value").is_not_null()
            & (pl.col("value") != pl.col("value").round(0))
        )
        | ((pl.col("data_type") == "boolean") & ~text.str.to_lowercase().is_in(sorted(_BOOLEANS)))
        | ((pl.col("data_type") == "date") & ~text.map_elements(_is_iso_date, pl.Boolean))
    )
    return _roll_up(
        typed.filter(wrong),
        FINDING_VALUE_TYPE,
        lambda table, count: (
            f"{count} fact(s) of {table} carry a value that is not of the cell's type "
            "(a number where text is expected, text where a number is expected, a "
            "non-integer count, or a malformed boolean or date)."
        ),
        expected="a value of the metric's data type",
    )


def _inconsistent_datapoints(resolved: pl.DataFrame, pack: TaxonomyPack) -> list[Finding]:
    """One data point reported in two cells with different values.

    Some figures appear in more than one table. They are ONE fact in the
    submission, so two different values for it cannot both be filed.

    Open-row tables are left out: every row of one maps to the same template
    cell, and what tells the rows apart is their key — they are different
    facts, not one fact reported twice.
    """
    open_tables = [code for code, table in pack.tables.items() if table.open_rows]
    mapped = resolved.filter(
        pl.col("datapoint").is_not_null() & ~pl.col("table").is_in(open_tables)
    )
    clashing = (
        mapped.group_by("datapoint", "open_key")
        .agg(
            pl.col("value").n_unique().alias("values"),
            pl.col("text_value").n_unique().alias("texts"),
            pl.len().alias("cells"),
        )
        .filter((pl.col("cells") > 1) & ((pl.col("values") > 1) | (pl.col("texts") > 1)))
        .select("datapoint", "open_key")
    )
    offending = mapped.join(clashing, on=["datapoint", "open_key"], how="inner", nulls_equal=True)
    return _roll_up(
        offending,
        FINDING_INCONSISTENT_DATAPOINT,
        lambda table, count: (
            f"{count} fact(s) of {table} report a data point that another cell reports with "
            "a different value. The two cells are one fact in the submission."
        ),
        expected="one value per data point",
    )


def _indicator_findings(
    ret: CanonicalReturn, known: pl.DataFrame, pack: TaxonomyPack
) -> list[Finding]:
    """Declared filing indicators the module lacks; facts in a template not reported.

    Only a return that DECLARES its indicators can get this wrong. A fact in a
    template that is not declared as reported is rejected on upload (Filing
    Manual rule 1.7.1): the regulator cannot tell whether the figure is meant.
    """
    if ret.indicators is None:
        return []
    findings: list[Finding] = []
    unknown = sorted(set(ret.indicators) - set(pack.filing_indicators))
    if unknown:
        findings.append(
            _finding(
                FINDING_INDICATOR_INVALID,
                f"{len(unknown)} declared filing indicator(s) are not templates of "
                f"{pack.info.module}: {', '.join(unknown[:MAX_EXAMPLES])}.",
                subject=pack.info.module,
                expected="filing indicators of the module",
                actual=", ".join(unknown[:MAX_EXAMPLES]),
            )
        )
    reported = {code for code, filed in ret.indicators.items() if filed}
    silent = [code for code, table in pack.tables.items() if table.filing_indicator not in reported]
    findings.extend(
        _roll_up(
            known.filter(pl.col("table").is_in(silent)),
            FINDING_INDICATOR_INVALID,
            lambda table, count: (
                f"{count} fact(s) of {table} are in a template the return does not declare as "
                f"reported (filing indicator {pack.tables[table].filing_indicator})."
            ),
            expected="a positive filing indicator for every template with a fact",
        )
    )
    return findings


# =============================================================================
# Private helpers — reporting
# =============================================================================


def _is_iso_date(text: str | None) -> bool:
    if text is None:
        return False
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def _roll_up(
    offending: pl.DataFrame,
    code: str,
    describe: Callable[[str, int], str],
    *,
    expected: str,
) -> list[Finding]:
    """One finding per table for ``offending`` facts, with the first few cells."""
    if offending.is_empty():
        return []
    findings: list[Finding] = []
    for (table,), part in offending.sort(COORDINATE_COLUMNS, nulls_last=False).group_by(
        "table", maintain_order=True
    ):
        examples = [_address(row) for row in part.head(MAX_EXAMPLES).iter_rows(named=True)]
        more = "" if part.height <= MAX_EXAMPLES else f" (first {MAX_EXAMPLES} of {part.height})"
        findings.append(
            _finding(
                code,
                f"{describe(str(table), part.height)} At {', '.join(examples)}{more}.",
                subject=str(table),
                expected=expected,
                actual=f"{part.height} fact(s)",
            )
        )
    return findings


def _address(row: dict[str, object]) -> str:
    """A fact's address, e.g. ``OF07.00.01.01[z0008][r0010][c0090]``."""
    sheet = f"[z{row['sheet']}]" if row.get("sheet") else ""
    key = f"[{row['open_key']}]" if row.get("open_key") else ""
    return f"{row['table']}{sheet}{key}[r{row['row']}][c{row['column']}]"


def _finding(code: str, message: str, *, subject: str, expected: str, actual: str) -> Finding:
    return Finding(
        code=code,
        severity=SEVERITY_ERROR,
        message=message,
        reference=STRUCTURE_REFERENCE,
        subject=subject,
        expected=expected,
        actual=actual,
    )
