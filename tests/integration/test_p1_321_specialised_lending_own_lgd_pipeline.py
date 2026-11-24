"""P1.321 end to end: a specialised-lending A-IRB row keeps its own LGD at any obligor size.

PS1/26 Art. 147(4C) assigns a corporate exposure to the financial-and-large subclass
only if "(a) they do not fall within the specialised lending exposure subclass
referred to in point (c)(i) of paragraph 2; and (b) the exposures are to: (i)
financial sector entities; or (ii) 'large' corporates with annual revenue of more
than GBP 440 million". Art. 147A(1)(e)(ii) restricts that subclass to the Foundation
IRB Approach, while Art. 147A(1)(d)(iii) leaves object, project and commodities
finance open to "the Advanced IRB Approach for exposures where permission has been
granted under Article 143(2A) or (2B)".

Before P1.321 the restriction ignored limb (a). A project-finance row whose obligor
is typed ``corporate`` and is large (or of unknown revenue, which the engine treats
as large) stayed on A-IRB, but the F-IRB LGD-clearing step nulled its own LGD. The
IRB calculator then priced it on the 40% senior-unsecured fallback with a BR001
warning. The unit tests in ``tests/unit/test_b31_approach_restrictions.py`` pin the
classifier exit; this module pins the RESULT, through ``PipelineOrchestrator``, on
the conformance portfolio's own rows (``tests/conformance/portfolios.py``: a GB
corporate with an internal PD and the firm LGD estimate, plus a project-finance
specialised-lending record).

CRR has no financial-and-large subclass, so the CRR leg is the control: the same
rows were always A-IRB on their own LGD there.

References:
- PRA PS1/26 Art. 147(4C)(a)-(b), Art. 147A(1)(d)(iii), Art. 147A(1)(e)(ii)
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.domain.enums import ApproachType
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.conformance.portfolios import FIRM_LGD, Combination, build_bundle, config_for

#: The fallback code the IRB calculator raises when an A-IRB row has no LGD.
_MISSING_LGD_FALLBACK_CODE = "BR001"

#: Obligor sizes the restriction would treat as large: GBP 600m revenue, and an
#: unknown revenue (the engine's conservative default, CLS008).
_SIZE_BANDS: tuple[str, ...] = ("large", "none")


def _run(regime: str) -> tuple[dict[str, dict], set[str | None]]:
    """Run one corporate-typed, project-finance A-IRB row per size band."""
    combos = tuple(
        Combination(regime, "corporate", size_band, "pd_lgd", "slotting")
        for size_band in _SIZE_BANDS
    )
    bundle = build_bundle(combos)
    # build_bundle writes one drawn loan per combination, in combination order.
    loan_references = bundle.loans.select("loan_reference").collect().to_series().to_list()
    result = PipelineOrchestrator().run_with_data(bundle, config_for(regime))
    frame = result.results.collect() if isinstance(result.results, pl.LazyFrame) else result.results
    by_reference = {row["exposure_reference"]: row for row in frame.to_dicts()}
    rows = {
        size_band: by_reference[reference]
        for size_band, reference in zip(_SIZE_BANDS, loan_references, strict=True)
    }
    fallback_references = {
        error.exposure_reference
        for error in result.errors
        if error.code == _MISSING_LGD_FALLBACK_CODE
    }
    return rows, fallback_references


@pytest.mark.parametrize("regime", ["CRR", "B31"])
@pytest.mark.parametrize("size_band", _SIZE_BANDS)
def test_project_finance_row_is_airb_on_its_own_lgd(regime: str, size_band: str) -> None:
    """The row is priced A-IRB on the firm's 35% LGD estimate, not the 40% fallback.

    Pre-P1.321 (Basel 3.1): approach advanced_irb but lgd_floored 0.40 (the fallback),
    RWA 651,667.80 against 570,209.33 on the own LGD.
    """
    # Arrange / Act
    rows, _fallbacks = _run(regime)
    row = rows[size_band]

    # Assert
    assert (row["approach_applied"], row["lgd_floored"]) == (
        ApproachType.AIRB.value,
        pytest.approx(FIRM_LGD),
    )


@pytest.mark.parametrize("regime", ["CRR", "B31"])
def test_project_finance_rows_raise_no_missing_lgd_fallback(regime: str) -> None:
    """No BR001: the own LGD reached the IRB calculator."""
    # Arrange / Act
    rows, fallbacks = _run(regime)

    # Assert
    flagged = {
        size_band for size_band, row in rows.items() if row["exposure_reference"] in fallbacks
    }
    assert not flagged, (
        f"{regime}: the A-IRB project-finance row(s) for size band(s) {sorted(flagged)} fell "
        "back to the supervisory LGD - the Art. 147(4C)(a) exclusion did not hold"
    )
