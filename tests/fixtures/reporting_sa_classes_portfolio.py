"""
SA quasi-sovereign reporting portfolio — the C 07.00 / OF 07.00 sheet axis.

Pipeline position:
    build_reporting_sa_classes_bundle() -> RawDataBundle -> PipelineOrchestrator
        -> AggregatedResultBundle -> COREPGenerator / Pillar3Generator

Why a FOURTH portfolio (rather than extending ``reporting_portfolio.py``):
C 07.00 is published per obligor class — the publisher's z-axis is Art. 112(1)(a)
to (q) in order — and a rule scoped to a sheet we never emit is not evaluated at
all. The three existing portfolios between them populate only six of the sixteen
sheet codes (central governments, institutions, corporates, retail, immovable
property, other items), so **57 CRR and 15 Basel 3.1 published rules had no
coordinate to run at**: every rule the EBA and the BoE wrote over the regional
government, public sector entity, multilateral development bank, international
organisation and covered bond sheets. That is the single largest addressable
coverage hole in the estate, and it is a hole of missing DATA, not missing code.

Adding these rows to the rich portfolio would move all 26 of its committed
goldens at once. This portfolio is separate and has its own golden directory, so
the existing gates keep their meaning — same reasoning, same shape, as
``reporting_ccr_portfolio.py`` and ``reporting_offbs_portfolio.py``.

Composition — every row exists to emit one named C 07.00 / OF 07.00 sheet, and
the pairs exist to exercise both limbs of a class whose treatment forks:

    ref              | entity_type      | basis                        | CRR  | B3.1
    -----------------|------------------|------------------------------|------|------
    LN_RGLA_UK       | rgla_sovereign   | Art. 115(2) sovereign-equiv. |   0% |   0%
    LN_RGLA_FOREIGN  | rgla_institution | Art. 115(1) as institution   |  50% |  50%
    LN_PSE           | pse_institution  | Art. 116(2) rated PSE        |  50% |  50%
    LN_MDB_RATED     | mdb              | Art. 117(1) as institution   |  50% |  30%
    LN_MDB_NAMED     | mdb_named        | Art. 117(2) listed MDB       |   0% |   0%
    LN_INTL_ORG      | international_org| Art. 118 listed org          |   0% |   0%
    LN_COVERED_BOND  | covered_bond     | Art. 129(4) by issuer CQS    |  10% |  10%
    LN_CORP_ANCHOR   | corporate        | Art. 122(1) — the anchor     | 100% |  75%

    -> C 07.00 / OF 07.00 sheets  rgla | pse | mdb | international_organisation
                                  covered_bond | corporate

``LN_MDB_RATED`` is the load-bearing regime-divergent row: CRR Art. 117(1) sends
an unlisted MDB to the Art. 120 institution table (CQS 2 -> 50%), while PS1/26
gives MDBs their own ECRA schedule (CQS 2 -> 30%). It is the only row here whose
risk weight moves between the two regimes, so a regression that collapsed the
MDB class onto the institution ladder under Basel 3.1 would show up as a single
changed cell rather than as silence.

The 0% rows (``LN_RGLA_UK``, ``LN_MDB_NAMED``, ``LN_INTL_ORG``) are deliberate,
not an oversight: Art. 117(2) and Art. 118 are unconditional 0% assignments, so
there is no parameterisation under which those classes carry a risk weight. They
still emit their sheet and still carry a non-zero EXPOSURE value, which is what
the exposure-value and CCF identities on C 07.00 are written over. A rule whose
operands are all zero is reported VACUOUS by the evaluator, which is honest —
and distinct from the NOT_EVALUATED it returned before this portfolio existed.

``LN_CORP_ANCHOR`` is not decoration. Several published rules foot a class sheet
against the C 02.00 / OF 02.00 total, and an estate whose entire standardised
book is 0%-weighted makes every one of those identities trivially true.

Deliberately OUT of scope:
- Art. 112(1)(k) items associated with particularly high risk, Art. 112(1)(n)
  short-term credit assessments, Art. 112(1)(o) collective investment
  undertakings. Their sheet codes resolve to NO bundle key at all
  (``validations/scope.py``), so no fixture row can emit them — the gap is in
  the estate's class taxonomy, not in the data.
- Art. 112(1)(p) equity. ``c07.py::c07_population`` admits the standardised book
  by ``reporting_approach_origin == "standardised"``, and the equity calculator
  seals ``equity``, so an equity exposure cannot reach C 07.00 however it is
  booked. Verified end-to-end: a loan to an ``entity_type="equity"`` obligor
  routes to the equity calculator too. This is an estate gap, not a data one.
- Off-balance-sheet items and CRM — ``reporting_offbs_portfolio.py`` owns the
  CCF-bucket axis and the rich portfolio owns the CRM columns. Every row here is
  drawn and unmitigated so a mis-weighted class is visible in one cell.

References:
- CRR Art. 115 (RGLA), 116 (PSE), 117 (MDB), 118 (international organisations),
  Art. 129(4) (covered bonds), Art. 122(1) (corporates)
- PRA PS1/26 Art. 115-118, Art. 129: the Basel 3.1 counterparts
- COREP Annex II, C 07.00: the Art. 112(1)(a)-(q) sheet (z-axis) breakdown
- docs/specifications/crr/sa-risk-weights.md
"""

from __future__ import annotations

from datetime import date

import polars as pl

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, LOAN_SCHEMA, RATINGS_SCHEMA
from tests.fixtures.raw_bundle import make_raw_bundle

# ---------------------------------------------------------------------------
# Scenario constants — the single source of truth for test assertions.
# ---------------------------------------------------------------------------

CP_RGLA_UK: str = "SAC-CP-RGLA-UK"  # UK local authority   -> rgla
CP_RGLA_FOREIGN: str = "SAC-CP-RGLA-FGN"  # foreign region  -> rgla
CP_PSE: str = "SAC-CP-PSE"  # public sector entity        -> pse
CP_MDB_RATED: str = "SAC-CP-MDB-RATED"  # unlisted MDB     -> mdb
CP_MDB_NAMED: str = "SAC-CP-MDB-NAMED"  # Art. 117(2) MDB  -> mdb
CP_INTL_ORG: str = "SAC-CP-INTL-ORG"  # Art. 118 org       -> international_organisation
CP_COVERED_BOND: str = "SAC-CP-COVBOND"  # covered bond    -> covered_bond
CP_CORP_ANCHOR: str = "SAC-CP-CORP"  # corporate anchor    -> corporate

LN_RGLA_UK: str = "SAC-LN-RGLA-UK"
LN_RGLA_FOREIGN: str = "SAC-LN-RGLA-FGN"
LN_PSE: str = "SAC-LN-PSE"
LN_MDB_RATED: str = "SAC-LN-MDB-RATED"
LN_MDB_NAMED: str = "SAC-LN-MDB-NAMED"
LN_INTL_ORG: str = "SAC-LN-INTL-ORG"
LN_COVERED_BOND: str = "SAC-LN-COVBOND"
LN_CORP_ANCHOR: str = "SAC-LN-CORP"

#: Drawn amounts, in GBP. Distinct per row so a mis-classified exposure is
#: identifiable from a single C 07.00 cell value without a reverse lookup.
DRAWN_RGLA_UK: float = 3_000_000.0
DRAWN_RGLA_FOREIGN: float = 3_500_000.0
DRAWN_PSE: float = 2_500_000.0
DRAWN_MDB_RATED: float = 4_000_000.0
DRAWN_MDB_NAMED: float = 4_500_000.0
DRAWN_INTL_ORG: float = 1_500_000.0
DRAWN_COVERED_BOND: float = 6_000_000.0
DRAWN_CORP_ANCHOR: float = 9_000_000.0

_VALUE_DATE: date = date(2020, 1, 1)
_MATURITY: date = date(2031, 12, 31)  # > both reporting dates (CRR 2025, B31 2027)

#: Every exposure and the ``reporting_class_origin`` sheet it must land on.
#: Consumed by the fixture-integrity test — if a row stops reaching its sheet the
#: goldens quietly stop covering that class, and the published rules written over
#: it go back to NOT_EVALUATED without any gate turning red.
SA_CLASS_EXPECTED_SHEET: dict[str, str] = {
    LN_RGLA_UK: "rgla",
    LN_RGLA_FOREIGN: "rgla",
    LN_PSE: "pse",
    LN_MDB_RATED: "mdb",
    LN_MDB_NAMED: "mdb",
    LN_INTL_ORG: "international_organisation",
    LN_COVERED_BOND: "covered_bond",
    LN_CORP_ANCHOR: "corporate",
}

#: Risk weight each row must resolve to, per regime. ``LN_MDB_RATED`` is the one
#: row that moves (Art. 117(1) institution table vs the PS1/26 MDB schedule).
SA_CLASS_EXPECTED_RW: dict[str, tuple[float, float]] = {
    # exposure_reference:   (CRR rw, Basel 3.1 rw)
    LN_RGLA_UK: (0.0, 0.0),
    LN_RGLA_FOREIGN: (0.5, 0.5),
    LN_PSE: (0.5, 0.5),
    LN_MDB_RATED: (0.5, 0.3),
    LN_MDB_NAMED: (0.0, 0.0),
    LN_INTL_ORG: (0.0, 0.0),
    LN_COVERED_BOND: (0.1, 0.1),
}


# ---------------------------------------------------------------------------
# Main public entry point
# ---------------------------------------------------------------------------


def build_reporting_sa_classes_bundle() -> RawDataBundle:
    """Assemble the SA quasi-sovereign reporting portfolio as a sealed bundle.

    Sealed against the loader edge contracts by ``make_raw_bundle``, so it is
    shape-identical to a parquet-loaded production bundle. Run it through
    ``PipelineOrchestrator().run_with_data`` under either regime with
    ``PermissionMode.STANDARDISED`` — C 07.00 / OF 07.00 is the SA template and
    every obligor here carries an external rating or none, never an internal PD.
    """
    return make_raw_bundle(
        counterparties=_counterparties(),
        loans=_loans(),
        ratings=_ratings(),
    )


# ---------------------------------------------------------------------------
# Table builders (private)
# ---------------------------------------------------------------------------


def _counterparties() -> pl.DataFrame:
    """One obligor per Art. 112(1) sheet this portfolio exists to emit.

    ``LN_RGLA_UK`` is GB-domiciled and lends in GBP so the Art. 115(2) /
    PRA sovereign-equivalence limb fires (UK local authorities take the UK
    central government's 0%); ``LN_RGLA_FOREIGN`` is deliberately non-UK so the
    Art. 115(1) "risk weighted as institutions" default limb is the one under
    test. The two limbs share a sheet, which is the point: the sheet must be
    emitted whichever limb a firm's book happens to hit.
    """
    rows: list[dict] = [
        {
            "counterparty_reference": CP_RGLA_UK,
            "entity_type": "rgla_sovereign",
            "country_code": "GB",
        },
        {
            "counterparty_reference": CP_RGLA_FOREIGN,
            "entity_type": "rgla_institution",
            "country_code": "US",
        },
        {"counterparty_reference": CP_PSE, "entity_type": "pse_institution", "country_code": "GB"},
        {"counterparty_reference": CP_MDB_RATED, "entity_type": "mdb", "country_code": "GB"},
        {"counterparty_reference": CP_MDB_NAMED, "entity_type": "mdb_named", "country_code": "GB"},
        {
            "counterparty_reference": CP_INTL_ORG,
            "entity_type": "international_org",
            "country_code": "GB",
        },
        {
            "counterparty_reference": CP_COVERED_BOND,
            "entity_type": "covered_bond",
            "country_code": "GB",
        },
        {
            "counterparty_reference": CP_CORP_ANCHOR,
            "entity_type": "corporate",
            "country_code": "GB",
            # Above the SME ceiling, so no supporting factor perturbs the anchor
            # and the C 02.00 footing stays a plain EAD x RW product.
            "annual_revenue": 400_000_000.0,
        },
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA))


def _ratings() -> pl.DataFrame:
    """External ECAI ratings only — no internal PD, so every row routes SA.

    ``CP_MDB_NAMED`` and ``CP_INTL_ORG`` are deliberately UNRATED: Art. 117(2)
    and Art. 118 assign 0% by identity, not by credit assessment, so attaching a
    CQS to either would misrepresent the basis on which the weight is given.
    """
    rows: list[dict] = [
        # Art. 115(1) -> Art. 120 Table 3: CQS 2 institution weight, 50%.
        _external(CP_RGLA_FOREIGN, cqs=2),
        # Art. 116(2): a PSE with its own ECAI assessment takes the institution
        # ladder, CQS 2 -> 50%.
        _external(CP_PSE, cqs=2),
        # Art. 117(1): an MDB outside the Art. 117(2) list is treated as an
        # institution under CRR (CQS 2 -> 50%); PS1/26 gives MDBs their own
        # ECRA schedule (CQS 2 -> 30%). The regime-divergent row.
        _external(CP_MDB_RATED, cqs=2),
        # Art. 129(4): the covered bond ladder is indexed on the CQS of the
        # ISSUING institution, CQS 1 -> 10%.
        _external(CP_COVERED_BOND, cqs=1),
        # Art. 122(1): CQS 3 corporate -> 100% (CRR). The anchor.
        _external(CP_CORP_ANCHOR, cqs=3),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(RATINGS_SCHEMA))


def _loans() -> pl.DataFrame:
    """One drawn, unmitigated exposure per class. EAD = drawn_amount.

    Drawn and uncollateralised on purpose: this portfolio's job is the SHEET
    axis, so every C 07.00 row must reduce to EAD x RW. The CCF columns belong
    to ``reporting_offbs_portfolio.py`` and the CRM columns to the rich one;
    duplicating either here would make a mis-weighted class hide behind a
    conversion or a substitution.
    """
    rows: list[dict] = [
        _loan(LN_RGLA_UK, CP_RGLA_UK, DRAWN_RGLA_UK),
        _loan(LN_RGLA_FOREIGN, CP_RGLA_FOREIGN, DRAWN_RGLA_FOREIGN),
        _loan(LN_PSE, CP_PSE, DRAWN_PSE),
        _loan(LN_MDB_RATED, CP_MDB_RATED, DRAWN_MDB_RATED),
        _loan(LN_MDB_NAMED, CP_MDB_NAMED, DRAWN_MDB_NAMED),
        _loan(LN_INTL_ORG, CP_INTL_ORG, DRAWN_INTL_ORG),
        _loan(LN_COVERED_BOND, CP_COVERED_BOND, DRAWN_COVERED_BOND),
        _loan(LN_CORP_ANCHOR, CP_CORP_ANCHOR, DRAWN_CORP_ANCHOR),
    ]
    return pl.DataFrame(rows, schema_overrides=dtypes_of(LOAN_SCHEMA))


# ---------------------------------------------------------------------------
# Row helpers (private)
# ---------------------------------------------------------------------------


def _loan(loan_reference: str, counterparty_reference: str, drawn_amount: float) -> dict:
    """One fully-drawn senior GBP loan (unset optional columns take schema defaults)."""
    return {
        "loan_reference": loan_reference,
        "counterparty_reference": counterparty_reference,
        "product_type": "term_loan",
        "drawn_amount": drawn_amount,
        "currency": "GBP",
        "value_date": _VALUE_DATE,
        "maturity_date": _MATURITY,
        "seniority": "senior",
    }


def _external(counterparty_reference: str, *, cqs: int) -> dict:
    """External ECAI rating row (CQS only — no internal PD, so SA routing)."""
    return {
        "rating_reference": f"SAC-RTG-{counterparty_reference}",
        "counterparty_reference": counterparty_reference,
        "rating_type": "external",
        "rating_agency": "TEST_AGENCY",
        "cqs": cqs,
        "rating_date": _VALUE_DATE,
    }
