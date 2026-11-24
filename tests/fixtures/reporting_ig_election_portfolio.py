"""
Investment-grade elections — the Art. 122(8)(b) floor election without the Art. 122(6) permission.

Pipeline position:
    build_reporting_ig_election_bundle() -> RawDataBundle
        -> PipelineOrchestrator (Basel 3.1, PermissionMode.IRB, 2027-06-01,
           ig_election_config: election ON, permission OFF)
        -> AggregatedResultBundle -> COREPGenerator (OF 08.01 rows 0190 / 0200,
           OF 07.00, OF 02.01 output floor)

Why this portfolio exists (P1.475, ``.claude/LESSONS.md`` B5). PS1/26 Art. 122
holds two investment-grade elections for unrated non-SME corporates, and the
engine used to drive both from one flag:

- Art. 122(6) — a PRA *permission* for the Standardised Approach (65% IG /
  135% not IG; without it Art. 122(5) gives 100%);
- Art. 122(8) — the output-floor choice for the corporates the firm weights
  under the IRB Approach: (a) 100%, or (b) the paragraph 6 weights, "An
  institution that assigns, or ceases to assign, risk weights in accordance
  with this point (b) shall give notice to the PRA" — notice, not permission.

This book holds the combination one flag could not express — the (8)(b) notice
WITHOUT the (6) permission — and it is the first registered book with an
investment-grade-assessed IRB leg. The one earlier book that assesses an obligor
investment grade, ``rw-ladder``, is Standardised-only, so OF 08.01 row 0200
"Of which: investment grade" was dead in every registered run and the Tier 2
gate could not see it.

## The five legs — two the election moves, three it must not

    ref              | approach | assessed IG | S-TREA weight | OF 08.01 row 0200?
    -----------------|----------|-------------|---------------|-----------------------------
    IGE-LN-IRB-IG    | F-IRB    | yes         | 65%  (8)(b)   | yes
    IGE-LN-IRB-NIG   | F-IRB    | no          | 135% (8)(b)   | no (row 0190 only)
    IGE-LN-IRB-SME   | F-IRB    | yes         | 85%  para 11  | no: Art. 122(11) sets it
    IGE-LN-IRB-SUB   | F-IRB    | yes         | 150% Art. 133 | no: Art. 112(1)(p), not (g)
    IGE-LN-SA-IG     | SA       | yes         | 100% (5)      | — (no (6) permission)

Drawn 3,000,000 / 2,000,000 / 1,200,000 / 800,000 / 1,500,000, all unrated (no
ECAI assessment), unsecured, on balance sheet.

- ``IGE-LN-IRB-IG`` and ``IGE-LN-IRB-NIG`` are the two-leg pattern B5 asks for on
  OF 08.01 rows 0190 / 0200: both sit in row 0190, only the first in row 0200,
  so a change that ZEROED row 0200 is distinguishable from one that left it.
  Their ``sa_rwa`` is 1,950,000 and 2,700,000 (100% under (8)(a): 3,000,000
  and 2,000,000).
- ``IGE-LN-IRB-SME`` and ``IGE-LN-IRB-SUB`` are assessed investment grade too, but
  another rule sets their output-floor weight, so row 0200 must leave them out
  (the weight-governing reading of Annex II's "consistent with approach used for
  the purpose of calculating the output floor"): the SME (revenue 10m, under the
  GBP 44m ceiling) takes the Art. 122(11) 85% and reports on the SME F-IRB
  sheet; the subordinated loan takes the Art. 133(5) 150% — Table A2 puts it in
  point (p), and Art. 122(8) reaches only "the exposure class set out in point
  (g)" — and stays on the non-SME F-IRB sheet beside the first two. Their
  ``sa_rwa`` (1,020,000 and 1,200,000) is the same under either election. A raw
  ``cp_is_investment_grade`` read would put both in row 0200.
- ``IGE-LN-SA-IG`` is assessed investment grade too, but is weighted under the
  Standardised Approach (no internal rating, so no IRB routing) and the firm
  holds no Art. 122(6) permission: it must stay at the Art. 122(5) 100% — the
  election may not leak onto it. It is also the leg OF 07.00 reads.

Hand calculation (Basel 3.1, election on, permission off): OF 08.01 col 0110
(exposure value) — non-SME F-IRB sheet row 0190 3,000,000 + 2,000,000 + 800,000
= 5,800,000 and row 0200 3,000,000; SME F-IRB sheet row 0190 1,200,000 and row
0200 unreported. S-TREA is the whole book's SA-equivalent RWEA: 1,950,000 +
2,700,000 + 1,020,000 + 1,200,000 + 1,500,000 = 8,370,000 under (8)(b) and
3,000,000 + 2,000,000 + 1,020,000 + 1,200,000 + 1,500,000 = 8,720,000 under
(8)(a); only the two first legs differ. The floor does not bind under either
(``tests/acceptance/reporting/test_of08_investment_grade_election.py`` measures
U-TREA against the threshold), so the reported total is unchanged.

What it is NOT: a CRR book (CRR Art. 122 has no investment-grade approach and
there is no output floor) or a book holding the Art. 122(6) permission.
Registered under Basel 3.1 only.

References:
- PRA PS1/26 Art. 122(5), (6), (8), (9); Art. 92(3A)(b)(ii)
- PRA PS1/26 Annex II, OF 08.01 rows 0190 / 0200 (printed p.118)
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, LOAN_SCHEMA, RATINGS_SCHEMA
from rwa_calc.domain.enums import PermissionMode
from tests.fixtures.irb_test_helpers import create_full_irb_model_permissions
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants — the single source of truth for test assertions.
# ---------------------------------------------------------------------------

#: Must match ``create_full_irb_model_permissions`` or no row routes IRB.
_MODEL_ID: str = "TEST_FULL_IRB"

REPORTING_DATE: date = date(2027, 6, 1)
PRIOR_REPORTING_DATE: date = date(2027, 1, 1)

CP_IRB_IG: str = "IGE-CP-IRB-IG"
CP_IRB_NIG: str = "IGE-CP-IRB-NIG"
CP_IRB_SME: str = "IGE-CP-IRB-SME"
CP_IRB_SUB: str = "IGE-CP-IRB-SUB"
CP_SA_IG: str = "IGE-CP-SA-IG"

LN_IRB_IG: str = "IGE-LN-IRB-IG"
LN_IRB_NIG: str = "IGE-LN-IRB-NIG"
LN_IRB_SME: str = "IGE-LN-IRB-SME"
LN_IRB_SUB: str = "IGE-LN-IRB-SUB"
LN_SA_IG: str = "IGE-LN-SA-IG"

DRAWN_IRB_IG: float = 3_000_000.0
DRAWN_IRB_NIG: float = 2_000_000.0
DRAWN_IRB_SME: float = 1_200_000.0
DRAWN_IRB_SUB: float = 800_000.0
DRAWN_SA_IG: float = 1_500_000.0

#: Internal PDs, above the Art. 160(1) 0.05% Basel 3.1 corporate floor.
PD_IRB_IG: float = 0.0040
PD_IRB_NIG: float = 0.0200
PD_IRB_SME: float = 0.0040
PD_IRB_SUB: float = 0.0040

#: Annual revenue: 400m is a large-ish non-SME corporate; 10m is under the GBP 44m
#: SME ceiling, so the SME obligor's unrated leg takes Art. 122(11) 85%.
_REVENUE_NON_SME: float = 400_000_000.0
_REVENUE_SME: float = 10_000_000.0

_VALUE_DATE: date = date(2024, 1, 1)
_MATURITY: date = date(2031, 12, 31)


# ---------------------------------------------------------------------------
# Main public entry point
# ---------------------------------------------------------------------------


def build_reporting_ig_election_bundle() -> RawDataBundle:
    """Assemble the investment-grade election book as a sealed ``RawDataBundle``.

    Run it under :func:`ig_election_config` (Art. 122(8)(b) election on, no
    Art. 122(6) permission); :func:`ig_election_config` with ``election=False``
    is the Art. 122(8)(a) comparison run on the identical bundle.
    """
    return make_raw_bundle(
        counterparties=_counterparties(),
        loans=_loans(),
        ratings=_ratings(),
        model_permissions=create_full_irb_model_permissions(),
    )


def ig_election_config(
    *, election: bool = True, reporting_date: date = REPORTING_DATE
) -> CalculationConfig:
    """The registered config: IRB permission, the (8)(b) notice, no (6) permission.

    ``enforce_retail_granularity=False`` is the production default since RE-04
    and decides nothing here (no retail obligor); stated rather than inherited.
    """
    return CalculationConfig.basel_3_1(
        reporting_date=reporting_date,
        permission_mode=PermissionMode.IRB,
        sa_investment_grade_permission=False,
        output_floor_investment_grade_election=election,
        enforce_retail_granularity=False,
    )


def ig_election_prior_config() -> CalculationConfig:
    """The same elections at an earlier reference date, for C 08.04's opening balance."""
    return ig_election_config(reporting_date=PRIOR_REPORTING_DATE)


# ---------------------------------------------------------------------------
# Table builders (private)
# ---------------------------------------------------------------------------


def _counterparties() -> pl.DataFrame:
    """Five unrated corporates; all but ``CP_IRB_NIG`` assessed investment grade.

    Revenue 400m sits above the GBP 44m SME ceiling (so Art. 122(11) 85% does
    not apply) and below the large-corporate threshold, so those IRB legs report
    on the "other general corporates - non-SME" F-IRB sheet. ``CP_IRB_SME`` has
    10m, so it is an SME and reports on the SME F-IRB sheet.
    """
    rows: list[dict] = [
        {
            "counterparty_reference": reference,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": revenue,
            "default_status": False,
            # The firm's own Art. 122(9)-(10) assessment, not an ECAI rating.
            "is_investment_grade": is_ig,
        }
        for reference, is_ig, revenue in (
            (CP_IRB_IG, True, _REVENUE_NON_SME),
            (CP_IRB_NIG, False, _REVENUE_NON_SME),
            (CP_IRB_SME, True, _REVENUE_SME),
            (CP_IRB_SUB, True, _REVENUE_NON_SME),
            (CP_SA_IG, True, _REVENUE_NON_SME),
        )
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA))


def _ratings() -> pl.DataFrame:
    """Internal PDs for the four IRB obligors only; ``CP_SA_IG`` has none, so it routes SA."""
    rows: list[dict] = [
        {
            "rating_reference": f"IGE-RTG-{reference}",
            "counterparty_reference": reference,
            "rating_type": "internal",
            "pd": pd,
            "model_id": _MODEL_ID,
            "rating_date": _VALUE_DATE,
        }
        for reference, pd in (
            (CP_IRB_IG, PD_IRB_IG),
            (CP_IRB_NIG, PD_IRB_NIG),
            (CP_IRB_SME, PD_IRB_SME),
            (CP_IRB_SUB, PD_IRB_SUB),
        )
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(RATINGS_SCHEMA))


def _loans() -> pl.DataFrame:
    """One drawn, unsecured term loan per obligor (no firm LGD -> F-IRB).

    Senior except ``LN_IRB_SUB``, which is subordinated: Art. 133(5) 150% for the
    output floor, and the F-IRB subordinated LGD in its own RWEA.
    """
    rows: list[dict] = [
        {
            "loan_reference": reference,
            "counterparty_reference": counterparty,
            "product_type": "term_loan",
            "drawn_amount": drawn,
            "currency": "GBP",
            "value_date": _VALUE_DATE,
            "maturity_date": _MATURITY,
            "seniority": seniority,
        }
        for reference, counterparty, drawn, seniority in (
            (LN_IRB_IG, CP_IRB_IG, DRAWN_IRB_IG, "senior"),
            (LN_IRB_NIG, CP_IRB_NIG, DRAWN_IRB_NIG, "senior"),
            (LN_IRB_SME, CP_IRB_SME, DRAWN_IRB_SME, "senior"),
            (LN_IRB_SUB, CP_IRB_SUB, DRAWN_IRB_SUB, "subordinated"),
            (LN_SA_IG, CP_SA_IG, DRAWN_SA_IG, "senior"),
        )
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(LOAN_SCHEMA))
