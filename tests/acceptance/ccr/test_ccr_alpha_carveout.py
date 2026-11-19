"""
CCR-ALPHA-1..3 (P8.28) and review CC-01: the SA-CCR supervisory alpha, by regime.

Pipeline position:
    RawDataBundle -> HierarchyResolver -> ccr_sa_ccr stage (alpha_applied)
    -> Classifier -> CRM -> SA Calculator -> OutputAggregator

Key responsibilities:
- Prove that under the current UK CRR every netting set takes α = 1.4, whatever
  the counterparty_type — the non-financial / pension-scheme carve-out does not
  exist in the CCR (CRR) Part in force until 31 December 2026.
- Prove that under Basel 3.1 (PS1/26) non-financial and pension-scheme
  counterparties take α = 1 and financial counterparties keep α = 1.4.

Rule text (quoted verbatim):
- CRR — PRA Rulebook, Counterparty Credit Risk (CRR) Part, Art. 274(2), version in
  force to 31 Dec 2026: "Exposure value = α · (RC + PFE) where: RC = the
  replacement cost calculated in accordance with Article 275 ; and PFE = the
  potential future exposure calculated in accordance with Article 278 ; α = 1.4."
- Basel 3.1 — PS1/26 Appendix 1, Annex R, Art. 274(2) (p. 456; new, underlined
  text): "α = 1.4, unless the counterparty is a non-financial counterparty or a
  pension scheme arrangement or an entity established to provide compensation to
  members of a pension scheme arrangement in case of default, in which case, α = 1."

Defect pinned (review CC-01): the α = 1 carve-out was applied with no regime gate,
so a CRR run gave an NFC netting set α = 1.0 and understated its EAD by
1 − 1/1.4 = 28.6%. This module previously ASSERTED that CRR behaviour (its CRR
config expected ead_ccr 3,914,298.228 and alpha_applied 1.0 for the NFC and
pension scenarios); those assertions are inverted here on the rule text above.

Hand calculation (one 10y GBP 100m payer IRS at inception, MtM 0, unmargined;
SA-CCR Art. 279b(1)(a) supervisory duration with S floored at 10/250 = 0.04y,
SF_IR = 0.5%, MF = 1 because BD >= 250, RC = max(0 - 0, 0) = 0):

    CRR  (reporting 2026-01-15, maturity 2036-01-15, E = 3652/365.25):
        SD = (e^(-0.05*0.04) - e^(-0.05*E)) / 0.05 = 7.82860
        AddOn = 0.005 * 100,000,000 * SD             = 3,914,298.228
        EAD (every counterparty) = 1.4 * AddOn        = 5,480,017.519

    B31  (reporting 2027-01-15, maturity 2037-01-15, E = 3653/365.25):
        SD = 7.83026
        AddOn = 0.005 * 100,000,000 * SD             = 3,915,128.523
        EAD (non-financial / pension, α = 1)         = 3,915,128.523
        EAD (financial, α = 1.4)                     = 5,481,179.932

    The NFC / pension counterparties are unrated corporates (100% SA RW in both
    regimes), so rwa_final == ead_final.

References:
    - PRA CCR (CRR) Part Art. 274(2) (in force to 31 Dec 2026) — α = 1.4
    - PS1/26 Annex R Art. 274(2) — α = 1 carve-out (Basel 3.1 only)
    - EMIR Art. 2(9) / 2(10) — non-financial counterparty / pension scheme arrangement
    - tests/fixtures/ccr/p828_alpha_builder.py — scenario builders
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.ccr.p828_alpha_builder import (
    P828_ALPHA_CARVE_OUT,
    P828_ALPHA_STANDARD,
    P828_CP_TYPE_FINANCIAL,
    P828_CP_TYPE_NON_FINANCIAL,
    P828_CP_TYPE_PENSION,
    P828_EAD_FINANCIAL,
    P828_NS_FIN_ID,
    P828_NS_NFC_ID,
    P828_NS_PENSION_ID,
    P828_PFE_ADDON,
    build_p828_bundle,
    build_p828_two_counterparty_book,
)

# ---------------------------------------------------------------------------
# Regime set-up and hand-calculated expectations (see module docstring).
# ---------------------------------------------------------------------------

_CRR_REPORTING_DATE = date(2026, 1, 15)
_B31_REPORTING_DATE = date(2027, 1, 15)

#: B31 trade dates are the CCR-A1 dates moved forward one year, so the trade is
#: still at inception on the B31 reporting date.
_B31_SHIFT_YEARS = 1

_B31_PFE_ADDON = 3_915_128.523
_B31_EAD_CARVE_OUT = 3_915_128.523
_B31_EAD_FINANCIAL = 5_481_179.932

_NS_BY_TYPE = {
    P828_CP_TYPE_NON_FINANCIAL: P828_NS_NFC_ID,
    P828_CP_TYPE_PENSION: P828_NS_PENSION_ID,
    P828_CP_TYPE_FINANCIAL: P828_NS_FIN_ID,
}


def _crr_config() -> CalculationConfig:
    return CalculationConfig.crr(
        reporting_date=_CRR_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )


def _b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(
        reporting_date=_B31_REPORTING_DATE,
        permission_mode=PermissionMode.STANDARDISED,
    )


def _ccr_rows(result_bundle) -> dict[str, dict]:
    """Every synthetic CCR row of a result, keyed by source netting-set id."""
    df = result_bundle.results.collect()
    rows = df.filter(pl.col("exposure_reference").str.starts_with("ccr__")).to_dicts()
    return {row["source_netting_set_id"]: row for row in rows}


def _single_row(result_bundle, ns_id: str) -> dict:
    rows = _ccr_rows(result_bundle)
    assert list(rows) == [ns_id], f"expected one CCR row for {ns_id!r}, got {sorted(rows)!r}"
    return rows[ns_id]


@pytest.fixture(scope="module")
def crr_rows() -> dict[str, dict]:
    """CRR run of each single-counterparty scenario, keyed by counterparty_type."""
    return {
        cp_type: _single_row(
            PipelineOrchestrator().run_with_data(build_p828_bundle(cp_type), _crr_config()),
            ns_id,
        )
        for cp_type, ns_id in _NS_BY_TYPE.items()
    }


@pytest.fixture(scope="module")
def b31_rows() -> dict[str, dict]:
    """Basel 3.1 run of each single-counterparty scenario, keyed by counterparty_type."""
    return {
        cp_type: _single_row(
            PipelineOrchestrator().run_with_data(
                build_p828_bundle(cp_type, shift_years=_B31_SHIFT_YEARS), _b31_config()
            ),
            ns_id,
        )
        for cp_type, ns_id in _NS_BY_TYPE.items()
    }


# ---------------------------------------------------------------------------
# CRR: one alpha for every netting set.
# ---------------------------------------------------------------------------


class TestCrrAlphaIsUniform:
    """CRR Art. 274(2): α = 1.4 whatever the counterparty_type (review CC-01)."""

    @pytest.mark.parametrize(
        "cp_type", [P828_CP_TYPE_NON_FINANCIAL, P828_CP_TYPE_PENSION, P828_CP_TYPE_FINANCIAL]
    )
    def test_crr_alpha_applied_is_one_point_four(
        self, crr_rows: dict[str, dict], cp_type: str
    ) -> None:
        """Every CRR netting set reports alpha_applied == 1.4 — no carve-out."""
        # Arrange
        row = crr_rows[cp_type]

        # Assert
        assert row["alpha_applied"] == P828_ALPHA_STANDARD, (
            f"CRR {cp_type}: alpha_applied must be 1.4 (CCR (CRR) Part Art. 274(2) "
            f"'α = 1.4'; the α = 1 carve-out is PS1/26 text), got {row['alpha_applied']!r}"
        )

    @pytest.mark.parametrize(
        "cp_type", [P828_CP_TYPE_NON_FINANCIAL, P828_CP_TYPE_PENSION, P828_CP_TYPE_FINANCIAL]
    )
    def test_crr_ead_is_one_point_four_times_pfe(
        self, crr_rows: dict[str, dict], cp_type: str
    ) -> None:
        """CRR EAD = 1.4 × (0 + 3,914,298.228) = 5,480,017.519 for every counterparty type."""
        # Arrange
        row = crr_rows[cp_type]

        # Assert
        assert row["pfe_addon"] == pytest.approx(P828_PFE_ADDON, rel=1e-9)
        assert row["ead_ccr"] == pytest.approx(P828_EAD_FINANCIAL, rel=1e-9), (
            f"CRR {cp_type}: ead_ccr must be 1.4 x {P828_PFE_ADDON:,.3f} = "
            f"{P828_EAD_FINANCIAL:,.3f}; got {row['ead_ccr']:,.3f}. A value of "
            f"{P828_PFE_ADDON:,.3f} means the Basel 3.1 carve-out leaked into CRR."
        )
        assert row["ead_final"] == pytest.approx(row["ead_ccr"], rel=1e-12)

    @pytest.mark.parametrize("cp_type", [P828_CP_TYPE_NON_FINANCIAL, P828_CP_TYPE_PENSION])
    def test_crr_nfc_rwa_at_one_point_four(self, crr_rows: dict[str, dict], cp_type: str) -> None:
        """Unrated corporate NFC / pension (100% RW): rwa_final = 5,480,017.519."""
        # Arrange
        row = crr_rows[cp_type]

        # Assert
        assert row["risk_weight"] == pytest.approx(1.0)
        assert row["rwa_final"] == pytest.approx(P828_EAD_FINANCIAL, rel=1e-9)


# ---------------------------------------------------------------------------
# Basel 3.1: the α = 1 carve-out.
# ---------------------------------------------------------------------------


class TestB31AlphaCarveOut:
    """PS1/26 Art. 274(2): α = 1 for NFC / pension, 1.4 for financial counterparties."""

    @pytest.mark.parametrize("cp_type", [P828_CP_TYPE_NON_FINANCIAL, P828_CP_TYPE_PENSION])
    def test_b31_carve_out_counterparty_takes_alpha_one(
        self, b31_rows: dict[str, dict], cp_type: str
    ) -> None:
        """NFC / pension: alpha_applied 1.0, ead_ccr = 1.0 × 3,915,128.523."""
        # Arrange
        row = b31_rows[cp_type]

        # Assert
        assert row["alpha_applied"] == P828_ALPHA_CARVE_OUT
        assert row["pfe_addon"] == pytest.approx(_B31_PFE_ADDON, rel=1e-9)
        assert row["ead_ccr"] == pytest.approx(_B31_EAD_CARVE_OUT, rel=1e-9)
        assert row["rwa_final"] == pytest.approx(_B31_EAD_CARVE_OUT * row["risk_weight"], rel=1e-9)

    def test_b31_financial_counterparty_keeps_alpha_one_point_four(
        self, b31_rows: dict[str, dict]
    ) -> None:
        """Financial: alpha_applied 1.4, ead_ccr = 1.4 × 3,915,128.523 = 5,481,179.932."""
        # Arrange
        row = b31_rows[P828_CP_TYPE_FINANCIAL]

        # Assert
        assert row["alpha_applied"] == P828_ALPHA_STANDARD
        assert row["ead_ccr"] == pytest.approx(_B31_EAD_FINANCIAL, rel=1e-9)

    def test_b31_nfc_to_financial_ead_ratio_is_alpha_ratio(self, b31_rows: dict[str, dict]) -> None:
        """Same economics, so EAD(NFC) / EAD(financial) == 1.0 / 1.4 exactly."""
        # Arrange
        nfc = b31_rows[P828_CP_TYPE_NON_FINANCIAL]["ead_ccr"]
        fin = b31_rows[P828_CP_TYPE_FINANCIAL]["ead_ccr"]

        # Assert
        assert nfc / fin == pytest.approx(P828_ALPHA_CARVE_OUT / P828_ALPHA_STANDARD, rel=1e-9)


# ---------------------------------------------------------------------------
# Keyed-join guard: two counterparties in one book, both regimes.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("config_factory", "shift_years", "expected_alpha"),
    [
        (_crr_config, 0, {P828_NS_NFC_ID: P828_ALPHA_STANDARD, P828_NS_FIN_ID: 1.4}),
        (
            _b31_config,
            _B31_SHIFT_YEARS,
            {P828_NS_NFC_ID: P828_ALPHA_CARVE_OUT, P828_NS_FIN_ID: P828_ALPHA_STANDARD},
        ),
    ],
    ids=["crr", "b31"],
)
def test_two_counterparty_book_keys_alpha_per_netting_set(
    config_factory, shift_years: int, expected_alpha: dict[str, float]
) -> None:
    """One row per netting set, each with its own regime-correct alpha (no fan-out)."""
    # Arrange
    bundle = build_p828_two_counterparty_book(shift_years=shift_years)

    # Act
    rows = _ccr_rows(PipelineOrchestrator().run_with_data(bundle, config_factory()))

    # Assert
    assert {ns: row["alpha_applied"] for ns, row in rows.items()} == expected_alpha
