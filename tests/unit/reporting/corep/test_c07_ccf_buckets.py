"""COREP C 07.00 / OF 07.00 CCF-bucket columns 0160-0190.

Split out of ``test_c07.py`` (2026-08-01) when the bucket semantics were
corrected — the per-template file convention Phase 7 Sn established, alongside
``test_c07_ccr.py`` / ``test_c07_provisions.py`` / ``test_c07_sign_convention.py``
/ ``test_c07_gross_side_carriers.py``.

What these columns mean: COREP Annex II heads the block "BREAKDOWN OF THE FULLY
ADJUSTED EXPOSURE VALUE OF OFF-BALANCE SHEET ITEMS BY CONVERSION FACTORS". Each
cell therefore carries the **pre-conversion** value of the off-balance-sheet
items in that bucket; col 0200 is what survives conversion. The two are tied by
the supervisory identities these tests exist to keep evaluable:

- ``v6364_m`` (and the EBA ``v1659_m`` / ``v1661_m``):
  ``{c0150} = {c0160}+{c0170}+{c0180}+{c0190}`` on the off-balance-sheet row.
- ``boe_b0471`` (Basel 3.1): ``{c0200} = {c0150} - 0.9*{c0160} - 0.8*{c0170}
  - 0.6*{c0171} - 0.5*{c0180}``, each coefficient being (1 - CCF).

Three defects were fixed together on 2026-08-01, all of which these tests pin:

1. The cells bucketed on ``ccf_applied``, a name no pipeline run produces (the
   sealed aggregator exit carries ``ccf``), so every real submission published
   structurally-null CCF columns.
2. They summed the POST-conversion ``ead_final``. Fixing only the name would
   have populated the columns and still failed every rule written over them; the
   cells now sum ``reporting_gross_off_bs``, the same carrier col 0010 sums on
   the off-side, so 0150 decomposes into the buckets by construction.
3. The off-side narrowing was gated on ``bs_type``, which the aggregator never
   seals, so on the ledger path it silently never applied — and a drawn loan
   carries ``ccf = 0.0``, which IS a real CRR bucket (Annex I LR 0% -> col
   0160). It is now gated on ``_has_bs_side``.

The end-to-end oracle over a real pipeline run (both regimes, both identities)
lives in ``tests/acceptance/reporting/test_reporting_offbs_golden.py``.

References:
- COREP Annex II, C 07.00 cols 0160-0190; PRA PS1/26 Annex II (OF 07.00)
- CRR Art. 111(1) + Annex I paras 1-4; PRA PS1/26 Art. 111(1) Table A1 Rows 1-7
"""

from __future__ import annotations

import polars as pl
import pytest

from tests.fixtures.recon_ledger import LedgerShimCorepGenerator
from tests.unit.reporting.corep._builders import _get_total_row, _sa_results


def _sa_results_with_ccf() -> pl.LazyFrame:
    """SA results with off-BS exposures across the four CRR CCF buckets.

    Internally consistent by construction: ``ead_final`` is exactly
    ``undrawn_amount x ccf_applied`` per row, so the pre-conversion values these
    tests assert (1000/2000/3000/500) and the post-conversion EADs they must NOT
    assert (0/400/1500/500) are visibly different numbers.

    ``SA_ON_1`` is the on-balance-sheet control: 5000 drawn, no CCF. It must
    never reach a bucket.
    """
    return pl.LazyFrame(
        {
            "exposure_reference": [
                "SA_ON_1",
                "SA_OFF_0",
                "SA_OFF_20",
                "SA_OFF_50",
                "SA_OFF_100",
            ],
            "approach_applied": ["standardised"] * 5,
            "exposure_class": ["corporate"] * 5,
            "drawn_amount": [5000.0, 0.0, 0.0, 0.0, 0.0],
            "undrawn_amount": [0.0, 1000.0, 2000.0, 3000.0, 500.0],
            "ead_final": [5000.0, 0.0, 400.0, 1500.0, 500.0],
            "rwa_final": [5000.0, 0.0, 400.0, 1500.0, 500.0],
            "risk_weight": [1.0, 1.0, 1.0, 1.0, 1.0],
            "scra_provision_amount": [0.0, 0.0, 0.0, 0.0, 0.0],
            "gcra_provision_amount": [0.0, 0.0, 0.0, 0.0, 0.0],
            "sa_cqs": [3, 3, 3, 3, 3],
            "counterparty_reference": ["CP_A", "CP_B", "CP_C", "CP_D", "CP_E"],
            "bs_type": ["ONB", "OFB", "OFB", "OFB", "OFB"],
            "ccf_applied": [None, 0.0, 0.2, 0.5, 1.0],
        }
    )


class TestCCFBreakdown:
    """Cols 0160-0190 report the pre-conversion off-BS value per CCF bucket."""

    def test_c07_ccf_columns_populated(self) -> None:
        """Each bucket carries the undrawn amount of its items, not their EAD.

        Arrange: five SA rows, one on-balance and one per CRR bucket.
        Act:     generate C 07.00.
        Assert:  each bucket equals the undrawn in it (1000/2000/3000/500), NOT
                 the post-conversion EAD (0/400/1500/500).
        """
        # Arrange + Act
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_ccf())

        # Assert
        corp = _get_total_row(bundle.c07_00["corporate"])
        assert corp["0160"][0] == pytest.approx(1000.0)  # 0% bucket
        assert corp["0170"][0] == pytest.approx(2000.0)  # 20% bucket
        assert corp["0180"][0] == pytest.approx(3000.0)  # 50% bucket
        assert corp["0190"][0] == pytest.approx(500.0)  # 100% bucket

    def test_c07_ccf_excludes_on_balance_sheet_rows(self) -> None:
        """A drawn (ONB) row never lands in a CCF bucket.

        Not a numeric coincidence — an on-balance row carries ccf 0.0, which is a
        REAL bucket under CRR (Annex I LR 0% -> col 0160), so only the ``c07_bs``
        narrowing keeps it out. This is the gate that silently stopped applying
        on the ledger path because it asked for ``bs_type``.

        Arrange: the five-row frame, whose ONB row is 5000 drawn.
        Act:     generate C 07.00.
        Assert:  col 0160 carries SA_OFF_0's 1000 alone — the 5000 is absent.
        """
        # Arrange + Act
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_ccf())

        # Assert
        corp = _get_total_row(bundle.c07_00["corporate"])
        assert corp["0160"][0] == pytest.approx(1000.0)

    def test_c07_ccf_sum_equals_off_bs_gross(self) -> None:
        """The ``v6364_m`` identity: the buckets foot to the off-BS gross.

        Arrange: the five-row frame (off-BS gross 1000+2000+3000+500).
        Act:     generate C 07.00 and sum the bucket columns.
        Assert:  6500 — the ONB row's 0.0 contributes nothing.
        """
        # Arrange + Act
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_ccf())

        # Assert
        corp = _get_total_row(bundle.c07_00["corporate"])
        ccf_sum = (
            (corp["0160"][0] or 0.0)
            + (corp["0170"][0] or 0.0)
            + (corp["0180"][0] or 0.0)
            + (corp["0190"][0] or 0.0)
        )
        assert ccf_sum == pytest.approx(6500.0)

    def test_c07_ccf_null_without_column(self) -> None:
        """CCF columns render structurally null when no applied-CCF carrier exists.

        The carrier ladder is ``("ccf", "ccf_applied")``; a frame carrying
        neither leaves the cells blank rather than reporting a false 0.0.

        Arrange: an SA frame with no CCF carrier at all.
        Act:     generate C 07.00.
        Assert:  the bucket cells are null.
        """
        # Arrange + Act
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results())

        # Assert
        corp = _get_total_row(bundle.c07_00["corporate"])
        assert corp["0160"][0] is None
        assert corp["0170"][0] is None

    def test_b31_ccf_includes_40pct_bucket(self) -> None:
        """Basel 3.1 adds col 0171 (40%) and moves col 0160 to the 10% UCC rate.

        PRA PS1/26 Art. 111(1) Table A1: Row 5 "other commitments" 40% is new and
        Row 7 UCC moves 0% -> 10%, so the CRR four-bucket axis becomes five.

        Arrange: two off-BS rows at the two Basel-3.1-only rates.
        Act:     generate OF 07.00.
        Assert:  0171 exists and both buckets carry pre-conversion undrawn.
        """
        # Arrange
        data = pl.LazyFrame(
            {
                "exposure_reference": ["SA_OFF_10", "SA_OFF_40"],
                "approach_applied": ["standardised", "standardised"],
                "exposure_class": ["corporate", "corporate"],
                "drawn_amount": [0.0, 0.0],
                "undrawn_amount": [1000.0, 2000.0],
                "ead_final": [100.0, 800.0],
                "rwa_final": [100.0, 800.0],
                "risk_weight": [1.0, 1.0],
                "sa_cqs": [3, 3],
                "counterparty_reference": ["CP_A", "CP_B"],
                "bs_type": ["OFB", "OFB"],
                "ccf_applied": [0.1, 0.4],
            }
        )

        # Act
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(data, framework="BASEL_3_1")

        # Assert
        corp = _get_total_row(bundle.c07_00["corporate"])
        assert "0171" in corp.columns
        assert corp["0160"][0] == pytest.approx(1000.0)  # 10% bucket (EAD would be 100)
        assert corp["0171"][0] == pytest.approx(2000.0)  # 40% bucket (EAD would be 800)

    def test_c07_ccf_on_rw_section_rows(self) -> None:
        """The breakdown also resolves inside the risk-weight section rows.

        Arrange: the five-row frame, every row at RW 100%.
        Act:     generate C 07.00 and read the "100%" band row.
        Assert:  its 20% bucket matches the total row's.
        """
        # Arrange + Act
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_ccf())

        # Assert
        corp = bundle.c07_00["corporate"]
        rw_100 = corp.filter(pl.col("row_name") == "100%")
        if len(rw_100) > 0:
            assert rw_100["0170"][0] == pytest.approx(2000.0)
