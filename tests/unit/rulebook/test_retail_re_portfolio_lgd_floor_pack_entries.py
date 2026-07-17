"""
Pins for the CRR Art. 164(4)/(5) retail-RE portfolio-level A-IRB LGD floor
pack entries (P1.183).

Homes the new portfolio-level check's regulatory values on the resolved
rulepack — a cited ``Feature`` gating the CRR-only check, and two cited
``ScalarParam`` entries (residential 10% / commercial 15%) — before the
engine-implementer wires the aggregator helper that reads them. These pins
lock the values first (rulepack = the value home, CLAUDE.md "Data/engine
separation") so a future engine change can't silently drift them.

Every assertion checks membership (``in pack.entries``) BEFORE calling a
shape-typed accessor (``.feature()`` / ``.scalar_param()``), so a missing
entry fails on a plain ``assert False``, never on the ``KeyError`` those
accessors raise for an absent name.

References:
- CRR Art. 164(4): portfolio-level minimum EW-avg LGD for A-IRB retail
  exposures secured by residential (10%) / commercial (15%) real estate.
- CRR Art. 164(4): central-government-guarantee exclusion from the floor.
- PRA PS1/26 Art. 164(4)(a): the B31 sibling is a PER-EXPOSURE 5% floor
  (the pre-existing ``airb_lgd_floor`` Feature), so this CRR-only
  portfolio-level Feature must resolve False under B31 (no duplicate
  check — see tests/acceptance/basel31/test_p1_183_art_164_portfolio_lgd_floor.py).
"""

from __future__ import annotations

from datetime import date

from rwa_calc.rulebook.resolve import resolve

_CRR_PACK = resolve("crr", date(2026, 1, 1))
_B31_PACK = resolve("b31", date(2027, 1, 1))


# ---------------------------------------------------------------------------
# crr_retail_re_portfolio_lgd_floor Feature — CRR-only, declared in BOTH
# packs (KeyError-safety precedent — see ucp_unilateral_change_ineligible /
# ccr_synthetic_maturity).
# ---------------------------------------------------------------------------


def test_crr_retail_re_portfolio_lgd_floor_feature_declared_in_crr_pack() -> None:
    # Assert — membership first, so a missing entry fails cleanly
    assert "crr_retail_re_portfolio_lgd_floor" in _CRR_PACK.entries


def test_crr_retail_re_portfolio_lgd_floor_feature_enabled_under_crr() -> None:
    # Arrange
    assert "crr_retail_re_portfolio_lgd_floor" in _CRR_PACK.entries
    # Act / Assert
    assert _CRR_PACK.feature("crr_retail_re_portfolio_lgd_floor") is True


def test_crr_retail_re_portfolio_lgd_floor_feature_declared_in_b31_pack() -> None:
    # Assert — declared in both regime packs (no KeyError on the B31 side)
    assert "crr_retail_re_portfolio_lgd_floor" in _B31_PACK.entries


def test_crr_retail_re_portfolio_lgd_floor_feature_disabled_under_b31() -> None:
    # Arrange
    assert "crr_retail_re_portfolio_lgd_floor" in _B31_PACK.entries
    # Act / Assert — B31's own per-exposure airb_lgd_floor already covers
    # this ground; the portfolio-level check is CRR-only.
    assert _B31_PACK.feature("crr_retail_re_portfolio_lgd_floor") is False


# ---------------------------------------------------------------------------
# retail_residential_re_portfolio_lgd_floor ScalarParam — CRR Art. 164(4), 10%
# ---------------------------------------------------------------------------


def test_retail_residential_re_portfolio_lgd_floor_declared_in_crr_pack() -> None:
    # Assert
    assert "retail_residential_re_portfolio_lgd_floor" in _CRR_PACK.entries


def test_retail_residential_re_portfolio_lgd_floor_value_is_10_pct() -> None:
    # Arrange
    assert "retail_residential_re_portfolio_lgd_floor" in _CRR_PACK.entries
    # Act
    entry = _CRR_PACK.scalar_param("retail_residential_re_portfolio_lgd_floor")
    # Assert — CRR Art. 164(4): 10% EW-avg LGD floor for residential RE
    assert float(entry.value) == 0.10


def test_retail_residential_re_portfolio_lgd_floor_cites_art_164() -> None:
    # Arrange
    assert "retail_residential_re_portfolio_lgd_floor" in _CRR_PACK.entries
    # Act
    entry = _CRR_PACK.scalar_param("retail_residential_re_portfolio_lgd_floor")
    # Assert — framework "CRR", article starting "164" (paragraph detail may
    # live in the article string or the free-text note — both are tolerated)
    assert entry.citation.framework == "CRR"
    assert entry.citation.article.startswith("164")


# ---------------------------------------------------------------------------
# retail_commercial_re_portfolio_lgd_floor ScalarParam — CRR Art. 164(4), 15%
# ---------------------------------------------------------------------------


def test_retail_commercial_re_portfolio_lgd_floor_declared_in_crr_pack() -> None:
    # Assert
    assert "retail_commercial_re_portfolio_lgd_floor" in _CRR_PACK.entries


def test_retail_commercial_re_portfolio_lgd_floor_value_is_15_pct() -> None:
    # Arrange
    assert "retail_commercial_re_portfolio_lgd_floor" in _CRR_PACK.entries
    # Act
    entry = _CRR_PACK.scalar_param("retail_commercial_re_portfolio_lgd_floor")
    # Assert — CRR Art. 164(4): 15% EW-avg LGD floor for commercial RE
    assert float(entry.value) == 0.15


def test_retail_commercial_re_portfolio_lgd_floor_cites_art_164() -> None:
    # Arrange
    assert "retail_commercial_re_portfolio_lgd_floor" in _CRR_PACK.entries
    # Act
    entry = _CRR_PACK.scalar_param("retail_commercial_re_portfolio_lgd_floor")
    # Assert
    assert entry.citation.framework == "CRR"
    assert entry.citation.article.startswith("164")
