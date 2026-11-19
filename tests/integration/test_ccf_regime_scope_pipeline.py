"""End-to-end CCF scope fixes (2026-11 review, cluster ``ccf``) through the real pipeline.

Each test drives a small bundle through ``PipelineOrchestrator.run_with_data`` in BOTH
regimes and asserts the hand-calculated conversion factor, EAD and RWA. The rule text
each item relies on is quoted in its unit-test module:

- CM-03  ``tests/unit/test_ccf_airb_own_estimate_scope.py`` (PS1/26 Art. 166D(1))
- CM-07 / TR-04  ``tests/unit/test_ccf_obs_product_regime_map.py`` (CRR Annex I /
  PS1/26 Table A1)
- TR-02  ``tests/unit/test_ccf_purchased_receivable_scope.py`` (PS1/26 Art. 166A(5))
- RE-14  ``tests/unit/test_ccf_uk_resi_commitment_derivation.py`` (PS1/26 Table A1
  Row 4(b))

All counterparties are unrated GB corporates (SA risk weight 100%) unless stated, so
an SA RWA is the EAD; an IRB RWA is asserted as EAD x the row's own risk weight, the
risk weight being independent of the conversion factor.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import CalculationError
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.raw_bundle import make_raw_bundle
from tests.integration.conftest import (
    make_contingent,
    make_counterparty,
    make_facility,
    make_loan,
    make_model_permission,
    make_rating,
    make_raw_data_bundle,
)

_CRR_DATE = date(2026, 6, 30)
_B31_DATE = date(2027, 6, 30)


def _config(regime: str, mode: PermissionMode = PermissionMode.STANDARDISED) -> CalculationConfig:
    if regime == "crr":
        return CalculationConfig.crr(reporting_date=_CRR_DATE, permission_mode=mode)
    return CalculationConfig.basel_3_1(reporting_date=_B31_DATE, permission_mode=mode)


def _run(bundle: Any, config: CalculationConfig) -> tuple[dict[str, dict[str, Any]], list]:
    result = PipelineOrchestrator().run_with_data(bundle, config)
    frame = result.results.collect() if isinstance(result.results, pl.LazyFrame) else result.results
    rows = {r["exposure_reference"]: r for r in frame.to_dicts()}
    errors: list[CalculationError] = list(result.errors)
    return rows, errors


# ---------------------------------------------------------------------------
# CM-03 — B31 A-IRB own estimates only for revolving loan COMMITMENTS
# ---------------------------------------------------------------------------


def _airb_bundle(**lc_overrides: Any) -> Any:
    """An issued MLR letter of credit (ccf_modelled 0.05) under a revolving RCF."""
    return make_raw_data_bundle(
        counterparties=[make_counterparty(counterparty_reference="CP1")],
        facilities=[
            make_facility(
                facility_reference="F_RCF",
                counterparty_reference="CP1",
                risk_type="OC",
                limit=10_000_000.0,
                is_revolving=True,
                lgd=0.4,
                ccf_modelled=0.30,
            )
        ],
        contingents=[
            make_contingent(
                contingent_reference="C_LC_ISSUED",
                counterparty_reference="CP1",
                risk_type="MLR",
                nominal_amount=1_000_000.0,
                ccf_modelled=0.05,
                lgd=0.4,
                **lc_overrides,
            )
        ],
        loans=[
            make_loan(
                loan_reference="L1",
                counterparty_reference="CP1",
                drawn_amount=0.0,
                interest=0.0,
                lgd=0.4,
            )
        ],
        facility_mappings=[
            {
                "parent_facility_reference": "F_RCF",
                "child_reference": "C_LC_ISSUED",
                "child_type": "contingent",
            },
            {"parent_facility_reference": "F_RCF", "child_reference": "L1", "child_type": "loan"},
        ],
        model_permissions=[
            make_model_permission(approach="advanced_irb", exposure_class="corporate")
        ],
        ratings=[make_rating(counterparty_reference="CP1", pd=0.01, model_id="MODEL_01")],
    )


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_cm03_issued_lc_under_revolving_facility_takes_the_supervisory_ccf(regime: str) -> None:
    """Issued LC: 20% in both regimes (CRR 166(10)(c); B31 166D(1)(b) -> Table A1 Row 6).

    Before the fix B31 took max(0.05, 0.5 x 0.20) = 0.10 -> EAD 100,000.
    """
    # Arrange / Act
    rows, _ = _run(_airb_bundle(), _config(regime, PermissionMode.IRB))
    lc = rows["C_LC_ISSUED"]

    # Assert
    assert lc["approach"] == "advanced_irb"
    assert lc["ccf"] == pytest.approx(0.20)
    assert lc["ead_final"] == pytest.approx(200_000.0)
    assert lc["rwa_final"] == pytest.approx(200_000.0 * lc["risk_weight"], rel=1e-9)


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_cm03_revolving_commitment_keeps_its_own_estimate(regime: str) -> None:
    """Control: the RCF's undrawn 9,000,000 at the modelled 30% = 2,700,000 in both."""
    # Arrange / Act
    rows, _ = _run(_airb_bundle(), _config(regime, PermissionMode.IRB))
    undrawn = rows["F_RCF_UNDRAWN"]

    # Assert
    assert undrawn["ccf"] == pytest.approx(0.30)
    assert undrawn["ead_final"] == pytest.approx(2_700_000.0)


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_cm03_issued_lc_under_revolving_facility_ignores_its_own_ead(regime: str) -> None:
    """Art. 166D(3) is for revolving loan facilities: the issued LC keeps its 20%.

    Before the fix B31 took max(50,000, 0.5 x 1,000,000 x 0.20) = 100,000. CRR has
    no Art. 166D and ignores ``ead_modelled`` (Art. 166(10)(c) 20%).
    """
    # Arrange / Act
    rows, _ = _run(_airb_bundle(ead_modelled=50_000.0), _config(regime, PermissionMode.IRB))
    lc = rows["C_LC_ISSUED"]

    # Assert
    assert lc["approach"] == "advanced_irb"
    assert lc["ead_modelled"] == pytest.approx(50_000.0), "the own estimate reached the CCF stage"
    assert lc["ead_final"] == pytest.approx(200_000.0)


# ---------------------------------------------------------------------------
# CM-07 / TR-04 — the obs_product map is regime-specific
# ---------------------------------------------------------------------------


def _obs_product_bundle() -> Any:
    contingents = [
        make_contingent(
            contingent_reference=f"C_{product}",
            counterparty_reference="CP1",
            risk_type=None,
            obs_product=product,
            nominal_amount=1_000_000.0,
        )
        for product in ("DOCUMENTARY_CREDIT", "SHIPPING_GUARANTEE", "TRADE_LC")
    ]
    return make_raw_data_bundle(
        counterparties=[make_counterparty(counterparty_reference="CP1")],
        facilities=[make_facility(facility_reference="F1", counterparty_reference="CP1")],
        loans=[make_loan(loan_reference="L1", counterparty_reference="CP1", drawn_amount=0.0)],
        contingents=contingents,
        facility_mappings=[],
    )


@pytest.mark.parametrize(
    ("regime", "product", "expected_ccf"),
    [
        # CRR Annex I 2(a) / 2(b)(i): medium risk 50% (before the fix DC was 20%)
        ("crr", "DOCUMENTARY_CREDIT", 0.50),
        ("crr", "SHIPPING_GUARANTEE", 0.50),
        # CRR Annex I 3(a)(i): self-liquidating 20%
        ("crr", "TRADE_LC", 0.20),
        # PS1/26 Table A1 row 6(a) / 6(d): 20% (shipping guarantee was the 50% residual)
        ("b31", "DOCUMENTARY_CREDIT", 0.20),
        ("b31", "SHIPPING_GUARANTEE", 0.20),
        ("b31", "TRADE_LC", 0.20),
    ],
)
def test_cm07_obs_product_prices_per_regime(regime: str, product: str, expected_ccf: float) -> None:
    """1,000,000 nominal, unrated corporate at 100%: RWA = EAD = 1,000,000 x CCF."""
    # Arrange / Act
    rows, errors = _run(_obs_product_bundle(), _config(regime))
    row = rows[f"C_{product}"]

    # Assert
    assert row["ccf"] == pytest.approx(expected_ccf)
    assert row["ead_final"] == pytest.approx(1_000_000.0 * expected_ccf)
    assert row["risk_weight"] == pytest.approx(1.0)
    assert row["rwa_final"] == pytest.approx(1_000_000.0 * expected_ccf)
    assert not [e for e in errors if e.code == "DQ016"], "a mapped product is not a gap"


# ---------------------------------------------------------------------------
# TR-02 — Art. 166A(5) is IRB-only and final
# ---------------------------------------------------------------------------


def _purchased_receivable_bundle(approach: str | None) -> Any:
    perms = (
        [make_model_permission(approach=approach, exposure_class="corporate")]
        if approach is not None
        else None
    )
    return make_raw_data_bundle(
        counterparties=[make_counterparty(counterparty_reference="CP1")],
        facilities=[
            make_facility(
                facility_reference="F_FACT",
                counterparty_reference="CP1",
                risk_type="FRC",
                limit=1_000_000.0,
                is_revolving=True,
                is_purchased_receivable_commitment=True,
                lgd=0.4,
                ccf_modelled=0.25,
            )
        ],
        loans=[
            make_loan(
                loan_reference="L1",
                counterparty_reference="CP1",
                drawn_amount=0.0,
                interest=0.0,
                lgd=0.4,
            )
        ],
        model_permissions=perms,
        ratings=[make_rating(counterparty_reference="CP1", pd=0.01, model_id="MODEL_01")],
    )


@pytest.mark.parametrize(
    ("regime", "expected_ccf"),
    [
        ("crr", 1.00),  # Annex I 1(e) transactions with recourse
        ("b31", 1.00),  # Table A1 Row 2(a); before the fix 0.40 -> EAD 400,000
    ],
)
def test_tr02_sa_factoring_line_keeps_its_table_a1_bucket(regime: str, expected_ccf: float) -> None:
    """Revolving factoring line with recourse, flagged, SA: 100% in both regimes."""
    # Arrange / Act
    rows, _ = _run(_purchased_receivable_bundle(None), _config(regime))
    row = rows["F_FACT_UNDRAWN"]

    # Assert
    assert row["approach"] == "standardised"
    assert row["ccf"] == pytest.approx(expected_ccf)
    assert row["ead_final"] == pytest.approx(1_000_000.0 * expected_ccf)
    assert row["rwa_final"] == pytest.approx(1_000_000.0 * expected_ccf)


@pytest.mark.parametrize(
    ("regime", "approach", "expected_ccf"),
    [
        ("b31", "foundation_irb", 0.40),
        ("b31", "advanced_irb", 0.40),  # before the fix the own estimate 0.25
        ("crr", "foundation_irb", 1.00),  # CRR: FRC full risk, no 166A(5)
    ],
)
def test_tr02_irb_purchase_commitment(regime: str, approach: str, expected_ccf: float) -> None:
    """B31 IRB rows take the fixed Art. 166A(5) 40%; CRR is untouched."""
    # Arrange / Act
    rows, _ = _run(_purchased_receivable_bundle(approach), _config(regime, PermissionMode.IRB))
    row = rows["F_FACT_UNDRAWN"]

    # Assert
    assert row["approach"] == approach
    assert row["ccf"] == pytest.approx(expected_ccf)
    assert row["ead_final"] == pytest.approx(1_000_000.0 * expected_ccf)
    assert row["rwa_final"] == pytest.approx(row["ead_final"] * row["risk_weight"], rel=1e-9)


# ---------------------------------------------------------------------------
# RE-14 — UK residential mortgage commitments take Row 4(b) 50% unflagged
# ---------------------------------------------------------------------------


def _mortgage_bundle(country: str = "GB", flag: bool | None = None) -> Any:
    facility: dict[str, Any] = {
        "facility_reference": "F1",
        "product_type": "mortgage",
        "book_code": "B",
        "counterparty_reference": "CP1",
        "value_date": date(2024, 1, 1),
        "maturity_date": date(2045, 1, 1),
        "currency": "GBP",
        "limit": 300_000.0,
        "committed": True,
        "is_revolving": False,
        "seniority": "senior",
        "risk_type": None,
        "is_uk_residential_mortgage_commitment": flag,
    }
    counterparty = {
        "counterparty_reference": "CP1",
        "counterparty_name": "CP1",
        "entity_type": "individual",
        "country_code": country,
        "default_status": False,
        "is_natural_person": True,
        "is_managed_as_retail": True,
    }
    loan = {
        "loan_reference": "L1",
        "product_type": "mortgage",
        "book_code": "B",
        "counterparty_reference": "CP1",
        "value_date": date(2024, 1, 1),
        "maturity_date": date(2045, 1, 1),
        "currency": "GBP",
        "drawn_amount": 200_000.0,
        "interest": 0.0,
        "seniority": "senior",
    }
    collateral = {
        "collateral_reference": "C1",
        "collateral_type": "real_estate",
        "currency": "GBP",
        "market_value": 600_000.0,
        "nominal_value": 600_000.0,
        "beneficiary_type": "facility",
        "beneficiary_reference": "F1",
        "property_type": "residential",
        "property_ltv": 0.5,
        "is_qualifying_re": True,
        "valuation_date": date(2026, 6, 30),
        "valuation_type": "market",
    }
    return make_raw_bundle(
        counterparties=pl.DataFrame([counterparty]),
        loans=pl.DataFrame([loan]),
        facilities=pl.DataFrame(
            [facility],
            schema_overrides={
                "risk_type": pl.Utf8,
                "is_uk_residential_mortgage_commitment": pl.Boolean,
            },
        ),
        facility_mappings=pl.DataFrame(
            [{"parent_facility_reference": "F1", "child_reference": "L1", "child_type": "loan"}]
        ),
        collateral=pl.DataFrame([collateral]),
    )


def test_re14_b31_uk_mortgage_commitment_takes_row_4b() -> None:
    """Undrawn 100,000 at Row 4(b) 50% -> EAD 50,000; RRE 20% (LTV 50%) -> RWA 10,000.

    Before the fix: Row 5 40% -> EAD 40,000, RWA 8,000.
    """
    # Arrange / Act
    rows, _ = _run(_mortgage_bundle(), _config("b31"))
    undrawn = rows["F1_UNDRAWN"]

    # Assert
    assert undrawn["ccf"] == pytest.approx(0.50)
    assert undrawn["ead_final"] == pytest.approx(50_000.0)
    assert undrawn["risk_weight"] == pytest.approx(0.20)
    assert undrawn["rwa_final"] == pytest.approx(10_000.0)


def test_re14_b31_non_uk_obligor_is_not_moved() -> None:
    """UK not evidenced (US obligor): Row 5 40% -> EAD 40,000, RWA 8,000 (unchanged)."""
    # Arrange / Act
    rows, _ = _run(_mortgage_bundle(country="US"), _config("b31"))
    undrawn = rows["F1_UNDRAWN"]

    # Assert
    assert undrawn["ccf"] == pytest.approx(0.40)
    assert undrawn["ead_final"] == pytest.approx(40_000.0)


def test_re14_b31_explicit_false_is_not_moved() -> None:
    """An explicit False survives the loader (the flag is tri-state, no default)."""
    # Arrange / Act
    rows, _ = _run(_mortgage_bundle(flag=False), _config("b31"))

    # Assert
    assert rows["F1_UNDRAWN"]["ccf"] == pytest.approx(0.40)


def test_re14_crr_is_untouched() -> None:
    """CRR: null risk_type takes the Annex I 1(k) 100% residual -> EAD 100,000; 35%."""
    # Arrange / Act
    rows, _ = _run(_mortgage_bundle(), _config("crr"))
    undrawn = rows["F1_UNDRAWN"]

    # Assert
    assert undrawn["ccf"] == pytest.approx(1.00)
    assert undrawn["ead_final"] == pytest.approx(100_000.0)
    assert undrawn["rwa_final"] == pytest.approx(35_000.0)
