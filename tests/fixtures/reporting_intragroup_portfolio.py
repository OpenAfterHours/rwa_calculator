"""
Intragroup (Art. 113(6)) reporting portfolio — a core-UK-group member's individual
return, with intragroup lending, derivative and SFT exposures beside external ones.

Pipeline position:
    build_reporting_intragroup_bundle(reporting_date) -> RawDataBundle
        -> PipelineOrchestrator (intragroup_config: BANK_A, INDIVIDUAL basis)
        -> AggregatedResultBundle -> COREPGenerator / Pillar3Generator

Why it exists (P1.364, LESSONS B5). The intragroup 0% risk weight fires only on a
scoped individual-basis run (``reporting_entity`` + ``ReportingBasis.INDIVIDUAL``)
of a core-UK-group member, and no run of the supervisory ``RUNS`` matrix set
either, so every reporting cell the permission writes was dead estate-wide: the
0% row 0140 of the C 07.00 / OF 07.00 institutions and corporates sheets, and its
column 0210 ("of which: arising from counterparty credit risk") once P1.364
extended the permission to SA-CCR netting sets and SFTs. The Bank's PI-05 rules
close exactly those cells (``boe_b0440`` / ``boe_b0441`` on OF 07.00.01.01 row
0140, ``boe_b0440_1`` / ``boe_b0441_1`` on OF 07.00.01.02 row 0140), so a correct
Basel 3.1 return of this book breaks them at the gateway as WARNINGs — a
publisher issue, not a figure to bend (Annex II paras 66-68 put an intragroup
exposure in its counterparty's own class, and Art. 113(6) gives it 0%).

Group (registry): GRP (financial holding company, parent) -> BANK_A, BANK_B; all
three ``core_uk_group=True``. Every exposure is booked on BANK_A's book, so the
BANK_A individual run keeps all of them. Counterparties:

    BANK_B    UK institution, unrated, SCRA grade A — the institutions sheet
    GRP       the parent financial holding company: a financial institution
              (Art. 113(6)(a)) whose SA class is corporate (Annex II para 68:
              "intra-group counterparties are not necessarily institutions") —
              the corporates sheet
    CORP_EXT  external unrated corporate — the controls

Hand calculation (CRR Art. 121 Table 5 unrated institution with an unrated
sovereign = 100%; PS1/26 Art. 121 SCRA grade A = 40%; unrated corporate 100% in
both; PS1/26 Art. 133(5) subordinated debt 150%):

    LN_IG_BANK      1m senior to BANK_B, intragroup     -> 0%        both (row 0140)
    LN_IG_BANK_SUB  1m subordinated to BANK_B, intra-
                    group: the own-funds carve-out      -> CRR 100% / B31 150%
    LN_IG_GRP       1m senior to GRP, intragroup        -> 0%        both (row 0140)
    LN_EXT          1m senior to CORP_EXT               -> 100%      both
    ccr__NS_IG_BANK SA-CCR set to BANK_B, intragroup    -> 0%        both (row 0140 c0210)
    ccr__NS_IG_GRP  SA-CCR set to GRP, intragroup       -> 0%        both (row 0140 c0210)
    ccr__NS_EXT     SA-CCR set to CORP_EXT              -> 100%      both
    ccr__SFT_NS_IG  10m cash-lent SFT to BANK_B, intra-
                    group (E* = 10m)                    -> 0%        both (row 0140 c0210)
    ccr__SFT_NS_EXT 10m cash-lent SFT to CORP_EXT       -> 100%      both

It is also the first registered book with an SFT at all, so the first to populate
row 0090 ("securities financing transactions netting sets") of C 07.00 / OF 07.00.

LESSONS B5's two-leg rule: row 0140 of the institutions sheet holds the senior
intragroup LOAN on every engine (the lending path predates P1.364) beside the
derivative and SFT legs that P1.364 moved into it, so a change that empties the
row is distinguishable from one that moves the CCR legs out of it; on the
corporates sheet the 0% row sits beside the 100% row of the external controls.

Assembled IN MEMORY (as ``reporting_declined_guarantee_portfolio`` is), so there
is no parquet to register in ``generate_all.py``. Dates are stated relative to
the reporting date, so each regime's run binds its own with
``functools.partial``. Registered in the supervisory ``RUNS`` matrix under both
regimes with ``intragroup_config`` — the generic SA config would leave
``reporting_entity`` unset, and every leg here would take its full weight
(LESSONS B5, third form: registered with the wrong config).

References:
- CRR Art. 113(6); PS1/26 Art. 113(6)-(7); PS1/26 Art. 133(5); CRR / PS1/26 Art. 121
- CRR / PS1/26 Annex II paras 66-68 (intragroup exposures in the counterparty's
  class) and 126 (0%-weighted intragroup counterparty credit risk)
- PS1/26 Annex II OF 07.00 row 0140 (0%), column 0210 (of which: CCR)
- docs/rwa-filer/publisher-issues.md PI-05
"""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from rwa_calc.contracts.bundles import (
    CCRCollateralBundle,
    MarginAgreementBundle,
    NettingSetBundle,
    RawCCRBundle,
    RawDataBundle,
    RawSFTBundle,
    SftTradeBundle,
    TradeBundle,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.edges import SFT_TABLE_EDGES, seal_lenient
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    BOOK_ENTITY_MAPPING_SCHEMA,
    CCR_COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    LOAN_SCHEMA,
    MARGIN_AGREEMENT_SCHEMA,
    NETTING_SET_SCHEMA,
    REPORTING_ENTITY_SCHEMA,
    SFT_TRADE_SCHEMA,
)
from rwa_calc.domain.enums import PermissionMode, ReportingBasis
from tests.fixtures.ccr.trade_builder import create_trades, make_trade
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants — the single source of truth for test assertions.
# ---------------------------------------------------------------------------

REPORTING_ENTITY: str = "BANK_A"
CP_BANK: str = "BANK_B"  # institution sheet
CP_PARENT: str = "GRP"  # corporates sheet (financial holding company)
CP_EXT: str = "CORP_EXT"  # external control

LN_IG_BANK: str = "LN_IG_BANK"
LN_IG_BANK_SUB: str = "LN_IG_BANK_SUB"
LN_IG_GRP: str = "LN_IG_GRP"
LN_EXT: str = "LN_EXT"
NS_IG_BANK: str = "NS_IG_BANK"
NS_IG_GRP: str = "NS_IG_GRP"
NS_EXT: str = "NS_EXT"
SFT_NS_IG: str = "SFT_NS_IG"
SFT_NS_EXT: str = "SFT_NS_EXT"

LOAN_AMOUNT: float = 1_000_000.0
SFT_CASH_LENT: float = 10_000_000.0

#: The reporting date of each regime's run (the supervisory register's SA dates).
INTRAGROUP_DATE: dict[str, date] = {"CRR": date(2025, 12, 31), "BASEL_3_1": date(2027, 6, 1)}

_BOOK_A: str = "BOOK_A1"
_BOOK_B: str = "BOOK_B1"
_SWAP_NOTIONAL: float = 10_000_000.0
_SWAP_MTM: float = 1_000_000.0


def build_reporting_intragroup_bundle(reporting_date: date) -> RawDataBundle:
    """Assemble the intragroup reporting portfolio as a sealed ``RawDataBundle``.

    Run it through ``PipelineOrchestrator().run_with_data`` with
    ``intragroup_config`` — the BANK_A individual-basis scope is what makes the
    Art. 113(6) carrier fire. Under an unscoped config every leg keeps its full
    weight.
    """
    return make_raw_bundle(
        counterparties=_counterparties(),
        loans=_loans(reporting_date),
        reporting_entities=_registry(),
        book_entity_mappings=_book_mapping(),
        ccr=_ccr(reporting_date),
        sft=_sft(reporting_date),
    )


def intragroup_config(framework: str) -> CalculationConfig:
    """BANK_A's individual-basis Standardised config for ``framework``.

    The scope (``reporting_entity`` + ``ReportingBasis.INDIVIDUAL``) is the
    load-bearing part: Art. 113(6) is an individual-basis permission, and the SA
    override fires only where the scope resolver is authoritative over the
    carrier. Standardised, like the other SA-only runs, so no prior frame.
    """
    if framework == "CRR":
        return CalculationConfig.crr(
            reporting_date=INTRAGROUP_DATE[framework],
            permission_mode=PermissionMode.STANDARDISED,
            reporting_entity=REPORTING_ENTITY,
            reporting_basis=ReportingBasis.INDIVIDUAL,
        )
    return CalculationConfig.basel_3_1(
        reporting_date=INTRAGROUP_DATE[framework],
        permission_mode=PermissionMode.STANDARDISED,
        reporting_entity=REPORTING_ENTITY,
        reporting_basis=ReportingBasis.INDIVIDUAL,
    )


# ---------------------------------------------------------------------------
# Table builders (private)
# ---------------------------------------------------------------------------


def _counterparties() -> pl.DataFrame:
    """BANK_B (institution), GRP (financial holding company), CORP_EXT."""

    def _cp(reference: str, entity_type: str, *, financial: bool) -> dict:
        is_bank = entity_type == "institution"
        return {
            "counterparty_reference": reference,
            "counterparty_name": reference,
            "entity_type": entity_type,
            "country_code": "GB",
            "annual_revenue": None if is_bank else 500_000_000.0,
            "total_assets": 50_000_000_000.0 if is_bank else 1_000_000_000.0,
            "default_status": False,
            "is_financial_sector_entity": financial,
            "apply_fi_scalar": False,
            "is_managed_as_retail": False,
            # PS1/26 Art. 121 SCRA grade A (40% senior, > 3 months) keeps BANK_B's
            # class weight apart from the Art. 133(5) 150%; CRR does not read it.
            "scra_grade": "A" if is_bank else None,
        }

    return pl.DataFrame(
        [
            _cp(CP_BANK, "institution", financial=True),
            _cp(CP_PARENT, "corporate", financial=True),
            _cp(CP_EXT, "corporate", financial=False),
        ],
        schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA),
    )


def _loans(reporting_date: date) -> pl.DataFrame:
    """Three intragroup loans (one subordinated) and one external control."""

    def _loan(reference: str, counterparty: str, seniority: str, intragroup: str | None) -> dict:
        return {
            "loan_reference": reference,
            "product_type": "term_loan",
            "book_code": _BOOK_A,
            "counterparty_reference": counterparty,
            "value_date": reporting_date,
            "maturity_date": reporting_date + timedelta(days=5 * 365),
            "currency": "GBP",
            "drawn_amount": LOAN_AMOUNT,
            "interest": 0.0,
            "seniority": seniority,
            "intragroup_entity_reference": intragroup,
        }

    return pl.DataFrame(
        [
            _loan(LN_IG_BANK, CP_BANK, "senior", CP_BANK),
            _loan(LN_IG_BANK_SUB, CP_BANK, "subordinated", CP_BANK),
            _loan(LN_IG_GRP, CP_PARENT, "senior", CP_PARENT),
            _loan(LN_EXT, CP_EXT, "senior", None),
        ],
        schema_overrides=dtypes_of(LOAN_SCHEMA),
    )


def _registry() -> pl.DataFrame:
    """GRP -> BANK_A, BANK_B: one core UK group."""
    return pl.DataFrame(
        [
            {
                "entity_reference": entity,
                "entity_name": entity,
                "lei": f"LEI{entity:0>17}",
                "parent_entity_reference": parent,
                "core_uk_group": True,
            }
            for entity, parent in (
                (CP_PARENT, None),
                (REPORTING_ENTITY, CP_PARENT),
                (CP_BANK, CP_PARENT),
            )
        ],
        schema_overrides=dtypes_of(REPORTING_ENTITY_SCHEMA),
    )


def _book_mapping() -> pl.DataFrame:
    """BANK_A's book holds every exposure; BANK_B's book is mapped and empty."""
    return pl.DataFrame(
        [
            {"book_code": _BOOK_A, "reporting_entity_reference": REPORTING_ENTITY},
            {"book_code": _BOOK_B, "reporting_entity_reference": CP_BANK},
        ],
        schema_overrides=dtypes_of(BOOK_ENTITY_MAPPING_SCHEMA),
    )


def _ccr(reporting_date: date) -> RawCCRBundle:
    """Three unmargined, enforceable one-swap netting sets on BANK_A's book."""
    #: (netting set, counterparty, intragroup tag)
    sets = (
        (NS_IG_BANK, CP_BANK, CP_BANK),
        (NS_IG_GRP, CP_PARENT, CP_PARENT),
        (NS_EXT, CP_EXT, None),
    )
    trades = create_trades(
        [
            make_trade(
                trade_id=f"T_{netting_set}",
                netting_set_id=netting_set,
                notional=_SWAP_NOTIONAL,
                mtm_value=_SWAP_MTM,
                start_date=reporting_date,
                maturity_date=reporting_date + timedelta(days=5 * 365),
            )
            for netting_set, _counterparty, _intragroup in sets
        ]
    )
    netting_sets = pl.DataFrame(
        [
            {
                "netting_set_id": netting_set,
                "counterparty_reference": counterparty,
                "is_legally_enforceable": True,
                "is_margined": False,
                "book_code": _BOOK_A,
                "intragroup_entity_reference": intragroup,
            }
            for netting_set, counterparty, intragroup in sets
        ],
        schema=dtypes_of(NETTING_SET_SCHEMA),
    )
    return RawCCRBundle(
        trades=TradeBundle(trades=trades.lazy()),
        netting_sets=NettingSetBundle(netting_sets=netting_sets.lazy()),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=pl.LazyFrame(schema=dtypes_of(MARGIN_AGREEMENT_SCHEMA))
        ),
        ccr_collateral=CCRCollateralBundle(
            ccr_collateral=pl.LazyFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))
        ),
    )


def _sft(reporting_date: date) -> RawSFTBundle:
    """Two uncollateralised 10m cash-lent SFTs on BANK_A's book: one intragroup."""
    trades = pl.DataFrame(
        [
            {
                "trade_id": f"T_{netting_set}",
                "netting_set_id": netting_set,
                "counterparty_reference": counterparty,
                "notional": SFT_CASH_LENT,
                "currency": "GBP",
                "maturity_date": reporting_date + timedelta(days=180),
                "start_date": reporting_date,
                "book_code": _BOOK_A,
                "intragroup_entity_reference": intragroup,
            }
            for netting_set, counterparty, intragroup in (
                (SFT_NS_IG, CP_BANK, CP_BANK),
                (SFT_NS_EXT, CP_EXT, None),
            )
        ],
        schema=dtypes_of(SFT_TRADE_SCHEMA),
    )
    sealed, _missing, _lossy = seal_lenient(trades.lazy(), SFT_TABLE_EDGES["sft_trades"])
    return RawSFTBundle(trades=SftTradeBundle(sft_trades=sealed))
