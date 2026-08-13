"""
Pillar 3 OV1 — the "of which" block must PARTITION row 1, and the equity split it
depends on is keyed on the equity METHOD, never on the approach label.

Pipeline position:
    reporting portfolio (rich | absent-method) -> PipelineOrchestrator
        -> Pillar3Generator (OV1, CR10) + COREPGenerator (C 02.00)

The defect this file drives out (P1.332):

``reporting/pillar3/ov1.py`` ``_APPROACH_REFS`` keys the of-which rows on the
approach LABEL, and admits ``"equity"`` into BOTH ``"2": ("standardised",
"equity")`` and ``"UK4a": ("equity",)``. Under CRR every equity leg is therefore
counted twice and the block does not partition row 1 — measured on the shipped
CRR golden, rows 2+3+4+UK4a+5 sum to 148,411,467.29 against a row 1 of
145,511,467.29, over by exactly UK 4a's 2,900,000.00.

Verbatim from the published instructions
(``docs/assets/crr-pillar3-risk-weighted-exposure-instructions-leverage-ratio.pdf``
pp. 0-1): UK 4a is "equities under the simple risk weighted approach **in
accordance with Article 155(2) CRR**", and rows 3 and 5 each carry an explicit
"excluding the RWEAs disclosed in row 4 ... and in row UK 4a" carve-out — which
only makes sense if the of-which rows are mutually exclusive and foot to row 1.
Art. 155(2) is IRB Chapter 3; Art. 133 is SA Chapter 2. The two populations are
disjoint, so the correct rule SPLITS BOTH WAYS and the two limbs need OPPOSITE
corrections:

- ``equity_method == "irb_simple"`` (Art. 155(2)) -> **UK 4a only**, and must NOT
  be in row 2. That is the rich book's leg: listed, RW 290%, EAD 1,000,000 ->
  2,900,000. Its UK 4a cell is the one that SURVIVES; its row 2 is the one that
  MOVES (19,128,450.00 -> 16,228,450.00).
- ``equity_method == "sa"``, **or the column absent/null** -> **row 2 only**, and
  must NOT be in UK 4a. That is the absent-method book's leg (an equity obligor
  on the loans table, so the equity calculator never seals a method): row 2 keeps
  its 9,850,000.00 and UK 4a falls 1,500,000.00 -> 0.00.

Both legs are pinned ABSOLUTELY and on the SAME book (``.claude/LESSONS.md`` B5,
second form): a test that only asserts "the of-which rows partition row 1" is
satisfied just as well by zeroing UK 4a on the rich book — moving the cell that
should stay and leaving the one that should move.

The independent cross-checks — neither can drift with ``ov1.py``:

    OV1 row 2   == C 02.00 r0060 ("Of which: Standardised Approach")
    OV1 row UK4a == C 02.00 r0420 ("Equity IRB")
    OV1 row UK4a == CR10 equity sheet row 4 ("Total") column e (RWEA)

``reporting/corep/c02.py`` and ``reporting/pillar3/cr10.py`` ALREADY key equity on
the sealed ``equity_method`` (``_EQUITY_IRB_METHODS = ("irb_simple", "pd_lgd")``
through an absent-tolerant ``.is_in(...).fill_null(False)``), which is why they
are a second opinion rather than an echo: on the rich CRR book C 02.00 reports
r0060 = 16,228,450.00 and r0420 = 2,900,000.00 today, against an OV1 that
contradicts both.

Basel 3.1 is the control and NOTHING there may move: the UKB OV1 row list emits
no UK 4a row at all, and PS1/26 Art. 147A stamps every equity leg ``sa``, so the
CRR re-split is arithmetically unreachable under B31. That is a recorded
one-regime gap in the ``.claude/LESSONS.md`` C7 sense — the B31 limb CANNOT be
reddened, so it is kept parametrised as an invariance control rather than as
evidence.

References:
- CRR Part 8 Art. 438; Art. 133 (SA equity); Art. 155(2) (IRB simple
  risk-weighted equity — the UK 4a population)
- UK Pillar 3 Annex II, Template UK OV1, rows 1-5 and UK 4a
- PS1/26 Art. 147A (no IRB equity under Basel 3.1 — why UK 4a has no UKB twin)
- tests/conformance/test_cell_rederivation.py
  ::test_the_of_which_rows_partition_the_credit_risk_total (the xfail(strict)
  partition pin this fix turns green; its marker AND its ``reason=`` text must be
  deleted with the fix)
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl
import pytest
from tests.acceptance.reporting.test_reporting_golden import _REGIMES as _RICH_REGIMES
from tests.fixtures.reporting_portfolio import build_reporting_bundle
from tests.properties import portfolios as props

from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.pillar3.generator import Pillar3Generator

# Phase 2 parity convention: group-by float sums are not bit-reproducible.
_REL = 1e-9
_ABS = 1e-6

# The of-which block of row 1, from the published instruction — NOT from
# ``ov1.py``'s ``_APPROACH_REFS`` (.claude/LESSONS.md B3: a test that shares
# production's assumption validates nothing). UK 4a is CRR-only, so the refs are
# filtered on presence rather than asserted into existence.
_OF_WHICH: tuple[str, ...] = ("2", "3", "4", "UK4a", "5")

_ROW_SA = "2"
_ROW_EQUITY_SIMPLE = "UK4a"

# The sealed ``equity_method`` values that mean "IRB, therefore UK 4a"
# (domain.enums.EquityApproach; the same tuple c02.py binds row 0420 on).
_IRB_EQUITY_METHODS: tuple[str, ...] = ("irb_simple", "pd_lgd")

# The C 02.00 rows OV1's two equity-bearing cells must agree with.
_C02_SA_TOTAL = "0060"
_C02_EQUITY_IRB = "0420"

# A frozen copy of the C4b conformance portfolio (tests/conformance/
# test_cell_rederivation.py::PORTFOLIO). Copied rather than imported so the
# expected values below cannot be invalidated by an edit to another suite's
# portfolio — and because its equity leg is the point: ``entity_type="equity"``
# on the LOANS table reaches the reporting classes with origin approach
# ``equity`` but never passes the equity calculator, so the sealed ledger carries
# NO ``equity_method`` column at all. That is the absent-column limb, and without
# it the fix ships with only one of its two populations tested.
_ABSENT_METHOD_PORTFOLIO: tuple[props.ExposureSpec, ...] = (
    props.ExposureSpec(entity_type="corporate", drawn=4_000_000.0, external_cqs=3),
    props.ExposureSpec(entity_type="institution", drawn=2_500_000.0, external_cqs=2),
    props.ExposureSpec(entity_type="sovereign", drawn=6_000_000.0, external_cqs=1),
    props.ExposureSpec(entity_type="individual", drawn=600_000.0, external_cqs=None),
    props.ExposureSpec(
        entity_type="corporate",
        drawn=3_000_000.0,
        internal_pd=0.015,
        off_bs_nominal=1_500_000.0,
    ),
    props.ExposureSpec(entity_type="institution", drawn=1_800_000.0, internal_pd=0.004),
    props.ExposureSpec(entity_type="corporate", drawn=5_000_000.0, internal_pd=0.02, firm_lgd=0.35),
    props.ExposureSpec(entity_type="individual", drawn=500_000.0, internal_pd=0.03, firm_lgd=0.25),
    props.ExposureSpec(
        entity_type="corporate",
        drawn=7_000_000.0,
        internal_pd=0.01,
        is_specialised_lending=True,
        sl_type="project_finance",
    ),
    props.ExposureSpec(entity_type="corporate", drawn=1_200_000.0, off_bs_nominal=900_000.0),
    props.ExposureSpec(entity_type="corporate", drawn=0.0, off_bs_nominal=2_000_000.0),
    props.ExposureSpec(entity_type="equity", drawn=1_500_000.0, external_cqs=None),
    props.ExposureSpec(entity_type="corporate", drawn=2_000_000.0, internal_pd=0.004),
)

# (portfolio, regime) -> framework string.
_CASES: tuple[tuple[str, str], ...] = (
    ("rich", "crr"),
    ("rich", "b31"),
    ("absent", "crr"),
    ("absent", "b31"),
)
_CRR_CASES: tuple[tuple[str, str], ...] = (("rich", "crr"), ("absent", "crr"))
_FRAMEWORKS: dict[str, str] = {"crr": "CRR", "b31": "BASEL_3_1"}


# =============================================================================
# The oracle — hand-derived expected cells (column a; column c == a x 0.08)
# =============================================================================

# Only the cells P1.332 speaks to are pinned absolutely: row 1 (the parent, which
# must NOT move — this is a disclosure re-split, not a capital change), the two
# equity-bearing of-which cells, and row 29 (the all-risk-type total). Rows 3 / 4
# / 5 are covered by the partition identity below, which is what makes the block
# a partition rather than a set of overlapping subsets.
#
# rich (crr): the equity leg is sealed ``irb_simple`` (Art. 155(2)) at 2,900,000.
#     Row 2 MOVES 19,128,450.00 -> 16,228,450.00; UK 4a SURVIVES at 2,900,000.00.
# absent (crr): the equity leg seals no method at all, so it is Art. 133 SA.
#     Row 2 KEEPS its 9,850,000.00; UK 4a FALLS 1,500,000.00 -> 0.00.
# b31 (both books): no UK 4a row exists and every equity leg is stamped ``sa``,
#     so nothing whatever moves.
_EXPECTED: dict[tuple[str, str], dict[str, float | None]] = {
    ("rich", "crr"): {
        "1": 145_511_467.28986624,
        _ROW_SA: 16_228_450.0,
        _ROW_EQUITY_SIMPLE: 2_900_000.0,
        "29": 145_511_467.28986624,
    },
    ("rich", "b31"): {
        "1": 137_449_963.91362947,
        _ROW_SA: 22_080_833.333333332,
        _ROW_EQUITY_SIMPLE: None,
        "29": 137_449_963.91362947,
    },
    ("absent", "crr"): {
        "1": 30_098_477.213579975,
        _ROW_SA: 9_850_000.0,
        _ROW_EQUITY_SIMPLE: 0.0,
        "29": 30_098_477.213579975,
    },
    ("absent", "b31"): {
        "1": 29_211_099.92781734,
        _ROW_SA: 9_937_500.0,
        _ROW_EQUITY_SIMPLE: None,
        "29": 29_211_099.92781734,
    },
}

# The equity RWEA each book carries at origin. Non-zero is what makes this test
# able to distinguish "correct" from "incomplete" at all — a 0.00 equity leg
# makes both keyings agree (.claude/LESSONS.md C2, in its equity form).
_EQUITY_RWEA: dict[tuple[str, str], float] = {
    ("rich", "crr"): 2_900_000.0,
    ("rich", "b31"): 2_500_000.0,
    ("absent", "crr"): 1_500_000.0,
    ("absent", "b31"): 3_750_000.0,
}


@dataclass(frozen=True)
class _Run:
    """One pipeline run: OV1, the two templates it must agree with, the ledger."""

    ov1: pl.DataFrame
    c02: pl.DataFrame
    cr10_equity: pl.DataFrame | None
    ledger: pl.DataFrame

    def ov1_row(self, ref: str) -> dict[str, float | str | None]:
        return _one_row(self.ov1, ref, "OV1")

    def has_ov1_row(self, ref: str) -> bool:
        return bool(self.ov1.filter(pl.col("row_ref") == ref).height)

    def c02_cell(self, ref: str) -> float:
        rows = self.c02.filter(pl.col("row_ref") == ref)
        assert rows.height == 1, f"expected exactly one C 02.00 row {ref!r}, got {rows.height}"
        value = rows.row(0, named=True)["0010"]
        assert value is not None, f"C 02.00 row {ref} column 0010 is null"
        return float(value)

    def equity_origin(self) -> pl.DataFrame:
        """The ledger legs whose ORIGIN approach is equity."""
        return self.ledger.filter(pl.col("reporting_approach_origin") == "equity")

    def equity_rwea(self) -> float:
        return float(self.equity_origin()["rwa_final"].fill_null(0.0).sum())


@pytest.fixture(scope="module")
def runs() -> dict[tuple[str, str], _Run]:
    """One pipeline run per (portfolio, regime) — four in all."""
    return {case: _run(*case) for case in _CASES}


# =============================================================================
# The defect — both legs, on the same book
# =============================================================================


@pytest.mark.parametrize(("portfolio", "regime"), _CASES)
def test_ov1_equity_rows_report_their_hand_derived_values(
    portfolio: str, regime: str, runs: dict[tuple[str, str], _Run]
) -> None:
    """Row 2, row UK 4a, row 1 and row 29 each equal their hand-derived value.

    The two limbs of the fix pull in OPPOSITE directions and BOTH are pinned here
    on the CRR books, absolutely: the rich book's ``irb_simple`` leg belongs in
    UK 4a and must leave row 2, while the absent-method book's leg belongs in
    row 2 and must leave UK 4a. Asserting only the partition identity would be
    satisfied by zeroing UK 4a everywhere — moving the cell that should stay.

    Row 1 and row 29 are pinned unchanged: this is a re-split of a disclosure,
    not a change of capital.

    Arrange: a reporting portfolio (rich | absent-method), either regime.
    Act:     run the pipeline -> Pillar 3 OV1.
    Assert:  each pinned row's columns a/b/c match the oracle.
    """
    # Arrange + Act
    run = runs[(portfolio, regime)]
    expected = _EXPECTED[(portfolio, regime)]

    # Assert — the premise: an equity leg that actually carries RWEA. Without it
    # both keyings agree and this test cannot distinguish correct from broken.
    assert run.equity_rwea() == pytest.approx(
        _EQUITY_RWEA[(portfolio, regime)], rel=_REL, abs=_ABS
    ), (
        f"[{portfolio}/{regime}] the book must carry "
        f"{_EQUITY_RWEA[(portfolio, regime)]:,.2f} of equity-origin rwa_final for this "
        f"test to mean anything; got {run.equity_rwea():,.2f}."
    )

    for ref, want in expected.items():
        if want is None:
            assert not run.has_ov1_row(ref), (
                f"[{portfolio}/{regime}] OV1 row {ref} must NOT exist under this "
                "framework — the UKB OV1 row list has no UK 4a row, because PS1/26 "
                "Art. 147A removes IRB equity entirely."
            )
            continue
        row = run.ov1_row(ref)
        assert row["b"] is None, (
            f"[{portfolio}/{regime}] OV1 row {ref} column b (RWEAs T-1) must stay null "
            f"— there is no prior period; got {row['b']}."
        )
        assert row["a"] is not None and row["c"] is not None, (
            f"[{portfolio}/{regime}] OV1 row {ref} columns a/c must be POPULATED — this "
            f"book has exposure on that row and null is not the same claim as 0.00 "
            f"(got a={row['a']}, c={row['c']})."
        )
        assert row["a"] == pytest.approx(want, rel=_REL, abs=_ABS), (
            f"[{portfolio}/{regime}] OV1 row {ref} column a: expected {want:,.6f}, got "
            f"{row['a']:,.6f}. UK 4a is 'equities under the simple risk weighted "
            f"approach in accordance with Article 155(2) CRR' and row 2 is the Art. 133 "
            f"SA block — disjoint populations, keyed on the sealed equity_method and "
            f"NEVER on the 'equity' approach label, which belongs to both."
        )
        assert row["c"] == pytest.approx(want * 0.08, rel=_REL, abs=_ABS), (
            f"[{portfolio}/{regime}] OV1 row {ref} column c (own funds) must be 8% of "
            f"column a: expected {want * 0.08:,.6f}, got {row['c']}."
        )


def test_ov1_uk4a_keeps_the_irb_simple_leg_it_alone_may_report(
    runs: dict[tuple[str, str], _Run],
) -> None:
    """The rich CRR book's UK 4a cell SURVIVES at 2,900,000.00 — it does not zero.

    The half of P1.332 an inverted reading gets backwards. This leg is sealed
    ``equity_method == "irb_simple"``, i.e. Art. 155(2) simple risk-weighted IRB
    equity, which is exactly and only what UK 4a discloses. Removing it from
    UK 4a (rather than from row 2) would also make the of-which rows foot to
    row 1, so the partition identity cannot tell the two fixes apart.

    Arrange: the rich reporting portfolio under CRR.
    Act:     run the pipeline -> Pillar 3 OV1 + the sealed ledger.
    Assert:  the leg is sealed irb_simple, and UK 4a reports its whole RWEA.
    """
    # Arrange + Act
    run = runs[("rich", "crr")]
    equity = run.equity_origin()
    uk4a = run.ov1_row(_ROW_EQUITY_SIMPLE)

    # Assert — the premise, then the cell.
    assert "equity_method" in run.ledger.columns, (
        "the rich book's sealed ledger must carry equity_method — it is the "
        "discriminator UK 4a is keyed on (CRR Art. 155(2) vs Art. 133)."
    )
    assert set(equity["equity_method"].to_list()) == {"irb_simple"}, (
        "the rich book's equity leg must be sealed 'irb_simple' for this assertion to "
        f"be about UK 4a at all; got {equity['equity_method'].to_list()}."
    )
    assert uk4a["a"] == pytest.approx(2_900_000.0, rel=_REL, abs=_ABS), (
        f"OV1 row UK 4a reports {uk4a['a']}, but this book's Art. 155(2) simple "
        "risk-weighted equity leg is 2,900,000.00 (listed, RW 290%, EAD 1,000,000). "
        "UK 4a is the cell that SURVIVES the fix; row 2 is the cell that moves."
    )


def test_ov1_row_2_keeps_the_leg_whose_equity_method_is_unsealed(
    runs: dict[tuple[str, str], _Run],
) -> None:
    """An equity leg with NO sealed method is Art. 133 SA: row 2 only, UK 4a 0.00.

    The absent-column limb. An unsealed ``equity_method`` is not evidence of IRB
    treatment, and C 02.00 already resolves it that way — ``_EQUITY_IRB_METHODS``
    is matched through ``.is_in(...).fill_null(False)``, so a null (or an absent
    column) reports as SA. Without this case the fix ships with the limb that
    covers every equity leg the equity calculator never touched untested.

    Arrange: the absent-method portfolio under CRR.
    Act:     run the pipeline -> Pillar 3 OV1 + the sealed ledger.
    Assert:  no IRB method is sealed; row 2 keeps the leg; UK 4a is a hard 0.00.
    """
    # Arrange + Act
    run = runs[("absent", "crr")]
    equity = run.equity_origin()
    sealed = (
        set(equity["equity_method"].to_list()) if "equity_method" in run.ledger.columns else set()
    )
    row_2 = run.ov1_row(_ROW_SA)
    uk4a = run.ov1_row(_ROW_EQUITY_SIMPLE)

    # Assert — the premise: nothing on this book proves IRB equity treatment.
    assert equity.height == 1, (
        f"the absent-method book must carry exactly one equity-origin leg, got "
        f"{equity.height} — the whole point of this case is one leg with no method."
    )
    assert not sealed & set(_IRB_EQUITY_METHODS), (
        f"the absent-method book's equity leg must NOT seal an IRB equity method "
        f"({_IRB_EQUITY_METHODS}); got {sealed}. If a method is now sealed, this case "
        "no longer tests the absent/null limb and needs a new fixture, not a new number."
    )
    assert row_2["a"] == pytest.approx(9_850_000.0, rel=_REL, abs=_ABS), (
        f"OV1 row 2 reports {row_2['a']}, but this book's SA block is 9,850,000.00 "
        "INCLUDING its 1,500,000.00 Art. 133 equity leg. An equity leg with no sealed "
        "method is SA equity and belongs in row 2."
    )
    assert uk4a["a"] == pytest.approx(0.0, abs=_ABS), (
        f"OV1 row UK 4a reports {uk4a['a']} on a book whose only equity leg has no "
        "sealed method. UK 4a is Art. 155(2) IRB simple risk-weighted equity only — an "
        "unsealed method is not evidence of IRB treatment, so the cell is a populated "
        "ZERO ('this book has no simple risk-weighted equity'), never the SA leg again."
    )
    assert uk4a["c"] == pytest.approx(0.0, abs=_ABS), (
        f"OV1 row UK 4a column c must be 0.00 alongside its zero RWEA, got {uk4a['c']}."
    )


# =============================================================================
# The conservation the labels promise
# =============================================================================


@pytest.mark.parametrize(("portfolio", "regime"), _CASES)
def test_ov1_of_which_rows_partition_credit_risk(
    portfolio: str, regime: str, runs: dict[tuple[str, str], _Run]
) -> None:
    """Rows 2 + 3 + 4 + UK 4a + 5 == row 1, exactly.

    Rows 2, 3 and 5 each carry the instruction "excluding the RWEAs disclosed in
    row 4 for specialised lending exposures subject to the slotting approach and
    in row UK 4a for equities under the simple risk weighted approach", which
    makes the block a partition of row 1 rather than a set of overlapping
    subsets. A leg counted by TWO of-which rows agrees with both of them
    individually, so only the footing catches it.

    Arrange: a reporting portfolio (rich | absent-method), either regime.
    Act:     run the pipeline -> Pillar 3 OV1.
    Assert:  every present of-which row is populated, and they sum to row 1.
    """
    # Arrange + Act
    run = runs[(portfolio, regime)]
    present = [ref for ref in _OF_WHICH if run.has_ov1_row(ref)]
    parent = run.ov1_row("1")

    # Assert
    assert _ROW_SA in present, (
        f"[{portfolio}/{regime}] OV1 must emit row 2 — a credit-risk book with no "
        "'of which: standardised approach' row discloses nothing at all."
    )
    for col in ("a", "c"):
        cells = [run.ov1_row(ref)[col] for ref in present]
        assert all(cell is not None for cell in cells), (
            f"[{portfolio}/{regime}] OV1 of-which rows {present} column {col} must ALL "
            f"be populated to partition row 1 — a legitimately empty approach reports "
            f"0.00, not null (got {cells})."
        )
        got = sum(float(cell) for cell in cells)  # type: ignore[arg-type]
        assert got == pytest.approx(parent[col], rel=_REL, abs=_ABS), (
            f"[{portfolio}/{regime}] OV1 rows {'+'.join(present)} column {col} sum to "
            f"{got:,.6f}, but row 1 ('Credit risk excluding CCR') reports "
            f"{parent[col]:,.6f} (delta {float(parent[col]) - got:,.6f}). The of-which "
            "block partitions row 1; keying UK 4a on the 'equity' approach label — "
            "which row 2 also claims — counts every equity leg twice."
        )


# =============================================================================
# The independent cross-checks — a second opinion that cannot drift with ov1.py
# =============================================================================


@pytest.mark.parametrize(("portfolio", "regime"), _CASES)
def test_ov1_row_2_agrees_with_corep_c02_standardised_total(
    portfolio: str, regime: str, runs: dict[tuple[str, str], _Run]
) -> None:
    """OV1 row 2 == C 02.00 r0060 — the same disclosure in two templates.

    C 02.00 row 0060 ("Of which: Standardised Approach") is the SA RWEA total
    INCLUDING SA-method equity, computed in ``reporting/corep/c02.py`` from the
    sealed ``equity_method`` rather than from the approach label. It is therefore
    an independent answer to the question OV1 row 2 asks, and on the rich CRR
    book the two contradict each other today: 16,228,450.00 against 19,128,450.00.

    Arrange: a reporting portfolio (rich | absent-method), either regime.
    Act:     run the pipeline -> Pillar 3 OV1 AND COREP C 02.00, one run.
    Assert:  row 2 column a == C 02.00 r0060, and both == the pinned value.
    """
    # Arrange + Act
    run = runs[(portfolio, regime)]
    row_2 = run.ov1_row(_ROW_SA)["a"]
    c02_sa = run.c02_cell(_C02_SA_TOTAL)
    want = _EXPECTED[(portfolio, regime)][_ROW_SA]

    # Assert
    assert c02_sa == pytest.approx(want, rel=_REL, abs=_ABS), (
        f"[{portfolio}/{regime}] C 02.00 r0060 reports {c02_sa:,.6f} against a pinned "
        f"{want:,.6f} — the cross-check's own side moved, so it is no longer an "
        "independent opinion about OV1 row 2."
    )
    assert row_2 == pytest.approx(c02_sa, rel=_REL, abs=_ABS), (
        f"[{portfolio}/{regime}] OV1 row 2 ('Of which: standardised approach') reports "
        f"{row_2}, but COREP C 02.00 r0060 ('Of which: Standardised Approach') reports "
        f"{c02_sa:,.6f} on the SAME run. C 02.00 keys equity on the sealed "
        "equity_method; OV1 keys it on the 'equity' approach label, which admits an "
        "Art. 155(2) IRB leg into the SA total."
    )


@pytest.mark.parametrize(("portfolio", "regime"), _CRR_CASES)
def test_ov1_uk4a_agrees_with_corep_c02_equity_irb_and_cr10(
    portfolio: str, regime: str, runs: dict[tuple[str, str], _Run]
) -> None:
    """OV1 UK 4a == C 02.00 r0420 == CR10 equity Total — two second opinions.

    Both companion cells are already keyed on the sealed ``equity_method``:
    C 02.00 r0420 ("Equity IRB") through ``_EQUITY_IRB_METHODS``, and CR10's
    equity sheet — the Art. 155(2) simple risk-weighted disclosure itself —
    through ``equity_method == "irb_simple"``. They pin BOTH directions: on the
    rich book they say 2,900,000.00 (so UK 4a may not be zeroed) and on the
    absent-method book they say nothing at all (so UK 4a may not keep an SA leg).

    CR10's equity sheet reports null rather than 0.00 when no leg qualifies —
    "not applicable" rather than "nil" — so a null Total is read as 0.00 here.

    Arrange: a CRR reporting portfolio (rich | absent-method).
    Act:     run the pipeline -> Pillar 3 OV1 + CR10 AND COREP C 02.00, one run.
    Assert:  UK 4a column a == C 02.00 r0420 == CR10 equity row 4 column e.
    """
    # Arrange + Act
    run = runs[(portfolio, regime)]
    uk4a = run.ov1_row(_ROW_EQUITY_SIMPLE)["a"]
    c02_equity_irb = run.c02_cell(_C02_EQUITY_IRB)
    cr10_total = _cr10_equity_rwea(run)

    # Assert
    assert uk4a is not None, (
        f"[{portfolio}/{regime}] OV1 row UK 4a column a is NULL. The row exists under "
        "CRR and reports a populated figure — 0.00 where the book holds no Art. 155(2) "
        "equity — because 'no simple risk-weighted equity' is a claim we can make."
    )
    assert uk4a == pytest.approx(c02_equity_irb, rel=_REL, abs=_ABS), (
        f"[{portfolio}/{regime}] OV1 row UK 4a reports {uk4a}, but COREP C 02.00 r0420 "
        f"('Equity IRB') reports {c02_equity_irb:,.6f} on the SAME run. Both disclose "
        "the IRB-method equity book; C 02.00 keys it on the sealed equity_method."
    )
    assert uk4a == pytest.approx(cr10_total, rel=_REL, abs=_ABS), (
        f"[{portfolio}/{regime}] OV1 row UK 4a reports {uk4a}, but Pillar 3 CR10's "
        f"equity sheet — 'equities under the simple risk weighted approach', the very "
        f"population UK 4a names — totals {cr10_total:,.6f} of RWEA on the same run."
    )


def _run(portfolio: str, regime: str) -> _Run:
    """Run one portfolio through one regime; keep OV1, C 02.00, CR10 and the ledger."""
    framework = _FRAMEWORKS[regime]
    if portfolio == "rich":
        result = PipelineOrchestrator().run_with_data(
            build_reporting_bundle(), _RICH_REGIMES[regime][2]()
        )
    else:
        result = props.run(_ABSENT_METHOD_PORTFOLIO, "CRR" if regime == "crr" else "B31")

    pillar3 = Pillar3Generator().generate_from_lazyframe(result.results, framework=framework)
    corep = COREPGenerator().generate_from_lazyframe(
        result.results,
        framework=framework,
        output_floor_summary=result.output_floor_summary,
    )

    assert pillar3.ov1 is not None, (
        f"[{portfolio}/{regime}] Pillar 3 OV1 was not generated at all — an unemitted "
        "template is the absence failure this file exists to catch, not a passing run."
    )
    assert corep.c_02_00 is not None, (
        f"[{portfolio}/{regime}] COREP C 02.00 was not generated — without it OV1 row 2 "
        "has no independent cross-check and this file degrades to a self-consistency test."
    )
    return _Run(
        ov1=pillar3.ov1,
        c02=corep.c_02_00,
        cr10_equity=(pillar3.cr10 or {}).get("equity"),
        ledger=result.results.collect(),
    )


def _cr10_equity_rwea(run: _Run) -> float:
    """CR10 equity sheet row 4 ("Total") column e (RWEA); null and absent read 0.00."""
    if run.cr10_equity is None:
        return 0.0
    total = _one_row(run.cr10_equity, "4", "CR10 equity")
    return 0.0 if total["e"] is None else float(total["e"])  # type: ignore[arg-type]


def _one_row(sheet: pl.DataFrame, ref: str, label: str) -> dict[str, float | str | None]:
    """The single row of ``sheet`` with the given ``row_ref``, as a dict of cells."""
    rows = sheet.filter(pl.col("row_ref") == ref)
    assert rows.height == 1, f"expected exactly one {label} row {ref!r}, got {rows.height}"
    return rows.row(0, named=True)
