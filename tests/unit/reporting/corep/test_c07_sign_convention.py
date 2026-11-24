"""COREP C 07.00 Annex II §1.3 "(-)" sign-convention tests (item R2).

Split from tests/unit/reporting/corep/test_c07.py so the largest reporting
test file does not accrete further (arch_check max_reporting_test_file_loc
ratchet). Covers the CRR supporting-factor adjustment columns 0216/0217,
which are labelled "(-)" and therefore reported as negative magnitudes so
0215 + 0216 + 0217 = 0220 foots under the display convention.
"""

from __future__ import annotations

import pytest

from tests.fixtures.recon_ledger import LedgerShimCorepGenerator
from tests.unit.reporting.corep._builders import _get_total_row
from tests.unit.reporting.corep.test_c07 import _sa_results_with_supporting_factors


class TestC0700SupportingFactorSignConvention:
    """Annex II §1.3 "(-)" sign convention on the CRR C 07.00 SF columns."""

    def test_0216_and_0217_are_negative(self) -> None:
        """Cols 0216/0217 (the "(-)"-labelled SF adjustments) are reported negative."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_supporting_factors(), framework="CRR")
        total = _get_total_row(bundle.c07_00["corporate"])
        # SME: (1000-761.9) + (2000-1523.8) = 714.3 -> -714.3; Infra: (5000-3750) = 1250 -> -1250.
        assert total["0216"][0] == pytest.approx(-714.3)
        assert total["0217"][0] == pytest.approx(-1250.0)
        assert total["0216"][0] <= 0.0
        assert total["0217"][0] <= 0.0

    def test_0215_plus_0216_plus_0217_foots_to_0220(self) -> None:
        """0220 = 0215 + 0216 + 0217 (SF adjustments already signed per Annex II §1.3).

        0215 (pre-SF RWEA) = Σ rwa_pre_factor = 1000+2000+5000+3200 = 11200;
        0220 (post-SF RWEA) = Σ rwa_final     = 761.9+1523.8+3750+3200 = 9235.7;
        so 11200 + (-714.3) + (-1250) = 9235.7.
        """
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_supporting_factors(), framework="CRR")
        total = _get_total_row(bundle.c07_00["corporate"])
        pre = total["0215"][0]
        sme_adj = total["0216"][0]
        infra_adj = total["0217"][0]
        post = total["0220"][0]
        assert pre == pytest.approx(11200.0)
        assert post == pytest.approx(9235.7)
        assert pre + sme_adj + infra_adj == pytest.approx(post)
