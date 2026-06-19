"""
Master script to generate all test fixture parquet files.

This script runs all fixture generators in the correct order to produce
a complete set of test data for RWA calculator acceptance testing.

Usage:
    uv run python tests/fixtures/generate_all.py
"""

import sys
from dataclasses import dataclass
from pathlib import Path

import polars as pl

# Repo root on sys.path: the per-P-code generator modules import the
# contract-derived builders as ``from tests.fixtures...`` (migration
# Phase 3), which resolves under pytest but not when this script loads
# them standalone from their own directories.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Fixture parquet filenames (referenced from multiple generators / integrity checks).
COUNTERPARTIES_PARQUET = "counterparties.parquet"
MODEL_PERMISSIONS_PARQUET = "model_permissions.parquet"

# Report label for builders that construct in-memory frames only (no parquet on disk).
PYTHON_ONLY_NO_PARQUET = "(python-only builder — no parquet)"

# Shared CCR builder module names cleared from sys.modules after each generator runs:
# the ccr/*.py modules use relative imports and must be reloaded per package-root insert.
CCR_GOLDEN_A1_MODULE = "ccr.golden_ccr_a1"
CCR_TRADE_BUILDER_MODULE = "ccr.trade_builder"
CCR_NETTING_SET_BUILDER_MODULE = "ccr.netting_set_builder"
CCR_MARGIN_BUILDER_MODULE = "ccr.margin_builder"


def main() -> None:
    """Entry point for master fixture generation."""
    fixtures_dir = Path(__file__).parent
    results = generate_all_fixtures(fixtures_dir)
    print_master_report(results, fixtures_dir)
    print_data_integrity_check(fixtures_dir)


@dataclass
class FixtureGroupResult:
    """Result of a fixture group generation."""

    group_name: str
    output_dir: Path
    file_count: int
    total_records: int
    files: list[tuple[str, int]]  # (filename, record_count)


def generate_all_fixtures(fixtures_dir: Path) -> list[FixtureGroupResult]:
    """
    Generate all fixture parquet files.

    Args:
        fixtures_dir: Root fixtures directory.

    Returns:
        List of generation results for each fixture group.
    """
    results = []

    # Import and run each generator
    generators = [
        ("Counterparties", "counterparty", _generate_counterparties),
        ("Mappings", "mapping", _generate_mappings),
        ("Ratings", "ratings", _generate_ratings),
        ("Exposures", "exposures", _generate_exposures),
        ("Collateral", "collateral", _generate_collateral),
        ("Guarantees", "guarantee", _generate_guarantees),
        ("Provisions", "provision", _generate_provisions),
        ("FX Rates", "fx_rates", _generate_fx_rates),
        ("Model Permissions", "model_permissions", _generate_model_permissions),
        ("P1.114 (null book_code / null country_code)", "p1_114", _generate_p1114),
        ("P1.112 (non-UK unrated PSE sovereign-derived RW)", "p1_112", _generate_p1112),
        ("P1.98 (subordinated corporate A-IRB LGD floor fallback)", "p1_98", _generate_p198),
        (
            "P1.99 (CRR Art. 120(2) Table 4 short-term rated institution RW)",
            "p1_99",
            _generate_p199,
        ),
        ("P1.117 (B31 HVCRE slotting short-maturity subgrades)", "p1_117", _generate_p1117),
        ("P1.125 (classifier FSE-column-missing warning CLS007)", "p1_125", _generate_p1125),
        (
            "P1.121 (CRR Art. 121(3) unrated institution short-term 20% RW)",
            "p1_121",
            _generate_p1121,
        ),
        ("P1.124 (CRR Art. 237(2)(a) guarantee maturity ineligibility)", "p1_124", _generate_p1124),
        (
            "P1.126 (classifier null-revenue conservative-large default CLS008)",
            "p1_126",
            _generate_p1126,
        ),
        ("P1.156 (PSM guarantor LGD seniority/FSE-aware Art. 236/161)", "p1_156", _generate_p1156),
        (
            "P1.157 (PSM 'no better than direct' PD floor Art. 160(4))",
            "p1_157",
            _generate_p1157,
        ),
        (
            "P1.139 (B31 CIU look-through equity transitional floor Rules 4.7-4.8 higher-of)",
            "p1_139",
            _generate_p1139,
        ),
        (
            "P1.182 (long-established PE/VC 250% vs 400% business-age split)",
            "p1_182",
            _generate_p1182,
        ),
        (
            "P1.100 (CRR Art. 137 ECA MEIP score 2 → 20% sovereign RW)",
            "p1_100",
            _generate_p1100,
        ),
        (
            "P1.101 (CRR Art. 226(1) non-daily revaluation haircut adjustment)",
            "p1_101",
            _generate_p1101,
        ),
        (
            "P1.104 (CRR Art. 239(1) FCSM binary maturity-mismatch eligibility)",
            "p1_104_art_239_1_fcsm_maturity",
            _generate_p1104,
        ),
        (
            "P1.181 (CRR Art. 126(2)(d) commercial RE proportion split)",
            "p1_181",
            _generate_p1181,
        ),
        (
            "P1.105 (B31 Art. 120(2B) Table 4A short-term institution ECAI RW)",
            "p1_105",
            _generate_p1105,
        ),
        (
            "P1.103 (B31 Art. 122(3) Table 6A short-term corporate ECAI RW)",
            "p1_103",
            _generate_p1103,
        ),
        (
            "P1.128 (B31 Art. 121(4) SCRA short-term trade finance exception)",
            "p1_128",
            _generate_p1128,
        ),
        (
            "P1.186 (CRR Art. 224(2)(a) FX haircut H_fx default liquidation scaling)",
            "p1_186",
            _generate_p1186,
        ),
        (
            "P1.96 (CRR Art. 197/207(2) covered-bond collateral haircut routing)",
            "p1_96",
            _generate_p196,
        ),
        (
            "P1.118 (CRR Art. 166(9) F-IRB 20% CCF short-term trade LC exception)",
            "p1_118",
            _generate_p1118,
        ),
        (
            "P1.120 (B31 Art. 127(1) defaulted corporate FCCM cash, gross denominator fix)",
            "p1_120",
            _generate_p1120,
        ),
        (
            "P1.151 (B31 Art. 161(1)(e)/(f)/(g) purchased receivables F-IRB LGD routing)",
            "p1_151",
            _generate_p1151,
        ),
        (
            "P1.184 (CRR Art. 117(1) MDB non-named institution routing)",
            "p1_184",
            _generate_p1184,
        ),
        (
            "P1.154 (CRR Art. 118 international org vs Art. 117 non-named MDB routing)",
            "p1_154",
            _generate_p1154,
        ),
        (
            "P1.154-B31 (B31 Art. 118 IO discriminator vs Art. 117(1)(a) Table 2B MDB CQS 2 = 30%)",
            "p1_154_b31",
            _generate_p1154b31,
        ),
        (
            "P1.93 (B31 Art. 222(4) FCSM SFT 0%/10% carve-out + Art. 222(6) non-SFT gating)",
            "p1_93",
            _generate_p193,
        ),
        (
            "P1.159 (PSM correlation re-derivation reads guarantor class Art. 236(1)(a)(i))",
            "p1_159",
            _generate_p1159,
        ),
        (
            "P2.14 (CRR Art. 128 high-risk omitted SI 2021/1078 → residual 100% RW)",
            "p2_14",
            _generate_p214,
        ),
        (
            "P1.110 (B31 SA RWSM corporate CQS-3 guarantor RW = 75% Art. 122(2) Table 6)",
            "p1_110",
            _generate_p1110,
        ),
        (
            "P1.109 (CRR Art. 239(3) maturity mismatch scaling on unfunded protection)",
            "p1_109",
            _generate_p1109,
        ),
        (
            "P1.160 (PSM LGD routing by guarantor_seniority — subordinated Art. 161(1)(b))",
            "p1_160",
            _generate_p1160,
        ),
        (
            "P1.145 (deterministic dedup of duplicate model_permissions rows)",
            "p1_145",
            _generate_p1145,
        ),
        (
            "P1.165 (CRR receivables collateral, F-IRB, no Art. 224 volatility haircut)",
            "p1_165",
            _generate_p1165,
        ),
        (
            "P1.190 (B31 Art. 230 F-IRB continuous LGD* formula — RE/other-physical/threshold)",
            "p1_190",
            _generate_p1190,
        ),
        (
            "P1.147 (ValidationRequest IRB mode requires model_permissions)",
            "api_validation",
            _generate_p1147,
        ),
        (
            "P2.39 (equity SA-only enforcement — Art. 147A classifier guard)",
            "p2_39",
            _generate_p239,
        ),
        (
            "P2.19 (B31 Art. 133(4) unlisted equity, young business, non-speculative → 400%)",
            "p2_19",
            _generate_p219,
        ),
        (
            "P1.153 (CRR Art. 155(3) PD/LGD equity approach — exchange-traded, no 1.5x)",
            "p1_153",
            _generate_p1153,
        ),
        (
            "P1.123 (CRR Art. 223(5) FCCM exposure volatility haircut HE for SFT exposures)",
            "p1_123",
            _generate_p1123,
        ),
        (
            "P1.140 (B31 Art. 124(3)/124K ADC classification derivation via is_under_construction)",
            "p1_140",
            _generate_p1140,
        ),
        (
            "P1.142 (B31 Art. 124E three-property limit → income-producing RE routing)",
            "p1_142",
            _generate_p1142,
        ),
        (
            "P1.161 (PRA Art. 191A(2)(e)(i) funded-only look-through two-layer protection)",
            "p1_161",
            _generate_p1161,
        ),
        (
            "P1.122 (CRR Art. 120(2) Table 4 short-term institution guarantor substitution)",
            "p1_122",
            _generate_p1122,
        ),
        (
            "P1.95 (B31 SCRA-grade dispatch for unrated institution guarantor)",
            "p1_95",
            _generate_p195,
        ),
        (
            "P1.127 (CRR Art. 159 Pool B EL shortfall — AVA + other_OFR no double-count)",
            "p1_127",
            _generate_p1127,
        ),
        (
            "P1.130 (B31 Art. 92(2A) output floor binding — unrated F-IRB + SA portfolio)",
            "p1_130",
            _generate_p1130,
        ),
        (
            "P2.18 (B31 Art. 226(1) 20-day secured-lending / FX-mismatch / weekly reval)",
            "p2_18",
            _generate_p218,
        ),
        (
            "P1.94a (is_hedged flag gates Art. 123B currency-mismatch multiplier)",
            "p1_94a",
            _generate_p194a,
        ),
        (
            "P1.94f (exposure-class gate on Art. 123B currency-mismatch multiplier)",
            "p1_94f",
            _generate_p194f,
        ),
        (
            "P1.94b (B31 hedge_coverage_ratio < 0.90 gate — Art. 123B(2) multiplier fires)",
            "p1_94b",
            _generate_p194b,
        ),
        (
            "P1.94d (B31 Art. 123B(2A) revolving-instalment rule — full-draw hedge rescale)",
            "p1_94d",
            _generate_p194d,
        ),
        (
            "P1.94e (B31 Art. 123B transitional gate — reporting_date < 2027-01-01 suppresses multiplier)",
            "p1_94e",
            _generate_p194e,
        ),
        (
            "P2.17 (CRR Art. 123 second subparagraph payroll/pension loan 35% RW)",
            "p2_17",
            _generate_p217,
        ),
        (
            "P2.43 (PSM LGD source switch — Art. 236(1)(a)(i) option (i))",
            "p2_43",
            _generate_p243,
        ),
        (
            "P2.44 (SA-SL inferred-rating fallback suppression Art. 139(2B) object-finance 100%)",
            "p2_44",
            _generate_p244,
        ),
        (
            "P1.122(a) (IRB borrower + null-PD corporate guarantor → SA-fallback branch)",
            "p1_122a",
            _generate_p1122a,
        ),
        (
            "P1.122(b) (IRB borrower + unrated SCRA-B institution guarantor)",
            "p1_122b",
            _generate_p1122b,
        ),
        (
            "PSE/RGLA guarantor (Phase 4 Slice 5 — IRB borrower + PSE/RGLA SA guarantors)",
            "pse_rgla_guarantor",
            _generate_pse_rgla_guarantor,
        ),
        (
            "P2.36 (sovereign/institution PD floor first-class config fields)",
            "p2_36",
            _generate_p236,
        ),
        (
            "P2.33 / B31-D.CCF9 (UK residential-mortgage commitment 50% CCF override)",
            "p2_33",
            _generate_p233,
        ),
        (
            "P2.32 / B31-D.CCF10 (purchased-receivables undrawn-commitment CCF Art. 166E(5))",
            "p2_32",
            _generate_p232,
        ),
        (
            "CCR-A1 golden (single 10y GBP IR swap, unmargined)",
            "ccr",
            _generate_ccr_golden,
        ),
        (
            "P8.14-marg (margined MF = 3/2 x sqrt(MPOR_eff/250), Art. 279c(2) + Art. 285 cascade)",
            "ccr",
            _generate_p814_margined,
        ),
        (
            "P8.15 (IR hedging-set partition + asset-class add-on, Art. 277/277a/280a, GBP)",
            "ccr",
            _generate_p815,
        ),
        (
            "P8.18 (CRR Art. 272(4) legal-enforceability gate — 2 trades, 1 non-enforceable NS)",
            "ccr",
            _generate_p818,
        ),
        (
            "P8.16 (SA-CCR PFE multiplier Art. 278(3) — under-collateralised + cap sub-test)",
            "ccr",
            _generate_p816,
        ),
        (
            "P8.24 (CRR Art. 378/379 failed trades — 4 DvP rows + 1 non-DvP Col-4 row)",
            "ccr",
            _generate_p824,
        ),
        (
            "P8.25 (QCCP trade exposure RW — CCR-B1a 2%, CCR-B1b 4%, CCR-B1c 50% SA fallback CQS-2)",
            "ccr",
            _generate_p825,
        ),
        (
            "P8.27 (CRR Art. 291 WWR identification — specific WWR break-out + LGD=100% override)",
            "ccr",
            _generate_p827,
        ),
        (
            "P8.53 / CCR-WWR-1 (orchestrator-ready WWR bundle — institution CQS 2 + full RawDataBundle)",
            "ccr",
            _generate_ccr_wwr1,
        ),
        (
            "CCR-A5 golden (single-name equity TRS, 1y, unmargined)",
            "ccr",
            _generate_ccr_a5,
        ),
        (
            "CCR-A10 golden (mixed-asset-class netting set — one trade per asset class)",
            "ccr",
            _generate_ccr_a10,
        ),
        (
            "P8.38 CCR-A11/A12 (SA-CCR SFT FCCM EAD - uncollateralised + cash-collateralised)",
            "ccr",
            _generate_ccr_a11_a12,
        ),
        (
            "P1.30(e) (CRR Art. 234 mezzanine partial-protection tranching attachment/detachment)",
            "p1_30e",
            _generate_p130e,
        ),
        (
            "P5.15 (B31 Art. 123A(1)(b)(ii) 0.2% retail portfolio granularity sub-condition)",
            "p5_15",
            _generate_p515,
        ),
        (
            "P2.29 (OV1 equity sub-approach rows 11-14 + output-floor rows 26/27 — Python-only)",
            "p2_29",
            _generate_p229,
        ),
        (
            "P1.141 (B31 Art. 124(4) all-or-nothing qualifying gate — mixed RE 124J fallback)",
            "p1_141",
            _generate_p1141,
        ),
        (
            "P2.30 (Annex I Row 3 vs Row 4 CCF discrimination — MR_ISSUED vs MR risk_type)",
            "p2_30",
            _generate_p230,
        ),
        (
            "P2.31 (Annex I obs_product -> risk_type fill — ACCEPTANCE/FR, PERF_BOND/MLR, explicit-wins)",
            "p2_31",
            _generate_p231,
        ),
        (
            "P2.49 (CR9 column-a taxonomy extension — 5 F-IRB + 10 A-IRB leaf classes)",
            "p2_49",
            _generate_p249,
        ),
        (
            "P2.15 (equity transitional irrevocable opt-out — Rules 4.9-4.10 higher-of suppression)",
            "p2_15",
            _generate_p215,
        ),
        (
            "P2.47 (Basel 3.1 Art. 137 ECA MEIP score 2 → 20% sovereign RW — B31 arm)",
            "p2_47",
            _generate_p247,
        ),
        (
            "P2.41 (COREP C 02.00 corporate sub-row split — FSE + large-corp-by-revenue → row 0295)",
            "p2_41",
            _generate_p241,
        ),
        (
            "P2.38 (CRR Art. 155(2) non-trading-book short-position netting — long+short ISSUER-A)",
            "p2_38",
            _generate_p238,
        ),
        (
            "P2.46 (Art. 150(1) PPU provenance ppu_reason — C 07.00 rows 0050/0060 discrimination)",
            "p2_46",
            _generate_p246,
        ),
        (
            "P2.48 (CR8 RWEA-flow statement — two-period IRB snapshot, opening + residual + closing)",
            "p2_48",
            _generate_p248,
        ),
        (
            "P2.25b (CR5 RE loan-split sub-row bucketing — not-materially-dependent 55%-LTV split, B3.1 only)",
            "p2_25",
            _generate_p225,
        ),
        (
            "P4.20 (C 08.02 IRB rows keyed by firm-supplied internal rating grade — grade-path fixture)",
            "p4_20",
            _generate_p420,
        ),
        (
            "P1.191 (QRRE per-individual aggregate nominal qualification — CRR Art. 154(4)(c) / B31 Art. 147(5A)(c))",
            "p1_191",
            _generate_p1191,
        ),
        (
            "P1.193 (B31 Art. 122(2) Table 6 rated corporate-SME — CQS gate on 85% override)",
            "p1_193",
            _generate_p1193,
        ),
        (
            "P1.197 (CRR-E.CCF1 slotting OBS EAD — Art. 166(8)(d) F-IRB CCF 75% vs SA CCF 50%)",
            "p1_197",
            _generate_p1197,
        ),
        (
            "P1.196 (CRR-SA-SME-CQS1 rated corporate-SME CQS 1 — Art. 122 20% vs 100% override)",
            "p1_196",
            _generate_p1196,
        ),
        (
            "P1.200 (B31 Art. 239(3) guarantee/CDS maturity-mismatch scaling wrongly gated on is_crr)",
            "p1_200",
            _generate_p1200,
        ),
        (
            "P8.39 (CCR-CCP-1/CCP-2 orchestrator QCCP wiring — 2%/4% vs 50% anti-degenerate baseline)",
            "ccr",
            _generate_p839_ccp,
        ),
        (
            "P8.28 (CCR-ALPHA-1/2/3 per-counterparty α=1.0 carve-out — non_financial/pension_scheme/financial)",
            "ccr",
            _generate_p828_alpha,
        ),
        (
            "P8.29 (CCR-ALPHA-ADDON-1..4 transitional alpha add-on — PS1/26 Art. 274(2A) phasing)",
            "ccr",
            _generate_p829_addon,
        ),
        (
            "P8.23 (CCR-LS-1/LS-1-CTRL long-settlement no-op regression pin — EAD invariant)",
            "ccr",
            _generate_p823_ls,
        ),
        (
            "P8.31 (CCR-IRB-1 — 5y GBP IR swap, F-IRB corporate CP_IRB_001, MOD_CORP_FIRB)",
            "ccr",
            _generate_ccr_irb1,
        ),
        (
            "P8.43 (CCR-C1/C2/C3 DvP failed-trade Art. 378 band ladder — 3 distinct CPs)",
            "ccr",
            _generate_p843,
        ),
        (
            "P8.55 / B31-CCR-FLOOR-1 (CCR-only SA portfolio — output floor S-TREA/U-TREA inclusion pin)",
            "ccr",
            _generate_ccr_floor1,
        ),
        (
            "P8.49 (CCR-B2/B3/B4 default-fund-contribution capital stack — Art. 308/309)",
            "ccr",
            _generate_p849_dfc,
        ),
        (
            "P8.42 / CCR-B5 (non-QCCP CCP trade exposure CQS-1 -> 20% institution RW)",
            "ccr",
            _generate_p842_nonqccp_b5,
        ),
        (
            "P8.44 (CCR-D1/D2/D3 Simplified SA-CCR + OEM fall-through regression guards)",
            "ccr",
            _generate_ccr_d1_d3,
        ),
        (
            "P8.45 (CCR-E1..E5 default-risk RWA routing — institution/corporate/sovereign x CRR/B3.1)",
            "ccr",
            _generate_p845_e1_e5,
        ),
        (
            "P8.60 (CVA-A1 BA-CVA reduced-K vertical slice — single Financials IG counterparty)",
            "p8_60",
            _generate_p860_cva_a1,
        ),
        (
            "P8.62 (CVA-HEDGE-A1 full BA-CVA — perfect single-name CDS hedge, beta=0.25 ratio pin)",
            "p8_62",
            _generate_p862_cva_hedge_a1,
        ),
    ]

    for group_name, subdir, generator_func in generators:
        output_dir = fixtures_dir / subdir
        try:
            files = generator_func(output_dir)
            total_records = sum(count for _, count in files)
            results.append(
                FixtureGroupResult(
                    group_name=group_name,
                    output_dir=output_dir,
                    file_count=len(files),
                    total_records=total_records,
                    files=files,
                )
            )
        except Exception as e:
            print(f"ERROR generating {group_name}: {e}")
            raise

    return results


def _generate_counterparties(output_dir: Path) -> list[tuple[str, int]]:
    """Generate counterparty fixtures."""
    sys.path.insert(0, str(output_dir))
    try:
        from corporate import create_corporate_counterparties
        from institution import create_institution_counterparties
        from retail import create_retail_counterparties
        from sovereign import create_sovereign_counterparties
        from specialised_lending import create_specialised_lending_counterparties

        frames = [
            create_sovereign_counterparties(),
            create_institution_counterparties(),
            create_corporate_counterparties(),
            create_retail_counterparties(),
            create_specialised_lending_counterparties(),
        ]

        combined = pl.concat(frames)
        combined.write_parquet(output_dir / COUNTERPARTIES_PARQUET)
        return [(COUNTERPARTIES_PARQUET, len(combined))]
    finally:
        sys.path.remove(str(output_dir))
        # Clear cached module to avoid collision with ratings/specialised_lending.py
        sys.modules.pop("specialised_lending", None)


def _generate_mappings(output_dir: Path) -> list[tuple[str, int]]:
    """Generate mapping fixtures."""
    sys.path.insert(0, str(output_dir))
    try:
        from lending_mapping import create_lending_mappings, save_lending_mappings
        from org_mapping import create_org_mappings, save_org_mappings

        files = []
        for name, create_fn, save_fn in [
            ("org_mapping.parquet", create_org_mappings, save_org_mappings),
            ("lending_mapping.parquet", create_lending_mappings, save_lending_mappings),
        ]:
            df = create_fn()
            save_fn(output_dir)
            files.append((name, len(df)))
        return files
    finally:
        sys.path.remove(str(output_dir))


def _generate_ratings(output_dir: Path) -> list[tuple[str, int]]:
    """Generate ratings fixtures."""
    sys.path.insert(0, str(output_dir))
    try:
        from ratings import create_ratings, save_ratings
        from specialised_lending import (
            create_specialised_lending_data,
            save_specialised_lending_data,
        )

        files = []
        for name, create_fn, save_fn in [
            ("ratings.parquet", create_ratings, save_ratings),
            (
                "specialised_lending.parquet",
                create_specialised_lending_data,
                save_specialised_lending_data,
            ),
        ]:
            df = create_fn()
            save_fn(output_dir)
            files.append((name, len(df)))
        return files
    finally:
        sys.path.remove(str(output_dir))


def _generate_exposures(output_dir: Path) -> list[tuple[str, int]]:
    """Generate exposure fixtures."""
    sys.path.insert(0, str(output_dir))
    try:
        from contingents import create_contingents, save_contingents
        from facilities import create_facilities, save_facilities
        from facility_mapping import create_facility_mappings, save_facility_mappings
        from loans import create_loans, save_loans

        files = []
        for name, create_fn, save_fn in [
            ("facilities.parquet", create_facilities, save_facilities),
            ("loans.parquet", create_loans, save_loans),
            ("contingents.parquet", create_contingents, save_contingents),
            ("facility_mapping.parquet", create_facility_mappings, save_facility_mappings),
        ]:
            df = create_fn()
            save_fn(output_dir)
            files.append((name, len(df)))
        return files
    finally:
        sys.path.remove(str(output_dir))


def _generate_collateral(output_dir: Path) -> list[tuple[str, int]]:
    """Generate collateral fixtures."""
    sys.path.insert(0, str(output_dir))
    try:
        from collateral import create_collateral, save_collateral

        df = create_collateral()
        save_collateral(output_dir)
        return [("collateral.parquet", len(df))]
    finally:
        sys.path.remove(str(output_dir))


def _generate_guarantees(output_dir: Path) -> list[tuple[str, int]]:
    """Generate guarantee fixtures."""
    sys.path.insert(0, str(output_dir))
    try:
        from guarantee import create_guarantees, save_guarantees

        df = create_guarantees()
        save_guarantees(output_dir)
        return [("guarantee.parquet", len(df))]
    finally:
        sys.path.remove(str(output_dir))


def _generate_provisions(output_dir: Path) -> list[tuple[str, int]]:
    """Generate provision fixtures."""
    sys.path.insert(0, str(output_dir))
    try:
        from provision import create_provisions, save_provisions

        df = create_provisions()
        save_provisions(output_dir)
        return [("provision.parquet", len(df))]
    finally:
        sys.path.remove(str(output_dir))


def _generate_fx_rates(output_dir: Path) -> list[tuple[str, int]]:
    """Generate FX rates fixtures."""
    sys.path.insert(0, str(output_dir))
    try:
        from fx_rates import create_fx_rates, save_fx_rates

        df = create_fx_rates()
        save_fx_rates(output_dir)
        return [("fx_rates.parquet", len(df))]
    finally:
        sys.path.remove(str(output_dir))


def _generate_model_permissions(output_dir: Path) -> list[tuple[str, int]]:
    """Generate model permissions fixtures."""
    sys.path.insert(0, str(output_dir))
    try:
        from model_permissions import create_model_permissions, save_model_permissions

        df = create_model_permissions()
        save_model_permissions(output_dir)
        return [(MODEL_PERMISSIONS_PARQUET, len(df))]
    finally:
        sys.path.remove(str(output_dir))


def _generate_p1114(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.114 fixtures (null-propagation defect in model permissions filter)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_114 import save_p1114_fixtures

        saved = save_p1114_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_114", None)


def _generate_p1112(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.112 fixtures (non-UK unrated PSE sovereign-derived risk weight)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_112 import save_p1112_fixtures

        saved = save_p1112_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_112", None)


def _generate_p198(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.98 fixtures (subordinated corporate A-IRB LGD floor fallback path)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_98 import save_p198_fixtures

        saved = save_p198_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_98", None)


def _generate_p199(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.99 fixtures (CRR Art. 120(2) Table 4 short-term rated institution RW)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_99 import save_p199_fixtures

        saved = save_p199_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_99", None)


def _generate_p1117(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.117 fixtures (B31 HVCRE slotting short-maturity subgrades)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_117 import save_p1117_fixtures

        saved = save_p1117_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_117", None)


def _generate_p1126(output_dir: Path) -> list[tuple[str, int]]:
    """
    Validate P1.126 builder imports (no parquet output — Python-only builder).

    P1.126 tests null vs. non-null annual_revenue values in the counterparty
    LazyFrame to exercise the CLS008 conservative-large-corp warning under
    Basel 3.1.  Like P1.125, this is a Python-only builder: parquet round-trips
    preserve column presence but may alter null handling semantics in edge cases.
    The fixture is exercised by constructing all three named scenario bundles and
    checking schema invariants that matter to the CLS008 logic.
    """
    sys.path.insert(0, str(output_dir))
    try:
        from p1_126 import (  # noqa: F401
            make_scenario_a_bundle,
            make_scenario_b_bundle,
            make_scenario_c_bundle,
        )

        # Smoke-check: all three bundles must construct without raising.
        bundle_a = make_scenario_a_bundle()
        bundle_b = make_scenario_b_bundle()
        bundle_c = make_scenario_c_bundle()

        # Invariant 1: annual_revenue column is present in all three scenarios
        # (it is always present — null in A/C, non-null in B).
        for label, bundle in [("A", bundle_a), ("B", bundle_b), ("C", bundle_c)]:
            cp_cols = bundle.counterparty_lookup.counterparties.collect_schema().names()
            if "annual_revenue" not in cp_cols:
                raise AssertionError(f"Scenario {label}: annual_revenue column must be present")

        # Invariant 2: Scenario A counterparty has null annual_revenue.
        cp_a = bundle_a.counterparty_lookup.counterparties.collect()
        if cp_a["annual_revenue"][0] is not None:
            raise AssertionError("Scenario A: annual_revenue must be null")

        # Invariant 3: Scenario B counterparty has non-null annual_revenue > 440m threshold.
        cp_b = bundle_b.counterparty_lookup.counterparties.collect()
        rev_b = cp_b["annual_revenue"][0]
        if rev_b is None or rev_b <= 440_000_000.0:
            raise AssertionError(f"Scenario B: annual_revenue must be > GBP 440m (got {rev_b})")

        # Invariant 4: Scenario C counterparty has null annual_revenue (same data as A).
        cp_c = bundle_c.counterparty_lookup.counterparties.collect()
        if cp_c["annual_revenue"][0] is not None:
            raise AssertionError("Scenario C: annual_revenue must be null")

        # Invariant 5: is_financial_sector_entity is present and False in all scenarios
        # (so FSE restriction does not interfere with the CLS008 path).
        for label, cp_df in [("A", cp_a), ("B", cp_b), ("C", cp_c)]:
            if "is_financial_sector_entity" not in cp_df.columns:
                raise AssertionError(
                    f"Scenario {label}: is_financial_sector_entity must be present"
                )
            if cp_df["is_financial_sector_entity"][0] is not False:
                raise AssertionError(f"Scenario {label}: is_financial_sector_entity must be False")

        # Invariant 6: model_id is present on the exposure and matches M_CORP_AIRB.
        from p1_126 import MODEL_ID  # noqa: PLC0415

        for label, bundle in [("A", bundle_a), ("B", bundle_b), ("C", bundle_c)]:
            exp_cols = bundle.exposures.collect_schema().names()
            if "model_id" not in exp_cols:
                raise AssertionError(f"Scenario {label}: model_id must be present on exposures")
            exp_df = bundle.exposures.collect()
            if exp_df["model_id"][0] != MODEL_ID:
                raise AssertionError(
                    f"Scenario {label}: model_id must be {MODEL_ID!r} "
                    f"(got {exp_df['model_id'][0]!r})"
                )

        # No parquet files written — report zero files, zero records.
        return [(PYTHON_ONLY_NO_PARQUET, 0)]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_126", None)


def _generate_p1125(output_dir: Path) -> list[tuple[str, int]]:
    """
    Validate P1.125 builder imports (no parquet output — Python-only builder).

    P1.125 tests column-schema existence, which cannot be preserved through a
    parquet round-trip (parquet writes include all declared columns regardless of
    whether they appear in the input dict).  The fixture is a Python builder that
    constructs in-memory LazyFrames with controlled schemas.  This function
    exercises the import path and checks the three named scenario bundles can be
    constructed without error.
    """
    sys.path.insert(0, str(output_dir))
    try:
        from p1_125 import (  # noqa: F401
            make_scenario_a_bundle,
            make_scenario_b_bundle,
            make_scenario_c_bundle,
        )

        # Smoke-check: all three bundles must construct without raising.
        bundle_a = make_scenario_a_bundle()
        bundle_b = make_scenario_b_bundle()
        bundle_c = make_scenario_c_bundle()

        # Confirm the critical schema invariants. Under the Phase 3 sealed
        # CounterpartyLookup contract the column ALWAYS exists — the old
        # "absent column" state is unrepresentable; Scenarios A/C now pin
        # the all-null form and Scenario B real values (mirrors the
        # sealed-frame invariant rewrite in test_p1_125_fse_column_warning).
        cp_a = bundle_a.counterparty_lookup.counterparties.collect()
        cp_b = bundle_b.counterparty_lookup.counterparties.collect()
        cp_c = bundle_c.counterparty_lookup.counterparties.collect()

        for label, frame in (("A", cp_a), ("C", cp_c)):
            if "is_financial_sector_entity" not in frame.columns:
                raise AssertionError(
                    f"Scenario {label}: sealed lookup must carry is_financial_sector_entity"
                )
            if frame["is_financial_sector_entity"].null_count() != frame.height:
                raise AssertionError(
                    f"Scenario {label}: is_financial_sector_entity must be all-null (unreported)"
                )
        if "is_financial_sector_entity" not in cp_b.columns:
            raise AssertionError("Scenario B: is_financial_sector_entity must be present")

        # No parquet files written — report zero files, zero records.
        return [(PYTHON_ONLY_NO_PARQUET, 0)]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_125", None)


def _generate_p1121(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.121 fixtures (CRR Art. 121(3) unrated institution short-term 20% RW)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_121 import save_p1121_fixtures

        saved = save_p1121_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_121", None)


def _generate_p1124(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.124 fixtures (CRR Art. 237(2)(a) guarantee maturity ineligibility)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_124 import save_p1124_fixtures

        saved = save_p1124_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_124", None)


def _generate_p1156(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.156 fixtures (PSM guarantor LGD seniority/FSE-aware Art. 236/161)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_156 import save_p1156_fixtures

        saved = save_p1156_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_156", None)


def _generate_p1157(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.157 fixtures (PSM 'no better than direct' PD floor Art. 160(4))."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_157 import save_p1157_fixtures

        saved = save_p1157_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_157", None)


def _generate_p1182(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.182 fixtures (long-established PE/VC 250% vs 400% business-age split)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_182 import save_p1182_fixtures

        saved = save_p1182_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_182", None)


def _generate_p1139(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.139 fixtures (B31 CIU look-through equity transitional floor Rules 4.7-4.8)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_139 import save_p1139_fixtures

        saved = save_p1139_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_139", None)


def _generate_p1100(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.100 fixtures (CRR Art. 137 ECA MEIP score 2 → 20% sovereign RW)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_100 import save_p1100_fixtures

        saved = save_p1100_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_100", None)


def _generate_p1101(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.101 fixtures (CRR Art. 226(1) non-daily revaluation haircut adjustment)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_101 import save_p1101_fixtures

        saved = save_p1101_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_101", None)


def _generate_p1104(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.104 fixtures (CRR Art. 239(1) FCSM binary maturity-mismatch eligibility)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_104 import save_p1104_fixtures

        saved = save_p1104_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_104", None)


def _generate_p1181(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.181 fixtures (CRR Art. 126(2)(d) commercial RE proportion split)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_181 import save_p1181_fixtures

        saved = save_p1181_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_181", None)


def _generate_p1105(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.105 fixtures (B31 Art. 120(2B) Table 4A short-term ECAI institution RW)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_105 import save_p1105_fixtures

        saved = save_p1105_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_105", None)


def _generate_p1103(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.103 fixtures (B31 Art. 122(3) Table 6A short-term ECAI corporate RW)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_103 import save_p1103_fixtures

        saved = save_p1103_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_103", None)


def _generate_p1128(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.128 fixtures (B31 Art. 121(4) SCRA short-term trade finance exception)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_128 import save_p1128_fixtures

        saved = save_p1128_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_128", None)


def _generate_p1118(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.118 fixtures (CRR Art. 166(9) F-IRB 20% CCF short-term trade LC)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_118 import save_p1118_fixtures

        saved = save_p1118_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_118", None)


def _generate_p1186(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.186 fixtures (CRR Art. 224(2)(a) FX haircut H_fx default liquidation scaling)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_186 import save_p1186_fixtures

        saved = save_p1186_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_186", None)


def _generate_p196(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.96 fixtures (CRR Art. 197/207(2) covered-bond collateral haircut routing)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_96 import save_p196_fixtures

        saved = save_p196_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_96", None)


def _generate_p1120(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.120 fixtures (B31 Art. 127(1) defaulted corporate FCCM cash, gross denominator fix)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_120 import save_p1120_fixtures

        saved = save_p1120_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_120", None)


def _generate_p1151(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.151 fixtures (B31 Art. 161(1)(e)/(f)/(g) purchased receivables LGD routing)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_151 import save_p1151_fixtures

        saved = save_p1151_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_151", None)


def _generate_p1184(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.184 fixtures (CRR Art. 117(1) MDB non-named institution routing)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_184 import save_p1184_fixtures

        saved = save_p1184_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_184", None)


def _generate_p1154(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.154 fixtures (CRR Art. 118 international org vs Art. 117 non-named MDB)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_154 import save_p1154_fixtures

        saved = save_p1154_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_154", None)


def _generate_p1154b31(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.154-B31 fixtures (B31 Art. 118 IO discriminator vs Art. 117(1)(a) Table 2B MDB)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_154_b31 import save_p1154b31_fixtures

        data_dir = output_dir / "data"
        saved = save_p1154b31_fixtures(data_dir)
        return [
            (f"data/{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()
        ]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_154_b31", None)


def _generate_p193(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.93 fixtures (B31 Art. 222(4) FCSM SFT 0%/10% carve-out + Art. 222(6))."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_93 import save_p193_fixtures

        saved = save_p193_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_93", None)


def _generate_p1159(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.159 fixtures (PSM correlation re-derivation reads guarantor class Art. 236(1)(a)(i))."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_159 import save_p1159_fixtures

        saved = save_p1159_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_159", None)


def _generate_p214(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P2.14 fixtures (CRR Art. 128 high-risk omitted via SI 2021/1078)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p2_14 import save_p214_fixtures

        saved = save_p214_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p2_14", None)


def _generate_p1110(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.110 fixtures (B31 SA RWSM corporate CQS-3 guarantor RW = 75%)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_110 import save_p1110_fixtures

        data_dir = output_dir / "data"
        saved = save_p1110_fixtures(data_dir)
        return [
            (f"data/{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()
        ]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_110", None)


def _generate_p1109(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.109 fixtures (CRR Art. 239(3) maturity mismatch on unfunded protection)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_109 import save_p1109_fixtures

        saved = save_p1109_fixtures(output_dir / "data")
        return [
            (f"data/{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()
        ]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_109", None)


def _generate_p1160(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.160 fixtures (PSM LGD routing by guarantor_seniority — subordinated case)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_160 import save_p1160_fixtures

        saved = save_p1160_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_160", None)


def _generate_p1145(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.145 fixtures (deterministic dedup of duplicate model_permissions rows)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_145 import save_p1145_fixtures

        saved = save_p1145_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_145", None)


def _generate_p1165(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.165 fixtures (CRR receivables collateral, F-IRB, no Art. 224 volatility haircut)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_165 import save_p1165_fixtures

        saved = save_p1165_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_165", None)


def _generate_p1190(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.190 fixtures (B31 Art. 230 F-IRB continuous LGD* formula)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_190 import save_p1190_fixtures

        saved = save_p1190_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_190", None)


def _generate_p1147(output_dir: Path) -> list[tuple[str, int]]:
    """
    Validate P1.147 builder imports (Python-only builder — no persistent parquet output).

    P1.147 tests the API/validation-plumbing path: DataPathValidator must append
    config/model_permissions.parquet to files_missing and emit a VAL003 APIError
    when permission_mode="irb" and that file is absent.

    The fixture writes files into a caller-supplied temporary directory at test
    time (via write_mandatory_minimum), not into a fixed subdirectory. This
    function smoke-checks the import and confirms the builder round-trips
    correctly into a tempfile directory without error.
    """
    import tempfile

    sys.path.insert(0, str(output_dir))
    try:
        from build_mandatory_only import (  # noqa: PLC0415
            COUNTERPARTY_REF,
            FACILITY_REF,
            LOAN_REF,
            write_mandatory_minimum,
        )

        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path as _Path  # noqa: PLC0415

            result = write_mandatory_minimum(_Path(tmp))
            parquets = list(result.rglob("*.parquet"))
            if len(parquets) != 5:
                raise AssertionError(
                    f"Expected 5 mandatory parquet files, got {len(parquets)}: {parquets}"
                )
            mp = result / "config" / MODEL_PERMISSIONS_PARQUET
            if mp.exists():
                raise AssertionError("config/model_permissions.parquet must NOT be written")

            # Confirm the three scenario constants are exported
            for const_name, val in [
                ("COUNTERPARTY_REF", COUNTERPARTY_REF),
                ("LOAN_REF", LOAN_REF),
                ("FACILITY_REF", FACILITY_REF),
            ]:
                if not isinstance(val, str) or not val:
                    raise AssertionError(f"{const_name} must be a non-empty string")

        return [("(python-only builder — no persistent parquet)", 0)]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("build_mandatory_only", None)


def _generate_p239(output_dir: Path) -> list[tuple[str, int]]:
    """
    Validate P2.39 builder imports (no parquet output — Python-only builder).

    P2.39 tests classifier routing for the equity SA-only guard: the classifier
    must enforce SA-only for equity exposures regardless of IRBPermissions
    configuration.  Like P1.125 and P1.126, this is a Python-only builder that
    constructs in-memory LazyFrames.  This function smoke-checks both named
    scenario bundles and verifies the critical schema invariants.

    The equity exposure EX_EQ_147A_H sits on bundle.exposures (the main
    LazyFrame), NOT on bundle.equity_exposures.  This routes it through
    _build_approach_expr() in classifier.py — the unit under test.
    """
    sys.path.insert(0, str(output_dir))
    try:
        from p2_39 import (  # noqa: F401
            COUNTERPARTY_REF,
            EQUITY_EXPOSURE_REF,
            make_scenario_b31_bundle,
            make_scenario_crr_bundle,
        )

        # Smoke-check: both bundles must construct without raising.
        bundle_b31 = make_scenario_b31_bundle()
        bundle_crr = make_scenario_crr_bundle()

        # Invariant 1: equity_exposures must be None on both bundles — the equity
        # row lives on bundle.exposures, not on the equity_exposures path.
        for label, bundle in [("B31", bundle_b31), ("CRR", bundle_crr)]:
            if bundle.equity_exposures is not None:
                raise AssertionError(
                    f"Scenario {label}: equity_exposures must be None "
                    "(equity row must be on main exposures LazyFrame)"
                )

        # Invariant 2: EX_EQ_147A_H must appear in bundle.exposures (main frame).
        for label, bundle in [("B31", bundle_b31), ("CRR", bundle_crr)]:
            exp_df = bundle.exposures.collect()
            refs = exp_df["exposure_reference"].to_list()
            if EQUITY_EXPOSURE_REF not in refs:
                raise AssertionError(
                    f"Scenario {label}: bundle.exposures must contain {EQUITY_EXPOSURE_REF!r}"
                )

        # Invariant 3: EX_EQ_147A_H row must have exposure_class="equity" and
        # exposure_class_irb="equity" on the main exposures frame.
        for label, bundle in [("B31", bundle_b31), ("CRR", bundle_crr)]:
            exp_df = bundle.exposures.collect()
            eq_row = exp_df.filter(pl.col("exposure_reference") == EQUITY_EXPOSURE_REF)
            if "exposure_class" in eq_row.columns:
                ec = eq_row["exposure_class"][0]
                if ec != "equity":
                    raise AssertionError(
                        f"Scenario {label}: EX_EQ_147A_H exposure_class must be 'equity' "
                        f"(got {ec!r})"
                    )
            if "exposure_class_irb" in eq_row.columns:
                ec_irb = eq_row["exposure_class_irb"][0]
                if ec_irb != "equity":
                    raise AssertionError(
                        f"Scenario {label}: EX_EQ_147A_H exposure_class_irb must be 'equity' "
                        f"(got {ec_irb!r})"
                    )

        # Invariant 4: counterparty must be present and reference CP_EQ_147A_H.
        for label, bundle in [("B31", bundle_b31), ("CRR", bundle_crr)]:
            cp_df = bundle.counterparty_lookup.counterparties.collect()
            cp_refs = cp_df["counterparty_reference"].to_list()
            if COUNTERPARTY_REF not in cp_refs:
                raise AssertionError(
                    f"Scenario {label}: counterparties must contain {COUNTERPARTY_REF!r}"
                )

        # Invariant 5: counterparty entity_type must be "equity" (drives classifier
        # to derive exposure_class="equity" via ENTITY_TYPE_TO_SA_CLASS mapping).
        for label, bundle in [("B31", bundle_b31), ("CRR", bundle_crr)]:
            cp_df = bundle.counterparty_lookup.counterparties.collect()
            et = cp_df["entity_type"][0]
            if et != "equity":
                raise AssertionError(
                    f"Scenario {label}: counterparty entity_type must be 'equity' (got {et!r})"
                )

        # Invariant 6: is_financial_sector_entity must be False (avoids FSE branch).
        for label, bundle in [("B31", bundle_b31), ("CRR", bundle_crr)]:
            cp_df = bundle.counterparty_lookup.counterparties.collect()
            if "is_financial_sector_entity" not in cp_df.columns:
                raise AssertionError(
                    f"Scenario {label}: is_financial_sector_entity must be present"
                )
            if cp_df["is_financial_sector_entity"][0] is not False:
                raise AssertionError(f"Scenario {label}: is_financial_sector_entity must be False")

        # Invariant 7: model_permissions must be None on both bundles (config-side permissions only).
        for label, bundle in [("B31", bundle_b31), ("CRR", bundle_crr)]:
            if bundle.model_permissions is not None:
                raise AssertionError(
                    f"Scenario {label}: model_permissions must be None on the bundle "
                    "(IRBPermissions are config-side for this scenario)"
                )

        # No parquet files written — report zero files, zero records.
        return [(PYTHON_ONLY_NO_PARQUET, 0)]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p2_39", None)


def _generate_p219(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P2.19 fixtures (B31 Art. 133(4) unlisted equity, young business → 400%)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p2_19 import save_p219_fixtures

        saved = save_p219_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p2_19", None)


def _generate_p215(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P2.15 fixtures (equity transitional irrevocable opt-out, Rules 4.9-4.10)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p2_15 import save_p215_fixtures

        saved = save_p215_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p2_15", None)


def _generate_p1153(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.153 fixtures (CRR Art. 155(3) PD/LGD equity approach — exchange-traded)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_153 import save_p1153_fixtures

        saved = save_p1153_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_153", None)


def _generate_p1123(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.123 fixtures (CRR Art. 223(5) FCCM exposure volatility haircut HE)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_123 import save_p1123_fixtures

        saved = save_p1123_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_123", None)


def _generate_p1140(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.140 fixtures (B31 Art. 124(3)/124K ADC classification via is_under_construction)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_140 import save_p1140_fixtures

        saved = save_p1140_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_140", None)


def _generate_p1142(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.142 fixtures (B31 Art. 124E three-property limit → income-producing RE routing)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_142 import save_p1142_fixtures

        saved = save_p1142_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_142", None)


def _generate_p1161(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.161 fixtures (PRA Art. 191A(2)(e)(i) funded-only look-through)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_161 import save_p1161_fixtures

        saved = save_p1161_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_161", None)


def _generate_p1122(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.122 fixtures (CRR Art. 120(2) Table 4 short-term institution guarantor substitution)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_122 import save_p1122_fixtures

        data_dir = output_dir / "data"
        saved = save_p1122_fixtures(data_dir)
        return [
            (f"data/{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()
        ]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_122", None)


def _generate_p195(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.95 fixtures (B31 SCRA-grade dispatch for unrated institution guarantor)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_95 import save_p195_fixtures

        saved = save_p195_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_95", None)


def _generate_p1127(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.127 fixtures (CRR Art. 159 Pool B EL shortfall — AVA + other_OFR no double-count)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_127 import save_p1127_fixtures

        saved = save_p1127_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_127", None)


def _generate_p1130(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.130 fixtures (B31 Art. 92(2A) output floor binding — unrated F-IRB + SA portfolio)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_130 import save_p1130_fixtures

        saved = save_p1130_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_130", None)


def _generate_p218(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P2.18 fixtures (B31 Art. 226(1) 20-day secured-lending / FX-mismatch / weekly reval)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p2_18 import save_p218_fixtures

        saved = save_p218_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p2_18", None)


def _generate_p194a(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.94a fixtures (is_hedged flag gates Art. 123B currency-mismatch multiplier)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_94a import save_p194a_fixtures

        saved = save_p194a_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_94a", None)


def _generate_p194f(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.94f fixtures (exposure-class gate on Art. 123B currency-mismatch multiplier)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_94f import save_p194f_fixtures

        saved = save_p194f_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_94f", None)


def _generate_p194b(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.94b fixtures (B31 hedge_coverage_ratio < 0.90 gate — Art. 123B(2) fires)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_94b import save_p194b_fixtures

        data_dir = output_dir / "data"
        saved = save_p194b_fixtures(data_dir)
        return [
            (f"data/{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()
        ]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_94b", None)


def _generate_p194d(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.94d fixtures (B31 Art. 123B(2A) revolving-instalment full-draw rescale)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_94d import save_p194d_fixtures

        saved = save_p194d_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_94d", None)


def _generate_p194e(output_dir: Path) -> list[tuple[str, int]]:
    """Validate P1.94e fixture module (Python-only; no parquet artefacts).

    This fixture provides named constants for the two reporting-date config
    runs that test the Art. 123B transitional gate.  The test drives
    calculate_single_sa_exposure() directly with an in-memory LazyFrame;
    no parquet is written.
    """
    sys.path.insert(0, str(output_dir))
    try:
        from p1_94e import (
            EAD,
            REPORTING_DATE_B31,
            REPORTING_DATE_PRE_2027,
            RW_B31,
            RW_PRE_2027,
            RWA_B31,
            RWA_PRE_2027,
        )

        # Sanity-check the hand-calculated scalars
        assert RW_PRE_2027 == 0.75, f"RW_PRE_2027={RW_PRE_2027} != 0.75"
        assert RWA_PRE_2027 == 75_000.0, f"RWA_PRE_2027={RWA_PRE_2027} != 75000"
        assert abs(RW_B31 - 1.125) < 1e-9, f"RW_B31={RW_B31} != 1.125"
        assert abs(RWA_B31 - 112_500.0) < 0.01, f"RWA_B31={RWA_B31} != 112500"
        assert REPORTING_DATE_PRE_2027.year == 2026
        assert REPORTING_DATE_B31.year == 2027

        # Two virtual "rows": Run A and Run B constants
        return [("p1_94e.py (Python-only, 2 config runs)", int(EAD // 50_000))]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_94e", None)


def _generate_p217(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P2.17 fixtures (CRR Art. 123 second subparagraph payroll/pension loan 35% RW)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p2_17 import save_p217_fixtures

        saved = save_p217_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p2_17", None)


def _generate_p243(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P2.43 fixtures (PSM LGD source switch — Art. 236(1)(a)(i) option (i))."""
    sys.path.insert(0, str(output_dir))
    try:
        from p2_43 import save_p243_fixtures

        saved = save_p243_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p2_43", None)


def _generate_p244(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P2.44 fixtures (SA-SL inferred-rating fallback suppression Art. 139(2B))."""
    sys.path.insert(0, str(output_dir))
    try:
        from p2_44 import save_p244_fixtures

        saved = save_p244_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p2_44", None)


def _generate_p1122a(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.122(a) fixtures (IRB borrower + null-PD corporate guarantor SA-fallback)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_122a import save_p1122a_fixtures

        data_dir = output_dir / "data"
        saved = save_p1122a_fixtures(data_dir)
        return [
            (f"data/{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()
        ]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_122a", None)


def _generate_p1122b(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.122(b) fixtures (IRB borrower + unrated SCRA-B institution guarantor)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_122b import save_p1122b_fixtures

        data_dir = output_dir / "data"
        saved = save_p1122b_fixtures(data_dir)
        return [
            (f"data/{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()
        ]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_122b", None)


def _generate_pse_rgla_guarantor(output_dir: Path) -> list[tuple[str, int]]:
    """Generate PSE/RGLA-guarantor fixtures (IRB borrower + PSE/RGLA SA guarantors)."""
    sys.path.insert(0, str(output_dir))
    try:
        from pse_rgla_guarantor import save_pse_rgla_guarantor_fixtures

        data_dir = output_dir / "data"
        saved = save_pse_rgla_guarantor_fixtures(data_dir)
        return [
            (f"data/{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()
        ]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("pse_rgla_guarantor", None)


def _generate_p236(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P2.36 fixtures (sovereign/institution PD floor first-class config fields)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p2_36 import save_p236_fixtures

        saved = save_p236_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p2_36", None)


def _generate_p233(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P2.33 / B31-D.CCF9 fixtures (UK residential-mortgage commitment 50% CCF)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p2_33 import save_p233_fixtures

        saved = save_p233_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p2_33", None)


def _generate_p232(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P2.32 / B31-D.CCF10 fixtures (purchased-receivables undrawn-commitment CCF)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p2_32 import save_p232_fixtures

        saved = save_p232_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p2_32", None)


def _generate_ccr_golden(output_dir: Path) -> list[tuple[str, int]]:
    """Generate CCR golden fixtures: CCR-A1 (IR swap), CCR-A3 (credit CDS),
    CCR-A7 (oil forward), CCR-A8 (electricity swap), CCR-A9 (multi-bucket
    commodity netting set — OIL_GAS + METALS + ELECTRICITY).

    All golden scenarios are written to the same ``ccr/`` output directory.
    golden_ccr_a* modules use relative imports (from .margin_builder etc.),
    so they are loaded as part of the 'ccr' package.  Insert the fixtures
    root (parent of ccr/) so that 'from ccr.golden_ccr_a* import …' resolves
    the sibling builders correctly.
    """
    fixtures_root = str(output_dir.parent)
    sys.path.insert(0, fixtures_root)
    try:
        from ccr.golden_ccr_a1 import save_golden_fixtures
        from ccr.golden_ccr_a3 import save_ccr_a3_fixtures
        from ccr.golden_ccr_a7 import save_ccr_a7_fixtures
        from ccr.golden_ccr_a8 import save_ccr_a8_fixtures
        from ccr.golden_ccr_a9 import save_ccr_a9_fixtures

        results: list[tuple[str, int]] = []

        # CCR-A1: writes canonical trades/netting_sets/margin_agreements/ccr_collateral parquets.
        saved_a1 = save_golden_fixtures(output_dir)
        results.extend(
            (f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved_a1.items()
        )

        # CCR-A3: writes ccr_a3_* parquets.
        saved_a3 = save_ccr_a3_fixtures(output_dir)
        results.extend(
            (f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved_a3.items()
        )

        # CCR-A7: writes ccr_a7_* parquets (oil forward).
        saved_a7 = save_ccr_a7_fixtures(output_dir)
        results.extend(
            (f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved_a7.items()
        )

        # CCR-A8: writes ccr_a8_* parquets (electricity swap).
        saved_a8 = save_ccr_a8_fixtures(output_dir)
        results.extend(
            (f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved_a8.items()
        )

        # CCR-A9: writes ccr_a9_* parquets (multi-bucket commodity, cross-bucket sqrt aggregation).
        saved_a9 = save_ccr_a9_fixtures(output_dir)
        results.extend(
            (f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved_a9.items()
        )

        return results
    finally:
        sys.path.remove(fixtures_root)
        for mod in (
            CCR_GOLDEN_A1_MODULE,
            "ccr.golden_ccr_a3",
            "ccr.golden_ccr_a7",
            "ccr.golden_ccr_a8",
            "ccr.golden_ccr_a9",
            CCR_TRADE_BUILDER_MODULE,
            CCR_NETTING_SET_BUILDER_MODULE,
            CCR_MARGIN_BUILDER_MODULE,
        ):
            sys.modules.pop(mod, None)


def _generate_p814_margined(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P8.14 margined MF fixtures (Art. 279c(2) + Art. 285 MPOR cascade)."""
    # margined_mf_builder uses relative imports from the ccr package, so load it
    # as part of the 'ccr' package — same pattern as _generate_ccr_golden.
    fixtures_root = str(output_dir.parent)
    import sys

    sys.path.insert(0, fixtures_root)
    try:
        from ccr.margined_mf_builder import save_margined_mf_fixtures

        saved = save_margined_mf_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(fixtures_root)
        for mod in (
            "ccr.margined_mf_builder",
            CCR_TRADE_BUILDER_MODULE,
            CCR_NETTING_SET_BUILDER_MODULE,
            CCR_MARGIN_BUILDER_MODULE,
        ):
            sys.modules.pop(mod, None)


def _generate_p815(output_dir: Path) -> list[tuple[str, int]]:
    """
    Validate P8.15 builder (Python-only — no persistent parquet output).

    P8.15 exercises IR hedging-set partition (Art. 277) and the intra-asset-class
    add-on aggregation formula (Art. 277a/280a) with two GBP IR swaps in netting
    set NS-IR-01: T1 (10y, GT_5Y bucket, delta=+1) and T2 (3y, 1Y_5Y bucket,
    delta=-1).  The builder is Python-only; test-writer imports the LazyFrame
    factories directly rather than reading parquet.
    """
    fixtures_root = str(output_dir.parent)
    import sys

    sys.path.insert(0, fixtures_root)
    try:
        from ccr.hedging_sets_ir_builder import save_p815_fixtures

        return save_p815_fixtures()
    finally:
        sys.path.remove(fixtures_root)
        for mod in (
            "ccr.hedging_sets_ir_builder",
            CCR_TRADE_BUILDER_MODULE,
            CCR_NETTING_SET_BUILDER_MODULE,
            CCR_MARGIN_BUILDER_MODULE,
        ):
            sys.modules.pop(mod, None)


def _generate_p818(output_dir: Path) -> list[tuple[str, int]]:
    """
    Validate P8.18 builder imports (Python-only builder — no persistent parquet output).

    P8.18 tests the legal-enforceability gate (CRR Art. 272(4) second subparagraph):
    when a netting set has ``is_legally_enforceable=False``, each trade must be
    expanded into its own single-trade synthetic netting set.  The fixture is a
    Python-only builder that constructs in-memory DataFrames typed against the
    canonical TRADE_SCHEMA / NETTING_SET_SCHEMA from schemas.py.

    This function smoke-checks the import, constructs the four frames, and
    verifies the critical invariants the test-writer will assert.
    """
    # p8_18_non_enforceable uses relative imports, so load it as part of the
    # 'ccr' package from the fixtures root (parent of ccr/).
    fixtures_root = str(output_dir.parent)
    sys.path.insert(0, fixtures_root)
    try:
        from ccr.p8_18_non_enforceable import (  # noqa: PLC0415
            NS_Q1_ID,
            NS_Q1_IS_LEGALLY_ENFORCEABLE,
            SPLIT_NS_ID_T_A,
            SPLIT_NS_ID_T_B,
            T_A_ID,
            T_B_ID,
            make_p818_frames,
        )

        frames = make_p818_frames()

        # Invariant 1: trades DataFrame has exactly 2 rows with the correct trade IDs.
        trades_df = frames["trades"]
        if trades_df.height != 2:
            raise AssertionError(f"P8.18: trades must have 2 rows (got {trades_df.height})")
        trade_ids = set(trades_df["trade_id"].to_list())
        if trade_ids != {T_A_ID, T_B_ID}:
            raise AssertionError(f"P8.18: expected trade_ids {{T_A, T_B}}, got {trade_ids}")

        # Invariant 2: netting_sets DataFrame has exactly 1 row with NS_Q1.
        ns_df = frames["netting_sets"]
        if ns_df.height != 1:
            raise AssertionError(f"P8.18: netting_sets must have 1 row (got {ns_df.height})")
        if ns_df["netting_set_id"][0] != NS_Q1_ID:
            raise AssertionError(
                f"P8.18: netting_set_id must be {NS_Q1_ID!r} (got {ns_df['netting_set_id'][0]!r})"
            )

        # Invariant 3: is_legally_enforceable must be False on NS_Q1.
        if ns_df["is_legally_enforceable"][0] is not False:
            raise AssertionError(
                "P8.18: NS_Q1.is_legally_enforceable must be False (Art. 272(4) gate trigger)"
            )
        if NS_Q1_IS_LEGALLY_ENFORCEABLE is not False:
            raise AssertionError(
                "P8.18: module constant NS_Q1_IS_LEGALLY_ENFORCEABLE must be False"
            )

        # Invariant 4: both trades belong to NS_Q1.
        ns_ids_on_trades = set(trades_df["netting_set_id"].to_list())
        if ns_ids_on_trades != {NS_Q1_ID}:
            raise AssertionError(
                f"P8.18: all trades must belong to {NS_Q1_ID!r} (got {ns_ids_on_trades})"
            )

        # Invariant 5: expected synthetic split IDs are formed correctly.
        expected_t_a = f"{NS_Q1_ID}__split__{T_A_ID}"
        expected_t_b = f"{NS_Q1_ID}__split__{T_B_ID}"
        if expected_t_a != SPLIT_NS_ID_T_A:
            raise AssertionError(
                f"P8.18: SPLIT_NS_ID_T_A must be {expected_t_a!r} (got {SPLIT_NS_ID_T_A!r})"
            )
        if expected_t_b != SPLIT_NS_ID_T_B:
            raise AssertionError(
                f"P8.18: SPLIT_NS_ID_T_B must be {expected_t_b!r} (got {SPLIT_NS_ID_T_B!r})"
            )

        # Invariant 6: margin_agreements is empty (unmargined scenario).
        if frames["margin_agreements"].height != 0:
            raise AssertionError("P8.18: margin_agreements must be empty (unmargined scenario)")

        # Invariant 7: ccr_collateral is empty (no posted/received collateral).
        if frames["ccr_collateral"].height != 0:
            raise AssertionError("P8.18: ccr_collateral must be empty (no collateral)")

        # No parquet files written — report zero files, zero records.
        return [(PYTHON_ONLY_NO_PARQUET, 0)]
    finally:
        sys.path.remove(fixtures_root)
        for mod in (
            "ccr.p8_18_non_enforceable",
            CCR_TRADE_BUILDER_MODULE,
            CCR_NETTING_SET_BUILDER_MODULE,
            CCR_MARGIN_BUILDER_MODULE,
        ):
            sys.modules.pop(mod, None)


def _generate_p816(output_dir: Path) -> list[tuple[str, int]]:
    """
    Validate P8.16 builder imports (Python-only builder — no persistent parquet output).

    P8.16 tests the SA-CCR PFE multiplier formula (CRR Art. 278(3)):
        multiplier = min(1, F + (1 − F) × exp((V − C) / (2 × (1 − F) × AddOn_aggregate)))

    Two scenarios are smoke-checked:
        Scenario A (NS-CCR-A2-01): v_net=-2_000_000, c_net=+500_000 → multiplier ≈ 0.853 < 1.
        Scenario B (NS-CCR-A2-02): v_net=+3_000_000, c_net=+500_000 → multiplier = 1.0 (capped).

    The builder is Python-only; test-writer imports the LazyFrame factories directly.
    """
    fixtures_root = str(output_dir.parent)
    sys.path.insert(0, fixtures_root)
    try:
        from ccr.pfe_multiplier_builder import save_pfe_multiplier_fixtures

        return save_pfe_multiplier_fixtures()
    finally:
        sys.path.remove(fixtures_root)
        for mod in (
            "ccr.pfe_multiplier_builder",
            CCR_NETTING_SET_BUILDER_MODULE,
        ):
            sys.modules.pop(mod, None)


def _generate_p824(output_dir: Path) -> list[tuple[str, int]]:
    """
    Validate P8.24 builder imports (Python-only builder — no persistent parquet output).

    P8.24 tests failed-trade settlement risk: four DvP rows exercising each
    Art. 378 Table 1 multiplier band (t+5, t+20, t+35, t+50) and one non-DvP
    Col-4 row exercising the Art. 379(1) Table 2 Column-4 1250% risk weight.

    The fixture is a Python-only builder that constructs an in-memory LazyFrame
    typed against the canonical ``FAILED_TRADE_SCHEMA`` from schemas.py.
    """
    fixtures_root = str(output_dir.parent)
    sys.path.insert(0, fixtures_root)
    try:
        from ccr.failed_trade_builder import (  # noqa: PLC0415
            COUNTERPARTY_REF,
            FT001_BAND,
            FT001_DAYS,
            FT001_ID,
            FT001_MULTIPLIER,
            FT001_OWN_FUNDS,
            FT001_PRICE_DIFF,
            FT001_RWA,
            FT002_BAND,
            FT002_ID,
            FT002_OWN_FUNDS,
            FT002_RWA,
            FT003_BAND,
            FT003_ID,
            FT003_OWN_FUNDS,
            FT003_RWA,
            FT004_BAND,
            FT004_ID,
            FT004_OWN_FUNDS,
            FT004_RWA,
            FT005_BAND,
            FT005_EXPOSURE,
            FT005_ID,
            FT005_OWN_FUNDS,
            FT005_RWA,
            PORTFOLIO_TOTAL_RWA,
            make_failed_trades_frame,
        )

        # Smoke-check: frame must construct without raising.
        lf = make_failed_trades_frame()
        df = lf.collect()

        # Invariant 1: exactly 5 rows.
        if df.height != 5:
            raise AssertionError(f"P8.24: frame must have 5 rows (got {df.height})")

        # Invariant 2: all five trade IDs present.
        ids = set(df["failed_trade_id"].to_list())
        expected_ids = {FT001_ID, FT002_ID, FT003_ID, FT004_ID, FT005_ID}
        if ids != expected_ids:
            raise AssertionError(f"P8.24: expected trade IDs {expected_ids}, got {ids}")

        # Invariant 3: all rows share a single counterparty reference.
        cp_refs = set(df["counterparty_reference"].to_list())
        if cp_refs != {COUNTERPARTY_REF}:
            raise AssertionError(
                f"P8.24: all rows must reference {COUNTERPARTY_REF!r} (got {cp_refs})"
            )

        # Invariant 4: settlement_type distribution (4 dvp, 1 non_dvp_free_delivery).
        type_counts = df["settlement_type"].value_counts().to_dicts()
        type_map = {r["settlement_type"]: r["count"] for r in type_counts}
        if type_map.get("dvp") != 4:
            raise AssertionError(f"P8.24: expected 4 dvp rows (got {type_map.get('dvp')})")
        if type_map.get("non_dvp_free_delivery") != 1:
            raise AssertionError(
                f"P8.24: expected 1 non_dvp_free_delivery row "
                f"(got {type_map.get('non_dvp_free_delivery')})"
            )

        # Invariant 5: DvP rows have null value_transferred and
        # current_positive_exposure; non-null agreed_settlement_price / mv.
        dvp_df = df.filter(pl.col("settlement_type") == "dvp")
        if dvp_df["value_transferred"].null_count() != 4:
            raise AssertionError("P8.24: DvP rows must have null value_transferred")
        if dvp_df["current_positive_exposure"].null_count() != 4:
            raise AssertionError("P8.24: DvP rows must have null current_positive_exposure")
        if dvp_df["agreed_settlement_price"].null_count() != 0:
            raise AssertionError("P8.24: DvP rows must have non-null agreed_settlement_price")
        if dvp_df["current_market_value"].null_count() != 0:
            raise AssertionError("P8.24: DvP rows must have non-null current_market_value")

        # Invariant 6: non-DvP row has null agreed_settlement_price / mv;
        # non-null value_transferred and current_positive_exposure.
        ndvp_df = df.filter(pl.col("settlement_type") == "non_dvp_free_delivery")
        if ndvp_df["agreed_settlement_price"].null_count() != 1:
            raise AssertionError("P8.24: non-DvP row must have null agreed_settlement_price")
        if ndvp_df["current_market_value"].null_count() != 1:
            raise AssertionError("P8.24: non-DvP row must have null current_market_value")
        if ndvp_df["value_transferred"].null_count() != 0:
            raise AssertionError("P8.24: non-DvP row must have non-null value_transferred")
        if ndvp_df["current_positive_exposure"].null_count() != 0:
            raise AssertionError("P8.24: non-DvP row must have non-null current_positive_exposure")

        # Invariant 7: FT001 scalar assertions (spot-check band constants).
        ft001 = df.filter(pl.col("failed_trade_id") == FT001_ID)
        if ft001["working_days_past_due"][0] != FT001_DAYS:
            raise AssertionError(
                f"P8.24: FT001 days must be {FT001_DAYS} (got {ft001['working_days_past_due'][0]})"
            )

        # Invariant 8: all optional boolean flags default False.
        for col in (
            "is_repo_or_sec_lending",
            "is_immaterial",
            "elect_cet1_deduction",
            "system_wide_failure_waiver",
        ):
            if col not in df.columns:
                raise AssertionError(f"P8.24: column {col!r} must be present")
            if df[col].sum() != 0:
                raise AssertionError(f"P8.24: all rows must have {col}=False")

        # Invariant 9: hand-calc spot-check — FT001 own-funds and RWA constants.
        # (price_diff × multiplier = own_funds; own_funds × 12.5 = rwa)
        if abs(FT001_PRICE_DIFF * FT001_MULTIPLIER - FT001_OWN_FUNDS) > 0.01:
            raise AssertionError(
                f"P8.24: FT001 own_funds hand-calc mismatch: "
                f"{FT001_PRICE_DIFF} × {FT001_MULTIPLIER} != {FT001_OWN_FUNDS}"
            )
        if abs(FT001_OWN_FUNDS * 12.5 - FT001_RWA) > 0.01:
            raise AssertionError(
                f"P8.24: FT001 RWA hand-calc mismatch: {FT001_OWN_FUNDS} × 12.5 != {FT001_RWA}"
            )

        # Invariant 10: portfolio total RWA constant matches sum of per-row RWAs.
        row_rwa_sum = FT001_RWA + FT002_RWA + FT003_RWA + FT004_RWA + FT005_RWA
        if abs(row_rwa_sum - PORTFOLIO_TOTAL_RWA) > 0.01:
            raise AssertionError(
                f"P8.24: PORTFOLIO_TOTAL_RWA {PORTFOLIO_TOTAL_RWA} != "
                f"sum of per-row RWAs {row_rwa_sum}"
            )

        # Invariant 11: FT005 exposure constant (value_transferred + cpe).
        ft005_row = ndvp_df
        vt = ft005_row["value_transferred"][0]
        cpe = ft005_row["current_positive_exposure"][0]
        if abs((vt + cpe) - FT005_EXPOSURE) > 0.01:
            raise AssertionError(
                f"P8.24: FT005 exposure mismatch: {vt} + {cpe} != {FT005_EXPOSURE}"
            )

        # Invariant 12: band string constants are correct.
        expected_bands = {
            FT001_ID: FT001_BAND,
            FT002_ID: FT002_BAND,
            FT003_ID: FT003_BAND,
            FT004_ID: FT004_BAND,
            FT005_ID: FT005_BAND,
        }
        for trade_id, expected_band in expected_bands.items():
            # Band is a module-level constant, not a column in the input frame.
            # Check a representative one to confirm correct naming.
            if not isinstance(expected_band, str) or not expected_band:
                raise AssertionError(
                    f"P8.24: band constant for {trade_id!r} must be a non-empty string"
                )

        # Invariant 13: own-funds and RWA constants for remaining rows (spot-check).
        for trade_id, of, rwa in [
            (FT002_ID, FT002_OWN_FUNDS, FT002_RWA),
            (FT003_ID, FT003_OWN_FUNDS, FT003_RWA),
            (FT004_ID, FT004_OWN_FUNDS, FT004_RWA),
            (FT005_ID, FT005_OWN_FUNDS, FT005_RWA),
        ]:
            if abs(of * 12.5 - rwa) > 0.01:
                raise AssertionError(
                    f"P8.24: {trade_id} RWA hand-calc mismatch: {of} × 12.5 != {rwa}"
                )

        # No parquet files written — report zero files, zero records.
        return [(PYTHON_ONLY_NO_PARQUET, 0)]
    finally:
        sys.path.remove(fixtures_root)
        for mod in ("ccr.failed_trade_builder",):
            sys.modules.pop(mod, None)


def _generate_p825(output_dir: Path) -> list[tuple[str, int]]:
    """
    Validate P8.25 builder imports (Python-only builder — no persistent parquet output).

    P8.25 tests the QCCP trade-exposure risk weight (CRR Art. 306/307): a single
    GBP IR derivative against LCH Ltd (CP-QCCP-LCH) produces the same EAD across
    three variants (CCR-B1a/b/c) but different risk weights depending on ``is_qccp``
    and ``is_client_cleared``.  The fixture is a Python-only builder; test-writer
    imports ``build_qccp_trade_fixture`` directly.

    This function smoke-checks all three variants and verifies the critical
    schema and data invariants the test-writer will assert.
    """
    fixtures_root = str(output_dir.parent)
    sys.path.insert(0, fixtures_root)
    try:
        from ccr.qccp_builder import (  # noqa: PLC0415
            QCCP_CP_REF,
            QCCP_EAD,
            QCCP_INSTITUTION_CQS,
            QCCP_NS_ID,
            QCCP_RW_CLIENT_CLEARED,
            QCCP_RW_PROPRIETARY,
            QCCP_RW_SA_FALLBACK,
            QCCP_TRADE_ID,
            build_qccp_trade_fixture,
        )

        b1a = build_qccp_trade_fixture(is_qccp=True, is_client_cleared=False)
        b1b = build_qccp_trade_fixture(is_qccp=True, is_client_cleared=True)
        b1c = build_qccp_trade_fixture(is_qccp=False, is_client_cleared=False)

        for label, fx in [("CCR-B1a", b1a), ("CCR-B1b", b1b), ("CCR-B1c", b1c)]:
            if fx.trades.height != 1:
                raise AssertionError(f"P8.25 {label}: trades must have 1 row")
            if fx.trades["trade_id"][0] != QCCP_TRADE_ID:
                raise AssertionError(f"P8.25 {label}: trade_id must be {QCCP_TRADE_ID!r}")

        for label, fx in [("CCR-B1a", b1a), ("CCR-B1b", b1b), ("CCR-B1c", b1c)]:
            if fx.netting_sets["netting_set_id"][0] != QCCP_NS_ID:
                raise AssertionError(f"P8.25 {label}: netting_set_id must be {QCCP_NS_ID!r}")
            if fx.counterparty["counterparty_reference"][0] != QCCP_CP_REF:
                raise AssertionError(
                    f"P8.25 {label}: counterparty_reference must be {QCCP_CP_REF!r}"
                )

        if "is_client_cleared" not in b1a.trades.columns:
            raise AssertionError("P8.25 CCR-B1a: is_client_cleared must be present on trades")
        if b1a.trades["is_client_cleared"][0] is not False:
            raise AssertionError("P8.25 CCR-B1a: is_client_cleared must be False")
        if b1b.trades["is_client_cleared"][0] is not True:
            raise AssertionError("P8.25 CCR-B1b: is_client_cleared must be True")
        if b1c.trades["is_client_cleared"][0] is not False:
            raise AssertionError("P8.25 CCR-B1c: is_client_cleared must be False")

        if "is_qccp" not in b1a.counterparty.columns:
            raise AssertionError("P8.25 CCR-B1a: is_qccp must be present on counterparty")
        if b1a.counterparty["is_qccp"][0] is not True:
            raise AssertionError("P8.25 CCR-B1a: is_qccp must be True")
        if b1b.counterparty["is_qccp"][0] is not True:
            raise AssertionError("P8.25 CCR-B1b: is_qccp must be True")
        if b1c.counterparty["is_qccp"][0] is not False:
            raise AssertionError("P8.25 CCR-B1c: is_qccp must be False")

        for label, fx in [("CCR-B1a", b1a), ("CCR-B1b", b1b), ("CCR-B1c", b1c)]:
            if fx.margin_agreements.height != 0:
                raise AssertionError(f"P8.25 {label}: margin_agreements must be empty")
            if fx.ccr_collateral.height != 0:
                raise AssertionError(f"P8.25 {label}: ccr_collateral must be empty")

        for label, fx in [("CCR-B1a", b1a), ("CCR-B1b", b1b), ("CCR-B1c", b1c)]:
            cqs = fx.counterparty["institution_cqs"][0]
            if cqs != QCCP_INSTITUTION_CQS:
                raise AssertionError(
                    f"P8.25 {label}: institution_cqs must be {QCCP_INSTITUTION_CQS} (got {cqs})"
                )

        if not (0 < QCCP_EAD < 100_000_000):
            raise AssertionError(f"P8.25: QCCP_EAD={QCCP_EAD} is outside plausible range")

        _ = (QCCP_RW_PROPRIETARY, QCCP_RW_CLIENT_CLEARED, QCCP_RW_SA_FALLBACK)

        return [(PYTHON_ONLY_NO_PARQUET, 0)]
    finally:
        sys.path.remove(fixtures_root)
        for mod in (
            "ccr.qccp_builder",
            CCR_TRADE_BUILDER_MODULE,
            CCR_NETTING_SET_BUILDER_MODULE,
            CCR_MARGIN_BUILDER_MODULE,
        ):
            sys.modules.pop(mod, None)


def _generate_p827(output_dir: Path) -> list[tuple[str, int]]:
    """
    Validate P8.27 builder (Python-only — no persistent parquet output).

    P8.27 exercises the specific-WWR identification gate (CRR Art. 291(4)-(5)):
    trade T_WWR_01 (equity derivative, underlying issued by counterparty CP_WWR_01)
    has ``is_specific_wwr=True`` and must be broken out into a synthetic netting
    set ``NS_WWR_01__wwr__T_WWR_01`` with ``wwr_lgd_override=1.0`` (Art. 291(5)(c)).
    Trade T_NORMAL_01 (IR derivative) remains in the residual NS_WWR_01.
    One CCR010 warning is emitted per original NS containing WWR trades; zero
    CCR011 (has_general_wwr_flag=False).  The builder is Python-only; test-writer
    imports the LazyFrame factories directly rather than reading parquet.
    """
    fixtures_root = str(output_dir.parent)
    sys.path.insert(0, fixtures_root)
    try:
        from ccr.wwr_builder import save_p827_fixtures

        return save_p827_fixtures()
    finally:
        sys.path.remove(fixtures_root)
        for mod in (
            "ccr.wwr_builder",
            CCR_TRADE_BUILDER_MODULE,
            CCR_NETTING_SET_BUILDER_MODULE,
            CCR_MARGIN_BUILDER_MODULE,
        ):
            sys.modules.pop(mod, None)


def _generate_ccr_wwr1(output_dir: Path) -> list[tuple[str, int]]:
    """
    Validate CCR-WWR-1 orchestrator-ready bundle (Python-only — no persistent parquet output).

    P8.53 / CCR-WWR-1 extends the P8.27 specific-WWR scenario with a full
    RawDataBundle that PipelineOrchestrator.run_with_data can consume end-to-end:
    counterparty CP_WWR_01 (institution, CQS 2) + external rating (S&P "A") +
    empty traditional-lending frames + RawCCRBundle assembled from the P8.27
    make_p827_* factories (2 trades, 1 NS, 0 margin agreements, 0 collateral).
    The builder is Python-only; test-writer imports build_raw_data_bundle_ccr_wwr1()
    directly rather than reading parquet.
    """
    fixtures_root = str(output_dir.parent)
    sys.path.insert(0, fixtures_root)
    try:
        from ccr.ccr_wwr1_builder import save_ccr_wwr1_fixtures

        return save_ccr_wwr1_fixtures()
    finally:
        sys.path.remove(fixtures_root)
        for mod in (
            "ccr.ccr_wwr1_builder",
            "ccr.wwr_builder",
            CCR_TRADE_BUILDER_MODULE,
            CCR_NETTING_SET_BUILDER_MODULE,
            CCR_MARGIN_BUILDER_MODULE,
        ):
            sys.modules.pop(mod, None)


def _generate_ccr_a5(output_dir: Path) -> list[tuple[str, int]]:
    """Generate CCR-A5 golden fixtures (single-name equity TRS, 1y, unmargined)."""
    # golden_ccr_a5 uses relative imports from the ccr package, so load it as
    # part of the 'ccr' package — same pattern as _generate_ccr_golden.
    fixtures_root = str(output_dir.parent)
    sys.path.insert(0, fixtures_root)
    try:
        from ccr.golden_ccr_a5 import save_ccr_a5_fixtures

        saved = save_ccr_a5_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(fixtures_root)
        for mod in (
            "ccr.golden_ccr_a5",
            CCR_GOLDEN_A1_MODULE,
            CCR_TRADE_BUILDER_MODULE,
            CCR_NETTING_SET_BUILDER_MODULE,
            CCR_MARGIN_BUILDER_MODULE,
        ):
            sys.modules.pop(mod, None)


def _generate_ccr_a10(output_dir: Path) -> list[tuple[str, int]]:
    """Generate CCR-A10 golden fixtures (mixed-asset-class netting set, 5 trades, unmargined)."""
    # golden_ccr_a10 uses relative imports from the ccr package, so load it as
    # part of the 'ccr' package — same pattern as _generate_ccr_golden.
    fixtures_root = str(output_dir.parent)
    sys.path.insert(0, fixtures_root)
    try:
        from ccr.golden_ccr_a10 import save_ccr_a10_fixtures

        saved = save_ccr_a10_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(fixtures_root)
        for mod in (
            "ccr.golden_ccr_a10",
            CCR_GOLDEN_A1_MODULE,
            "ccr.golden_ccr_a2",
            CCR_TRADE_BUILDER_MODULE,
            CCR_NETTING_SET_BUILDER_MODULE,
            CCR_MARGIN_BUILDER_MODULE,
        ):
            sys.modules.pop(mod, None)


def _generate_ccr_a11_a12(output_dir: Path) -> list[tuple[str, int]]:
    """Generate CCR-A11/A12 golden fixtures (SA-CCR SFT FCCM EAD branch, Art. 271(2)).

    CCR-A11: uncollateralised SFT — EAD = E·(1+HE).
    CCR-A12: cash-collateralised SFT — EAD = max(0, E·(1+HE) − CVA).
    Both: counterparty CP_INST_001 (institution, CQS 2, GB) → 50% SA RW.
    """
    fixtures_root = str(output_dir.parent)
    sys.path.insert(0, fixtures_root)
    try:
        from ccr.golden_ccr_a11_a12 import save_ccr_a11_a12_fixtures

        saved = save_ccr_a11_a12_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(fixtures_root)
        for mod in (
            "ccr.golden_ccr_a11_a12",
            CCR_TRADE_BUILDER_MODULE,
            CCR_NETTING_SET_BUILDER_MODULE,
            CCR_MARGIN_BUILDER_MODULE,
        ):
            sys.modules.pop(mod, None)


def _generate_p130e(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.30(e) fixtures (CRR Art. 234 mezzanine partial-protection tranching)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_30e import save_p130e_fixtures

        saved = save_p130e_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_30e", None)


def _generate_p515(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P5.15 fixtures (B31 Art. 123A(1)(b)(ii) 0.2% retail granularity sub-condition)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p5_15 import save_p515_fixtures

        saved = save_p515_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p5_15", None)


def _generate_p225(output_dir: Path) -> list[tuple[str, int]]:
    """Validate P2.25(b) fixture module (Python-only; no parquet artefacts).

    This fixture provides factory functions and constants for the CR5 RE
    loan-split sub-row bucketing (rows 9f/9g, not-materially-dependent, B3.1).
    The test drives ``Pillar3Generator._generate_cr5`` directly with a seeded
    two-row LazyFrame; no parquet is written.
    """
    sys.path.insert(0, str(output_dir))
    try:
        from p2_25 import build_re_split_results_lf

        lf = build_re_split_results_lf()
        df = lf.collect()
        return [("p2_25.py (Python-only)", df.height)]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p2_25", None)


def _generate_p229(output_dir: Path) -> list[tuple[str, int]]:
    """Validate P2.29 fixture module (Python-only; no parquet artefacts).

    This fixture provides factory functions and constants for the OV1
    equity sub-approach rows (11-14) and output-floor rows (26/27).
    The test drives ``Pillar3Generator.generate_from_lazyframe`` directly
    with a seeded LazyFrame + ``OutputFloorSummary``; no parquet is written.
    """
    sys.path.insert(0, str(output_dir))
    try:
        from p2_29 import build_equity_results_lf, build_output_floor_summary

        lf = build_equity_results_lf()
        df = lf.collect()
        _ = build_output_floor_summary()  # verifies construction
        return [("p2_29.py (Python-only)", df.height)]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p2_29", None)


def _generate_p1141(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.141 fixtures (B31 Art. 124(4) all-or-nothing qualifying gate — mixed RE)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_141 import save_p1141_fixtures

        saved = save_p1141_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_141", None)


def _generate_p230(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P2.30 fixtures (Annex I Row 3 vs Row 4 CCF discrimination — MR_ISSUED vs MR)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p2_30 import save_p230_fixtures

        saved = save_p230_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p2_30", None)


def _generate_p231(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P2.31 fixtures (Annex I obs_product -> risk_type fill, explicit-wins control)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p2_31 import save_p231_fixtures

        saved = save_p231_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p2_31", None)


def _generate_p249(output_dir: Path) -> list[tuple[str, int]]:
    """
    Validate P2.49 builder imports (no parquet output — Python-only builder).

    P2.49 extends the CR9 column-a exposure-class taxonomy from 4+6 leaves to
    5+10 leaves.  The seed frame is a LazyFrame built in-memory and passed
    directly to Pillar3Generator._generate_all_cr9; it is never written to
    parquet.  This function smoke-checks the import, verifies frame shape, and
    confirms the three new discriminator columns are present with correct types.
    """
    sys.path.insert(0, str(output_dir))
    try:
        from p2_49 import (  # noqa: F401
            EXPECTED_AIRB_CLASS_COUNT,
            EXPECTED_FIRB_CLASS_COUNT,
            EXPECTED_KEYS,
            build_cr9_irb_results_lf,
        )

        lf = build_cr9_irb_results_lf()
        df = lf.collect()

        # Invariant 1: 15 rows — one per leaf class (5 F-IRB + 10 A-IRB)
        if df.height != 15:
            raise AssertionError(f"Expected 15 rows, got {df.height}")

        # Invariant 2: three new discriminator columns must be present
        for col_name in ("is_sme", "property_type", "cp_is_financial_sector_entity"):
            if col_name not in df.columns:
                raise AssertionError(f"Column {col_name!r} must be present")

        # Invariant 3: is_sme and cp_is_financial_sector_entity are Boolean
        schema = df.schema
        if schema["is_sme"] != pl.Boolean:
            raise AssertionError(f"is_sme must be Boolean, got {schema['is_sme']}")
        if schema["cp_is_financial_sector_entity"] != pl.Boolean:
            raise AssertionError(
                f"cp_is_financial_sector_entity must be Boolean, "
                f"got {schema['cp_is_financial_sector_entity']}"
            )

        # Invariant 4: expected leaf counts match scenario constants
        if EXPECTED_FIRB_CLASS_COUNT != 5:
            raise AssertionError(
                f"EXPECTED_FIRB_CLASS_COUNT must be 5, got {EXPECTED_FIRB_CLASS_COUNT}"
            )
        if EXPECTED_AIRB_CLASS_COUNT != 10:
            raise AssertionError(
                f"EXPECTED_AIRB_CLASS_COUNT must be 10, got {EXPECTED_AIRB_CLASS_COUNT}"
            )
        if len(EXPECTED_KEYS) != 15:
            raise AssertionError(f"EXPECTED_KEYS must have 15 entries, got {len(EXPECTED_KEYS)}")

        # No parquet files written — report zero files, zero records.
        return [(PYTHON_ONLY_NO_PARQUET, 0)]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p2_49", None)


def _generate_p247(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P2.47 fixtures (Basel 3.1 Art. 137 ECA MEIP score 2 → 20% sovereign RW)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p2_47 import save_p247_fixtures

        saved = save_p247_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p2_47", None)


def _generate_p241(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P2.41 fixtures (COREP C 02.00 corporate sub-row 0295/0296/0297 split)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p2_41 import save_p241_fixtures

        saved = save_p241_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p2_41", None)


def _generate_p238(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P2.38 fixtures (CRR Art. 155(2) non-trading-book short-position netting)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p2_38 import save_p238_fixtures

        saved = save_p238_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p2_38", None)


def _generate_p246(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P2.46 fixtures (Art. 150(1) PPU provenance ppu_reason — C 07.00 rows 0050/0060)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p2_46 import save_p246_fixtures

        saved = save_p246_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p2_46", None)


def _generate_p248(output_dir: Path) -> list[tuple[str, int]]:
    """Validate P2.48 fixture module (Python-only; no parquet artefacts).

    This fixture provides factory functions and constants for the CR8 RWEA-flow
    statement two-period snapshot scenario.  The test drives
    ``Pillar3Generator.generate_from_lazyframe`` with a seeded current-period
    LazyFrame plus an optional ``previous_period_results`` LazyFrame; no parquet
    is written.
    """
    sys.path.insert(0, str(output_dir))
    try:
        from p2_48 import build_current_period_lf, build_prior_period_lf

        prior_df = build_prior_period_lf().collect()
        current_df = build_current_period_lf().collect()
        # Report combined row count (3 prior + 3 current)
        return [("p2_48.py (Python-only)", prior_df.height + current_df.height)]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p2_48", None)


def _generate_p1191(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.191 fixtures (QRRE per-individual aggregate nominal test)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_191 import save_p1191_fixtures

        saved = save_p1191_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_191", None)


def _generate_p420(output_dir: Path) -> list[tuple[str, int]]:
    """Validate P4.20 fixture module (Python-only; no parquet artefacts).

    P4.20 provides the grade-path IRB results LazyFrame for C 08.02 testing.
    The frame carries ``cp_internal_rating_grade`` so the generator groups by
    grade label rather than fixed PD-band labels.  Three corporate exposures
    cover grades AAA / BB / D.  The load-bearing property (E1 PD 0.01 and
    E2 PD 0.02 both fall in the same fixed PD bucket "0.75% - 2.50%") is
    verified by the module self-check; this function confirms the import and
    row count only.  No parquet files are written.
    """
    sys.path.insert(0, str(output_dir))
    try:
        from p4_20 import build_grade_path_irb_results_lf  # noqa: F401

        df = build_grade_path_irb_results_lf().collect()
        if df.height != 3:
            raise AssertionError(f"Expected 3 rows, got {df.height}")
        if "cp_internal_rating_grade" not in df.columns:
            raise AssertionError("Column 'cp_internal_rating_grade' must be present")
        grades = set(df["cp_internal_rating_grade"].to_list())
        expected = {"AAA", "BB", "D"}
        if grades != expected:
            raise AssertionError(f"Expected grades {expected}, got {grades}")
        return [("p4_20.py (Python-only)", df.height)]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p4_20", None)


def _generate_p1193(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.193 fixtures (B31 Art. 122(2) Table 6 rated corporate-SME CQS gate)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_193 import save_p1193_fixtures

        saved = save_p1193_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_193", None)


def _generate_p1197(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.197 fixtures (CRR-E.CCF1 slotting OBS EAD Art. 166(8)(d) F-IRB CCF 75%)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_197 import save_p1197_fixtures

        saved = save_p1197_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_197", None)


def _generate_p1196(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.196 fixtures (CRR-SA-SME-CQS1: rated corporate-SME Art. 122 CQS-gate)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_196 import save_p1196_fixtures

        saved = save_p1196_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_196", None)


def _generate_p1200(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.200 fixtures (B31 Art. 239(3) guarantee/CDS maturity-mismatch scaling)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_200 import save_p1200_fixtures

        saved = save_p1200_fixtures(output_dir / "data")
        return [
            (f"data/{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()
        ]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_200", None)


def _generate_p828_alpha(output_dir: Path) -> list[tuple[str, int]]:
    """
    Validate P8.28 α=1.0 carve-out bundles (Python-only — no persistent parquet output).

    P8.28 / CCR-ALPHA-1, CCR-ALPHA-2, CCR-ALPHA-3 provide orchestrator-ready
    RawDataBundles proving that applying per-counterparty α (1.0 for
    non_financial/pension_scheme, 1.4 for financial) produces the correct EAD.
    The supplementary 2-counterparty book regression-guards the keyed-join
    in the counterparty→NS alpha lookup against cross-join fan-out.
    """
    fixtures_root = str(output_dir.parent)
    sys.path.insert(0, fixtures_root)
    try:
        from ccr.p828_alpha_builder import save_p828_fixtures

        return save_p828_fixtures()
    finally:
        sys.path.remove(fixtures_root)
        for mod in (
            "ccr.p828_alpha_builder",
            CCR_GOLDEN_A1_MODULE,
            CCR_TRADE_BUILDER_MODULE,
            CCR_NETTING_SET_BUILDER_MODULE,
            CCR_MARGIN_BUILDER_MODULE,
        ):
            sys.modules.pop(mod, None)


def _generate_p829_addon(output_dir: Path) -> list[tuple[str, int]]:
    """
    Validate P8.29 transitional alpha add-on bundles (Python-only — no persistent parquet output).

    P8.29 / CCR-ALPHA-ADDON-1..4 provide orchestrator-ready RawDataBundles proving
    that the transitional alpha add-on (PRA PS1/26 Art. 274(2A)) fires correctly for
    legacy CVA-exempt non-financial counterparties under Basel 3.1, phases over
    2027/28/29, and is suppressed for non-legacy, financial, or CRR-framework scenarios.
    The supplementary 2-NS book regression-guards the per-trade→per-NS
    any(is_legacy_cva_exempt) collapse against cross-join fan-out.
    """
    fixtures_root = str(output_dir.parent)
    sys.path.insert(0, fixtures_root)
    try:
        from ccr.p829_addon_builder import save_p829_fixtures

        return save_p829_fixtures()
    finally:
        sys.path.remove(fixtures_root)
        for mod in (
            "ccr.p829_addon_builder",
            CCR_GOLDEN_A1_MODULE,
            CCR_TRADE_BUILDER_MODULE,
            CCR_NETTING_SET_BUILDER_MODULE,
            CCR_MARGIN_BUILDER_MODULE,
        ):
            sys.modules.pop(mod, None)


def _generate_p823_ls(output_dir: Path) -> list[tuple[str, int]]:
    """
    Validate P8.23 long-settlement no-op regression-pin bundles (Python-only).

    P8.23 / CCR-LS-1 and CCR-LS-1-CTRL provide two orchestrator-ready
    RawDataBundles that are economically identical except for the
    ``is_long_settlement`` flag.  The smoke-check verifies structural
    invariants and the parity property (all trade fields identical except
    trade_id, netting_set_id, is_long_settlement) so that the acceptance
    test can rely on EAD(LS=True) == EAD(LS=False) by construction.

    Regulatory basis: CRR Art. 271 / 272(2) / 279c(1) / 285 — the flag
    is inert under SA-CCR (no bespoke MPOR floor for long-settlement).
    """
    fixtures_root = str(output_dir.parent)
    sys.path.insert(0, fixtures_root)
    try:
        from ccr.p823_ls_builder import save_p823_fixtures

        return save_p823_fixtures()
    finally:
        sys.path.remove(fixtures_root)
        for mod in (
            "ccr.p823_ls_builder",
            CCR_GOLDEN_A1_MODULE,
            CCR_TRADE_BUILDER_MODULE,
            CCR_NETTING_SET_BUILDER_MODULE,
            CCR_MARGIN_BUILDER_MODULE,
        ):
            sys.modules.pop(mod, None)


def _generate_ccr_irb1(output_dir: Path) -> list[tuple[str, int]]:
    """
    Generate P8.31 / CCR-IRB-1 fixture parquet files and smoke-check the bundle.

    Writes four parquet files to the ``ccr/`` output directory:
        ccr_irb1_trades.parquet           — 1 row (T_IRB_001, 5y GBP IR swap)
        ccr_irb1_netting_sets.parquet     — 1 row (NS_IRB_001, CP_IRB_001)
        ccr_irb1_margin_agreements.parquet — 0 rows
        ccr_irb1_ccr_collateral.parquet   — 0 rows

    The model permission row (MOD_CORP_FIRB) is added to the shared
    model_permissions.parquet by the Model Permissions generator — it is
    NOT written by this function.

    Structural invariants for the CCR-IRB-1 scenario are validated by
    ``save_ccr_irb1_smoke_check()`` before the parquet files are returned.
    """
    fixtures_root = str(output_dir.parent)
    sys.path.insert(0, fixtures_root)
    try:
        from ccr.golden_ccr_irb1 import save_ccr_irb1_smoke_check

        return save_ccr_irb1_smoke_check()
    finally:
        sys.path.remove(fixtures_root)
        for mod in (
            "ccr.golden_ccr_irb1",
            CCR_TRADE_BUILDER_MODULE,
            CCR_NETTING_SET_BUILDER_MODULE,
            CCR_MARGIN_BUILDER_MODULE,
        ):
            sys.modules.pop(mod, None)


def _generate_p843(output_dir: Path) -> list[tuple[str, int]]:
    """
    Validate P8.43 builder imports (Python-only builder — no persistent parquet output).

    P8.43 tests three independent DvP failed-trade scenarios (CCR-C1 / C2 / C3),
    each placed in a distinct Art. 378 Table 1 multiplier band:

        CCR-C1: FT_C1, t+6,  dvp_5_15    (8%),  own_funds=8,000,    RWA=100,000
        CCR-C2: FT_C2, t+35, dvp_31_45   (75%), own_funds=600,000,  RWA=7,500,000
        CCR-C3: FT_C3, t+46, dvp_46_plus (100%), own_funds=500,000,  RWA=6,250,000

    Portfolio total RWA = 13,850,000.

    Each row carries a distinct counterparty reference (CP_FT_C1 / C2 / C3).
    The fixture is a Python-only builder; test-writer imports constants and
    ``make_c_failed_trades_frame()`` / ``make_minimal_counterparties_frame()`` directly.

    Regulatory basis: CRR Art. 378 + Table 1 (DvP multiplier ladder).
    """
    fixtures_root = str(output_dir.parent)
    sys.path.insert(0, fixtures_root)
    try:
        from ccr.p843_failed_trade_builder import (  # noqa: PLC0415
            FT_C1_BAND,
            FT_C1_DAYS,
            FT_C1_ID,
            FT_C1_MULTIPLIER,
            FT_C1_OWN_FUNDS,
            FT_C1_PRICE_DIFF,
            FT_C1_RWA,
            FT_C2_BAND,
            FT_C2_ID,
            FT_C2_OWN_FUNDS,
            FT_C2_RWA,
            FT_C3_BAND,
            FT_C3_ID,
            FT_C3_OWN_FUNDS,
            FT_C3_RWA,
            PORTFOLIO_TOTAL_RWA,
            make_c_failed_trades_frame,
            make_minimal_counterparties_frame,
        )

        # Smoke-check: frame must construct without raising.
        lf = make_c_failed_trades_frame()
        df = lf.collect()

        # Invariant 1: exactly 3 rows.
        if df.height != 3:
            raise AssertionError(f"P8.43: frame must have 3 rows (got {df.height})")

        # Invariant 2: all three trade IDs present.
        ids = set(df["failed_trade_id"].to_list())
        expected_ids = {FT_C1_ID, FT_C2_ID, FT_C3_ID}
        if ids != expected_ids:
            raise AssertionError(f"P8.43: expected trade IDs {expected_ids}, got {ids}")

        # Invariant 3: all rows are dvp settlement type.
        if df["settlement_type"].n_unique() != 1 or df["settlement_type"][0] != "dvp":
            raise AssertionError("P8.43: all rows must have settlement_type='dvp'")

        # Invariant 4: each row has a distinct counterparty reference.
        cp_refs = set(df["counterparty_reference"].to_list())
        if len(cp_refs) != 3:
            raise AssertionError(
                f"P8.43: expected 3 distinct counterparty references, got {cp_refs}"
            )

        # Invariant 5: DvP rows have null value_transferred and current_positive_exposure.
        if df["value_transferred"].null_count() != 3:
            raise AssertionError("P8.43: DvP rows must have null value_transferred")
        if df["current_positive_exposure"].null_count() != 3:
            raise AssertionError("P8.43: DvP rows must have null current_positive_exposure")
        if df["agreed_settlement_price"].null_count() != 0:
            raise AssertionError("P8.43: DvP rows must have non-null agreed_settlement_price")
        if df["current_market_value"].null_count() != 0:
            raise AssertionError("P8.43: DvP rows must have non-null current_market_value")

        # Invariant 6: FT_C1 day count and band constant.
        ft_c1 = df.filter(pl.col("failed_trade_id") == FT_C1_ID)
        if ft_c1["working_days_past_due"][0] != FT_C1_DAYS:
            raise AssertionError(
                f"P8.43: FT_C1 days must be {FT_C1_DAYS} "
                f"(got {ft_c1['working_days_past_due'][0]})"
            )

        # Invariant 7: all optional boolean flags default False.
        for col in (
            "is_repo_or_sec_lending",
            "is_immaterial",
            "elect_cet1_deduction",
            "system_wide_failure_waiver",
        ):
            if col not in df.columns:
                raise AssertionError(f"P8.43: column {col!r} must be present")
            if df[col].sum() != 0:
                raise AssertionError(f"P8.43: all rows must have {col}=False")

        # Invariant 8: hand-calc spot-check — FT_C1 own-funds and RWA constants.
        if abs(FT_C1_PRICE_DIFF * FT_C1_MULTIPLIER - FT_C1_OWN_FUNDS) > 0.01:
            raise AssertionError(
                f"P8.43: FT_C1 own_funds hand-calc mismatch: "
                f"{FT_C1_PRICE_DIFF} × {FT_C1_MULTIPLIER} != {FT_C1_OWN_FUNDS}"
            )
        if abs(FT_C1_OWN_FUNDS * 12.5 - FT_C1_RWA) > 0.01:
            raise AssertionError(
                f"P8.43: FT_C1 RWA hand-calc mismatch: {FT_C1_OWN_FUNDS} × 12.5 != {FT_C1_RWA}"
            )

        # Invariant 9: own-funds and RWA constants for remaining rows.
        for trade_id, of, rwa in [
            (FT_C2_ID, FT_C2_OWN_FUNDS, FT_C2_RWA),
            (FT_C3_ID, FT_C3_OWN_FUNDS, FT_C3_RWA),
        ]:
            if abs(of * 12.5 - rwa) > 0.01:
                raise AssertionError(
                    f"P8.43: {trade_id} RWA hand-calc mismatch: {of} × 12.5 != {rwa}"
                )

        # Invariant 10: portfolio total RWA constant matches sum of per-row RWAs.
        row_rwa_sum = FT_C1_RWA + FT_C2_RWA + FT_C3_RWA
        if abs(row_rwa_sum - PORTFOLIO_TOTAL_RWA) > 0.01:
            raise AssertionError(
                f"P8.43: PORTFOLIO_TOTAL_RWA {PORTFOLIO_TOTAL_RWA} != "
                f"sum of per-row RWAs {row_rwa_sum}"
            )

        # Invariant 11: band string constants are correct non-empty strings.
        for trade_id, band in [
            (FT_C1_ID, FT_C1_BAND),
            (FT_C2_ID, FT_C2_BAND),
            (FT_C3_ID, FT_C3_BAND),
        ]:
            if not isinstance(band, str) or not band:
                raise AssertionError(
                    f"P8.43: band constant for {trade_id!r} must be a non-empty string"
                )

        # Invariant 12: minimal counterparties frame has 3 rows with correct references.
        cp_lf = make_minimal_counterparties_frame()
        cp_df = cp_lf.collect()
        if cp_df.height != 3:
            raise AssertionError(
                f"P8.43: counterparties frame must have 3 rows (got {cp_df.height})"
            )
        cp_set = set(cp_df["counterparty_reference"].to_list())
        expected_cps = {"CP_FT_C1", "CP_FT_C2", "CP_FT_C3"}
        if cp_set != expected_cps:
            raise AssertionError(
                f"P8.43: counterparties must be {expected_cps}, got {cp_set}"
            )

        # No parquet files written — report zero files, zero records.
        return [(PYTHON_ONLY_NO_PARQUET, 0)]
    finally:
        sys.path.remove(fixtures_root)
        for mod in ("ccr.p843_failed_trade_builder",):
            sys.modules.pop(mod, None)


def _generate_ccr_floor1(output_dir: Path) -> list[tuple[str, int]]:
    """
    Generate P8.55 / B31-CCR-FLOOR-1 parquet files and smoke-check the bundle.

    Writes four parquet files to the ``ccr/`` output directory:
        ccr_floor1_trades.parquet             — 1 row (T_CCR_1, 5y GBP IR derivative)
        ccr_floor1_netting_sets.parquet       — 1 row (NS_CCR_1, CP_CCR_1)
        ccr_floor1_margin_agreements.parquet  — 0 rows (unmargined)
        ccr_floor1_ccr_collateral.parquet     — 0 rows (no collateral)

    Smoke-checks structural invariants on the bundle:
    - trades: 1 row, T_CCR_1, interest_rate, mtm_value=10,000,000
    - netting_sets: 1 row, NS_CCR_1, is_margined=False
    - RawDataBundle constructs without error (no raise on build)
    """
    fixtures_root = str(output_dir.parent)
    sys.path.insert(0, fixtures_root)
    try:
        from ccr.golden_ccr_floor1 import (
            CCR_FLOOR1_MTM,
            CCR_FLOOR1_NETTING_SET_ID,
            CCR_FLOOR1_TRADE_ID,
            build_raw_data_bundle_ccr_floor1,
            save_ccr_floor1_fixtures,
        )

        # Write parquet artefacts.
        saved = save_ccr_floor1_fixtures(output_dir)

        # Smoke-check: bundle must construct without raising.
        bundle = build_raw_data_bundle_ccr_floor1()
        assert bundle.ccr is not None, "B31-CCR-FLOOR-1: ccr must not be None"

        # Validate trades frame.
        trades_df = bundle.ccr.trades.trades.collect()
        if trades_df.height != 1:
            raise AssertionError(
                f"B31-CCR-FLOOR-1: expected 1 trade row, got {trades_df.height}"
            )
        if trades_df["trade_id"][0] != CCR_FLOOR1_TRADE_ID:
            raise AssertionError(
                f"B31-CCR-FLOOR-1: trade_id must be {CCR_FLOOR1_TRADE_ID!r}, "
                f"got {trades_df['trade_id'][0]!r}"
            )
        if trades_df["mtm_value"][0] != CCR_FLOOR1_MTM:
            raise AssertionError(
                f"B31-CCR-FLOOR-1: mtm_value must be {CCR_FLOOR1_MTM}, "
                f"got {trades_df['mtm_value'][0]}"
            )

        # Validate netting sets frame.
        ns_df = bundle.ccr.netting_sets.netting_sets.collect()
        if ns_df.height != 1:
            raise AssertionError(
                f"B31-CCR-FLOOR-1: expected 1 netting set row, got {ns_df.height}"
            )
        if ns_df["netting_set_id"][0] != CCR_FLOOR1_NETTING_SET_ID:
            raise AssertionError(
                f"B31-CCR-FLOOR-1: netting_set_id must be {CCR_FLOOR1_NETTING_SET_ID!r}"
            )
        if ns_df["is_margined"][0] is not False:
            raise AssertionError("B31-CCR-FLOOR-1: netting set must be unmargined")

        return [
            (f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()
        ]
    finally:
        sys.path.remove(fixtures_root)
        for mod in (
            "ccr.golden_ccr_floor1",
            CCR_TRADE_BUILDER_MODULE,
            CCR_NETTING_SET_BUILDER_MODULE,
            CCR_MARGIN_BUILDER_MODULE,
        ):
            sys.modules.pop(mod, None)


def _generate_p839_ccp(output_dir: Path) -> list[tuple[str, int]]:
    """
    Validate P8.39 CCP-wiring bundles (Python-only — no persistent parquet output).

    P8.39 / CCR-CCP-1 and CCR-CCP-2 provide orchestrator-ready RawDataBundles
    proving that apply_ccp_risk_weight, once wired into _run_ccr_stage, produces
    2% / 4% RWs instead of the CQS-2 SA-Institution fallback of 50%.
    The supplementary 2-counterparty book regression-guards the keyed-join in
    apply_ccp_risk_weight against cross-join fan-out.
    """
    fixtures_root = str(output_dir.parent)
    sys.path.insert(0, fixtures_root)
    try:
        from ccr.p839_ccp_builder import save_p839_fixtures

        return save_p839_fixtures()
    finally:
        sys.path.remove(fixtures_root)
        for mod in (
            "ccr.p839_ccp_builder",
            "ccr.qccp_builder",
            CCR_TRADE_BUILDER_MODULE,
            CCR_NETTING_SET_BUILDER_MODULE,
            CCR_MARGIN_BUILDER_MODULE,
        ):
            sys.modules.pop(mod, None)


def print_master_report(results: list[FixtureGroupResult], fixtures_dir: Path) -> None:
    """Print master generation report."""
    print("=" * 80)
    print("RWA CALCULATOR - MASTER FIXTURE GENERATOR")
    print("=" * 80)
    print(f"Output directory: {fixtures_dir}\n")

    total_files = 0
    total_records = 0

    for result in results:
        print(f"[OK] {result.group_name}")
        for filename, count in result.files:
            print(f"     - {filename}: {count} records")
        total_files += result.file_count
        total_records += result.total_records

    print("\n" + "-" * 80)
    print("SUMMARY BY GROUP")
    print("-" * 80)

    for result in results:
        print(
            f"  {result.group_name:<20} {result.file_count:>3} files  {result.total_records:>6} records"
        )

    print("-" * 80)
    print(f"  {'TOTAL':<20} {total_files:>3} files  {total_records:>6} records")
    print("=" * 80)


def print_data_integrity_check(fixtures_dir: Path) -> None:
    """Print data integrity validation results."""
    print("\n" + "=" * 80)
    print("DATA INTEGRITY CHECK")
    print("=" * 80)

    errors = []
    warnings = []

    # Load all parquet files
    try:
        counterparties = pl.read_parquet(fixtures_dir / "counterparty" / COUNTERPARTIES_PARQUET)
        loans = pl.read_parquet(fixtures_dir / "exposures" / "loans.parquet")
        facilities = pl.read_parquet(fixtures_dir / "exposures" / "facilities.parquet")
        contingents = pl.read_parquet(fixtures_dir / "exposures" / "contingents.parquet")
        collateral = pl.read_parquet(fixtures_dir / "collateral" / "collateral.parquet")
        guarantees = pl.read_parquet(fixtures_dir / "guarantee" / "guarantee.parquet")
        provisions = pl.read_parquet(fixtures_dir / "provision" / "provision.parquet")
        ratings = pl.read_parquet(fixtures_dir / "ratings" / "ratings.parquet")
        facility_mappings = pl.read_parquet(fixtures_dir / "exposures" / "facility_mapping.parquet")
        org_mappings = pl.read_parquet(fixtures_dir / "mapping" / "org_mapping.parquet")
        lending_mappings = pl.read_parquet(fixtures_dir / "mapping" / "lending_mapping.parquet")

        cpty_refs = set(counterparties["counterparty_reference"].to_list())

        # Check 1: All loan counterparty references exist
        loan_cpty_refs = set(loans["counterparty_reference"].to_list())
        missing_loan_cpty = loan_cpty_refs - cpty_refs
        if missing_loan_cpty:
            errors.append(f"Loans reference missing counterparties: {missing_loan_cpty}")
        else:
            print("[OK] All loan counterparty references valid")

        # Check 2: All facility counterparty references exist
        fac_cpty_refs = set(facilities["counterparty_reference"].to_list())
        missing_fac_cpty = fac_cpty_refs - cpty_refs
        if missing_fac_cpty:
            errors.append(f"Facilities reference missing counterparties: {missing_fac_cpty}")
        else:
            print("[OK] All facility counterparty references valid")

        # Check 3: All contingent counterparty references exist
        cont_cpty_refs = set(contingents["counterparty_reference"].to_list())
        missing_cont_cpty = cont_cpty_refs - cpty_refs
        if missing_cont_cpty:
            errors.append(f"Contingents reference missing counterparties: {missing_cont_cpty}")
        else:
            print("[OK] All contingent counterparty references valid")

        # Check 4: All rating counterparty references exist
        rating_cpty_refs = set(ratings["counterparty_reference"].to_list())
        missing_rating_cpty = rating_cpty_refs - cpty_refs
        if missing_rating_cpty:
            errors.append(f"Ratings reference missing counterparties: {missing_rating_cpty}")
        else:
            print("[OK] All rating counterparty references valid")

        # Check 5: Facility mappings reference valid facilities and loans
        fac_refs = set(facilities["facility_reference"].to_list())
        loan_refs = set(loans["loan_reference"].to_list())

        parent_fac_refs = set(facility_mappings["parent_facility_reference"].to_list())
        missing_parent_facs = parent_fac_refs - fac_refs
        if missing_parent_facs:
            errors.append(f"Facility mappings reference missing facilities: {missing_parent_facs}")
        else:
            print("[OK] All facility mapping parent references valid")

        # Check child references (can be facility or loan)
        child_refs = set(facility_mappings["child_reference"].to_list())
        valid_children = fac_refs | loan_refs
        missing_children = child_refs - valid_children
        if missing_children:
            warnings.append(f"Facility mappings reference unknown children: {missing_children}")
        else:
            print("[OK] All facility mapping child references valid")

        # Check 6: Org mappings reference valid counterparties
        org_parents = set(org_mappings["parent_counterparty_reference"].to_list())
        org_children = set(org_mappings["child_counterparty_reference"].to_list())
        missing_org = (org_parents | org_children) - cpty_refs
        if missing_org:
            errors.append(f"Org mappings reference missing counterparties: {missing_org}")
        else:
            print("[OK] All org mapping counterparty references valid")

        # Check 7: Lending mappings reference valid counterparties
        lending_parents = set(lending_mappings["parent_counterparty_reference"].to_list())
        lending_children = set(lending_mappings["child_counterparty_reference"].to_list())
        missing_lending = (lending_parents | lending_children) - cpty_refs
        if missing_lending:
            errors.append(f"Lending mappings reference missing counterparties: {missing_lending}")
        else:
            print("[OK] All lending mapping counterparty references valid")

        # Check 8: Collateral beneficiary references
        coll_loan_refs = set(
            collateral.filter(pl.col("beneficiary_type") == "loan")[
                "beneficiary_reference"
            ].to_list()
        )
        coll_fac_refs = set(
            collateral.filter(pl.col("beneficiary_type") == "facility")[
                "beneficiary_reference"
            ].to_list()
        )
        missing_coll_loans = coll_loan_refs - loan_refs
        missing_coll_facs = coll_fac_refs - fac_refs
        if missing_coll_loans:
            errors.append(f"Collateral references missing loans: {missing_coll_loans}")
        if missing_coll_facs:
            errors.append(f"Collateral references missing facilities: {missing_coll_facs}")
        if not missing_coll_loans and not missing_coll_facs:
            print("[OK] All collateral beneficiary references valid")

        # Check 9: Guarantee beneficiary references
        guar_loan_refs = set(
            guarantees.filter(pl.col("beneficiary_type") == "loan")[
                "beneficiary_reference"
            ].to_list()
        )
        guar_fac_refs = set(
            guarantees.filter(pl.col("beneficiary_type") == "facility")[
                "beneficiary_reference"
            ].to_list()
        )
        missing_guar_loans = guar_loan_refs - loan_refs
        missing_guar_facs = guar_fac_refs - fac_refs
        if missing_guar_loans:
            errors.append(f"Guarantees reference missing loans: {missing_guar_loans}")
        if missing_guar_facs:
            errors.append(f"Guarantees reference missing facilities: {missing_guar_facs}")
        if not missing_guar_loans and not missing_guar_facs:
            print("[OK] All guarantee beneficiary references valid")

        # Check 10: Guarantee guarantor references (should be counterparties)
        guarantor_refs = set(guarantees["guarantor"].to_list())
        missing_guarantors = guarantor_refs - cpty_refs
        if missing_guarantors:
            errors.append(f"Guarantees reference missing guarantors: {missing_guarantors}")
        else:
            print("[OK] All guarantee guarantor references valid")

        # Check 11: Provision beneficiary references
        prov_loan_refs = set(
            provisions.filter(pl.col("beneficiary_type") == "loan")[
                "beneficiary_reference"
            ].to_list()
        )
        missing_prov_loans = prov_loan_refs - loan_refs
        if missing_prov_loans:
            errors.append(f"Provisions reference missing loans: {missing_prov_loans}")
        else:
            print("[OK] All provision loan references valid")

        # Check 12: Model ID references (ratings → model_permissions)
        model_perms_path = fixtures_dir / "model_permissions" / MODEL_PERMISSIONS_PARQUET
        if model_perms_path.exists():
            model_perms = pl.read_parquet(model_perms_path)
            valid_model_ids = set(model_perms["model_id"].to_list())

            # Collect non-null model_ids from ratings
            rating_model_ids: set[str] = set()
            if "model_id" in ratings.columns:
                non_null = ratings.filter(pl.col("model_id").is_not_null())["model_id"].to_list()
                rating_model_ids.update(non_null)

            missing_model_ids = rating_model_ids - valid_model_ids
            if missing_model_ids:
                errors.append(f"Ratings reference missing model_ids: {missing_model_ids}")
            else:
                print(
                    f"[OK] All rating model_id references valid "
                    f"({len(rating_model_ids)} unique model_ids)"
                )
        else:
            print("[--] Model permissions file not found, skipping model_id check")

    except Exception as e:
        errors.append(f"Error during integrity check: {e}")

    # Print summary
    print("\n" + "-" * 80)
    if errors:
        print(f"ERRORS: {len(errors)}")
        for error in errors:
            print(f"  [X] {error}")
    if warnings:
        print(f"WARNINGS: {len(warnings)}")
        for warning in warnings:
            print(f"  [!] {warning}")
    if not errors and not warnings:
        print("All integrity checks passed!")
    print("=" * 80)


def _generate_p842_nonqccp_b5(output_dir: Path) -> list[tuple[str, int]]:
    """
    Validate P8.42 CCR-B5 builder imports (Python-only builder — no persistent parquet output).

    CCR-B5 pins the non-QCCP CCP trade exposure path through the institution SA
    risk-weight ladder at CQS-1 -> 20% (CRR Art. 107(2)(a) + Art. 120(1) Table 3).
    Trade economics are byte-identical to CCR-A1 (same dates, notional, MtM, delta)
    so the EAD is the CCR-A1 golden value loaded from CCR-A1.json.
    The new pin: risk_weight == 0.20, distinguishing CQS-1 from the CQS-2 fallback
    at 50% already pinned by the P8.39 two-counterparty book.
    """
    fixtures_root = str(output_dir.parent)
    sys.path.insert(0, fixtures_root)
    try:
        from ccr.p842_nonqccp_b5_builder import save_p842_fixtures  # noqa: PLC0415

        return save_p842_fixtures()
    finally:
        sys.path.remove(fixtures_root)
        for mod in (
            "ccr.p842_nonqccp_b5_builder",
            CCR_GOLDEN_A1_MODULE,
            CCR_TRADE_BUILDER_MODULE,
            CCR_NETTING_SET_BUILDER_MODULE,
            CCR_MARGIN_BUILDER_MODULE,
        ):
            sys.modules.pop(mod, None)


def _generate_ccr_d1_d3(output_dir: Path) -> list[tuple[str, int]]:
    """
    Validate P8.44 CCR-D1/D2/D3 fall-through guard bundles (Python-only — no persistent parquet).

    P8.44 / CCR-D1, CCR-D2, CCR-D3 provide three orchestrator-ready RawDataBundles
    that verify the engine always applies the full SA-CCR formula and never routes
    through Simplified SA-CCR (Art. 281) or the Original Exposure Method (Art. 282).

    The load-bearing scenario is CCR-D3: a margined OTM IR swap whose PFE multiplier
    drops below 1.0 (0.6048...).  Simplified Art. 281 would force the multiplier to 1.0,
    producing EAD 8,629,617.519 instead of the correct 6,464,360.391383706.

        CCR-D1: unmargined 10y GBP IR swap  (CCR-A1 economics)  — multiplier=1.0
        CCR-D2: unmargined 1y USD/GBP FX   (CCR-A2 economics)  — multiplier=1.0
        CCR-D3: margined 10y GBP IR swap, MtM=-4m (CCR-A13 economics)
                pfe_multiplier=0.6048083569079303 (PRIMARY PIN: != 1.0 proves full SA-CCR)

    Regulatory basis: CRR Art. 273a(1)/(2) threshold not implemented (absent from engine);
    Art. 278(3) multiplier always computed; Art. 279c(1) MF always applied (not OEM).
    """
    fixtures_root = str(output_dir.parent)
    sys.path.insert(0, fixtures_root)
    try:
        from ccr.golden_ccr_d1_d3 import save_ccr_d1_d3_fixtures  # noqa: PLC0415

        return save_ccr_d1_d3_fixtures()
    finally:
        sys.path.remove(fixtures_root)
        for mod in (
            "ccr.golden_ccr_d1_d3",
            CCR_GOLDEN_A1_MODULE,
            CCR_TRADE_BUILDER_MODULE,
            CCR_NETTING_SET_BUILDER_MODULE,
            CCR_MARGIN_BUILDER_MODULE,
        ):
            sys.modules.pop(mod, None)


def _generate_p849_dfc(output_dir: Path) -> list[tuple[str, int]]:
    """
    Validate P8.49 builder imports (Python-only builder — no persistent parquet output).

    P8.49 tests three independent DF-contribution scenarios (CCR-B2 / B3 / B4),
    each exercising a distinct CRR Art. 308/309 regulatory branch:

        CCR-B2: DFC_B2, QCCP pre-funded   (Art. 308), K_CM=1,000,000   RWEA=12,500,000
        CCR-B3: DFC_B3, non-QCCP pre-funded(Art. 309), K_CM=750,000    RWEA=9,375,000
        CCR-B4: DFC_B4, non-QCCP unfunded  (Art. 309), K_CM=400,000    RWEA=5,000,000

    Portfolio total RWEA (B2+B3+B4) = 26,875,000.

    Each row carries a distinct CCP counterparty reference.
    The fixture is a Python-only builder; test-writer imports constants and
    ``make_b2_frame()`` / ``make_combined_b2_b3_b4_frame()`` directly.

    Regulatory basis: CRR Art. 308(2)/(3) + Art. 309(1)/(2).
    """
    fixtures_root = str(output_dir.parent)
    sys.path.insert(0, fixtures_root)
    try:
        from ccr.p849_default_fund_builder import save_p849_fixtures  # noqa: PLC0415

        return save_p849_fixtures()
    finally:
        sys.path.remove(fixtures_root)
        sys.modules.pop("ccr.p849_default_fund_builder", None)


def _generate_p845_e1_e5(output_dir: Path) -> list[tuple[str, int]]:
    """
    Validate P8.45 / CCR-E1..E5 bundles (Python-only builder — no persistent parquet output).

    P8.45 tests five independent default-risk RWA routing scenarios that share
    identical trade economics (10y GBP IR swap, notional GBP 100m, EAD ~ 5,480,018)
    but differ in counterparty class (institution / corporate / sovereign) and
    regulatory framework (CRR / Basel 3.1):

        CCR-E1 (CRR):  institution, CQS 2  -> RW 0.50  (CRR Art. 120(1) Table 3)
        CCR-E2 (CRR):  corporate,   CQS 3  -> RW 1.00  (CRR Art. 122(1))
        CCR-E3 (CRR):  sovereign BR, CQS 3 -> RW 0.50  (CRR Art. 114(1) Table 1, non-domestic)
        CCR-E4 (B3.1): institution, CQS 2  -> RW 0.30  (PS1/26 Art. 120(2) T3 ECRA)
        CCR-E5 (B3.1): corporate,   CQS 3  -> RW 0.75  (PS1/26 Art. 122(2) Table 6)

    The fixture is a Python-only builder; test-writer imports the five
    ``build_raw_data_bundle_ccr_eN()`` functions and the two config factories
    ``make_crr_config()`` / ``make_b31_config()`` directly.

    Regulatory basis: CRR Art. 114, 120, 122, 274(2); PS1/26 Art. 120, 122, 274(2).
    """
    fixtures_root = str(output_dir.parent)
    sys.path.insert(0, fixtures_root)
    try:
        from ccr.p845_e1_e5_builder import save_p845_fixtures

        return save_p845_fixtures()
    finally:
        sys.path.remove(fixtures_root)
        for mod in (
            "ccr.p845_e1_e5_builder",
            CCR_GOLDEN_A1_MODULE,
            CCR_TRADE_BUILDER_MODULE,
            CCR_NETTING_SET_BUILDER_MODULE,
            CCR_MARGIN_BUILDER_MODULE,
        ):
            sys.modules.pop(mod, None)


def _generate_p860_cva_a1(output_dir: Path) -> list[tuple[str, int]]:
    """
    Generate P8.60 / CVA-A1 fixtures — BA-CVA reduced-K vertical slice.

    CVA-A1 tests the reduced version of BA-CVA (PS1/26 CVA Part 4.2-4.4) with a
    single counterparty (CP_CVA_001, Financials IG, M=3.0 years) and a single
    netting set (NS_CVA_001, 3-year GBP IR swap, GBP 100m notional).

    Parquet files produced (5 files):
        cva_a1_trades.parquet              1 row  (T_CVA_001, 3y GBP IR swap)
        cva_a1_netting_sets.parquet        1 row  (NS_CVA_001, CP_CVA_001)
        cva_a1_margin_agreements.parquet   0 rows (no CSA)
        cva_a1_ccr_collateral.parquet      0 rows (no CCR collateral)
        cva_a1_cva_counterparties.parquet  1 row  (FINANCIAL, IG, M=3.0, in_scope=True)

    Confirmed regulatory scalars (ps126app1.pdf):
        DSBA-CVA = 0.65       (page 399, section 4.2)
        rho = 50%             (page 399, section 4.2)
        DF = (1-e^-0.05M)/(0.05M)  (page 400, section 4.3)
        RW_Financials_IG = 5.0%    (page 401, section 4.4 table)
        x12.5 multiplier      (page 15, Own Funds Part 4(b))

    CORRECTION vs scenario-architect proposal: the proposal omitted the
    DSBA-CVA = 0.65 scalar. The correct RWEA formula is:
        RWEA_CVA = 0.65 * K_reduced * 12.5

    Regulatory basis: PS1/26 App.1 CVA Part 4.2-4.4; CRR Art. 274(2).
    """
    _REPO_ROOT_STR = str(_REPO_ROOT)
    if _REPO_ROOT_STR not in sys.path:
        sys.path.insert(0, _REPO_ROOT_STR)
    try:
        from tests.fixtures.p8_60.cva_a1_builder import save_p860_fixtures

        return save_p860_fixtures(output_dir)
    finally:
        for mod in list(sys.modules.keys()):
            if "p8_60" in mod or "cva_a1_builder" in mod:
                sys.modules.pop(mod, None)


def _generate_p862_cva_hedge_a1(output_dir: Path) -> list[tuple[str, int]]:
    """
    Generate P8.62 / CVA-HEDGE-A1 fixtures — full BA-CVA with perfect single-name CDS hedge.

    CVA-HEDGE-A1 extends the P8.60 reduced-version baseline by adding one eligible
    single-name CDS hedge (H_SN_CVA_001) that perfectly offsets the SCVA of
    CP_CVA_001. The perfect-hedge condition is B_h = EAD_NS / alpha (NOT EAD_NS).

    Key formula correction vs scenario-architect proposal:
        The SNH_c formula (ps126app1.pdf 4.7, page 402) carries NO (1/alpha).
        SCVA_c (4.3, page 400) does carry (1/alpha). For SNH_c == SCVA_c with
        r_hc=1.0 and matching RW/M/DF, the hedge notional must satisfy:
            B_h = EAD_NS / alpha  (i.e. EAD_NS / 1.4)

    Parquet files produced (1 file):
        cva_hedge_a1_single_name.parquet  1 row  (H_SN_CVA_001, IDENTICAL,
                                                  FINANCIAL/IG, M=3.0,
                                                  placeholder notional = EAD_ref/1.4)

    NOTE: The parquet uses a placeholder notional (reference EAD / alpha). The
    acceptance test rebuilds this row from the live pipeline EAD.

    Confirmed regulatory scalars (ps126app1.pdf):
        beta = 0.25                      (page 401, section 4.5)
        r_hc IDENTICAL = 1.00            (page 403, section 4.10)
        r_hc LEGALLY_RELATED = 0.80      (page 403, section 4.10)
        r_hc SAME_SECTOR_REGION = 0.50   (page 403, section 4.10)
        SNH_c formula (no 1/alpha)       (page 402, section 4.7)
        index diversification = 0.70     (page 403, section 4.8)

    Regulatory basis: PS1/26 App.1 CVA Part 4.5-4.10; CRR Art. 274(2).
    """
    _REPO_ROOT_STR = str(_REPO_ROOT)
    if _REPO_ROOT_STR not in sys.path:
        sys.path.insert(0, _REPO_ROOT_STR)
    try:
        from tests.fixtures.p8_62.cva_hedge_a1_builder import save_p862_fixtures

        return save_p862_fixtures(output_dir)
    finally:
        for mod in list(sys.modules.keys()):
            if "p8_62" in mod or "cva_hedge_a1_builder" in mod:
                sys.modules.pop(mod, None)


if __name__ == "__main__":
    main()
