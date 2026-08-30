"""
Off-balance-sheet reporting portfolio — the oracle for the CCF-bucket axis.

Pipeline position:
    build_reporting_offbs_bundle() -> RawDataBundle -> PipelineOrchestrator
        -> AggregatedResultBundle -> COREPGenerator / Pillar3Generator

Why a THIRD portfolio (rather than extending ``reporting_portfolio.py``):
the rich portfolio is entirely on-balance-sheet — every one of its 14 loan rows
is drawn, so across all 26 committed golden files **not a single** C 07.00 row
carries a value in the CCF-bucket columns 0160 / 0170 / 0171 / 0180 / 0190.
Adding off-balance-sheet rows there would move every existing golden at once and
bury the CCF question in unrelated churn. This portfolio is small and
OBS-shaped, so the diff stays readable and the existing golden gate keeps its
meaning. Same reasoning, same shape, as ``reporting_ccr_portfolio.py``.

Composition — every row exists to land in one named CCF bucket, in BOTH regimes.
The regime pair is the point: CRR Art. 111 / Annex I has four buckets (0 / 20 /
50 / 100%) and PRA PS1/26 Art. 111 Table A1 has five (10 / 20 / 40 / 50 / 100%),
so the same row can and does move column between the two.

    ref                | Annex I / Table A1 basis                | CRR    | B3.1
    -------------------|-----------------------------------------|--------|-------
    LN_CORP_DRAWN      | on-balance-sheet anchor (no CCF)         |   --   |   --
    CT_GUARANTEE       | para 1(a) / Row 1 direct credit sub.     | 100%   | 100%
    CT_FRC_FWD         | para 2 FRC / Row 2 certain drawdown      | 100%   | 100%
    CT_STANDBY_MR      | para 2 issued / Row 3 non-substitute     |  50%   |  50%
    CT_DOC_CREDIT      | para 3(a) / Row 6(a) self-liquidating LC |  20%   |  20%
    FAC_NIF            | para 2 / Row 4(a) NIF                    |  50%   |  50%
    FAC_OC             | item 2(b) / Row 5 "other commitments"    |  50%   |  40%
    FAC_UCC            | para 4(a) / Row 7 uncond. cancellable    |   0%   |  10%

    -> C 07.00 columns   CRR: 0160 FAC_UCC | 0170 CT_DOC_CREDIT
                              0180 CT_STANDBY_MR + FAC_NIF + FAC_OC
                              0190 CT_GUARANTEE + CT_FRC_FWD
                         B31: 0160 FAC_UCC | 0170 CT_DOC_CREDIT | 0171 FAC_OC
                              0180 CT_STANDBY_MR + FAC_NIF
                              0190 CT_GUARANTEE + CT_FRC_FWD

``FAC_OC`` is the load-bearing row: it is the ONLY source of the Basel 3.1 40%
bucket (col 0171), which has no CRR counterpart at all — CRR splits "other
commitments" on ORIGINAL maturity into 50% (item 2(b), > 1yr) / 20% (item 3(b),
<= 1yr) and Table A1 Row 5 replaces that with a flat 40%. Its value_date /
maturity_date span ~12 years so the CRR arm resolves unambiguously to item 2(b).

``FAC_UCC`` carries ``committed=True`` deliberately. An unconditionally
cancellable line is modelled here by ``risk_type="LR"``, NOT by
``committed=False``: a ``committed=False`` facility emits no synthetic undrawn
exposure at all (``engine/hierarchy/facility_undrawn.py`` filters it out),
so it could never reach a C 07.00 CCF bucket. The LR route is also the one that
shows the headline Basel 3.1 change — UCC moves from 0% to 10%, i.e. from a
zero-EAD row to a real one, in the same column.

Deliberately OUT of scope (each already has a dedicated fixture, and each would
add a row without adding a bucket):
- CRR Annex I item 3(b) short-original-maturity OC (20%). Exercising it needs a
  commitment whose ORIGINAL term is <= 1 year, which cannot be live at both the
  CRR (2025-12-31) and Basel 3.1 (2027-06-01) reporting dates — the row would be
  about maturity handling, not about the CCF axis.
- PRA Table A1 Row 4(b) UK residential mortgage commitment 50% override — see
  ``tests/fixtures/p2_33`` (P2.33 / B31-D.CCF9).
- Art. 166E(5) revolving purchased-receivables commitments — ``tests/fixtures/p2_32``.
- F-IRB / A-IRB CCFs (Art. 166(8)/(10), Art. 166C/166D). The portfolio is run
  ``PermissionMode.STANDARDISED`` because C 07.00 is the SA template: its CCF
  columns are defined over the Art. 111 / Table A1 schedule, and an F-IRB row
  (e.g. the Art. 166(8)(d) 75%) has no bucket to land in.

This portfolio was built BEFORE the C 07.00 CCF-bucket fix and exposed three
defects, all since corrected (2026-08-01) — the goldens now capture the fixed
behaviour:

1. ``reporting/corep/c07.py`` bucketed on a column named ``ccf_applied``, which
   no pipeline run produces; the sealed aggregator exit carries ``ccf``. Every
   real submission published structurally-null CCF columns.
2. The bucket cells summed the POST-conversion ``ead_final``. Annex II heads that
   block "fully adjusted exposure value of off-balance sheet items", i.e. the
   PRE-conversion value — so ``boe_b0471`` and ``v6364_m`` could not close even
   once the columns were populated. They now sum ``reporting_gross_off_bs``.
3. ``obs_product`` did not survive the hierarchy stage, so the CRR Annex I /
   Art. 111(1) product -> risk_type fill in ``engine/ccf.py`` was unreachable
   end-to-end. ``CT_DOC_CREDIT`` carries NO explicit ``risk_type`` precisely so
   this portfolio proves the fill is live.

The identities this portfolio exists to make evaluable now close exactly — see
``test_reporting_offbs_golden.py``, which pins both.

References:
- CRR Art. 111(1) + Annex I paras 1-4: SA CCF categories (FR/FRC/MR/MLR/LR)
- PRA PS1/26 Art. 111(1) Table A1 Rows 1-7: revised SA CCFs (10% and 40% added)
- COREP Annex II, C 07.00 cols 0160-0190: exposure value by CCF bucket
- docs/specifications/crr/credit-conversion-factors.md
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    CONTINGENTS_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants — the single source of truth for test assertions.
# ---------------------------------------------------------------------------

CP_CORP: str = "OBS-CP-CORP"  # corporate, CQS 3 -> 100% RW (CRR Art. 122(1))
CP_INST: str = "OBS-CP-INST"  # institution, CQS 2 -> 50% RW (CRR Art. 120(1))

LN_CORP_DRAWN: str = "OBS-LN-CORP"  # drawn under FAC_OC — the on-BS anchor

CT_GUARANTEE: str = "OBS-CT-GUARANTEE"  # FR   -> 100% / 100%
CT_FRC_FWD: str = "OBS-CT-FRC-FWD"  # FRC  -> 100% / 100%
CT_STANDBY_MR: str = "OBS-CT-STANDBY"  # MR_ISSUED -> 50% / 50%
CT_DOC_CREDIT: str = "OBS-CT-DOCCREDIT"  # MLR  ->  20% /  20%

FAC_NIF: str = "OBS-FAC-NIF"  # MR   ->  50% /  50%
FAC_OC: str = "OBS-FAC-OC"  # OC   ->  50% /  40%
FAC_UCC: str = "OBS-FAC-UCC"  # LR   ->   0% /  10%

#: ``<facility>_UNDRAWN`` is the synthetic exposure_reference the hierarchy
#: stage mints for undrawn headroom (facility_undrawn.py).
UNDRAWN_SUFFIX: str = "_UNDRAWN"

#: Off-balance-sheet nominal / undrawn amounts, in GBP. Distinct per row so a
#: mis-bucketed exposure is identifiable from the C 07.00 cell value alone.
NOMINAL_GUARANTEE: float = 2_000_000.0
NOMINAL_FRC_FWD: float = 2_500_000.0
NOMINAL_STANDBY: float = 1_000_000.0
NOMINAL_DOC_CREDIT: float = 1_500_000.0
LIMIT_NIF: float = 5_000_000.0
LIMIT_OC: float = 10_000_000.0
LIMIT_UCC: float = 3_000_000.0
DRAWN_CORP: float = 4_000_000.0
#: FAC_OC headroom = limit - drawn child loan (facility_undrawn.py).
UNDRAWN_OC: float = LIMIT_OC - DRAWN_CORP

_VALUE_DATE: date = date(2020, 1, 1)
_MATURITY: date = date(2031, 12, 31)  # > both reporting dates (CRR 2025, B31 2027)

#: Every off-balance-sheet exposure_reference this portfolio produces, and the
#: CCF each must resolve to per regime. Consumed by the fixture-integrity test.
OFFBS_EXPECTED_CCF: dict[str, tuple[float, float]] = {
    # exposure_reference:            (CRR ccf, Basel 3.1 ccf)
    CT_GUARANTEE: (1.0, 1.0),
    CT_FRC_FWD: (1.0, 1.0),
    CT_STANDBY_MR: (0.5, 0.5),
    CT_DOC_CREDIT: (0.2, 0.2),
    FAC_NIF + UNDRAWN_SUFFIX: (0.5, 0.5),
    FAC_OC + UNDRAWN_SUFFIX: (0.5, 0.4),
    FAC_UCC + UNDRAWN_SUFFIX: (0.0, 0.1),
}


# ---------------------------------------------------------------------------
# Main public entry point
# ---------------------------------------------------------------------------


def build_reporting_offbs_bundle() -> RawDataBundle:
    """Assemble the off-balance-sheet reporting portfolio as a sealed bundle.

    Sealed against the loader edge contracts by ``make_raw_bundle``, so it is
    shape-identical to a parquet-loaded production bundle. Run it through
    ``PipelineOrchestrator().run_with_data`` under either regime with
    ``PermissionMode.STANDARDISED`` — C 07.00 is the SA template and the CCF
    columns are defined over the Art. 111 / Table A1 schedule.
    """
    return make_raw_bundle(
        counterparties=_counterparties(),
        loans=_loans(),
        contingents=_contingents(),
        facilities=_facilities(),
        facility_mappings=_facility_mappings(),
        ratings=_ratings(),
    )


# ---------------------------------------------------------------------------
# Table builders (private)
# ---------------------------------------------------------------------------


def _counterparties() -> pl.DataFrame:
    """One corporate (the OBS book) and one institution (a second C 07.00 sheet).

    Two obligors, not one: the CCF-bucket axis must be shown to be per-sheet,
    not an artefact of a single exposure class. ``annual_revenue`` is above the
    SME ceiling so no supporting factor perturbs the corporate RWEA.
    """
    rows: list[dict] = [
        {
            "counterparty_reference": CP_CORP,
            "entity_type": "corporate",
            "country_code": "GB",
            "annual_revenue": 250_000_000.0,
        },
        {"counterparty_reference": CP_INST, "entity_type": "institution", "country_code": "GB"},
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA))


def _ratings() -> pl.DataFrame:
    """External ECAI ratings — corporate CQS 3, institution CQS 2.

    External only (no internal PD), so every exposure routes SA regardless of
    the permission mode the caller supplies.
    """
    rows: list[dict] = [
        {
            "rating_reference": "OBS-RTG-CORP",
            "counterparty_reference": CP_CORP,
            "rating_type": "external",
            "rating_agency": "TEST_AGENCY",
            "rating_value": "BBB",
            "cqs": 3,
            "rating_date": _VALUE_DATE,
        },
        {
            "rating_reference": "OBS-RTG-INST",
            "counterparty_reference": CP_INST,
            "rating_type": "external",
            "rating_agency": "TEST_AGENCY",
            "rating_value": "A",
            "cqs": 2,
            "rating_date": _VALUE_DATE,
        },
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(RATINGS_SCHEMA))


def _loans() -> pl.DataFrame:
    """One drawn corporate loan — the on-balance-sheet anchor.

    Two jobs. It gives C 07.00 an on-balance component so the col 0150 ->
    col 0200 exposure-value derivation has a non-trivial residual (the
    ``boe_b0471`` identity is vacuous on an all-off-balance sheet), and it
    consumes part of ``FAC_OC``'s limit so that facility's undrawn headroom is a
    genuine limit-minus-drawn number rather than the whole limit.
    """
    rows: list[dict] = [
        {
            "loan_reference": LN_CORP_DRAWN,
            "counterparty_reference": CP_CORP,
            "product_type": "term_loan",
            "drawn_amount": DRAWN_CORP,
            "currency": "GBP",
            "value_date": _VALUE_DATE,
            "maturity_date": _MATURITY,
            "seniority": "senior",
        },
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(LOAN_SCHEMA))


def _contingents() -> pl.DataFrame:
    """Four ISSUED off-balance-sheet items — one per issued-item CCF bucket.

    Contingents default to ``is_obs_commitment=False`` (issued item, not a
    commitment), which is what each of these is. All are ``bs_type="OFB"`` so
    the nominal stays off balance sheet and flows through the CCF stage.
    """
    rows: list[dict] = [
        # CRR Annex I para 1(a) / Table A1 Row 1 — a financial guarantee with
        # the character of a credit substitute. Full risk: 100% in both regimes.
        {
            "contingent_reference": CT_GUARANTEE,
            "counterparty_reference": CP_CORP,
            "product_type": "financial_guarantee",
            "nominal_amount": NOMINAL_GUARANTEE,
            "risk_type": "FR",
            "currency": "GBP",
            "value_date": _VALUE_DATE,
            "maturity_date": _MATURITY,
            "bs_type": "OFB",
        },
        # CRR Annex I para 3(a) / Table A1 Row 6(a) — a self-liquidating
        # documentary credit arising from the movement of goods. 20% in both
        # regimes. ``risk_type`` is deliberately LEFT NULL: this row is the
        # end-to-end proof of the Art. 111(1) obs_product -> risk_type fill
        # (DOCUMENTARY_CREDIT -> MLR). If the ``obs_product`` projection through
        # the hierarchy stage ever regresses, this row silently falls to the
        # conservative 50% MR default and lands in the wrong CCF bucket.
        {
            "contingent_reference": CT_DOC_CREDIT,
            "counterparty_reference": CP_CORP,
            "product_type": "documentary_credit",
            "obs_product": "DOCUMENTARY_CREDIT",
            "nominal_amount": NOMINAL_DOC_CREDIT,
            "is_short_term_trade_lc": True,
            "currency": "GBP",
            "value_date": _VALUE_DATE,
            "maturity_date": _MATURITY,
            "bs_type": "OFB",
        },
        # CRR Annex I para 2 (issued items) / Table A1 Row 3 — an irrevocable
        # standby letter of credit that does NOT have the character of a credit
        # substitute. 50% in both regimes. MR_ISSUED (not MR) so the Row 3 vs
        # Row 4 issued-item / commitment discriminator is the one under test.
        {
            "contingent_reference": CT_STANDBY_MR,
            "counterparty_reference": CP_CORP,
            "product_type": "standby_lc",
            "nominal_amount": NOMINAL_STANDBY,
            "risk_type": "MR_ISSUED",
            "currency": "GBP",
            "value_date": _VALUE_DATE,
            "maturity_date": _MATURITY,
            "bs_type": "OFB",
        },
        # CRR Annex I para 2 (FRC) / Table A1 Row 2 — a forward asset purchase:
        # a commitment with CERTAIN drawdown, so 100% in both regimes. Booked
        # against the institution so the CCF-bucket axis is populated on a
        # SECOND C 07.00 sheet, not just the corporate one.
        {
            "contingent_reference": CT_FRC_FWD,
            "counterparty_reference": CP_INST,
            "product_type": "forward_asset_purchase",
            "nominal_amount": NOMINAL_FRC_FWD,
            "risk_type": "FRC",
            "currency": "GBP",
            "value_date": _VALUE_DATE,
            "maturity_date": _MATURITY,
            "bs_type": "OFB",
        },
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(CONTINGENTS_SCHEMA))


def _facilities() -> pl.DataFrame:
    """Three COMMITMENTS — the undrawn-headroom side of the CCF axis.

    Each emits one synthetic ``<facility>_UNDRAWN`` exposure. All carry
    ``committed=True``: an uncommitted facility produces no undrawn exposure at
    all, so unconditional cancellability is expressed as ``risk_type="LR"``
    (see the module docstring).
    """
    rows: list[dict] = [
        # CRR Annex I para 2 / Table A1 Row 4(a) — a note issuance facility.
        # 50% in both regimes: the one commitment whose bucket does NOT move.
        {
            "facility_reference": FAC_NIF,
            "counterparty_reference": CP_CORP,
            "product_type": "note_issuance_facility",
            "limit": LIMIT_NIF,
            "risk_type": "MR",
            "currency": "GBP",
            "value_date": _VALUE_DATE,
            "maturity_date": _MATURITY,
            "committed": True,
        },
        # CRR Annex I item 2(b) / Table A1 Row 5 — a revolving corporate credit
        # line that is not in any other category. THE regime-divergent row:
        # CRR splits "other commitments" on ORIGINAL maturity (here ~12 years,
        # so item 2(b) -> 50%) and Table A1 Row 5 replaces the split with a flat
        # 40%. It is the sole source of the Basel 3.1 col 0171 bucket.
        # LN_CORP_DRAWN maps to it, so undrawn = LIMIT_OC - DRAWN_CORP.
        {
            "facility_reference": FAC_OC,
            "counterparty_reference": CP_CORP,
            "product_type": "revolving_credit_facility",
            "limit": LIMIT_OC,
            "risk_type": "OC",
            "currency": "GBP",
            "value_date": _VALUE_DATE,
            "maturity_date": _MATURITY,
            "committed": True,
            "is_revolving": True,
        },
        # CRR Annex I para 4(a) / Table A1 Row 7 — an overdraft line cancellable
        # unconditionally at any time without notice. The headline Basel 3.1
        # change: 0% -> 10%, i.e. a zero-EAD row becomes a real one in the same
        # C 07.00 column (0160).
        {
            "facility_reference": FAC_UCC,
            "counterparty_reference": CP_CORP,
            "product_type": "overdraft",
            "limit": LIMIT_UCC,
            "risk_type": "LR",
            "currency": "GBP",
            "value_date": _VALUE_DATE,
            "maturity_date": _MATURITY,
            "committed": True,
            "is_revolving": True,
        },
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(FACILITY_SCHEMA))


def _facility_mappings() -> pl.DataFrame:
    """Link the drawn loan to ``FAC_OC`` so its headroom nets the drawn balance.

    ``FAC_NIF`` and ``FAC_UCC`` have no children — their undrawn equals their
    full limit, which keeps their C 07.00 cells trivially hand-checkable.
    """
    rows: list[dict] = [
        {
            "parent_facility_reference": FAC_OC,
            "child_reference": LN_CORP_DRAWN,
            "child_type": "loan",
        },
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(FACILITY_MAPPING_SCHEMA))
