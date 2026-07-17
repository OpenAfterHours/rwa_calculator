"""
Golden CCR-SFT-IRB-* scenarios: FCCM SFTs routed to IRB, asserting the
Art. 162 effective maturity M for the synthetic ``ccr__<NS>`` row (both regimes).

Pipeline position:
    fixture-builder output -> test-writer (tests/acceptance/ccr/test_ccr_sft_irb_maturity.py)
    -> engine sft_fccm FCCM stage (engine/sft/fccm.py) -> IRBCalculator maturity chain

Scenario design (CCR/SFT IRB effective-maturity fix, Phase 5 — A0 anchors):

    A single FCCM SFT (``RawDataBundle.sft``, the lean RawSFTBundle) against an
    INTERNALLY-rated corporate counterparty (``CP_SFT_IRB`` — internal_pd=0.0150,
    model_id=MOD_CORP_IRB), with an IRB model permission injected by the test.
    PermissionMode.IRB routes the synthetic ``ccr__<NS>`` row through the IRB
    maturity chain, which reads the producer-emitted ``ccr_effective_maturity``
    carrier (the full Art. 162 M = clip(remaining, floor, 5y)).

    Unlike CCR-A11/A12 (whose CP_INST_001 carries an EXTERNAL rating, pd=None,
    so the row falls to SA), this counterparty carries an INTERNAL rating so the
    classifier gates into FIRB/AIRB. FIRB vs AIRB is selected SOLELY by the
    ``approach`` string on the injected model permission ("foundation_irb" vs
    "advanced_irb"); the counterparty / rating are identical for both.

    Each anchor varies the three Art. 162 SFT input flags
    (``under_master_netting_agreement`` / ``qualifies_one_day_maturity_floor`` /
    ``qualifies_mna_intermediate_floor``) and the ``maturity_date`` (residual via
    the engine's /365 day-count) to land the regulatorily-correct M.

CORRECTED A0 anchors (reporting_date 2026-01-15; assert ``irb_maturity_m`` DIRECTLY):

    | id     | repo                         | regime | approach | M (assert)        | citation        |
    |--------|------------------------------|--------|----------|-------------------|-----------------|
    | A0-1   | NOT under MNA                | CRR    | AIRB     | 1.0               | 162(2)(f)       |
    | A0-2   | same repo, under MNA*        | CRR    | FIRB     | 0.5               | 162(1)          |
    | A0-3   | same repo                    | B31    | FIRB     | 1.0 (162(1) gone) | 162(1) deleted  |
    | A0-4   | overnight, MNA, one-day      | CRR    | AIRB     | 1/365 ≈ 0.00274   | 162(3)          |
    | A0-5   | 2-day, MNA, NON-daily [USER] | CRR    | AIRB     | 5/365 ≈ 0.01370   | 162(2)(d)       |
    | A0-5b  | same as A0-5, no daily-gate  | B31    | FIRB→AIRB| 1.0 (daily gate)  | 162(2A)(d)/(f)  |
    | A0-6   | long (~0.8y), MNA, non-daily | CRR    | AIRB     | 0.8 (floor inert) | 162(2)(f)       |

    *A0-2 is FIRB so M=0.5 comes from the FIRB-0.5y rung (Art. 162(1)); the MNA
     flag is irrelevant for it (the carrier is AIRB-gated). A0-2 keeps the same
     non-MNA repo body as A0-1 for clarity — FIRB never reaches the carrier.

    A0-5 and A0-5b are the SAME inputs run under crr() vs basel_3_1(): under CRR
    the 5BD intermediate floor applies on MNA alone (5/365); under B31 the
    162(2A)(d) daily condition is required (qualifies_mna_intermediate_floor=False
    here) so the row falls to the 162(2A)(f) 1-year catch-all (1.0). A0-5b uses
    AIRB so the carrier rung is reachable and the regime divergence is the whole
    point (a FIRB B31 row would also give 1.0 but via the date-derived base, not
    the daily-gate — AIRB isolates the gate).

Counterparty / rating / model permission (mirrors CCR-IRB-1):
    CP_SFT_IRB: corporate, GB, internal_pd=0.0150, model_id=MOD_CORP_IRB.
    The internal rating promotes to internal_pd / internal_model_id on the
    counterparty_lookup; the model permission row (corporate, GB, approach=...)
    is injected by the test via dataclasses.replace + seal_raw_table.

References:
    - CRR Art. 162(1): F-IRB fixed supervisory M = 0.5y for repo-style SFTs.
    - CRR Art. 162(2)(d): 5BD weighted-avg floor for repos/sec-lending under MNA.
    - CRR Art. 162(2)(f): 1-year catch-all (no MNA / not calculable).
    - CRR Art. 162(3): 1-day floor (daily re-margin AND revaluation AND prompt
      liquidation docs).
    - PS1/26 Art. 162(2A)(d): 5BD floor under B31 requires the daily condition.
    - PS1/26 Art. 162(1): F-IRB 0.5y supervisory M DELETED under B31.
    - CRR Art. 161(1)(a): F-IRB senior unsecured corporate LGD = 45%.
    - CRR Art. 163: PD floor 0.03%.
    - tests/fixtures/ccr/golden_ccr_irb1.py — counterparty / rating / permission pattern.
    - tests/fixtures/ccr/sft_bundle_builder.py — SFT seal helpers.
"""

from __future__ import annotations

from datetime import date as _date

import polars as pl

from rwa_calc.contracts.bundles import (
    RawDataBundle,
    RawSFTBundle,
    SftTradeBundle,
)
from rwa_calc.contracts.edges import SFT_TABLE_EDGES, seal_lenient
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    LOAN_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    RATINGS_SCHEMA,
    SFT_TRADE_SCHEMA,
)
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Shared scenario constants — single source of truth for test assertions.
# ---------------------------------------------------------------------------

# Reporting date: residual = (mat - rep) via the engine /365 day-count.
CCR_SFT_IRB_REPORTING_DATE: _date = _date(2026, 1, 15)

# Counterparty (internally rated corporate, GB — gates into FIRB/AIRB).
CCR_SFT_IRB_COUNTERPARTY_REF: str = "CP_SFT_IRB"
CCR_SFT_IRB_CP_ENTITY_TYPE: str = "corporate"
CCR_SFT_IRB_CP_COUNTRY_CODE: str = "GB"

# Internal rating (pd above CRR Art. 163 floor 0.03%; carries the model_id).
CCR_SFT_IRB_RATING_REF: str = "RTG_CP_SFT_IRB"
CCR_SFT_IRB_INTERNAL_PD: float = 0.0150
CCR_SFT_IRB_RATING_DATE: _date = _date(2026, 1, 15)

# Model permission (corporate, GB). approach is supplied per-anchor by the test.
CCR_SFT_IRB_MODEL_ID: str = "MOD_CORP_IRB"
CCR_SFT_IRB_MODEL_EXPOSURE_CLASS: str = "corporate"
CCR_SFT_IRB_MODEL_COUNTRY_CODES: str = "GB"
CCR_SFT_IRB_APPROACH_FIRB: str = "foundation_irb"
CCR_SFT_IRB_APPROACH_AIRB: str = "advanced_irb"

# Trade economics (a GBP repo; HE inputs left null = cash-equivalent, HE=0 —
# E* / EAD is immaterial here, the assertion is on irb_maturity_m).
CCR_SFT_IRB_NOTIONAL: float = 100_000_000.0
CCR_SFT_IRB_CURRENCY: str = "GBP"

# Illustrative own-estimate LGD (P1.215) for the A-IRB anchors (A0-1, A0-4,
# A0-5, A0-5b, A0-6). The SAME trade row also feeds the FIRB anchors
# (A0-2, A0-3), but FIRB permissions clear modelled LGD downstream (FIRB uses
# the supervisory 45% senior-unsecured LGD, Art. 161(1)(a)), so one value on
# the shared row is correct for every anchor — see ``_sft_irb_trade_df``.
CCR_SFT_IRB_MODELLED_LGD: float = 0.45

# ---------------------------------------------------------------------------
# Per-anchor identifiers + dates + flags. Each anchor -> one netting set ->
# one emitted ``ccr__<NS>`` synthetic row.
#
# residual (/365 day-count, rep=2026-01-15):
#   A0-1/A0-2/A0-3: 2026-05-21 -> 0.3452 (sub-1y -> date-derived clips to 1.0)
#   A0-4         : 2026-01-16 -> 1/365  (overnight)
#   A0-5/A0-5b   : 2026-01-17 -> 2/365  (2-day)
#   A0-6         : 2026-11-03 -> 0.8    (floor inert)
# ---------------------------------------------------------------------------

# A0-1 / A0-2 / A0-3 — shared 126-day repo body (sub-1y residual).
CCR_SFT_IRB_A0_1_NETTING_SET_ID: str = "NS_SFT_IRB_A01"
CCR_SFT_IRB_A0_1_TRADE_ID: str = "T_SFT_IRB_A01"
CCR_SFT_IRB_A0_1_MATURITY_DATE: _date = _date(2026, 5, 21)
CCR_SFT_IRB_A0_1_EXPOSURE_REFERENCE: str = f"ccr__{CCR_SFT_IRB_A0_1_NETTING_SET_ID}"

# A0-4 — overnight repo, MNA, daily one-day floor.
CCR_SFT_IRB_A0_4_NETTING_SET_ID: str = "NS_SFT_IRB_A04"
CCR_SFT_IRB_A0_4_TRADE_ID: str = "T_SFT_IRB_A04"
CCR_SFT_IRB_A0_4_MATURITY_DATE: _date = _date(2026, 1, 16)
CCR_SFT_IRB_A0_4_EXPOSURE_REFERENCE: str = f"ccr__{CCR_SFT_IRB_A0_4_NETTING_SET_ID}"

# A0-5 / A0-5b — 2-day repo, MNA, non-daily (the user case).
CCR_SFT_IRB_A0_5_NETTING_SET_ID: str = "NS_SFT_IRB_A05"
CCR_SFT_IRB_A0_5_TRADE_ID: str = "T_SFT_IRB_A05"
CCR_SFT_IRB_A0_5_MATURITY_DATE: _date = _date(2026, 1, 17)
CCR_SFT_IRB_A0_5_EXPOSURE_REFERENCE: str = f"ccr__{CCR_SFT_IRB_A0_5_NETTING_SET_ID}"

# A0-6 — long (~0.8y) repo, MNA, non-daily (floor inert -> M = residual).
CCR_SFT_IRB_A0_6_NETTING_SET_ID: str = "NS_SFT_IRB_A06"
CCR_SFT_IRB_A0_6_TRADE_ID: str = "T_SFT_IRB_A06"
CCR_SFT_IRB_A0_6_MATURITY_DATE: _date = _date(2026, 11, 3)
CCR_SFT_IRB_A0_6_EXPOSURE_REFERENCE: str = f"ccr__{CCR_SFT_IRB_A0_6_NETTING_SET_ID}"

# ---------------------------------------------------------------------------
# Expected M anchors (assert irb_maturity_m DIRECTLY, abs=1e-6).
# ---------------------------------------------------------------------------

CCR_SFT_IRB_ONE_DAY_M: float = 1.0 / 365.0  # ≈ 0.0027397
CCR_SFT_IRB_FIVE_BD_M: float = 5.0 / 365.0  # ≈ 0.0136986
CCR_SFT_IRB_FIRB_SUPERVISORY_M: float = 0.5

CCR_SFT_IRB_A0_1_EXPECTED_M: float = 1.0  # 162(2)(f) date-derived 1y floor (no MNA)
CCR_SFT_IRB_A0_2_EXPECTED_M: float = CCR_SFT_IRB_FIRB_SUPERVISORY_M  # 162(1) CRR FIRB
CCR_SFT_IRB_A0_3_EXPECTED_M: float = 1.0  # 162(1) deleted under B31 -> date-derived
CCR_SFT_IRB_A0_4_EXPECTED_M: float = CCR_SFT_IRB_ONE_DAY_M  # 162(3)
CCR_SFT_IRB_A0_5_EXPECTED_M: float = CCR_SFT_IRB_FIVE_BD_M  # 162(2)(d) CRR
CCR_SFT_IRB_A0_5B_EXPECTED_M: float = 1.0  # 162(2A)(d) daily gate -> catch-all (B31)
CCR_SFT_IRB_A0_6_EXPECTED_M: float = 0.8  # 162(2)(f) floor inert


# ---------------------------------------------------------------------------
# SFT seal helpers (loader-identical, mirroring sft_bundle_builder.py).
# ---------------------------------------------------------------------------


def _seal_sft_trades(df: pl.DataFrame) -> pl.LazyFrame:
    """Seal an SFT trade frame exactly as the loader does (leniently)."""
    sealed, _missing = seal_lenient(df.lazy(), SFT_TABLE_EDGES["sft_trades"])
    return sealed


def _sft_irb_trade_df(
    trade_id: str,
    netting_set_id: str,
    maturity_date: _date,
    *,
    under_master_netting_agreement: bool,
    qualifies_one_day_maturity_floor: bool,
    qualifies_mna_intermediate_floor: bool,
    is_margined: bool = False,
    remargining_frequency_days: int = 3,
) -> pl.DataFrame:
    """One-row GBP repo SFT carrying the three Art. 162 flags + maturity_date.

    HE inputs (``exposure_collateral_type`` / ``exposure_security_cqs`` /
    ``exposure_security_residual_maturity_years``) are left null => HE=0
    (cash-equivalent), so EAD is immaterial to the maturity assertion. The
    margining columns default to the non-daily / unmargined branch (the carrier
    never infers the one-day floor from remargin frequency — only the explicit
    ``qualifies_one_day_maturity_floor`` flag unlocks it).

    ``ccr_modelled_lgd`` (P1.215) is NOT yet declared on ``SFT_TRADE_SCHEMA`` /
    ``SFT_TABLE_EDGES["sft_trades"]`` — the engine-implementer adds it later.
    Today it is carried on the row's OWN construction schema
    (``sft_trade_schema_plus`` below, mirroring the P1.10 / P1.124
    extra-column-beyond-schema pattern) so it survives into the DataFrame and
    is then dropped at the loader-boundary seal (``_seal_sft_trades`` ->
    ``seal_lenient`` against the current, narrower ``SFT_TABLE_EDGES``) rather
    than vanishing one step earlier at construction time — this is the
    behaviour the P1.215 sequencing check exercises.
    """
    row = {
        "trade_id": trade_id,
        "netting_set_id": netting_set_id,
        "counterparty_reference": CCR_SFT_IRB_COUNTERPARTY_REF,
        "notional": CCR_SFT_IRB_NOTIONAL,
        "currency": CCR_SFT_IRB_CURRENCY,
        "maturity_date": maturity_date,
        "start_date": CCR_SFT_IRB_REPORTING_DATE,
        "exposure_collateral_type": None,
        "exposure_security_cqs": None,
        "exposure_security_residual_maturity_years": None,
        "is_margined": is_margined,
        "remargining_frequency_days": remargining_frequency_days,
        "mpor_floor_category": "repo_only",
        "has_margin_dispute_doubling": False,
        "mpor_days_override": None,
        "under_master_netting_agreement": under_master_netting_agreement,
        "qualifies_one_day_maturity_floor": qualifies_one_day_maturity_floor,
        "qualifies_mna_intermediate_floor": qualifies_mna_intermediate_floor,
        # NEW field (P1.215) — not yet in SFT_TRADE_SCHEMA. Illustrative
        # own-estimate LGD shared by every anchor (see CCR_SFT_IRB_MODELLED_LGD).
        "ccr_modelled_lgd": CCR_SFT_IRB_MODELLED_LGD,
    }
    sft_trade_schema_plus = {**dtypes_of(SFT_TRADE_SCHEMA), "ccr_modelled_lgd": pl.Float64}
    return pl.DataFrame([row], schema=sft_trade_schema_plus)


def _single_sft_bundle(df: pl.DataFrame) -> RawSFTBundle:
    """Wrap a one-row SFT trade frame in a collateral-free RawSFTBundle."""
    return RawSFTBundle(
        trades=SftTradeBundle(sft_trades=_seal_sft_trades(df)),
        collateral=None,
    )


# ---------------------------------------------------------------------------
# Per-anchor SFT bundles.
# ---------------------------------------------------------------------------


def build_sft_bundle_a0_1() -> RawSFTBundle:
    """A0-1/A0-2/A0-3 repo body: 126-day repo, NOT under an MNA (carrier None)."""
    return _single_sft_bundle(
        _sft_irb_trade_df(
            CCR_SFT_IRB_A0_1_TRADE_ID,
            CCR_SFT_IRB_A0_1_NETTING_SET_ID,
            CCR_SFT_IRB_A0_1_MATURITY_DATE,
            under_master_netting_agreement=False,
            qualifies_one_day_maturity_floor=False,
            qualifies_mna_intermediate_floor=False,
        )
    )


def build_sft_bundle_a0_4() -> RawSFTBundle:
    """A0-4: overnight repo, under MNA, qualifies one-day floor (Art. 162(3))."""
    return _single_sft_bundle(
        _sft_irb_trade_df(
            CCR_SFT_IRB_A0_4_TRADE_ID,
            CCR_SFT_IRB_A0_4_NETTING_SET_ID,
            CCR_SFT_IRB_A0_4_MATURITY_DATE,
            under_master_netting_agreement=True,
            qualifies_one_day_maturity_floor=True,
            qualifies_mna_intermediate_floor=False,
            is_margined=True,
            remargining_frequency_days=1,
        )
    )


def build_sft_bundle_a0_5() -> RawSFTBundle:
    """A0-5/A0-5b: 2-day repo, under MNA, NON-daily, no daily-gate (Art. 162(2)(d))."""
    return _single_sft_bundle(
        _sft_irb_trade_df(
            CCR_SFT_IRB_A0_5_TRADE_ID,
            CCR_SFT_IRB_A0_5_NETTING_SET_ID,
            CCR_SFT_IRB_A0_5_MATURITY_DATE,
            under_master_netting_agreement=True,
            qualifies_one_day_maturity_floor=False,
            qualifies_mna_intermediate_floor=False,
        )
    )


def build_sft_bundle_a0_6() -> RawSFTBundle:
    """A0-6: long (~0.8y) repo, under MNA, non-daily (5BD floor inert -> M=0.8)."""
    return _single_sft_bundle(
        _sft_irb_trade_df(
            CCR_SFT_IRB_A0_6_TRADE_ID,
            CCR_SFT_IRB_A0_6_NETTING_SET_ID,
            CCR_SFT_IRB_A0_6_MATURITY_DATE,
            under_master_netting_agreement=True,
            qualifies_one_day_maturity_floor=False,
            qualifies_mna_intermediate_floor=False,
        )
    )


# ---------------------------------------------------------------------------
# Counterparty / rating / model-permission builders (CCR-IRB-1 pattern).
# ---------------------------------------------------------------------------


def _build_cp_sft_irb_counterparty() -> pl.LazyFrame:
    """One-row corporate counterparty (GB) — internal rating gates into IRB."""
    row = {
        "counterparty_reference": CCR_SFT_IRB_COUNTERPARTY_REF,
        "counterparty_name": "CCR-SFT-IRB Test Corporate",
        "entity_type": CCR_SFT_IRB_CP_ENTITY_TYPE,
        "country_code": CCR_SFT_IRB_CP_COUNTRY_CODE,
        # MUST be present and below the GBP 440m large-corporate threshold
        # (Art. 147A(1)(d)): engine/stages/classify/approach.py's is_large_corp
        # treats a counterparty with BOTH annual_revenue and total_assets null
        # as large (conservative ``.otherwise(pl.lit(True))`` default), and a
        # B31 large corporate is A-IRB-blocked. That would silently route A0-5b
        # (the only B31 AIRB anchor) to SA instead of exercising the
        # ccr_modelled_lgd carrier. Do not strip this value.
        "annual_revenue": 50_000_000.0,
        "default_status": False,
        "apply_fi_scalar": False,
        "is_managed_as_retail": False,
    }
    return pl.DataFrame([row], schema=dtypes_of(COUNTERPARTY_SCHEMA)).lazy()


def _build_cp_sft_irb_rating() -> pl.LazyFrame:
    """One-row INTERNAL rating (pd=0.0150, model_id=MOD_CORP_IRB).

    The hierarchy promotes pd -> internal_pd and model_id -> internal_model_id on
    the counterparty_lookup; non-null internal_pd is the IRB gate. cqs=None (no
    external CQS) keeps this a pure PD-path rating.
    """
    row = {
        "rating_reference": CCR_SFT_IRB_RATING_REF,
        "counterparty_reference": CCR_SFT_IRB_COUNTERPARTY_REF,
        "rating_type": "internal",
        "rating_agency": None,
        "rating_value": None,
        "cqs": None,
        "pd": CCR_SFT_IRB_INTERNAL_PD,
        "rating_date": CCR_SFT_IRB_RATING_DATE,
        "is_solicited": False,
        "model_id": CCR_SFT_IRB_MODEL_ID,
        "is_short_term": False,
        "scope_type": None,
        "scope_id": None,
    }
    return pl.DataFrame([row], schema=dtypes_of(RATINGS_SCHEMA)).lazy()


def create_ccr_sft_irb_model_permission(*, approach: str) -> pl.DataFrame:
    """One-row model permission for MOD_CORP_IRB (corporate, GB, *approach*).

    Pass ``approach="foundation_irb"`` for FIRB anchors (A0-2/A0-3) or
    ``approach="advanced_irb"`` for AIRB anchors (A0-1/A0-4/A0-5/A0-5b/A0-6).
    The FIRB/AIRB selection is driven ENTIRELY by this string — the counterparty
    and rating are identical for both. The test injects the row via
    dataclasses.replace + seal_raw_table(..., "model_permissions").
    """
    row = {
        "model_id": CCR_SFT_IRB_MODEL_ID,
        "exposure_class": CCR_SFT_IRB_MODEL_EXPOSURE_CLASS,
        "approach": approach,
        "country_codes": CCR_SFT_IRB_MODEL_COUNTRY_CODES,
        "excluded_book_codes": None,
    }
    return pl.DataFrame([row], schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA))


def _build_empty_facilities() -> pl.LazyFrame:
    return pl.LazyFrame(schema=dtypes_of(FACILITY_SCHEMA))


def _build_empty_loans() -> pl.LazyFrame:
    return pl.LazyFrame(schema=dtypes_of(LOAN_SCHEMA))


def _build_empty_facility_mappings() -> pl.LazyFrame:
    return pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA))


def _build_empty_lending_mappings() -> pl.LazyFrame:
    return pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA))


# ---------------------------------------------------------------------------
# Public bundle-assembly helper.
# ---------------------------------------------------------------------------


def build_raw_data_bundle_ccr_sft_irb(sft: RawSFTBundle) -> RawDataBundle:
    """Assemble a RawDataBundle for one CCR-SFT-IRB anchor.

    The internally-rated CP_SFT_IRB counterparty + internal rating are shared
    across all anchors; only the SFT bundle (flags + maturity_date) varies. The
    model permission is NOT on the bundle (model_permissions=None) — the test
    injects it via dataclasses.replace, choosing FIRB vs AIRB per anchor.
    """
    return make_raw_bundle(
        counterparties=_build_cp_sft_irb_counterparty(),
        facilities=_build_empty_facilities(),
        loans=_build_empty_loans(),
        facility_mappings=_build_empty_facility_mappings(),
        lending_mappings=_build_empty_lending_mappings(),
        ratings=_build_cp_sft_irb_rating(),
        sft=sft,
    )
