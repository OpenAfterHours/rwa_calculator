"""Unit tests for the legacy reporting-ledger projection.

Covers the identity round-trip on BOTH mapping routes (raw amounts the generator
derives from, and the derived-carrier override) under both frameworks, the
null-never-zero discipline, the sealed-target rule, the PD band allocation under
the two frameworks' different row scales, the coverage / reachability report
including C 08.03's fatal row axis, and backwards compatibility of the grammar.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from rwa_calc.analysis.legacy_ledger import (
    LEDGER_TEMPLATE_IDS,
    LEDGER_VOCABULARY,
    MULTI_TARGET_COMPONENTS,
    PROJECTABLE_LEDGER_COLUMNS,
    TEMPLATE_POPULATION_LABELS,
    LegacyLedgerSource,
    ledger_coverage,
    project_legacy_ledger,
)
from rwa_calc.analysis.recon_registry import (
    LEDGER_CARRIERS,
    RECONCILABLE_COMPONENTS,
    CarrierMapping,
    ComponentMapping,
    LegacyColumnMapping,
)
from rwa_calc.api.reconciliation import (
    LegacyOutputLoader,
    ReconciliationSettings,
    dump_reconciliation_config,
    loads_reconciliation_config,
)
from rwa_calc.contracts.edges import AGGREGATOR_EXIT_EDGE
from rwa_calc.data.schemas import VALID_PROTECTION_TYPES
from rwa_calc.domain.enums import ApproachType, ExposureClass
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.kernel.columns import _CREDIT_BS_TYPES

if TYPE_CHECKING:
    from pathlib import Path

    from rwa_calc.reporting.metadata import ResultsSource

FRAMEWORKS = ("CRR", "BASEL_3_1")
TEMPLATES = ("c07_00", "c08_01", "c08_03")

# =============================================================================
# The reference portfolio
# =============================================================================
#
# An our-side results frame RESTRICTED TO THE PROJECTABLE LEDGER VOCABULARY —
# the columns a component or a carrier can target. That restriction is what makes
# the identity test meaningful rather than tautological: the legacy file below
# carries the same portfolio under the firm's own column names, in the firm's own
# units (percentages, thousands, "CORP"/"AIRB"/"TERM LOAN"/"Y" labels), so the
# projection has a real rename / scale / unit / label-canonicalisation job to do,
# and the assertion is that the two frames generate the SAME templates.
#
# Two shapes, because there are two mapping ROUTES to the gross-exposure columns:
#   "raw"     — drawn / interest / undrawn / nominal + exposure_type, with
#               ensure_gross_side_carriers deriving the per-side gross (default).
#   "derived" — reporting_gross_on_bs / _off_bs mapped directly (the override).
# They must agree with each other as well as with their projections.

_COMMON_SCHEMA: dict[str, pl.DataType] = {
    "exposure_reference": pl.String(),
    "counterparty_reference": pl.String(),
    "reporting_class_origin": pl.String(),
    "reporting_approach_origin": pl.String(),
    "exposure_type": pl.String(),
    "is_defaulted": pl.Boolean(),
    "protection_type": pl.String(),
    "ccf": pl.Float64(),
    "ead_final": pl.Float64(),
    "risk_weight": pl.Float64(),
    "rwa_final": pl.Float64(),
    "rwa_pre_factor": pl.Float64(),
    "pd": pl.Float64(),
    "pd_floored": pl.Float64(),
    "lgd_floored": pl.Float64(),
    "irb_maturity_m": pl.Float64(),
    "expected_loss": pl.Float64(),
    "provision_deducted": pl.Float64(),
    "provision_allocated": pl.Float64(),
    "collateral_adjusted_value": pl.Float64(),
    "guaranteed_portion": pl.Float64(),
    "guarantee_rwa_benefit": pl.Float64(),
    "supporting_factor": pl.Float64(),
    "external_cqs": pl.Float64(),
}
_RAW_SCHEMA: dict[str, pl.DataType] = {
    "drawn_amount": pl.Float64(),
    "interest": pl.Float64(),
    "undrawn_amount": pl.Float64(),
    "nominal_amount": pl.Float64(),
}
_DERIVED_SCHEMA: dict[str, pl.DataType] = {
    "reporting_gross_on_bs": pl.Float64(),
    "reporting_gross_off_bs": pl.Float64(),
}

_COMMON_ROWS: dict[str, list[object]] = {
    "exposure_reference": ["SA1", "SA2", "IRB1", "IRB2", "IRB3", "SA3", "SA4"],
    # IRB1/IRB2 differ only by CASE, which is what makes the C 08.01 col 0300
    # distinct-obligor count sensitive to a casefold of the carrier.
    "counterparty_reference": ["O1", "O1", "O2", "o2", "O4", "O5", "O6"],
    "reporting_class_origin": [
        "corporate",
        "retail_other",
        "corporate",
        "corporate",
        "institution",
        "corporate",
        "corporate",
    ],
    "reporting_approach_origin": [
        "standardised",
        "standardised",
        "advanced_irb",
        "advanced_irb",
        "foundation_irb",
        "standardised",
        "standardised",
    ],
    "exposure_type": [
        "loan",
        "facility_undrawn",
        "loan",
        "facility_undrawn",
        "loan",
        "loan",
        "loan",
    ],
    "is_defaulted": [False, False, False, True, False, False, False],
    "protection_type": [None, None, "guarantee", None, None, "guarantee", "credit_derivative"],
    "ccf": [0.0, 0.5, 0.0, 0.2, 0.0, 0.0, 0.0],
    "ead_final": [
        1_000_000.0,
        250_000.0,
        4_000_000.0,
        160_000.0,
        2_500_000.0,
        2_000_000.0,
        1_500_000.0,
    ],
    "risk_weight": [1.0, 0.75, 0.6, 1.5, 0.2, 1.0, 1.0],
    "rwa_final": [
        1_000_000.0,
        187_500.0,
        2_400_000.0,
        240_000.0,
        500_000.0,
        2_000_000.0,
        1_500_000.0,
    ],
    "rwa_pre_factor": [
        1_000_000.0,
        250_000.0,
        2_400_000.0,
        240_000.0,
        500_000.0,
        2_000_000.0,
        1_500_000.0,
    ],
    "pd": [None, None, 0.0035, 1.0, 0.0003, None, None],
    "pd_floored": [None, None, 0.0035, 1.0, 0.0003, None, None],
    "lgd_floored": [None, None, 0.45, 0.45, 0.45, None, None],
    "irb_maturity_m": [None, None, 2.5, 2.5, 1.0, None, None],
    "expected_loss": [None, None, 6_300.0, 72_000.0, 1_125.0, None, None],
    "provision_deducted": [1_500.0, 0.0, 3_000.0, 50_000.0, 0.0, 0.0, 0.0],
    "provision_allocated": [1_500.0, 0.0, 3_000.0, 50_000.0, 0.0, 0.0, 0.0],
    "collateral_adjusted_value": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    "guaranteed_portion": [0.0, 0.0, 500_000.0, 0.0, 0.0, 400_000.0, 300_000.0],
    "guarantee_rwa_benefit": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    "supporting_factor": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
    "external_cqs": [3.0, 4.0, None, None, 2.0, 3.0, 3.0],
}
_RAW_ROWS: dict[str, list[object]] = {
    "drawn_amount": [
        1_000_000.0,
        0.0,
        4_000_000.0,
        0.0,
        2_500_000.0,
        2_000_000.0,
        1_500_000.0,
    ],
    "interest": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    "undrawn_amount": [0.0, 500_000.0, 0.0, 800_000.0, 0.0, 0.0, 0.0],
    "nominal_amount": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
}
# What ensure_gross_side_carriers derives from _RAW_ROWS given the exposure types
# above: a loan's off-side is a true 0.0, a facility_undrawn's is its undrawn.
_DERIVED_ROWS: dict[str, list[object]] = {
    "reporting_gross_on_bs": [
        1_000_000.0,
        0.0,
        4_000_000.0,
        0.0,
        2_500_000.0,
        2_000_000.0,
        1_500_000.0,
    ],
    "reporting_gross_off_bs": [0.0, 500_000.0, 0.0, 800_000.0, 0.0, 0.0, 0.0],
}

# The same portfolio as the firm's own extract: their column names, their units.
_LEGACY_ROWS: dict[str, list[object]] = {
    "Loan Ref": ["SA1", "SA2", "IRB1", "IRB2", "IRB3", "SA3", "SA4"],
    "Obligor Ref": ["O1", "O1", "O2", "o2", "O4", "O5", "O6"],
    "Asset Class": ["CORP", "RETAIL", "CORP", "CORP", "INST", "CORP", "CORP"],
    "Approach": ["SA", "SA", "AIRB", "AIRB", "FIRB", "SA", "SA"],
    "Product": [
        "TERM LOAN",
        "RCF",
        "TERM LOAN",
        "RCF",
        "TERM LOAN",
        "TERM LOAN",
        "TERM LOAN",
    ],
    "Default Flag": ["N", "N", "N", "Y", "N", "N", "N"],
    "Protection": [None, None, "GTEE", None, None, "GTEE", "CDS"],
    "Drawn 000": [1_000.0, 0.0, 4_000.0, 0.0, 2_500.0, 2_000.0, 1_500.0],
    "Accrued 000": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    "Undrawn 000": [0.0, 500.0, 0.0, 800.0, 0.0, 0.0, 0.0],
    "Nominal 000": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    "Gross On BS 000": [1_000.0, 0.0, 4_000.0, 0.0, 2_500.0, 2_000.0, 1_500.0],
    "Gross Off BS 000": [0.0, 500.0, 0.0, 800.0, 0.0, 0.0, 0.0],
    "CCF Pct": [0.0, 50.0, 0.0, 20.0, 0.0, 0.0, 0.0],
    "EAD 000": [1_000.0, 250.0, 4_000.0, 160.0, 2_500.0, 2_000.0, 1_500.0],
    "RW Pct": [100.0, 75.0, 60.0, 150.0, 20.0, 100.0, 100.0],
    "RWA 000": [1_000.0, 187.5, 2_400.0, 240.0, 500.0, 2_000.0, 1_500.0],
    "RWA Pre SF 000": [1_000.0, 250.0, 2_400.0, 240.0, 500.0, 2_000.0, 1_500.0],
    "PD Pct": [None, None, 0.35, 100.0, 0.03, None, None],
    "LGD Pct": [None, None, 45.0, 45.0, 45.0, None, None],
    "Maturity Yrs": [None, None, 2.5, 2.5, 1.0, None, None],
    "EL 000": [None, None, 6.3, 72.0, 1.125, None, None],
    "Provisions": [1_500.0, 0.0, 3_000.0, 50_000.0, 0.0, 0.0, 0.0],
    "Collateral": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    "Guaranteed 000": [0.0, 0.0, 500.0, 0.0, 0.0, 400.0, 300.0],
    "Guarantee Benefit": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    "Supporting Factor": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
    "CQS": [3.0, 4.0, None, None, 2.0, 3.0, 3.0],
}

_CLASS_MAP = {"CORP": "corporate", "RETAIL": "retail_other", "INST": "institution"}
_APPROACH_MAP = {"SA": "standardised", "AIRB": "advanced_irb", "FIRB": "foundation_irb"}

# Everything except the two gross routes, which the fixtures below add.
_BASE_COMPONENTS: dict[str, ComponentMapping] = {
    "exposure_class": ComponentMapping("Asset Class", value_map=dict(_CLASS_MAP)),
    "approach": ComponentMapping("Approach", value_map=dict(_APPROACH_MAP)),
    "cqs": ComponentMapping("CQS"),
    "pd": ComponentMapping("PD Pct", unit="percent"),
    "lgd": ComponentMapping("LGD Pct", unit="percent"),
    "maturity": ComponentMapping("Maturity Yrs"),
    "ccf": ComponentMapping("CCF Pct", unit="percent"),
    "collateral": ComponentMapping("Collateral"),
    "guarantee": ComponentMapping("Guaranteed 000", scale=1_000.0),
    "guarantee_rwa_benefit": ComponentMapping("Guarantee Benefit"),
    "ead": ComponentMapping("EAD 000", scale=1_000.0),
    "risk_weight": ComponentMapping("RW Pct", unit="percent"),
    "supporting_factor": ComponentMapping("Supporting Factor"),
    "rwa_pre_factor": ComponentMapping("RWA Pre SF 000", scale=1_000.0),
    "expected_loss": ComponentMapping("EL 000", scale=1_000.0),
    "provisions": ComponentMapping("Provisions"),
    "rwa": ComponentMapping("RWA 000", scale=1_000.0),
}
_RAW_GROSS_COMPONENTS: dict[str, ComponentMapping] = {
    "drawn": ComponentMapping("Drawn 000", scale=1_000.0),
    "interest": ComponentMapping("Accrued 000", scale=1_000.0),
    "undrawn": ComponentMapping("Undrawn 000", scale=1_000.0),
    "nominal": ComponentMapping("Nominal 000", scale=1_000.0),
}
_DERIVED_GROSS_COMPONENTS: dict[str, ComponentMapping] = {
    "gross_on_balance_sheet": ComponentMapping("Gross On BS 000", scale=1_000.0),
    "gross_off_balance_sheet": ComponentMapping("Gross Off BS 000", scale=1_000.0),
}

_CARRIERS: dict[str, CarrierMapping] = {
    "obligor": CarrierMapping("Obligor Ref"),
    "exposure_type": CarrierMapping(
        "Product", value_map={"TERM LOAN": "loan", "RCF": "facility_undrawn"}
    ),
    "defaulted": CarrierMapping("Default Flag", value_map={"Y": "true", "N": "false"}),
    "protection_type": CarrierMapping(
        "Protection", value_map={"GTEE": "guarantee", "CDS": "credit_derivative"}
    ),
}

_ROUTES = {
    "raw": (_RAW_GROSS_COMPONENTS, _RAW_SCHEMA, _RAW_ROWS),
    "derived": (_DERIVED_GROSS_COMPONENTS, _DERIVED_SCHEMA, _DERIVED_ROWS),
}


def _reference_frame(route: str) -> pl.LazyFrame:
    """Our own results for one gross route, in the projectable vocabulary."""
    _components, schema, rows = _ROUTES[route]
    return pl.LazyFrame({**_COMMON_ROWS, **rows}, schema={**_COMMON_SCHEMA, **schema})


def _components_for(route: str) -> dict[str, ComponentMapping]:
    return {**_BASE_COMPONENTS, **_ROUTES[route][0]}


def _write_legacy(tmp_path: Path, rows: dict[str, list[object]] | None = None) -> Path:
    """Write the firm's extract as a parquet the loader can scan."""
    path = tmp_path / "legacy.parquet"
    pl.DataFrame(rows if rows is not None else _LEGACY_ROWS).write_parquet(path)
    return path


def _load(
    tmp_path: Path,
    components: dict[str, ComponentMapping],
    carriers: dict[str, CarrierMapping] | None = None,
    rows: dict[str, list[object]] | None = None,
) -> tuple[pl.LazyFrame, LegacyColumnMapping]:
    """Run the real loader so the projection's input is the production shape."""
    mapping = LegacyColumnMapping(
        legacy_keys=("Loan Ref",),
        our_keys=("exposure_reference",),
        components=components,
        carriers=carriers or {},
    )
    settings = ReconciliationSettings(
        legacy_file=_write_legacy(tmp_path, rows),
        mapping=mapping,
        legacy_format="parquet",
    )
    return LegacyOutputLoader(settings).load(), mapping


def _assert_same_templates(ours: object, theirs: object) -> None:
    for template in TEMPLATES:
        our_sheets: dict[str, pl.DataFrame] = getattr(ours, template)
        their_sheets: dict[str, pl.DataFrame] = getattr(theirs, template)
        assert our_sheets, f"{template} produced no sheet on the reference side"
        assert set(our_sheets) == set(their_sheets), template
        for exposure_class, our_sheet in our_sheets.items():
            assert_frame_equal(
                our_sheet,
                their_sheets[exposure_class],
                check_exact=False,
                rel_tol=1e-9,
                abs_tol=1e-12,
            )


def _cell(sheet: pl.DataFrame, row_ref: str, col_ref: str) -> float | None:
    matched = sheet.filter(pl.col("row_ref") == row_ref)
    assert matched.height == 1, f"row {row_ref} not emitted (rows: {sheet['row_ref'].to_list()})"
    return matched[col_ref][0]


# =============================================================================
# The identity test
# =============================================================================


@pytest.mark.parametrize("route", sorted(_ROUTES))
@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_identity_projection_generates_cell_identical_templates(
    tmp_path: Path, framework: str, route: str
) -> None:
    """Our own results, re-read as a legacy extract, generate the same templates.

    The strongest statement this slice can make: the projection is faithful (it
    renames, scales and canonicalises, and changes nothing else) AND the firm's
    side runs through the identical executor, because the only thing that differs
    between the two generate calls is which frame went in. Run on BOTH gross
    routes — the raw-amount one is the path a real extract takes.
    """
    # Arrange
    reference = _reference_frame(route)
    legacy, mapping = _load(tmp_path, _components_for(route), _CARRIERS)

    # Act
    source, coverage = project_legacy_ledger(legacy, mapping, framework=framework)
    ours = COREPGenerator().generate_from_lazyframe(reference, framework=framework)
    theirs = COREPGenerator().generate(source)

    # Assert
    assert coverage.reachable_templates == set(LEDGER_TEMPLATE_IDS)
    assert coverage.unmapped_labels == {}
    _assert_same_templates(ours, theirs)
    # ...and the C 07.00 CRM substitution block is not an equality between two
    # sets of zeros: SA3 (a 400,000 guarantee) and SA4 (a 300,000 credit
    # derivative) are SA-ORIGIN, so cols 0050/0060/0090 carry real money on the
    # obligor sheet. Cols 0050/0060/0090 are Annex II §1.3 "(-)" deductions.
    corporate = theirs.c07_00["corporate"]
    assert _cell(corporate, "0010", "0050") == pytest.approx(-400_000.0)
    assert _cell(corporate, "0010", "0060") == pytest.approx(-300_000.0)
    assert _cell(corporate, "0010", "0090") == pytest.approx(-700_000.0)


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_raw_and_derived_gross_routes_agree(tmp_path: Path, framework: str) -> None:
    """Deriving the per-side gross gives the same templates as mapping it.

    The evidence for choosing the raw route as the default: it is not a
    compromise. ``ensure_gross_side_carriers`` reproduces the firm's own split
    exactly, so mapping the derived carriers buys nothing but an extra column.
    """
    # Arrange
    raw_legacy, raw_mapping = _load(tmp_path, _components_for("raw"), _CARRIERS)
    derived_legacy, derived_mapping = _load(tmp_path, _components_for("derived"), _CARRIERS)

    # Act
    raw_source, _c1 = project_legacy_ledger(raw_legacy, raw_mapping, framework=framework)
    derived_source, _c2 = project_legacy_ledger(
        derived_legacy, derived_mapping, framework=framework
    )

    # Assert
    raw_bundle = COREPGenerator().generate(raw_source)
    _assert_same_templates(raw_bundle, COREPGenerator().generate(derived_source))
    # ...and the agreement is not between two sets of zeros: both gross SIDES
    # carry money on the derived route, so the derivation is genuinely exercised.
    assert _cell(raw_bundle.c08_03["corporate"], "0050", "0010") == pytest.approx(4_000_000.0)
    assert _cell(raw_bundle.c07_00["retail_other"], "0080", "0010") == pytest.approx(500_000.0)


def test_projection_satisfies_the_results_source_protocol(tmp_path: Path) -> None:
    """``LegacyLedgerSource`` is structurally a ``reporting.metadata.ResultsSource``."""
    # Arrange
    legacy, mapping = _load(tmp_path, _components_for("raw"), _CARRIERS)

    # Act
    source, _coverage = project_legacy_ledger(legacy, mapping, framework="CRR")

    # Assert — the annotation is what ``ty`` checks; the call proves it at runtime
    def accepts(results_source: ResultsSource) -> str:
        return results_source.framework

    assert isinstance(source, LegacyLedgerSource)
    assert accepts(source) == "CRR"
    assert source.scan_results().collect().height == 7


# =============================================================================
# The leave-one-out property: a silently changed cell is a bug
# =============================================================================


def _cells(bundle: object, template_id: str) -> dict[tuple[str, str, str], float | None]:
    """Every (sheet, row, col) -> value of one template on one bundle."""
    out: dict[tuple[str, str, str], float | None] = {}
    for sheet_key, sheet in getattr(bundle, template_id).items():
        value_cols = [c for c in sheet.columns if c not in {"row_ref", "row_name"}]
        for row in sheet.iter_rows(named=True):
            for col in value_cols:
                out[(sheet_key, row["row_ref"], col)] = row[col]
    return out


def _changed(
    baseline: dict[tuple[str, str, str], float | None],
    variant: dict[tuple[str, str, str], float | None],
) -> set[tuple[str, str, str]]:
    """The cells that differ, treating appearance and disappearance as changes."""
    return {key for key in baseline | variant if baseline.get(key) != variant.get(key)}


@pytest.mark.parametrize("framework", FRAMEWORKS)
@pytest.mark.parametrize("dropped", sorted({*_components_for("raw"), *_CARRIERS}))
def test_dropping_any_mapping_changes_no_cell_coverage_does_not_name(
    tmp_path: Path, dropped: str, framework: str
) -> None:
    """Drop each mapping in turn; every cell it moves must be REPORTED.

    The general guard, written as the property rather than as a list of the
    carriers someone thought of. It is how the ``drawn`` / ``undrawn`` defect was
    found: an OR-group read ``interest`` as an ALTERNATIVE to ``drawn`` when
    ``ensure_gross_side_carriers`` treats it as an ADDEND, so a mapping without
    ``drawn`` satisfied the requirement, coverage called the cell available, and
    the generator published a present, non-null 0.0 — a 100% understatement of
    on-balance-sheet gross reported as a confident zero, with
    ``unavailable_refs("c07_00")`` byte-identical to the full mapping's.

    A changed cell is acceptable only if coverage says so, in one of four ways:
    the template became unreachable, the cell's COLUMN is unavailable, the cell's
    ROW cannot be keyed, or the row axis was deleted outright. Anything else is a
    silent change, which is the bug.

    Over-reporting is deliberately allowed: naming a cell that did not move costs
    an analyst a look, while missing one costs them a wrong number.
    """
    # Arrange
    components = {k: v for k, v in _components_for("raw").items() if k != dropped}
    carriers = {k: v for k, v in _CARRIERS.items() if k != dropped}
    full_legacy, full_mapping = _load(tmp_path, _components_for("raw"), _CARRIERS)
    baseline_source, _baseline_cov = project_legacy_ledger(
        full_legacy, full_mapping, framework=framework
    )
    baseline = COREPGenerator().generate(baseline_source)

    thin_legacy, thin_mapping = _load(tmp_path, components, carriers)

    # Act
    thin_source, coverage = project_legacy_ledger(thin_legacy, thin_mapping, framework=framework)
    variant = COREPGenerator().generate(thin_source)

    # Assert
    for template_id in TEMPLATES:
        if template_id not in coverage.reachable_templates:
            continue  # reported as unproducible, which is the loud condition
        if coverage.row_axis_deleted(template_id):
            continue
        moved = _changed(_cells(baseline, template_id), _cells(variant, template_id))
        named_cols = set(coverage.unavailable_refs(template_id))
        named_rows = set(coverage.unavailable_rows(template_id, framework))
        silent = sorted(
            f"{sheet}/{row}/{col}"
            for sheet, row, col in moved
            if col not in named_cols and row not in named_rows
        )
        assert silent == [], (
            f"dropping {dropped!r} silently changed {template_id} cells {silent} — "
            f"coverage names columns {sorted(named_cols)} and rows {sorted(named_rows)}"
        )


# =============================================================================
# The sealed-target rule
# =============================================================================


def test_every_projection_target_is_a_sealed_ledger_column() -> None:
    """No registry entry may write onto a synthetic-frame-only ladder rung.

    The generators resolve most quantities through a ladder — ``scra_provision_amount``
    before ``provision_deducted``, ``bs_type`` before ``exposure_type``,
    ``ccf_applied`` beside ``ccf``. Only the sealed rungs exist on a real run, so
    targeting an unsealed one would put the legacy side on a DIFFERENT rung from
    ours and produce two plausible numbers from different bases. Asserted against
    the edge contract itself, which cannot drift with this module.
    """
    # Arrange
    sealed = set(AGGREGATOR_EXIT_EDGE.columns)
    targets: set[str] = set()
    for spec in RECONCILABLE_COMPONENTS:
        targets |= set(MULTI_TARGET_COMPONENTS.get(spec.name, (spec.our_columns[0],)))
    targets |= {carrier.ledger_column for carrier in LEDGER_CARRIERS}

    # Act
    unsealed = sorted(targets - sealed)

    # Assert
    assert unsealed == [], f"projection targets not on AGGREGATOR_EXIT_EDGE: {unsealed}"


def test_provisions_land_on_the_rung_our_own_side_traverses(tmp_path: Path) -> None:
    """A mapped provisions column reaches both sealed carriers, and neither SCRA.

    C 07.00 col 0030 resolves ``provision_deducted`` and the C 08.01/C 08.03
    post-pass resolves ``provision_allocated``; both ladders check SCRA/GCRA
    first, and neither SCRA column is sealed. Landing there would also move
    ``_block_cap_scale``, the C 07.00 protection-block cap basis.
    """
    # Arrange
    legacy, mapping = _load(tmp_path, _components_for("raw"), _CARRIERS)

    # Act
    source, _coverage = project_legacy_ledger(legacy, mapping, framework="CRR")
    projected = source.scan_results().collect()

    # Assert
    assert projected["provision_deducted"].to_list() == projected["provision_allocated"].to_list()
    assert projected["provision_deducted"][0] == pytest.approx(1_500.0)
    assert "scra_provision_amount" not in projected.columns
    assert "gcra_provision_amount" not in projected.columns


def test_a_leg_written_to_both_provision_names_is_counted_once(tmp_path: Path) -> None:
    """The dual write cannot double-count, because the populations partition.

    One mapped provisions value lands on ``provision_deducted`` AND
    ``provision_allocated``, so the safety of that rests on no leg reaching both
    readers. C 07.00 filters ``reporting_approach_origin == "standardised"`` and
    C 08.01/C 08.03 filter the IRB set; a leg has exactly one origin approach, so
    the two populations are disjoint. Measured here rather than argued: the
    corporate sheets split 54,500 of provisions into 1,500 (the SA leg, C 07.00
    col 0030) and 53,000 (the two IRB legs, C 08.01 col 0290) with nothing
    counted twice and nothing lost. Both columns carry the Annex II §1.3 "(-)"
    sign, hence the negatives.
    """
    # Arrange — SA1 1,500 | IRB1 3,000 | IRB2 50,000, all on the corporate sheet
    legacy, mapping = _load(tmp_path, _components_for("raw"), _CARRIERS)

    # Act
    source, _coverage = project_legacy_ledger(legacy, mapping, framework="CRR")
    bundle = COREPGenerator().generate(source)

    # Assert
    sa_provisions = _cell(bundle.c07_00["corporate"], "0010", "0030")
    irb_provisions = _cell(bundle.c08_01["corporate"], "0010", "0290")
    assert sa_provisions == pytest.approx(-1_500.0)
    assert irb_provisions == pytest.approx(-53_000.0)
    assert -(sa_provisions + irb_provisions) == pytest.approx(54_500.0)


def test_risk_type_is_not_projectable_so_the_populations_cannot_overlap() -> None:
    """The one mechanism that could break the population partition is unreachable.

    ``c07_population`` admits the counterparty-credit-risk rows by ``risk_type``
    with NO approach filter, so an IRB-origin CCR leg would sit in C 07.00's
    population AND C 08.01's — the single structural breach of the disjointness
    the dual provisions write depends on. It cannot arise here because nothing in
    the grammar can supply ``risk_type``: with the column absent, ``admit`` is
    ``None`` and the population is purely approach-based.

    This test is the guard on that. Adding a ``risk_type`` carrier later would
    make the breach reachable, and the dual write would then have to be split
    per approach — so this must fail loudly rather than the projection quietly
    acquiring a double count.
    """
    # Arrange / Act / Assert
    assert "risk_type" not in PROJECTABLE_LEDGER_COLUMNS


# =============================================================================
# Label canonicalisation
# =============================================================================


def test_categorical_component_labels_are_canonicalised_by_the_projection(
    tmp_path: Path,
) -> None:
    """A legacy class label reaches the sheet key CANONICALISED, not raw.

    The loader is mechanical: ``_component_expr`` casts a categorical to String
    and applies NO ``value_map`` (``analysis.reconciliation`` does that at
    comparison time). So the projection has to, or a firm's ``"CORP"`` partitions
    into a sheet no template has and C 07.00 / C 08.01 / C 08.03 come out silently
    empty — the exact failure this feature exists to surface, shipped inside it.
    """
    # Arrange — the extract says CORP / RETAIL / INST and SA / AIRB / FIRB
    legacy, mapping = _load(tmp_path, _components_for("raw"), _CARRIERS)

    # Act
    source, _coverage = project_legacy_ledger(legacy, mapping, framework="CRR")
    projected = source.scan_results().collect()
    sheets = COREPGenerator().generate(source)

    # Assert
    assert projected["reporting_class_origin"].to_list() == [
        "corporate",
        "retail_other",
        "corporate",
        "corporate",
        "institution",
        "corporate",
        "corporate",
    ]
    assert projected["reporting_approach_origin"].to_list() == [
        "standardised",
        "standardised",
        "advanced_irb",
        "advanced_irb",
        "foundation_irb",
        "standardised",
        "standardised",
    ]
    # ...and the canonical labels are what the sheet axes actually key on.
    assert set(sheets.c07_00) == {"corporate", "retail_other"}
    assert set(sheets.c08_01) == {"corporate", "institution"}


def test_categorical_component_label_is_casefolded_without_a_value_map(
    tmp_path: Path,
) -> None:
    """An already-canonical label in the wrong case still keys its sheet.

    Mirrors ``analysis.reconciliation``'s ``_normalise`` so a label that
    reconciles as equal on the exposure-grain view keys the same sheet here.
    """
    # Arrange — no value_map at all; the extract's own labels are canonical
    rows = dict(_LEGACY_ROWS)
    rows["Asset Class"] = [
        "Corporate",
        "RETAIL_OTHER",
        " corporate",
        "corporate",
        "Institution",
        "CORPORATE",
        "corporate ",
    ]
    components = dict(_components_for("raw"))
    components["exposure_class"] = ComponentMapping("Asset Class")
    legacy, mapping = _load(tmp_path, components, _CARRIERS, rows)

    # Act
    source, _coverage = project_legacy_ledger(legacy, mapping, framework="CRR")

    # Assert
    assert source.scan_results().collect()["reporting_class_origin"].to_list() == [
        "corporate",
        "retail_other",
        "corporate",
        "corporate",
        "institution",
        "corporate",
        "corporate",
    ]


def test_the_vocabularies_are_anchored_to_their_sources_of_truth() -> None:
    """No vocabulary may be a hand-written list that drifts out of the engine.

    A vocabulary that drifts is invisible: a label the engine accepts but this
    table does not gets reported as unmapped (a false alarm), and one the engine
    rejects but the table accepts passes through silently again — the exact
    failure the vocabulary exists to remove. So each is asserted against the
    definition it is taken from, none of which can change with this module.
    """
    # Arrange / Act / Assert
    assert LEDGER_VOCABULARY["reporting_class_origin"].values == {
        member.value for member in ExposureClass
    }
    assert LEDGER_VOCABULARY["reporting_approach_origin"].values == {
        member.value for member in ApproachType
    }
    assert LEDGER_VOCABULARY["protection_type"].values == set(VALID_PROTECTION_TYPES)
    # The exposure-type set is the kernel's credit-risk gross scope plus the
    # legacy "facility" alias every balance-sheet discriminator still recognises.
    assert LEDGER_VOCABULARY["exposure_type"].values == {*_CREDIT_BS_TYPES, "facility"}
    # And every population label a template filters on is a real approach.
    for labels in TEMPLATE_POPULATION_LABELS.values():
        assert labels <= {member.value for member in ApproachType}


def test_unmapped_class_label_is_reported_with_its_row_count(tmp_path: Path) -> None:
    """A class label matching no ``ExposureClass`` is named, not passed through.

    Canonicalisation casefolds and applies the value_map; it cannot INVENT a
    translation. An unrecognised class silently keys a sheet no template has, so
    the value, its row count and the TOML table to fix are reported instead.
    """
    # Arrange — "SOVEREIGN" has no value_map entry and is not an ExposureClass
    rows = dict(_LEGACY_ROWS)
    rows["Asset Class"] = ["SOVEREIGN", "RETAIL", "CORP", "CORP", "INST", "SOVEREIGN", "CORP"]
    legacy, mapping = _load(tmp_path, _components_for("raw"), _CARRIERS, rows)

    # Act
    _source, coverage = project_legacy_ledger(legacy, mapping, framework="CRR")

    # Assert
    assert coverage.unmapped_labels["exposure_class"] == ("sovereign (2 rows)",)
    assert "approach" not in coverage.unmapped_labels


def test_unmapped_approach_label_makes_every_template_unreachable(tmp_path: Path) -> None:
    """The worst failure this feature can have, and the one coverage used to hide.

    ``population_flags`` admits by an ``is_in`` over the approach values, so a
    label outside the vocabulary matches NOTHING and every template emits no
    sheet at all. Reachability that reported "all three reachable" alongside a
    blank return was asserting the opposite of the truth — and the decomposition
    slice now refuses to decompose a cell coverage marks unavailable, so an
    optimistic answer here propagates into confidently wrong waterfalls.

    The bundle is asserted empty as well as the coverage, so the two cannot
    drift: this test fails if either the reporting or the reality changes.
    """
    # Arrange — the firm writes "IRB", with no value_map to translate it
    rows = dict(_LEGACY_ROWS)
    rows["Approach"] = ["IRB"] * 7
    components = dict(_components_for("raw"))
    components["approach"] = ComponentMapping("Approach")
    legacy, mapping = _load(tmp_path, components, _CARRIERS, rows)

    # Act
    source, coverage = project_legacy_ledger(legacy, mapping, framework="CRR")
    bundle = COREPGenerator().generate(source)

    # Assert — coverage says unreachable...
    assert coverage.reachable_templates == frozenset()
    assert coverage.unmapped_labels["approach"] == ("irb (7 rows)",)
    assert coverage.present_approaches == frozenset({"irb"})
    # ...naming the offending value rather than a column, because the column IS
    # there — nothing is missing, the values are simply not the ones needed.
    for template_id in LEDGER_TEMPLATE_IDS:
        assert coverage.blocking_columns(template_id) == ()
        assert coverage.blocking_labels(template_id) == ("irb",)
    # ...and reality agrees: every template really does emit nothing.
    assert bundle.c07_00 == {}
    assert bundle.c08_01 == {}
    assert bundle.c08_03 == {}


def test_an_all_sa_book_leaves_the_irb_templates_reachable_but_unpopulated(
    tmp_path: Path,
) -> None:
    """ "This firm has no IRB book" is NOT "you cannot produce C 08.01".

    Reachable is a statement about the MAPPING; populated is a statement about
    the BOOK. Every label here is recognised, so nothing about the mapping stops
    C 08.01 — the extract simply carries no IRB rows. Reporting that as
    unreachable produced an unreachable template with ``blocking_labels() == ()``:
    unreachable with nothing to fix, which a user cannot act on, and the same
    conflation ``sheet_not_emitted`` already made between "no exposure" and "no
    bundle key".
    """
    # Arrange — every leg standardised, every label valid
    rows = dict(_LEGACY_ROWS)
    rows["Approach"] = ["SA"] * 7
    legacy, mapping = _load(tmp_path, _components_for("raw"), _CARRIERS, rows)

    # Act
    source, coverage = project_legacy_ledger(legacy, mapping, framework="CRR")
    bundle = COREPGenerator().generate(source)

    # Assert — reachable, because the mapping is complete...
    assert coverage.reachable_templates == set(LEDGER_TEMPLATE_IDS)
    assert coverage.unmapped_labels == {}
    for template_id in LEDGER_TEMPLATE_IDS:
        assert coverage.blocking_columns(template_id) == ()
        assert coverage.blocking_labels(template_id) == ()
    # ...and unpopulated, because the book has no IRB exposures.
    assert coverage.populated_templates == {"c07_00"}
    assert bundle.c07_00
    assert bundle.c08_01 == {}
    assert bundle.c08_03 == {}


def test_unmapped_approach_is_unreachable_where_an_absent_population_is_not(
    tmp_path: Path,
) -> None:
    """The two "no IRB rows" cases are told apart by WHY, and only one is a defect.

    Same observation — no recognised approach admits C 08.01 — with opposite
    meanings. An unrecognised label might have BEEN the missing population, so it
    is a mapping defect with something to fix; a fully recognised all-SA book is
    just a book without an IRB business.
    """
    # Arrange — one leg's approach is unrecognised, the rest are standardised
    rows = dict(_LEGACY_ROWS)
    rows["Approach"] = ["SA", "SA", "IRB-A", "SA", "SA", "SA", "SA"]
    components = dict(_components_for("raw"))
    components["approach"] = ComponentMapping("Approach", value_map={"SA": "standardised"})
    legacy, mapping = _load(tmp_path, components, _CARRIERS, rows)

    # Act
    _source, coverage = project_legacy_ledger(legacy, mapping, framework="CRR")

    # Assert
    assert coverage.unmapped_labels["approach"] == ("irb-a (1 rows)",)
    assert "c08_01" not in coverage.reachable_templates
    assert coverage.blocking_columns("c08_01") == ()
    assert coverage.blocking_labels("c08_01") == ("irb-a", "standardised")
    # C 07.00 is unaffected: a recognised label admits it.
    assert "c07_00" in coverage.reachable_templates
    assert coverage.populated_templates == {"c07_00"}


def test_preflight_coverage_cannot_answer_the_population_question() -> None:
    """The column-only form knows what the mapping unlocks, not what the book has.

    ``ledger_coverage`` without ``present_approaches`` answers "what would this
    mapping unlock" — a different question from "what did it". It reports
    ``populated_templates is None`` rather than guessing, because a guess here is
    exactly the conflation that made an all-standardised book look like a broken
    mapping. Reachability is unaffected: that IS a mapping question, and the
    pre-flight form can answer it.
    """
    # Arrange
    supplied = {"reporting_class_origin", "reporting_approach_origin", "ead_final", "rwa_final"}

    # Act
    preflight = ledger_coverage(supplied, framework="CRR")
    all_sa = ledger_coverage(
        supplied, framework="CRR", present_approaches=frozenset({"standardised"})
    )
    unmapped = ledger_coverage(
        supplied,
        framework="CRR",
        present_approaches=frozenset({"irb"}),
        unmapped_labels={"approach": ("irb (7 rows)",)},
    )

    # Assert — pre-flight: reachability answered, population not knowable
    assert preflight.reachable_templates == {"c07_00", "c08_01"}
    assert preflight.present_approaches is None
    assert preflight.populated_templates is None
    # A complete mapping over an SA-only book: still reachable, now known unpopulated
    assert all_sa.reachable_templates == {"c07_00", "c08_01"}
    assert all_sa.populated_templates == {"c07_00"}
    # An unrecognised label: genuinely unreachable, and it says which value
    assert unmapped.reachable_templates == frozenset()
    assert unmapped.populated_templates == frozenset()
    assert unmapped.blocking_labels("c08_01") == ("irb",)


# =============================================================================
# Null, never zero
# =============================================================================


def test_unsupplied_carriers_yield_null_cells_and_are_reported(tmp_path: Path) -> None:
    """An unmapped carrier produces a null cell, not a legacy zero — and is named.

    ``irb_maturity_m`` (C 08.03 col 0080) and ``expected_loss`` (col 0100) are the
    two clean cases: their bindings resolve the column by name, so an absent
    column renders ``None``. A false 0.0 there would read as "the firm reports no
    maturity / no expected loss", which is the largest kind of delta on the sheet.
    """
    # Arrange — every component EXCEPT maturity and expected_loss
    components = {
        name: spec
        for name, spec in _components_for("raw").items()
        if name not in {"maturity", "expected_loss"}
    }
    legacy, mapping = _load(tmp_path, components, _CARRIERS)

    # Act
    source, coverage = project_legacy_ledger(legacy, mapping, framework="CRR")
    sheet = COREPGenerator().generate(source).c08_03["corporate"]

    # Assert
    assert _cell(sheet, "0050", "0080") is None
    assert _cell(sheet, "0050", "0100") is None
    assert "irb_maturity_m" in coverage.missing
    assert "expected_loss" in coverage.missing
    assert "0080" in coverage.unavailable_refs("c08_03")
    assert "0100" in coverage.unavailable_refs("c08_03")


def test_unsupplied_carrier_reason_names_the_column_to_map(tmp_path: Path) -> None:
    """The coverage entry carries the WHY, so a panel can say what to map."""
    # Arrange
    components = {
        name: spec for name, spec in _components_for("raw").items() if name != "provisions"
    }
    legacy, mapping = _load(tmp_path, components, _CARRIERS)

    # Act
    _source, coverage = project_legacy_ledger(legacy, mapping, framework="CRR")

    # Assert
    entries = coverage.unavailable_cells["c08_03"]
    provisions = next(entry for entry in entries if entry.startswith("0110:"))
    assert "provision_allocated" in provisions
    # ...and it does NOT name the synthetic rungs the cell checks first: nothing
    # in the grammar can map them, so naming them sends an analyst hunting for a
    # column that has no home.
    assert "scra_provision_amount" not in provisions
    assert "provision_held" not in provisions


def test_projection_never_writes_a_column_for_an_unmapped_component(tmp_path: Path) -> None:
    """An unsupplied carrier is ABSENT, not an all-null column.

    A typed null COLUMN is present, and ``kernel/sums.py::col_sum`` sums a present
    all-null column to 0.0 while returning None for an absent one — so injecting
    nulls here would manufacture the very zeros this module exists to avoid.
    """
    # Arrange
    components = {
        name: spec for name, spec in _components_for("raw").items() if name != "expected_loss"
    }
    legacy, mapping = _load(tmp_path, components, _CARRIERS)

    # Act
    source, _coverage = project_legacy_ledger(legacy, mapping, framework="CRR")

    # Assert
    assert "expected_loss" not in source.scan_results().collect_schema().names()


# =============================================================================
# PD band allocation
# =============================================================================


@pytest.mark.parametrize(
    ("framework", "pd_pct", "expected_row", "expected_label"),
    [
        # STRADDLING THE BASEL 3.1 0.05% BOUNDARY. The two PDs are 0.0002
        # percentage points apart and land in the SAME CRR row — CRR's first band
        # splits once, at 0.10% — but in DIFFERENT Basel 3.1 rows, because PS1/26
        # splits it again at 0.05% (18 rows against CRR's 17). A mid-band PD would
        # pass under any banding rule; this pair only passes under the right one.
        ("CRR", 0.0499, "0020", "0.00 to <0.10"),
        ("CRR", 0.0501, "0020", "0.00 to <0.10"),
        ("BASEL_3_1", 0.0499, "0015", "0.00 to <0.05"),
        ("BASEL_3_1", 0.0501, "0025", "0.05 to <0.10"),
    ],
)
def test_mapped_pd_bands_correctly_across_a_band_boundary(
    tmp_path: Path, framework: str, pd_pct: float, expected_row: str, expected_label: str
) -> None:
    """One mapped legacy PD bands correctly on either side of a band edge.

    The projection writes it to ``pd`` AND ``pd_floored`` (module docstring),
    which is what makes this hold: Basel 3.1 allocates on the pre-input-floor
    ``pd`` and CRR on ``pd_floored``, and an extract carrying one PD knows of no
    difference between them. The bands are half-open ``[lower, upper)``, so
    0.0499% is inside the first Basel 3.1 sub-band and 0.0501% is outside it.
    """
    # Arrange — IRB3 (the only institution leg) carries the boundary PD
    rows = dict(_LEGACY_ROWS)
    rows["PD Pct"] = [None, None, 0.35, 100.0, pd_pct, None, None]
    legacy, mapping = _load(tmp_path, _components_for("raw"), _CARRIERS, rows)

    # Act
    source, _coverage = project_legacy_ledger(legacy, mapping, framework=framework)
    sheet = COREPGenerator().generate(source).c08_03["institution"]

    # Assert
    assert expected_row in sheet["row_ref"].to_list()
    assert _cell(sheet, expected_row, "0040") == pytest.approx(2_500_000.0)
    assert sheet.filter(pl.col("row_ref") == expected_row)["row_name"][0] == expected_label
    # The parent band (0010, "0.00 to <0.15") overlaps and sums its children, so
    # it carries the leg whichever sub-band took it.
    assert _cell(sheet, "0010", "0040") == pytest.approx(2_500_000.0)
    # No OTHER sub-band of that parent is emitted — the leg is in exactly one leaf.
    siblings = {"0015", "0020", "0025", "0030"} - {expected_row}
    assert siblings.isdisjoint(sheet["row_ref"].to_list())


def test_mapped_pd_reaches_both_ledger_pd_columns(tmp_path: Path) -> None:
    """The recorded PD decision, asserted directly rather than via a band."""
    # Arrange
    legacy, mapping = _load(tmp_path, _components_for("raw"), _CARRIERS)

    # Act
    source, _coverage = project_legacy_ledger(legacy, mapping, framework="CRR")
    projected = source.scan_results().collect()

    # Assert
    assert projected["pd"].to_list() == projected["pd_floored"].to_list()
    assert projected["pd_floored"][2] == pytest.approx(0.0035)


# =============================================================================
# Coverage and reachability
# =============================================================================


def test_missing_gross_route_reports_c08_03_gross_columns_unavailable(
    tmp_path: Path,
) -> None:
    """With NEITHER gross route mapped, C 08.03 cols 0010/0020 are unavailable...

    ...and the rest of the template still generates. The 0.0 those two cells
    render is NOT a legacy zero: ``kernel/columns.py::ensure_gross_side_carriers``
    injects all-null gross columns at generator entry when it has no source, and a
    present all-null column sums to 0.0. That is the generator's contract, not
    something the projection can fix — which is exactly why the coverage report
    has to name the cells.
    """
    # Arrange
    legacy, mapping = _load(tmp_path, dict(_BASE_COMPONENTS), _CARRIERS)

    # Act
    source, coverage = project_legacy_ledger(legacy, mapping, framework="CRR")
    sheet = COREPGenerator().generate(source).c08_03["corporate"]

    # Assert
    unavailable = coverage.unavailable_refs("c08_03")
    assert {"0010", "0020", "0030"} <= set(unavailable)
    assert "c08_03" in coverage.reachable_templates
    assert _cell(sheet, "0050", "0040") == pytest.approx(4_000_000.0)
    assert _cell(sheet, "0050", "0090") == pytest.approx(2_400_000.0)


def test_template_is_unreachable_without_the_approach_component() -> None:
    """No approach discriminator means an EMPTY population, so nothing is reachable."""
    # Arrange
    supplied = {"reporting_class_origin", "ead_final", "rwa_final", "pd_floored", "pd"}

    # Act
    coverage = ledger_coverage(supplied, framework="CRR")

    # Assert
    assert coverage.reachable_templates == frozenset()
    assert "reporting_approach_origin" in coverage.missing
    assert coverage.blocking_columns("c07_00") == ("reporting_approach_origin",)
    assert not coverage.row_axis_deleted("c08_03")


def test_missing_pd_deletes_c08_03_entirely_and_is_reported_as_such(tmp_path: Path) -> None:
    """C 08.03's PD is its ROW AXIS: without it the template does not exist.

    The one fatal-missing-column case of the three. ``banded_rows`` cannot run,
    ``c08_03_plans`` returns ``{}`` for every class, and NO sheet is emitted — a
    categorically different condition from an empty cell, which a compare surface
    must not render as a template-wide zero delta.
    """
    # Arrange
    components = {name: spec for name, spec in _components_for("raw").items() if name != "pd"}
    legacy, mapping = _load(tmp_path, components, _CARRIERS)

    # Act
    source, coverage = project_legacy_ledger(legacy, mapping, framework="CRR")
    bundle = COREPGenerator().generate(source)

    # Assert
    assert bundle.c08_03 == {}
    assert coverage.row_axis_deleted("c08_03")
    assert coverage.blocking_columns("c08_03") == ("pd", "pd_floored")
    assert "c08_03" not in coverage.reachable_templates
    # ...while the two static-row-axis templates still generate.
    assert coverage.reachable_templates == {"c07_00", "c08_01"}
    assert bundle.c07_00
    assert bundle.c08_01
    assert not coverage.row_axis_deleted("c07_00")


def test_full_mapping_reaches_every_scoped_template() -> None:
    """A mapping of every component and carrier leaves no scoped template behind."""
    # Arrange
    supplied = {
        target
        for spec in RECONCILABLE_COMPONENTS
        for target in (spec.our_columns[0], *(("pd",) if spec.name == "pd" else ()))
    } | {carrier.ledger_column for carrier in LEDGER_CARRIERS}

    # Act
    coverage = ledger_coverage(supplied, framework="BASEL_3_1")

    # Assert
    assert coverage.reachable_templates == set(LEDGER_TEMPLATE_IDS)
    assert coverage.unavailable_refs("c08_03") == ()


def test_unknown_framework_is_a_programming_error(tmp_path: Path) -> None:
    """A bad regime string is the caller's bug, not a data-quality condition."""
    # Arrange
    legacy, mapping = _load(tmp_path, _components_for("raw"))

    # Act / Assert
    with pytest.raises(ValueError, match="framework must be one of"):
        project_legacy_ledger(legacy, mapping, framework="BASEL_III")


# =============================================================================
# Carriers
# =============================================================================


def test_carrier_values_are_written_verbatim_not_casefolded(tmp_path: Path) -> None:
    """A carrier's value reaches the ledger with its own case intact.

    This guard replaces one that could not fail. Its predecessor asserted the
    same rule against ``exposure_type`` / ``protection_type``, whose vocabularies
    are entirely lowercase — so casefolding a carrier value changed nothing and
    the test stayed green under the exact mutation its docstring named.

    ``counterparty_reference`` is where the rule has teeth: it is a free
    identifier, not a vocabulary, and C 08.01 col 0300 is a DISTINCT COUNT of it.
    ``IRB1`` and ``IRB2`` here are obligors ``"O2"`` and ``"o2"`` — two
    counterparties that a casefold would silently merge into one, understating
    the obligor count on a published cell. The label assertions below ride along;
    the count is the one that detects the mutation.
    """
    # Arrange
    legacy, mapping = _load(tmp_path, _components_for("raw"), _CARRIERS)

    # Act
    source, _coverage = project_legacy_ledger(legacy, mapping, framework="CRR")
    projected = source.scan_results().collect()
    corporate = COREPGenerator().generate(source).c08_01["corporate"]

    # Assert — two distinct obligors on the corporate IRB sheet, not one
    assert projected["counterparty_reference"].to_list()[2:4] == ["O2", "o2"]
    assert _cell(corporate, "0010", "0300") == pytest.approx(2.0)
    assert projected["exposure_type"].to_list()[:2] == ["loan", "facility_undrawn"]
    assert projected["protection_type"].to_list()[5:] == ["guarantee", "credit_derivative"]


def test_unrecognised_flag_token_is_null_not_false(tmp_path: Path) -> None:
    """An unknown default flag stays unknown — "we do not know" is not "not defaulted"."""
    # Arrange
    rows = dict(_LEGACY_ROWS)
    rows["Default Flag"] = ["N", "N", "N", "UNKNOWN", "N", "N", "N"]
    carriers = dict(_CARRIERS)
    carriers["defaulted"] = CarrierMapping("Default Flag", value_map={"Y": "true"})
    legacy, mapping = _load(tmp_path, _components_for("raw"), carriers, rows)

    # Act
    source, _coverage = project_legacy_ledger(legacy, mapping, framework="CRR")

    # Assert
    assert source.scan_results().collect()["is_defaulted"].to_list() == [
        False,
        False,
        False,
        None,
        False,
        False,
        False,
    ]


def test_unknown_carrier_name_is_rejected() -> None:
    """The carrier registry is closed, exactly as the component registry is."""
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="unknown ledger carriers"):
        LegacyColumnMapping(
            legacy_keys=("Loan Ref",),
            components={"rwa": ComponentMapping("RWA 000")},
            carriers={"guarantor": CarrierMapping("Guarantor")},
        )


# =============================================================================
# Backwards compatibility of the mapping grammar
# =============================================================================


_LEGACY_ONLY_CONFIG = """
legacy_file = "./legacy.parquet"
legacy_format = "parquet"
legacy_keys = ["Loan Ref"]
our_keys = ["exposure_reference"]
top_n = 25

[components.rwa]
legacy_column = "RWA 000"
scale = 1000.0

[components.ead]
legacy_column = "EAD 000"
scale = 1000.0
"""


def test_config_without_carriers_parses_unchanged(tmp_path: Path) -> None:
    """Every mapping written before carriers existed keeps working untouched."""
    # Arrange / Act
    settings = loads_reconciliation_config(_LEGACY_ONLY_CONFIG, base_dir=tmp_path)

    # Assert
    assert settings.mapping.carriers == {}
    assert set(settings.mapping.components) == {"rwa", "ead"}
    assert settings.top_n == 25


def test_config_without_carriers_still_projects(tmp_path: Path) -> None:
    """...and still projects — with a coverage report that says what it cannot do."""
    # Arrange
    settings = loads_reconciliation_config(_LEGACY_ONLY_CONFIG, base_dir=tmp_path)
    _write_legacy(tmp_path)
    legacy = LegacyOutputLoader(settings).load()

    # Act
    source, coverage = project_legacy_ledger(legacy, settings.mapping, framework="CRR")

    # Assert
    assert coverage.reachable_templates == frozenset()
    assert set(source.scan_results().collect_schema().names()) == {
        "exposure_reference",
        "rwa_final",
        "ead_final",
    }


def test_carriers_round_trip_through_the_toml_grammar(tmp_path: Path) -> None:
    """``dump`` -> ``loads`` preserves a carrier table, value map included."""
    # Arrange
    settings = ReconciliationSettings(
        legacy_file=tmp_path / "legacy.parquet",
        mapping=LegacyColumnMapping(
            legacy_keys=("Loan Ref",),
            components={"rwa": ComponentMapping("RWA 000", scale=1_000.0)},
            carriers=dict(_CARRIERS),
        ),
        legacy_format="parquet",
    )

    # Act
    reloaded = loads_reconciliation_config(dump_reconciliation_config(settings), base_dir=tmp_path)

    # Assert
    assert reloaded.mapping.carriers == _CARRIERS
