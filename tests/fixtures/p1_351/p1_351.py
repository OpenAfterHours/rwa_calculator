"""
Generate P1.351 fixtures: retail F-IRB rows priced on corporate supervisory LGDs.

Pipeline position:
    fixture-builder output -> test-writer -> pipeline exit
    (contracts/validation.py::validate_branch_reasons, IRB009)

Key responsibilities:
- Reach the ``IrbLgdReason.SUPERVISORY_SUBTYPE`` branch in
  ``engine/irb/transforms.py::apply_firb_lgd`` on a RETAIL row. The branch census
  (``scripts/branch_census_baseline.json``, owner P1.341) still banks it ``dead``:
  the census walks a fixed run matrix, not ``tests/fixtures/``, and every
  portfolio in that matrix leaves ``purchased_receivables_subtype`` null.
- Provide the rows that tell the IRB009 warning (a retail IRB row priced on an
  Art. 161(1) corporate supervisory LGD) apart from both an over-broad
  implementation (catches every subtype) and an over-reaching one (catches
  every class):

    1. retail + "senior" + null lgd        -> FIRES  (LOAN_P1351_RETAIL_SENIOR)
    2. retail + "subordinated" + null lgd   -> FIRES  (LOAN_P1351_RETAIL_SUB)
    3. retail + "dilution_risk" + null lgd  -> SILENT (LOAN_P1351_RETAIL_DILUTION)
       Anti-false-positive control: Art. 164(1) legislates a retail dilution-risk
       rate and the engine already handles it correctly. A guard that keys on
       the ``supervisory_subtype`` branch alone (every subtype) fires here.
    4. corporate + "senior" + null lgd      -> SILENT (LOAN_P1351_CORP_SENIOR)
       Anti-over-reach control: the authorised Art. 161(1)(e) population.
    5. retail + no subtype + null lgd       -> FIRES  (LOAN_P1351_RETAIL_NOSUBTYPE)
       Reaches ``IrbLgdReason.SUPERVISORY_FIRB`` — the Art. 161(1)(a) seniority
       fallback — NOT ``UNKNOWN_FALLBACK``, so it raises no BR001.
       ``is_firb_cleared`` in ``apply_firb_lgd`` fires for any F-IRB row with a
       null LGD before the ``otherwise`` clause is reached. Art. 161(1)(a) is a
       corporates/institutions rate exactly as (e)/(f) are, so a retail row
       priced on it is just as unauthorised: this row is why IRB009 keys on the
       branch reason and not on the subtype alone.

Case-variant leg (``respell_p1351_subtypes``, in memory only — no parquet):
    The same rows with each subtype respelled (``Senior``, ``Subordinated``,
    ``Dilution_Risk``; the corporate row ``Senior``) plus one corporate row on an
    out-of-vocabulary ``junior``. The input gate's DQ006 lower-cases both sides
    before checking, so it accepts every respelling and names only ``junior``;
    the engine dispatch in ``engine/irb/transforms.py::apply_firb_lgd`` matches
    exactly, so every respelled row — ``Dilution_Risk`` included — is priced on
    the Art. 161(1)(a)/(b) seniority fallback. Nothing else names those rows, so
    IRB009 must fire on every retail row whose subtype is not exactly
    ``dilution_risk``: it is the only finding that does.

Route (measured — reachable in BOTH regimes):
    The engine accepts a ``retail_other`` / ``foundation_irb`` model permission
    (``engine/classify/permissions.py`` takes any class/approach pair) and then
    clears whatever LGD the firm supplied (``engine/classify/approach.py``,
    F-IRB LGD clearing). Neither is lawful — CRR Art. 151(7) requires own LGD
    estimates for retail and PS1/26 Art. 147A(1)(g) allows retail only SA or
    A-IRB — and that root cause is a separate plan item. Under CRR the frames
    below reach it as they stand. Under Basel 3.1 two input deltas are needed
    (``create_p1351_b31_counterparty`` / ``create_p1351_b31_loans``): the retail
    obligor managed as retail (Art. 147(5)(c), or its IRB class becomes
    CORPORATE) and an own LGD estimate on each retail loan (a managed-as-retail
    row without one is routed to SA before the F-IRB branch). The firm's 0.30 is
    then discarded and the rows take the Basel 3.1 Art. 161(1) rates.

Two traps a naive CRR retail-F-IRB fixture falls into (both avoided here):
    - ``approach="advanced_irb"`` in the model_permission row sends the row to
      SA (RW 0.75) instead of F-IRB — ``airb_expr`` requires
      ``has_modelled_lgd``, which a null-LGD row can never satisfy. This
      fixture uses ``approach="foundation_irb"``.
    - Setting ``is_managed_as_retail=True`` on the counterparty routes the row
      through ``_build_approach_expr``'s branch 1 (managed-as-retail without
      LGD -> SA, ``engine/classify/approach.py:285-289``) BEFORE it
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
    RWA = K x 12.5 x 1.06 x EAD   (no maturity adjustment for retail)

    Row 1 (senior, LGD=0.45, Art. 161(1)(e)):        RWA = 61,465.63
    Row 2 (subordinated, LGD=1.00, Art. 161(1)(f)):  RWA = 136,590.29
    Row 3 (dilution_risk, LGD=0.75, Art. 161(1)(g)-CRR): RWA = 169,194.90
        — NOT on the retail curve: Art. 157(1) prices dilution risk of purchased
        retail receivables "in accordance with the formula set out in Article
        153(1)", i.e. the corporate correlation R = 0.12 f + 0.24 (1 - f),
        f = (1-exp(-50xPD))/(1-exp(-50)) -> 0.164146, with the Art. 153(1)
        maturity adjustment (= 1 at M = 1). Review TR-03; the retail-curve
        figure this fixture used to carry was 102,442.72.

    LGD ratios reproduce the RWA ratios exactly for rows 1 and 2 (K is linear in
    LGD at fixed PD and correlation): 1.00/0.45 = 2.222 = 136,590.29/61,465.63.

    Row 1's LGD (0.45) is IDENTICAL to the CRR unsecured-senior F-IRB fallback
    (``firb_supervisory_lgd_values(pack)["unsecured_senior"]`` = 0.45) — the
    subtype routing changes nothing about row 1's RWA. Its only observable
    effect there is which ``irb_lgd_branch_reason`` is recorded — see
    LOAN_P1351_RETAIL_NOSUBTYPE, which takes the same 0.45 on
    ``supervisory_firb``.

References:
    - CRR Art. 161(1)(e)/(f)/(g): F-IRB supervisory LGD for purchased
      receivables (senior 45%, subordinated 100%, dilution risk 75%).
    - CRR Art. 164(1): retail dilution-risk LGD (row 3's SILENT control).
    - CRR Art. 151(7); PS1/26 Art. 147A(1)(g), Art. 164(1): retail IRB takes
      own LGD estimates; Art. 161(1) is a corporates/institutions article.
    - src/rwa_calc/engine/irb/transforms.py::apply_firb_lgd — dispatch site.
    - src/rwa_calc/domain/branch_reasons.py::IrbLgdReason — instrumented
      vocabulary (SUPERVISORY_SUBTYPE / UNKNOWN_FALLBACK).
    - scripts/branch_census_baseline.json:
      irb_lgd_branch_reason::supervisory_subtype — banked "dead"; this fixture
      is outside the census matrix, so it does not retire it. OWNER: P1.341.

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
LOAN_REF_RETAIL_NOSUBTYPE = "LOAN_P1351_RETAIL_NOSUBTYPE"  # Row 5 — FIRES (supervisory_firb)
# Case-variant leg only: a corporate row on an out-of-vocabulary subtype, the
# live-gate control that shows DQ006 runs on this path at all.
LOAN_REF_CORP_JUNIOR = "LOAN_P1351_CORP_JUNIOR"

#: Case-variant leg: each subtype-bearing loan respelled. DQ006 accepts every one
#: of these (it lower-cases both sides); the engine dispatch matches none of them.
CASE_VARIANT_SUBTYPES: dict[str, str] = {
    LOAN_REF_RETAIL_SENIOR: "Senior",
    LOAN_REF_RETAIL_SUB: "Subordinated",
    LOAN_REF_RETAIL_DILUTION: "Dilution_Risk",
    LOAN_REF_CORP_SENIOR: "Senior",
}
OUT_OF_VOCABULARY_SUBTYPE = "junior"

RATING_REF_RETAIL = "RTG_P1351_RETAIL"
RATING_REF_CORP = "RTG_P1351_CORP"

MODEL_ID_RETAIL = "M_P1351_RETAIL_FIRB"
MODEL_ID_CORP = "M_P1351_CORP_FIRB"

# Reporting and maturity dates (CRR window — before the 2027-01-01 B31 cutover)
REPORTING_DATE = date(2026, 12, 31)
B31_REPORTING_DATE = date(2027, 6, 30)  # Basel 3.1 leg (create_p1351_b31_*)
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

# The firm's own retail LGD estimate on the Basel 3.1 leg. The engine discards it
# on the F-IRB route (the root-cause defect), so no expected value below uses it.
RETAIL_FIRM_LGD: float = 0.30

# ---------------------------------------------------------------------------
# Expected outputs (measured by the Wave 0 premise audit; test-writer reference)
# ---------------------------------------------------------------------------

EXPECTED_RWA_RETAIL_SENIOR: float = 61_465.63
EXPECTED_RWA_RETAIL_SUB: float = 136_590.29
EXPECTED_RWA_RETAIL_DILUTION: float = 169_194.90  # Art. 157(1) -> Art. 153(1) formula (TR-03)


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
        Expected LGD=0.75, RWA=169,194.90 (Art. 157(1): the Art. 153(1) formula).

    LOAN_P1351_CORP_SENIOR (Row 4 — SILENT, anti-over-reach control):
        corporate, purchased_receivables_subtype="senior", lgd=null.
        The authorised Art. 161(1)(e) population — must keep reaching
        SUPERVISORY_SUBTYPE with no new warning after the engine change.

    LOAN_P1351_RETAIL_NOSUBTYPE (Row 5 — FIRES):
        retail, purchased_receivables_subtype=null, lgd=null. Reaches
        SUPERVISORY_FIRB (the Art. 161(1)(a) seniority fallback, LGD 0.45) with
        no BR001 — a corporate rate on a retail row, reached without a subtype.
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


def create_p1351_b31_counterparty() -> pl.DataFrame:
    """
    Return the P1.351 counterparties for the Basel 3.1 leg.

    Identical to :func:`create_p1351_counterparty` except that
    CP_P1351_RETAIL is managed as retail. Under Basel 3.1 a natural person with
    ``is_managed_as_retail`` False fails PS1/26 Art. 147(5)(c) and its IRB
    class becomes CORPORATE, so the retail population this item is about
    would not exist.
    """
    is_retail = pl.col("counterparty_reference") == COUNTERPARTY_REF_RETAIL
    return create_p1351_counterparty().with_columns(
        pl.when(is_retail)
        .then(pl.lit(True))
        .otherwise(pl.col("is_managed_as_retail"))
        .alias("is_managed_as_retail")
    )


def create_p1351_b31_loans() -> pl.DataFrame:
    """
    Return the P1.351 loans for the Basel 3.1 leg.

    Identical to :func:`create_p1351_loans` except that the four retail loans
    carry the firm's own LGD estimate (``RETAIL_FIRM_LGD``). A managed-as-retail
    row with no LGD is routed to SA before the F-IRB branch; with one, the
    retail F-IRB model permission routes it to F-IRB and the LGD is cleared, so
    the row is priced on the Basel 3.1 Art. 161(1) corporate rates.
    """
    is_retail = pl.col("counterparty_reference") == COUNTERPARTY_REF_RETAIL
    return create_p1351_loans().with_columns(
        pl.when(is_retail)
        .then(pl.lit(RETAIL_FIRM_LGD))
        .otherwise(pl.col("lgd"))
        .cast(pl.Float64)
        .alias("lgd")
    )


def respell_p1351_subtypes(loans: pl.DataFrame) -> pl.DataFrame:
    """
    Return ``loans`` with the subtypes respelled, plus one out-of-vocabulary row.

    Applies to either regime's loan frame (:func:`create_p1351_loans` or
    :func:`create_p1351_b31_loans`). Each loan in ``CASE_VARIANT_SUBTYPES`` takes
    its respelled subtype; the no-subtype row stays null. A copy of the corporate
    row is appended as ``LOAN_P1351_CORP_JUNIOR`` with subtype ``junior``: the
    one spelling DQ006 rejects, so a test can show the gate ran and still let
    every respelling through.
    """
    respelled = loans.with_columns(
        pl.col("loan_reference")
        .replace_strict(CASE_VARIANT_SUBTYPES, default=pl.col("purchased_receivables_subtype"))
        .alias("purchased_receivables_subtype")
    )
    junior = loans.filter(pl.col("loan_reference") == LOAN_REF_CORP_SENIOR).with_columns(
        pl.lit(LOAN_REF_CORP_JUNIOR).alias("loan_reference"),
        pl.lit(OUT_OF_VOCABULARY_SUBTYPE).alias("purchased_receivables_subtype"),
    )
    return pl.concat([respelled, junior])


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
        (LOAN_REF_RETAIL_NOSUBTYPE, "retail", None, "FIRES (supervisory_firb)", LGD_SENIOR, None),
    ]
    for ref, cls, subtype, expectation, lgd, rwa in rows_data:
        lgd_str = f"{lgd:.0%}" if lgd is not None else "n/a"
        rwa_str = f"{rwa:,.2f}" if rwa is not None else "n/a"
        print(
            f"  {ref:<28}  {cls:<10}  {str(subtype):<15}  {expectation:<35}  LGD={lgd_str:>5}  RWA={rwa_str}"
        )
    print("")
    print("  Outside the branch-census matrix: does not retire the dead entry")
    print("    irb_lgd_branch_reason::supervisory_subtype (OWNER: P1.341)")


def main() -> None:
    """Entry point for standalone generation."""
    saved = save_p1351_fixtures()
    print_summary(saved)


if __name__ == "__main__":
    main()
