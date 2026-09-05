"""
On-balance-sheet netting reporting portfolio — the oracle for the
agreement-perimeter change (reverses P1.238; see ``on_bs_netting_agreement.md``
decision note referenced from the netting commit).

Pipeline position:
    build_reporting_netting_bundle() -> RawDataBundle -> PipelineOrchestrator
        -> AggregatedResultBundle -> COREPGenerator / Pillar3Generator

Why a NEW portfolio (rather than extending an existing one): the
agreement-perimeter change makes on-balance-sheet netting key on the
``netting_agreement_reference`` ALONE, so a deposit and a loan under the SAME
agreement now net regardless of which counterparty holds which leg (CRR/PS1-26
Art. 195, Art. 205(a), Art. 219). Every existing golden/oracle/reporting
portfolio is number-NEUTRAL to this change — the census that motivated this
fixture found only three fixture files that set
``netting_agreement_reference`` at all (``tests/fixtures/p1_238/``,
``tests/fixtures/p1_241/`` and the ``r1_negative_gross`` portfolio in
``tests/acceptance/reporting/test_r1_negative_gross_carriers.py``), and each of
those puts every leg of its agreement under ONE counterparty. A reference held
by a single counterparty nets identically whether the perimeter key is
``(agreement,)`` or ``(agreement, counterparty)`` — so the change to
``on_bs_netting_perimeter_is_agreement`` cannot move a single number in the
whole estate today. Adding cross-counterparty rows to an existing portfolio
would move that portfolio's committed goldens and bury the actual question —
does a netting agreement spanning counterparties work end to end, and does it
survive turning the Feature back off — in unrelated churn. Same reasoning,
same shape, as ``reporting_offbs_portfolio.py``.

Two-leg design (LESSONS.md B5 / C2 — a scenario must be able to SHOW a
difference, not just exist):

    AGR_SAME (CP_D only)   — a same-counterparty deposit/loan pair. This is
        the cell that SURVIVES either Feature state: whether the perimeter key
        includes ``counterparty_reference`` or not, CP_D's own deposit and its
        own loan always net against each other, so ``NETTING_D`` (GBP
        1,000,000) is identical Feature-enabled or Feature-disabled. It is the
        regression control — if a future change to the netting stage breaks
        even the ORIGINAL, single-counterparty case, this leg catches it
        independently of the agreement-perimeter question.

    AGR_GROUP (CP_A / CP_B / CP_C)  — one deposit held by CP_A, split
        pro-rata (CRR Art. 219 nets drawn-against-drawn; the netting benefit is
        allocated across the offsetting drawn balances in proportion to their
        drawn amount) across two DIFFERENT counterparties' loans, CP_B and
        CP_C, all three sharing ``AGR_GROUP``. This is the cell that MOVES: it
        nets (GBP 3,000,000 total) under the Feature's default
        (``on_bs_netting_perimeter_is_agreement=True``) and does NOT net at all
        (GBP 0) when the Feature is disabled and the perimeter reverts to
        ``(agreement, counterparty)`` keying — CP_A, CP_B and CP_C are three
        different counterparties, so no two of AGR_GROUP's legs share a key
        under the disabled reading.

    CP_E (no agreement reference) — an un-netted control drawn loan, present
        so the portfolio has a comparison row unaffected by netting in either
        state and so C 07.00's on-balance-sheet columns carry more than one
        distinct value.

None of the four counterparties is guaranteed or given a 0%-risk-weight
short-circuit (LESSONS.md C2 — a 0%-RW leg cannot verify a basis move): all
are unrated corporates, so every SA risk weight is the flat 100% CQS.UNRATED /
``None``-key entry in both regimes' corporate lookup table (pack entries
``corporate_risk_weights`` under CRR, ``b31_corporate_risk_weights`` under
Basel 3.1 — see ``src/rwa_calc/rulebook/packs/{crr,b31}.py``; LESSONS.md A4 —
cite the pack entry name, never type the risk weight). With a flat 100% RW and
no collateral/guarantee CRM in play, RWEA equals EAD exactly, so the netting
benefit is visible undiluted in ``rwa_final``.

C 07.00 column exposure — the reporting-template reason this portfolio has to
exist, not just the engine reason: col 0035 "(-) Adjustment due to
on-balance-sheet netting" is emitted on the Basel 3.1 SA sheet ONLY
(``reporting/corep/c07.py`` adds it under ``if is_b31`` — CRR has no column
dedicated to the netting adjustment; the CRR C 07.00 sheet folds the netted
EAD straight into col 0200 "Exposure value", so the netting effect is visible
there but not broken out as its own adjustment column). Before this fixture,
col 0035 and every rule keyed off it were ``NOT_EVALUATED`` end to end
(LESSONS.md B5) because no golden portfolio put non-zero on-balance-sheet
netting through the Basel 3.1 SA branch with more than one counterparty in
play.

CRM016 audit trail: the cross-counterparty offset inside AGR_GROUP is expected
to raise exactly ONE ``CRM016`` warning identifying ``AGR_GROUP`` and stating
it nets "across 3 counterparties" (CP_A, CP_B, CP_C) — see
``tests/fixtures/p1_238/p1_238.py`` for the sibling single-cross-counterparty
form of the same warning. AGR_SAME and CP_E raise none: AGR_SAME never crosses
a counterparty boundary, and CP_E carries no agreement reference at all.

References:
- CRR/PS1-26 Art. 195: on-balance-sheet netting of reciprocal balances.
- CRR Art. 205(a): eligibility of on-balance-sheet netting as CRM.
- CRR Art. 219: drawn-on-drawn cash netting, pro-rata allocation.
- CRR Art. 122 / PS1/26 Art. 122(2) Table 6: unrated corporate 100% SA RW.
- COREP Annex II, C 07.00 col 0035 (Basel 3.1 SA sheet only).
- Pack Feature: ``on_bs_netting_perimeter_is_agreement``.
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, FACILITY_MAPPING_SCHEMA, LOAN_SCHEMA
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants — the single source of truth for test assertions.
# ---------------------------------------------------------------------------

CP_A: str = "NET-CP-A"  # holds the deposit in the GROUP agreement
CP_B: str = "NET-CP-B"  # borrower in the GROUP agreement
CP_C: str = "NET-CP-C"  # borrower in the GROUP agreement
CP_D: str = "NET-CP-D"  # same-counterparty control: its own deposit and loan
CP_E: str = "NET-CP-E"  # un-netted control

AGR_GROUP: str = "NET-AGR-GROUP"  # spans CP_A / CP_B / CP_C — the moving cell
AGR_SAME: str = "NET-AGR-SAME"  # CP_D only — the cell that survives either state

DEP_A: str = "NET-DEP-A"
LN_B: str = "NET-LN-B"
LN_C: str = "NET-LN-C"
DEP_D: str = "NET-DEP-D"
LN_D: str = "NET-LN-D"
LN_E: str = "NET-LN-E"

#: Deposits are negative drawn amounts (CRR Art. 195/219).
DEPOSIT_GROUP: float = -2_000_000.0
DEPOSIT_SAME: float = -1_000_000.0
DRAWN_B: float = 10_000_000.0
DRAWN_C: float = 5_000_000.0
DRAWN_D: float = 4_000_000.0
DRAWN_E: float = 3_000_000.0

#: Pro-rata allocation of DEPOSIT_GROUP's netting benefit across LN_B / LN_C by
#: drawn amount (CRR Art. 219): 2,000,000 * 10/15 and 2,000,000 * 5/15.
NETTING_B: float = 2_000_000.0 * 10.0 / 15.0  # 1,333,333.33...
NETTING_C: float = 2_000_000.0 * 5.0 / 15.0  # 666,666.67...
NETTING_D: float = 1_000_000.0

#: Total on-balance-sheet netting benefit, Feature enabled (agreement
#: perimeter, the default) vs disabled (reverts to P1.238 single-counterparty
#: keying, under which only AGR_SAME's same-counterparty legs net).
TOTAL_NETTING_ENABLED: float = 3_000_000.0
TOTAL_NETTING_DISABLED: float = 1_000_000.0

#: Sealed gross on-balance-sheet carriers floor negative (deposit) balances to
#: zero (see tests/acceptance/reporting/test_r1_negative_gross_carriers.py),
#: so the portfolio's gross on-BS total is the sum of the four POSITIVE loan
#: balances only: 10,000,000 + 5,000,000 + 4,000,000 + 3,000,000.
GROSS_ON_BS: float = 22_000_000.0

#: Total EAD / RWA (100% unrated-corporate RW, no other CRM) with the netting
#: benefit applied vs withheld.
EXPOSURE_VALUE_ENABLED: float = 19_000_000.0
EXPOSURE_VALUE_DISABLED: float = 21_000_000.0

#: Expected on-balance-sheet netting amount per loan leg, Feature enabled
#: (the default). The two deposits (DEP_A, DEP_D) are not loan legs, so they
#: are intentionally absent from this map — see the borrower-side rows only.
EXPECTED_NETTING: dict[str, float] = {
    LN_B: NETTING_B,
    LN_C: NETTING_C,
    LN_D: NETTING_D,
    LN_E: 0.0,
}

#: Pack Feature gating the agreement-perimeter keying.
NETTING_FEATURE: str = "on_bs_netting_perimeter_is_agreement"

_VALUE_DATE: date = date(2020, 1, 1)
#: Later than both reporting dates used by the golden test (CRR 2025-12-31,
#: Basel 3.1 2027-06-01), and EQUAL across every row including the deposits,
#: so no Art. 237-239 maturity-mismatch haircut perturbs the netting figures.
_MATURITY: date = date(2031, 12, 31)


# ---------------------------------------------------------------------------
# Main public entry point
# ---------------------------------------------------------------------------


def build_reporting_netting_bundle() -> RawDataBundle:
    """Assemble the on-balance-sheet netting reporting portfolio as a sealed bundle.

    Sealed against the loader edge contracts by ``make_raw_bundle``, so it is
    shape-identical to a parquet-loaded production bundle. Run it through
    ``PipelineOrchestrator().run_with_data`` under either regime with
    ``PermissionMode.STANDARDISED`` — every counterparty is an unrated
    corporate, so every exposure routes SA regardless of permission mode.
    """
    return make_raw_bundle(
        counterparties=_counterparties(),
        loans=_loans(),
        facility_mappings=_facility_mappings(),
    )


# ---------------------------------------------------------------------------
# Table builders (private)
# ---------------------------------------------------------------------------


def _counterparties() -> pl.DataFrame:
    """Five unrated corporates. No ratings table at all, so every row is
    unrated in both regimes — a flat 100% SA risk weight (CRR Art. 122 / PS1/26
    Art. 122(2) Table 6, pack entries ``corporate_risk_weights`` /
    ``b31_corporate_risk_weights``) with no guarantee or 0%-RW short-circuit to
    dilute the netting effect (LESSONS.md C2). ``annual_revenue`` is above the
    SME ceiling so no supporting factor perturbs the RWEA.
    """
    rows: list[dict] = [
        {
            "counterparty_reference": cp,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 250_000_000.0,
        }
        for cp in (CP_A, CP_B, CP_C, CP_D, CP_E)
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA))


def _loans() -> pl.DataFrame:
    """Two deposits (negative drawn amounts) and four loans.

    Every row shares ``product_type="term_loan"``, ``seniority="senior"`` and
    identical ``value_date`` / ``maturity_date`` — equal maturities across a
    netting set avoid any Art. 237-239 mismatch haircut, so the only effect in
    play is the on-balance-sheet netting itself.
    """
    common: dict = {
        "product_type": "term_loan",
        "currency": "GBP",
        "value_date": _VALUE_DATE,
        "maturity_date": _MATURITY,
        "seniority": "senior",
        "interest": 0.0,
    }
    rows: list[dict] = [
        # -- AGR_GROUP: one deposit (CP_A) nets pro-rata across two BORROWERS
        # under different counterparties (CP_B, CP_C) sharing the agreement.
        # This is the leg that only nets when the perimeter key is the
        # agreement alone.
        {
            "loan_reference": DEP_A,
            "counterparty_reference": CP_A,
            "drawn_amount": DEPOSIT_GROUP,
            "netting_agreement_reference": AGR_GROUP,
            **common,
        },
        {
            "loan_reference": LN_B,
            "counterparty_reference": CP_B,
            "drawn_amount": DRAWN_B,
            "netting_agreement_reference": AGR_GROUP,
            **common,
        },
        {
            "loan_reference": LN_C,
            "counterparty_reference": CP_C,
            "drawn_amount": DRAWN_C,
            "netting_agreement_reference": AGR_GROUP,
            **common,
        },
        # -- AGR_SAME: CP_D's own deposit and own loan. Nets under EITHER
        # Feature state — the regression control for the original,
        # single-counterparty netting case.
        {
            "loan_reference": DEP_D,
            "counterparty_reference": CP_D,
            "drawn_amount": DEPOSIT_SAME,
            "netting_agreement_reference": AGR_SAME,
            **common,
        },
        {
            "loan_reference": LN_D,
            "counterparty_reference": CP_D,
            "drawn_amount": DRAWN_D,
            "netting_agreement_reference": AGR_SAME,
            **common,
        },
        # -- CP_E: un-netted control, no agreement reference at all.
        {
            "loan_reference": LN_E,
            "counterparty_reference": CP_E,
            "drawn_amount": DRAWN_E,
            "netting_agreement_reference": None,
            **common,
        },
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(LOAN_SCHEMA))


def _facility_mappings() -> pl.DataFrame:
    """No facilities in this portfolio — an empty, correctly-typed frame.

    ``make_raw_bundle`` requires the table to be sealable even when unused
    (mirrors ``tests/fixtures/p1_238/p1_238.py``).
    """
    return pl.DataFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA))
