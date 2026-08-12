"""
The input-domain registries are anchored to the schemas they claim to describe.

`contracts/validation.py::_validate_declared_domains` resolves three
hand-written maps in `data/schemas.py` before it can validate anything:

- ``TABLE_SCHEMAS`` — table name -> the declaring schema. A table absent from
  it returns ``[]`` and the domain gate is **silently off for that whole
  table**.
- ``TABLE_KEY_COLUMNS`` — table name -> its natural key. A key that is not a
  real column degrades every error on that table to ``exposure_reference=None``,
  so violations are reported but untraceable to a row.
- ``ColumnSpec.domain`` — the bound itself.

None of these was anchored to anything when the generic reader was written.
Every name resolved at the time, and this file exists so that stays true: a
typo, a rename, or a table added to the bundle and forgotten here produces a
gate that goes quiet rather than a gate that fails. That is the exact shape
this project has already paid for — a column-name map keyed on a string
nothing checked, which published nothing for a template's entire life
(`.claude/LESSONS.md` B1/B3) — and it is the shape the whole input-domain
workstream exists to close, so it would be a poor thing to reintroduce inside
the change that closes it.

References:
- docs/plans/test-space-correctness-proposal.md (Phases 0-1)
- .claude/LESSONS.md B1 — a presence guard on a name no run produces
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.edges import RAW_TABLE_EDGES
from rwa_calc.data.column_spec import NumericDomain
from rwa_calc.data.schemas import TABLE_KEY_COLUMNS, TABLE_SCHEMAS

#: Table names namespaced to a composite sub-bundle rather than a top-level
#: RawDataBundle field. They are declared in CCR_TABLE_EDGES / SFT_TABLE_EDGES,
#: not RAW_TABLE_EDGES, so they are legitimately outside the raw-edge anchor.
_COMPOSITE_PREFIXES = ("ccr.", "sft.")


def _top_level(table_names: object) -> set[str]:
    """The subset of *table_names* that name a top-level raw table."""
    return {
        name
        for name in table_names  # type: ignore[attr-defined]
        if not name.startswith(_COMPOSITE_PREFIXES)
    }


def test_every_key_column_is_a_column_of_its_own_schema() -> None:
    """A key that is not a real column silently costs every error its row identity."""
    # Act
    unresolved = {
        table: key for table, key in TABLE_KEY_COLUMNS.items() if key not in TABLE_SCHEMAS[table]
    }

    # Assert
    assert not unresolved, (
        "TABLE_KEY_COLUMNS names a column its schema does not declare. "
        "_validate_declared_domains drops to key_column=None for these, so their "
        "domain violations are reported with exposure_reference=None and cannot be "
        f"traced to a row: {unresolved}"
    )


def test_every_keyed_table_has_a_schema() -> None:
    """A key for a table with no schema is a rename that only half landed."""
    # Act
    orphans = sorted(set(TABLE_KEY_COLUMNS) - set(TABLE_SCHEMAS))

    # Assert
    assert not orphans, (
        f"TABLE_KEY_COLUMNS names tables absent from TABLE_SCHEMAS: {orphans}. "
        "The domain gate resolves the schema first and returns [] when it is missing, "
        "so these tables are not validated at all."
    )


def test_every_table_carrying_declared_domains_can_name_its_rows() -> None:
    """Declaring a domain without a key buys errors nobody can act on."""
    # Arrange
    with_domains = {
        table
        for table, schema in TABLE_SCHEMAS.items()
        if any(spec.domain is not None for spec in schema.values())
    }

    # Act
    unkeyed = sorted(with_domains - set(TABLE_KEY_COLUMNS))

    # Assert
    assert not unkeyed, (
        f"these tables declare an input domain but have no TABLE_KEY_COLUMNS entry: "
        f"{unkeyed}. Their violations would be reported with no row reference, which "
        "is the difference between a finding a firm can fix and a finding it cannot."
    )


def test_top_level_table_names_are_raw_edge_names() -> None:
    """The registries key on the same strings the loader edge contracts do."""
    # Act
    unknown = sorted(_top_level(TABLE_SCHEMAS) - set(RAW_TABLE_EDGES))

    # Assert
    assert not unknown, (
        f"TABLE_SCHEMAS names top-level tables that are not RAW_TABLE_EDGES keys: "
        f"{unknown}. The bundle field, the edge contract and the domain registry must "
        "agree on the table's name, or the gate resolves nothing for it."
    )


def test_every_validated_bundle_table_has_a_schema_entry() -> None:
    """A raw table the gate iterates but cannot resolve is a gate that is off.

    ``validate_bundle_values`` walks the ``RawDataBundle`` LazyFrame fields.
    Any field it reaches whose name is missing from ``TABLE_SCHEMAS`` gets no
    domain validation at all, silently — no error, no warning, no log.
    """
    # Arrange — the bundle's own declared frame fields, from the dataclass.
    frame_fields = {
        name
        for name, field in RawDataBundle.__dataclass_fields__.items()
        if name in RAW_TABLE_EDGES
    }

    # Act
    unresolvable = sorted(frame_fields - set(TABLE_SCHEMAS))

    # Assert
    assert not unresolvable, (
        f"these RawDataBundle tables have a loader edge contract but no TABLE_SCHEMAS "
        f"entry, so the input-domain gate skips them in silence: {unresolvable}"
    )


def test_the_anchor_actually_fires_on_a_broken_key() -> None:
    """A negative control — the assertions above must be capable of failing.

    Anchoring tests are themselves prone to the trap they guard: an assertion
    over an empty or mis-derived set passes forever. This proves the key-column
    check discriminates.
    """
    # Arrange — a plausible typo of a real key.
    broken = dict(TABLE_KEY_COLUMNS)
    broken["loans"] = "loan_ref"

    # Act
    unresolved = {table: key for table, key in broken.items() if key not in TABLE_SCHEMAS[table]}

    # Assert
    assert unresolved == {"loans": "loan_ref"}, (
        "the key-column anchor cannot distinguish a valid key from a typo, so the "
        "positive test above proves nothing."
    )


@pytest.mark.parametrize(
    ("lower", "upper", "value", "expected_violation"),
    [
        (0.0, 1.0, 0.0, False),  # closed lower bound admits its own value
        (0.0, 1.0, 1.5, True),  # the percent-scale PD feed
        (0.0, 1.0, -0.01, True),
        (0.0, None, 1e12, False),  # unbounded above
    ],
)
def test_numeric_domain_violation_expr_discriminates(
    lower: float, upper: float | None, value: float, expected_violation: bool
) -> None:
    """The predicate a declared domain compiles to must actually separate values."""
    # Arrange
    domain = NumericDomain(reason="test", lower=lower, upper=upper)
    frame = pl.DataFrame({"x": [value]})

    # Act
    flagged = frame.select(domain.violation_expr("x")).to_series().item()

    # Assert
    assert flagged is expected_violation, (
        f"domain {domain.describe()} judged {value} as "
        f"{'out of' if flagged else 'in'} domain; expected the opposite"
    )


def test_null_is_never_a_domain_violation() -> None:
    """Missing and out-of-range are different findings with different codes."""
    # Arrange
    domain = NumericDomain(reason="test", lower=0.0, upper=1.0)
    frame = pl.DataFrame({"x": [None]}, schema={"x": pl.Float64})

    # Act
    flagged = frame.select(domain.violation_expr("x")).to_series().item()

    # Assert — conflating the two would make the error channel useless for both.
    assert not flagged, "a null was reported as out-of-domain; it is a missing-value finding"
