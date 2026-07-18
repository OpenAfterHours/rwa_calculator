"""COREP OF 02.01 output-floor comparison tests.

Split from tests/unit/test_corep.py (Phase 7 Sn), then rewritten 2026-07-14 when the
partition defect was fixed (docs/plans/c07-ccr-derivatives.md §4 D3). The old bodies
here PINNED that defect — ``test_modelled_rwa`` literally documented column 0010 as
"the sum of rwa_pre_floor for **all exposures**", which is the bug in prose.

The semantics these tests now hold the engine to (PS1/26 Annex II):

- **The columns PARTITION the book.** Column 0010 is "portfolios where RWAs are
  calculated using MODELLED approaches only" (``foundation_irb``, ``advanced_irb``,
  ``slotting`` — Art. 153(5) slotting is an IRB-chapter approach); column 0020 is the
  COMPLEMENT (standardised, SA-CCR, equity, and any unrecognised label). Column 0030
  (U-TREA) = 0010 + 0020, which reconstitutes the complete portfolio ONLY because the
  two columns partition it.
- **Both partition columns sum ``rwa_pre_floor``.** Column 0020 must NOT sum ``sa_rwa``:
  that carrier is null on equity rows, so the standardised side would silently drop
  equity's RWA. Column 0040 (S-TREA) sums ``sa_rwa`` over the row's WHOLE population.
- **The rows partition by risk type.** 0010 = credit risk excluding CCR, 0020 = CCR
  (``risk_type`` in {CCR_DERIVATIVE, CCR_SFT}), 0080 = the whole book = their sum.
  Rows 0030-0070 stay NULL — out of scope for a credit-risk calculator, and null is
  not the same claim as 0.0.

The acceptance oracle on the real portfolios is
tests/acceptance/reporting/test_of02_output_floor.py.
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.reporting.corep.generator import COREPGenerator, COREPTemplateBundle
from rwa_calc.reporting.corep.templates import (
    OF_02_01_COLUMN_REFS,
    OF_02_01_COLUMNS,
    OF_02_01_ROW_SECTIONS,
)

# The four data columns.
_COLS: tuple[str, ...] = ("0010", "0020", "0030", "0040")


def _b31_results_with_floor() -> pl.LazyFrame:
    """Mixed IRB/SA results with rwa_pre_floor and sa_rwa. No ``risk_type`` column.

    Three modelled exposures (E1/E2 F-IRB, E4 A-IRB) and one standardised (E3), so the
    partition is:

        col 0010 (modelled)     = 500 + 1500 + 900 = 2900
        col 0020 (standardised) = 100                    (E3's rwa_pre_floor)
        col 0030 (U-TREA)       = 3000                   (== the whole book)
        col 0040 (S-TREA)       = 700 + 1400 + 100 + 1050 = 3250

    The absent ``risk_type`` column is deliberate: it pins that a book with no CCR
    carrier lands entirely on row 0010 rather than dropping out of both rows.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["E1", "E2", "E3", "E4"],
            "approach_applied": [
                "foundation_irb",
                "foundation_irb",
                "standardised",
                "advanced_irb",
            ],
            "exposure_class": ["corporate", "corporate", "institution", "corporate"],
            "ead_final": [1000.0, 2000.0, 500.0, 1500.0],
            "risk_weight": [0.5, 0.75, 0.2, 0.6],
            "rwa_final": [500.0, 1500.0, 100.0, 900.0],
            "rwa_pre_floor": [500.0, 1500.0, 100.0, 900.0],
            "sa_rwa": [700.0, 1400.0, 100.0, 1050.0],
        }
    )


def _b31_results_floor_binding() -> pl.LazyFrame:
    """All-IRB results where modelled RWA < SA RWA (the floor is binding).

    100% modelled, so the standardised partition (col 0020) is an empty 0.0 and
    U-TREA (1100) < S-TREA (2200).
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["E1", "E2"],
            "approach_applied": ["foundation_irb", "foundation_irb"],
            "exposure_class": ["corporate", "corporate"],
            "ead_final": [1000.0, 2000.0],
            "risk_weight": [0.3, 0.4],
            "rwa_final": [300.0, 800.0],
            "rwa_pre_floor": [300.0, 800.0],
            "sa_rwa": [600.0, 1600.0],
        }
    )


def _sa_only_results_with_floor_cols() -> pl.LazyFrame:
    """A 100%-standardised book: no IRB model, no slotting.

    The modelled partition (col 0010) must be EMPTY, and U-TREA == S-TREA == 1100, so
    the floor cannot bind.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["E1", "E2"],
            "approach_applied": ["standardised", "standardised"],
            "exposure_class": ["corporate", "institution"],
            "ead_final": [1000.0, 500.0],
            "risk_weight": [1.0, 0.2],
            "rwa_final": [1000.0, 100.0],
            "rwa_pre_floor": [1000.0, 100.0],
            "sa_rwa": [1000.0, 100.0],
        }
    )


def _b31_results_all_approaches() -> pl.LazyFrame:
    """One exposure per approach label, including equity and an unrecognised label.

        F1  foundation_irb            500   modelled
        A1  advanced_irb              900   modelled
        SL1 slotting                  700   modelled      (Art. 153(5) — IRB chapter)
        SA1 standardised              100   standardised
        EQ1 equity                    250   standardised  (sa_rwa is NULL — see below)
        XX1 <unrecognised>             50   standardised  (the COMPLEMENT, not an
                                                           allow-list)

        col 0010 (modelled)     = 500 + 900 + 700       = 2100
        col 0020 (standardised) = 100 + 250 + 50        =  400
        col 0030 (U-TREA)       = 2500                  (== the whole book)
        col 0040 (S-TREA)       = 700+1050+700+100+50   = 2600 (equity's null skipped)

    EQ1 carries a NULL ``sa_rwa`` on purpose: equity bypasses the SA calculator, so the
    carrier is genuinely null in production. A ``Sum(sa_rwa)`` on column 0020 would book
    the standardised side at 150 and lose equity's 250 of RWA out of U-TREA entirely.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["F1", "A1", "SL1", "SA1", "EQ1", "XX1"],
            "approach_applied": [
                "foundation_irb",
                "advanced_irb",
                "slotting",
                "standardised",
                "equity",
                "some_unrecognised_approach",
            ],
            "exposure_class": [
                "corporate",
                "corporate",
                "specialised_lending",
                "institution",
                "equity",
                "corporate",
            ],
            "ead_final": [1000.0, 1500.0, 1000.0, 500.0, 1000.0, 100.0],
            "rwa_final": [500.0, 900.0, 700.0, 100.0, 250.0, 50.0],
            "rwa_pre_floor": [500.0, 900.0, 700.0, 100.0, 250.0, 50.0],
            "sa_rwa": [700.0, 1050.0, 700.0, 100.0, None, 50.0],
        }
    )


def _b31_results_with_ccr() -> pl.LazyFrame:
    """A book with both risk-type sides, and both approach sides on each.

        E1  foundation_irb   full_risk        500   non-CCR modelled
        E2  standardised     full_risk        100   non-CCR standardised
        D1  standardised_ccr CCR_DERIVATIVE   300   CCR standardised
        D2  advanced_irb     CCR_DERIVATIVE   400   CCR modelled (IRB RW on SA-CCR EAD)
        S1  standardised_ccr CCR_SFT          200   CCR standardised

    Row 0010 (excl. CCR): 0010=500, 0020=100, 0030= 600, 0040= 800
    Row 0020 (CCR):       0010=400, 0020=500, 0030= 900, 0040= 950
    Row 0080 (Total):     0010=900, 0020=600, 0030=1500, 0040=1750

    The CCR legs are keyed by ``risk_type``, never by the approach label: under Basel 3.1
    they carry ``standardised_ccr`` and under CRR plain ``standardised``, so an
    approach-based rule would no-op exactly where it matters.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": ["E1", "E2", "D1", "D2", "S1"],
            "approach_applied": [
                "foundation_irb",
                "standardised",
                "standardised_ccr",
                "advanced_irb",
                "standardised_ccr",
            ],
            "risk_type": [
                "full_risk",
                "full_risk",
                "CCR_DERIVATIVE",
                "CCR_DERIVATIVE",
                "CCR_SFT",
            ],
            "exposure_class": [
                "corporate",
                "institution",
                "institution",
                "corporate",
                "institution",
            ],
            "ead_final": [1000.0, 500.0, 600.0, 800.0, 400.0],
            "rwa_final": [500.0, 100.0, 300.0, 400.0, 200.0],
            "rwa_pre_floor": [500.0, 100.0, 300.0, 400.0, 200.0],
            "sa_rwa": [700.0, 100.0, 300.0, 450.0, 200.0],
        }
    )


def _of_02_01(results: pl.LazyFrame) -> pl.DataFrame:
    """Generate OF 02.01 under BASEL_3_1 and assert it exists."""
    bundle = COREPGenerator().generate_from_lazyframe(results, framework="BASEL_3_1")
    assert bundle.of_02_01 is not None
    return bundle.of_02_01


def _row(sheet: pl.DataFrame, ref: str) -> dict[str, float | str | None]:
    """The single OF 02.01 row with the given ``row_ref``, as a dict of cells."""
    rows = sheet.filter(pl.col("row_ref") == ref)
    assert rows.height == 1, f"expected exactly one row {ref}, got {rows.height}"
    return rows.row(0, named=True)


def _num(row: dict[str, float | str | None], col: str) -> float:
    """The cell at ``col``, asserted numeric — a reported figure, not a label or a null."""
    value = row[col]
    assert isinstance(value, int | float), f"cell {col} must be numeric, got {value!r}"
    return float(value)


class TestOF0201TemplateDefinitions:
    """Template structure definitions for OF 02.01."""

    def test_column_count(self) -> None:
        """OF 02.01 has exactly 4 columns."""
        assert len(OF_02_01_COLUMNS) == 4

    def test_column_refs(self) -> None:
        """Column refs are 0010, 0020, 0030, 0040."""
        assert OF_02_01_COLUMN_REFS == ["0010", "0020", "0030", "0040"]

    def test_column_names(self) -> None:
        """Columns have correct regulatory names."""
        names = [c.name for c in OF_02_01_COLUMNS]
        assert "modelled approaches" in names[0].lower()
        assert "standardised approaches" in names[1].lower()
        assert "U-TREA" in names[2]
        assert "S-TREA" in names[3]

    def test_column_groups(self) -> None:
        """First two columns are Comparison, last two are Output Floor."""
        groups = [c.group for c in OF_02_01_COLUMNS]
        assert groups == ["Comparison", "Comparison", "Output Floor", "Output Floor"]

    def test_row_count(self) -> None:
        """OF 02.01 has exactly 8 rows (risk types) in 1 section."""
        assert len(OF_02_01_ROW_SECTIONS) == 1
        assert len(OF_02_01_ROW_SECTIONS[0].rows) == 8

    def test_row_refs(self) -> None:
        """Row refs are 0010-0080."""
        refs = [r.ref for r in OF_02_01_ROW_SECTIONS[0].rows]
        assert refs == ["0010", "0020", "0030", "0040", "0050", "0060", "0070", "0080"]

    def test_credit_risk_row_name(self) -> None:
        """First row is 'Credit risk (excluding CCR)'."""
        assert OF_02_01_ROW_SECTIONS[0].rows[0].name == "Credit risk (excluding CCR)"

    def test_total_row_name(self) -> None:
        """Last row is 'Total'."""
        assert OF_02_01_ROW_SECTIONS[0].rows[-1].name == "Total"

    def test_section_name(self) -> None:
        """Section is named 'Risk Type Breakdown'."""
        assert OF_02_01_ROW_SECTIONS[0].name == "Risk Type Breakdown"


class TestOF0201Generation:
    """OF 02.01 generation from pipeline results."""

    def test_generated_under_b31(self) -> None:
        """OF 02.01 is generated when framework is BASEL_3_1."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="BASEL_3_1")
        assert bundle.of_02_01 is not None

    def test_none_under_crr(self) -> None:
        """OF 02.01 is None when framework is CRR (no output floor)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="CRR")
        assert bundle.of_02_01 is None

    def test_none_without_floor_columns(self) -> None:
        """OF 02.01 is None when rwa_pre_floor/sa_rwa columns are absent."""
        gen = COREPGenerator()
        results = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["standardised"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
                "rwa_final": [500.0],
            }
        )
        bundle = gen.generate_from_lazyframe(results, framework="BASEL_3_1")
        assert bundle.of_02_01 is None

    def test_error_logged_when_skipped(self) -> None:
        """Error message added when OF 02.01 is skipped (missing columns)."""
        gen = COREPGenerator()
        results = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["standardised"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
                "rwa_final": [500.0],
            }
        )
        bundle = gen.generate_from_lazyframe(results, framework="BASEL_3_1")
        assert any("OF 02.01 skipped" in e for e in bundle.errors)

    def test_is_dataframe(self) -> None:
        """OF 02.01 output is a Polars DataFrame."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="BASEL_3_1")
        assert isinstance(bundle.of_02_01, pl.DataFrame)

    def test_row_count(self) -> None:
        """OF 02.01 has 8 rows (one per risk type)."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="BASEL_3_1")
        assert bundle.of_02_01 is not None
        assert len(bundle.of_02_01) == 8

    def test_column_structure(self) -> None:
        """DataFrame has row_ref, row_name, and 4 data columns."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="BASEL_3_1")
        assert bundle.of_02_01 is not None
        cols = set(bundle.of_02_01.columns)
        assert "row_ref" in cols
        assert "row_name" in cols
        assert "0010" in cols
        assert "0020" in cols
        assert "0030" in cols
        assert "0040" in cols


class TestOF0201CreditRiskRow:
    """OF 02.01 row 0010 — Credit risk (excluding CCR)."""

    def test_modelled_rwa(self) -> None:
        """Col 0010 = sum of rwa_pre_floor over the MODELLED partition only.

        "Portfolios where RWAs are calculated using modelled approaches only"
        (Annex II) — F-IRB, A-IRB and slotting. The standardised exposure E3 is NOT
        in this column; summing the whole book here is the D3 defect.
        """
        cr_row = _row(_of_02_01(_b31_results_with_floor()), "0010")
        # E1=500 (F-IRB) + E2=1500 (F-IRB) + E4=900 (A-IRB) → 2900. E3 (SA) excluded.
        assert cr_row["0010"] == pytest.approx(2900.0)

    def test_standardised_partition_rwa(self) -> None:
        """Col 0020 = sum of rwa_pre_floor over the COMPLEMENT of the modelled set.

        Not ``Sum(sa_rwa)`` (which would be 3250 over the whole book) and not an SA
        allow-list — the complement, so nothing can fall into neither column.
        """
        cr_row = _row(_of_02_01(_b31_results_with_floor()), "0010")
        # Only E3 is non-modelled: rwa_pre_floor = 100 (its sa_rwa happens to match).
        assert cr_row["0020"] == pytest.approx(100.0)

    def test_u_trea_is_sum_of_modelled_and_standardised(self) -> None:
        """P2.42: Col 0030 (U-TREA) == col 0010 + col 0020 == the complete portfolio.

        Annex II defines col 0030 as "a sum of 0010 and 0020, i.e. the complete current
        portfolio" — it only reconstitutes the portfolio because the two columns
        PARTITION it. The old expectation (6250 = 3000 modelled + 3250 SA) was
        U-TREA + S-TREA: the whole book counted twice, on two different carriers.

        Arrange: four exposures, whole-book rwa_pre_floor = 3000.
        Act:     generate OF 02.01 under BASEL_3_1.
        Assert:  col 0030 == col 0010 + col 0020 == 3000.0 == the whole book.
        """
        # Arrange / Act
        cr_row = _row(_of_02_01(_b31_results_with_floor()), "0010")

        # Assert
        # col 0010 (modelled)     = 500 + 1500 + 900 = 2900
        # col 0020 (standardised) = 100
        # col 0030 (U-TREA)       = 3000 = sum(rwa_pre_floor) over every row
        assert cr_row["0030"] == pytest.approx(_num(cr_row, "0010") + _num(cr_row, "0020")), (
            "U-TREA (col 0030) must equal col 0010 + col 0020 per Annex II §1.3.2"
        )
        assert cr_row["0030"] == pytest.approx(3000.0), (
            "U-TREA must be the complete portfolio's pre-floor RWA, counted once"
        )

    def test_s_trea_equals_standardised_column_only_on_an_sa_only_book(self) -> None:
        """Col 0040 (S-TREA) == col 0020 only where the whole book is standardised.

        They are different quantities: col 0040 is Σ ``sa_rwa`` over the row's WHOLE
        population (S-TREA — what the book would weigh under the SA), while col 0020 is
        Σ ``rwa_pre_floor`` over the standardised PARTITION. On a mixed book the modelled
        exposures carry an sa_rwa that col 0020 must not see; the old blanket identity
        assertion was the double-count in disguise.
        """
        mixed = _row(_of_02_01(_b31_results_with_floor()), "0010")
        assert mixed["0040"] == pytest.approx(3250.0)  # 700+1400+100+1050, whole book
        assert mixed["0040"] != pytest.approx(mixed["0020"])  # 3250 vs 100

        sa_only = _row(_of_02_01(_sa_only_results_with_floor_cols()), "0010")
        assert sa_only["0040"] == pytest.approx(sa_only["0020"])  # 1100 == 1100

    def test_floor_binding_scenario(self) -> None:
        """Floor binding on a 100%-modelled book: U-TREA (1100) < S-TREA (2200).

        The floor compares U-TREA (col 0030) against S-TREA (col 0040) — not col 0010
        against col 0020, which are two halves of one portfolio. With no standardised
        exposures the standardised partition is a populated zero.
        """
        cr_row = _row(_of_02_01(_b31_results_floor_binding()), "0010")
        assert cr_row["0010"] == pytest.approx(1100.0)  # 300+800, all F-IRB
        assert cr_row["0020"] == pytest.approx(0.0)  # nothing outside the modelled set
        assert cr_row["0030"] == pytest.approx(1100.0)  # U-TREA
        assert cr_row["0040"] == pytest.approx(2200.0)  # S-TREA: 600+1600
        assert _num(cr_row, "0030") < _num(cr_row, "0040"), "the floor binds when U-TREA < S-TREA"

    def test_sa_only_portfolio(self) -> None:
        """A 100%-standardised book reports ZERO modelled RWA, and U-TREA == S-TREA.

        This is the sharpest statement of the partition. The book holds two SA exposures
        and no IRB model and no slotting, so column 0010 ("modelled approaches only")
        must be 0.0 — the old test asserted 1100 of "modelled" RWA against a book with
        no models. With every exposure standardised the comparison is degenerate:
        U-TREA (col 0030) == S-TREA (col 0040), so the floor can never bind.
        """
        cr_row = _row(_of_02_01(_sa_only_results_with_floor_cols()), "0010")
        assert cr_row["0010"] == pytest.approx(0.0), "no models → no modelled RWA"
        assert cr_row["0020"] == pytest.approx(1100.0)  # 1000+100, the whole book
        assert cr_row["0030"] == pytest.approx(1100.0)  # U-TREA
        assert cr_row["0040"] == pytest.approx(1100.0)  # S-TREA
        assert cr_row["0030"] == pytest.approx(cr_row["0040"]), "the floor cannot bind"


class TestOF0201Partition:
    """The completeness invariant: modelled + standardised == the whole book."""

    def test_mixed_book_partition_is_complete(self) -> None:
        """Col 0010 + col 0020 == Σ rwa_pre_floor over EVERY ledger row.

        The invariant that would have caught D3: no exposure may be counted twice (the
        defect: both columns summed the whole book) and none may be dropped (the trap an
        SA allow-list would create — an unrecognised approach label falling into neither
        column and silently understating U-TREA).

        Arrange: a book spanning F-IRB, A-IRB, slotting, SA, equity and an unrecognised
                 approach label — whole-book rwa_pre_floor = 2500.
        Act:     generate OF 02.01 under BASEL_3_1.
        Assert:  row 0080's modelled + standardised columns sum to exactly 2500.
        """
        # Arrange
        results = _b31_results_all_approaches()
        whole_book = float(results.collect()["rwa_pre_floor"].sum())

        # Act
        total = _row(_of_02_01(results), "0080")

        # Assert
        assert whole_book == pytest.approx(2500.0)
        assert _num(total, "0010") + _num(total, "0020") == pytest.approx(whole_book)
        assert total["0030"] == pytest.approx(whole_book)

    def test_slotting_is_modelled(self) -> None:
        """Supervisory slotting (Art. 153(5)) belongs in col 0010, not col 0020.

        Slotting is an IRB-chapter approach reported in the CR IRB templates, so it is
        modelled for the output-floor comparison.
        """
        total = _row(_of_02_01(_b31_results_all_approaches()), "0080")
        # F1=500 (F-IRB) + A1=900 (A-IRB) + SL1=700 (slotting) → 2100.
        assert total["0010"] == pytest.approx(2100.0)

    def test_equity_rwa_is_not_dropped_from_the_standardised_column(self) -> None:
        """Equity's RWA reaches col 0020 even though its ``sa_rwa`` is NULL.

        Equity bypasses the SA calculator, so ``sa_rwa`` is null on equity rows. Column
        0020 therefore sums ``rwa_pre_floor``, not ``sa_rwa`` — a ``Sum(sa_rwa)`` would
        book the standardised side at 150 (100 SA + 50 unrecognised) and lose equity's
        250 of RWA out of U-TREA altogether.
        """
        total = _row(_of_02_01(_b31_results_all_approaches()), "0080")
        # SA1=100 + EQ1=250 (sa_rwa null) + XX1=50 → 400.
        assert total["0020"] == pytest.approx(400.0)
        assert total["0020"] != pytest.approx(150.0), "equity's rwa_pre_floor was dropped"

    def test_unrecognised_approach_falls_into_the_standardised_column(self) -> None:
        """An approach label the template does not know lands in col 0020, not nowhere.

        Column 0020 is the COMPLEMENT of the modelled set, never an allow-list: a new or
        misspelled label must understate nothing. XX1 (50) is in neither the modelled set
        nor any SA enum, and it still reaches U-TREA.
        """
        results = _b31_results_all_approaches()
        total = _row(_of_02_01(results), "0080")
        modelled_only = results.filter(
            pl.col("approach_applied").is_in(["foundation_irb", "advanced_irb", "slotting"])
        )
        modelled_total = float(modelled_only.collect()["rwa_pre_floor"].sum())

        assert total["0010"] == pytest.approx(modelled_total)  # 2100
        assert total["0020"] == pytest.approx(2500.0 - modelled_total)  # the complement

    def test_s_trea_spans_both_partitions(self) -> None:
        """Col 0040 (S-TREA) sums ``sa_rwa`` over the row's whole population.

        S-TREA is what the book would weigh under the standardised approach — modelled
        exposures included. It is not the standardised partition (col 0020), and it skips
        equity's null carrier.
        """
        total = _row(_of_02_01(_b31_results_all_approaches()), "0080")
        # 700 + 1050 + 700 + 100 + (equity: null) + 50 → 2600.
        assert total["0040"] == pytest.approx(2600.0)


class TestOF0201RiskTypeRows:
    """The row axis: 0010 (credit risk excl. CCR) and 0020 (CCR) partition the book."""

    def test_credit_risk_row_excludes_ccr(self) -> None:
        """Row 0010 ("Credit risk EXCLUDING CCR") carries no CCR leg.

        The row is keyed by ``risk_type``, never by the approach label: under Basel 3.1
        the CCR legs carry ``standardised_ccr`` and under CRR plain ``standardised``.
        """
        cr_row = _row(_of_02_01(_b31_results_with_ccr()), "0010")
        assert cr_row["0010"] == pytest.approx(500.0)  # E1 (F-IRB) only
        assert cr_row["0020"] == pytest.approx(100.0)  # E2 (SA) only
        assert cr_row["0030"] == pytest.approx(600.0)
        assert cr_row["0040"] == pytest.approx(800.0)  # 700 + 100

    def test_ccr_row_carries_the_ccr_legs(self) -> None:
        """Row 0020 ("Counterparty credit risk") carries CCR_DERIVATIVE + CCR_SFT.

        And it partitions by approach exactly as row 0010 does: D2 is a derivative
        risk-weighted under A-IRB (an IRB RW on an SA-CCR EAD), so it is modelled RWA.
        """
        ccr_row = _row(_of_02_01(_b31_results_with_ccr()), "0020")
        assert ccr_row["0010"] == pytest.approx(400.0)  # D2, A-IRB
        assert ccr_row["0020"] == pytest.approx(500.0)  # D1 (300) + S1 (200), SA-CCR
        assert ccr_row["0030"] == pytest.approx(900.0)  # U-TREA of the CCR book
        assert ccr_row["0040"] == pytest.approx(950.0)  # 300 + 450 + 200

    def test_row_axis_foots_to_the_total(self) -> None:
        """Row 0010 + row 0020 == row 0080, in every column.

        The Total row is the sum of the two populated rows, not a copy of row 0010.
        """
        sheet = _of_02_01(_b31_results_with_ccr())
        non_ccr, ccr, total = (_row(sheet, ref) for ref in ("0010", "0020", "0080"))
        for col in _COLS:
            assert _num(non_ccr, col) + _num(ccr, col) == pytest.approx(total[col]), (
                f"OF 02.01 does not foot on column {col}"
            )

    def test_ccr_row_is_zero_not_null_when_the_book_has_no_ccr(self) -> None:
        """Row 0020 is a populated 0.0 on a book with no CCR — a claim we can make.

        "This book holds no counterparty credit risk" is not the same statement as "we do
        not report counterparty credit risk" (which is what rows 0030-0070 say with null).
        """
        ccr_row = _row(_of_02_01(_b31_results_with_floor()), "0020")
        for col in _COLS:
            assert ccr_row[col] == pytest.approx(0.0), f"row 0020 column {col} must be 0.0"


class TestOF0201TotalRow:
    """OF 02.01 row 0080 — Total."""

    def test_total_equals_credit_risk_when_book_has_no_ccr(self) -> None:
        """Total row equals the credit-risk row when the book carries no CCR leg.

        Not because the Total is a copy of row 0010 — because row 0020 is empty here.
        See ``TestOF0201RiskTypeRows::test_row_axis_foots_to_the_total`` for the general
        case.
        """
        sheet = _of_02_01(_b31_results_with_floor())
        cr_row, total_row = _row(sheet, "0010"), _row(sheet, "0080")
        for col_ref in _COLS:
            assert total_row[col_ref] == cr_row[col_ref]

    def test_total_modelled_rwa(self) -> None:
        """Total row col 0010 is the whole book's MODELLED rwa_pre_floor."""
        total_row = _row(_of_02_01(_b31_results_with_floor()), "0080")
        # E1=500 + E2=1500 + E4=900 → 2900. E3 (SA) is in col 0020, not here.
        assert total_row["0010"] == pytest.approx(2900.0)

    def test_total_row_name(self) -> None:
        """Total row is named 'Total'."""
        total_row = _row(_of_02_01(_b31_results_with_floor()), "0080")
        assert total_row["row_name"] == "Total"


class TestOF0201NullRows:
    """OF 02.01 rows 0030-0070 — out-of-scope risk types (null).

    Row 0020 (CCR) is NOT in this set: it is a populated row (see
    ``TestOF0201RiskTypeRows``). A credit-risk calculator has nothing to say about CVA,
    securitisation, market, operational or other risk — null means "not reported here",
    which is a different claim from 0.0.
    """

    @pytest.mark.parametrize(
        "row_ref,row_name",
        [
            ("0030", "Credit valuation adjustment risk"),
            ("0040", "Securitisation positions in the non-trading book"),
            ("0050", "Market risk"),
            ("0060", "Operational risk"),
            ("0070", "Other"),
        ],
    )
    def test_out_of_scope_row_is_null(self, row_ref: str, row_name: str) -> None:
        """Out-of-scope risk types have null values in all data columns."""
        row = _row(_of_02_01(_b31_results_with_floor()), row_ref)
        assert row["row_name"] == row_name
        for col_ref in _COLS:
            assert row[col_ref] is None

    def test_null_rows_present(self) -> None:
        """All 5 out-of-scope rows are present."""
        sheet = _of_02_01(_b31_results_with_floor())
        null_refs = {"0030", "0040", "0050", "0060", "0070"}
        actual_refs = set(sheet["row_ref"].to_list())
        assert null_refs.issubset(actual_refs)


class TestOF0201EdgeCases:
    """Edge cases and data type verification for OF 02.01."""

    def test_empty_results(self) -> None:
        """Empty LazyFrame with floor columns produces zero-valued OF 02.01."""
        gen = COREPGenerator()
        results = pl.LazyFrame(
            schema={
                "exposure_reference": pl.String,
                "approach_applied": pl.String,
                "exposure_class": pl.String,
                "ead_final": pl.Float64,
                "rwa_final": pl.Float64,
                "rwa_pre_floor": pl.Float64,
                "sa_rwa": pl.Float64,
            }
        )
        bundle = gen.generate_from_lazyframe(results, framework="BASEL_3_1")
        assert bundle.of_02_01 is not None
        cr_row = _row(bundle.of_02_01, "0010")
        for col_ref in _COLS:
            assert cr_row[col_ref] == pytest.approx(0.0)

    def test_null_rwa_values_treated_as_zero(self) -> None:
        """Null rwa_pre_floor/sa_rwa values are treated as 0 on both partitions.

        E1 (modelled) has a null rwa_pre_floor and E2 (standardised) a null sa_rwa, so
        each carrier's null is exercised on the side that reads it.
        """
        gen = COREPGenerator()
        results = pl.LazyFrame(
            {
                "exposure_reference": ["E1", "E2", "E3"],
                "approach_applied": ["foundation_irb", "standardised", "advanced_irb"],
                "exposure_class": ["corporate", "institution", "corporate"],
                "ead_final": [1000.0, 500.0, 1500.0],
                "rwa_final": [None, 100.0, 900.0],
                "rwa_pre_floor": [None, 100.0, 900.0],
                "sa_rwa": [700.0, None, 1050.0],
            }
        )
        bundle = gen.generate_from_lazyframe(results, framework="BASEL_3_1")
        assert bundle.of_02_01 is not None
        cr_row = _row(bundle.of_02_01, "0010")
        assert cr_row["0010"] == pytest.approx(900.0)  # E1's null → 0, E3 = 900
        assert cr_row["0020"] == pytest.approx(100.0)  # E2
        assert cr_row["0030"] == pytest.approx(1000.0)
        assert cr_row["0040"] == pytest.approx(1750.0)  # 700 + (null → 0) + 1050

    def test_data_columns_are_float64(self) -> None:
        """All 4 data columns are Float64 type."""
        sheet = _of_02_01(_b31_results_with_floor())
        for col_ref in _COLS:
            assert sheet[col_ref].dtype == pl.Float64

    def test_row_ref_and_name_are_string(self) -> None:
        """row_ref and row_name columns are String type."""
        sheet = _of_02_01(_b31_results_with_floor())
        assert sheet["row_ref"].dtype == pl.String
        assert sheet["row_name"].dtype == pl.String

    def test_no_errors_on_success(self) -> None:
        """No OF 02.01 errors when generation succeeds."""
        gen = COREPGenerator()
        bundle = gen.generate_from_lazyframe(_b31_results_with_floor(), framework="BASEL_3_1")
        assert not any("OF 02.01" in e for e in bundle.errors)

    def test_bundle_field_none_by_default(self) -> None:
        """COREPTemplateBundle.of_02_01 defaults to None."""
        bundle = COREPTemplateBundle(c07_00={}, c08_01={}, c08_02={})
        assert bundle.of_02_01 is None

    def test_large_rwa_values(self) -> None:
        """OF 02.01 handles large RWA values without precision loss, on both partitions."""
        gen = COREPGenerator()
        results = pl.LazyFrame(
            {
                "exposure_reference": ["E1", "E2"],
                "approach_applied": ["foundation_irb", "standardised"],
                "exposure_class": ["corporate", "institution"],
                "ead_final": [1e12, 6e11],
                "rwa_final": [5e11, 3e11],
                "rwa_pre_floor": [5e11, 3e11],
                "sa_rwa": [7e11, 3e11],
            }
        )
        bundle = gen.generate_from_lazyframe(results, framework="BASEL_3_1")
        assert bundle.of_02_01 is not None
        cr_row = _row(bundle.of_02_01, "0010")
        assert cr_row["0010"] == pytest.approx(5e11)  # modelled
        assert cr_row["0020"] == pytest.approx(3e11)  # standardised
        assert cr_row["0030"] == pytest.approx(8e11)  # U-TREA
        assert cr_row["0040"] == pytest.approx(1e12)  # S-TREA: 7e11 + 3e11

    def test_row_order_preserved(self) -> None:
        """Rows are in the correct order: 0010, 0020, ..., 0080."""
        sheet = _of_02_01(_b31_results_with_floor())
        refs = sheet["row_ref"].to_list()
        assert refs == ["0010", "0020", "0030", "0040", "0050", "0060", "0070", "0080"]

    def test_only_rwa_pre_floor_missing(self) -> None:
        """OF 02.01 is None when only rwa_pre_floor is missing."""
        gen = COREPGenerator()
        results = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["standardised"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
                "rwa_final": [500.0],
                "sa_rwa": [500.0],
            }
        )
        bundle = gen.generate_from_lazyframe(results, framework="BASEL_3_1")
        assert bundle.of_02_01 is None

    def test_only_sa_rwa_missing(self) -> None:
        """OF 02.01 is None when only sa_rwa is missing."""
        gen = COREPGenerator()
        results = pl.LazyFrame(
            {
                "exposure_reference": ["E1"],
                "approach_applied": ["standardised"],
                "exposure_class": ["corporate"],
                "ead_final": [1000.0],
                "rwa_final": [500.0],
                "rwa_pre_floor": [500.0],
            }
        )
        bundle = gen.generate_from_lazyframe(results, framework="BASEL_3_1")
        assert bundle.of_02_01 is None
