"""
Generate P1.248 fixtures: partially-secured corporate A-IRB LGD-floor blend.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (engine/irb/formulas.py,
    engine/irb/transforms.py)

Key responsibilities:
- Produce one corporate counterparty row (CP-CORP-AIRB-P1248): entity_type="corporate",
  annual_revenue GBP 200,000,000 (below the GBP 440m large-corp F-IRB-only threshold,
  Art. 147(4C)/147A -- keeps A-IRB eligibility), unrated externally.
- Produce one drawn term loan row (LN-CORP-AIRB-P1248): GBP 1,000,000 drawn,
  own-estimate lgd=0.15, book_code="CORP_LENDING" (NOT "TRADE_FINANCE" --
  UK_CORP_AIRB_01 excludes that book), effective_maturity=2.5 (explicit override
  to avoid date-arithmetic ambiguity -- mirrors tests/fixtures/p1_98/p1_98.py).
- Produce one internal rating row (RTG-CORP-AIRB-P1248): pd=0.01, model_id=
  "UK_CORP_AIRB_01" -- the existing corporate A-IRB permission (advanced_irb, GB,
  excludes TRADE_FINANCE; tests/fixtures/model_permissions/model_permissions.py:104-110).
  A local model_permissions.parquet mirrors that row verbatim (self-contained scenario
  package, following the tests/fixtures/p1_223, p1_190, p1_154_b31 convention).
- Produce one commercial real-estate collateral row (COLL-CRE-P1248): collateral_type=
  "commercial_re", beneficiary_type="loan"/beneficiary_reference=LN-CORP-AIRB-P1248,
  maturity 2031-01-01 (well beyond the loan's 2028-07-01 maturity -- no Art. 237/238
  mismatch).

Defect under test (PS1/26 Art. 161(5) / BCBS CRE32.17):
    engine/irb/formulas.py:319-405 (_lgd_floor_blended_expression) computes the
    Art. 164(4)(c) EAD-weighted-average LGD floor blend using the crm_alloc_* /
    total_collateral_for_lgd columns from the Art. 231 sequential waterfall, but
    the eligibility gate at line 402 (``is_blended_eligible``) restricts it to
    ``retail_other`` / ``retail_qrre`` only. For a partially-secured CORPORATE
    A-IRB exposure the blend never fires; the code falls through to
    _lgd_floor_expression_with_collateral() (formulas.py:246-315) -- which in turn
    requires a raw ``collateral_type`` STRING column directly on the exposures
    frame. That column is never present on a genuine CRM-collateral-table-driven
    exposures frame (the collateral join aggregates into numeric crm_alloc_* /
    total_collateral_for_lgd columns only; ``collateral_type`` lives solely on the
    per-collateral-item frame and is dropped by the Art. 231 waterfall aggregation
    in engine/crm/collateral.py). So for this fixture shape the code falls all the
    way through to the flat _lgd_floor_expression() -- the single flat 25%
    unsecured floor (Art. 161(5)), collateral entirely ignored:
        lgd_floored = max(lgd_own=0.15, floors["unsecured"]=0.25) = 0.25 (BUG)
    This is a MORE conservative (too-high) floor than the correct blend, not the
    "single-type CRE 10% floor applied to the whole exposure" originally
    hypothesised in the scenario proposal -- see "Deviation from proposal" below.
    Either way, 0.25 (bug) != 0.19 (fix): the primary assertion still
    discriminates cleanly.

Post-fix (engine-implementer scope, not this package):
    Extend _lgd_floor_blended_expression's ``is_blended_eligible`` gate
    (formulas.py:402) to also match ``corporate`` / ``corporate_sme`` /
    ``institution``, and make ``lgdu_expr`` (formulas.py:388-393) class-aware:
    floors["unsecured"]=0.25 for corporate/institution (not the retail 0.30/0.50
    values). The blend then correctly computes:
        secured   (crm_alloc_real_estate)        = GBP 400,000.00 (~40% of EAD)
        unsecured (ead_gross - total_collateral_for_lgd) = GBP 600,000.00 (~60%)
        LGD_floor = (400,000 x 0.10 + 600,000 x 0.25) / 1,000,000 = 0.19
        lgd_floored = max(0.15, 0.19) = 0.19

Hand-calculation (Basel 3.1, CalculationConfig.basel_3_1(), permission_mode=IRB):
    EAD          = drawn_amount = 1,000,000 (fully drawn, no CCF ambiguity)
    PD_floored   = max(0.01, 0.0005) = 0.01   (Art. 163(1)/CRE30.55 corp floor)
    LGD_floored  = 0.19   (post-fix; PRIMARY assertion -- distinguishes 0.19 from
                            the pre-fix 0.25)
    Correlation (Art. 153(1), corporate, PD=0.01):
        w = (1 - e^-0.5) / (1 - e^-50) = 0.393469340
        R = 0.12w + 0.24(1-w)          = 0.192783679165516
    Maturity adjustment (M=2.5, via explicit effective_maturity override):
        b  = (0.11852 - 0.05478 x ln(0.01))^2 = 0.137486131 (0.13748613089693737)
        MA = 1 / (1 - 1.5b)                    = 1.259809547 (1.2598095009238282)
             (M - 2.5 = 0 simplifies the numerator to 1)
    K (engine convention -- the ``k`` column EXCLUDES the maturity adjustment;
       MA is applied separately at the risk_weight step, i.e.
       risk_weight = k x 12.5 x MA, NOT k = [...] x MA x 12.5):
        cond = N[(N^-1(0.01) + sqrt(R) x N^-1(0.999)) / sqrt(1-R)] = 0.140273 (0.14027267845651598)
        k    = 0.19 x 0.140273 - 0.01 x 0.19               = 0.024752 (0.024751808867656228)
    risk_weight = k x 12.5 x MA         = 0.389782 (0.38978204970654967)
    rwa         = risk_weight x EAD     = 389,782 (389,782.05)
    expected_loss = PD_floored x LGD_floored x EAD = 0.01 x 0.19 x 1,000,000 = 1,900

Deviation from the scenario proposal (why market_value != GBP 560,000):
    The proposal's hand-calc assumed a B31 "real-estate overcollateralisation 1.4x
    divisor" (effectively_secured = market_value / 1.4). Verified against the
    resolved rulepack: PRA PS1/26 Art. 230(1) replaces the CRR Foundation
    Collateral Method's step-function entirely with a continuous LGD* formula
    that has NO overcollateralisation divisor for ANY collateral type under
    Basel 3.1 -- ``firb_overcollateralisation_divisor_applies`` is
    ``enabled=False`` in src/rwa_calc/rulebook/packs/b31.py:689-693, so
    engine/crm/expressions.py::overcollateralisation_ratio_expr() returns 1.0
    uniformly for every collateral type under B31 (confirmed by direct pipeline
    run -- see "Verification" below). Instead, the SAME Art. 231 sequential
    waterfall that already computes total_collateral_for_lgd / crm_alloc_real_estate
    for the (already-implemented, already-tested per docs/specifications/crr/
    airb-calculation.md "27 dedicated tests") retail Art. 164(4)(c) blend --
    the exact mechanism this fix reuses per the compliance-audit fix note --
    applies the flat PS1/26 Art. 224/230(2) non-financial haircut
    (HC=40% for real_estate; src/rwa_calc/rulebook/packs/b31.py:797, cited
    "PS1/26 224") BEFORE the value enters total_collateral_for_lgd. A GBP
    560,000 real-estate collateral value would therefore actually secure
    560,000 x (1 - 0.40) = GBP 336,000 (33.6% of EAD) of this exposure, giving
    a blended floor of 0.1996 (not the proposal's clean discriminating 0.19).
    To preserve the proposal's intended 40%-of-EAD secured coverage and its
    exact lgd_floored=0.19 discriminating target (own LGD 0.15 sits strictly
    between the single-type CRE floor 0.10 and the correct blended floor 0.19),
    this fixture instead sets market_value = GBP 666,666.67, chosen so that
    market_value x (1 - 0.40) ~= GBP 400,000.00 (the exact 40%-of-EAD secured
    amount): 400,000 / 0.6 = 666,666.67 (rounded to the penny). All other
    proposal inputs (drawn_amount, own PD/LGD, maturity, collateral_type,
    beneficiary) are unchanged from Section 2 of the scenario proposal.

Verification (direct PipelineOrchestrator run against this exact fixture shape,
pre-fix engine, CalculationConfig.basel_3_1(permission_mode=PermissionMode.IRB)):
    exposure_class=corporate, approach_applied=advanced_irb, is_airb=True
    total_collateral_for_lgd = crm_alloc_real_estate = 400,000.00 (~40.0000002%
        of EAD -- the 2-tenths-of-a-penny rounding noise from market_value being
        rounded to the nearest penny is immaterial to any reasonable float
        tolerance; hand-computing the post-fix blend from this exact value
        gives lgd_floored=0.18999999969999998, i.e. 0.19 to within 3e-10)
    pd_floored=0.01, correlation=0.192783679165516, maturity_adjustment=
        1.2598095009238282 (bit-identical to the hand-calc above once
        effective_maturity=2.5 is supplied explicitly)
    Pre-fix (bug) lgd_floored=0.25 (flat unsecured floor; collateral ignored --
        see "Defect under test" above). Engine columns (pre-fix, confirmed by
        direct pipeline run): k=0.03256816961587036, risk_weight=
        0.5128711188721529, rwa=512,871.12, expected_loss=2,500
        (EAD x 0.01 x 0.25).

References:
    - PS1/26 Art. 161(5): A-IRB unsecured corporate LGD floor 25% / collateral-type
      LGDS floors (CRE unsecured floor via floors["commercial_real_estate"]=10%).
    - BCBS CRE32.17: partially-secured exposure-weighted-average LGD floor formula.
    - PS1/26 Art. 230: Foundation Collateral Method Art. 231 sequential waterfall
      (crm_alloc_* / total_collateral_for_lgd), reused by the A-IRB blend per the
      compliance-audit fix note.
    - PS1/26 Art. 163(1) / CRE30.55: corporate PD floor 0.05%.
    - PS1/26 Art. 153-154: IRB K, correlation, maturity adjustment.
    - PS1/26 Art. 147(4C)/147A: GBP 440m large-corp F-IRB-only boundary (kept
      below, so this exposure stays A-IRB-eligible).
    - src/rwa_calc/rulebook/packs/b31.py:157-179 (lgd_floors FormulaParams),
      :689-693 (firb_overcollateralisation_divisor_applies=False), :797
      (real_estate haircut=0.40, "PS1/26 224").
    - src/rwa_calc/engine/irb/formulas.py:301-315 (_lgd_floor_expression_with_collateral,
      bug fallback), :319-405 (_lgd_floor_blended_expression, gate at :402, LGDU
      at :388-393).
    - src/rwa_calc/engine/irb/transforms.py:341-373 (apply_lgd_floor, same dispatch),
      :1085-1112.
    - tests/fixtures/model_permissions/model_permissions.py:104-110 (UK_CORP_AIRB_01).
    - docs/plans/compliance-audit-crr-111-241-rectification.md Section 5, P1.248
      entry (fix note: extend eligibility to corporate/institution, reusing
      crm_alloc_* / total_collateral_for_lgd; LGDU=25% from floors["unsecured"]).
    - Target test: tests/acceptance/basel31/test_p1_248_partial_secured_corp_lgd_blend.py.

Usage:
    uv run python tests/fixtures/p1_248/p1_248.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    LOAN_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    RATINGS_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

COUNTERPARTY_REF = "CP-CORP-AIRB-P1248"
LOAN_REF = "LN-CORP-AIRB-P1248"
RATING_REF = "RTG-CORP-AIRB-P1248"
COLLATERAL_REF = "COLL-CRE-P1248"

#: Existing corporate A-IRB model permission (advanced_irb, GB, excludes
#: TRADE_FINANCE) -- tests/fixtures/model_permissions/model_permissions.py:104-110.
#: Reused verbatim rather than inventing a new permission id.
MODEL_ID = "UK_CORP_AIRB_01"

REPORTING_DATE = date(2026, 1, 1)
VALUE_DATE = date(2026, 1, 1)
RATING_DATE = date(2026, 1, 1)
#: ~2.5y calendar maturity; effective_maturity below is the authoritative M
#: (highest-priority override per engine/irb/transforms.py:1013-1017) so the
#: hand-calc's M=2.5 is exact regardless of day-count method.
MATURITY_DATE = date(2028, 7, 1)
#: Well beyond the loan's maturity -- no Art. 237/238 maturity mismatch.
COLLATERAL_MATURITY_DATE = date(2031, 1, 1)

DRAWN_AMOUNT: float = 1_000_000.0
ANNUAL_REVENUE: float = 200_000_000.0  # below the GBP 440m large-corp F-IRB-only threshold

#: A-IRB own-estimate LGD -- strictly between the single-type CRE floor (10%)
#: and the correct blended floor (19%), so the fix binds and is fail-first
#: discriminating (see module docstring "Defect under test").
LGD_OWN: float = 0.15
PD_OWN: float = 0.01  # 1.00% -- above the 0.05% B31 corporate PD floor
EFFECTIVE_MATURITY: float = 2.5

#: GBP 666,666.67 -- chosen so that, after the PS1/26 Art. 224/230(2) flat 40%
#: non-financial (real-estate) haircut already applied by the existing Art. 231
#: waterfall, the recognised secured amount is ~GBP 400,000.00 (40% of EAD).
#: See module docstring "Deviation from the scenario proposal" for the full
#: derivation (400,000 / (1 - 0.40) = 666,666.67, rounded to the penny).
MARKET_VALUE: float = 666_666.67

# ---------------------------------------------------------------------------
# Expected post-fix outputs (Basel 3.1) -- single source of truth for
# test-writer assertions. See module docstring "Hand-calculation" /
# "Verification" for full derivation.
# ---------------------------------------------------------------------------

EXPECTED_PD_FLOORED: float = 0.01
#: PRIMARY assertion -- distinguishes the fix (0.19) from the pre-fix bug
#: (0.25, flat unsecured floor -- collateral entirely ignored for this
#: fixture shape; see "Defect under test").
EXPECTED_LGD_FLOORED: float = 0.19
EXPECTED_CORRELATION: float = 0.192783679165516
EXPECTED_MATURITY_ADJUSTMENT: float = 1.2598095009238282
#: Engine convention: the ``k`` column EXCLUDES the maturity adjustment (MA is
#: applied separately at the risk_weight step: risk_weight = k x 12.5 x MA).
#: Confirmed against the pipeline's own pre-fix ``k`` column (see
#: "Verification" in the module docstring) -- correlation/PD/MA are unaffected
#: by the LGD-floor fix, so this hand-derived post-fix value is exact once the
#: fix ships.
EXPECTED_K: float = 0.024751808867656228
EXPECTED_RISK_WEIGHT: float = 0.38978204970654967
EXPECTED_EAD_FINAL: float = 1_000_000.0
EXPECTED_RWA: float = 389_782.05
EXPECTED_EXPECTED_LOSS: float = 1_900.0
#: Recognised secured amount feeding the blend (crm_alloc_real_estate /
#: total_collateral_for_lgd), ~40% of EAD.
EXPECTED_TOTAL_COLLATERAL_FOR_LGD: float = 400_000.0

# Pre-fix (bug) figures -- docstring/regression documentation only, not an
# assertion target. Flat unsecured floor (25%) applied because (a) the blend
# eligibility gate excludes corporate/institution and (b) no raw
# ``collateral_type`` column reaches the exposures frame via a genuine
# CRM-collateral-table join (see "Defect under test"). Values below are
# confirmed by a direct PipelineOrchestrator run against this exact fixture
# (see module docstring "Verification").
PRE_FIX_LGD_FLOORED: float = 0.25
PRE_FIX_K: float = 0.03256816961587036
PRE_FIX_RISK_WEIGHT: float = 0.5128711188721529
PRE_FIX_RWA: float = 512_871.12
PRE_FIX_EXPECTED_LOSS: float = 2_500.0


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """P1.248 corporate counterparty: unrated externally, GB, not defaulted."""

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    annual_revenue: float
    default_status: bool
    apply_fi_scalar: bool
    is_financial_sector_entity: bool
    is_managed_as_retail: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "annual_revenue": self.annual_revenue,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
            "is_financial_sector_entity": self.is_financial_sector_entity,
            "is_managed_as_retail": self.is_managed_as_retail,
        }


@dataclass(frozen=True)
class _Loan:
    """
    P1.248 drawn term loan: GBP 1,000,000, own LGD 15%, book_code="CORP_LENDING".

    book_code deliberately avoids "TRADE_FINANCE" -- UK_CORP_AIRB_01 excludes
    that book (tests/fixtures/model_permissions/model_permissions.py:104-110).
    effective_maturity=2.5 is set directly (highest-priority M override) so the
    hand-calc's M=2.5 is exact regardless of date day-count method.
    """

    loan_reference: str
    counterparty_reference: str
    book_code: str
    currency: str
    value_date: date
    maturity_date: date
    drawn_amount: float
    interest: float
    lgd: float
    seniority: str
    effective_maturity: float

    def to_dict(self) -> dict:
        return {
            "loan_reference": self.loan_reference,
            "counterparty_reference": self.counterparty_reference,
            "book_code": self.book_code,
            "currency": self.currency,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "drawn_amount": self.drawn_amount,
            "interest": self.interest,
            "lgd": self.lgd,
            "seniority": self.seniority,
            "effective_maturity": self.effective_maturity,
        }


@dataclass(frozen=True)
class _Rating:
    """P1.248 internal rating: pd=0.01, model_id=UK_CORP_AIRB_01 (no external CQS)."""

    rating_reference: str
    counterparty_reference: str
    rating_type: str
    pd: float
    model_id: str
    rating_date: date

    def to_dict(self) -> dict:
        return {
            "rating_reference": self.rating_reference,
            "counterparty_reference": self.counterparty_reference,
            "rating_type": self.rating_type,
            "pd": self.pd,
            "model_id": self.model_id,
            "rating_date": self.rating_date,
        }


@dataclass(frozen=True)
class _ModelPermission:
    """
    P1.248 model permission -- mirrors the shared UK_CORP_AIRB_01 row verbatim
    (tests/fixtures/model_permissions/model_permissions.py:104-110), packaged
    locally so this scenario is self-contained (matches the tests/fixtures/
    p1_223, p1_190, p1_154_b31 convention).
    """

    model_id: str
    exposure_class: str
    approach: str
    country_codes: str | None
    excluded_book_codes: str | None

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "exposure_class": self.exposure_class,
            "approach": self.approach,
            "country_codes": self.country_codes,
            "excluded_book_codes": self.excluded_book_codes,
        }


@dataclass(frozen=True)
class _Collateral:
    """
    P1.248 commercial real-estate collateral row.

    beneficiary_type="loan"/beneficiary_reference=LN-CORP-AIRB-P1248 anchors the
    collateral directly to the exposure (matches the proposal's "beneficiary =
    the exposure"). is_eligible_irb_collateral=True / is_eligible_financial_
    collateral=False mirror the tests/fixtures/p1_190/p1_190.py convention for
    eligible non-financial IRB collateral (CRR Art. 199(4)/(5) / PS1/26 Art. 199).
    market_value is derived -- see module docstring "Deviation from the
    scenario proposal".
    """

    collateral_reference: str
    collateral_type: str
    currency: str
    maturity_date: date
    market_value: float
    beneficiary_type: str
    beneficiary_reference: str
    is_eligible_financial_collateral: bool
    is_eligible_irb_collateral: bool
    valuation_date: date
    valuation_type: str

    def to_dict(self) -> dict:
        return {
            "collateral_reference": self.collateral_reference,
            "collateral_type": self.collateral_type,
            "currency": self.currency,
            "maturity_date": self.maturity_date,
            "market_value": self.market_value,
            "beneficiary_type": self.beneficiary_type,
            "beneficiary_reference": self.beneficiary_reference,
            "is_eligible_financial_collateral": self.is_eligible_financial_collateral,
            "is_eligible_irb_collateral": self.is_eligible_irb_collateral,
            "valuation_date": self.valuation_date,
            "valuation_type": self.valuation_type,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1248_counterparty() -> pl.DataFrame:
    """Return the P1.248 counterparty as a single-row DataFrame."""
    row = _Counterparty(
        counterparty_reference=COUNTERPARTY_REF,
        counterparty_name="Partial-Secured AIRB Corporate Ltd",
        entity_type="corporate",
        country_code="GB",
        annual_revenue=ANNUAL_REVENUE,
        default_status=False,
        apply_fi_scalar=False,
        is_financial_sector_entity=False,
        is_managed_as_retail=False,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1248_loan() -> pl.DataFrame:
    """Return the P1.248 loan as a single-row DataFrame."""
    row = _Loan(
        loan_reference=LOAN_REF,
        counterparty_reference=COUNTERPARTY_REF,
        book_code="CORP_LENDING",
        currency="GBP",
        value_date=VALUE_DATE,
        maturity_date=MATURITY_DATE,
        drawn_amount=DRAWN_AMOUNT,
        interest=0.0,
        lgd=LGD_OWN,
        seniority="senior",
        effective_maturity=EFFECTIVE_MATURITY,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(LOAN_SCHEMA))


def create_p1248_rating() -> pl.DataFrame:
    """Return the P1.248 internal rating as a single-row DataFrame."""
    row = _Rating(
        rating_reference=RATING_REF,
        counterparty_reference=COUNTERPARTY_REF,
        rating_type="internal",
        pd=PD_OWN,
        model_id=MODEL_ID,
        rating_date=RATING_DATE,
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(RATINGS_SCHEMA))


def create_p1248_model_permission() -> pl.DataFrame:
    """Return the P1.248 model permission (UK_CORP_AIRB_01) as a single-row DataFrame."""
    row = _ModelPermission(
        model_id=MODEL_ID,
        exposure_class="corporate",
        approach="advanced_irb",
        country_codes="GB",
        excluded_book_codes="TRADE_FINANCE",
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA))


def create_p1248_collateral() -> pl.DataFrame:
    """Return the P1.248 commercial real-estate collateral as a single-row DataFrame."""
    row = _Collateral(
        collateral_reference=COLLATERAL_REF,
        collateral_type="commercial_re",
        currency="GBP",
        maturity_date=COLLATERAL_MATURITY_DATE,
        market_value=MARKET_VALUE,
        beneficiary_type="loan",
        beneficiary_reference=LOAN_REF,
        is_eligible_financial_collateral=False,
        is_eligible_irb_collateral=True,
        valuation_date=REPORTING_DATE,
        valuation_type="market",
    )
    return pl.DataFrame([row.to_dict()], schema=dtypes_of(COLLATERAL_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p1248_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.248 parquet files and return a mapping of name to path.

    Files written:
        counterparty.parquet       -- 1 row (CP-CORP-AIRB-P1248)
        loan.parquet                -- 1 row (LN-CORP-AIRB-P1248)
        rating.parquet              -- 1 row (RTG-CORP-AIRB-P1248 -> UK_CORP_AIRB_01)
        model_permission.parquet    -- 1 row (UK_CORP_AIRB_01, mirrors shared fixture)
        collateral.parquet          -- 1 row (COLL-CRE-P1248, commercial_re)

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    output_dir.mkdir(parents=True, exist_ok=True)

    saved: dict[str, Path] = {}

    artefacts = [
        ("counterparty", create_p1248_counterparty()),
        ("loan", create_p1248_loan()),
        ("rating", create_p1248_rating()),
        ("model_permission", create_p1248_model_permission()),
        ("collateral", create_p1248_collateral()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.248 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: corporate A-IRB, own LGD=0.15, partially secured by")
    print("          commercial_re (~40% of EAD after the flat 40% Art. 230(2)")
    print("          non-financial haircut).")
    print(f"Bug path:  lgd_floored={PRE_FIX_LGD_FLOORED} (flat unsecured floor,")
    print("           collateral ignored -- corporate excluded from blend gate)")
    print(f"Fix:       lgd_floored={EXPECTED_LGD_FLOORED} (EAD-weighted blend,")
    print("           Art. 164(4)(c) formula extended to corporate/institution)")
    print(f"Expected:  rwa~{EXPECTED_RWA:,.0f} (fix) vs rwa~{PRE_FIX_RWA:,.0f} (bug)")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1248_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
