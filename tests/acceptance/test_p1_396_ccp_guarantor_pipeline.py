"""
P1.396 — a CCP guarantor takes the SA weight of a direct exposure to it, end to end.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor (guarantor join,
    Art. 107(2) class, Art. 201 gate) -> SA / IRB guarantee substitution
    -> OutputAggregator (incl. the Basel 3.1 output-floor SA-equivalent)

Why this exists: ``engine/sa/guarantor_rw.py::build_guarantor_rw_expr`` gave every
guarantor booked ``entity_type='ccp'`` the CCR (CRR) Part Art. 306(1) trade-exposure
weight of 2% (4% when the guarantor's counterparty row said client-cleared), ahead of
the institution and corporate branches, and never read ``is_qccp``. A guarantee is not
a trade exposure. Under Art. 235(1) the covered part takes "the risk weight of a
comparable direct exposure to the protection provider as specified under" the SA
(CRR: "the risk weight of exposures to the protection provider as specified under
Chapter 2"), and Art. 107(2) sends only trade exposures and default-fund contributions
to Section 9; every other exposure to a CCP is
"(a) ... an institution for ... a qualifying CCP; (b) ... a corporate for ... a
non-qualifying CCP" (CRR and PS1/26 Art. 107(2), identical). Art. 201(1)(h) admits
qualifying CCPs; a non-qualifying one is an "other corporate entity", eligible under
Art. 201(1)(g) with an ECAI assessment or, on the parameter-substitution path,
Art. 201(2) / CRR 201(1)(g)(ii) with an internal rating, and otherwise not at all.

Shape (the P1.227 borrowers, one GBP 1,000,000 loan per leg, each 100% guaranteed by
its own ``ccp`` guarantor):
- SA leg: borrower CP_P227_B, CQS 5 -> 150% in both regimes (CRR Art. 122 Table 5 /
  PS1/26 Art. 122(2) Table 6). Borrower RWEA 1,500,000.
- F-IRB leg: borrower CP_P227_B_IRB, internal PD 1.5%. Borrower IRB RWEA 1,175,736.91
  (CRR) / 985,942.90 (B31) and SA-equivalent 1,000,000 (unrated corporate 100%) - the
  P1.395 derivation, reused.

Guarantors and hand-calculation (weights read from the pack in the test, never typed):
- ``qccp_cqs2``: ``is_qccp`` True, ECAI CQS 2 -> institution class (Art. 107(2)(a)),
  Art. 120 Table 3 CQS 2 (CRR ``institution_rw_crr``) / ECRA Table 3 (PS1/26
  ``institution_rw_b31_ecra``). SA leg RWEA = 1,000,000 x that weight; the F-IRB leg
  routes to SA substitution (no internal PD), so its covered RWEA - and under Basel
  3.1 its SA-equivalent - is the same 1,000,000 x weight.
- ``nq_cqs3``: ``is_qccp`` False, ECAI CQS 3 -> corporate class (Art. 107(2)(b)),
  eligible under (1)(g); Art. 122 Table 5 / Table 6 CQS 3. CQS 3 is the grade that
  separates the two ladders in both regimes (corporate vs institution).
- ``null_cqs3``: ``is_qccp`` supplied as an explicit null. The loader seals it to the
  schema default False, so it is priced exactly as ``nq_cqs3`` (owner decision: an
  unreported qualification is not shown).
- ``nq_unrated``: ``is_qccp`` False, no rating -> corporate with no ECAI assessment
  and no internal rating -> not an Art. 201 provider: guarantee declined, CRM013, the
  leg keeps the borrower basis (1,500,000 SA; 1,175,736.91 / 985,942.90 F-IRB, and
  SA-equivalent 1,000,000).
- ``nq_internal``: ``is_qccp`` False, internal PD 1% only, on the F-IRB leg -> the
  internal-rating limb admits it as a corporate: parameter substitution under the
  corporate class, priced exactly as an ordinary corporate guarantor with the same PD
  (``corp_internal``, the twin control on the same leg). Under Basel 3.1 its
  output-floor SA-equivalent prices the covered part as an unrated corporate (100%):
  1,000,000.

At HEAD every ``ccp`` leg priced 2%: RWEA 20,000 on every SA leg and every F-IRB leg
routed to SA substitution, no CRM013, class institution - and the parameter-substituted
``nq_internal`` leg's Basel 3.1 SA-equivalent was 20,000 (the 2% leaked into the
output-floor input even where the IRB RWEA was right).

References:
- CRR Art. 107(2), 201(1)(f)-(h), 235(1); PS1/26 Art. 107(2), CRM (CRR) Part
  Art. 194(6)(c), 201(1)-(2), 235(1)(a)
- tests/fixtures/p1_227/p1_227.py (borrowers, ratings, model permission)
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import polars as pl
import pytest

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.contracts.errors import ERROR_INELIGIBLE_GUARANTOR
from rwa_calc.domain.enums import CQS
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.rulebook.resolve import resolve
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
_EAD = 1_000_000.0

#: Borrower basis (P1.395 derivation; see the module docstring).
_BORROWER_RWEA_SA = 1_500_000.0
_BORROWER_RWEA_FIRB = {"crr": 1_175_736.91, "b31": 985_942.90}
_BORROWER_SA_EQUIVALENT_FIRB = 1_000_000.0

#: guarantor key -> (entity_type, is_qccp, rating shape). ``None`` for is_qccp is an
#: explicit null in the input; ``None`` for the shape is no rating row at all.
_GUARANTORS: dict[str, tuple[str, bool | None, str | None]] = {
    "qccp_cqs2": ("ccp", True, "cqs2"),
    "nq_cqs3": ("ccp", False, "cqs3"),
    "null_cqs3": ("ccp", None, "cqs3"),
    "nq_unrated": ("ccp", False, None),
    "nq_internal": ("ccp", False, "internal"),
    "corp_internal": ("corporate", False, "internal"),
}

#: (guarantor key, leg) pairs that are booked.
_LEGS: tuple[tuple[str, str], ...] = (
    ("qccp_cqs2", "sa"),
    ("qccp_cqs2", "firb"),
    ("nq_cqs3", "sa"),
    ("null_cqs3", "sa"),
    ("nq_unrated", "sa"),
    ("nq_unrated", "firb"),
    ("nq_internal", "firb"),
    ("corp_internal", "firb"),
)

_GUARANTOR_INTERNAL_PD = 0.01


def _guarantor_ref(key: str) -> str:
    return f"CP_P396_{key.upper()}"


def _loan_ref(key: str, leg: str) -> str:
    return f"LN_P396_{key.upper()}_{leg.upper()}"


def _pack_weight(regime: str, ladder: str, cqs: int) -> float:
    """The SA weight of a direct exposure at ``cqs`` on ``ladder``, from the run's pack."""
    if regime == "crr":
        pack = resolve("crr", date(2026, 6, 30))
        name = "institution_rw_crr" if ladder == "institution" else "corporate_risk_weights"
        entries: dict[object, Decimal] = dict(pack.lookup(name).entries)
        return float(entries[CQS(cqs)])
    pack = resolve("b31", _REPORTING_DATE)
    if ladder == "institution":
        entries = dict(pack.lookup("institution_rw_b31_ecra").entries)
        return float(entries[CQS(cqs)])
    entries = dict(pack.lookup("b31_corporate_risk_weights").entries)
    return float(entries[cqs])


def _build_bundle() -> RawDataBundle:
    """The P1.227 borrowers plus one 100%-guaranteed loan per (guarantor, leg)."""
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
    external = ratings.filter(pl.col("counterparty_reference") == CP_G2_REF)
    rating_template = {
        "cqs2": external.with_columns(pl.lit(2).cast(ratings.schema["cqs"]).alias("cqs")),
        "cqs3": external.with_columns(pl.lit(3).cast(ratings.schema["cqs"]).alias("cqs")),
        "internal": ratings.filter(pl.col("counterparty_reference") == CP_G34_REF).with_columns(
            pl.lit(_GUARANTOR_INTERNAL_PD).alias("pd")
        ),
    }
    guarantee_template = guarantees.filter(pl.col("guarantee_reference") == GUARANTEE_G2_REF)

    new_counterparties = [
        counterparties.filter(pl.col("counterparty_reference").is_in([CP_B_REF, CP_B_IRB_REF]))
    ]
    new_ratings = [ratings.filter(pl.col("counterparty_reference").is_in([CP_B_REF, CP_B_IRB_REF]))]
    for key, (entity_type, is_qccp, shape) in _GUARANTORS.items():
        guarantor = _guarantor_ref(key)
        new_counterparties.append(
            guarantor_template.with_columns(
                pl.lit(guarantor).alias("counterparty_reference"),
                pl.lit(entity_type).alias("entity_type"),
                pl.lit(is_qccp, dtype=pl.Boolean).alias("is_qccp"),
            )
        )
        if shape is not None:
            new_ratings.append(
                rating_template[shape].with_columns(
                    pl.lit(f"RTG_{guarantor}").alias("rating_reference"),
                    pl.lit(guarantor).alias("counterparty_reference"),
                )
            )

    new_loans: list[pl.DataFrame] = []
    new_guarantees: list[pl.DataFrame] = []
    for key, leg in _LEGS:
        loan = _loan_ref(key, leg)
        new_loans.append(loan_template[leg].with_columns(pl.lit(loan).alias("loan_reference")))
        new_guarantees.append(
            guarantee_template.with_columns(
                pl.lit(f"GUAR_{loan}").alias("guarantee_reference"),
                pl.lit(_guarantor_ref(key)).alias("guarantor"),
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


def _leg_rows(results: pl.DataFrame, key: str, leg: str) -> pl.DataFrame:
    rows = results.filter(pl.col("parent_exposure_reference") == _loan_ref(key, leg))
    assert rows.height > 0, f"no result rows for {key}/{leg} - the assertions would be vacuous"
    return rows


def _covered(rows: pl.DataFrame) -> pl.DataFrame:
    covered = rows.filter(pl.col("guaranteed_portion").fill_null(0.0) > 0)
    assert covered.height == 1, "no covered leg - every assertion below would be vacuous"
    return covered


class TestQualifyingCcpTakesTheInstitutionWeight:
    """Art. 107(2)(a) + Art. 235(1): a QCCP's guarantee is an exposure to an institution."""

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_sa_leg_is_priced_on_the_institution_ladder(
        self, runs: dict[str, tuple[pl.DataFrame, list[str]]], regime: str
    ) -> None:
        results, _ = runs[regime]
        expected_rw = _pack_weight(regime, "institution", 2)
        assert expected_rw * _EAD < _BORROWER_RWEA_SA, "adequacy: the guarantee must be beneficial"

        rows = _leg_rows(results, "qccp_cqs2", "sa")

        covered = _covered(rows)
        assert covered["guarantor_rw"][0] == pytest.approx(expected_rw)
        assert covered["guarantor_exposure_class"][0] == "institution"
        assert rows["rwa_final"].sum() == pytest.approx(expected_rw * _EAD, rel=1e-9)

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_firb_leg_substitutes_the_institution_weight(
        self, runs: dict[str, tuple[pl.DataFrame, list[str]]], regime: str
    ) -> None:
        """No internal PD -> SA risk-weight substitution; the floor's SA-equivalent agrees."""
        results, _ = runs[regime]
        expected_rw = _pack_weight(regime, "institution", 2)

        rows = _leg_rows(results, "qccp_cqs2", "firb")

        covered = _covered(rows)
        assert covered["guarantor_approach"][0] == "sa"
        assert covered["guarantor_rw"][0] == pytest.approx(expected_rw)
        assert rows["rwa_final"].sum() == pytest.approx(expected_rw * _EAD, rel=1e-9)
        if regime == "b31":
            assert rows["sa_rwa"].sum() == pytest.approx(expected_rw * _EAD, rel=1e-9), (
                "the output-floor SA-equivalent must carry the institution weight too"
            )


class TestNonQualifyingCcpIsACorporate:
    """Art. 107(2)(b): a non-QCCP's guarantee is an exposure to a corporate."""

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    @pytest.mark.parametrize("key", ["nq_cqs3", "null_cqs3"], ids=["flag_false", "flag_null"])
    def test_rated_non_qccp_is_priced_on_the_corporate_ladder(
        self, runs: dict[str, tuple[pl.DataFrame, list[str]]], regime: str, key: str
    ) -> None:
        results, _ = runs[regime]
        expected_rw = _pack_weight(regime, "corporate", 3)
        assert expected_rw != _pack_weight(regime, "institution", 3), (
            "adequacy: CQS 3 must separate the corporate and institution ladders"
        )
        assert expected_rw * _EAD < _BORROWER_RWEA_SA, "adequacy: the guarantee must be beneficial"

        rows = _leg_rows(results, key, "sa")

        covered = _covered(rows)
        assert covered["guarantor_rw"][0] == pytest.approx(expected_rw)
        assert covered["guarantor_exposure_class"][0] == "corporate"
        assert rows["rwa_final"].sum() == pytest.approx(expected_rw * _EAD, rel=1e-9)

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    @pytest.mark.parametrize("leg", ["sa", "firb"])
    def test_unrated_non_qccp_is_declined(
        self, runs: dict[str, tuple[pl.DataFrame, list[str]]], regime: str, leg: str
    ) -> None:
        """Neither (h) nor (g) admits it: no guarantor RW, borrower RWEA and SA-equivalent."""
        results, crm013 = runs[regime]

        rows = _leg_rows(results, "nq_unrated", leg)

        assert rows["guarantor_rw"].is_null().all(), rows["guarantor_rw"].to_list()
        assert not rows["is_guarantee_beneficial"].fill_null(False).any()
        borrower = _BORROWER_RWEA_SA if leg == "sa" else _BORROWER_RWEA_FIRB[regime]
        assert rows["rwa_final"].sum() == pytest.approx(borrower, rel=1e-6)
        assert _loan_ref("nq_unrated", leg) in crm013
        if regime == "b31" and leg == "firb":
            assert rows["sa_rwa"].sum() == pytest.approx(_BORROWER_SA_EQUIVALENT_FIRB, rel=1e-9)

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_internally_rated_non_qccp_is_priced_as_a_corporate_guarantor(
        self, runs: dict[str, tuple[pl.DataFrame, list[str]]], regime: str
    ) -> None:
        """The internal-rating limb admits it as a corporate, exactly like its corporate twin."""
        results, _ = runs[regime]
        twin = _covered(_leg_rows(results, "corp_internal", "firb"))
        assert twin["guarantor_approach"][0] == "irb", (
            "adequacy: the corporate twin must take parameter substitution"
        )

        rows = _leg_rows(results, "nq_internal", "firb")

        covered = _covered(rows)
        twin_rows = _leg_rows(results, "corp_internal", "firb")
        assert covered["guarantor_approach"][0] == "irb"
        assert covered["guarantor_exposure_class"][0] == "corporate"
        assert rows["rwa_final"].sum() == pytest.approx(twin_rows["rwa_final"].sum(), rel=1e-9)
        if regime == "b31":
            # The output floor's SA-equivalent prices the covered part on the SA
            # ladder: an unrated corporate (100%), not the 2% the CCP branch gave.
            assert rows["sa_rwa"].sum() == pytest.approx(_BORROWER_SA_EQUIVALENT_FIRB, rel=1e-9)
            assert rows["sa_rwa"].sum() == pytest.approx(twin_rows["sa_rwa"].sum(), rel=1e-9)


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_crm013_names_exactly_the_unrated_non_qccp_legs(
    runs: dict[str, tuple[pl.DataFrame, list[str]]], regime: str
) -> None:
    """Every other CCP guarantor here is an Art. 201 provider; only the unrated non-QCCP is not."""
    _, crm013 = runs[regime]

    assert sorted(crm013) == sorted(_loan_ref("nq_unrated", leg) for leg in ("sa", "firb"))
