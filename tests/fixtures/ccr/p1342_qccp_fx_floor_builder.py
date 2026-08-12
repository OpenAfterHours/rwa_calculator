"""
P1.342 fixture: QCCP trade exposures under the Art. 121(6) FX sovereign floor.

Pipeline position:
    fixture-builder output -> test-writer (P1.342 acceptance test)
    -> engine-implementer (engine/sa/sovereign_floor.py QCCP carve-out)

Why this fixture exists
-----------------------
``apply_sovereign_floor_for_institutions`` floors an **unrated institution**
exposure denominated in a currency other than the institution's own at that
jurisdiction's sovereign risk weight. A QCCP counterparty classifies as an
institution (``entity_type == "ccp"`` -> INSTITUTION, per COUNTERPARTY_SCHEMA),
so an unrated QCCP with a foreign-currency netting set falls inside the floor's
predicate — and the floor overwrites the Art. 306 2% / 4% trade-exposure weight
with the (unrated) sovereign 100%. Art. 306 is lex specialis for QCCP trade
exposures and admits no such floor.

The country/currency pair is LOAD-BEARING and was measured, not guessed
-----------------------------------------------------------------------
The floor's FX test falls back to ``~is_domestic_currency`` when the
counterparty carries no ``cp_local_currency`` (the ordinary case — nothing
populates it from the raw input). ``is_domestic_currency`` is
``is_uk_domestic | is_eu_domestic``, and ``is_eu_domestic`` is built by
``replace_strict(..., default=None).eq(currency)``, so a non-EU country code
yields NULL rather than False. Note the UK limb is NOT the null source: for
GB/USD ``(country == "GB") & (ccy == "GBP")`` is a determinate ``True & False``.
It is the EU limb that goes null, and ``False | NULL`` is NULL:

    GB + USD  -> False | NULL = NULL  -> ``~NULL`` is NULL -> ``pl.when``
                 takes ``otherwise`` -> the floor NEVER ARMS. Vacuous.
    US + GBP  -> same shape, same vacuity.
    FR + USD  -> False | False = False -> ``~False`` is True -> ARMED.

Measured on this bundle with the country flipped and nothing else changed, under
both the current engine and one patched with the null-safe denomination currency
below: GB/USD stays ``UNKNOWN_FALLBACK`` at 2% in BOTH states, FR/USD reaches
``floor_bound`` at 100% in the patched one. So **FR + USD is the only shape in
which this item can be shown to fail**; a GB/USD or US/GBP fixture would sit
green before and after the fix, for the wrong reason, until the sibling item
P1.333 lands. See `.claude/LESSONS.md` B5 — a row that never lights the branch
makes coverage worse, not better.

There is a SECOND disarming mechanism on this path, and it is why the fixture
looks quiet today
-----------------------------------------------------------------------------
``denomination_currency_expr`` returns ``pl.col("original_currency")`` whenever
that column is in the schema. The FX converter stamps it, but it runs on the
lending frame — the synthetic ``ccr__`` rows are minted afterwards and pick the
column up as a NULL fill from ``SA_INPUT_CONTRACT``. Measured on this fixture:
``original_currency`` is null on all three rows while ``currency`` is ``"USD"``.
So ``"EUR".eq(NULL)`` is NULL, ``is_domestic_currency`` is NULL, and the floor
lands on ``UNKNOWN_FALLBACK`` — with a BR001 WARNING per row saying exactly
that. Today's correct-looking 2% is an accident of that null, not a carve-out.

Consequence for the test-writer: **``risk_weight == 0.02`` alone is NOT a
fail-first assertion** — it holds today. Assert the branch reason too (today:
``UNKNOWN_FALLBACK``, plus a BR001 warning in ``result.errors``); that is the
part that can only go green once the denomination currency is null-safe AND the
Art. 306 carve-out exists.

The counterparties are deliberately UNRATED (no ``ratings`` row, null
``institution_cqs``) — ``_is_unrated`` is the floor's second conjunct — and no
FR sovereign counterparty is supplied, so ``cp_sovereign_cqs`` is null and the
floor resolves through the Art. 114(1) unrated-sovereign residual.

Composition (three netting sets, one trade each, identical economics)
--------------------------------------------------------------------
    NS-P1342-QCCP-PROP   unrated QCCP (FR), proprietary trade exposure.
                         Art. 306(1)(a) -> ``QCCP_RW_PROPRIETARY``.
                         THE ROW UNDER TEST.
    NS-P1342-QCCP-CLI    same QCCP, client-cleared trade exposure.
                         Art. 306(1)(c) / Art. 307 -> ``QCCP_RW_CLIENT_CLEARED``.
                         The second limb of the same carve-out — a fix keyed on
                         the proprietary branch alone leaves this one floored.
    NS-P1342-INST        unrated ORDINARY institution (FR), NOT a CCP, same
                         FR/USD shape. SCOPE CONTROL: a carve-out written over
                         "is a CCR row" rather than "is a QCCP trade exposure"
                         would hand this row 2% and understate it 50x (CRR) /
                         75x (B31). Stated honestly: this leg does NOT
                         demonstrate the floor BINDING — an unrated
                         institution's sovereign-derived weight is already at
                         or above the unrated-sovereign residual, so it reads
                         ``floor_not_binding`` at 100% (CRR) / 150% (B31) once
                         the floor arms. It is a scope control, nothing more.

All three trades are the canonical CCR-A1 10y vanilla IR swap
(``trade_builder.make_trade`` defaults: notional 100m, MtM 0, delta 1.0,
unmargined, legally enforceable) redenominated into USD. No ``fx_rates`` frame
is supplied, so nothing converts the amounts and the expected values carry no
FX-rate dependency — the denomination is genuinely foreign on the input side.

EAD is reporting-date dependent (the SA-CCR add-on integrates remaining
maturity), so the two regimes do NOT share an EAD — the measured constants
below are keyed by the config that produced them.

References:
- CRR Art. 306(1)(a)/(c), Art. 307 — QCCP trade-exposure risk weights
- CRR Art. 301-311 / Art. 272(88) — QCCP definition and CCP framework
- PRA PS1/26 Art. 121(6) — the FX sovereign floor for unrated institutions
- PRA PS1/26 Art. 114(1)-(2) — the floor's value source (unrated residual)
- BCBS CRE54.14 / CRE54.15 — the 2% / 4% supervisory factors
- CRE20.22 + footnote 13 — the Basel SCRA sovereign floor and its only carve-out
- tests/fixtures/ccr/qccp_builder.py — canonical QCCP risk-weight constants
- src/rwa_calc/engine/sa/sovereign_floor.py — the rule under test
"""

from __future__ import annotations

from typing import Any

import polars as pl

from rwa_calc.contracts.bundles import (
    CCRCollateralBundle,
    MarginAgreementBundle,
    NettingSetBundle,
    RawCCRBundle,
    RawDataBundle,
    TradeBundle,
)
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    CCR_COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)
from tests.fixtures.raw_bundle import make_raw_bundle

from .margin_builder import create_margin_agreements
from .netting_set_builder import NettingSet, create_netting_sets, make_netting_set
from .qccp_builder import QCCP_RW_CLIENT_CLEARED, QCCP_RW_PROPRIETARY
from .trade_builder import create_trades, make_trade

# ---------------------------------------------------------------------------
# Scenario constants — the single source of truth for test assertions.
# ---------------------------------------------------------------------------

#: Country of incorporation for every counterparty here. FR is in the EU
#: domestic-currency map (-> EUR), which is what makes ``is_eu_domestic``
#: resolve to a real False against a USD denomination instead of NULL.
P1342_COUNTRY: str = "FR"

#: Trade / netting-set denomination. EUR would make the row domestic and
#: disarm the floor; USD is the mismatch Art. 121(6) is written about.
P1342_CURRENCY: str = "USD"

#: Unrated QCCP (entity_type "ccp", is_qccp True, no ratings row).
P1342_CP_QCCP_REF: str = "CP-P1342-QCCP-FR"

#: Unrated ordinary institution, same jurisdiction — the scope control.
P1342_CP_INST_REF: str = "CP-P1342-INST-FR"

P1342_NS_QCCP_PROP: str = "NS-P1342-QCCP-PROP"
P1342_NS_QCCP_CLIENT: str = "NS-P1342-QCCP-CLI"
P1342_NS_INST: str = "NS-P1342-INST"

P1342_TRADE_QCCP_PROP: str = "T-P1342-QCCP-PROP"
P1342_TRADE_QCCP_CLIENT: str = "T-P1342-QCCP-CLI"
P1342_TRADE_INST: str = "T-P1342-INST"

#: Synthetic exposure references the CCR stage emits (``ccr__<netting_set_id>``).
#: These are what a test selects on off ``result.results``.
P1342_EXPOSURE_QCCP_PROP: str = f"ccr__{P1342_NS_QCCP_PROP}"
P1342_EXPOSURE_QCCP_CLIENT: str = f"ccr__{P1342_NS_QCCP_CLIENT}"
P1342_EXPOSURE_INST: str = f"ccr__{P1342_NS_INST}"

#: Expected post-fix risk weights for the two QCCP legs — imported, never
#: retyped (`.claude/LESSONS.md` A4: the pack is the value home, and
#: ``qccp_builder`` is this tree's single carrier for the Art. 306 pair).
P1342_RW_QCCP_PROPRIETARY: float = QCCP_RW_PROPRIETARY
P1342_RW_QCCP_CLIENT_CLEARED: float = QCCP_RW_CLIENT_CLEARED

#: Measured SA-CCR EAD per regime, keyed by the config that produced it.
#: The add-on integrates remaining maturity FROM THE REPORTING DATE, so the two
#: regimes differ purely by their reporting dates — nothing regulatory. Use
#: these configs or re-measure; a different reporting date moves the EAD:
#:     CRR       CalculationConfig.crr(reporting_date=date(2025, 12, 31))
#:     BASEL_3_1 CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 1))
#: both with ``permission_mode=PermissionMode.STANDARDISED`` — the same pair
#: ``tests/acceptance/reporting/test_reporting_ccr_golden.py`` uses.
P1342_EAD_CRR: float = 5_496_691.101365475
P1342_EAD_B31: float = 4_875_927.249918847

#: Correct RWA for the two QCCP legs — Art. 306 weight x EAD. This is what the
#: engine produces today (the floor is disarmed by a null ``original_currency``
#: on CCR rows) and what it must still produce once the floor arms.
P1342_RWA_QCCP_PROP_CRR: float = P1342_EAD_CRR * P1342_RW_QCCP_PROPRIETARY
P1342_RWA_QCCP_CLIENT_CRR: float = P1342_EAD_CRR * P1342_RW_QCCP_CLIENT_CLEARED
P1342_RWA_QCCP_PROP_B31: float = P1342_EAD_B31 * P1342_RW_QCCP_PROPRIETARY
P1342_RWA_QCCP_CLIENT_B31: float = P1342_EAD_B31 * P1342_RW_QCCP_CLIENT_CLEARED

#: ANTI-DEGENERATE baseline — the RWA a QCCP leg takes when the Art. 121(6)
#: floor arms and no carve-out stops it. The floor resolves through the
#: Art. 114(1) unrated-sovereign residual (``cp_sovereign_cqs`` is null here),
#: which is 100%, so the floored RWA is numerically the EAD. Measured against a
#: simulated null-safe denomination currency with the carve-out absent:
#: 50x the proprietary leg, 25x the client-cleared leg, in both regimes.
P1342_RWA_QCCP_FLOORED_CRR: float = P1342_EAD_CRR
P1342_RWA_QCCP_FLOORED_B31: float = P1342_EAD_B31

# ---------------------------------------------------------------------------
# Netting-set terms. Everything else about the trades is the shared CCR-A1
# default from ``trade_builder.make_trade``, redenominated into USD — so a
# change to those defaults surfaces here as a measured-EAD diff rather than
# silently re-pricing the scenario.
# ---------------------------------------------------------------------------

_IS_LEGALLY_ENFORCEABLE: bool = True
_IS_MARGINED: bool = False

#: Mirrors ``generate_all.PYTHON_ONLY_NO_PARQUET``. Reported back by
#: ``save_p1342_fixtures`` without importing the generator (which imports this
#: module); ``generate_all`` asserts the two agree.
_PYTHON_ONLY_NO_PARQUET: str = "(python-only builder — no parquet)"


def build_p1342_bundle() -> RawDataBundle:
    """Assemble the P1.342 FR/USD QCCP book as a sealed ``RawDataBundle``.

    Run through ``PipelineOrchestrator().run_with_data`` under either regime.
    Three synthetic ``ccr__`` rows come out, one per netting set; select them by
    ``exposure_reference`` using the ``P1342_EXPOSURE_*`` constants.

    Returns:
        A bundle with three netting sets, three trades, two counterparties, no
        ratings, no lending, no collateral, no margin agreements and no FX
        rates.
    """
    trades = pl.concat(
        [
            _trade(P1342_TRADE_QCCP_PROP, P1342_NS_QCCP_PROP, is_client_cleared=False),
            _trade(P1342_TRADE_QCCP_CLIENT, P1342_NS_QCCP_CLIENT, is_client_cleared=True),
            _trade(P1342_TRADE_INST, P1342_NS_INST, is_client_cleared=False),
        ]
    )
    netting_sets = create_netting_sets(
        [
            _netting_set(P1342_NS_QCCP_PROP, P1342_CP_QCCP_REF),
            _netting_set(P1342_NS_QCCP_CLIENT, P1342_CP_QCCP_REF),
            _netting_set(P1342_NS_INST, P1342_CP_INST_REF),
        ]
    )

    facilities, loans, facility_mappings, lending_mappings = _empty_lending_frames()

    return make_raw_bundle(
        counterparties=_counterparties().lazy(),
        facilities=facilities,
        loans=loans,
        facility_mappings=facility_mappings,
        lending_mappings=lending_mappings,
        ratings=pl.LazyFrame(schema=dtypes_of(RATINGS_SCHEMA)),
        ccr=_raw_ccr_bundle(trades, netting_sets),
    )


def save_p1342_fixtures() -> list[tuple[str, int]]:
    """Smoke-check entry point for ``tests/fixtures/generate_all.py``.

    Python-only builder — no parquet is written. This verifies the invariants
    the scenario rests on, so a drift in a shared builder default (currency,
    country, ratings, QCCP flags) fails the generator rather than silently
    disarming the floor the fixture exists to arm.
    """
    bundle = build_p1342_bundle()

    counterparties = bundle.counterparties.collect()
    if counterparties.height != 2:
        raise AssertionError("P1.342: expected exactly 2 counterparties")
    if sorted(counterparties["country_code"].to_list()) != [P1342_COUNTRY, P1342_COUNTRY]:
        raise AssertionError(
            f"P1.342: both counterparties must be incorporated in {P1342_COUNTRY!r} — "
            "a non-EU code makes is_eu_domestic NULL and the Art. 121(6) floor never arms"
        )
    qccp_flags = dict(
        zip(
            counterparties["counterparty_reference"].to_list(),
            counterparties["is_qccp"].to_list(),
            strict=True,
        )
    )
    if qccp_flags.get(P1342_CP_QCCP_REF) is not True:
        raise AssertionError(f"P1.342: {P1342_CP_QCCP_REF} must carry is_qccp=True")
    if qccp_flags.get(P1342_CP_INST_REF) is not False:
        raise AssertionError(
            f"P1.342: {P1342_CP_INST_REF} must carry is_qccp=False — it is the scope control"
        )
    if any(cqs is not None for cqs in counterparties["institution_cqs"].to_list()):
        raise AssertionError(
            "P1.342: both counterparties must be UNRATED (null institution_cqs) — "
            "a rated one fails the floor's _is_unrated conjunct and the row falls out of scope"
        )

    if bundle.ratings is not None and bundle.ratings.collect().height != 0:
        raise AssertionError("P1.342: the ratings frame must be empty (unrated counterparties)")

    if bundle.ccr is None:
        raise AssertionError("P1.342: bundle must carry a RawCCRBundle")
    trades = bundle.ccr.trades.trades.collect()
    if trades.height != 3:
        raise AssertionError("P1.342: expected exactly 3 trades")
    if set(trades["currency"].to_list()) != {P1342_CURRENCY}:
        raise AssertionError(
            f"P1.342: every trade must be denominated in {P1342_CURRENCY!r} — "
            "an EUR denomination is domestic for FR and disarms the floor"
        )
    cleared = dict(
        zip(trades["trade_id"].to_list(), trades["is_client_cleared"].to_list(), strict=True)
    )
    if cleared[P1342_TRADE_QCCP_PROP] is not False:
        raise AssertionError("P1.342: the proprietary QCCP trade must be is_client_cleared=False")
    if cleared[P1342_TRADE_QCCP_CLIENT] is not True:
        raise AssertionError("P1.342: the client-cleared QCCP trade must be is_client_cleared=True")

    netting_sets = bundle.ccr.netting_sets.netting_sets.collect()
    if netting_sets.height != 3:
        raise AssertionError("P1.342: expected exactly 3 netting sets")
    if netting_sets["is_margined"].any():
        raise AssertionError("P1.342: every netting set is unmargined (CCR-A1 economics)")

    if not (0.0 < P1342_RW_QCCP_PROPRIETARY < P1342_RW_QCCP_CLIENT_CLEARED < 1.0):
        raise AssertionError(
            "P1.342: the Art. 306 pair must be ordered and strictly below the sovereign floor — "
            "otherwise the scenario cannot show the floor over-writing them"
        )
    if not (0 < P1342_EAD_B31 < P1342_EAD_CRR):
        raise AssertionError("P1.342: measured EADs are implausible")

    return [(_PYTHON_ONLY_NO_PARQUET, 0)]


# ---------------------------------------------------------------------------
# Private helpers.
# ---------------------------------------------------------------------------


def _counterparties() -> pl.DataFrame:
    """One unrated QCCP and one unrated ordinary institution, both in FR.

    ``institution_cqs`` is null on BOTH rows and no ratings frame accompanies
    them: ``_is_unrated`` in ``sovereign_floor.py`` is
    ``cqs.is_null() | (cqs <= 0)``, so a rating here would take every row out
    of the floor's scope and make the whole fixture vacuous.
    """
    rows: list[dict[str, Any]] = [
        {
            "counterparty_reference": P1342_CP_QCCP_REF,
            "counterparty_name": "Unrated QCCP (FR)",
            "entity_type": "ccp",
            "country_code": P1342_COUNTRY,
            "default_status": False,
            "sector_code": "66.11",
            "apply_fi_scalar": False,
            "is_managed_as_retail": False,
            "institution_cqs": None,
        },
        {
            "counterparty_reference": P1342_CP_INST_REF,
            "counterparty_name": "Unrated institution (FR)",
            "entity_type": "institution",
            "country_code": P1342_COUNTRY,
            "default_status": False,
            "sector_code": "64.19",
            "apply_fi_scalar": False,
            "is_managed_as_retail": False,
            "institution_cqs": None,
        },
    ]
    base = pl.DataFrame(rows, schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA))
    return base.with_columns(
        (pl.col("counterparty_reference") == P1342_CP_QCCP_REF).alias("is_qccp")
    )


def _trade(trade_id: str, netting_set_id: str, *, is_client_cleared: bool) -> pl.DataFrame:
    """One CCR-A1 10y vanilla IR swap, redenominated into ``P1342_CURRENCY``.

    ``is_client_cleared`` is appended via ``with_columns`` — the same pattern
    ``qccp_builder`` / ``p839_ccp_builder`` use, since the ``Trade`` dataclass
    does not carry it.
    """
    trade = make_trade(
        trade_id=trade_id,
        netting_set_id=netting_set_id,
        currency=P1342_CURRENCY,
    )
    return create_trades([trade]).with_columns(
        pl.lit(value=is_client_cleared).alias("is_client_cleared")
    )


def _netting_set(netting_set_id: str, counterparty_reference: str) -> NettingSet:
    """One unmargined, legally enforceable netting set."""
    return make_netting_set(
        netting_set_id=netting_set_id,
        counterparty_reference=counterparty_reference,
        is_legally_enforceable=_IS_LEGALLY_ENFORCEABLE,
        is_margined=_IS_MARGINED,
    )


def _raw_ccr_bundle(trades: pl.DataFrame, netting_sets: pl.DataFrame) -> RawCCRBundle:
    """Wrap the trade / netting-set frames with empty margin and collateral."""
    return RawCCRBundle(
        trades=TradeBundle(trades=trades.lazy()),
        netting_sets=NettingSetBundle(netting_sets=netting_sets.lazy()),
        margin_agreements=MarginAgreementBundle(
            margin_agreements=create_margin_agreements([]).lazy()
        ),
        ccr_collateral=CCRCollateralBundle(
            ccr_collateral=pl.DataFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA)).lazy()
        ),
    )


def _empty_lending_frames() -> tuple[pl.LazyFrame, pl.LazyFrame, pl.LazyFrame, pl.LazyFrame]:
    """Zero-row facilities / loans / facility_mappings / lending_mappings."""
    return (
        pl.LazyFrame(schema=dtypes_of(FACILITY_SCHEMA)),
        pl.LazyFrame(schema=dtypes_of(LOAN_SCHEMA)),
        pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
        pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA)),
    )
