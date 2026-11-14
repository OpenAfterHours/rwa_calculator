"""
The template index — a return's frames, addressable by publisher coordinates.

Pipeline position:
    source of figures  ->  TemplateIndex(frames, bindings, sheet_maps)
    ValidationRule + TemplateIndex  ->  expand_rule  ->  [Coordinate] + [Skip]

Key responsibilities:
- Define the one shape the rule engine reads a return through: ``TemplateIndex``.
  Whoever holds the figures builds it — ``rwa-calc`` from its generated template
  bundles, a file reader from a canonical fact table — and the engine never sees
  where they came from.
- Bind a publisher TABLE code (``C 07.00.a`` / ``OF08.01.01.01``) to the frame
  group that carries it (``TableBinding``), and answer "is this template
  reported at all?".
- Map publisher SHEET (z-axis) codes onto the source's own sheet keys through an
  explicit, caller-supplied table (``SheetCode``). Where a code's meaning could
  not be established the map holds nothing and the rule is skipped: a wrong
  sheet mapping silently produces wrong findings, which is far worse than a skip.
- Expand a rule into the concrete (sheet, row, column) coordinates it must be
  evaluated at, and record — never collapse — every coordinate that could not be
  formed. "Row not reported" is NOT "row reported as zero".

Why the sheet map is the hard part: the supervisory z-axis is a positional index
into the regulation's exposure-class list, while a source may key its sheets by
something else and — in places — on a COARSER partition than the DPM's. A scoped
subset of z-codes is therefore only safe to evaluate when the set is CLOSED
under the mapping — see ``resolve_sheet_codes``. A source that keys its sheets
on the z-codes themselves passes an identity map and closure holds trivially.

This module holds NO sheet map and NO table binding of its own. Those are facts
about one particular source of figures and live with it (for ``rwa-calc``:
``rwa_calc.reporting.filing``).

References:
- CRR Art. 112(1) / Art. 147(2) — the exposure-class lists the z-axes index
- COREP Annex II; PRA PS1/26 Annex II (the templates the coordinates address)
"""

from __future__ import annotations

import itertools
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

import polars as pl

from rwa_filer.rules.catalogue import SCOPE_ALL, SCOPE_LIST, RuleScope

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from rwa_filer.rules.catalogue import ValidationRule

logger = logging.getLogger(__name__)

# =============================================================================
# Skip reasons — every one is a NOT_EVALUATED outcome, never a break
# =============================================================================

SKIP_TABLE_NOT_EMITTED: Final = "table_not_emitted"
SKIP_SHEET_NOT_EMITTED: Final = "sheet_not_emitted"
SKIP_SHEET_INDEX_MAP_UNKNOWN: Final = "sheet_index_map_unknown"
SKIP_SHEET_SCOPE_NOT_CLOSED: Final = "sheet_scope_not_closed"
SKIP_ROW_NOT_EMITTED: Final = "row_not_emitted"
SKIP_COLUMN_NOT_EMITTED: Final = "column_not_emitted"
SKIP_NO_COORDINATES: Final = "no_coordinates"
SKIP_PREREQUISITE_TABLE_ABSENT: Final = "prerequisite_table_absent"

# =============================================================================
# The sheet (z-axis) index map
# =============================================================================


@dataclass(frozen=True)
class SheetCode:
    """One publisher sheet code and what it addresses in the source's sheets.

    Attributes:
        code: The publisher's z-axis id, e.g. ``"0008"``.
        label: The regulatory exposure class the code indexes.
        bundle_keys: The source's sheet keys that carry those exposures. EMPTY
            means the code is understood but has no analogue in the source's
            output (a ``Total`` sheet it does not produce, or a class it does
            not model) — a skip, never a zero. A code ABSENT from the map is one
            whose meaning could not be established; it is reported as
            ``sheet_index_map_unknown``.

            "No analogue" is about the source's MODEL, never about one run: a
            class the source does model names its key here even where a given
            run or regime can never produce the sheet. Both read as
            ``sheet_not_emitted``, but only the declared form says WHY, and the
            empty form additionally claims the code addresses nothing — which
            makes a reported sheet unreachable by every rule scoped to it.

            At most ONE key per code. ``resolve_sheet_codes`` returns every key
            a scoped code addresses and the evaluator sums across them, so a
            second key asserts the publisher's rule against a figure that
            appears on no submitted sheet.
        source: How the entry was established.
    """

    code: str
    label: str
    bundle_keys: tuple[str, ...]
    source: str


# =============================================================================
# Table bindings — publisher table code -> frame group
# =============================================================================


@dataclass(frozen=True)
class TableBinding:
    """Binds one publisher table code to the frame group that carries it.

    ``attribute`` names the entry of ``TemplateIndex.frames`` holding the
    table's frames. Several table codes may name the same one.

    ``sheet_map`` names the entry of ``TemplateIndex.sheet_maps`` that indexes
    the group's sheet dict, or is ``None`` when the dict is keyed by something
    the publisher never addresses positionally.

    ``columns`` restricts the binding to one DPM variant's own columns. Several
    table codes bind to the SAME frame — a single C 09.01 frame carrying the union of
    ``C 09.01.a`` and ``C 09.01.b`` — and without this a rule scoped
    ``columns: (All)`` on one variant would iterate the other variant's columns
    and report breaks against cells it does not govern. ``None`` means "the whole
    frame", which is correct for a code that is the sole binding for its member,
    and is also the recorded fallback where the variants do NOT split by column
    (see ``derive_variant_columns``).
    """

    attribute: str
    per_sheet: bool
    sheet_map: str | None = None
    columns: frozenset[str] | None = None

    def owns_column(self, column: str) -> bool:
        """Whether ``column`` belongs to this variant."""
        return self.columns is None or column in self.columns


# =============================================================================
# The frame index
# =============================================================================

#: Sentinel sheet key for a single-frame (no z-axis) template.
SINGLE_SHEET: Final = "__single__"


@dataclass(frozen=True)
class CellValue:
    """One resolved cell: present with a value, present but null, or absent.

    ``absent`` is emphatically NOT ``0.0``. A row, column or sheet our estate
    never emitted carries no assertion at all; collapsing it to zero manufactures
    a figure and turns a structural gap into an arithmetic break.
    """

    present: bool
    value: float | None

    @property
    def is_null(self) -> bool:
        """Present in the frame but carrying no value."""
        return self.present and self.value is None


ABSENT_CELL: Final = CellValue(present=False, value=None)


@dataclass(frozen=True)
class TemplateIndex:
    """Every reported frame, addressable by publisher table code.

    ``frames`` maps a frame-group name (``TableBinding.attribute``) to
    ``{sheet key: DataFrame}``, using ``SINGLE_SHEET`` for templates with no
    z-axis. Each frame carries a ``row_ref`` column and one column per reported
    column reference. A table code with no entry (or an empty one) was NOT
    reported.

    ``sheet_maps`` holds the named publisher-sheet-code maps the bindings refer
    to (``TableBinding.sheet_map``). They are DATA ABOUT THE SOURCE, supplied by
    whoever builds the index — this package ships none.

    By convention the all-geographies total of a per-country template is keyed
    ``evaluate.GEOGRAPHY_TOTAL_SHEET``.
    """

    framework: str
    frames: Mapping[str, Mapping[str, pl.DataFrame]]
    bindings: Mapping[str, TableBinding] = field(default_factory=dict)
    sheet_maps: Mapping[str, Mapping[str, SheetCode]] = field(default_factory=dict)
    #: Lazily-built ``{row_ref: {column: value}}`` per (attribute, sheet). A rule
    #: estate reads the same handful of frames tens of thousands of times — an
    #: aggregate over an unbound axis touches every row of a template per
    #: coordinate — and a Polars ``filter`` per cell makes that quadratic. The
    #: dict is a read-through cache of frames that never change during a run, so
    #: it cannot drift from ``frames``; it is excluded from equality and repr so
    #: the dataclass still compares by its declared content.
    _cells: dict[tuple[str, str], dict[str, dict[str, float | None]]] = field(
        default_factory=dict, repr=False, compare=False
    )

    def binding(self, table: str) -> TableBinding | None:
        """The binding for a publisher table code, or ``None`` if unbindable."""
        return self.bindings.get(table)

    def is_emitted(self, table: str) -> bool:
        """Whether this run produced any frame for ``table``."""
        binding = self.binding(table)
        return bool(binding and self.frames.get(binding.attribute))

    def sheet_keys(self, table: str) -> tuple[str, ...]:
        """Every sheet key emitted for ``table`` (``(SINGLE_SHEET,)`` if flat)."""
        binding = self.binding(table)
        if binding is None:
            return ()
        return tuple(self.frames.get(binding.attribute, {}))

    def frame(self, table: str, sheet: str) -> pl.DataFrame | None:
        """The DataFrame at ``(table, sheet)``, or ``None`` when not emitted."""
        binding = self.binding(table)
        if binding is None:
            return None
        return self.frames.get(binding.attribute, {}).get(sheet)

    def row_refs(self, table: str, sheet: str) -> tuple[str, ...]:
        """Row references present on a frame, in emitted order."""
        frame = self.frame(table, sheet)
        if frame is None or "row_ref" not in frame.columns:
            return ()
        return tuple(str(value) for value in frame["row_ref"].to_list())

    def column_refs(self, table: str, sheet: str) -> tuple[str, ...]:
        """Numeric column references this table code governs on a frame.

        Restricted to the variant's own columns when the binding carries a set,
        so a ``columns: (All)`` rule iterates the columns of the table it is
        scoped to rather than everything its sibling variants share the frame
        with.
        """
        frame = self.frame(table, sheet)
        if frame is None:
            return ()
        binding = self.binding(table)
        return tuple(
            name
            for name in frame.columns
            if name not in _NON_DATA_COLUMNS and (binding is None or binding.owns_column(name))
        )

    def cell(self, table: str, sheet: str, row: str, column: str) -> CellValue:
        """Read one cell, distinguishing "absent" from "present but null"."""
        binding = self.binding(table)
        if binding is None or not binding.owns_column(column):
            return ABSENT_CELL
        by_row = self._cell_map(binding.attribute, sheet)
        cells = by_row.get(row)
        if cells is None or column not in cells:
            return ABSENT_CELL
        value = cells[column]
        if value is None:
            return CellValue(present=True, value=None)
        return CellValue(present=True, value=value)

    def _cell_map(self, attribute: str, sheet: str) -> dict[str, dict[str, float | None]]:
        """Materialise (once) the ``{row_ref: {column: value}}`` map for a frame.

        Only numeric columns are kept, and a non-numeric cell is stored as
        ``None`` — "present but not a figure" reads the same as "present but
        null", and neither may become a zero.
        """
        key = (attribute, sheet)
        cached = self._cells.get(key)
        if cached is not None:
            return cached

        by_row: dict[str, dict[str, float | None]] = {}
        frame = self.frames.get(attribute, {}).get(sheet)
        if frame is not None and "row_ref" in frame.columns:
            columns = [name for name in frame.columns if name not in _NON_DATA_COLUMNS]
            for record in frame.select("row_ref", *columns).iter_rows(named=True):
                by_row[str(record["row_ref"])] = {name: _as_float(record[name]) for name in columns}
        self._cells[key] = by_row
        return by_row


#: Frame columns that are labels, not reportable cells.
_NON_DATA_COLUMNS: Final[frozenset[str]] = frozenset({"row_ref", "row_name", "row_label", "label"})

#: ``{C 08.01.a, r0070, c0020}`` / ``{t: OF08.01.01.01, r: 0070, c: 0020}`` — a
#: reference whose FIRST part names a table, so its columns are attributable to
#: that table rather than to the rule's home.
#: The table run is greedy and unpadded: its class excludes the "," it stops at,
#: so the scan is deterministic, whereas the lazy form plus a trailing `\s*` left
#: the separating spaces claimable by either and backtracked quadratically on a
#: brace group with no comma. The caller strips the captured name.
_QUALIFIED_REF = re.compile(r"\{\s*(?:t:\s*)?([A-Za-z][A-Za-z0-9. ]*),([^{}]*)\}")
#: A column id in either grammar (``c0020`` / ``c: 0020``).
_COLUMN_ID = re.compile(r"\bc[:\s]*(\d{3,5})\b")


def derive_variant_columns(
    rules: Iterable[ValidationRule], bindings: Mapping[str, TableBinding]
) -> Mapping[str, frozenset[str]]:
    """Derive each DPM variant's own column set FROM THE RULES THEMSELVES.

    Several publisher table codes may bind to one frame group (``C 09.01.a`` and
    ``C 09.01.b`` are column partitions of one CR GB 1 template, and a source
    may carry the union in one frame). A rule scoped ``columns: (All)`` on one
    variant must iterate only that variant's columns; without this it evaluates
    against its sibling's and reports breaks on cells it does not govern.

    The sets are derived, never hand-written: a variant owns every column a rule
    attributes to it explicitly — a reference qualified with the table name, or
    any column reference / column scope on a rule naming that table alone. A
    hand-maintained table would rot at the next taxonomy refresh, exactly as a
    pinned must-run rule-id list would.

    A group is scoped ONLY when its variants' derived sets are non-empty and
    PAIRWISE DISJOINT — the signature of a genuine column partition. Where they
    overlap, the variants are split by something else and a column set is the
    wrong model, so the group is left unscoped. On the two packaged credit-risk
    extracts that correctly scopes ``C 09.01``, ``C 08.01``, ``C 34.01``,
    ``C 34.08``, ``OF08.01``, ``OF02.01`` and ``C34.08.01``, and correctly
    declines the ``C 07.00`` / ``OF07.00`` family, whose ``.c`` / ``.d``
    variants are the memorandum ROWS (0290-0320) over the same column space as
    ``.a``.

    Args:
        rules: The rules to read the attribution from. Pass the ENFORCED rules
            only: a withdrawn rule may reference a retired column, which would
            widen a variant's set and quietly weaken the partition.
        bindings: The literal table map, before any column scoping.

    Returns:
        ``{table code: columns}`` for the codes that could be scoped. A code
        absent from the mapping is deliberately unrestricted.
    """
    attributed = _attributed_columns(rules)
    by_attribute: dict[str, list[str]] = {}
    for table, binding in bindings.items():
        by_attribute.setdefault(binding.attribute, []).append(table)

    scoped: dict[str, frozenset[str]] = {}
    for tables in by_attribute.values():
        if len(tables) < 2:
            continue  # sole binding for its frame: the frame IS that table
        sets = {table: attributed.get(table, frozenset()) for table in tables}
        if not all(sets.values()):
            continue  # a variant we have no column evidence for
        if any(sets[a] & sets[b] for a, b in itertools.combinations(sorted(sets), 2)):
            continue  # not a column partition — see the docstring
        scoped.update(sets)
    return scoped


def _attributed_columns(rules: Iterable[ValidationRule]) -> Mapping[str, frozenset[str]]:
    """Columns each table code is explicitly credited with by ``rules``."""
    collected: dict[str, set[str]] = {}
    for rule in rules:
        expression = rule.expression or ""
        for qualified, body in _QUALIFIED_REF.findall(expression):
            table = qualified.strip()
            if table in rule.tables:
                collected.setdefault(table, set()).update(_COLUMN_ID.findall(body))
        if len(rule.tables) != 1:
            continue  # an unqualified reference on a multi-table rule is ambiguous
        table = rule.tables[0]
        unqualified = _QUALIFIED_REF.sub(" ", expression)
        collected.setdefault(table, set()).update(_COLUMN_ID.findall(unqualified))
        columns = rule.scope_for(table).columns
        if columns.kind == SCOPE_LIST:
            collected[table].update(columns.ids)
    return {table: frozenset(values) for table, values in collected.items()}


def _as_float(value: object) -> float | None:
    """Coerce a cell to a float, or ``None`` when it carries no figure.

    A template cell can legitimately hold a non-numeric label (a PD band such as
    ``"0.75% - 2.50%"`` on the C 08.02 row axis). Such a cell is not a figure, so
    it reads as unreported rather than being forced to a number.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


# =============================================================================
# Rule expansion
# =============================================================================


@dataclass(frozen=True)
class Coordinate:
    """One concrete cell address a rule is evaluated at.

    ``row`` / ``column`` are ``None`` when the rule's formula addresses that axis
    itself (every reference is fully qualified), so there is nothing to iterate.

    ``sheet_is_representative`` marks a sheet the rule does not actually address:
    when every reference names its own sheet, the axis is collapsed to one
    arbitrary emitted sheet so the grid is not multiplied. Such a sheet must not
    be shown in a finding — quoting ``[GB]`` on a cross-table identity that is
    not GB-specific would send a reader to the wrong place.
    """

    table: str
    sheet: str
    row: str | None
    column: str | None
    sheet_is_representative: bool = False

    def describe(self) -> str:
        """Compact human address, e.g. ``C 07.00.a[corporate][r0010][c0090]``."""
        hide_sheet = self.sheet == SINGLE_SHEET or self.sheet_is_representative
        sheet = "" if hide_sheet else f"[{self.sheet}]"
        row = f"[r{self.row}]" if self.row else ""
        column = f"[c{self.column}]" if self.column else ""
        return f"{self.table}{sheet}{row}{column}"


@dataclass(frozen=True)
class SheetResolution:
    """The outcome of mapping a set of publisher sheet codes onto our sheets."""

    sheets: tuple[str, ...]
    skip_reason: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class Expansion:
    """A rule's concrete coordinates, plus why anything was left out."""

    home_table: str | None
    coordinates: tuple[Coordinate, ...]
    skip_reason: str | None = None
    detail: str = ""


def expand_rule(
    rule: ValidationRule,
    index: TemplateIndex,
    *,
    needs_row_axis: bool,
    needs_column_axis: bool,
    needs_sheet_axis: bool = True,
) -> Expansion:
    """Expand a rule into the coordinates it must be evaluated at.

    The publisher's doctrine is that the SCOPED axis is the loop and the formula
    addresses the other one. That generalises to all three axes: an axis is
    iterated when the rule scopes it, or when the formula carries at least one
    reference that does not qualify it (the ``needs_*_axis`` flags, derived from
    the parsed expression). Otherwise the axis collapses to a single value.

    Args:
        rule: The rule to expand.
        index: The generated frames.
        needs_row_axis: The expression has a reference with no explicit row.
        needs_column_axis: The expression has a reference with no explicit column.
        needs_sheet_axis: The expression has a reference that names neither a
            sheet nor a dimensional filter selecting one. When False the sheet
            axis collapses to one representative sheet: every reference resolves
            its own, so iterating would re-evaluate the identical comparison once
            per sheet and count each verdict several times.

    Returns:
        An ``Expansion``; ``skip_reason`` is set (and ``coordinates`` empty) when
        the rule cannot be placed on this run's output at all.
    """
    missing_prerequisite = next(
        (table for table in rule.prerequisites if not index.is_emitted(table)), None
    )
    if missing_prerequisite is not None:
        return Expansion(None, (), SKIP_PREREQUISITE_TABLE_ABSENT, missing_prerequisite)

    home = next((table for table in rule.tables if index.is_emitted(table)), None)
    if home is None:
        return Expansion(None, (), SKIP_TABLE_NOT_EMITTED, ", ".join(rule.tables))

    scope = rule.scope_for(home)
    binding = index.binding(home)
    assert binding is not None  # is_emitted() already proved the binding resolves

    resolution = _resolve_sheet_axis(rule, home, index, binding)
    if resolution.skip_reason is not None:
        return Expansion(home, (), resolution.skip_reason, resolution.detail)
    # Every reference names its own sheet, so the axis carries no information:
    # keep one real key (references still fall back to it) but mark it so no
    # finding quotes a sheet the rule does not address.
    representative = not needs_sheet_axis and len(resolution.sheets) > 1
    if representative:
        resolution = SheetResolution(resolution.sheets[:1])

    coordinates: list[Coordinate] = []
    dropped_rows = scope.rows.kind == SCOPE_LIST
    dropped_columns = scope.columns.kind == SCOPE_LIST
    for sheet in resolution.sheets:
        rows = _axis_values(scope.rows, index.row_refs(home, sheet), iterate=needs_row_axis)
        columns = _axis_values(
            scope.columns, index.column_refs(home, sheet), iterate=needs_column_axis
        )
        dropped_rows = dropped_rows and not rows
        dropped_columns = dropped_columns and not columns
        coordinates.extend(
            Coordinate(home, sheet, row, column, sheet_is_representative=representative)
            for row in rows
            for column in columns
        )

    if coordinates:
        return Expansion(home, tuple(coordinates))
    # Name the axis that emptied the grid: a scoped row / column this estate
    # never emits is a structural gap, and saying which one is the difference
    # between a triageable skip and an opaque one.
    if dropped_rows:
        return Expansion(home, (), SKIP_ROW_NOT_EMITTED, ", ".join(scope.rows.ids))
    if dropped_columns:
        return Expansion(home, (), SKIP_COLUMN_NOT_EMITTED, ", ".join(scope.columns.ids))
    return Expansion(home, (), SKIP_NO_COORDINATES, "scope resolved to no emitted cell")


def resolve_sheet_codes(
    codes: Iterable[str], sheet_map: Mapping[str, SheetCode], emitted: Iterable[str]
) -> SheetResolution:
    """Map publisher sheet codes onto our emitted sheet keys.

    Three ways this refuses, each a skip rather than a break:

    - a code absent from the map -> ``sheet_index_map_unknown``;
    - a code whose class this estate does not produce -> ``sheet_not_emitted``;
    - a code set that is not CLOSED under the mapping -> ``sheet_scope_not_closed``.

    Closure is the load-bearing test. A source's sheets may be a COARSER
    partition than the publisher's z-axis — on the Art. 147(2) IRB axis, one
    ``retail_mortgage`` sheet may answer the DPM's SME (z0013) / non-SME (z0014)
    pair — so a sheet we would evaluate may carry exposures the rule was never
    scoped to. The set is safe only when every code mapping into the selected
    sheets is itself in the requested set. A map with one key per z-code (or an
    identity map over a source keyed on the z-codes themselves) is closed by
    construction.
    """
    requested = tuple(codes)
    unknown = [code for code in requested if code not in sheet_map]
    if unknown:
        return SheetResolution((), SKIP_SHEET_INDEX_MAP_UNKNOWN, ", ".join(sorted(set(unknown))))

    selected: list[str] = []
    for code in requested:
        for key in sheet_map[code].bundle_keys:
            if key not in selected:
                selected.append(key)
    if not selected:
        labels = ", ".join(sheet_map[code].label for code in requested)
        return SheetResolution((), SKIP_SHEET_NOT_EMITTED, labels)

    requested_set = set(requested)
    leaking = sorted(
        code
        for code, entry in sheet_map.items()
        if code not in requested_set and set(entry.bundle_keys) & set(selected)
    )
    if leaking:
        return SheetResolution(
            (),
            SKIP_SHEET_SCOPE_NOT_CLOSED,
            f"our sheet(s) {', '.join(selected)} also carry sheet code(s) {', '.join(leaking)}",
        )

    emitted_set = set(emitted)
    present = tuple(key for key in selected if key in emitted_set)
    if not present:
        return SheetResolution((), SKIP_SHEET_NOT_EMITTED, ", ".join(selected))
    return SheetResolution(present)


# =============================================================================
# Private helpers
# =============================================================================


def _resolve_sheet_axis(
    rule: ValidationRule, home: str, index: TemplateIndex, binding: TableBinding
) -> SheetResolution:
    """Resolve the sheet axis a rule iterates over on its home table."""
    emitted = index.sheet_keys(home)
    if not binding.per_sheet:
        return SheetResolution((SINGLE_SHEET,))

    scope = rule.scope_for(home).sheets
    if scope.kind != SCOPE_LIST:
        # ``(All)`` and an unscoped axis both mean "every sheet". An unscoped
        # sheet axis is NOT "the total sheet": the publisher leaves it blank on
        # rules that hold identically on each sheet, and our estate emits no
        # total sheet at all.
        return SheetResolution(emitted)

    sheet_map = index.sheet_maps.get(binding.sheet_map or "")
    if sheet_map is None:
        return SheetResolution(
            (),
            SKIP_SHEET_INDEX_MAP_UNKNOWN,
            f"{home} sheets are not indexed positionally by the publisher",
        )
    return resolve_sheet_codes(scope.ids, sheet_map, emitted)


def _axis_values(
    scope: RuleScope, emitted: tuple[str, ...], *, iterate: bool
) -> tuple[str | None, ...]:
    """Resolve one axis of the coordinate grid.

    A listed scope keeps ONLY the ids the frame actually emitted — a scoped id we
    never produced is a structural gap, not a zero, and is dropped here so it can
    never contribute to an arithmetic assertion.
    """
    if scope.kind == SCOPE_LIST:
        return tuple(ref for ref in scope.ids if ref in emitted)
    if scope.kind == SCOPE_ALL or iterate:
        return emitted
    return (None,)
