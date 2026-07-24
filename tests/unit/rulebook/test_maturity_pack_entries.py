"""
Pins for the CCR/SFT IRB effective-maturity (Art. 162) pack additions.

Phase 1 of the CCR/SFT IRB effective-maturity fix homes the two engine maturity
literals (the 1/365 one-day floor and the 0.5y F-IRB SFT supervisory M) onto
cited pack ``ScalarParam`` entries, and adds one cited ``Feature`` gating the new
CCR synthetic-maturity rung (the rung that survives under BOTH regimes — only the
CRR Art. 162(1) 0.5y is regime-specific, gated by the pre-existing
``firb_sft_supervisory_maturity`` feature). These pins lock the new entries before
the engine wires them (Phase 4).

References:
- CRR Art. 162(3) / PRA PS1/26 Art. 162(3): one-day (~1/365 y) maturity floor.
- CRR Art. 162(1): F-IRB fixed 0.5y supervisory M for repo-style SFTs (CRR-only;
  deleted under Basel 3.1, so only CRR reads the scalar).
- CRR Art. 162 / PRA PS1/26 Art. 162: CCR/SFT synthetic-row MNA & one-day floors
  (survive under both regimes).
"""

from __future__ import annotations

from datetime import date

from rwa_calc.rulebook.model import Citation, Feature, ScalarParam
from rwa_calc.rulebook.resolve import resolve

_CRR_PACK = resolve("crr", date(2026, 1, 1))
_B31_PACK = resolve("b31", date(2027, 1, 1))


# ---------------------------------------------------------------------------
# New cited scalars (common pack — regime-invariant day-count / value)
# ---------------------------------------------------------------------------


def test_one_day_maturity_floor_years_value() -> None:
    # Act
    entry = _CRR_PACK.scalar_param("one_day_maturity_floor_years")
    # Assert — homes the engine literal _ONE_DAY_YEARS = 1.0 / 365.0 (float round-trip)
    assert isinstance(entry, ScalarParam)
    assert float(entry.value) == 1 / 365


def test_one_day_maturity_floor_years_regime_invariant() -> None:
    # Act / Assert — the day-count is identical under both regimes (common pack)
    assert _CRR_PACK.scalar("one_day_maturity_floor_years") == _B31_PACK.scalar(
        "one_day_maturity_floor_years"
    )


def test_firb_sft_supervisory_maturity_years_value() -> None:
    # Act
    entry = _CRR_PACK.scalar_param("firb_sft_supervisory_maturity_years")
    # Assert — fixed 0.5y (Art. 162(1)), NOT 0.4y and NOT a floor
    assert isinstance(entry, ScalarParam)
    assert float(entry.value) == 0.5


def test_firb_fixed_supervisory_maturity_years_value() -> None:
    # Act
    entry = _CRR_PACK.scalar_param("firb_fixed_supervisory_maturity_years")
    # Assert — P1.249: Art. 162(1) "all other exposures M of 2,5 years" (a FIXED
    # value, the sibling of the 0.5y repo-style limb — not a floor, not a clip bound)
    assert isinstance(entry, ScalarParam)
    assert float(entry.value) == 2.5


def test_firb_fixed_supervisory_maturity_feature_is_crr_only() -> None:
    # Assert — CRR has Art. 162(1); PS1/26 Art. 162(1) is "Provision left blank",
    # so the fixed-M election can never fire under Basel 3.1.
    assert _CRR_PACK.feature("firb_fixed_supervisory_maturity") is True
    assert _B31_PACK.feature("firb_fixed_supervisory_maturity") is False


def test_firb_fixed_supervisory_maturity_feature_declared_in_both_packs() -> None:
    # Act / Assert — declared in both packs (avoids the pack.feature KeyError trap)
    assert isinstance(_CRR_PACK.entry("firb_fixed_supervisory_maturity"), Feature)
    assert isinstance(_B31_PACK.entry("firb_fixed_supervisory_maturity"), Feature)


def test_irb_maturity_floor_repo_sft_years_is_five_over_365() -> None:
    # Act
    entry = _CRR_PACK.scalar_param("irb_maturity_floor_repo_sft_years")
    # Assert — 5-day repo/SFT floor is a CALENDAR /365 fraction (NOT 5/250=0.02);
    # 5/365≈0.0137 is the value an MNA repo's M floors to (Art. 162(2)(d)).
    assert isinstance(entry, ScalarParam)
    assert float(entry.value) == 5 / 365


def test_irb_maturity_floor_collateralised_deriv_years_is_ten_over_365() -> None:
    # Act
    entry = _CRR_PACK.scalar_param("irb_maturity_floor_collateralised_deriv_years")
    # Assert — 10-day collateralised-deriv/margin-lending floor, /365 (Art. 162(2)(c))
    assert isinstance(entry, ScalarParam)
    assert float(entry.value) == 10 / 365


def test_mna_intermediate_floor_daily_condition_feature_regime_split() -> None:
    # Assert — CRR: 5BD/10BD floors apply on MNA alone (no daily condition);
    # B31 162(2A)(c)/(d): the daily-re-margin/revaluation condition IS required.
    assert _CRR_PACK.feature("mna_intermediate_floor_requires_daily_condition") is False
    assert _B31_PACK.feature("mna_intermediate_floor_requires_daily_condition") is True


# ---------------------------------------------------------------------------
# New cited feature (declared in BOTH regime packs — no KeyError)
# ---------------------------------------------------------------------------


def test_ccr_synthetic_maturity_feature_enabled_under_both_regimes() -> None:
    # Act / Assert — the CCR synthetic-maturity rung survives under both regimes
    assert _CRR_PACK.feature("ccr_synthetic_maturity") is True
    assert _B31_PACK.feature("ccr_synthetic_maturity") is True


# ---------------------------------------------------------------------------
# Each new entry carries a watchfire-visible Citation
# ---------------------------------------------------------------------------


def test_new_entries_carry_citations() -> None:
    # Act / Assert — every new entry exposes a non-empty Citation
    for name in (
        "one_day_maturity_floor_years",
        "irb_maturity_floor_repo_sft_years",
        "irb_maturity_floor_collateralised_deriv_years",
        "firb_sft_supervisory_maturity_years",
        "firb_fixed_supervisory_maturity_years",
        "firb_fixed_supervisory_maturity",
        "ccr_synthetic_maturity",
        "mna_intermediate_floor_requires_daily_condition",
    ):
        citation = _CRR_PACK.entry(name).citation
        assert isinstance(citation, Citation)
        assert citation.framework
        assert citation.article


def test_ccr_synthetic_maturity_feature_is_a_feature_in_both_packs() -> None:
    # Act / Assert — declared in both packs (avoids the pack.feature KeyError trap)
    assert isinstance(_CRR_PACK.entry("ccr_synthetic_maturity"), Feature)
    assert isinstance(_B31_PACK.entry("ccr_synthetic_maturity"), Feature)
