"""
Generate P1.351 fixtures: CRR F-IRB retail purchased-receivables LGD guard.

Pipeline position:
    fixture-builder output -> test-writer -> engine-implementer (irb/transforms.py)

Key responsibilities:
- Reach the ``IrbLgdReason.SUPERVISORY_SUBTYPE`` branch in
  ``engine/irb/transforms.py::apply_firb_lgd`` on a RETAIL row, which
  ``scripts/branch_census_baseline.json`` banks ``dead`` (owner P1.341) —
  every fixture in the estate leaves ``purchased_receivables_subtype`` null.
- Provide the FOUR-row minimum the Wave 0 premise audit specified, two that
  FIRE the guard and two that stay SILENT, so a future
  ``IrbLgdReason.SUPERVISORY_SUBTYPE_UNAUTHORISED_CLASS`` partition (retail +
  senior/subordinated subtype -> new reason; Art. 161(1)(e)/(f) confine those
  supervisory rates to purchased CORPORATE receivables) can be told apart from
  both an over-broad implementation (catches every subtype) and an
  over-reaching one (catches every class):

    1. retail + "senior" + null lgd        -> FIRES  (LOAN_P1351_RETAIL_SENIOR)
    2. retail + "subordinated" + null lgd   -> FIRES  (LOAN_P1351_RETAIL_SUB)
    3. retail + "dilution_risk" + null lgd  -> SILENT (LOAN_P1351_RETAIL_DILUTION)
       Anti-false-positive control: Art. 164(1) legislates a retail dilution-risk
       rate and the engine already handles it correctly. If the future guard is
       ever written as ``!= "dilution_risk"`` instead of an allowlist of
       ["senior", "subordinated"], this row fires and the guard is inverted.
    4. corporate + "senior" + null lgd      -> SILENT (LOAN_P1351_CORP_SENIOR)
       Anti-over-reach control: the authorised Art. 161(1)(e) population.
- A fifth row (LOAN_P1351_RETAIL_NOSUBTYPE, no subtype, null lgd) is a
  documentation control, not one of the four guard rows: it reaches
  ``IrbLgdReason.UNKNOWN_FALLBACK`` and the BR001 pipeline-exit error today,
  in contrast to rows 1-3's clean ``SUPERVISORY_SUBTYPE``. Registering the
  contrast in the fixture itself (rather than citing it from memory) lets the
  contrast be re-verified by anyone running this module standalone.

Route constraints (measured by the Wave 0 premise audit — CRR ONLY):
    No B31 route to a retail row with a null LGD could be constructed: Art.
    147A blocks retail F-IRB under Basel 3.1, the A-IRB gate at
    ``engine/stages/classify/permissions.py:340`` requires ``has_modelled_lgd``
    (which a null-LGD row cannot satisfy), and the two remaining B31 retail
    limbs are mutually exclusive with an IRB route. This fixture is CRR-only;
    treat B31 as not demonstrated reachable for this scenario.

Two traps a naive retail-F-IRB fixture falls into (both avoided here):
    - ``approach="advanced_irb"`` in the model_permission row sends the row to
      SA (RW 0.75) instead of F-IRB — ``airb_expr`` requires
      ``has_modelled_lgd``, which a null-LGD row can never satisfy. This
      fixture uses ``approach="foundation_irb"``.
    - Setting ``is_managed_as_retail=True`` on the counterparty routes the row
      through ``_build_approach_expr``'s branch 1 (managed-as-retail without
      LGD -> SA, ``engine/stages/classify/approach.py:285-289``) BEFORE it
      ever reaches the F-IRB branch, because this scenario's LGD is null by
      construction. This fixture leaves ``is_managed_as_retail`` False (the
      loader-seal default via ``apply_boolean_column_defaults`` — CRR's
      ``qualifies_as_retail`` is a threshold-only check with no dependency on
      it, and ``entity_type="individual"`` alone routes both
      ``exposure_class`` and ``exposure_class_irb`` to RETAIL_OTHER via
      ``entity_type_to_sa_class`` — see ``data/schemas.py`` COUNTERPARTY_SCHEMA
      entity_type notes).

Hand-calculation (CRR F-IRB, CalculationConfig.crr(), retail_other, PD=2%,
EAD=100,000 GBP, no maturity adjustment for retail — CRR Art. 154(1)):

    R = 0.03 x f(PD) + 0.16 x (1 - f(PD)),  f(PD) = (1-exp(-35xPD))/(1-exp(-35))
    K = LGD x N[(G(PD) + sqrt(R/(1-R)) x G(0.999)) / sqrt(1-R)] - PD x LGD
    RWA = K x 12.5 x EAD   (no maturity adjustment, no scaling factor under CRR)

    Row 1 (senior, LGD=0.45, Art. 161(1)(e)):        RWA = 61,465.63
    Row 2 (subordinated, LGD=1.00, Art. 161(1)(f)):  RWA = 136,590.29
    Row 3 (dilution_risk, LGD=0.75, Art. 161(1)(g)-CRR): RWA = 102,442.72

    LGD ratios reproduce the RWA ratios exactly (K is linear in LGD at fixed
    PD): 1.00/0.45 = 2.222 = 136,590.29/61,465.63; 0.75/0.45 = 1.667 =
    102,442.72/61,465.63.

    Row 1's LGD (0.45) is IDENTICAL to the CRR unsecured-senior F-IRB fallback
    (``firb_supervisory_lgd_values(pack)["unsecured_senior"]`` = 0.45) — the
    subtype routing changes nothing about row 1's RWA. Its only observable
    effect there is which ``irb_lgd_branch_reason`` is recorded (and, after
    the engine change, suppressing the CalculationError a bare null-LGD row
    would otherwise raise) — see LOAN_P1351_RETAIL_NOSUBTYPE below for the
    contrast this depends on.

References:
    - CRR Art. 161(1)(e)/(f)/(g): F-IRB supervisory LGD for purchased
      receivables (senior 45%, subordinated 100%, dilution risk 75%).
    - CRR Art. 164(1): retail dilution-risk LGD (row 3's SILENT control).
    - src/rwa_calc/engine/irb/transforms.py::apply_firb_lgd — dispatch site.
    - src/rwa_calc/domain/branch_reasons.py::IrbLgdReason — instrumented
      vocabulary (SUPERVISORY_SUBTYPE / UNKNOWN_FALLBACK).
    - scripts/branch_census_baseline.json:
      irb_lgd_branch_reason::supervisory_subtype — the "dead" entry this
      fixture retires. OWNER: P1.341.

Usage:
    uv run python tests/fixtures/p1_351/p1_351.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    LOAN_SCHEMA,
    MODEL_PERMISSIONS_SCHEMA,
    RATINGS_SCHEMA,
)

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

COUNTERPARTY_REF_RETAIL = "CP_P1351_RETAIL"
COUNTERPARTY_REF_CORP = "CP_P1351_CORP"

LOAN_REF_RETAIL_SENIOR = "LOAN_P1351_RETAIL_SENIOR"  # Row 1 — FIRES
LOAN_REF_RETAIL_SUB = "LOAN_P1351_RETAIL_SUB"  # Row 2 — FIRES
LOAN_REF_RETAIL_DILUTION = "LOAN_P1351_RETAIL_DILUTION"  # Row 3 — SILENT (anti-false-positive)
LOAN_REF_CORP_SENIOR = "LOAN_P1351_CORP_SENIOR"  # Row 4 — SILENT (anti-over-reach)
LOAN_REF_RETAIL_NOSUBTYPE = "LOAN_P1351_RETAIL_NOSUBTYPE"  # Row 5 — contrast control

RATING_REF_RETAIL = "RTG_P1351_RETAIL"
RATING_REF_CORP = "RTG_P1351_CORP"

MODEL_ID_RETAIL = "M_P1351_RETAIL_FIRB"
MODEL_ID_CORP = "M_P1351_CORP_FIRB"

# Reporting and maturity dates (CRR window — before the 2027-01-01 B31 cutover)
REPORTING_DATE = date(2026, 12, 31)
VALUE_DATE = date(2026, 1, 1)
MATURITY_DATE = date(2027, 12, 31)  # residual maturity 1.0y from reporting date
RATING_DATE = date(2026, 1, 1)

# Common financial parameters (identical across all five rows so the only
# variable between rows is the subtype/class, not the PD or EAD basis)
PD: float = 0.02  # 2.00% — well above the CRR retail_other PD floor (0.03%)
DRAWN_AMOUNT: float = 100_000.0  # GBP, on-balance-sheet, no CRM

# ---------------------------------------------------------------------------
# Supervisory LGD values (Art. 161(1)(e)/(f)/(g) under CRR)
# ---------------------------------------------------------------------------

LGD_SENIOR: float = 0.45  # Art. 161(1)(e) — identical to the CRR unsecured-senior fallback
LGD_SUB: float = 1.00  # Art. 161(1)(f)
LGD_DILUTION: float = 0.75  # Art. 161(1)(g) under CRR (Basel 3.1 raises this to 1.00)

# ---------------------------------------------------------------------------
# Expected outputs (measured by the Wave 0 premise audit; test-writer reference)
# ---------------------------------------------------------------------------

EXPECTED_RWA_RETAIL_SENIOR: float = 61_465.63
EXPECTED_RWA_RETAIL_SUB: float = 136_590.29
EXPECTED_RWA_RETAIL_DILUTION: float = 102_442.72


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Counterparty:
    """
    P1.351 counterparty row.

    entity_type="individual" -> SA: RETAIL_OTHER, IRB: RETAIL_OTHER (see
    COUNTERPARTY_SCHEMA entity_type notes) with NO dependency on
    ``is_managed_as_retail`` under CRR's threshold-only ``qualifies_as_retail``
    check. entity_type="corporate" is the row-4 anti-over-reach control.
    is_managed_as_retail=False deliberately — see the module docstring trap
    note; True would route the null-LGD row to SA before it ever reaches the
    F-IRB LGD dispatch.
    """

    counterparty_reference: str
    counterparty_name: str
    entity_type: str
    country_code: str
    default_status: bool
    apply_fi_scalar: bool
    is_financial_sector_entity: bool
    is_managed_as_retail: bool
    is_natural_person: bool

    def to_dict(self) -> dict:
        return {
            "counterparty_reference": self.counterparty_reference,
            "counterparty_name": self.counterparty_name,
            "entity_type": self.entity_type,
            "country_code": self.country_code,
            "default_status": self.default_status,
            "apply_fi_scalar": self.apply_fi_scalar,
            "is_financial_sector_entity": self.is_financial_sector_entity,
            "is_managed_as_retail": self.is_managed_as_retail,
            "is_natural_person": self.is_natural_person,
        }


@dataclass(frozen=True)
class _Rating:
    """P1.351 internal F-IRB rating row. PD=2%, no external CQS."""

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
    P1.351 model permission: F-IRB only, no geographic/book restriction.

    approach="foundation_irb" is load-bearing — "advanced_irb" would require
    ``has_modelled_lgd`` (never satisfied by these null-LGD rows) and the row
    would fall through to SA instead of reaching the F-IRB LGD dispatch.
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
class _Loan:
    """
    P1.351 loan row.

    lgd=None: forces F-IRB supervisory LGD selection (own-estimate absent).
    purchased_receivables_subtype: the field under test — None for the
    row-5 contrast control, one of "senior"/"subordinated"/"dilution_risk"
    for the other four.
    """

    loan_reference: str
    counterparty_reference: str
    currency: str
    value_date: date
    maturity_date: date
    drawn_amount: float
    interest: float
    seniority: str
    purchased_receivables_subtype: str | None
    is_sft: bool
    book_code: str

    def to_dict(self) -> dict:
        return {
            "loan_reference": self.loan_reference,
            "counterparty_reference": self.counterparty_reference,
            "currency": self.currency,
            "value_date": self.value_date,
            "maturity_date": self.maturity_date,
            "drawn_amount": self.drawn_amount,
            "interest": self.interest,
            "seniority": self.seniority,
            "purchased_receivables_subtype": self.purchased_receivables_subtype,
            "is_sft": self.is_sft,
            "book_code": self.book_code,
        }


# ---------------------------------------------------------------------------
# Public DataFrame factories
# ---------------------------------------------------------------------------


def create_p1351_counterparty() -> pl.DataFrame:
    """
    Return the two P1.351 counterparty rows as a DataFrame.

    CP_P1351_RETAIL (rows 1/2/3/5): entity_type="individual", not defaulted,
    not managed as a retail pool (default False — see module docstring).
    CP_P1351_CORP (row 4): entity_type="corporate", annual_revenue omitted
    (null) so the engine treats it as a large corporate with no SME
    correlation reduction.
    """
    rows = [
        _Counterparty(
            counterparty_reference=COUNTERPARTY_REF_RETAIL,
            counterparty_name="Purchased Receivables Retail Individual — P1.351",
            entity_type="individual",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
            is_financial_sector_entity=False,
            is_managed_as_retail=False,
            is_natural_person=True,
        ),
        _Counterparty(
            counterparty_reference=COUNTERPARTY_REF_CORP,
            counterparty_name="Purchased Receivables Corp (GB) — P1.351",
            entity_type="corporate",
            country_code="GB",
            default_status=False,
            apply_fi_scalar=False,
            is_financial_sector_entity=False,
            is_managed_as_retail=False,
            is_natural_person=False,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(COUNTERPARTY_SCHEMA))


def create_p1351_rating() -> pl.DataFrame:
    """
    Return the two P1.351 internal rating rows as a DataFrame.

    Both PD=2%, one per counterparty/model pairing.
    """
    rows = [
        _Rating(
            rating_reference=RATING_REF_RETAIL,
            counterparty_reference=COUNTERPARTY_REF_RETAIL,
            rating_type="internal",
            pd=PD,
            model_id=MODEL_ID_RETAIL,
            rating_date=RATING_DATE,
        ),
        _Rating(
            rating_reference=RATING_REF_CORP,
            counterparty_reference=COUNTERPARTY_REF_CORP,
            rating_type="internal",
            pd=PD,
            model_id=MODEL_ID_CORP,
            rating_date=RATING_DATE,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(RATINGS_SCHEMA))


def create_p1351_model_permissions() -> pl.DataFrame:
    """
    Return the two P1.351 model permission rows as a DataFrame.

    MODEL_ID_RETAIL: exposure_class="retail_other", approach="foundation_irb".
    MODEL_ID_CORP: exposure_class="corporate", approach="foundation_irb"
    (row-4 anti-over-reach control — the authorised Art. 161(1)(e) population).
    """
    rows = [
        _ModelPermission(
            model_id=MODEL_ID_RETAIL,
            exposure_class="retail_other",
            approach="foundation_irb",
            country_codes=None,
            excluded_book_codes=None,
        ),
        _ModelPermission(
            model_id=MODEL_ID_CORP,
            exposure_class="corporate",
            approach="foundation_irb",
            country_codes=None,
            excluded_book_codes=None,
        ),
    ]
    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(MODEL_PERMISSIONS_SCHEMA))


def create_p1351_loans() -> pl.DataFrame:
    """
    Return the five P1.351 loan rows as a DataFrame.

    LOAN_P1351_RETAIL_SENIOR (Row 1 — FIRES):
        retail, purchased_receivables_subtype="senior", lgd=null.
        Expected LGD=0.45, RWA=61,465.63.

    LOAN_P1351_RETAIL_SUB (Row 2 — FIRES):
        retail, purchased_receivables_subtype="subordinated", lgd=null.
        Expected LGD=1.00, RWA=136,590.29.

    LOAN_P1351_RETAIL_DILUTION (Row 3 — SILENT, anti-false-positive control):
        retail, purchased_receivables_subtype="dilution_risk", lgd=null.
        Art. 164(1) legislates the retail dilution-risk rate directly; the
        engine already routes this correctly today and must go on doing so.
        Expected LGD=0.75, RWA=102,442.72.

    LOAN_P1351_CORP_SENIOR (Row 4 — SILENT, anti-over-reach control):
        corporate, purchased_receivables_subtype="senior", lgd=null.
        The authorised Art. 161(1)(e) population — must keep reaching
        SUPERVISORY_SUBTYPE with no new warning after the engine change.

    LOAN_P1351_RETAIL_NOSUBTYPE (Row 5 — contrast control, not a guard row):
        retail, purchased_receivables_subtype=null, lgd=null. Reaches
        UNKNOWN_FALLBACK + BR001 today — the "no signal at all" case that
        rows 1-3's clean SUPERVISORY_SUBTYPE contrasts against.
    """
    _common = {
        "currency": "GBP",
        "value_date": VALUE_DATE,
        "maturity_date": MATURITY_DATE,
        "interest": 0.0,
        "is_sft": False,
    }

    rows = [
        _Loan(
            loan_reference=LOAN_REF_RETAIL_SENIOR,
            counterparty_reference=COUNTERPARTY_REF_RETAIL,
            drawn_amount=DRAWN_AMOUNT,
            seniority="senior",
            purchased_receivables_subtype="senior",
            book_code="RETAIL",
            **_common,
        ),
        _Loan(
            loan_reference=LOAN_REF_RETAIL_SUB,
            counterparty_reference=COUNTERPARTY_REF_RETAIL,
            drawn_amount=DRAWN_AMOUNT,
            seniority="subordinated",
            purchased_receivables_subtype="subordinated",
            book_code="RETAIL",
            **_common,
        ),
        _Loan(
            loan_reference=LOAN_REF_RETAIL_DILUTION,
            counterparty_reference=COUNTERPARTY_REF_RETAIL,
            drawn_amount=DRAWN_AMOUNT,
            seniority="senior",
            purchased_receivables_subtype="dilution_risk",
            book_code="RETAIL",
            **_common,
        ),
        _Loan(
            loan_reference=LOAN_REF_CORP_SENIOR,
            counterparty_reference=COUNTERPARTY_REF_CORP,
            drawn_amount=DRAWN_AMOUNT,
            seniority="senior",
            purchased_receivables_subtype="senior",
            book_code="CORP_LENDING",
            **_common,
        ),
        _Loan(
            loan_reference=LOAN_REF_RETAIL_NOSUBTYPE,
            counterparty_reference=COUNTERPARTY_REF_RETAIL,
            drawn_amount=DRAWN_AMOUNT,
            seniority="senior",
            purchased_receivables_subtype=None,
            book_code="RETAIL",
            **_common,
        ),
    ]

    return pl.DataFrame([r.to_dict() for r in rows], schema=dtypes_of(LOAN_SCHEMA))


def create_p1351_facility_mapping() -> pl.DataFrame:
    """Return an empty facility-mapping DataFrame — no facilities in this fixture."""
    return pl.DataFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA))


def create_p1351_lending_mapping() -> pl.DataFrame:
    """Return an empty lending-mapping DataFrame — no multi-debtor structure here."""
    return pl.DataFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA))


# ---------------------------------------------------------------------------
# Save helpers (one parquet per artefact type)
# ---------------------------------------------------------------------------


def save_p1351_fixtures(output_dir: Path | None = None) -> dict[str, Path]:
    """
    Write all P1.351 parquet files and return a mapping of name -> path.

    Args:
        output_dir: Target directory. Defaults to the package directory.

    Returns:
        dict mapping artefact name to saved Path.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    saved: dict[str, Path] = {}

    artefacts: list[tuple[str, pl.DataFrame]] = [
        ("counterparty", create_p1351_counterparty()),
        ("rating", create_p1351_rating()),
        ("model_permission", create_p1351_model_permissions()),
        ("loan", create_p1351_loans()),
        ("facility_mapping", create_p1351_facility_mapping()),
        ("lending_mapping", create_p1351_lending_mapping()),
    ]

    for name, df in artefacts:
        path = output_dir / f"{name}.parquet"
        df.write_parquet(path)
        saved[name] = path

    return saved


def print_summary(saved: dict[str, Path]) -> None:
    """Print a human-readable generation summary."""
    print("P1.351 fixture generation complete")
    print("-" * 80)
    for name, path in saved.items():
        df = pl.read_parquet(path)
        print(f"  {name:<25} {len(df):>3} row(s)  ->  {path}")
    print("-" * 80)
    print("Scenario: CRR F-IRB retail purchased receivables LGD guard (Art. 161(1)(e)/(f)/(g))")
    print(f"  Reporting date: {REPORTING_DATE},  Maturity: {MATURITY_DATE}")
    print(f"  PD = {PD:.2%} on all five rows, EAD = {DRAWN_AMOUNT:,.0f} GBP")
    print("")
    rows_data = [
        (
            LOAN_REF_RETAIL_SENIOR,
            "retail",
            "senior",
            "FIRES",
            LGD_SENIOR,
            EXPECTED_RWA_RETAIL_SENIOR,
        ),
        (LOAN_REF_RETAIL_SUB, "retail", "subordinated", "FIRES", LGD_SUB, EXPECTED_RWA_RETAIL_SUB),
        (
            LOAN_REF_RETAIL_DILUTION,
            "retail",
            "dilution_risk",
            "SILENT (anti-false-positive)",
            LGD_DILUTION,
            EXPECTED_RWA_RETAIL_DILUTION,
        ),
        (LOAN_REF_CORP_SENIOR, "corporate", "senior", "SILENT (anti-over-reach)", LGD_SENIOR, None),
        (LOAN_REF_RETAIL_NOSUBTYPE, "retail", None, "control (UNKNOWN_FALLBACK/BR001)", None, None),
    ]
    for ref, cls, subtype, expectation, lgd, rwa in rows_data:
        lgd_str = f"{lgd:.0%}" if lgd is not None else "n/a"
        rwa_str = f"{rwa:,.2f}" if rwa is not None else "n/a"
        print(
            f"  {ref:<28}  {cls:<10}  {str(subtype):<15}  {expectation:<35}  LGD={lgd_str:>5}  RWA={rwa_str}"
        )
    print("")
    print("  Retires scripts/branch_census_baseline.json dead entry:")
    print("    irb_lgd_branch_reason::supervisory_subtype (OWNER: P1.341)")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1351_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
