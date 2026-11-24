"""
P1.259 — PS1/26 Art. 138(1)(g): implicit-support assessments are not used for institutions.

Pipeline position:
    Loader -> HierarchyResolver.resolve (Art. 138 selection, short-term ECAI
    override) -> Classifier

What this pins:
    PS1/26 Art. 138(1)(g) (ps126app1.pdf printed pp. 70-71, read verbatim):
    "an institution shall not use a credit assessment that incorporates
    assumptions of implicit government support for the purposes of assigning a
    risk weight to an exposure to an institution, unless the respective credit
    assessment applies to an institution owned by or set up and sponsored by
    central governments, regional governments or local authorities."

    UK CRR Art. 138 has limbs (a)-(f) only, so the suppression is Basel 3.1
    only and every CRR expectation below is the unsuppressed Art. 138 result.

    The limb removes an assessment from the set Art. 138(1)(d)-(f) choose from,
    so it acts BEFORE the best / second-best selection — a post-selection null
    (the Art. 139(2B) sibling pattern) would give a different answer, and the
    ordering cases below tell the two apart. It covers the dedicated short-term
    ECAI assessments too ("In using a credit assessment ..." governs every
    limb), which never pass through ``ratings.py``.

    It also acts BEFORE the per-agency "most recent assessment" reduction that
    precedes the Art. 138 ranking. The canonical production shape is ONE agency
    publishing two concurrent long-term assessments of a bank — a
    support-uplifted rating and a stand-alone one (Moody's LT vs BCA, S&P ICR
    vs SACP). (g) bars the first; the second is still a credit assessment the
    firm may use. Reducing to the latest row first would let the flagged row
    shadow the clean one and then remove it, leaving the bank unrated
    (``_CP_SAME_AGENCY``). Consequence, by design: the agency's latest
    UNFLAGGED assessment is used, so a ratings feed must not carry superseded
    assessments.

DQ015 (unsolicited assessment used, Art. 138 chapeau) counts the rows the run
reads after the filter: a disregarded unsolicited assessment is never used, so
under Basel 3.1 it is not counted (``_CP_UNSOLICITED``).

Assessments in scope: external (ECAI) credit assessments only. Art. 138 governs
"credit assessments" by nominated ECAIs ((d)-(f) say so in terms); a firm's own
INTERNAL rating is not one, so a flag set on an internal row must not remove
the IRB PD / model id it carries (nor let the parent's internal rating be
inherited in its place).

Population (an "exposure to an institution"):
    entity types the run's pack maps to the ``institution`` SA class — bank /
    institution, Art. 119(5) financial institutions "treated as exposures to
    institutions", and a qualifying CCP, whose other exposures PS1/26 Art.
    107(2)(a) treats "as exposures to an institution". A NON-qualifying CCP is
    treated "as exposures to a corporate" (Art. 107(2)(b)) and is out of scope.

Every value asserted is a CQS (the hierarchy's output); the risk weights the
CQS produce are pinned end to end in
``tests/acceptance/basel31/test_p1_259_implicit_support_ratings.py``.

References:
- PS1/26 Art. 138(1)(d)-(g); Art. 107(2); Art. 119(5)
- CRR Art. 138(1)(a)-(f): no implicit-support limb
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.engine.hierarchy import HierarchyResolver
from tests.fixtures.raw_bundle import make_raw_bundle

_REPORTING_DATE = date(2027, 1, 31)
_VALUE_DATE = date(2027, 1, 1)
_SHORT_MATURITY = date(2027, 3, 15)  # 73 days original maturity
_LONG_MATURITY = date(2030, 1, 1)
_RATING_DATE = date(2027, 1, 2)

# --- counterparties (one loan each, loan reference = "LN_" + counterparty) ---
_CP_MULTI = "CP259_BANK_MULTI"  # CQS1 flagged, CQS1 flagged, CQS3 clean
_CP_ORDER = "CP259_BANK_ORDER"  # CQS1 clean, CQS2 flagged, CQS3 clean
_CP_SOLE = "CP259_BANK_SOLE"  # single CQS2 flagged; entity_type "Bank" (mixed case)
_CP_GOV = "CP259_BANK_GOV"  # as MULTI, but government-owned / sponsored
_CP_CORP = "CP259_CORP"  # corporate, single CQS1 flagged
_CP_NULL = "CP259_BANK_NULL"  # single CQS1, flag null (not reviewed)
_CP_FALSE = "CP259_BANK_FALSE"  # single CQS1, flag False (reviewed: stand-alone)
_CP_QCCP = "CP259_QCCP"  # qualifying CCP, single CQS1 flagged
_CP_NQCCP = "CP259_NQCCP"  # non-qualifying CCP, single CQS1 flagged
_CP_FI = "CP259_FIN_INST"  # financial_institution, single CQS2 flagged
_CP_ST_DOWN = "CP259_BANK_ST_DOWN"  # long CQS1 clean + short-term CQS3 flagged
_CP_ST_UP = "CP259_BANK_ST_UP"  # long CQS4 clean + short-term CQS1 flagged
_CP_INTERNAL = "CP259_BANK_INTERNAL"  # INTERNAL rating flagged True + clean external CQS2
_CP_INTERNAL_PARENT = "CP259_BANK_INTERNAL_PARENT"  # its parent: own internal rating
_CP_SAME_AGENCY = "CP259_BANK_SAME_AGENCY"  # MOODYS: newer CQS1 flagged, older CQS3 clean
_CP_UNSOLICITED = "CP259_BANK_UNSOLICITED"  # single CQS2 flagged, unsolicited

_INTERNAL_PD = 0.004
_INTERNAL_MODEL = "M259_INST_FIRB"
_PARENT_PD = 0.0008
_PARENT_MODEL = "M259_PARENT"

#: The same-agency pair: the support-uplifted row is the NEWER one, so a
#: per-agency "latest" reduction taken before (g) would select it and then drop it.
_SAME_AGENCY_FLAGGED_DATE = _RATING_DATE
_SAME_AGENCY_CLEAN_DATE = date(2026, 12, 1)
_DQ_UNSOLICITED = "DQ015"


@dataclass(frozen=True)
class _Expected:
    """The Art. 138-resolved external CQS one counterparty must carry, per regime."""

    b31: int | None
    crr: int | None


#: Counterparty-level (long-term) Art. 138 result. CRR is the unsuppressed
#: selection in every row; B31 differs only where (g) bites.
_LONG_TERM: dict[str, _Expected] = {
    # (f) over {1, 1, 3} = 1; with both flagged rows removed, (d) over {3} = 3.
    _CP_MULTI: _Expected(b31=3, crr=1),
    # (f) over {1, 2, 3} = 2. Suppressed BEFORE selection: (e) over {1, 3} = 3.
    # A post-selection null of the flagged winner would give None instead.
    _CP_ORDER: _Expected(b31=3, crr=2),
    # The only assessment is disregarded: the institution is unrated (SCRA).
    _CP_SOLE: _Expected(b31=None, crr=2),
    # Art. 138(1)(g) tail clause: government-owned / sponsored -> may be used.
    _CP_GOV: _Expected(b31=1, crr=1),
    # Not an exposure to an institution.
    _CP_CORP: _Expected(b31=1, crr=1),
    # Null = no ECAI methodology review recorded: not treated as True.
    _CP_NULL: _Expected(b31=1, crr=1),
    _CP_FALSE: _Expected(b31=1, crr=1),
    # Art. 107(2)(a): treated as an exposure to an institution.
    _CP_QCCP: _Expected(b31=None, crr=1),
    # Art. 107(2)(b): treated as an exposure to a corporate.
    _CP_NQCCP: _Expected(b31=1, crr=1),
    # Art. 119(5): treated as an exposure to an institution.
    _CP_FI: _Expected(b31=None, crr=2),
    _CP_ST_DOWN: _Expected(b31=1, crr=1),
    _CP_ST_UP: _Expected(b31=4, crr=4),
    # A flagged INTERNAL rating is not an ECAI assessment: the external CQS2 stands.
    _CP_INTERNAL: _Expected(b31=2, crr=2),
    _CP_INTERNAL_PARENT: _Expected(b31=None, crr=None),
    # One agency, two long-term rows. CRR: the agency's latest (CQS1) is its
    # assessment. B31: the flagged CQS1 is removed BEFORE the per-agency
    # reduction, so the agency's clean CQS3 is used. Reducing first would pick
    # the flagged CQS1, then drop it: None (unrated, SCRA) instead of 3.
    _CP_SAME_AGENCY: _Expected(b31=3, crr=1),
    # Its only assessment is disregarded under B31 (and so is never used).
    _CP_UNSOLICITED: _Expected(b31=None, crr=2),
}


@dataclass(frozen=True)
class _ExpectedShortTerm:
    """The short-term exposure's (has_short_term_ecai, cqs) per regime."""

    b31: tuple[bool, int]
    crr: tuple[bool, int]


#: Exposure-level result of the Art. 120(2B) / Art. 131 short-term override.
_SHORT_TERM: dict[str, _ExpectedShortTerm] = {
    # B31: the flagged short-term CQS3 is disregarded -> the long-term CQS1
    # stays, routed by Table 4 (Art. 120(2)), not Table 4A.
    _CP_ST_DOWN: _ExpectedShortTerm(b31=(False, 1), crr=(True, 3)),
    # B31: the flagged short-term CQS1 is disregarded -> the long-term CQS4.
    _CP_ST_UP: _ExpectedShortTerm(b31=(False, 4), crr=(True, 1)),
}


@dataclass(frozen=True)
class _Resolved:
    """One regime's hierarchy output: the rating audit, the CP lookup, the exposures."""

    regime: str
    rating_inheritance: pl.DataFrame
    counterparties: pl.DataFrame
    exposures: pl.DataFrame
    error_codes: tuple[str, ...]


@pytest.fixture(scope="module", params=["crr", "b31"])
def resolved(request: pytest.FixtureRequest) -> _Resolved:
    """Resolve the P1.259 bundle once per regime."""
    regime: str = request.param
    config = _config(regime)

    result = HierarchyResolver().resolve(_bundle(), config)

    return _Resolved(
        regime=regime,
        rating_inheritance=result.counterparty_lookup.rating_inheritance.collect(),
        counterparties=result.counterparty_lookup.counterparties.collect(),
        exposures=result.exposures.collect(),
        error_codes=tuple(e.code for e in result.hierarchy_errors),
    )


def test_p1_259_fixture_carries_the_flags_the_scenarios_need() -> None:
    """Adequacy: the flags reach the sealed raw tables, or every B31 test is vacuous."""
    # Arrange
    bundle = _bundle()

    # Act
    ratings = bundle.ratings.collect() if bundle.ratings is not None else pl.DataFrame()
    counterparties = bundle.counterparties.collect()

    # Assert
    assert "rating_incorporates_government_support" in ratings.columns, (
        "RATINGS_SCHEMA must declare rating_incorporates_government_support, or the "
        "loader seal strips the flag and Art. 138(1)(g) can never be applied"
    )
    flagged = ratings.filter(pl.col("rating_incorporates_government_support").eq_missing(True))
    assert flagged.height == 15, f"expected 15 flagged rating rows, got {flagged.height}"
    flagged_internal = flagged.filter(pl.col("rating_type") == "internal")
    assert flagged_internal["counterparty_reference"].to_list() == [_CP_INTERNAL], (
        "the internal-rating leg needs exactly one flagged INTERNAL row, or the "
        "external-only scope of the filter is untested"
    )
    assert ratings["rating_incorporates_government_support"].null_count() == 1, (
        "the null-flag leg must keep its null through the seal (no Boolean default)"
    )
    gov = counterparties.filter(pl.col("is_government_owned_or_sponsored").eq_missing(True))
    assert gov["counterparty_reference"].to_list() == [_CP_GOV]
    same_agency = (
        ratings.filter(pl.col("counterparty_reference") == _CP_SAME_AGENCY)
        .sort("rating_date", descending=True)
        .select("rating_agency", "is_short_term", "rating_incorporates_government_support")
        .rows()
    )
    assert same_agency == [("MOODYS", False, True), ("MOODYS", False, False)], (
        "the same-agency leg needs two LONG-TERM rows from ONE agency, the NEWER one "
        f"flagged — or the filter-before-dedup order is untested; got {same_agency}"
    )
    unsolicited = ratings.filter(pl.col("is_solicited").eq_missing(False))
    assert unsolicited["counterparty_reference"].to_list() == [_CP_UNSOLICITED]


@pytest.mark.parametrize("counterparty", sorted(_LONG_TERM))
def test_p1_259_art_138_resolved_external_cqs(resolved: _Resolved, counterparty: str) -> None:
    """External CQS after Art. 138: B31 disregards (g)-barred assessments, CRR does not."""
    # Arrange
    regime = resolved.regime
    expected = getattr(_LONG_TERM[counterparty], regime)

    # Act
    rows = resolved.rating_inheritance.filter(pl.col("counterparty_reference") == counterparty)

    # Assert
    assert rows.height == 1, f"{regime}: expected one rating row for {counterparty}"
    assert rows["external_cqs"][0] == expected, (
        f"{regime}: {counterparty} external_cqs expected {expected!r}, "
        f"got {rows['external_cqs'][0]!r}"
    )


@pytest.mark.parametrize("counterparty", sorted(_LONG_TERM))
def test_p1_259_counterparty_lookup_carries_the_disregarded_result(
    resolved: _Resolved, counterparty: str
) -> None:
    """The sealed CP lookup's ``cqs`` — what CCR / SFT rows and guarantor joins read — matches.

    ``engine/stages/_ccr_shared.py`` attaches ``cqs`` / ``external_cqs`` to the
    synthetic CCR and SFT rows from ``counterparty_lookup.counterparties``, not
    from the rating audit frame, so the suppression must reach that carrier too.
    """
    # Arrange
    regime = resolved.regime
    expected = getattr(_LONG_TERM[counterparty], regime)

    # Act
    rows = resolved.counterparties.filter(pl.col("counterparty_reference") == counterparty)

    # Assert
    assert rows.height == 1, f"{regime}: expected one lookup row for {counterparty}"
    got = (rows["cqs"][0], rows["external_cqs"][0])
    assert got == (expected, expected), (
        f"{regime}: {counterparty} lookup (cqs, external_cqs) expected "
        f"{(expected, expected)}, got {got}"
    )


def test_p1_259_flagged_internal_rating_is_not_disregarded(resolved: _Resolved) -> None:
    """A flagged INTERNAL rating keeps its PD and model id in both regimes.

    Art. 138(1)(g) bars a "credit assessment" — an ECAI's — that incorporates
    implicit government support; an internal rating is the firm's own IRB
    grade, outside Art. 138. Removing it would leave the bank with no own
    internal rating, so it would silently inherit its parent's PD and model id
    (Art. 171(1) / 175(3) inheritance) and lose its own model permission route.
    """
    # Arrange
    regime = resolved.regime

    # Act
    rows = resolved.rating_inheritance.filter(pl.col("counterparty_reference") == _CP_INTERNAL)

    # Assert
    assert rows.height == 1, f"{regime}: expected one rating row for {_CP_INTERNAL}"
    got = (rows["internal_pd"][0], rows["internal_model_id"][0])
    assert got == (_INTERNAL_PD, _INTERNAL_MODEL), (
        f"{regime}: {_CP_INTERNAL} (internal_pd, internal_model_id) expected "
        f"{(_INTERNAL_PD, _INTERNAL_MODEL)}, got {got} — the parent's is "
        f"{(_PARENT_PD, _PARENT_MODEL)}"
    )


def test_p1_259_disregarded_unsolicited_assessment_is_not_counted_by_dq015(
    resolved: _Resolved,
) -> None:
    """DQ015 counts only assessments the run may use: B31 disregards the one unsolicited row.

    The fixture's only unsolicited assessment is a flagged one on a bank. Under
    CRR it is the bank's assessment, so the Art. 138 chapeau warning fires;
    under Basel 3.1 (g) removes it before anything reads it, so nothing
    unsolicited is used and no warning is raised.
    """
    # Arrange
    expected = 1 if resolved.regime == "crr" else 0

    # Act
    found = resolved.error_codes.count(_DQ_UNSOLICITED)

    # Assert
    assert found == expected, (
        f"{resolved.regime}: expected {expected} {_DQ_UNSOLICITED} warning(s), got {found} "
        f"(codes: {sorted(set(resolved.error_codes))})"
    )


@pytest.mark.parametrize("counterparty", sorted(_SHORT_TERM))
def test_p1_259_short_term_assessment_is_disregarded_too(
    resolved: _Resolved, counterparty: str
) -> None:
    """A flagged dedicated short-term assessment is not used under B31 (Art. 138(1)(g)).

    The short-term override reads the raw ratings table, not the Art. 138
    selection — a filter applied only to the long-term selection leaves both
    legs on Table 4A.
    """
    # Arrange
    regime = resolved.regime
    expected = getattr(_SHORT_TERM[counterparty], regime)

    # Act
    rows = resolved.exposures.filter(pl.col("exposure_reference") == f"LN_{counterparty}")

    # Assert
    assert rows.height == 1, f"{regime}: expected one exposure for {counterparty}"
    got = (rows["has_short_term_ecai"][0], rows["cqs"][0])
    assert got == expected, (
        f"{regime}: {counterparty} (has_short_term_ecai, cqs) expected {expected}, got {got}"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config(regime: str) -> CalculationConfig:
    """SA-only config for the regime."""
    if regime == "crr":
        return CalculationConfig.crr(
            reporting_date=_REPORTING_DATE, permission_mode=PermissionMode.STANDARDISED
        )
    return CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE, permission_mode=PermissionMode.STANDARDISED
    )


def _bundle() -> RawDataBundle:
    """Sixteen obligors, one loan each, and the ratings each scenario needs."""
    counterparties = pl.DataFrame(
        [
            _counterparty(_CP_MULTI, "bank"),
            _counterparty(_CP_ORDER, "bank"),
            _counterparty(_CP_SOLE, "Bank"),
            _counterparty(_CP_GOV, "bank", government_owned=True),
            _counterparty(_CP_CORP, "corporate"),
            _counterparty(_CP_NULL, "bank"),
            _counterparty(_CP_FALSE, "bank"),
            _counterparty(_CP_QCCP, "ccp", is_qccp=True),
            _counterparty(_CP_NQCCP, "ccp", is_qccp=False),
            _counterparty(_CP_FI, "financial_institution"),
            _counterparty(_CP_ST_DOWN, "bank"),
            _counterparty(_CP_ST_UP, "bank"),
            _counterparty(_CP_INTERNAL, "bank"),
            _counterparty(_CP_INTERNAL_PARENT, "bank"),
            _counterparty(_CP_SAME_AGENCY, "bank"),
            _counterparty(_CP_UNSOLICITED, "bank"),
        ]
    )
    short_term = {_CP_ST_DOWN, _CP_ST_UP}
    loans = pl.DataFrame(
        [_loan(cp, _SHORT_MATURITY if cp in short_term else _LONG_MATURITY) for cp in _LONG_TERM]
    )
    ratings = pl.DataFrame(
        [
            _rating(_CP_MULTI, "MOODYS", 1, flagged=True),
            _rating(_CP_MULTI, "SP", 1, flagged=True),
            _rating(_CP_MULTI, "FITCH", 3, flagged=False),
            _rating(_CP_ORDER, "MOODYS", 1, flagged=False),
            _rating(_CP_ORDER, "SP", 2, flagged=True),
            _rating(_CP_ORDER, "FITCH", 3, flagged=False),
            _rating(_CP_SOLE, "MOODYS", 2, flagged=True),
            _rating(_CP_GOV, "MOODYS", 1, flagged=True),
            _rating(_CP_GOV, "SP", 1, flagged=True),
            _rating(_CP_GOV, "FITCH", 3, flagged=False),
            _rating(_CP_CORP, "MOODYS", 1, flagged=True),
            _rating(_CP_NULL, "MOODYS", 1, flagged=None),
            _rating(_CP_FALSE, "MOODYS", 1, flagged=False),
            _rating(_CP_QCCP, "MOODYS", 1, flagged=True),
            _rating(_CP_NQCCP, "MOODYS", 1, flagged=True),
            _rating(_CP_FI, "MOODYS", 2, flagged=True),
            _rating(_CP_ST_DOWN, "MOODYS", 1, flagged=False),
            _rating(_CP_ST_DOWN, "MOODYS", 3, flagged=True, short_term=True),
            _rating(_CP_ST_UP, "MOODYS", 4, flagged=False),
            _rating(_CP_ST_UP, "MOODYS", 1, flagged=True, short_term=True),
            _rating(_CP_INTERNAL, "MOODYS", 2, flagged=False),
            _internal_rating(_CP_INTERNAL, _INTERNAL_PD, _INTERNAL_MODEL, flagged=True),
            _internal_rating(_CP_INTERNAL_PARENT, _PARENT_PD, _PARENT_MODEL, flagged=False),
            _rating(
                _CP_SAME_AGENCY,
                "MOODYS",
                1,
                flagged=True,
                rating_date=_SAME_AGENCY_FLAGGED_DATE,
                tag="SUPPORT",
            ),
            _rating(
                _CP_SAME_AGENCY,
                "MOODYS",
                3,
                flagged=False,
                rating_date=_SAME_AGENCY_CLEAN_DATE,
                tag="STANDALONE",
            ),
            _rating(_CP_UNSOLICITED, "MOODYS", 2, flagged=True, solicited=False),
        ],
        schema_overrides={
            "cqs": pl.Int8,
            "pd": pl.Float64,
            "model_id": pl.String,
            "rating_incorporates_government_support": pl.Boolean,
        },
    )
    org_mappings = pl.DataFrame(
        [
            {
                "parent_counterparty_reference": _CP_INTERNAL_PARENT,
                "child_counterparty_reference": _CP_INTERNAL,
            }
        ]
    )
    return make_raw_bundle(
        facilities=pl.LazyFrame(
            schema={"facility_reference": pl.String, "counterparty_reference": pl.String}
        ),
        loans=loans,
        counterparties=counterparties,
        facility_mappings=pl.LazyFrame(
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }
        ),
        ratings=ratings,
        org_mappings=org_mappings,
    )


def _counterparty(
    reference: str,
    entity_type: str,
    *,
    government_owned: bool = False,
    is_qccp: bool = False,
) -> dict[str, object]:
    return {
        "counterparty_reference": reference,
        "counterparty_name": reference,
        "entity_type": entity_type,
        "country_code": "GB",
        "annual_revenue": 100_000_000.0,
        "total_assets": 100_000_000.0,
        "is_qccp": is_qccp,
        "is_government_owned_or_sponsored": government_owned,
    }


def _loan(counterparty: str, maturity: date) -> dict[str, object]:
    return {
        "loan_reference": f"LN_{counterparty}",
        "counterparty_reference": counterparty,
        "currency": "GBP",
        "value_date": _VALUE_DATE,
        "maturity_date": maturity,
        "drawn_amount": 1_000_000.0,
        "interest": 0.0,
        "seniority": "senior",
    }


def _rating(
    counterparty: str,
    agency: str,
    cqs: int,
    *,
    flagged: bool | None,
    short_term: bool = False,
    rating_date: date = _RATING_DATE,
    solicited: bool = True,
    tag: str = "",
) -> dict[str, object]:
    suffix = "ST" if short_term else "LT"
    return {
        "rating_reference": f"RTG_{counterparty}_{agency}_{suffix}{tag}",
        "counterparty_reference": counterparty,
        "rating_type": "external",
        "rating_agency": agency,
        "rating_value": f"cqs{cqs}",
        "cqs": cqs,
        "rating_date": rating_date,
        "is_solicited": solicited,
        "is_short_term": short_term,
        "scope_type": "loan" if short_term else None,
        "scope_id": f"LN_{counterparty}" if short_term else None,
        "rating_incorporates_government_support": flagged,
    }


def _internal_rating(
    counterparty: str, pd: float, model_id: str, *, flagged: bool | None
) -> dict[str, object]:
    return {
        "rating_reference": f"RTG_{counterparty}_INTERNAL",
        "counterparty_reference": counterparty,
        "rating_type": "internal",
        "rating_agency": None,
        "rating_value": None,
        "cqs": None,
        "pd": pd,
        "model_id": model_id,
        "rating_date": _RATING_DATE,
        "is_solicited": True,
        "is_short_term": False,
        "scope_type": None,
        "scope_id": None,
        "rating_incorporates_government_support": flagged,
    }
