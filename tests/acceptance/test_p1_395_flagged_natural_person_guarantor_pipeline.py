"""
P1.395 — outcome: a guarantee from a flagged natural person is not recognised, end to end.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor (Art. 201 gate)
        -> SA / IRB guarantee substitution -> OutputAggregator

Why this exists: the unit tests in
``tests/unit/crm/test_p1_395_art_201_flagged_natural_person_guarantor.py`` pin the
gate's MEANS - ``guarantor_approach`` and ``guarantor_exposure_class`` cleared, one
natural-person CRM013. They could not see that a cleared class does not, on its
own, stop substitution: the guarantor RW chain (``engine/sa/guarantor_rw.py``)
keyed its QCCP branch on ``entity_type == "ccp"``, not on the class the gate
clears. A flagged guarantor booked ``ccp`` therefore kept its 2% / 4% weight on SA
legs, and on F-IRB legs too (the IRB path falls back to the SA guarantor RW
whenever ``guarantor_approach != "irb"``) - while its CRM013 said the exposure
"reverts to the borrower's own basis". This file pins the OUTCOME instead: for a
flagged guarantor of every entity type the RW chain can price, the covered leg
carries no guarantor RW, is not beneficially substituted, and lands on the
borrower's own RWEA - on the IRB leg's SA-equivalent (the output-floor input) as
well as on its IRB RWEA. Both regimes; Art. 201 admits no natural person in
either (CRR Art. 201(1)/(2); PS1/26 Credit Risk Mitigation (CRR) Part
Art. 201(1)/(2) and Art. 194(6)(c)).

Shape (reuses the P1.227 borrowers and their ratings, one GBP 1,000,000 loan per
leg, each 100% guaranteed by its own guarantor):
- ``ecai``: guarantor with an external CQS 1 rating, on an SA leg (borrower
  CP_P227_B, CQS 5) and on an F-IRB leg (borrower CP_P227_B_IRB, internal PD 1.5%).
- ``internal``: guarantor with only an internal PD of 1% on the F-IRB leg - the
  shape of the reviewer's probe (P1.227 G34 re-booked ``ccp``).
Each flagged guarantor (``is_natural_person`` True) has an unflagged twin of the
same entity type and rating, which is the adequacy control: the twin IS
substituted, so the RW chain prices that type and the flagged assertion can fail.

Hand-calculation of the borrower basis (the value every flagged leg must land on):
- SA leg: CP_P227_B, CQS 5 -> 150% (CRR Art. 122 Table 5 / PS1/26 Art. 122(2)
  Table 6, identical) -> 1,000,000 x 1.50 = 1,500,000, both regimes.
- F-IRB leg: CP_P227_B_IRB, PD 1.50%, senior unsecured, large corporate (no SME
  adjustment), engine residual maturity M = 1064 / 365 = 2.91507 years
  (reporting date 2027-02-01, maturity 2030-01-01):
      R = 0.12 w + 0.24 (1 - w), w = (1 - e^(-50 PD)) / (1 - e^(-50))
      b = (0.11852 - 0.05478 ln PD)^2
      K = [LGD N((G(PD) + sqrt(R) G(0.999)) / sqrt(1 - R)) - PD LGD]
          x (1 + (M - 2.5) b) / (1 - 1.5 b)
      CRR:  LGD 45% (Art. 161(1)(a)), RWEA = K x 12.5 x 1.06 x EAD = 1,175,736.91
      B31:  LGD 40% (PS1/26 Art. 161(1)(aa)), RWEA = K x 12.5 x EAD = 985,942.90
  Its SA-equivalent (``sa_rwa``): CP_P227_B_IRB has no ECAI rating -> unrated
  corporate 100% (CRR Art. 122(2) / PS1/26 Art. 122(2)) -> 1,000,000.

References:
- CRR Art. 201(1)/(2), Art. 194(5); PS1/26 CRM (CRR) Part Art. 201(1)/(2), 194(6)(c)
- CRR Art. 235 / PS1/26 Art. 235 (risk-weight substitution), CRR Art. 236 /
  PS1/26 Art. 236 (parameter substitution)
- CRR Art. 306 (QCCP 2% / 4%) - the branch the leak ran through
- tests/fixtures/p1_227/p1_227.py (borrowers, ratings, model permission)
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.contracts.errors import ERROR_INELIGIBLE_GUARANTOR
from rwa_calc.engine.entity_class_maps import ENTITY_TYPE_TO_SA_CLASS
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.p1_227.p1_227 import (
    CP_B_IRB_REF,
    CP_B_REF,
    CP_G2_REF,
    CP_G34_REF,
    GUARANTEE_G2_REF,
    LOAN_G2_REF,
    LOAN_G3_REF,
    create_p227_counterparties,
    create_p227_guarantees,
    create_p227_loans,
    create_p227_model_permission,
    create_p227_ratings,
)
from tests.fixtures.raw_bundle import make_raw_bundle

_REPORTING_DATE = date(2027, 2, 1)

#: The guarantor SA classes ``build_guarantor_rw_expr`` prices (CCP rides on
#: ``institution``). Every entity type booked into one of them is exercised.
_PRICED_GUARANTOR_CLASSES = frozenset(
    {
        "central_govt_central_bank",
        "rgla",
        "pse",
        "mdb",
        "international_organisation",
        "institution",
        "corporate",
    }
)
_PRICED_ENTITY_TYPES: tuple[str, ...] = tuple(
    sorted(et for et, cls in ENTITY_TYPE_TO_SA_CLASS.items() if cls in _PRICED_GUARANTOR_CLASSES)
)

#: (rating shape, leg) cases. The ``internal`` shape is F-IRB only: an internal
#: rating is invisible to the SA ECAI lookup, so on an SA leg it is the corporate
#: limb's concern (P1.227 G4), not this item's.
_CASES: tuple[tuple[str, str], ...] = (("ecai", "sa"), ("ecai", "firb"), ("internal", "firb"))

_GUARANTOR_CQS = 1
_GUARANTOR_INTERNAL_PD = 0.01

#: Borrower basis - see the module docstring for the derivation.
_BORROWER_RWEA_SA = 1_500_000.0
_BORROWER_RWEA_FIRB = {"crr": 1_175_736.91, "b31": 985_942.90}
_BORROWER_SA_EQUIVALENT_FIRB = 1_000_000.0


def _loan_ref(entity_type: str, shape: str, leg: str, *, flagged: bool) -> str:
    return f"LN_P395_{entity_type}_{shape}_{leg}_{'F' if flagged else 'U'}"


def _guarantor_ref(entity_type: str, shape: str, *, flagged: bool) -> str:
    return f"CP_P395_{entity_type}_{shape}_{'F' if flagged else 'U'}"


def _build_bundle() -> RawDataBundle:
    """The P1.227 borrowers plus one guaranteed loan per (type, shape, leg, flag)."""
    counterparties = create_p227_counterparties()
    loans = create_p227_loans()
    ratings = create_p227_ratings()
    guarantees = create_p227_guarantees()

    loan_template = {
        "sa": loans.filter(pl.col("loan_reference") == LOAN_G2_REF),
        "firb": loans.filter(pl.col("loan_reference") == LOAN_G3_REF),
    }
    assert loan_template["sa"]["counterparty_reference"].to_list() == [CP_B_REF]
    assert loan_template["firb"]["counterparty_reference"].to_list() == [CP_B_IRB_REF]
    guarantor_template = counterparties.filter(pl.col("counterparty_reference") == CP_G2_REF)
    rating_template = {
        "ecai": ratings.filter(pl.col("counterparty_reference") == CP_G2_REF).with_columns(
            pl.lit(_GUARANTOR_CQS).cast(ratings.schema["cqs"]).alias("cqs")
        ),
        "internal": ratings.filter(pl.col("counterparty_reference") == CP_G34_REF).with_columns(
            pl.lit(_GUARANTOR_INTERNAL_PD).alias("pd")
        ),
    }
    guarantee_template = guarantees.filter(pl.col("guarantee_reference") == GUARANTEE_G2_REF)

    new_counterparties = [
        counterparties.filter(pl.col("counterparty_reference").is_in([CP_B_REF, CP_B_IRB_REF]))
    ]
    new_ratings = [ratings.filter(pl.col("counterparty_reference").is_in([CP_B_REF, CP_B_IRB_REF]))]
    new_loans: list[pl.DataFrame] = []
    new_guarantees: list[pl.DataFrame] = []
    for entity_type in _PRICED_ENTITY_TYPES:
        for shape in ("ecai", "internal"):
            for flagged in (True, False):
                guarantor = _guarantor_ref(entity_type, shape, flagged=flagged)
                new_counterparties.append(
                    guarantor_template.with_columns(
                        pl.lit(guarantor).alias("counterparty_reference"),
                        pl.lit(entity_type).alias("entity_type"),
                        pl.lit(flagged).alias("is_natural_person"),
                    )
                )
                new_ratings.append(
                    rating_template[shape].with_columns(
                        pl.lit(f"RTG_{guarantor}").alias("rating_reference"),
                        pl.lit(guarantor).alias("counterparty_reference"),
                    )
                )
        for shape, leg in _CASES:
            for flagged in (True, False):
                loan = _loan_ref(entity_type, shape, leg, flagged=flagged)
                new_loans.append(
                    loan_template[leg].with_columns(pl.lit(loan).alias("loan_reference"))
                )
                new_guarantees.append(
                    guarantee_template.with_columns(
                        pl.lit(f"GUAR_{loan}").alias("guarantee_reference"),
                        pl.lit(_guarantor_ref(entity_type, shape, flagged=flagged)).alias(
                            "guarantor"
                        ),
                        pl.lit(loan).alias("beneficiary_reference"),
                    )
                )

    return make_raw_bundle(
        facilities=pl.LazyFrame(
            schema={"facility_reference": pl.String, "counterparty_reference": pl.String}
        ),
        loans=pl.concat(new_loans).lazy(),
        counterparties=pl.concat(new_counterparties, how="diagonal_relaxed").lazy(),
        facility_mappings=pl.LazyFrame(
            schema={
                "parent_facility_reference": pl.String,
                "child_reference": pl.String,
                "child_type": pl.String,
            }
        ),
        lending_mappings=pl.LazyFrame(
            schema={
                "parent_counterparty_reference": pl.String,
                "child_counterparty_reference": pl.String,
            }
        ),
        ratings=pl.concat(new_ratings).lazy(),
        guarantees=pl.concat(new_guarantees).lazy(),
        model_permissions=create_p227_model_permission().lazy(),
    )


def _config(regime: str) -> CalculationConfig:
    if regime == "crr":
        return CalculationConfig.crr(
            reporting_date=_REPORTING_DATE, permission_mode=PermissionMode.IRB
        )
    return CalculationConfig.basel_3_1(
        reporting_date=_REPORTING_DATE, permission_mode=PermissionMode.IRB
    )


@pytest.fixture(scope="module")
def runs() -> Iterator[dict[str, tuple[pl.DataFrame, list[str]]]]:
    """One full pipeline run per regime: (results, exposure refs named by a CRM013)."""
    bundle = _build_bundle()
    out: dict[str, tuple[pl.DataFrame, list[str]]] = {}
    for regime in ("crr", "b31"):
        result = PipelineOrchestrator().run_with_data(bundle, _config(regime))
        assert result.results is not None
        crm013 = [
            str(e.exposure_reference) for e in result.errors if e.code == ERROR_INELIGIBLE_GUARANTOR
        ]
        out[regime] = (result.results.collect(), crm013)
    yield out


def _loan_rows(results: pl.DataFrame, loan: str) -> pl.DataFrame:
    rows = results.filter(pl.col("parent_exposure_reference") == loan)
    assert rows.height > 0, f"no result rows for {loan} - the assertions would be vacuous"
    return rows


def _borrower_rwea(regime: str, leg: str) -> float:
    return _BORROWER_RWEA_SA if leg == "sa" else _BORROWER_RWEA_FIRB[regime]


def test_every_priced_guarantor_class_is_exercised() -> None:
    """Adequacy: the CCP branch the leak ran through, and every class, are covered."""
    assert "ccp" in _PRICED_ENTITY_TYPES
    assert {ENTITY_TYPE_TO_SA_CLASS[et] for et in _PRICED_ENTITY_TYPES} == (
        _PRICED_GUARANTOR_CLASSES
    )


@pytest.mark.parametrize("regime", ["crr", "b31"])
@pytest.mark.parametrize(("shape", "leg"), _CASES, ids=[f"{s}_{lg}" for s, lg in _CASES])
@pytest.mark.parametrize("entity_type", _PRICED_ENTITY_TYPES)
def test_unflagged_twin_is_substituted(
    runs: dict[str, tuple[pl.DataFrame, list[str]]],
    regime: str,
    entity_type: str,
    shape: str,
    leg: str,
) -> None:
    """Control: without the flag the guarantee IS recognised, so the flagged case can fail."""
    results, _ = runs[regime]

    rows = _loan_rows(results, _loan_ref(entity_type, shape, leg, flagged=False))

    assert rows["is_guarantee_beneficial"].fill_null(False).any(), (
        f"{regime}/{entity_type}/{shape}/{leg}: the unflagged twin is not substituted, "
        "so the flagged leg below cannot distinguish a decline from a non-beneficial guarantee"
    )
    assert rows["rwa_final"].sum() < _borrower_rwea(regime, leg)


@pytest.mark.parametrize("regime", ["crr", "b31"])
@pytest.mark.parametrize(("shape", "leg"), _CASES, ids=[f"{s}_{lg}" for s, lg in _CASES])
@pytest.mark.parametrize("entity_type", _PRICED_ENTITY_TYPES)
def test_flagged_guarantee_leaves_the_leg_on_the_borrower_basis(
    runs: dict[str, tuple[pl.DataFrame, list[str]]],
    regime: str,
    entity_type: str,
    shape: str,
    leg: str,
) -> None:
    """A natural person is in no Art. 201 limb: no guarantor RW, no substitution, borrower RWEA."""
    results, _ = runs[regime]
    label = f"{regime}/{entity_type}/{shape}/{leg}"

    rows = _loan_rows(results, _loan_ref(entity_type, shape, leg, flagged=True))

    assert rows["guarantor_rw"].is_null().all(), (
        f"{label}: a declined guarantor must price no RW, got {rows['guarantor_rw'].to_list()}"
    )
    assert not rows["is_guarantee_beneficial"].fill_null(False).any(), label
    assert rows["rwa_final"].sum() == pytest.approx(_borrower_rwea(regime, leg), rel=1e-6), label
    if regime == "b31" and leg == "firb":
        # The output floor (PS1/26 Art. 92(2A)) exists only under Basel 3.1; a CRR
        # run carries no SA-equivalent column.
        assert rows["sa_rwa"].sum() == pytest.approx(_BORROWER_SA_EQUIVALENT_FIRB, rel=1e-9), (
            f"{label}: the output-floor SA-equivalent must also stay on the borrower basis"
        )


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_crm013_names_exactly_the_flagged_guarantees(
    runs: dict[str, tuple[pl.DataFrame, list[str]]], regime: str
) -> None:
    """Every CRM013 ("reverts to the borrower's own basis") is a leg the outcome test checks."""
    _, crm013 = runs[regime]

    expected = sorted(
        _loan_ref(et, shape, leg, flagged=True)
        for et in _PRICED_ENTITY_TYPES
        for shape, leg in _CASES
    )
    assert sorted(crm013) == expected
