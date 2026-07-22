"""COREP C 07.00 gross-side-carrier tests (R-gross-side-carriers).

Split into its own file rather than added to tests/unit/reporting/corep/test_c07.py
so the largest reporting test file does not accrete further (arch_check
max_reporting_test_file_loc ratchet).

Root cause: col 0010 (original exposure) is SafeSum(drawn_amount,
undrawn_amount) — it drops a contingent's nominal amount and a loan's
accrued interest entirely (CRR Art. 166 requires both in original exposure).
The "of which" on/off-BS rows (0070/0080) key on the ``c07_bs`` ladder, which
recognises ``exposure_type`` "loan" (on) and "facility"/"contingent" (off)
but never "facility_undrawn" — the unified pipeline emits "facility_undrawn",
not the dead "facility" value — so a facility_undrawn leg is dropped from
row 0080 (off-BS) entirely while its EAD stays in the class total.

See .claude/state/gross-side-carriers-spec.md.
"""

from __future__ import annotations

import polars as pl
import pytest

from tests.fixtures.recon_ledger import LedgerShimCorepGenerator
from tests.unit.reporting.corep._builders import _get_total_row


def _mixed_gross_side_carrier_results() -> pl.LazyFrame:
    """One corporate class: a loan (with accrued interest), a contingent,
    and a facility_undrawn commitment."""
    return pl.LazyFrame(
        {
            "exposure_reference": ["LN1", "CO1", "FU1"],
            "counterparty_reference": ["CP1", "CP2", "CP3"],
            "exposure_class": ["corporate"] * 3,
            "approach_applied": ["standardised"] * 3,
            "exposure_type": ["loan", "contingent", "facility_undrawn"],
            "risk_weight": [1.0, 1.0, 1.0],
            "ead_final": [5000.0, 1000.0, 3000.0],
            "rwa_final": [5000.0, 1000.0, 3000.0],
            "drawn_amount": [5000.0, 0.0, 0.0],
            "interest": [200.0, 0.0, 0.0],
            "nominal_amount": [0.0, 2000.0, 4000.0],
            "undrawn_amount": [0.0, 0.0, 4000.0],
            "scra_provision_amount": [0.0, 0.0, 0.0],
            "gcra_provision_amount": [0.0, 0.0, 0.0],
            "ccf_applied": [None, 0.5, 0.75],
        }
    )


class TestC0700GrossSideCarriers:
    """R-gross-side-carriers: col 0010 (original exposure) must count a
    contingent's nominal amount and a loan's accrued interest (today's
    SafeSum(drawn, undrawn) drops both — a deliberate golden mover, CRR
    Art. 166); the "of which" on/off-BS rows (0070/0080) must not drop a
    facility_undrawn leg.
    """

    def test_col_0010_includes_contingent_nominal_and_interest(self) -> None:
        """Total row (0010) = on-BS (loan drawn+interest) + off-BS (contingent
        nominal + facility_undrawn headroom) = 5200 + 6000 = 11200 (today:
        drawn 5000 + undrawn 4000 = 9000, dropping the 200 interest and the
        2000 contingent nominal)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_mixed_gross_side_carrier_results())
        corp = _get_total_row(bundle.c07_00["corporate"])
        assert corp["0010"][0] == pytest.approx(11200.0)

    def test_row_0080_off_bs_includes_facility_undrawn(self) -> None:
        """Row 0080 (off-BS exposure value, col 0200) must include the
        facility_undrawn leg's EAD alongside the contingent's (today it is
        dropped: 1000, not 4000); row 0070 (on-BS) is unaffected (5000, the
        loan only)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_mixed_gross_side_carrier_results())
        corp = bundle.c07_00["corporate"]
        on_row = corp.filter(pl.col("row_ref") == "0070")
        off_row = corp.filter(pl.col("row_ref") == "0080")
        assert on_row["0200"][0] == pytest.approx(5000.0)
        assert off_row["0200"][0] == pytest.approx(4000.0)  # contingent 1000 + FU 3000

    def test_col_0010_facility_alias_leg_counted_once(self) -> None:
        """A legacy ``exposure_type="facility"`` leg must count its gross
        EXACTLY ONCE in col 0010 (Amendment 2: "facility" populates the
        sealed side carriers, so the C07-local ``c07_ccr_gross`` term — which
        restores original exposure for the non-credit-risk/CCR legs C 07.00
        keeps but the side carriers null out — must itself null out for
        "facility", not double-count it). 0010 = loan (5000) + facility
        (2000, the undrawn headroom) = 7000, NOT 9000 (5000 + 2000 off-BS
        carrier + 2000 c07_ccr_gross — the same leg counted on both terms)."""
        gen = LedgerShimCorepGenerator()
        data = pl.LazyFrame(
            {
                "exposure_reference": ["LN1", "FA1"],
                "counterparty_reference": ["CP1", "CP2"],
                "exposure_class": ["corporate"] * 2,
                "approach_applied": ["standardised"] * 2,
                "exposure_type": ["loan", "facility"],
                "risk_weight": [1.0, 1.0],
                "ead_final": [5000.0, 1000.0],
                "rwa_final": [5000.0, 1000.0],
                "drawn_amount": [5000.0, 0.0],
                "interest": [0.0, 0.0],
                "nominal_amount": [0.0, 0.0],
                "undrawn_amount": [0.0, 2000.0],
                "scra_provision_amount": [0.0, 0.0],
                "gcra_provision_amount": [0.0, 0.0],
                "ccf_applied": [None, 0.5],
            }
        )
        bundle = gen.generate_from_lazyframe(data)
        corp = _get_total_row(bundle.c07_00["corporate"])
        assert corp["0010"][0] == pytest.approx(7000.0)
