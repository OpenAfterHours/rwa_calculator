"""
Tests for IRBCalculator.calculate_expected_loss warning emissions.

P1.88: calculate_expected_loss previously silently defaulted PD to 0.01 (1%)
and LGD to 0.45 (45%) when those columns were absent from IRB exposures,
returning errors=[]. Now emits IRB004/IRB005 warnings so consumers can detect
that EL figures are based on placeholder values, not actual model outputs.

References:
    CRR Art. 160: PD floors and estimation requirements
    CRR Art. 161: LGD supervisory values (F-IRB) / own estimates (A-IRB)
    CRR Art. 158: Expected loss calculation EL = PD × LGD × EAD
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import CRMAdjustedBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.errors import ErrorCategory, ErrorSeverity
from rwa_calc.engine.irb.calculator import IRBCalculator

_REPORTING_DATE = date(2026, 1, 1)


# =============================================================================
# HELPERS
# =============================================================================


def _make_crm_bundle(
    *,
    include_pd: bool = True,
    include_lgd: bool = True,
    include_ead_final: bool = False,
) -> CRMAdjustedBundle:
    """Build a minimal CRMAdjustedBundle with optional PD/LGD columns."""
    data: dict[str, list] = {
        "exposure_reference": ["EXP_001", "EXP_002"],
        "ead": [100_000.0, 200_000.0],
    }
    if include_pd:
        data["pd"] = [0.02, 0.05]
    if include_lgd:
        data["lgd"] = [0.40, 0.60]
    if include_ead_final:
        data["ead_final"] = [90_000.0, 180_000.0]

    lf = pl.LazyFrame(data)
    return CRMAdjustedBundle(
        exposures=lf,
        sa_exposures=pl.LazyFrame({"exposure_reference": []}),
        irb_exposures=lf,
    )


# =============================================================================
# TESTS
# =============================================================================


class TestIRBCalculatorELWarnings:
    """IRBCalculator.calculate_expected_loss emits warnings for missing PD/LGD."""

    def test_missing_pd_emits_irb004_warning(self) -> None:
        """When PD column is absent, IRB004 warning is emitted."""
        bundle = _make_crm_bundle(include_pd=False)
        calc = IRBCalculator()
        config = CalculationConfig.crr(_REPORTING_DATE)

        result = calc.calculate_expected_loss(bundle, config)

        irb004 = [e for e in result.errors if e.code == "IRB004"]
        assert len(irb004) == 1
        assert irb004[0].severity == ErrorSeverity.WARNING
        assert irb004[0].category == ErrorCategory.DATA_QUALITY
        assert irb004[0].field_name == "pd"

    def test_missing_lgd_emits_irb005_warning(self) -> None:
        """When LGD column is absent, IRB005 warning is emitted."""
        bundle = _make_crm_bundle(include_lgd=False)
        calc = IRBCalculator()
        config = CalculationConfig.crr(_REPORTING_DATE)

        result = calc.calculate_expected_loss(bundle, config)

        irb005 = [e for e in result.errors if e.code == "IRB005"]
        assert len(irb005) == 1
        assert irb005[0].severity == ErrorSeverity.WARNING
        assert irb005[0].category == ErrorCategory.DATA_QUALITY
        assert irb005[0].field_name == "lgd"

    def test_both_missing_emits_both_warnings(self) -> None:
        """When both PD and LGD are absent, both IRB004 and IRB005 are emitted."""
        bundle = _make_crm_bundle(include_pd=False, include_lgd=False)
        calc = IRBCalculator()
        config = CalculationConfig.crr(_REPORTING_DATE)

        result = calc.calculate_expected_loss(bundle, config)

        codes = {e.code for e in result.errors}
        assert codes == {"IRB004", "IRB005"}
        assert len(result.errors) == 2

    def test_both_present_no_warnings(self) -> None:
        """When both PD and LGD are present, no warnings are emitted."""
        bundle = _make_crm_bundle(include_pd=True, include_lgd=True)
        calc = IRBCalculator()
        config = CalculationConfig.crr(_REPORTING_DATE)

        result = calc.calculate_expected_loss(bundle, config)

        assert result.errors == []

    def test_missing_pd_uses_default_001(self) -> None:
        """When PD is absent, default 0.01 (1%) is used in EL computation."""
        bundle = _make_crm_bundle(include_pd=False, include_lgd=True)
        calc = IRBCalculator()
        config = CalculationConfig.crr(_REPORTING_DATE)

        result = calc.calculate_expected_loss(bundle, config)
        df = result.frame.collect()

        # EL = PD × LGD × EAD = 0.01 × 0.40 × 100,000 = 400
        assert df["expected_loss"][0] == pytest.approx(0.01 * 0.40 * 100_000)
        # Second row: 0.01 × 0.60 × 200,000 = 1,200
        assert df["expected_loss"][1] == pytest.approx(0.01 * 0.60 * 200_000)

    def test_missing_lgd_uses_default_045(self) -> None:
        """When LGD is absent, default 0.45 (45%) is used in EL computation."""
        bundle = _make_crm_bundle(include_pd=True, include_lgd=False)
        calc = IRBCalculator()
        config = CalculationConfig.crr(_REPORTING_DATE)

        result = calc.calculate_expected_loss(bundle, config)
        df = result.frame.collect()

        # EL = PD × LGD × EAD = 0.02 × 0.45 × 100,000 = 900
        assert df["expected_loss"][0] == pytest.approx(0.02 * 0.45 * 100_000)

    def test_ead_final_preferred_over_ead(self) -> None:
        """When ead_final exists, it is used instead of ead."""
        bundle = _make_crm_bundle(include_ead_final=True)
        calc = IRBCalculator()
        config = CalculationConfig.crr(_REPORTING_DATE)

        result = calc.calculate_expected_loss(bundle, config)
        df = result.frame.collect()

        # Should use ead_final (90,000) not ead (100,000)
        assert df["expected_loss"][0] == pytest.approx(0.02 * 0.40 * 90_000)

    def test_warning_includes_regulatory_reference(self) -> None:
        """Warnings include CRR regulatory article references."""
        bundle = _make_crm_bundle(include_pd=False, include_lgd=False)
        calc = IRBCalculator()
        config = CalculationConfig.crr(_REPORTING_DATE)

        result = calc.calculate_expected_loss(bundle, config)

        for err in result.errors:
            assert err.regulatory_reference is not None
            assert "Art. 16" in err.regulatory_reference

    def test_warning_includes_actual_default_values(self) -> None:
        """Warnings document the default values being substituted."""
        bundle = _make_crm_bundle(include_pd=False, include_lgd=False)
        calc = IRBCalculator()
        config = CalculationConfig.crr(_REPORTING_DATE)

        result = calc.calculate_expected_loss(bundle, config)

        pd_warning = next(e for e in result.errors if e.code == "IRB004")
        assert pd_warning.actual_value == "default 0.01"
        lgd_warning = next(e for e in result.errors if e.code == "IRB005")
        assert lgd_warning.actual_value == "default 0.45"

    def test_works_with_basel_31_config(self) -> None:
        """Warning emissions work identically under Basel 3.1 config."""
        bundle = _make_crm_bundle(include_pd=False)
        calc = IRBCalculator()
        config = CalculationConfig.basel_3_1(reporting_date=_REPORTING_DATE)

        result = calc.calculate_expected_loss(bundle, config)

        irb004 = [e for e in result.errors if e.code == "IRB004"]
        assert len(irb004) == 1
