"""
P1.94e scenario constants: reporting_date transitional gate on Art. 123B currency-mismatch
multiplier.

Pipeline position:
    SACalculator.apply_currency_mismatch_multiplier  (namespace.py)
    -> date gate: config.reporting_date < B31_EFFECTIVE_DATE => suppress multiplier

Key responsibilities:
- Provide the two reporting dates (Run A: pre-2027, Run B: on 2027-01-01) and the
  corresponding expected outputs for the transitional suppression test.
- No parquet artefacts are written; the test drives calculate_single_sa_exposure()
  directly, varying only config.reporting_date over a single in-memory row.

Scenario design:

    Single FX-mismatched unhedged retail_other exposure (identical to P194A_UNHEDGED):
        - counterparty_income_currency = GBP
        - exposure currency            = EUR  (currency mismatch)
        - exposure_class               = retail_other
        - is_hedged                    = False
        - ead_final                    = 100,000.00
        - pre-multiplier risk_weight   = 0.75  (PRA PS1/26 Art. 123(1))

    Run A  (REPORTING_DATE_PRE_2027 = 2026-12-31):
        config.reporting_date < B31_EFFECTIVE_DATE (2027-01-01) is True
        => transitional gate fires => multiplier suppressed
        => risk_weight = 0.75, rwa = 75,000, currency_mismatch_multiplier_applied = False

    Run B  (REPORTING_DATE_B31 = 2027-01-01):
        strict < comparison: 2027-01-01 NOT < 2027-01-01 is False
        => gate does not fire => eligibility test fires (retail + mismatch + unhedged)
        => risk_weight = min(0.75 x 1.5, 1.50) = 1.125
        => rwa = 112,500, currency_mismatch_multiplier_applied = True

Hand-calculation (Basel 3.1, Art. 123B, PS1/26 commencement 1 January 2027):

    B31_EFFECTIVE_DATE          = 2027-01-01
    B31_CURRENCY_MISMATCH_MULT  = 1.50
    SA_RETAIL_BASE_RW           = 0.75   (Art. 123(1) non-mortgage retail)

    Run A: 2026-12-31 < 2027-01-01 => True => RW unchanged = 0.75
           RWA = 100,000 x 0.75 = 75,000.00

    Run B: 2027-01-01 < 2027-01-01 => False => multiplier applies
           RW = 0.75 x 1.50 = 1.125
           RWA = 100,000 x 1.125 = 112,500.00

Regulatory references:
    - PRA PS1/26 Art. 123B(3): transitional treatment; commencement 1 January 2027.
    - PRA PS1/26 Art. 123(1): retail non-mortgage SA risk weight = 75%.
    - BCBS CRE20.93: currency mismatch multiplier effective date.
    - tests/fixtures/p1_94a/p1_94a.py: canonical row shape (reused by P1.94e test).
    - tests/fixtures/single_exposure.py: calculate_single_sa_exposure helper.
    - src/rwa_calc/data/tables/b31_risk_weights.py: B31_EFFECTIVE_DATE (new scalar),
      B31_CURRENCY_MISMATCH_MULTIPLIER, B31_CURRENCY_MISMATCH_RW_CAP.
    - src/rwa_calc/engine/sa/namespace.py: apply_currency_mismatch_multiplier.

Usage:
    Python-only; no parquet artefacts. Import constants in test file:
        from tests.fixtures.p1_94e.p1_94e import (
            REPORTING_DATE_PRE_2027,
            REPORTING_DATE_B31,
            EAD,
            RW_PRE_2027,
            RWA_PRE_2027,
            RW_B31,
            RWA_B31,
            CURRENCY_MISMATCH_MULTIPLIER,
        )
"""

from __future__ import annotations

from datetime import date

# ---------------------------------------------------------------------------
# Input constants
# ---------------------------------------------------------------------------

#: Exposure drawn amount (EAD = drawn, no CRM, no interest)
EAD: float = 100_000.0

#: Exposure currency — mismatched against borrower income currency (GBP)
EXPOSURE_CURRENCY: str = "EUR"

#: Borrower income currency — triggers Art. 123B when loan currency differs
BORROWER_INCOME_CURRENCY: str = "GBP"

#: Hedge flag — False means multiplier eligibility is open
IS_HEDGED: bool = False

# ---------------------------------------------------------------------------
# Regulatory scalars (single source of truth for test assertions)
# ---------------------------------------------------------------------------

#: Basel 3.1 framework commencement date (PRA PS1/26 effective date)
B31_EFFECTIVE_DATE: date = date(2027, 1, 1)

#: Art. 123B currency-mismatch multiplier
CURRENCY_MISMATCH_MULTIPLIER: float = 1.50

#: Art. 123B RW cap (applied after multiplier)
CURRENCY_MISMATCH_RW_CAP: float = 1.50

#: Base SA retail non-mortgage risk weight (Art. 123(1))
SA_RETAIL_BASE_RW: float = 0.75

# ---------------------------------------------------------------------------
# Run A — reporting_date 2026-12-31 (pre-effective date; multiplier suppressed)
# ---------------------------------------------------------------------------

#: Run A reporting date: one day before the B31 commencement date.
REPORTING_DATE_PRE_2027: date = date(2026, 12, 31)

#: Run A expected risk_weight: base retail RW (no multiplier; gate fires).
RW_PRE_2027: float = SA_RETAIL_BASE_RW  # 0.75

#: Run A expected RWA: EAD x 0.75 = 75,000.
RWA_PRE_2027: float = EAD * RW_PRE_2027  # 75,000.00

#: Run A expected currency_mismatch_multiplier_applied flag.
MULTIPLIER_APPLIED_PRE_2027: bool = False

# ---------------------------------------------------------------------------
# Run B — reporting_date 2027-01-01 (on effective date; multiplier fires)
# ---------------------------------------------------------------------------

#: Run B reporting date: exactly 2027-01-01 (boundary-in-scope test).
REPORTING_DATE_B31: date = date(2027, 1, 1)

#: Run B expected risk_weight: min(0.75 x 1.5, 1.50) = 1.125.
RW_B31: float = min(SA_RETAIL_BASE_RW * CURRENCY_MISMATCH_MULTIPLIER, CURRENCY_MISMATCH_RW_CAP)

#: Run B expected RWA: EAD x 1.125 = 112,500.
RWA_B31: float = EAD * RW_B31  # 112,500.00

#: Run B expected currency_mismatch_multiplier_applied flag.
MULTIPLIER_APPLIED_B31: bool = True
