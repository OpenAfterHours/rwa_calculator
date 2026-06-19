"""
P8.62 / CVA-HEDGE-A1 fixture builder: full BA-CVA with eligible single-name CDS hedge.

Pipeline position:
    fixture-builder output -> test-writer (tests/acceptance/ccr/test_cva_hedge_a1_ba_cva_full.py)
    -> engine-implementer (engine/cva/ba_cva.py)

Scenario design:
    Extends the P8.60 CVA-A1 reduced-version baseline. The CCR book and CVA
    counterparty frame are imported verbatim from P8.60 so the reduced-version
    EAD and SCVA_c are byte-identical to P8.60.  A single eligible single-name
    CDS hedge (H_SN_CVA_001) referencing CP_CVA_001 is added.

    The perfect-hedge equality condition (SNH_c == SCVA_c) is derived from the
    PDF formulae.  A CRITICAL DIFFERENCE from the proposal is noted below.

CRITICAL FORMULA DIFFERENCE — SNH_c does not carry (1/alpha):

    The proposal assumed SNH_c used the same (1/alpha) scaling as SCVA_c.  The
    PDF (ps126app1.pdf page 402, section 4.7) is explicit:

        SCVA_c = (1/alpha) * RW_c * sum_NS(M_NS * EAD_NS * DF_NS)
        SNH_c  = sum_h(r_hc * RW_h * M_h * B_h * DF_h)          [NO 1/alpha]

    Therefore, for a perfect single-name hedge (r_hc=1.0, matching RW_h=RW_c,
    M_h=M_NS, DF_h=DF_NS):

        SNH_c == SCVA_c
        r_hc * RW_h * M_h * B_h * DF_h == (1/alpha) * RW_c * M_NS * EAD_NS * DF_NS
        1.0 * RW * M * B_h * DF == (1/alpha) * RW * M * EAD_NS * DF
        B_h == EAD_NS / alpha

    So hedge_notional = EAD_NS / alpha (NOT hedge_notional = EAD_NS).

    With this identity: K_hedged = 0 exactly, and:
        K_full = beta * K_reduced + (1 - beta) * 0 = beta * K_reduced
        RWEA_full = DS_BA_CVA * beta * K_reduced * 12.5 = beta * RWEA_reduced

    The acceptance test pins the ratio rwea_cva_full / rwea_cva_reduced == beta == 0.25.
    This is robust to the absolute EAD value (EAD cancels in the ratio).

Source-verified (ps126app1.pdf — effective from 1 January 2027):
    - beta = 0.25                                             [page 401, section 4.5]
    - K_full = beta * K_reduced + (1 - beta) * K_hedged      [page 401, section 4.5]
    - DS_BA-CVA = 0.65                                        [page 401, section 4.5]
    - rho = 50%                                               [page 402, section 4.6]
    - SCVA_c = (1/alpha) * RW_c * sum(M_NS * EAD_NS * DF_NS) [page 400, section 4.3]
    - SNH_c = sum_h(r_hc * RW_h * M_h * B_h * DF_h)         [page 402, section 4.7]
      NOTE: SNH carries NO (1/alpha) factor (confirmed against 4.7 formula text)
    - DF_h = (1 - e^(-0.05*M_h)) / (0.05 * M_h)             [page 402, section 4.7]
    - HMA_c = sum_h((1 - r_hc^2) * (RW_h * M_h * B_h * DF_h)^2) [page 403, section 4.9]
    - IH = sum_i(RW_i_ind * M_i * B_i * DF_i)                [page 402, section 4.8]
    - r_hc table (section 4.10, page 403):
        IDENTICAL (references CP directly)     = 1.00 (100%)
        LEGALLY_RELATED (parent/sub)           = 0.80 (80%)
        SAME_SECTOR_REGION                     = 0.50 (50%)
    - Index diversification factor             = 0.70 [page 403, section 4.8(1)/(2)]
      (applied to RW_i_ind for index hedges — out of scope for this fixture)
    - RWEA_full = DS_BA-CVA * K_full * 12.5                   [page 401, section 4.5;
                                                               page 15, Own Funds 4(b)]

CVA hedge input schema (CVA_HEDGE_SCHEMA, defined locally to allow tests to
run before the engine schema is wired):
    cva_hedge_reference          String   PK
    cva_hedge_type               String   SINGLE_NAME | INDEX
    counterparty_reference       String   FK to cva_counterparties (null for INDEX)
    cva_hedge_correlation_band   String   IDENTICAL | LEGALLY_RELATED | SAME_SECTOR_REGION
    cva_hedge_rw_sector          String   sector key (same values as cva_rw_sector)
    cva_hedge_rw_rating_band     String   IG | HY_NR
    cva_hedge_residual_maturity_years Float64  remaining maturity M_h (years)
    cva_hedge_notional           Float64  B_h (notional of the single-name hedge)
    cva_hedge_eligible           Boolean  eligibility flag

References:
    - PS1/26 App.1 CVA Part 4.5  (full BA-CVA, beta, K_full)
    - PS1/26 App.1 CVA Part 4.6  (K_hedged formula)
    - PS1/26 App.1 CVA Part 4.7  (SNH_c formula — NO 1/alpha)
    - PS1/26 App.1 CVA Part 4.8  (IH formula, index diversification 0.70)
    - PS1/26 App.1 CVA Part 4.9  (HMA_c formula)
    - PS1/26 App.1 CVA Part 4.10 (r_hc table)
    - PS1/26 App.1 CVA Part 4.2-4.4 (reduced-version baseline — from P8.60)
    - PS1/26 App.1 Own Funds Part 4(b) (x12.5 multiplier, page 15)
"""

from __future__ import annotations

import math
from pathlib import Path

import polars as pl

# ---------------------------------------------------------------------------
# Re-export everything from P8.60 — the CCR book and CVA counterparty frame
# are byte-identical to P8.60.
# ---------------------------------------------------------------------------
from tests.fixtures.p8_60.cva_a1_builder import (
    CVA_A1_COUNTERPARTY_REF,
    CVA_A1_CVA_EFFECTIVE_MATURITY_YEARS,
    CVA_A1_CVA_RW_RATING_BAND,
    CVA_A1_CVA_RW_SECTOR,
    CVA_A1_NETTING_SET_ID,
    CVA_ALPHA,
    CVA_DS_BA_CVA,
    CVA_RW_FINANCIALS_IG,
    CVA_RWEA_MULTIPLIER,
    CVA_SUPERVISORY_CORRELATION_RHO,
    CVA_SUPERVISORY_DISCOUNT_RATE,
    build_cva_a1_inputs,
    compute_cva_a1_golden,
)

__all__ = [
    # P8.60 re-exports (counterparty + CCR book unchanged)
    "CVA_A1_COUNTERPARTY_REF",
    "CVA_A1_CVA_EFFECTIVE_MATURITY_YEARS",
    "CVA_A1_CVA_RW_RATING_BAND",
    "CVA_A1_CVA_RW_SECTOR",
    "CVA_A1_NETTING_SET_ID",
    "CVA_ALPHA",
    "CVA_DS_BA_CVA",
    "CVA_RW_FINANCIALS_IG",
    "CVA_RWEA_MULTIPLIER",
    "CVA_SUPERVISORY_CORRELATION_RHO",
    "CVA_SUPERVISORY_DISCOUNT_RATE",
    "build_cva_a1_inputs",
    "compute_cva_a1_golden",
    # P8.62 new additions
    "CVA_HEDGE_A1_REF",
    "CVA_BA_BETA",
    "CVA_BA_RHC_IDENTICAL",
    "CVA_BA_RHC_LEGALLY_RELATED",
    "CVA_BA_RHC_SAME_SECTOR_REGION",
    "CVA_HEDGE_SCHEMA_DTYPES",
    "create_perfect_single_name_hedge_frame",
    "compute_cva_full_golden",
    "save_cva_hedge_a1_fixtures",
    "save_p862_fixtures",
]

# ---------------------------------------------------------------------------
# P8.62 scenario constants — single source of truth for test-writer assertions.
# ---------------------------------------------------------------------------

CVA_HEDGE_A1_REF: str = "H_SN_CVA_001"

# ---------------------------------------------------------------------------
# Source-verified scalars for full BA-CVA (ps126app1.pdf).
# ---------------------------------------------------------------------------

# beta: hedging-disallowance weight.
# K_full = beta * K_reduced + (1 - beta) * K_hedged.
# Source: ps126app1.pdf page 401, section 4.5.
CVA_BA_BETA: float = 0.25

# r_hc correlation values (source: ps126app1.pdf page 403, section 4.10).
# "references counterparty c directly" -> 100%
CVA_BA_RHC_IDENTICAL: float = 1.00
# "is legally related to counterparty c" -> 80%
CVA_BA_RHC_LEGALLY_RELATED: float = 0.80
# "shares sector and region with counterparty c" -> 50%
CVA_BA_RHC_SAME_SECTOR_REGION: float = 0.50

# Index diversification factor (source: ps126app1.pdf page 403, section 4.8(1)/(2)).
# Applied to RW_i_ind for index hedges.  Out of scope for this fixture; included
# here for completeness so the engine-implementer can reference the constant.
CVA_BA_INDEX_DIVERSIFICATION_FACTOR: float = 0.70

# ---------------------------------------------------------------------------
# CVA hedge input schema (explicit mirror of CVA_HEDGE_SCHEMA).
# Defined here so acceptance tests can run before the engine schema is wired.
# ---------------------------------------------------------------------------

CVA_HEDGE_SCHEMA_DTYPES: dict[str, type[pl.DataType]] = {
    "cva_hedge_reference": pl.String,
    "cva_hedge_type": pl.String,
    "counterparty_reference": pl.String,
    "cva_hedge_correlation_band": pl.String,
    "cva_hedge_rw_sector": pl.String,
    "cva_hedge_rw_rating_band": pl.String,
    "cva_hedge_residual_maturity_years": pl.Float64,
    "cva_hedge_notional": pl.Float64,
    "cva_hedge_eligible": pl.Boolean,
}


# ---------------------------------------------------------------------------
# Perfect single-name hedge builder (parametrised on notional).
# ---------------------------------------------------------------------------


def create_perfect_single_name_hedge_frame(hedge_notional: float) -> pl.DataFrame:
    """
    Return a single-row CVA hedge DataFrame for the perfect single-name CDS scenario.

    The hedge references CP_CVA_001 directly (IDENTICAL correlation, r_hc=1.00),
    matches the counterparty's sector/rating (FINANCIAL/IG), and has the same
    residual maturity as the netting set (M_h = M_NS = 3.0 years) so DF_h = DF_NS.

    PERFECT-HEDGE EQUALITY CONDITION (source-verified against ps126app1.pdf):
        For SNH_c == SCVA_c (K_hedged = 0), we need:
            r_hc * RW_h * M_h * B_h * DF_h == (1/alpha) * RW_c * M_NS * EAD_NS * DF_NS

        With r_hc=1.0, RW_h=RW_c, M_h=M_NS, DF_h=DF_NS cancelling:
            B_h = EAD_NS / alpha  (NOT EAD_NS as the proposal assumed)

        The acceptance test materialises EAD_NS from the CCR pipeline and passes
        ``hedge_notional = ead_ns / CVA_ALPHA`` to this builder.

    The SNH formula (ps126app1.pdf 4.7) carries NO (1/alpha) factor. The SCVA
    formula (4.3) does. This asymmetry drives the B_h = EAD / alpha condition.

    Args:
        hedge_notional: B_h notional of the single-name CDS. For a perfect hedge,
            caller must pass EAD_NS / CVA_ALPHA (i.e. EAD_NS / 1.4).

    Returns:
        Single-row DataFrame matching CVA_HEDGE_SCHEMA_DTYPES.

    References:
        - PS1/26 App.1 CVA Part 4.7  (SNH_c formula, no 1/alpha, page 402)
        - PS1/26 App.1 CVA Part 4.10 (r_hc = 1.00 for IDENTICAL, page 403)
        - PS1/26 App.1 CVA Part 4.3  (SCVA_c formula with 1/alpha, page 400)
    """
    row: dict[str, object] = {
        "cva_hedge_reference": CVA_HEDGE_A1_REF,
        "cva_hedge_type": "SINGLE_NAME",
        "counterparty_reference": CVA_A1_COUNTERPARTY_REF,  # "CP_CVA_001"
        "cva_hedge_correlation_band": "IDENTICAL",
        "cva_hedge_rw_sector": CVA_A1_CVA_RW_SECTOR,  # "FINANCIAL"
        "cva_hedge_rw_rating_band": CVA_A1_CVA_RW_RATING_BAND,  # "IG"
        "cva_hedge_residual_maturity_years": CVA_A1_CVA_EFFECTIVE_MATURITY_YEARS,  # 3.0
        "cva_hedge_notional": hedge_notional,
        "cva_hedge_eligible": True,
    }
    return pl.DataFrame([row], schema=CVA_HEDGE_SCHEMA_DTYPES)


# ---------------------------------------------------------------------------
# Golden computation for the full BA-CVA scenario.
# ---------------------------------------------------------------------------


def compute_cva_full_golden(ead_ccr: float) -> dict[str, float]:
    """
    Compute the full BA-CVA golden values for the perfect single-name hedge scenario.

    Extends compute_cva_a1_golden (from P8.60) by computing K_hedged from the
    verified full-BA-CVA formula and K_full from the beta weighting.

    The perfect hedge is constructed as:
        hedge_notional = ead_ccr / CVA_ALPHA  (= EAD_NS / alpha)

    With that notional, SNH_c == SCVA_c exactly, so K_hedged == 0.

    Formula walk-through (ps126app1.pdf pages 401-403):

        hedge_notional = ead_ccr / alpha
        r_hc = 1.00                     (IDENTICAL band, section 4.10)
        RW_h = RW_c = 0.05              (Financials IG, section 4.4 table)
        M_h = M_NS = 3.0               (matching maturity)
        DF_h = DF_NS                    (same formula, same M)

        SNH_c = r_hc * RW_h * M_h * B_h * DF_h
              = 1.0 * 0.05 * 3.0 * (ead/alpha) * DF_NS
              = (0.05 * 3.0 * DF_NS / alpha) * ead
              = SCVA_c            [exact equality]

        HMA_c = (1 - r_hc^2) * (RW_h * M_h * B_h * DF_h)^2
              = (1 - 1.0) * ... = 0.0

        IH = 0.0  (no index hedges in this scenario)

        K_hedged formula (section 4.6):
            K_hedged = sqrt[
                (rho * sum_c(SCVA_c - SNH_c) - IH)^2
                + (1 - rho^2) * sum_c(SCVA_c - SNH_c)^2
                + sum_c(HMA_c)
            ]
            = sqrt[(rho * 0 - 0)^2 + (1 - rho^2) * 0 + 0]
            = 0.0

        K_full = beta * K_reduced + (1 - beta) * K_hedged
               = 0.25 * K_reduced + 0.75 * 0.0
               = 0.25 * K_reduced

        OFR_full = DS_BA_CVA * K_full = 0.65 * 0.25 * K_reduced
        RWEA_full = OFR_full * 12.5

        Ratio:  RWEA_full / RWEA_reduced = 0.25 = beta  (exact)

    Args:
        ead_ccr: The materialised EAD from the CCR pipeline for NS_CVA_001.

    Returns:
        Dict with keys:
            df_ns            -- supervisory discount factor (from P8.60)
            scva_c           -- SCVA for the single counterparty
            k_reduced        -- K_reduced (from P8.60 formula)
            ofr_cva_reduced  -- OFR = DS_BA_CVA * K_reduced
            rwea_cva_reduced -- RWEA = OFR * 12.5  (P8.60 baseline)
            hedge_notional   -- B_h = EAD / alpha  (perfect-hedge condition)
            snh_c            -- SNH_c (= SCVA_c for perfect hedge)
            hma_c            -- HMA_c (= 0.0 for IDENTICAL r_hc)
            ih               -- IH index-hedge term (= 0.0, no index hedges)
            k_hedged         -- K_hedged (= 0.0 for perfect hedge)
            k_full           -- K_full = beta * K_reduced
            ofr_cva_full     -- OFR_full = DS_BA_CVA * K_full
            rwea_cva_full    -- RWEA_full = OFR_full * 12.5
            ratio_full_reduced -- RWEA_full / RWEA_reduced (should equal beta = 0.25)

    References:
        - PS1/26 App.1 CVA Part 4.5 (K_full, beta = 0.25)
        - PS1/26 App.1 CVA Part 4.6 (K_hedged formula)
        - PS1/26 App.1 CVA Part 4.7 (SNH_c formula — NO 1/alpha)
        - PS1/26 App.1 CVA Part 4.9 (HMA_c formula)
        - PS1/26 App.1 CVA Part 4.10 (r_hc = 1.00 for IDENTICAL)
    """
    # Step 1: reduced-version baseline from P8.60.
    reduced = compute_cva_a1_golden(ead_ccr)
    df_ns = reduced["df_ns"]
    scva_c = reduced["scva_c"]
    k_reduced = reduced["k_reduced"]
    ofr_cva_reduced = reduced["ofr_cva"]
    rwea_cva_reduced = reduced["rwea_cva"]

    # Step 2: hedge inputs for perfect single-name CDS.
    # B_h = EAD_NS / alpha  (NOT EAD_NS — see module docstring for derivation).
    alpha = CVA_ALPHA
    rw_h = CVA_RW_FINANCIALS_IG  # 0.05, matches counterparty
    m_h = CVA_A1_CVA_EFFECTIVE_MATURITY_YEARS  # 3.0, matches netting set
    rate = CVA_SUPERVISORY_DISCOUNT_RATE
    r_hc = CVA_BA_RHC_IDENTICAL  # 1.00, IDENTICAL band

    # DF_h uses same formula as DF_NS (4.7): (1 - e^(-rate*M_h)) / (rate*M_h)
    df_h = (1.0 - math.exp(-rate * m_h)) / (rate * m_h)  # == df_ns since m_h == m_ns

    # Perfect-hedge notional: B_h such that SNH_c == SCVA_c.
    hedge_notional = ead_ccr / alpha

    # Step 3: SNH_c (section 4.7) — NO (1/alpha).
    snh_c = r_hc * rw_h * m_h * hedge_notional * df_h

    # Verify the perfect-hedge identity (internal assertion, not suppressed in tests).
    _diff = abs(snh_c - scva_c)
    _tol = max(abs(scva_c) * 1e-9, 1e-6)
    if _diff > _tol:
        raise AssertionError(
            f"P8.62 perfect-hedge identity violated: SNH_c={snh_c:.6f} != "
            f"SCVA_c={scva_c:.6f} (diff={_diff:.2e}, tol={_tol:.2e}). "
            f"Check hedge_notional={hedge_notional:.4f} vs EAD/alpha={ead_ccr / alpha:.4f}."
        )

    # Step 4: HMA_c (section 4.9) — (1 - r_hc^2) * (RW_h * M_h * B_h * DF_h)^2.
    # For IDENTICAL r_hc = 1.0: (1 - 1.0^2) * ... = 0.
    hma_c = (1.0 - r_hc**2) * (rw_h * m_h * hedge_notional * df_h) ** 2

    # Step 5: IH (section 4.8) — index-hedge term. No index hedges in this scenario.
    ih = 0.0

    # Step 6: K_hedged (section 4.6).
    rho = CVA_SUPERVISORY_CORRELATION_RHO
    net_c = scva_c - snh_c  # == 0.0 for perfect hedge
    systematic_term = (rho * net_c - ih) ** 2
    idiosyncratic_term = (1.0 - rho**2) * net_c**2
    k_hedged = math.sqrt(systematic_term + idiosyncratic_term + hma_c)

    # Step 7: K_full (section 4.5) = beta * K_reduced + (1 - beta) * K_hedged.
    beta = CVA_BA_BETA
    k_full = beta * k_reduced + (1.0 - beta) * k_hedged

    # Step 8: OFR_full and RWEA_full.
    ofr_cva_full = CVA_DS_BA_CVA * k_full
    rwea_cva_full = ofr_cva_full * CVA_RWEA_MULTIPLIER

    # Step 9: ratio pin — the strongest invariant for the acceptance test.
    ratio = rwea_cva_full / rwea_cva_reduced if rwea_cva_reduced != 0.0 else float("nan")

    return {
        "df_ns": df_ns,
        "scva_c": scva_c,
        "k_reduced": k_reduced,
        "ofr_cva_reduced": ofr_cva_reduced,
        "rwea_cva_reduced": rwea_cva_reduced,
        "hedge_notional": hedge_notional,
        "snh_c": snh_c,
        "hma_c": hma_c,
        "ih": ih,
        "k_hedged": k_hedged,
        "k_full": k_full,
        "ofr_cva_full": ofr_cva_full,
        "rwea_cva_full": rwea_cva_full,
        "ratio_full_reduced": ratio,
    }


# ---------------------------------------------------------------------------
# Parquet save helpers.
# ---------------------------------------------------------------------------


def save_cva_hedge_a1_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all CVA-HEDGE-A1 parquet files to output_dir.

    Files produced:
        cva_hedge_a1_single_name.parquet  — 1 row (H_SN_CVA_001, IDENTICAL,
                                            FINANCIAL/IG, M=3.0, placeholder notional)

    NOTE on placeholder notional: the parquet uses the P8.60 reference EAD
    divided by alpha (5_480_017.519 / 1.4 = 3_914_298.228) as a representative
    placeholder.  The acceptance test rebuilds this row from the live pipeline
    EAD before feeding it to the CVA engine.  Do not use the parquet notional
    for golden-value computation.

    Args:
        output_dir: Target directory.  Defaults to the directory containing
            this script (``tests/fixtures/p8_62/``).

    Returns:
        Dict mapping artefact name to saved absolute Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    # Placeholder notional: P8.60 reference EAD (10y CCR-A1) / alpha.
    # This is indicative only; the live test uses the materialised 3y EAD.
    _REFERENCE_EAD = 5_480_017.519
    placeholder_notional = _REFERENCE_EAD / CVA_ALPHA  # = 3_914_298.228

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("cva_hedge_a1_single_name", create_perfect_single_name_hedge_frame(placeholder_notional)),
    ]

    saved: dict[str, Path] = {}
    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def save_p862_fixtures(output_dir: Path | None = None) -> list[tuple[str, int]]:
    """
    Smoke-check the CVA-HEDGE-A1 bundle and persist parquet files to output_dir.

    Invariants checked:
        1. CVA hedge schema columns match CVA_HEDGE_SCHEMA_DTYPES exactly.
        2. Hedge frame has exactly 1 row (H_SN_CVA_001).
        3. cva_hedge_type == "SINGLE_NAME".
        4. counterparty_reference == CVA_A1_COUNTERPARTY_REF.
        5. cva_hedge_correlation_band == "IDENTICAL".
        6. cva_hedge_rw_sector == CVA_A1_CVA_RW_SECTOR ("FINANCIAL").
        7. cva_hedge_rw_rating_band == CVA_A1_CVA_RW_RATING_BAND ("IG").
        8. cva_hedge_residual_maturity_years == CVA_A1_CVA_EFFECTIVE_MATURITY_YEARS (3.0).
        9. cva_hedge_eligible == True.
        10. compute_cva_full_golden produces K_hedged ≈ 0.
        11. ratio rwea_cva_full / rwea_cva_reduced ≈ 0.25 (beta identity).
        12. P8.60 imports resolve cleanly (build_cva_a1_inputs, compute_cva_a1_golden).

    Returns:
        List of (filename, row_count) tuples for the master report.
    """
    saved = save_cva_hedge_a1_fixtures(output_dir)

    # Invariant 1+2: hedge frame schema and row count.
    hedge_df = pl.read_parquet(next(iter(saved.values())))
    _expected_cols = set(CVA_HEDGE_SCHEMA_DTYPES.keys())
    _actual_cols = set(hedge_df.columns)
    if _actual_cols != _expected_cols:
        missing = _expected_cols - _actual_cols
        extra = _actual_cols - _expected_cols
        raise AssertionError(f"P8.62: hedge schema mismatch. Missing: {missing}, Extra: {extra}")
    if len(hedge_df) != 1:
        raise AssertionError(f"P8.62: expected 1 hedge row, got {len(hedge_df)}")

    # Invariants 3-9: per-column value checks.
    if hedge_df["cva_hedge_reference"][0] != CVA_HEDGE_A1_REF:
        raise AssertionError(
            f"P8.62: cva_hedge_reference {hedge_df['cva_hedge_reference'][0]!r} "
            f"!= {CVA_HEDGE_A1_REF!r}"
        )
    if hedge_df["cva_hedge_type"][0] != "SINGLE_NAME":
        raise AssertionError(
            f"P8.62: cva_hedge_type {hedge_df['cva_hedge_type'][0]!r} != 'SINGLE_NAME'"
        )
    if hedge_df["counterparty_reference"][0] != CVA_A1_COUNTERPARTY_REF:
        raise AssertionError("P8.62: counterparty_reference mismatch")
    if hedge_df["cva_hedge_correlation_band"][0] != "IDENTICAL":
        raise AssertionError("P8.62: cva_hedge_correlation_band must be 'IDENTICAL'")
    if hedge_df["cva_hedge_rw_sector"][0] != CVA_A1_CVA_RW_SECTOR:
        raise AssertionError("P8.62: cva_hedge_rw_sector mismatch")
    if hedge_df["cva_hedge_rw_rating_band"][0] != CVA_A1_CVA_RW_RATING_BAND:
        raise AssertionError("P8.62: cva_hedge_rw_rating_band mismatch")
    if (
        abs(hedge_df["cva_hedge_residual_maturity_years"][0] - CVA_A1_CVA_EFFECTIVE_MATURITY_YEARS)
        > 1e-9
    ):
        raise AssertionError("P8.62: cva_hedge_residual_maturity_years mismatch")
    if not hedge_df["cva_hedge_eligible"][0]:
        raise AssertionError("P8.62: cva_hedge_eligible must be True")

    # Invariant 10+11: golden computation invariants.
    test_ead = 5_480_017.519  # P8.60 reference EAD (10y CCR-A1 swap) for smoke check
    golden = compute_cva_full_golden(test_ead)

    if golden["k_hedged"] > 1.0:  # should be numerically ~0
        raise AssertionError(
            f"P8.62: K_hedged={golden['k_hedged']:.2e} must be ~0 for perfect hedge"
        )

    _ratio = golden["ratio_full_reduced"]
    _tol = 1e-9
    if abs(_ratio - CVA_BA_BETA) > _tol:
        raise AssertionError(
            f"P8.62: ratio RWEA_full/RWEA_reduced={_ratio:.10f} != beta={CVA_BA_BETA} "
            f"(diff={abs(_ratio - CVA_BA_BETA):.2e})"
        )

    # Invariant 12: P8.60 imports resolve (smoke-check only; covered by invariants above).
    _inputs = build_cva_a1_inputs()
    if _inputs.raw_data_bundle.ccr is None:
        raise AssertionError("P8.62: P8.60 CCR bundle must not be None")

    return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]


def main() -> None:
    """Entry point for standalone fixture generation and verification."""
    import sys

    saved = save_cva_hedge_a1_fixtures()
    print("CVA-HEDGE-A1 fixture generation complete (P8.62)")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<40} {len(df):>2} row(s)  {len(df.columns):>2} cols  ->  {path.name}")
    print("-" * 70)

    # Verify the perfect-hedge identity with the P8.60 reference EAD.
    ead_reference = 5_480_017.519  # CCR-A1 10y EAD (smoke-check only)
    golden = compute_cva_full_golden(ead_reference)

    print()
    print("Smoke-check using P8.60 reference EAD = 5,480,017.519:")
    print(f"  hedge_notional (EAD/alpha) = {golden['hedge_notional']:.4f}")
    print(f"  SCVA_c                     = {golden['scva_c']:.6f}")
    print(f"  SNH_c                      = {golden['snh_c']:.6f}  (should equal SCVA_c)")
    print(f"  HMA_c                      = {golden['hma_c']:.2e}  (should be 0)")
    print(f"  IH                         = {golden['ih']:.2e}   (no index hedges)")
    print(f"  K_hedged                   = {golden['k_hedged']:.2e}  (should be ~0)")
    print(f"  K_reduced                  = {golden['k_reduced']:.6f}")
    print(f"  K_full (beta*K_reduced)    = {golden['k_full']:.6f}")
    print(f"  RWEA_reduced               = {golden['rwea_cva_reduced']:.4f}")
    print(f"  RWEA_full                  = {golden['rwea_cva_full']:.4f}")
    print(f"  Ratio RWEA_full/RWEA_red   = {golden['ratio_full_reduced']:.10f}  (expect beta=0.25)")
    print()

    # Confirm ratio == beta exactly.
    ratio = golden["ratio_full_reduced"]
    assert abs(ratio - CVA_BA_BETA) < 1e-9, (
        f"SMOKE-CHECK FAILED: ratio={ratio} != beta={CVA_BA_BETA}"
    )
    print("SMOKE-CHECK PASSED: RWEA_full / RWEA_reduced == 0.25 (beta) exactly")
    print()
    print("NOTE: acceptance tests must derive hedge_notional from the ACTUAL ead_ccr")
    print("      the pipeline emits for the 3-year trade (= ead_ccr / CVA_ALPHA).")

    sys.exit(0)


if __name__ == "__main__":
    main()
