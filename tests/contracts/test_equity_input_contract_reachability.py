"""
P1.206 -- every column the equity calculator reads from input survives the loader.

Pipeline position:
    equity_exposures file -> loader seal (RAW_TABLE_EDGES["equity_exposures"])
        -> ... -> EquityCalculator._prepare_columns (ensure_columns over
        ``_EQUITY_INPUT_CONTRACT``)

The equity calculator defaults the columns it reads through
``_EQUITY_INPUT_CONTRACT``. The loader seal (``seal_lenient`` ->
``conform_lenient``) emits only the columns the ``equity_exposures`` edge
declares, and it drops every other column with no data-quality error. A
contract key the edge does not declare is therefore always absent by the time
the calculator runs, and ``ensure_columns`` injects its default on every
production row. Any branch keyed on that column is dead in production. Unit
tests that hand-build frames for ``calculate_branch`` keep the column and so
report the dead branch as covered.

Measured instance (P1.206): ``is_diversified_portfolio`` was a contract key
with default False. The IRB-Simple branch read it as a second encoding of CRR
Art. 155(2)'s "private equity exposures in sufficiently diversified portfolios".
The edge never declared it, so a firm that followed the user guide and set it
got 370% / 2.4% EL (IRB-Simple) and a 90% LGD (Art. 165(2), PD/LGD) in place of
190% / 0.8% / 65%, silently. The one encoding the loader carries is
``equity_type == "private_equity_diversified"``.

The test seals a frame carrying every contract key, the way the loader does,
and requires each key to survive unless the pipeline derives it (named below,
with the step that writes it).

References:
- CRR Art. 155(2), 155(3), 165(2): the diversified-private-equity predicate.
- engine/loader.py::_seal_table, contracts/edges.py::seal_lenient.
"""

from __future__ import annotations

import polars as pl

from rwa_calc.contracts.edges import RAW_TABLE_EDGES, seal_lenient
from rwa_calc.engine.equity.calculator import _EQUITY_INPUT_CONTRACT

#: Contract keys the pipeline derives rather than loads, each with the step that
#: writes it. A key here is exempt from the survival check; it must still be a
#: contract key and must not also be declared on the loader edge.
_DERIVED_KEYS: dict[str, str] = {
    "ciu_look_through_rw": (
        "EquityCalculator._resolve_look_through_rw: Art. 132A(1) look-through "
        "over the ciu_holdings table"
    ),
}

_EQUITY_EDGE = RAW_TABLE_EDGES["equity_exposures"]


def test_every_loaded_equity_contract_key_survives_the_loader_seal() -> None:
    """A key the seal strips is a column the engine reads but no input can set."""
    # Arrange -- one row carrying every contract key in its contract dtype.
    frame = pl.DataFrame(
        {
            "exposure_reference": ["EQ-1"],
            "counterparty_reference": ["CP-1"],
            **{
                name: pl.Series(name, [None], dtype=spec.dtype)
                for name, spec in _EQUITY_INPUT_CONTRACT.items()
            },
        }
    ).lazy()

    # Act
    sealed, _missing, _lossy = seal_lenient(frame, _EQUITY_EDGE)
    surviving = set(sealed.collect_schema().names())

    # Assert
    stripped = sorted(set(_EQUITY_INPUT_CONTRACT) - surviving - set(_DERIVED_KEYS))
    assert stripped == [], (
        f"equity input-contract keys {stripped} are stripped by the loader seal "
        "(not declared on RAW_TABLE_EDGES['equity_exposures']), so every production "
        "row reads their contract default and any branch keyed on them is dead. "
        "Declare the column in EQUITY_EXPOSURE_SCHEMA, or delete the key and the "
        "branch that reads it, or name the upstream step that derives it in "
        "_DERIVED_KEYS."
    )


def test_derived_equity_contract_keys_are_contract_keys_the_loader_does_not_declare() -> None:
    """The exemption list stays honest: no stale entry and no loadable entry."""
    # Arrange
    derived = set(_DERIVED_KEYS)

    # Act
    stale = sorted(derived - set(_EQUITY_INPUT_CONTRACT))
    loadable = sorted(derived & set(_EQUITY_EDGE.columns))

    # Assert
    assert stale == [], f"_DERIVED_KEYS names {stale}, which are no longer contract keys"
    assert loadable == [], (
        f"_DERIVED_KEYS names {loadable}, which the loader edge declares -- they are "
        "loaded, not derived, so the survival check must cover them"
    )
