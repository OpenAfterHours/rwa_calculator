"""
Unit tests for the BA-CVA netting-set inputs (review items CC-15 / CC-16).

Pipeline position:
    aggregated results (``ccr__`` rows) -> engine/cva/ba_cva.py -> cva_rwa

Key responsibilities under test:
- CC-15: SCVA_c divides each netting set by the alpha the CCR Part applied to
  THAT netting set (``alpha_applied``), reads the pre-CRM SA-CCR exposure value
  (``ead_ccr``), counts each netting set once however many CRM legs it was split
  into, and admits derivative netting sets only (``risk_type ==
  CCR_DERIVATIVE``) — FCCM SFT rows share the ``ccr__`` prefix but are not
  covered transactions by default.
- CC-16: every derivative counterparty that has NO row in the CVA counterparty
  input is named by a WARNING (CCR030), except QCCP trades.

Rule text (PS1/26 Appendix 1, Credit Valuation Adjustment Risk Part, effective
1 January 2027 — Basel 3.1 only; under CRR the ``cva_ba_cva`` Feature is off):
- 4.3: "SCVA_c = (1/alpha) . RW_c . SUM_NS M_NS . EAD_NS . DF_NS" where "EAD_NS
  is the exposure at default of the netting set, calculated in the same manner in
  which the firm calculates exposure at default for determining own funds
  requirements for counterparty credit risk, in accordance with either Sections 3
  to 5 of Counterparty Credit Risk (CRR) Part ..." and "alpha = the value of alpha
  as specified in the Counterparty Credit Risk (CRR) Part".
- CCR (CRR) Part Art. 274(2) as amended by PS1/26 Annex R: "alpha = 1.4, unless
  the counterparty is a non-financial counterparty or a pension scheme
  arrangement ... in which case, alpha = 1."
- 1.2 "covered transaction": "(1) a derivative transaction, but excluding: (a)
  derivatives transacted directly with a qualifying central counterparty ...;
  (2) a securities financing transaction, if: (a) it is fair-valued ... and (b)
  the firm's CVA risk arising from the transaction is material."

Hand calculation (NFC, OTHER / IG -> RW_c 5%, M 5, EAD 10m):
    DF  = (1 - e^-0.25) / 0.25 = 0.8847968677
    SCVA = (1/1.0) x 0.05 x 5 x 10,000,000 x 0.8847968677 = 2,211,992.169
    RWEA = 0.65 x SCVA x 12.5 = 17,972,436.38   (pre-fix alpha 1.4: 12,837,454.56)
"""

from __future__ import annotations

import math
from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.errors import ERROR_CVA_COUNTERPARTY_NOT_SUPPLIED
from rwa_calc.domain.enums import ErrorSeverity
from rwa_calc.engine.cva import compute_ba_cva_rwa, uncovered_cva_counterparty_errors
from rwa_calc.rulebook.resolve import resolve

_PACK = resolve("b31", date(2027, 3, 31))
_DF_5Y = (1.0 - math.exp(-0.05 * 5.0)) / (0.05 * 5.0)
_RWEA_NFC_10M = 0.65 * 12.5 * 0.05 * 5.0 * 10_000_000.0 * _DF_5Y


def _cva_counterparties(*refs: str, in_scope: bool = True) -> pl.LazyFrame:
    return pl.LazyFrame(
        {
            "counterparty_reference": list(refs),
            "cva_rw_sector": ["OTHER"] * len(refs),
            "cva_rw_rating_band": ["IG"] * len(refs),
            "cva_effective_maturity_years": [5.0] * len(refs),
            "cva_in_scope": [in_scope] * len(refs),
        }
    )


def _ccr_rows(rows: list[dict[str, object]]) -> pl.LazyFrame:
    base: dict[str, object] = {
        "risk_type": "CCR_DERIVATIVE",
        "cp_entity_type": "corporate",
        "cp_is_qccp": None,
    }
    return pl.LazyFrame(
        [{**base, **row} for row in rows],
        schema_overrides={"cp_is_qccp": pl.Boolean, "alpha_applied": pl.Float64},
    )


class TestCC15NettingSetInputs:
    """SCVA_c reads the CCR Part's own alpha and exposure value, per netting set."""

    def test_nfc_netting_set_is_divided_by_its_own_alpha_of_one(self) -> None:
        # Arrange: a non-financial counterparty, alpha_applied = 1.0 (Annex R 274(2)).
        rows = _ccr_rows(
            [
                {
                    "exposure_reference": "ccr__NS1",
                    "source_netting_set_id": "NS1",
                    "counterparty_reference": "NFC",
                    "ead_ccr": 10_000_000.0,
                    "ead_final": 10_000_000.0,
                    "alpha_applied": 1.0,
                }
            ]
        )

        # Act
        result = compute_ba_cva_rwa(_cva_counterparties("NFC"), rows, _PACK)

        # Assert (pre-fix: 12,837,454.56 — every netting set divided by 1.4)
        assert result.rwea == pytest.approx(_RWEA_NFC_10M, rel=1e-9)
        assert result.rwea == pytest.approx(17_972_436.38, abs=0.01)

    def test_financial_netting_set_keeps_alpha_one_point_four(self) -> None:
        # Arrange
        rows = _ccr_rows(
            [
                {
                    "exposure_reference": "ccr__NS1",
                    "source_netting_set_id": "NS1",
                    "counterparty_reference": "FIN",
                    "ead_ccr": 10_000_000.0,
                    "ead_final": 10_000_000.0,
                    "alpha_applied": 1.4,
                }
            ]
        )

        # Act
        result = compute_ba_cva_rwa(_cva_counterparties("FIN"), rows, _PACK)

        # Assert
        assert result.rwea == pytest.approx(_RWEA_NFC_10M / 1.4, rel=1e-9)

    def test_ead_is_the_pre_crm_sa_ccr_exposure_value(self) -> None:
        # Arrange: lending-side CRM cut ead_final to 2m; EAD_NS is still 10m.
        rows = _ccr_rows(
            [
                {
                    "exposure_reference": "ccr__NS1",
                    "source_netting_set_id": "NS1",
                    "counterparty_reference": "NFC",
                    "ead_ccr": 10_000_000.0,
                    "ead_final": 2_000_000.0,
                    "alpha_applied": 1.0,
                }
            ]
        )

        # Act
        result = compute_ba_cva_rwa(_cva_counterparties("NFC"), rows, _PACK)

        # Assert (pre-fix: 2m / 1.4 basis -> 2,567,490.91)
        assert result.rwea == pytest.approx(_RWEA_NFC_10M, rel=1e-9)

    def test_guarantee_split_legs_count_their_netting_set_once(self) -> None:
        # Arrange: one netting set split into a guaranteed and a remainder leg,
        # both carrying the netting set's ead_ccr.
        rows = _ccr_rows(
            [
                {
                    "exposure_reference": "ccr__NS1__G_GOV",
                    "source_netting_set_id": "NS1",
                    "counterparty_reference": "NFC",
                    "ead_ccr": 10_000_000.0,
                    "ead_final": 6_000_000.0,
                    "alpha_applied": 1.0,
                },
                {
                    "exposure_reference": "ccr__NS1__REM",
                    "source_netting_set_id": "NS1",
                    "counterparty_reference": "NFC",
                    "ead_ccr": 10_000_000.0,
                    "ead_final": 4_000_000.0,
                    "alpha_applied": 1.0,
                },
            ]
        )
        legs = rows.collect()
        assert legs.height == 2, "adequacy: the netting set must be split into two legs"
        assert legs["source_netting_set_id"].n_unique() == 1, "adequacy: legs of ONE netting set"

        # Act
        result = compute_ba_cva_rwa(_cva_counterparties("NFC"), rows, _PACK)

        # Assert: 10m once, not 20m
        assert result.rwea == pytest.approx(_RWEA_NFC_10M, rel=1e-9)

    def test_sft_rows_are_not_covered_transactions(self) -> None:
        # Arrange: an FCCM SFT row shares the ccr__ prefix and the counterparty.
        rows = _ccr_rows(
            [
                {
                    "exposure_reference": "ccr__NS1",
                    "source_netting_set_id": "NS1",
                    "counterparty_reference": "NFC",
                    "ead_ccr": 10_000_000.0,
                    "ead_final": 10_000_000.0,
                    "alpha_applied": 1.0,
                },
                {
                    "exposure_reference": "ccr__SFT1",
                    "source_netting_set_id": "SFT1",
                    "counterparty_reference": "NFC",
                    "risk_type": "CCR_SFT",
                    "ead_ccr": None,
                    "ead_final": 50_000_000.0,
                    "alpha_applied": None,
                },
            ]
        )

        # Act
        result = compute_ba_cva_rwa(_cva_counterparties("NFC"), rows, _PACK)

        # Assert (pre-fix: the 50m SFT entered SCVA_c)
        assert result.rwea == pytest.approx(_RWEA_NFC_10M, rel=1e-9)


class TestCC16CoverageWarning:
    """A derivative counterparty with no CVA input row is named, not dropped."""

    def test_counterparty_missing_from_cva_input_is_warned(self) -> None:
        # Arrange
        rows = _ccr_rows(
            [
                {
                    "exposure_reference": "ccr__NS1",
                    "source_netting_set_id": "NS1",
                    "counterparty_reference": "LISTED",
                    "ead_ccr": 1.0,
                    "ead_final": 1.0,
                    "alpha_applied": 1.4,
                },
                {
                    "exposure_reference": "ccr__NS2",
                    "source_netting_set_id": "NS2",
                    "counterparty_reference": "MISSING",
                    "ead_ccr": 1.0,
                    "ead_final": 1.0,
                    "alpha_applied": 1.4,
                },
            ]
        )

        # Act
        errors = uncovered_cva_counterparty_errors(rows, _cva_counterparties("LISTED"))

        # Assert
        assert [e.counterparty_reference for e in errors] == ["MISSING"]
        assert errors[0].code == ERROR_CVA_COUNTERPARTY_NOT_SUPPLIED == "CCR030"
        assert errors[0].severity == ErrorSeverity.WARNING

    def test_absent_cva_input_warns_every_derivative_counterparty(self) -> None:
        # Arrange
        rows = _ccr_rows(
            [
                {
                    "exposure_reference": f"ccr__NS{i}",
                    "source_netting_set_id": f"NS{i}",
                    "counterparty_reference": ref,
                    "ead_ccr": 1.0,
                    "ead_final": 1.0,
                    "alpha_applied": 1.4,
                }
                for i, ref in enumerate(("B", "A", "A"))
            ]
        )

        # Act
        errors = uncovered_cva_counterparty_errors(rows, None)

        # Assert: one per counterparty, deterministic order
        assert [e.counterparty_reference for e in errors] == ["A", "B"]

    def test_explicitly_out_of_scope_counterparty_is_not_warned(self) -> None:
        # Arrange: the firm listed it with cva_in_scope=False (e.g. a 3.2 exemption).
        rows = _ccr_rows(
            [
                {
                    "exposure_reference": "ccr__NS1",
                    "source_netting_set_id": "NS1",
                    "counterparty_reference": "EXEMPT",
                    "ead_ccr": 1.0,
                    "ead_final": 1.0,
                    "alpha_applied": 1.4,
                }
            ]
        )

        # Act
        errors = uncovered_cva_counterparty_errors(
            rows, _cva_counterparties("EXEMPT", in_scope=False)
        )

        # Assert
        assert errors == []

    def test_qccp_trades_and_sfts_are_not_warned(self) -> None:
        # Arrange: a QCCP derivative (definition (1)(a) exclusion) and an SFT.
        rows = _ccr_rows(
            [
                {
                    "exposure_reference": "ccr__NS1",
                    "source_netting_set_id": "NS1",
                    "counterparty_reference": "QCCP",
                    "cp_entity_type": "ccp",
                    "cp_is_qccp": True,
                    "ead_ccr": 1.0,
                    "ead_final": 1.0,
                    "alpha_applied": 1.4,
                },
                {
                    "exposure_reference": "ccr__SFT1",
                    "source_netting_set_id": "SFT1",
                    "counterparty_reference": "REPO_CP",
                    "risk_type": "CCR_SFT",
                    "ead_ccr": None,
                    "ead_final": 1.0,
                    "alpha_applied": None,
                },
                {
                    "exposure_reference": "ccr__NS2",
                    "source_netting_set_id": "NS2",
                    "counterparty_reference": "NON_QCCP",
                    "cp_entity_type": "ccp",
                    "cp_is_qccp": False,
                    "ead_ccr": 1.0,
                    "ead_final": 1.0,
                    "alpha_applied": 1.4,
                },
            ]
        )

        # Act
        errors = uncovered_cva_counterparty_errors(rows, None)

        # Assert: only the non-qualifying CCP's derivatives are covered transactions
        assert [e.counterparty_reference for e in errors] == ["NON_QCCP"]
