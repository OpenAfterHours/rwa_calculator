"""
C4b — a second opinion on what each money cell is made of.

Pipeline position:
    portfolio -> PipelineOrchestrator -> sealed aggregator-exit ledger
        -> Pillar3Generator (the engine's answer)
        -> cell_rederivation.toml (an independently authored answer)
        -> these assertions

What this proves that nothing else does:
``reporting/lineage.py`` re-runs the generator's own ``RowPredicate`` by design,
so a wrong ``CellSpec`` produces a number that is self-consistent,
lineage-explicable, golden-matching and rule-passing — and still wrong. Both
sides here read the SAME sealed ledger, so any difference can only be a
disagreement about which rows and which carrier a cell is made of. That is the
defect class the row-axis property cannot reach: a cell whose population is
complete but whose carrier or scale is wrong.

Scope is bounded on purpose. C 02.00, C 07.00 and C 08.01 are NOT covered here
— see the module-level note in the final report — and the data file's
``meta.limits`` records what a green run does not settle.

References:
- UK Pillar 3 Annex II, Template UK OV1; CRR Art. 92(1)/(3), Art. 438(d)
- docs/plans/independent-validation-system.md §C4b
"""

from __future__ import annotations

import logging

import polars as pl
import pytest

from tests.conformance.rederive import load_derivations
from tests.properties.portfolios import ExposureSpec, pillar3_bundle, results_df

logger = logging.getLogger(__name__)

#: Money agreement tolerance. The two sides sum the same Float64 column over the
#: same rows in a different order, so only float reassociation separates them.
MONEY_TOLERANCE = 0.005

REGIMES: tuple[str, ...] = ("CRR", "B31")

#: A portfolio that lights every OV1 credit-risk row: standardised, F-IRB
#: (internal PD, no own LGD), A-IRB (own LGD), slotting (specialised lending
#: with a PD but no own LGD) and equity. Deliberately small — twelve obligors —
#: because the assertion is about which rows and which carrier a cell is made
#: of, not about scale.
PORTFOLIO: tuple[ExposureSpec, ...] = (
    ExposureSpec(entity_type="corporate", drawn=4_000_000.0, external_cqs=3),
    ExposureSpec(entity_type="institution", drawn=2_500_000.0, external_cqs=2),
    ExposureSpec(entity_type="sovereign", drawn=6_000_000.0, external_cqs=1),
    ExposureSpec(entity_type="individual", drawn=600_000.0, external_cqs=None),
    ExposureSpec(entity_type="corporate", drawn=3_000_000.0, internal_pd=0.015),
    ExposureSpec(entity_type="institution", drawn=1_800_000.0, internal_pd=0.004),
    ExposureSpec(entity_type="corporate", drawn=5_000_000.0, internal_pd=0.02, firm_lgd=0.35),
    ExposureSpec(entity_type="individual", drawn=500_000.0, internal_pd=0.03, firm_lgd=0.25),
    ExposureSpec(
        entity_type="corporate",
        drawn=7_000_000.0,
        internal_pd=0.01,
        is_specialised_lending=True,
        sl_type="project_finance",
    ),
    ExposureSpec(entity_type="corporate", drawn=1_200_000.0, off_bs_nominal=900_000.0),
    ExposureSpec(entity_type="corporate", drawn=0.0, off_bs_nominal=2_000_000.0),
    ExposureSpec(entity_type="equity", drawn=1_500_000.0, external_cqs=None),
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ledgers() -> dict[str, pl.DataFrame]:
    """regime -> the collected sealed aggregator-exit ledger."""
    return {regime: results_df(PORTFOLIO, regime) for regime in REGIMES}


@pytest.fixture(scope="module")
def templates() -> dict[str, dict[str, pl.DataFrame]]:
    """regime -> template name -> the generated frame."""
    out: dict[str, dict[str, pl.DataFrame]] = {}
    for regime in REGIMES:
        bundle = pillar3_bundle(PORTFOLIO, regime)
        out[regime] = {"OV1": bundle.ov1} if bundle.ov1 is not None else {}
    return out


# ---------------------------------------------------------------------------
# Anti-vacuity — the portfolio must reach the cells before agreement means anything
# ---------------------------------------------------------------------------


def test_the_portfolio_reaches_every_approach_the_cells_partition(ledgers) -> None:
    """Every OV1 approach row carries non-zero RWEA under at least one regime.

    Arrange: the sealed ledger for both regimes.
    Act: sum ``rwa_final`` per origin approach.
    Assert: standardised, F-IRB, A-IRB and slotting are all non-zero somewhere.
    A cell nothing populates agrees with any re-derivation at 0.00, which is the
    ``.claude/LESSONS.md`` C2 trap in miniature — measure the crossing amount
    before trusting green.
    """
    reached: dict[str, float] = {}
    for regime, ledger in ledgers.items():
        totals = (
            ledger.group_by("reporting_approach_origin")
            .agg(pl.col("rwa_final").fill_null(0.0).sum().alias("rwa"))
            .to_dicts()
        )
        for entry in totals:
            key = entry["reporting_approach_origin"]
            reached[key] = max(reached.get(key, 0.0), abs(float(entry["rwa"])))
        logger.info("C4b %s approach RWEA: %s", regime, totals)
    for approach in ("standardised", "foundation_irb", "advanced_irb", "slotting"):
        assert reached.get(approach, 0.0) > 0.0, (
            f"no {approach} RWEA in either regime — the OV1 cells for it would "
            f"agree at 0.00 without asserting anything: {reached}"
        )


def test_every_authored_cell_is_reachable(templates) -> None:
    """Each re-derived cell names a row and column the generated template has.

    A cell whose row_ref does not exist would be read as 0.0 by any lenient
    accessor and would pass silently; this makes the address itself an assertion.
    """
    missing: list[str] = []
    for cell in load_derivations():
        for regime in cell.regimes:
            frame = templates[regime].get(cell.template)
            if frame is None:
                missing.append(f"{cell.id}: {regime} emitted no {cell.template}")
                continue
            if frame.filter(pl.col("row_ref") == cell.row).height == 0:
                missing.append(f"{cell.id}: {regime} {cell.template} has no row {cell.row}")
            elif cell.column not in frame.columns:
                missing.append(f"{cell.id}: {regime} {cell.template} has no column {cell.column}")
    assert not missing, "unreachable cell addresses:\n  " + "\n  ".join(missing)


# ---------------------------------------------------------------------------
# The second opinion
# ---------------------------------------------------------------------------


def _cell_ids() -> list[str]:
    return [cell.id for cell in load_derivations()]


@pytest.mark.parametrize("cell_id", _cell_ids())
def test_generated_cell_matches_the_independent_rederivation(
    ledgers, templates, cell_id: str
) -> None:
    """The generator and the independently-authored predicate agree on one cell.

    Arrange: the sealed ledger and the generated template, per regime.
    Act: rebuild the cell from ``cell_rederivation.toml`` — a separately
    authored predicate, carrier and scale sourced from the Annex II text.
    Assert: the two agree to float-reassociation tolerance. They read the same
    ledger, so a difference is a disagreement about the cell's DEFINITION.
    """
    cell = next(c for c in load_derivations() if c.id == cell_id)
    differences: list[str] = []
    for regime in cell.regimes:
        frame = templates[regime][cell.template]
        published = _published(frame, cell.row, cell.column)
        rederived = cell.evaluate(ledgers[regime])
        if abs(published - rederived) > MONEY_TOLERANCE:
            differences.append(
                f"{regime} {cell.template} r{cell.row}/{cell.column}: "
                f"generated {published:,.2f} vs re-derived {rederived:,.2f} "
                f"(delta {published - rederived:,.2f})"
            )
    assert not differences, f"{cell.id} [{cell.citation}]:\n  " + "\n  ".join(differences)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "A Basel 3.1 equity leg is CALCULATED and then dropped. Measured on the portfolio "
        "below: LN011, EAD 1,500,000, reporting_rw 2.5 (the PS1/26 Art. 133 250% equity risk "
        "weight), sa_rwa 3,750,000 — and rwa_final NULL. The same leg under CRR carries "
        "rwa_final 1,500,000 at 100%. Because rwa_final is the carrier every credit-risk "
        "template and OV1 row sums, 3,750,000 of RWEA and 300,000 of own funds requirement "
        "(CRR Art. 92(1)) leave the Basel 3.1 submission with no error, no null cell and no "
        "failing published rule — the row simply is not there. The engine is believed wrong: "
        "a leg whose risk weight the engine has resolved must reach rwa_final, and null is "
        "not a defensible response to an input shape it otherwise processed. Caveat recorded "
        "honestly: the canonical input for an equity holding is the dedicated "
        "equity_exposures table, and this leg reaches the equity approach from the loans "
        "table, so the population may be narrower than every equity holding."
    ),
)
def test_every_equity_leg_carries_its_rwea_to_rwa_final(ledgers) -> None:
    """An equity leg the engine risk-weighted reaches the carrier the templates sum.

    Arrange: the sealed ledger for both regimes.
    Act: select the legs whose origin approach is ``equity``.
    Assert: each has a non-null ``rwa_final``. This is the ``.claude/LESSONS.md``
    B4 shape — assert what should be there, not only what is — at the one place
    where a null and a genuine zero are indistinguishable downstream.
    """
    dropped: list[str] = []
    for regime, ledger in ledgers.items():
        equity = ledger.filter(pl.col("reporting_approach_origin") == "equity")
        for row in equity.iter_rows(named=True):
            if row["rwa_final"] is None:
                dropped.append(
                    f"{regime} {row['exposure_reference']}: ead_final="
                    f"{row['ead_final']:,.2f} reporting_rw={row['reporting_rw']} "
                    f"sa_rwa={row['sa_rwa']:,.2f} rwa_final=None"
                )
    assert not dropped, "equity RWEA never reaches rwa_final:\n  " + "\n  ".join(dropped)


def test_own_funds_columns_are_exactly_eight_percent_of_their_rwea(templates) -> None:
    """Every OV1 column-c cell is 8% of the column-a cell on the SAME row.

    Arrange: the generated OV1 frames.
    Act: compare column c against 0.08 x column a, row by row.
    Assert: they agree. The instruction is "own fund requirements corresponding
    to the RWEAs for the different risk categories" (CRR Art. 92(1)), so any row
    where the two are unrelated has taken its own-funds figure from a different
    population than its RWEA figure — the E2 shape, one row wide.
    """
    breaks: list[str] = []
    for regime in REGIMES:
        frame = templates[regime].get("OV1")
        if frame is None:
            continue
        for row in frame.iter_rows(named=True):
            rwea, own_funds = row.get("a"), row.get("c")
            if rwea is None or own_funds is None:
                continue
            if abs(float(own_funds) - 0.08 * float(rwea)) > MONEY_TOLERANCE:
                breaks.append(
                    f"{regime} r{row['row_ref']}: c={float(own_funds):,.2f} "
                    f"vs 0.08 x a={0.08 * float(rwea):,.2f}"
                )
    assert not breaks, "OV1 own-funds columns not 8% of their RWEA:\n  " + "\n  ".join(breaks)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _published(frame: pl.DataFrame, row_ref: str, column: str) -> float:
    """One generated cell, with a null read as 0.00.

    Reading a null as zero is safe HERE only because
    ``test_every_authored_cell_is_reachable`` has already proved the address
    exists — otherwise a missing row and a genuine zero would be the same value.
    """
    row = frame.filter(pl.col("row_ref") == row_ref)
    value = row[column][0] if row.height else None
    return float(value) if value is not None else 0.0
