"""
Reviews CL-01 and CL-11: which collateral TYPES the two funded methods recognise.

CL-01 — the SA exposure-value reduction honours the Art. 197 flag only on an
Art. 197 type.
    CRR Art. 197(1): "Institutions may use the following items as eligible
    collateral under all approaches and methods: (a) cash on deposit ... (b)
    debt securities issued by central governments ..."; Art. 199(1): "In
    addition to the collateral referred to in Articles 197 and 198, institutions
    that calculate risk-weighted exposure amounts ... under the IRB Approach may
    also use ... (a) immovable property ... (b) receivables ... (c) other
    physical collateral". PS1/26 Art. 199(1) reads the same "under the
    Foundation Collateral Method". Life insurance is other funded protection
    (Art. 232(3)), weighted, not netted. Before CL-01 the SA E* summed every row
    flagged ``is_eligible_financial_collateral``, so a flagged receivable took a
    100,000 corporate loan to EAD 0 (CRR) / 40,000 (Basel 3.1).

    Hand calculation (SA, large unrated corporate, RW 100%, loan 100,000, one
    100,000 pledge flagged True): receivables / other physical / immovable
    property -> no SA reduction, EAD 100,000; life insurance (insurer
    unrated) -> no E* reduction, the Art. 232(3) mapping applies exactly as when
    unflagged (RWA 70,000 measured both ways). Cash control -> EAD 0.

    The Art. 222 Simple Method reads the same flag. Art. 197 binds "under all
    approaches and methods", so a flagged non-Art. 197 row is no Simple-Method
    collateral either: ``fcsm_collateral_value`` 0 (pre-fix 100,000, the whole
    loan, substituted at the corporate-bond fallback weight — a relief wherever
    the obligor's own weight exceeds it); the cash control is recognised in full.

CL-11 — the canonical input type ``bond`` is financial collateral by its issuer.
    ``normalise_collateral_type_expr`` already resolved ``bond`` + ``issuer_type``
    for the Art. 224 haircut (P1.233); the category ladder did not, so on the
    F-IRB path a sovereign ``bond`` was "other": zeroed as unattested
    non-financial collateral (CRM014), or with an attestation given the other-
    physical LGDS, while ``government_bond`` took the 0% financial LGDS (Art.
    230(2): "Financial collateral 0%"). Both now resolve the same.

    Hand calculation (F-IRB, loan 100,000, CQS 1 sovereign bond 50,000, 4-year
    residual, 10-day period: H_c = 2% both regimes -> C = 49,000):
        CRR: LGD* = 0.45 x 51,000 / 100,000 = 0.2295 (pre-fix 0.45)
        Basel 3.1: LGD* = 0.40 x 51,000 / 100,000 = 0.204 (pre-fix 0.40)
"""

from __future__ import annotations

import polars as pl
import pytest
from tests.unit.crm import _pipeline_harness as harness

from rwa_calc.domain.enums import CRMCollateralMethod
from rwa_calc.engine.crm.expressions import collateral_category_expr, sa_fccm_type_eligible_expr


def _sa_run(
    regime: str,
    pledge: dict,
    method: CRMCollateralMethod = CRMCollateralMethod.COMPREHENSIVE,
) -> tuple[dict, set[str]]:
    results, errors = harness.run(
        regime,
        collateral_method=method,
        loans=harness.loans(
            [{"loan_reference": "L1", "counterparty_reference": "CP1", "drawn_amount": 100_000.0}]
        ),
        collateral=harness.collateral([pledge]),
    )
    return harness.row(results, "L1"), harness.codes(errors)


def _flagged(collateral_type: str, **extra: object) -> dict:
    return {
        "collateral_reference": "C1",
        "collateral_type": collateral_type,
        "market_value": 100_000.0,
        "beneficiary_type": "loan",
        "beneficiary_reference": "L1",
        "is_eligible_financial_collateral": True,
        "is_eligible_irb_collateral": True,
        **extra,
    }


class TestSaFccmIgnoresTheFlagOnNonArt197Types:
    """CL-01: a flagged non-financial row reduces no SA exposure value."""

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    @pytest.mark.parametrize("collateral_type", ["receivables", "other_physical"])
    def test_flagged_non_financial_row_leaves_ead_whole(
        self, regime: str, collateral_type: str
    ) -> None:
        # Act
        result, error_codes = _sa_run(regime, _flagged(collateral_type))

        # Assert: pre-fix CRR 0 / 0, Basel 3.1 40,000 / 40,000.
        assert result["ead_final"] == pytest.approx(100_000.0)
        assert result["rwa_final"] == pytest.approx(100_000.0)
        assert "CRM026" in error_codes

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_flagged_property_leaves_ead_whole(self, regime: str) -> None:
        # Act
        result, error_codes = _sa_run(
            regime,
            _flagged(
                "real_estate", property_type="commercial", property_ltv=1.0, is_qualifying_re=True
            ),
        )

        # Assert: the E* reduction is gone (pre-fix CRR EAD 0, Basel 3.1 40,000).
        assert result["ead_final"] == pytest.approx(100_000.0)
        assert result["collateral_adjusted_value"] == pytest.approx(0.0)
        assert "CRM026" in error_codes

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_flagged_life_policy_is_weighted_as_when_unflagged(self, regime: str) -> None:
        # Arrange
        policy = _flagged("life_insurance")
        unflagged, _ = _sa_run(regime, {**policy, "is_eligible_financial_collateral": False})

        # Act
        flagged, error_codes = _sa_run(regime, policy)

        # Assert: pre-fix the flagged policy took EAD to 0 (RWA 0).
        assert flagged["ead_final"] == pytest.approx(100_000.0)
        assert flagged["rwa_final"] == pytest.approx(70_000.0)
        assert unflagged["rwa_final"] == pytest.approx(70_000.0)
        assert "CRM026" in error_codes

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    @pytest.mark.parametrize(
        ("collateral_type", "expected_value"),
        [("receivables", 0.0), ("other_physical", 0.0), ("cash", 100_000.0)],
    )
    def test_simple_method_honours_the_flag_only_on_art_197_types(
        self, regime: str, collateral_type: str, expected_value: float
    ) -> None:
        # Act
        result, error_codes = _sa_run(
            regime, _flagged(collateral_type), method=CRMCollateralMethod.SIMPLE
        )

        # Assert: pre-fix the flagged receivable / other-physical row was
        # recognised for the whole loan (fcsm_collateral_value 100,000).
        assert result["fcsm_collateral_value"] == pytest.approx(expected_value, abs=1e-9)
        assert ("CRM026" in error_codes) is (collateral_type != "cash")

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_flagged_cash_still_reduces_ead(self, regime: str) -> None:
        # Act
        result, error_codes = _sa_run(regime, _flagged("cash"))

        # Assert: the Art. 197(1)(a) control.
        assert result["ead_final"] == pytest.approx(0.0, abs=1e-9)
        assert "CRM026" not in error_codes


class TestBondIsCategorisedByItsIssuer:
    """CL-11: ``bond`` + issuer resolves like the named debt-security types."""

    @pytest.mark.parametrize(
        ("issuer_type", "expected"),
        [
            ("sovereign", "financial"),
            ("corporate", "financial"),
            ("pse", "financial"),
            ("institution", "financial"),
            ("securitisation", "financial"),
            (None, "other_physical"),
        ],
    )
    def test_category(self, issuer_type: str | None, expected: str) -> None:
        # Arrange
        frame = pl.LazyFrame(
            {"collateral_type": ["bond"], "issuer_type": [issuer_type]},
            schema={"collateral_type": pl.String, "issuer_type": pl.String},
        )

        # Act
        out = frame.select(
            collateral_category_expr().alias("cat"),
            sa_fccm_type_eligible_expr().alias("sa_ok"),
        ).collect()

        # Assert: the SA type gate agrees with the category.
        assert out["cat"][0] == expected
        assert out["sa_ok"][0] is (expected == "financial")

    @pytest.mark.parametrize(
        ("regime", "expected_lgd"), [("crr", 0.45 * 0.51), ("b31", 0.40 * 0.51)]
    )
    @pytest.mark.parametrize("collateral_type", ["bond", "government_bond"])
    def test_firb_lgd_is_the_financial_lgds(
        self, regime: str, expected_lgd: float, collateral_type: str
    ) -> None:
        # Arrange
        pledge = {
            "collateral_reference": "C1",
            "collateral_type": collateral_type,
            "issuer_type": "sovereign",
            "issuer_cqs": 1,
            "market_value": 50_000.0,
            "residual_maturity_years": 4.0,
            "original_maturity_years": 5.0,
            "beneficiary_type": "loan",
            "beneficiary_reference": "L1",
            "is_eligible_financial_collateral": True,
        }

        # Act
        results, errors = harness.run(
            regime,
            firb=True,
            loans=harness.loans(
                [
                    {
                        "loan_reference": "L1",
                        "counterparty_reference": "CP1",
                        "drawn_amount": 100_000.0,
                    }
                ]
            ),
            collateral=harness.collateral([pledge]),
        )

        # Assert: C = 50,000 x (1 - 2%) = 49,000 at LGDS 0%; no CRM014 / CRM021.
        result = harness.row(results, "L1")
        assert result["approach_applied"] == "foundation_irb"
        assert result["lgd_post_crm"] == pytest.approx(expected_lgd, rel=1e-9)
        assert result["collateral_financial_value"] == pytest.approx(49_000.0)
        assert not {"CRM014", "CRM021"} & harness.codes(errors)
