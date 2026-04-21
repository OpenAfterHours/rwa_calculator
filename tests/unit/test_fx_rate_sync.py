"""
Unit tests for fx_rate_sync module.

Covers extract_eur_gbp_rate: the helper that pulls the (EUR, GBP) rate from
a loaded fx_rates LazyFrame so the pipeline can keep config.eur_gbp_rate
consistent with the FX table.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import polars as pl

from rwa_calc.engine.fx_rate_sync import extract_eur_gbp_rate


class TestExtractEurGbpRate:
    """Tests for extract_eur_gbp_rate."""

    def test_returns_rate_when_single_eur_gbp_row(self) -> None:
        fx_rates = pl.LazyFrame(
            {
                "currency_from": ["USD", "EUR", "JPY"],
                "currency_to": ["GBP", "GBP", "GBP"],
                "rate": [0.79, 0.90, 0.0053],
            }
        )

        result = extract_eur_gbp_rate(fx_rates)

        assert result == Decimal("0.9")

    def test_returns_none_when_no_eur_gbp_row(self) -> None:
        fx_rates = pl.LazyFrame(
            {
                "currency_from": ["USD", "JPY"],
                "currency_to": ["GBP", "GBP"],
                "rate": [0.79, 0.0053],
            }
        )

        assert extract_eur_gbp_rate(fx_rates) is None

    def test_returns_none_when_fx_rates_is_none(self) -> None:
        assert extract_eur_gbp_rate(None) is None

    def test_returns_none_and_warns_when_multiple_eur_gbp_rows(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        fx_rates = pl.LazyFrame(
            {
                "currency_from": ["EUR", "EUR"],
                "currency_to": ["GBP", "GBP"],
                "rate": [0.88, 0.90],
            }
        )

        with caplog.at_level(logging.WARNING, logger="rwa_calc.engine.fx_rate_sync"):
            result = extract_eur_gbp_rate(fx_rates)

        assert result is None
        assert any("2 (EUR, GBP) rows" in rec.message for rec in caplog.records)

    def test_ignores_reverse_direction_rows(self) -> None:
        """A (GBP, EUR) row must not match when we're looking for (EUR, GBP)."""
        fx_rates = pl.LazyFrame(
            {
                "currency_from": ["GBP"],
                "currency_to": ["EUR"],
                "rate": [1.15],
            }
        )

        assert extract_eur_gbp_rate(fx_rates) is None

    def test_preserves_precision_via_string_roundtrip(self) -> None:
        """The helper should round-trip via str to avoid float-noise in Decimal."""
        fx_rates = pl.LazyFrame(
            {
                "currency_from": ["EUR"],
                "currency_to": ["GBP"],
                "rate": [0.8732],
            }
        )

        result = extract_eur_gbp_rate(fx_rates)

        assert result == Decimal("0.8732")


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
