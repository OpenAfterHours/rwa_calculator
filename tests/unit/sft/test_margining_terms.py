"""
Unit tests for the SFT margining-term derivation (CRR Art. 285 / Art. 224(2)).

Validates ``_derive_margining_terms`` — the branch selector that returns
``(T_M, non_daily_N_R)`` for one SFT netting set:

- Branch (a) unmargined: ``(5-BD repo period, real N_R)`` → Art. 226 non-daily
  factor applies (driven by ``remargining_frequency_days``).
- Branch (b) margined: ``(MPOR, 1)`` → Art. 226 factor suppressed (the MPOR
  already encodes N via the +N−1 term).

The MPOR floor F (5/10/20) and the Art. 285(4) dispute multiplier (2) are read
from cited pack scalars in the engine — these tests pin the wiring and the
Art. 285(5) ``MPOR = F + N − 1`` derivation.

References:
    CRR Art. 224(2)(b) — 5-BD repo liquidation period.
    CRR Art. 226 — non-daily revaluation scale-up.
    CRR Art. 285(2)-(5) — margined MPOR floors, doubling, F + N − 1.
"""

from __future__ import annotations

from rwa_calc.engine.sft.fccm import _derive_margining_terms


class TestUnmarginedBranch:
    """Branch (a): unmargined SFT → 5-BD repo period + real N_R."""

    def test_unmargined_returns_repo_period_and_real_nr(self) -> None:
        """Unmargined: T_M = 5-BD repo (Art. 224(2)(b)); N_R passed through."""
        result = _derive_margining_terms(
            is_margined=False,
            remargining_frequency_days=3,
            mpor_floor_category=None,
            has_margin_dispute_doubling=None,
            mpor_days_override=None,
        )
        assert result == (5, 3)

    def test_unmargined_daily_defaults_nr_one(self) -> None:
        """Unmargined daily (N_R=1) → (5, 1): Art. 226 factor collapses to 1.0."""
        result = _derive_margining_terms(
            is_margined=False,
            remargining_frequency_days=1,
            mpor_floor_category=None,
            has_margin_dispute_doubling=None,
            mpor_days_override=None,
        )
        assert result == (5, 1)


class TestMarginedBranch:
    """Branch (b): margined SFT → MPOR + suppressed N_R."""

    def test_margined_repo_only_n2_yields_mpor6_nr_suppressed(self) -> None:
        """Margined repo-only N=2 → MPOR = 5·1 + 2 − 1 = 6, N_R suppressed (Art. 285(5))."""
        result = _derive_margining_terms(
            is_margined=True,
            remargining_frequency_days=2,
            mpor_floor_category="repo_only",
            has_margin_dispute_doubling=False,
            mpor_days_override=None,
        )
        assert result == (6, 1)

    def test_margined_override_supersedes_derivation(self) -> None:
        """``mpor_days_override`` wins over the F·mult + N − 1 derivation."""
        result = _derive_margining_terms(
            is_margined=True,
            remargining_frequency_days=2,
            mpor_floor_category="repo_only",
            has_margin_dispute_doubling=True,
            mpor_days_override=15,
        )
        assert result == (15, 1)

    def test_margined_dispute_doubling_doubles_floor(self) -> None:
        """Art. 285(4) doubling: F = 5×2, MPOR = 10 + 2 − 1 = 11."""
        result = _derive_margining_terms(
            is_margined=True,
            remargining_frequency_days=2,
            mpor_floor_category="repo_only",
            has_margin_dispute_doubling=True,
            mpor_days_override=None,
        )
        assert result == (11, 1)

    def test_margined_other_floor_is_ten(self) -> None:
        """Category 'other' → F=10 (Art. 285(2)(b)); MPOR = 10 + 1 − 1 = 10 at N=1."""
        result = _derive_margining_terms(
            is_margined=True,
            remargining_frequency_days=1,
            mpor_floor_category="other",
            has_margin_dispute_doubling=False,
            mpor_days_override=None,
        )
        assert result == (10, 1)

    def test_margined_large_or_illiquid_floor_is_twenty(self) -> None:
        """Category 'illiquid_or_large' → F=20 (Art. 285(3)); MPOR = 20 at N=1."""
        result = _derive_margining_terms(
            is_margined=True,
            remargining_frequency_days=1,
            mpor_floor_category="illiquid_or_large",
            has_margin_dispute_doubling=False,
            mpor_days_override=None,
        )
        assert result == (20, 1)

    def test_margined_daily_repo_only_equals_unmargined_period(self) -> None:
        """Margined-but-daily repo-only N=1 → MPOR = 5 (back-compat cross-check)."""
        result = _derive_margining_terms(
            is_margined=True,
            remargining_frequency_days=1,
            mpor_floor_category="repo_only",
            has_margin_dispute_doubling=False,
            mpor_days_override=None,
        )
        assert result == (5, 1)
