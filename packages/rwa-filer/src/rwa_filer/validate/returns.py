"""
Validate a canonical return — structure first, then the published rules.

Pipeline position:
    CanonicalReturn  ->  validate_return
        ->  taxonomy.resolve_pack(module, reference date)
        ->  structure.check_structure
        ->  index_from_return  ->  checker.evaluate_index
        ->  ReturnValidation

Key responsibilities:
- Be the one call that answers "is this return fit to submit?" for a return in
  canonical form, whatever file or system it came from.
- Present a canonical return to the rule engine as a ``TemplateIndex``. A
  canonical return is already in the publisher's coordinates, so the bindings
  and sheet maps are the identity, built from the taxonomy pack: each table code
  answers to its own frames, and each sheet is keyed by its own published code.
- Keep the two kinds of finding apart in the result — structure (the taxonomy
  rejects it) and rules (the supervisor's arithmetic does not hold) — and say
  plainly whether anything blocks submission.

References:
- BoE XBRL Filing Manual v1.0.1
- Bank of England Banking Taxonomy; BoE banking validation rules
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import polars as pl

from rwa_filer.rules.catalogue import FRAMEWORK_BASEL_3_1
from rwa_filer.taxonomy.pack import resolve_pack
from rwa_filer.validate.checker import evaluate_index, findings_for
from rwa_filer.validate.evaluate import GEOGRAPHY_TOTAL_SHEET
from rwa_filer.validate.index import SINGLE_SHEET, SheetCode, TableBinding, TemplateIndex
from rwa_filer.validate.structure import check_structure, local_name

if TYPE_CHECKING:
    from collections.abc import Sequence

    from rwa_filer.model import CanonicalReturn
    from rwa_filer.rules.catalogue import RuleSet
    from rwa_filer.taxonomy.pack import Table, TaxonomyPack
    from rwa_filer.validate.checker import Finding, ValidationReport

logger = logging.getLogger(__name__)

#: The packaged rule extract each reporting module is validated against.
MODULE_FRAMEWORKS: Final[dict[str, str]] = {
    "PRA001": FRAMEWORK_BASEL_3_1,
}

#: The open-axis member that is the all-geographies total. The engine addresses
#: that sheet by ``GEOGRAPHY_TOTAL_SHEET``; see ``evaluate._parse_filter``.
_GEOGRAPHY_DIMENSION: Final = "eba_dim:CEG"
_GEOGRAPHY_TOTAL_MEMBER: Final = "x1"

_SHEET_MAP_SOURCE: Final = "taxonomy pack (identity)"


# =============================================================================
# Public entry point
# =============================================================================


@dataclass(frozen=True)
class ReturnValidation:
    """Everything validating one return established.

    Attributes:
        pack: The taxonomy the return was read against.
        structure: Structure findings (``STR...``).
        report: The rule engine's per-rule report, or ``None`` when the module
            has no packaged rule set.
        rules: Rule findings (``VAL...``), from ``report``.
    """

    pack: TaxonomyPack
    structure: tuple[Finding, ...]
    report: ValidationReport | None
    rules: tuple[Finding, ...]

    @property
    def findings(self) -> tuple[Finding, ...]:
        """Every finding, structure first."""
        return (*self.structure, *self.rules)

    @property
    def blocking(self) -> tuple[Finding, ...]:
        """The findings that stop the return being submitted."""
        return tuple(finding for finding in self.findings if finding.is_blocking)

    @property
    def is_submittable(self) -> bool:
        """Whether nothing found blocks submission.

        True is evidence the return is well-formed, not a guarantee of
        acceptance: the regulator's own validation on upload is authoritative.
        """
        return not self.blocking


def validate_return(
    ret: CanonicalReturn,
    pack: TaxonomyPack | None = None,
    *,
    ruleset: RuleSet | None = None,
    source_findings: Sequence[Finding] = (),
) -> ReturnValidation:
    """Validate ``ret``: structure against the taxonomy, then the published rules.

    Args:
        ret: The return, in canonical form.
        pack: The taxonomy to read it against. Defaults to the packaged pack in
            force for the return's module on its reference date.
        ruleset: The rules to run. Defaults to the packaged rule set for the
            module; a module with none packaged has only its structure checked.
        source_findings: What reading the return's source found — an XBRL
            instance holding a fact the module does not have, say. They are
            reported first, with the structure findings.

    Returns:
        A ``ReturnValidation``. Never raises for a condition in the data.

    Raises:
        PackNotFoundError: no ``pack`` was given and none is packaged for the
            module and reference date.
    """
    pack = pack or resolve_pack(ret.header.module, ret.header.reference_date)
    structure = (*source_findings, *check_structure(ret, pack))

    framework = ruleset.framework if ruleset else MODULE_FRAMEWORKS.get(pack.info.module.upper())
    if framework is None:
        logger.warning("no packaged rule set for module %s; rules not run", pack.info.module)
        return ReturnValidation(pack=pack, structure=structure, report=None, rules=())

    report = evaluate_index(index_from_return(ret, pack, framework), ruleset)
    return ReturnValidation(
        pack=pack, structure=structure, report=report, rules=tuple(findings_for(report))
    )


def index_from_return(ret: CanonicalReturn, pack: TaxonomyPack, framework: str) -> TemplateIndex:
    """Present a canonical return to the rule engine.

    Each table's facts are pivoted into one frame per sheet — ``row_ref`` plus a
    column per reported column code. Only numeric facts are pivoted: the rules
    are arithmetic, and a text cell is not a figure.

    The bindings and sheet maps are the IDENTITY: the return is already in the
    publisher's coordinates, so table ``T`` answers to its own frames and sheet
    code ``z`` to the sheet keyed ``z``. The identity map is closed by
    construction, so no rule is skipped for a sheet-scope reason.

    Facts in tables the module does not have are left out; ``check_structure``
    reports them.
    """
    frames: dict[str, dict[str, pl.DataFrame]] = {}
    bindings: dict[str, TableBinding] = {}
    sheet_maps: dict[str, dict[str, SheetCode]] = {}

    numeric = ret.facts.filter(pl.col("value").is_not_null())
    for code, table in pack.tables.items():
        per_sheet = bool(table.z_axes)
        fixed = table.fixed_axis
        bindings[code] = TableBinding(code, per_sheet=per_sheet, sheet_map=code if fixed else None)
        if fixed is not None:
            sheet_maps[code] = {
                sheet.code: SheetCode(sheet.code, sheet.label, (sheet.code,), _SHEET_MAP_SOURCE)
                for sheet in fixed.sheets
            }
        part = numeric.filter(pl.col("table") == code)
        if part.is_empty():
            continue
        frames[code] = _table_frames(part, table)
    return TemplateIndex(
        framework=framework, frames=frames, bindings=bindings, sheet_maps=sheet_maps
    )


# =============================================================================
# Private helpers
# =============================================================================


def _table_frames(facts: pl.DataFrame, table: Table) -> dict[str, pl.DataFrame]:
    """One wide frame per sheet key for a table's numeric facts."""
    if not table.z_axes:
        return {SINGLE_SHEET: _pivot(facts)}
    keyed = facts.with_columns(_sheet_key(table).alias("_sheet_key"))
    return {
        str(key): _pivot(part)
        for (key,), part in keyed.sort("_sheet_key").group_by("_sheet_key", maintain_order=True)
        if key is not None
    }


def _sheet_key(table: Table) -> pl.Expr:
    """The engine's sheet key for a fact: the fixed code, else the open member.

    The all-geographies total of a per-country table is keyed by the engine's
    own ``GEOGRAPHY_TOTAL_SHEET``, which is how its geography filter finds it.
    """
    open_axis = table.open_axis
    if table.fixed_axis is not None:
        return pl.col("sheet")
    key = pl.col("open_key").map_elements(local_name, pl.String)
    if open_axis is not None and open_axis.dimension == _GEOGRAPHY_DIMENSION:
        return (
            pl.when(key == _GEOGRAPHY_TOTAL_MEMBER)
            .then(pl.lit(GEOGRAPHY_TOTAL_SHEET))
            .otherwise(key)
        )
    return key


def _pivot(facts: pl.DataFrame) -> pl.DataFrame:
    """Long facts for one sheet -> ``row_ref`` + one Float64 column per column code.

    A duplicated cell keeps its first value here; the duplicate itself is a
    structure finding (``STR005``) and must not also become an arithmetic one.
    """
    return (
        facts.select(pl.col("row").alias("row_ref"), "column", "value")
        .filter(pl.col("row_ref").is_not_null())
        .pivot(on="column", index="row_ref", values="value", aggregate_function="first")
        .sort("row_ref")
    )
