"""
P2.49 fixture builder: CR9 column-a taxonomy extension seed frame (Basel 3.1 only).

Pipeline position (reporting path):
    seeded results LazyFrame
        -> Pillar3Generator._generate_all_cr9(lf, framework="BASEL_3_1")
        -> Pillar3TemplateBundle.cr9 (B31 only)

Scenario design (P2.49 — PRA PS1/26 Annex XXII, Art. 147, 147A, 452(h)):

    CR9 column-a (exposure class) taxonomy is expanded from 4+6 leaves to 5+10
    leaves.  The new sub-classes require three discriminator columns beyond the
    two originally consumed:

        is_sme               (Bool)   — retail SME vs non-SME split
        property_type        (Str)    — "residential" / "commercial" for retail
                                       mortgage sub-classes
        cp_is_financial_sector_entity (Bool) — True flags F-IRB corporate as
                                       "Corporates — Financial and large corporates"

    These three columns are already defined in the pipeline schema (schemas.py)
    and carried onto the results frame.  Unlike P3.5's ECAI columns, they are
    NOT seed-only injections — they exist in the production path.

Corrected taxonomy (post P2.49 engine change):

    F-IRB (5 leaves):
        1.   institution               → "Institutions"
        2.1  specialised_lending       → "Corporates — Specialised lending"
        2.2  corporate_financial_large → "Corporates — Financial and large corporates"
                                         (exposure_class=="corporate" AND
                                          cp_is_financial_sector_entity==True)
        2.3  corporate_sme             → "Corporates — Other general corporates (SME)"
        2.4  corporate_other_non_sme   → "Corporates — Other general corporates (non-SME)"
                                         (exposure_class=="corporate" AND
                                          cp_is_financial_sector_entity==False)

    A-IRB (10 leaves):
        1.1  specialised_lending       → "Corporates — Specialised lending"
        1.2  corporate_sme             → "Corporates — Other general corporates (SME)"
        1.3  corporate_other_non_sme   → "Corporates — Other general corporates (non-SME)"
                                         (exposure_class=="corporate")
        2.1  retail_rre_sme            → "Retail — Secured by residential immovable property (SME)"
                                         (retail_mortgage AND residential AND is_sme)
        2.2  retail_rre_non_sme        → "Retail — Secured by residential immovable property (non-SME)"
                                         (retail_mortgage AND residential AND NOT is_sme)
        2.3  retail_cre_sme            → "Retail — Secured by commercial immovable property (SME)"
                                         (retail_mortgage AND commercial AND is_sme)
        2.4  retail_cre_non_sme        → "Retail — Secured by commercial immovable property (non-SME)"
                                         (retail_mortgage AND commercial AND NOT is_sme)
        2.5  retail_qrre               → "Retail — Qualifying revolving"
        2.6  retail_other_sme          → "Retail — Other (SME)"
                                         (retail_other AND is_sme)
        2.7  retail_other_non_sme      → "Retail — Other (non-SME)"
                                         (retail_other AND NOT is_sme)

Seed frame: one obligor per CR9 sub-class (15 rows total: 5 F-IRB + 10 A-IRB).

    Row  | approach        | exposure_class   | is_sme | property_type | cp_is_fin | maps to
    -----+-----------------+------------------+--------+---------------+-----------+-----------------------------
    R01  | foundation_irb  | institution      | False  | None          | False     | foundation_irb - institution
    R02  | foundation_irb  | specialised_lend | False  | None          | False     | foundation_irb - specialised_lending
    R03  | foundation_irb  | corporate        | False  | None          | True      | foundation_irb - corporate_financial_large
    R04  | foundation_irb  | corporate_sme    | True   | None          | False     | foundation_irb - corporate_sme
    R05  | foundation_irb  | corporate        | False  | None          | False     | foundation_irb - corporate_other_non_sme
    R06  | advanced_irb    | specialised_lend | False  | None          | False     | advanced_irb - specialised_lending
    R07  | advanced_irb    | corporate_sme    | True   | None          | False     | advanced_irb - corporate_sme
    R08  | advanced_irb    | corporate        | False  | None          | False     | advanced_irb - corporate_other_non_sme
    R09  | advanced_irb    | retail_mortgage  | True   | residential   | False     | advanced_irb - retail_rre_sme
    R10  | advanced_irb    | retail_mortgage  | False  | residential   | False     | advanced_irb - retail_rre_non_sme
    R11  | advanced_irb    | retail_mortgage  | True   | commercial    | False     | advanced_irb - retail_cre_sme
    R12  | advanced_irb    | retail_mortgage  | False  | commercial    | False     | advanced_irb - retail_cre_non_sme
    R13  | advanced_irb    | retail_qrre      | False  | None          | False     | advanced_irb - retail_qrre
    R14  | advanced_irb    | retail_other     | True   | None          | False     | advanced_irb - retail_other_sme
    R15  | advanced_irb    | retail_other     | False  | None          | False     | advanced_irb - retail_other_non_sme

Each row carries the columns consumed by _compute_cr9_values (cols c-h):
    counterparty_reference  — unique per row (unique-obligor counting)
    ead_final               — EAD weight for col f (_cr9_ewa_pd_pct)
    irb_pd_floored          — reported PD (cols f / g)
    irb_pd_original         — allocation PD (bucket selection for CR6 PD ranges)
    is_defaulted            — default-count discriminator for col d
    drawn_amount, nominal_amount, undrawn_amount — supporting columns
    exposure_type, ccf_applied                   — supporting columns

Expected dict keys (post engine change):
    "foundation_irb - institution"
    "foundation_irb - specialised_lending"
    "foundation_irb - corporate_financial_large"
    "foundation_irb - corporate_sme"
    "foundation_irb - corporate_other_non_sme"
    "advanced_irb - specialised_lending"
    "advanced_irb - corporate_sme"
    "advanced_irb - corporate_other_non_sme"
    "advanced_irb - retail_rre_sme"
    "advanced_irb - retail_rre_non_sme"
    "advanced_irb - retail_cre_sme"
    "advanced_irb - retail_cre_non_sme"
    "advanced_irb - retail_qrre"
    "advanced_irb - retail_other_sme"
    "advanced_irb - retail_other_non_sme"

Usage (clean-import check):
    cd /path/to/worktrees/P2.49
    PYTHONPATH=src /path/to/.venv/bin/python tests/fixtures/p2_49/p2_49.py

References:
    - PRA PS1/26 Annex XXII paras 12-15, pp. 18-22
    - Art. 147(2)(b)/(c)(i)-(iii)/(d)(i)-(iii)
    - Art. 147A(1)(b)/(d)/(e) — financial/large corporates
    - Art. 452(h) — IRB PD back-testing disclosure
    - templates.py:601/611 (CR9_AIRB_CLASSES / CR9_FIRB_CLASSES)
    - generator.py:647-667 (_generate_all_cr9)
    - schemas.py:1474 (is_sme), :669/:1974 (property_type), :380 (is_financial_sector_entity)
"""

from __future__ import annotations

import polars as pl

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

SCENARIO_ID: str = "P2.49"
FRAMEWORK: str = "BASEL_3_1"

# Expected number of leaf classes after engine change
EXPECTED_FIRB_CLASS_COUNT: int = 5
EXPECTED_AIRB_CLASS_COUNT: int = 10

# Expected dict keys emitted by _generate_all_cr9 with this seed frame
EXPECTED_KEYS: frozenset[str] = frozenset(
    [
        "foundation_irb - institution",
        "foundation_irb - specialised_lending",
        "foundation_irb - corporate_financial_large",
        "foundation_irb - corporate_sme",
        "foundation_irb - corporate_other_non_sme",
        "advanced_irb - specialised_lending",
        "advanced_irb - corporate_sme",
        "advanced_irb - corporate_other_non_sme",
        "advanced_irb - retail_rre_sme",
        "advanced_irb - retail_rre_non_sme",
        "advanced_irb - retail_cre_sme",
        "advanced_irb - retail_cre_non_sme",
        "advanced_irb - retail_qrre",
        "advanced_irb - retail_other_sme",
        "advanced_irb - retail_other_non_sme",
    ]
)

# ---------------------------------------------------------------------------
# Row-level expected values for discriminator routing assertions
# ---------------------------------------------------------------------------

# F-IRB corporate + cp_is_financial_sector_entity=True → financial_large key
FIRB_FINANCIAL_LARGE_KEY: str = "foundation_irb - corporate_financial_large"
# F-IRB corporate + cp_is_financial_sector_entity=False → other_non_sme key
FIRB_OTHER_NON_SME_KEY: str = "foundation_irb - corporate_other_non_sme"
# A-IRB retail_mortgage + commercial + is_sme → retail_cre_sme key
AIRB_CRE_SME_KEY: str = "advanced_irb - retail_cre_sme"
# A-IRB retail_mortgage + residential + NOT is_sme → retail_rre_non_sme key
AIRB_RRE_NON_SME_KEY: str = "advanced_irb - retail_rre_non_sme"
# A-IRB corporate (not sme, not specialised) → corporate_other_non_sme key
AIRB_CORP_OTHER_NON_SME_KEY: str = "advanced_irb - corporate_other_non_sme"


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------


def build_cr9_irb_results_lf() -> pl.LazyFrame:
    """Return a seeded IRB results LazyFrame with one obligor per CR9 sub-class.

    Produces 15 rows covering all 5 F-IRB and 10 A-IRB leaf classes introduced
    by the P2.49 taxonomy extension.  The three new discriminator columns
    (``is_sme``, ``property_type``, ``cp_is_financial_sector_entity``) are
    included alongside all columns required by ``_compute_cr9_values``.

    All PD values are well within a single CR6 PD-range bucket (0.01–0.02
    range maps to bucket "10" — 1.00% to 2.50%) to keep bucket assertions
    simple.  No row is defaulted, so col d=0 for every sub-class.

    Returns:
        A LazyFrame with 15 rows and the full discriminator + metrics column set.
    """
    rows = [
        # ---- F-IRB leaves ----
        # R01: institution → "foundation_irb - institution"
        {
            "counterparty_reference": "P249_R01",
            "approach_applied": "foundation_irb",
            "exposure_class": "institution",
            "is_sme": False,
            "property_type": None,
            "cp_is_financial_sector_entity": False,
            "ead_final": 1000.0,
            "irb_pd_floored": 0.010,
            "irb_pd_original": 0.010,
            "is_defaulted": False,
            "drawn_amount": 900.0,
            "nominal_amount": 100.0,
            "undrawn_amount": 100.0,
            "interest": 0.0,
            "exposure_type": "loan",
            "ccf_applied": 1.0,
            "rwa_final": 500.0,
            "irb_lgd_floored": 0.45,
            "irb_maturity_m": 2.5,
            "irb_expected_loss": 4.5,
        },
        # R02: specialised_lending → "foundation_irb - specialised_lending"
        {
            "counterparty_reference": "P249_R02",
            "approach_applied": "foundation_irb",
            "exposure_class": "specialised_lending",
            "is_sme": False,
            "property_type": None,
            "cp_is_financial_sector_entity": False,
            "ead_final": 2000.0,
            "irb_pd_floored": 0.012,
            "irb_pd_original": 0.012,
            "is_defaulted": False,
            "drawn_amount": 1800.0,
            "nominal_amount": 200.0,
            "undrawn_amount": 200.0,
            "interest": 0.0,
            "exposure_type": "loan",
            "ccf_applied": 1.0,
            "rwa_final": 1200.0,
            "irb_lgd_floored": 0.45,
            "irb_maturity_m": 2.5,
            "irb_expected_loss": 24.0,
        },
        # R03: corporate + cp_is_financial_sector_entity=True
        #      → "foundation_irb - corporate_financial_large"
        {
            "counterparty_reference": "P249_R03",
            "approach_applied": "foundation_irb",
            "exposure_class": "corporate",
            "is_sme": False,
            "property_type": None,
            "cp_is_financial_sector_entity": True,
            "ead_final": 3000.0,
            "irb_pd_floored": 0.015,
            "irb_pd_original": 0.015,
            "is_defaulted": False,
            "drawn_amount": 2700.0,
            "nominal_amount": 300.0,
            "undrawn_amount": 300.0,
            "interest": 0.0,
            "exposure_type": "loan",
            "ccf_applied": 1.0,
            "rwa_final": 1800.0,
            "irb_lgd_floored": 0.45,
            "irb_maturity_m": 2.5,
            "irb_expected_loss": 45.0,
        },
        # R04: corporate_sme → "foundation_irb - corporate_sme"
        {
            "counterparty_reference": "P249_R04",
            "approach_applied": "foundation_irb",
            "exposure_class": "corporate_sme",
            "is_sme": True,
            "property_type": None,
            "cp_is_financial_sector_entity": False,
            "ead_final": 500.0,
            "irb_pd_floored": 0.018,
            "irb_pd_original": 0.018,
            "is_defaulted": False,
            "drawn_amount": 450.0,
            "nominal_amount": 50.0,
            "undrawn_amount": 50.0,
            "interest": 0.0,
            "exposure_type": "loan",
            "ccf_applied": 1.0,
            "rwa_final": 300.0,
            "irb_lgd_floored": 0.45,
            "irb_maturity_m": 2.5,
            "irb_expected_loss": 9.0,
        },
        # R05: corporate + cp_is_financial_sector_entity=False
        #      → "foundation_irb - corporate_other_non_sme"
        {
            "counterparty_reference": "P249_R05",
            "approach_applied": "foundation_irb",
            "exposure_class": "corporate",
            "is_sme": False,
            "property_type": None,
            "cp_is_financial_sector_entity": False,
            "ead_final": 4000.0,
            "irb_pd_floored": 0.020,
            "irb_pd_original": 0.020,
            "is_defaulted": False,
            "drawn_amount": 3600.0,
            "nominal_amount": 400.0,
            "undrawn_amount": 400.0,
            "interest": 0.0,
            "exposure_type": "loan",
            "ccf_applied": 1.0,
            "rwa_final": 2400.0,
            "irb_lgd_floored": 0.45,
            "irb_maturity_m": 2.5,
            "irb_expected_loss": 80.0,
        },
        # ---- A-IRB leaves ----
        # R06: specialised_lending → "advanced_irb - specialised_lending"
        {
            "counterparty_reference": "P249_R06",
            "approach_applied": "advanced_irb",
            "exposure_class": "specialised_lending",
            "is_sme": False,
            "property_type": None,
            "cp_is_financial_sector_entity": False,
            "ead_final": 1500.0,
            "irb_pd_floored": 0.010,
            "irb_pd_original": 0.010,
            "is_defaulted": False,
            "drawn_amount": 1350.0,
            "nominal_amount": 150.0,
            "undrawn_amount": 150.0,
            "interest": 0.0,
            "exposure_type": "loan",
            "ccf_applied": 1.0,
            "rwa_final": 900.0,
            "irb_lgd_floored": 0.30,
            "irb_maturity_m": 2.5,
            "irb_expected_loss": 15.0,
        },
        # R07: corporate_sme → "advanced_irb - corporate_sme"
        {
            "counterparty_reference": "P249_R07",
            "approach_applied": "advanced_irb",
            "exposure_class": "corporate_sme",
            "is_sme": True,
            "property_type": None,
            "cp_is_financial_sector_entity": False,
            "ead_final": 600.0,
            "irb_pd_floored": 0.012,
            "irb_pd_original": 0.012,
            "is_defaulted": False,
            "drawn_amount": 540.0,
            "nominal_amount": 60.0,
            "undrawn_amount": 60.0,
            "interest": 0.0,
            "exposure_type": "loan",
            "ccf_applied": 1.0,
            "rwa_final": 360.0,
            "irb_lgd_floored": 0.30,
            "irb_maturity_m": 2.5,
            "irb_expected_loss": 7.2,
        },
        # R08: corporate (not sme) → "advanced_irb - corporate_other_non_sme"
        {
            "counterparty_reference": "P249_R08",
            "approach_applied": "advanced_irb",
            "exposure_class": "corporate",
            "is_sme": False,
            "property_type": None,
            "cp_is_financial_sector_entity": False,
            "ead_final": 2500.0,
            "irb_pd_floored": 0.015,
            "irb_pd_original": 0.015,
            "is_defaulted": False,
            "drawn_amount": 2250.0,
            "nominal_amount": 250.0,
            "undrawn_amount": 250.0,
            "interest": 0.0,
            "exposure_type": "loan",
            "ccf_applied": 1.0,
            "rwa_final": 1500.0,
            "irb_lgd_floored": 0.30,
            "irb_maturity_m": 2.5,
            "irb_expected_loss": 37.5,
        },
        # R09: retail_mortgage + residential + is_sme
        #      → "advanced_irb - retail_rre_sme"
        {
            "counterparty_reference": "P249_R09",
            "approach_applied": "advanced_irb",
            "exposure_class": "retail_mortgage",
            "is_sme": True,
            "property_type": "residential",
            "cp_is_financial_sector_entity": False,
            "ead_final": 800.0,
            "irb_pd_floored": 0.010,
            "irb_pd_original": 0.010,
            "is_defaulted": False,
            "drawn_amount": 720.0,
            "nominal_amount": 80.0,
            "undrawn_amount": 80.0,
            "interest": 0.0,
            "exposure_type": "loan",
            "ccf_applied": 1.0,
            "rwa_final": 240.0,
            "irb_lgd_floored": 0.10,
            "irb_maturity_m": 1.0,
            "irb_expected_loss": 0.8,
        },
        # R10: retail_mortgage + residential + NOT is_sme
        #      → "advanced_irb - retail_rre_non_sme"
        {
            "counterparty_reference": "P249_R10",
            "approach_applied": "advanced_irb",
            "exposure_class": "retail_mortgage",
            "is_sme": False,
            "property_type": "residential",
            "cp_is_financial_sector_entity": False,
            "ead_final": 1200.0,
            "irb_pd_floored": 0.008,
            "irb_pd_original": 0.008,
            "is_defaulted": False,
            "drawn_amount": 1080.0,
            "nominal_amount": 120.0,
            "undrawn_amount": 120.0,
            "interest": 0.0,
            "exposure_type": "loan",
            "ccf_applied": 1.0,
            "rwa_final": 360.0,
            "irb_lgd_floored": 0.10,
            "irb_maturity_m": 1.0,
            "irb_expected_loss": 0.96,
        },
        # R11: retail_mortgage + commercial + is_sme
        #      → "advanced_irb - retail_cre_sme"
        {
            "counterparty_reference": "P249_R11",
            "approach_applied": "advanced_irb",
            "exposure_class": "retail_mortgage",
            "is_sme": True,
            "property_type": "commercial",
            "cp_is_financial_sector_entity": False,
            "ead_final": 700.0,
            "irb_pd_floored": 0.012,
            "irb_pd_original": 0.012,
            "is_defaulted": False,
            "drawn_amount": 630.0,
            "nominal_amount": 70.0,
            "undrawn_amount": 70.0,
            "interest": 0.0,
            "exposure_type": "loan",
            "ccf_applied": 1.0,
            "rwa_final": 280.0,
            "irb_lgd_floored": 0.10,
            "irb_maturity_m": 1.0,
            "irb_expected_loss": 0.84,
        },
        # R12: retail_mortgage + commercial + NOT is_sme
        #      → "advanced_irb - retail_cre_non_sme"
        {
            "counterparty_reference": "P249_R12",
            "approach_applied": "advanced_irb",
            "exposure_class": "retail_mortgage",
            "is_sme": False,
            "property_type": "commercial",
            "cp_is_financial_sector_entity": False,
            "ead_final": 900.0,
            "irb_pd_floored": 0.014,
            "irb_pd_original": 0.014,
            "is_defaulted": False,
            "drawn_amount": 810.0,
            "nominal_amount": 90.0,
            "undrawn_amount": 90.0,
            "interest": 0.0,
            "exposure_type": "loan",
            "ccf_applied": 1.0,
            "rwa_final": 360.0,
            "irb_lgd_floored": 0.10,
            "irb_maturity_m": 1.0,
            "irb_expected_loss": 1.26,
        },
        # R13: retail_qrre → "advanced_irb - retail_qrre"
        {
            "counterparty_reference": "P249_R13",
            "approach_applied": "advanced_irb",
            "exposure_class": "retail_qrre",
            "is_sme": False,
            "property_type": None,
            "cp_is_financial_sector_entity": False,
            "ead_final": 400.0,
            "irb_pd_floored": 0.020,
            "irb_pd_original": 0.020,
            "is_defaulted": False,
            "drawn_amount": 360.0,
            "nominal_amount": 40.0,
            "undrawn_amount": 40.0,
            "interest": 0.0,
            "exposure_type": "loan",
            "ccf_applied": 1.0,
            "rwa_final": 120.0,
            "irb_lgd_floored": 0.50,
            "irb_maturity_m": 1.0,
            "irb_expected_loss": 4.0,
        },
        # R14: retail_other + is_sme → "advanced_irb - retail_other_sme"
        {
            "counterparty_reference": "P249_R14",
            "approach_applied": "advanced_irb",
            "exposure_class": "retail_other",
            "is_sme": True,
            "property_type": None,
            "cp_is_financial_sector_entity": False,
            "ead_final": 300.0,
            "irb_pd_floored": 0.015,
            "irb_pd_original": 0.015,
            "is_defaulted": False,
            "drawn_amount": 270.0,
            "nominal_amount": 30.0,
            "undrawn_amount": 30.0,
            "interest": 0.0,
            "exposure_type": "loan",
            "ccf_applied": 1.0,
            "rwa_final": 90.0,
            "irb_lgd_floored": 0.30,
            "irb_maturity_m": 1.0,
            "irb_expected_loss": 1.35,
        },
        # R15: retail_other + NOT is_sme → "advanced_irb - retail_other_non_sme"
        {
            "counterparty_reference": "P249_R15",
            "approach_applied": "advanced_irb",
            "exposure_class": "retail_other",
            "is_sme": False,
            "property_type": None,
            "cp_is_financial_sector_entity": False,
            "ead_final": 500.0,
            "irb_pd_floored": 0.018,
            "irb_pd_original": 0.018,
            "is_defaulted": False,
            "drawn_amount": 450.0,
            "nominal_amount": 50.0,
            "undrawn_amount": 50.0,
            "interest": 0.0,
            "exposure_type": "loan",
            "ccf_applied": 1.0,
            "rwa_final": 150.0,
            "irb_lgd_floored": 0.30,
            "irb_maturity_m": 1.0,
            "irb_expected_loss": 2.7,
        },
    ]

    schema = {
        "counterparty_reference": pl.Utf8,
        "approach_applied": pl.Utf8,
        "exposure_class": pl.Utf8,
        "is_sme": pl.Boolean,
        "property_type": pl.Utf8,
        "cp_is_financial_sector_entity": pl.Boolean,
        "ead_final": pl.Float64,
        "irb_pd_floored": pl.Float64,
        "irb_pd_original": pl.Float64,
        "is_defaulted": pl.Boolean,
        "drawn_amount": pl.Float64,
        "nominal_amount": pl.Float64,
        "undrawn_amount": pl.Float64,
        "interest": pl.Float64,
        "exposure_type": pl.Utf8,
        "ccf_applied": pl.Float64,
        "rwa_final": pl.Float64,
        "irb_lgd_floored": pl.Float64,
        "irb_maturity_m": pl.Float64,
        "irb_expected_loss": pl.Float64,
    }

    return pl.DataFrame(rows, schema=schema).lazy()


# ---------------------------------------------------------------------------
# Self-check (also serves as clean-import verification)
# ---------------------------------------------------------------------------


def _verify_lf() -> None:
    """Verify the LazyFrame builds and has the expected shape and content."""
    lf = build_cr9_irb_results_lf()
    df = lf.collect()
    assert df.height == 15, f"Expected 15 rows, got {df.height}"

    expected_cols = {
        "counterparty_reference",
        "approach_applied",
        "exposure_class",
        "is_sme",
        "property_type",
        "cp_is_financial_sector_entity",
        "ead_final",
        "irb_pd_floored",
        "irb_pd_original",
        "is_defaulted",
    }
    assert expected_cols.issubset(set(df.columns)), (
        f"Missing columns: {expected_cols - set(df.columns)}"
    )

    # 5 F-IRB rows, 10 A-IRB rows
    firb = df.filter(pl.col("approach_applied") == "foundation_irb")
    airb = df.filter(pl.col("approach_applied") == "advanced_irb")
    assert firb.height == 5, f"Expected 5 F-IRB rows, got {firb.height}"
    assert airb.height == 10, f"Expected 10 A-IRB rows, got {airb.height}"

    # All counterparty_references are unique
    assert df.select(pl.col("counterparty_reference").n_unique()).item() == 15, (
        "counterparty_reference values must be unique"
    )

    # No defaulted rows (col d = 0 for all sub-classes)
    defaulted = df.filter(pl.col("is_defaulted") == True)  # noqa: E712
    assert defaulted.height == 0, f"Expected 0 defaulted rows, got {defaulted.height}"

    # F-IRB discriminator routing checks
    firb_corp = firb.filter(pl.col("exposure_class") == "corporate")
    assert firb_corp.height == 2, f"Expected 2 F-IRB corporate rows, got {firb_corp.height}"

    firb_fin = firb_corp.filter(pl.col("cp_is_financial_sector_entity") == True)  # noqa: E712
    firb_non_fin = firb_corp.filter(pl.col("cp_is_financial_sector_entity") == False)  # noqa: E712
    assert firb_fin.height == 1, f"Expected 1 F-IRB corporate financial row, got {firb_fin.height}"
    assert firb_non_fin.height == 1, (
        f"Expected 1 F-IRB corporate non-financial row, got {firb_non_fin.height}"
    )

    # A-IRB retail_mortgage sub-class routing checks
    airb_rm = airb.filter(pl.col("exposure_class") == "retail_mortgage")
    assert airb_rm.height == 4, f"Expected 4 A-IRB retail_mortgage rows, got {airb_rm.height}"

    residential_sme = airb_rm.filter(
        (pl.col("property_type") == "residential") & (pl.col("is_sme") == True)  # noqa: E712
    )
    residential_non_sme = airb_rm.filter(
        (pl.col("property_type") == "residential") & (pl.col("is_sme") == False)  # noqa: E712
    )
    commercial_sme = airb_rm.filter(
        (pl.col("property_type") == "commercial") & (pl.col("is_sme") == True)  # noqa: E712
    )
    commercial_non_sme = airb_rm.filter(
        (pl.col("property_type") == "commercial") & (pl.col("is_sme") == False)  # noqa: E712
    )
    assert residential_sme.height == 1, f"Expected 1 RRE SME row, got {residential_sme.height}"
    assert residential_non_sme.height == 1, (
        f"Expected 1 RRE non-SME row, got {residential_non_sme.height}"
    )
    assert commercial_sme.height == 1, f"Expected 1 CRE SME row, got {commercial_sme.height}"
    assert commercial_non_sme.height == 1, (
        f"Expected 1 CRE non-SME row, got {commercial_non_sme.height}"
    )

    # A-IRB retail_other sub-class routing checks
    airb_ro = airb.filter(pl.col("exposure_class") == "retail_other")
    assert airb_ro.height == 2, f"Expected 2 A-IRB retail_other rows, got {airb_ro.height}"
    ro_sme = airb_ro.filter(pl.col("is_sme") == True)  # noqa: E712
    ro_non_sme = airb_ro.filter(pl.col("is_sme") == False)  # noqa: E712
    assert ro_sme.height == 1, f"Expected 1 retail_other SME row, got {ro_sme.height}"
    assert ro_non_sme.height == 1, f"Expected 1 retail_other non-SME row, got {ro_non_sme.height}"


def _verify_constants() -> None:
    """Verify scenario constants are internally consistent."""
    assert EXPECTED_FIRB_CLASS_COUNT == 5, (
        f"EXPECTED_FIRB_CLASS_COUNT must be 5, got {EXPECTED_FIRB_CLASS_COUNT}"
    )
    assert EXPECTED_AIRB_CLASS_COUNT == 10, (
        f"EXPECTED_AIRB_CLASS_COUNT must be 10, got {EXPECTED_AIRB_CLASS_COUNT}"
    )
    assert len(EXPECTED_KEYS) == 15, f"EXPECTED_KEYS must have 15 entries, got {len(EXPECTED_KEYS)}"

    # Confirm the four discriminator-routing keys exist in the expected set
    for key in [
        FIRB_FINANCIAL_LARGE_KEY,
        FIRB_OTHER_NON_SME_KEY,
        AIRB_CRE_SME_KEY,
        AIRB_RRE_NON_SME_KEY,
        AIRB_CORP_OTHER_NON_SME_KEY,
    ]:
        assert key in EXPECTED_KEYS, f"Key {key!r} missing from EXPECTED_KEYS"


if __name__ == "__main__":
    _verify_lf()
    _verify_constants()
    lf = build_cr9_irb_results_lf()
    df = lf.collect()
    print("P2.49 fixture self-check passed.")
    print(f"  {df.height} rows: 5 F-IRB + 10 A-IRB leaf obligors")
    print(f"  Expected F-IRB class count: {EXPECTED_FIRB_CLASS_COUNT}")
    print(f"  Expected A-IRB class count: {EXPECTED_AIRB_CLASS_COUNT}")
    print(f"  Expected dict keys ({len(EXPECTED_KEYS)}):")
    for key in sorted(EXPECTED_KEYS):
        print(f"    {key!r}")
