"""
Generate P1.220 fixtures: institution-typed PSE stays SA-only under Basel 3.1
(quasi-sovereign class), not F-IRB.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer
    (data/schemas.py B31_SOVEREIGN_LIKE_ENTITY_TYPES / a sibling
    B31_QUASI_SOVEREIGN_SA_ONLY list, engine/stages/classify/approach.py
    _apply_b31_approach_restrictions)

Key responsibilities:
- Produce one counterparty row: entity_type="pse_institution", GB, non-FSE,
  sovereign_cqs=2, unrated own-CQS (external cqs null) so the SA engine hits
  the PSE unrated / sovereign-derived branch (Art. 116(1) Table 2).
- Produce one loan row: GBP 10,000,000 drawn, senior, no modelled LGD,
  ~2.5-year maturity (F-IRB M=2.5, illustrative only — SA ignores maturity
  for a PSE outside the Art. 116(3) short-term carve-out window).
- Produce one internal rating row: pd=0.001 (0.10%, above the 0.05% B31
  institution PD floor), model_id="M-INST-FIRB", cqs=null (no external ECAI
  assessment).
- Produce one model-permissions row: model_id="M-INST-FIRB",
  exposure_class="institution", approach="foundation_irb" — grants the
  institution F-IRB permission that the *current* (pre-fix) engine wrongly
  honours for this PSE because the SA-only backstop
  (``B31_SOVEREIGN_LIKE_ENTITY_TYPES``) deliberately excludes
  ``pse_institution`` / ``rgla_institution``.

The bug (capital understatement):
    entity_type="pse_institution" maps to SA class PSE / IRB class
    INSTITUTION (packs/common.py). Under B31 the approach-restriction step
    (engine/stages/classify/approach.py) only blocks A-IRB for the
    institution class and keeps F-IRB open; the SA-only backstop keys on
    B31_SOVEREIGN_LIKE_ENTITY_TYPES, which excludes pse_institution /
    rgla_institution. With an institution F-IRB model permission attached,
    the engine currently routes this PSE to F-IRB (RW ~= 26.36%) instead of
    the mandatory SA path (RW = 50%).

Regulatory basis (PS1/26, per the orchestrator PDF-verification addendum —
see the P1.220 scenario proposal header; this SUPERSEDES the "0%-RW
qualifier applies to the whole quasi-sovereign list" reading in the repo's
basel31 skill / specs, which mis-states this rule):
    Art. 147(3)(c)-(e): regional governments, local authorities and public
        sector entities are assigned to the central-government / quasi-
        sovereign exposure class (Art. 147(2)(a)) UNCONDITIONALLY — no
        "risk weight of 0%" qualifier (that qualifier binds only to
        Art. 147(3)(g) international organisations).
    Art. 147A(1)(a): the quasi-sovereign class (Art. 147(2)(a)) is
        Standardised-Approach only.
    => pse_institution / rgla_institution (RGLAs/PSEs that CRR Art. 147(4)(b)
       treated as institutions) must route to SA under B31, not F-IRB.

Hand-calculation (Basel 3.1, CalculationConfig.basel_3_1(),
                   PermissionMode.IRB, full_irb_b31() org-wide permissions):

    Correct (post-fix) — SA path:
        entity_type               = pse_institution
        SA exposure_class         = PSE
        Art. 147(3)(e)+147A(1)(a) = quasi-sovereign class -> SA ONLY
        external cqs              = null -> PSE unrated branch
        cp_sovereign_cqs          = 2
        SA risk weight            = pse_risk_weights_sovereign_derived[CQS2] = 0.50
                                     (CRR/PS1/26 Art. 116(1) Table 2; not
                                     overridden in the B31 pack)
        EAD                       = drawn_amount + interest
                                   = 10,000,000 + 0 = 10,000,000
        supporting factor         = 1.0 (SME/infra factors removed under B31)
        RWA                       = EAD x RW x SF = 10,000,000 x 0.50 x 1.0
                                   = 5,000,000

    Current (pre-fix, illustrative only — NOT asserted precisely; depends on
    the engine's polars-normal-stats N/G implementation) — F-IRB path:
        IRB exposure_class (post-align) = INSTITUTION
        PD    = 0.001   (> institution PD floor 0.0005, PS1/26 Art. 160(1))
        LGD   = 0.40    (unsecured/senior/non-FSE, PS1/26 Art. 161(1)(aa))
        M     = 2.5     (clipped [1, 5])
        RW   ~= 0.2636  (~26.36% by hand; engine smoke test confirms
                          0.263324 -- close, small N/G rounding difference)
        RWA  ~= 2,635,550 (by hand; engine smoke test: 2,633,236)
    Understatement demonstrated: 5,000,000 - 2,633,236 ~= 2,366,764
    (modelled RW sits ~47% below the mandatory SA weight).

    A fixture-builder smoke test through PipelineOrchestrator().run_with_data
    (pre-fix engine, 2026-07-10) confirms the primary assertion: the current
    engine returns approach="foundation_irb" for this row (the bug), not
    "standardised" — see ILLUSTRATIVE_PRE_FIX_* constants below.

References:
    - PS1/26 Art. 147(3)(c)-(e) read with Art. 147A(1)(a) (quasi-sovereign
      class assignment, unconditional; class is SA-only).
    - CRR/PS1/26 Art. 116(1) Table 2 (PSE sovereign-derived SA weight).
    - PS1/26 Art. 160(1) (institution PD floor); Art. 161(1)(aa) (F-IRB
      supervisory LGD, unsecured/senior/non-FSE); Art. 153(1)/(2) (K formula)
      — F-IRB parameters shown for the "before" state only.
    - src/rwa_calc/data/schemas.py:1526-1548 — RGLA_PSE_ENTITY_TYPES,
      B31_SOVEREIGN_LIKE_ENTITY_TYPES (the bug site: excludes
      rgla_institution / pse_institution).
    - src/rwa_calc/engine/stages/classify/approach.py:204-226 —
      _apply_b31_approach_restrictions (b31_sa_only must fire for these
      entity types under the approach_restrictions_b31_applicable Feature).
    - src/rwa_calc/rulebook/packs/crr.py:812-825 —
      pse_risk_weights_sovereign_derived (CQS2 -> 0.50).
    - src/rwa_calc/rulebook/packs/b31.py:139-156 — pd_floors (institution
      0.0005); :718-737 — firb_supervisory_lgd (unsecured/senior/non-FSE 0.40).
    - docs/plans/compliance-audit-crr-111-241-rectification.md Section 5 WS5
      (P1.220).

Usage:
    uv run python tests/fixtures/p1_220/p1_220.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    LOAN_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    RATINGS_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

COUNTERPARTY_REF = "CP-PSE-INST-01"
LOAN_REF = "LN-PSE-INST-01"
RATING_REF = "RTG-PSE-INST-01"
MODEL_ID = "M-INST-FIRB"

# 2.5-year window (2027-01-04 -> 2029-07-04, 30 months exactly): gives F-IRB
# M=2.5 for the illustrative "before" state. B31 effective 1 Jan 2027; the
# value date sits just after go-live so no transitional carve-outs apply.
VALUE_DATE = date(2027, 1, 4)
MATURITY_DATE = date(2029, 7, 4)
REPORTING_DATE = VALUE_DATE
RATING_DATE = date(2027, 1, 3)

# Scenario inputs (match the hand-calculation in the module docstring)
SOVEREIGN_CQS = 2  # home-sovereign CQS -> Art. 116(1) Table 2 lookup
INTERNAL_PD = 0.001  # 0.10%, above the 0.05% B31 institution PD floor
DRAWN_AMOUNT = 10_000_000.0

# Expected outputs (post-fix SA path — for assertions in the acceptance test)
EXPECTED_APPROACH = "standardised"  # ApproachType.SA.value — primary assertion
EXPECTED_EXPOSURE_CLASS = "pse"  # ExposureClass.PSE.value
EXPECTED_EXPOSURE_CLASS_IRB = "institution"  # unchanged
EXPECTED_RISK_WEIGHT = 0.50  # Art. 116(1) Table 2, CQS 2, PSE sovereign-derived
EXPECTED_EAD = DRAWN_AMOUNT  # 10,000,000.0 (interest=0, no CCF/CRM)
EXPECTED_RWA = EXPECTED_EAD * EXPECTED_RISK_WEIGHT  # 5,000,000.0

# Illustrative-only "before" figures (F-IRB path the current/pre-fix engine
# takes). Not asserted precisely — depends on the engine's
# polars-normal-stats N/G implementation; see module docstring hand-calc.
# Confirmed by a fixture-builder smoke test through
# PipelineOrchestrator().run_with_data (pre-fix, 2026-07-10): the engine
# currently returns approach="foundation_irb",
# exposure_class="institution" (rewritten by _align_irb_exposure_class),
# risk_weight~=0.263324 -> rwa_final~=2,633,236 (hand-calc estimate 0.263555
# / 2,635,550 was close but not exact -- rounding in the by-hand N/G steps).
ILLUSTRATIVE_PRE_FIX_APPROACH = "foundation_irb"  # ApproachType.FIRB.value
ILLUSTRATIVE_PRE_FIX_RISK_WEIGHT = 0.2633235579442769  # approximate, do not pin exactly
ILLUSTRATIVE_PRE_FIX_RWA = DRAWN_AMOUNT * ILLUSTRATIVE_PRE_FIX_RISK_WEIGHT  # ~2,633,236


# ---------------------------------------------------------------------------
# Minimal dataclasses for this scenario
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    P1.220 counterparty: institution-typed PSE, GB, non-FSE, sovereign_cqs=2.

    entity_type="pse_institution" maps to SA exposure_class PSE and IRB
    exposure_class INSTITUTION (packs/common.py entity-type map) — the
    dual-class row this scenario exercises. is_financial_sector_entity=False
    so the F-IRB "before" LGD reads the 40% non-FSE row rather than the FSE
    row. apply_fi_scalar=False — no 1.25x correlation multiplier.
    """

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    sovereign_cqs: int
    is_financial_sector_entity: bool
    apply_fi_scalar: bool
    default_status: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "sovereign_cqs": self.sovereign_cqs,
            "is_financial_sector_entity": self.is_financial_sector_entity,
            "apply_fi_scalar": self.apply_fi_scalar,
            "default_status": self.default_status,
        }


@dataclass(frozen=True)
class _Loan:
    """
    P1.220 loan: GBP 10,000,000 drawn, senior, no modelled LGD, ~2.5y maturity.

    lgd=None -> no modelled LGD, so the F-IRB "before" path uses the
    supervisory LGD (PS1/26 Art. 161(1)(aa)); SA ignores it entirely.
    ~2.5-year maturity gives F-IRB M=2.5 (illustrative only) and keeps the
    exposure well outside the Art. 116(3) PSE short-term carve-out window.
    """

    loan_reference: str
    counterparty_reference: str
    currency: str
    value_date: date
    maturity_date: date
    drawn_amount: float
    interest: float
    lgd: float | None
    seniority: str

    def to_dict(self) -> dict:
        return {
            "loan_reference": self.loan_reference,
            "counterparty_reference": self.counterparty_reference,
            "currency": self.currency,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "drawn_amount": self.drawn_amount,
            "interest": self.interest,
            "lgd": self.lgd,
            "seniority": self.seniority,
        }


@dataclass(frozen=True)
class _Rating:
    """
    P1.220 internal rating: pd=0.001, model_id=M-INST-FIRB, cqs=null.

    rating_type="internal" populates internal_pd. model_id links to the
    P1.220 model permission granting institution F-IRB — the permission the
    current/pre-fix engine wrongly honours for this PSE. cqs=null means no
    external ECAI assessment, so the SA engine (post-fix) hits the PSE
    *unrated* (sovereign-derived) branch rather than an own-CQS lookup.
    """

    rating_reference: str
    counterparty_reference: str
    rating_type: str
    rating_agency: str
    rating_value: str
    cqs: int | None
    pd: float
    rating_date: date
    is_solicited: bool
    model_id: str

    def to_dict(self) -> dict:
        return {
            "rating_reference": self.rating_reference,
            "counterparty_reference": self.counterparty_reference,
            "rating_type": self.rating_type,
            "rating_agency": self.rating_agency,
            "rating_value": self.rating_value,
            "cqs": self.cqs,
            "pd": self.pd,
            "rating_date": self.rating_date,
            "is_solicited": self.is_solicited,
            "model_id": self.model_id,
        }


@dataclass(frozen=True)
class _ModelPermission:
    """
    P1.220 model permission: institution F-IRB, no geo or book restrictions.

    A dedicated model_id (M-INST-FIRB) avoids interference with the existing
    INST_FIRB_01 permission in the shared model_permissions fixture.
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


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1220_counterparty() -> pl.DataFrame:
    """Return the P1.220 counterparty as a single-row DataFrame."""
    rows = [
        _Counterparty(
            counterparty_reference=COUNTERPARTY_REF,
            counterparty_name="Institution-Typed PSE (P1.220)",
            entity_type="pse_institution",
            country_code="GB",
            sovereign_cqs=SOVEREIGN_CQS,
            is_financial_sector_entity=False,
            apply_fi_scalar=False,
            default_status=False,
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1220_loan() -> pl.DataFrame:
    """Return the P1.220 loan as a single-row DataFrame."""
    rows = [
        _Loan(
            loan_reference=LOAN_REF,
            counterparty_reference=COUNTERPARTY_REF,
            currency="GBP",
            value_date=VALUE_DATE,
            maturity_date=MATURITY_DATE,
            drawn_amount=DRAWN_AMOUNT,
            interest=0.0,
            lgd=None,
            seniority="senior",
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_p1220_rating() -> pl.DataFrame:
    """Return the P1.220 internal rating as a single-row DataFrame."""
    rows = [
        _Rating(
            rating_reference=RATING_REF,
            counterparty_reference=COUNTERPARTY_REF,
            rating_type="internal",
            rating_agency="internal",
            rating_value="INT-2",
            cqs=None,
            pd=INTERNAL_PD,
            rating_date=RATING_DATE,
            is_solicited=False,
            model_id=MODEL_ID,
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


def create_p1220_model_permission() -> pl.DataFrame:
    """Return the P1.220 model permission as a single-row DataFrame."""
    rows = [
        _ModelPermission(
            model_id=MODEL_ID,
            exposure_class="institution",
            approach="foundation_irb",
            country_codes=None,
            excluded_book_codes=None,
        )
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p1220_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.220 parquet files and return a mapping of name to path.

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("counterparty", create_p1220_counterparty()),
        ("loan", create_p1220_loan()),
        ("rating", create_p1220_rating()),
        ("model_permission", create_p1220_model_permission()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.220 fixture generation complete")
    print("-" * 70)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<20} {len(df):>3} row(s)  ->  {path}")
    print("-" * 70)
    print("Scenario: institution-typed PSE (pse_institution) stays SA-only")
    print("          under Basel 3.1 (Art. 147(3)(c)-(e) + Art. 147A(1)(a))")
    print(f"  Expected (post-fix) approach      : {EXPECTED_APPROACH}")
    print(f"  Expected (post-fix) exposure_class: {EXPECTED_EXPOSURE_CLASS}")
    print(f"  Expected (post-fix) risk_weight    : {EXPECTED_RISK_WEIGHT:.2%}")
    print(f"  Expected (post-fix) ead_final       : {EXPECTED_EAD:,.0f}")
    print(f"  Expected (post-fix) rwa_final       : {EXPECTED_RWA:,.0f}")
    print(
        f"  Illustrative (pre-fix) approach/RW : "
        f"{ILLUSTRATIVE_PRE_FIX_APPROACH} / {ILLUSTRATIVE_PRE_FIX_RISK_WEIGHT:.2%} "
        f"(not asserted precisely)"
    )


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1220_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
