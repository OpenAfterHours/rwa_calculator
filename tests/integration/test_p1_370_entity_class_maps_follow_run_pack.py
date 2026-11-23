"""
P1.370 — every entity-type -> SA-class consumer follows the run's pack, not CRR's.

Pipeline position:
    PipelineOrchestrator.run_with_data(rulepack=...) -> HierarchyResolver
    (short-term-ECAI obligor-class gate) -> Classifier -> CRMProcessor
    (guarantor exposure class) -> SA calculator

What this pins:
    ``engine/entity_class_maps.py`` binds module-level constants against the
    CRR default pack at import. P1.311 threaded the run's pack into the
    classifier's two forward maps and left two production consumers on those
    constants:

    - the CRR Art. 140(1) / PS1/26 Art. 140(1) short-term-ECAI obligor-class
      gate (``engine/hierarchy/enrich.py``), which expands the ``institution``
      and ``corporate`` SA classes into the entity types a short-term
      assessment may be used for, through ``ENTITY_TYPES_BY_SA_CLASS``;
    - the CRM guarantor-class derivation (``engine/crm/guarantees.py``), through
      ``ENTITY_TYPE_TO_SA_CLASS``.

    Art. 140(1) reads the same in both regimes ("only ... exposures to
    institutions and corporates"), so the right behaviour is not a regime
    branch: it is "the class the RUN assigns". Under a pack that maps an entity
    type to a different SA class — an amendment overlay passed through
    ``run_with_data(rulepack=...)`` or ``RunSpec.rulepack``, or a future
    ``packs/b31.py`` override — the classifier honoured the new class while the
    gate and the guarantor class kept the CRR one, so one frame carried two
    classes for the same obligor.

Why an overlay and not the shipped packs:
    The shipped CRR and Basel 3.1 maps are identical (31 entries each), so the
    change is number-neutral on every default run and no golden moves. The
    overlay is the only way to make the two bindings disagree; the adequacy
    test below asserts it does, so the defect tests cannot pass vacuously.

Scenario (one run per regime, the same overlay in each):
    - ``pse_institution`` -> ``institution`` (default SA class: ``pse``).
      CP_PSEI holds a short loan with a loan-scoped short-term rating (CQS 1).
      The run classes CP_PSEI as an institution, so Art. 140(1) admits the
      assessment: ``has_short_term_ecai`` True, ``cqs`` 1, no DQ009.
    - ``company`` -> ``other`` (default SA class: ``corporate``).
      CP_CO holds the same shape. The run classes CP_CO as ``other``, so
      Art. 140(1) rejects the assessment: ``has_short_term_ecai`` False,
      ``cqs`` null (no long-term rating), one DQ009 naming the loan.
    - CP_PSEI also guarantees a corporate borrower's loan in full. The
      guaranteed leg's ``guarantor_exposure_class`` is the run's class for
      ``pse_institution``: ``institution``, not CRR's ``pse``.

References:
    - CRR Art. 140(1); PS1/26 Art. 140(1): short-term assessments only for
      institutions and corporates
    - CRR Art. 112: SA exposure classes (the map being overlaid)
    - CRR Art. 235: guarantee substitution (the guarantor's class)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.contracts.errors import CalculationError
from rwa_calc.engine.entity_class_maps import entity_type_to_sa_class
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.rulebook import RulepackV0
from rwa_calc.rulebook.model import CategoryMap, Citation
from rwa_calc.rulebook.resolve import ResolvedRulepack, resolve
from tests.fixtures.raw_bundle import make_raw_bundle

_REPORTING_DATE = date(2027, 1, 31)
_VALUE_DATE = date(2027, 1, 1)
# 43 days residual at the reporting date: inside the short-term window.
_SHORT_MATURITY = date(2027, 3, 15)
_LONG_MATURITY = date(2030, 1, 1)
_DRAWN = 1_000_000.0

#: entity_type -> SA class the overlay assigns, and the class the shipped pack
#: assigns. The two must differ or the scenario proves nothing (adequacy test).
_OVERLAY = {"pse_institution": "institution", "company": "other"}
_SHIPPED = {"pse_institution": "pse", "company": "corporate"}

_CP_PSE_INSTITUTION = "CP_P1370_PSEI"
_CP_COMPANY = "CP_P1370_CO"
_CP_BORROWER = "CP_P1370_BORR"
_LOAN_PSE_INSTITUTION = "LN_P1370_PSEI"
_LOAN_COMPANY = "LN_P1370_CO"
_LOAN_GUARANTEED = "LN_P1370_BORR"

_DQ009 = "DQ009"


@dataclass(frozen=True)
class _Run:
    """One regime's pipeline output under the overlay."""

    regime: str
    sa: pl.DataFrame
    errors: list[CalculationError]


@pytest.fixture(scope="module", params=["crr", "b31"])
def overlay_run(request: pytest.FixtureRequest) -> _Run:
    """Run the P1.370 bundle once per regime under the entity-class overlay."""
    regime: str = request.param
    config = _config(regime)
    rulepack = RulepackV0.from_resolved(config, _overlay_pack(regime))

    result = PipelineOrchestrator().run_with_data(_bundle(), config, rulepack=rulepack)

    assert result.sa_results is not None, f"{regime}: SA results missing"
    return _Run(regime=regime, sa=result.sa_results.collect(), errors=list(result.errors))


def test_p1_370_the_overlay_diverges_from_the_shipped_pack_and_reaches_the_classifier(
    overlay_run: _Run,
) -> None:
    """Adequacy: the overlay is a real divergence, and the classifier honours it.

    Without this the defect tests below could pass vacuously — if the overlay
    agreed with the shipped map, the frozen CRR binding would give the same
    answer as the run's pack.
    """
    # Arrange
    shipped = entity_type_to_sa_class(resolve(overlay_run.regime, _REPORTING_DATE))

    # Act
    classes = {ref: _row(overlay_run, ref)["exposure_class"] for ref in _short_term_loans()}

    # Assert
    assert {et: shipped[et] for et in _SHIPPED} == _SHIPPED, (
        f"{overlay_run.regime}: the shipped map moved; re-pick entity types whose "
        "shipped SA class differs from the overlay"
    )
    assert classes == {
        _LOAN_PSE_INSTITUTION: _OVERLAY["pse_institution"],
        _LOAN_COMPANY: _OVERLAY["company"],
    }, f"{overlay_run.regime}: the classifier did not honour the overlay: {classes}"


def test_p1_370_short_term_assessment_admitted_for_an_obligor_the_run_classes_institution(
    overlay_run: _Run,
) -> None:
    """Art. 140(1) admits the assessment: the run classes the obligor an institution.

    Fails pre-fix: the gate built its eligible list from the CRR-frozen index,
    where ``pse_institution`` is a PSE, so it rejected the rating and raised
    DQ009 on an exposure the same frame reports as an institution.
    """
    # Arrange / Act
    row = _row(overlay_run, _LOAN_PSE_INSTITUTION)

    # Assert
    assert (row["has_short_term_ecai"], row["cqs"]) == (True, 1), (
        f"{overlay_run.regime}: the short-term CQS 1 rating on an exposure classed "
        f"'institution' must be used (Art. 140(1)); got has_short_term_ecai="
        f"{row['has_short_term_ecai']!r}, cqs={row['cqs']!r}"
    )
    assert _dq009_for(overlay_run, _LOAN_PSE_INSTITUTION) == [], (
        f"{overlay_run.regime}: DQ009 raised for an institution-class obligor"
    )


def test_p1_370_short_term_assessment_rejected_for_an_obligor_the_run_classes_other(
    overlay_run: _Run,
) -> None:
    """Art. 140(1) rejects the assessment: the run classes the obligor ``other``.

    Fails pre-fix: ``company`` is a corporate in the CRR-frozen index, so the
    gate accepted the rating on an exposure the same frame reports as
    ``other`` — and raised no DQ009.
    """
    # Arrange / Act
    row = _row(overlay_run, _LOAN_COMPANY)

    # Assert
    assert (row["has_short_term_ecai"], row["cqs"]) == (False, None), (
        f"{overlay_run.regime}: a short-term rating on an exposure classed 'other' "
        f"must be ignored (Art. 140(1)); got has_short_term_ecai="
        f"{row['has_short_term_ecai']!r}, cqs={row['cqs']!r}"
    )
    assert len(_dq009_for(overlay_run, _LOAN_COMPANY)) == 1, (
        f"{overlay_run.regime}: expected one DQ009 for the rejected rating on {_LOAN_COMPANY}"
    )


def test_p1_370_guarantor_exposure_class_follows_the_run_pack(overlay_run: _Run) -> None:
    """The guaranteed leg carries the guarantor's class under the RUN's map.

    Fails pre-fix: ``crm/guarantees.py`` derived ``guarantor_exposure_class``
    from the CRR-frozen map, so a ``pse_institution`` guarantor stayed ``pse``
    while the classifier classed the same counterparty ``institution``.
    """
    # Arrange
    legs = overlay_run.sa.filter(
        pl.col("exposure_reference").str.starts_with(_LOAN_GUARANTEED)
        & (pl.col("guaranteed_portion").fill_null(0.0) > 0)
    )
    assert legs.height == 1, (
        f"{overlay_run.regime}: expected one guaranteed leg for {_LOAN_GUARANTEED}, "
        f"got {legs.height}"
    )

    # Act
    leg = legs.row(0, named=True)

    # Assert
    assert (leg["guarantor_exposure_class"], leg["post_crm_exposure_class_guaranteed"]) == (
        _OVERLAY["pse_institution"],
        _OVERLAY["pse_institution"],
    ), (
        f"{overlay_run.regime}: the guarantor's class must come from the run's pack; got "
        f"guarantor_exposure_class={leg['guarantor_exposure_class']!r}, "
        f"post_crm_exposure_class_guaranteed={leg['post_crm_exposure_class_guaranteed']!r}"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config(regime: str) -> CalculationConfig:
    """SA-only config for the regime, at a date both regimes accept."""
    if regime == "crr":
        return CalculationConfig.crr(
            reporting_date=_REPORTING_DATE, permission_mode=PermissionMode.STANDARDISED
        )
    return CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE, permission_mode=PermissionMode.STANDARDISED
    )


def _overlay_pack(regime: str) -> ResolvedRulepack:
    """The regime's resolved pack with ``entity_type_to_sa_class`` overlaid."""
    pack = resolve(regime, _REPORTING_DATE)
    entries = {**pack.category_map("entity_type_to_sa_class").entries, **_OVERLAY}
    return pack.with_overrides(
        entity_type_to_sa_class=CategoryMap(
            name="entity_type_to_sa_class",
            entries=entries,
            key="entity_type",
            citation=Citation("CRR", "112"),
        )
    )


def _bundle() -> RawDataBundle:
    """Three obligors, three loans, two short-term ratings, one guarantee."""
    counterparties = pl.DataFrame(
        [
            _counterparty(_CP_PSE_INSTITUTION, "pse_institution"),
            _counterparty(_CP_COMPANY, "company"),
            _counterparty(_CP_BORROWER, "corporate"),
        ]
    )
    loans = pl.DataFrame(
        [
            _loan(_LOAN_PSE_INSTITUTION, _CP_PSE_INSTITUTION, _SHORT_MATURITY),
            _loan(_LOAN_COMPANY, _CP_COMPANY, _SHORT_MATURITY),
            _loan(_LOAN_GUARANTEED, _CP_BORROWER, _LONG_MATURITY),
        ]
    )
    ratings = pl.DataFrame(
        [
            _short_term_rating("RTG_P1370_PSEI", _CP_PSE_INSTITUTION, _LOAN_PSE_INSTITUTION),
            _short_term_rating("RTG_P1370_CO", _CP_COMPANY, _LOAN_COMPANY),
        ]
    )
    guarantees = pl.DataFrame(
        [
            {
                "guarantee_reference": "GTE_P1370",
                "guarantee_type": "guarantee",
                "guarantor": _CP_PSE_INSTITUTION,
                "currency": "GBP",
                "maturity_date": date(2030, 12, 31),
                "amount_covered": _DRAWN,
                "beneficiary_type": "loan",
                "beneficiary_reference": _LOAN_GUARANTEED,
                "protection_type": "guarantee",
                "includes_restructuring": True,
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
        guarantees=guarantees,
    )


def _counterparty(reference: str, entity_type: str) -> dict[str, object]:
    return {
        "counterparty_reference": reference,
        "counterparty_name": reference,
        "entity_type": entity_type,
        "country_code": "GB",
        "annual_revenue": 100_000_000.0,
        "total_assets": 100_000_000.0,
    }


def _loan(reference: str, counterparty: str, maturity: date) -> dict[str, object]:
    return {
        "loan_reference": reference,
        "counterparty_reference": counterparty,
        "currency": "GBP",
        "value_date": _VALUE_DATE,
        "maturity_date": maturity,
        "drawn_amount": _DRAWN,
        "interest": 0.0,
        "seniority": "senior",
    }


def _short_term_rating(reference: str, counterparty: str, loan: str) -> dict[str, object]:
    return {
        "rating_reference": reference,
        "counterparty_reference": counterparty,
        "rating_type": "external",
        "rating_agency": "S&P",
        "rating_value": "A-1+",
        "cqs": 1,
        "rating_date": date(2027, 1, 2),
        "is_solicited": True,
        "is_short_term": True,
        "scope_type": "loan",
        "scope_id": loan,
    }


def _short_term_loans() -> tuple[str, str]:
    return (_LOAN_PSE_INSTITUTION, _LOAN_COMPANY)


def _row(run: _Run, exposure_reference: str) -> dict[str, object]:
    rows = run.sa.filter(pl.col("exposure_reference") == exposure_reference).to_dicts()
    assert len(rows) == 1, f"{run.regime}: expected one row for {exposure_reference}"
    return rows[0]


def _dq009_for(run: _Run, exposure_reference: str) -> list[CalculationError]:
    return [
        e for e in run.errors if e.code == _DQ009 and e.exposure_reference == exposure_reference
    ]
