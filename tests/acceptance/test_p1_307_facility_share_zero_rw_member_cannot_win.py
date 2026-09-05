"""
P1.307, re-pointed — a 0%-weighted member cannot own a facility share's undrawn.

Pipeline position:
    Loader -> HierarchyResolver (candidate fan-out) -> Classifier
        -> CRMProcessor -> SACalculator -> OutputAggregator (share resolution)

What changed, and why the intent survives
-----------------------------------------
P1.307 was a defect in a PREVIEW. ``engine/hierarchy/facility_undrawn.py``
picked a facility share's owner by sorting members on an SA-only preview risk
weight built from ``entity_type``, ``cqs`` and ``country_code``, and that preview
mis-priced two entity types against the SA pricing it approximated:

    Limb A — CRR Art. 117(1): a non-named MDB "shall be treated in the same
    manner as exposures to institutions". CRR has no MDB table, so the CRR
    unrated weight is the institution one, not PS1/26's Table 2B. CRR ONLY;
    PS1/26 Art. 117(1)(a)/(b) does grant Table 2B.

    Limb B — Art. 114(3), regime-invariant: "Exposures to the ECB shall be
    assigned a 0% risk weight." ``central_bank_ecb`` fell into the generic CGCB
    bucket and previewed at the unrated 100% — the top of this book — so the ECB
    took the whole undrawn commitment and was then priced at its true 0%,
    publishing zero RWEA against 4,000,000 of exposure.

**The preview is deleted** (design of record D5). The hierarchy stage now emits
one candidate row per member; each is classified, CRM-adjusted and PRICED as an
ordinary exposure of its own member; and the aggregator keeps the one with the
largest RWA its own applied approach produced. So both limbs' intent is served
structurally rather than by a corrected approximation:

- **Limb B is now unfalsifiable in the good direction.** A 0%-weighted member's
  own RWA is exactly zero, and zero cannot be the maximum of a set containing a
  positive. The ECB cannot swallow a share whatever the pack says about it.
- **Limb A no longer has a place to be wrong.** Nothing approximates the MDB's
  weight; the MDB candidate is priced by the SA branch that would price it if it
  owned the row, which is the same code either way.

What this module therefore asserts is the RESOLVER's outcome — which member owns
the surviving ``<facility>_UNDRAWN`` row and at what weight — not a preview
value. The expression-level pins are gone with the expression
(``tests/unit/test_entity_rw_preview.py``, deleted); the hierarchy-stage pins are
``tests/unit/test_hierarchy.py::TestFacilityShareFanOutIsEntityTypeBlind``.

The ranking rule and this portfolio's floor state
-------------------------------------------------
Design of record D1/D2: under CRR the winner is ``argmax`` own-approach RWA
(policy P0). Under Basel 3.1 with the floor applicable the rule is P2 — evaluate
the own-approach assignment A and the floored-branch assignment B end to end and
keep the larger TREA, ties to A.

**MEASURED on this portfolio, not assumed:** every row runs
``PermissionMode.STANDARDISED``, so there is no floor-eligible row at all,
U-TREA and S-TREA are both 0.00 and ``portfolio_floor_binding`` is False. Under
that state every candidate's floored-branch marginal ``b_i`` equals its own
``u_i`` (a standardised member sits outside the max at full weight), assignments
A and B pick the same member in every group, and P2 collapses onto P0. That is
asserted by ``test_the_output_floor_does_not_bind_on_this_portfolio`` before any
winner is read, because the whole Basel 3.1 arm's derivation rests on it.

Expected winners, derived from the pack (see the module constants)
------------------------------------------------------------------
``F-ECB-SHARE`` — 8,000,000 headroom at the MR 50% conversion factor, so each
candidate carries EAD 4,000,000, both regimes:

    CP-ECB      central_govt_central_bank   0%     ->        0.00
    CP-CORP-A   corporate CQS 1            20%     ->  800,000.00   WINNER

``F-MDB-SHARE`` — 800,000 headroom, EAD 400,000 per candidate:

    CRR   CP-MDB      mdb, Art. 117(1) unrated institution  100%  -> 400,000  WINNER
          CP-RETAIL   retail_other, Art. 123                 75%  -> 300,000
    B31   CP-MDB      mdb, Table 2B unrated                  50%  -> 200,000
          CP-RETAIL   corporate, unrated                    100%  -> 400,000  WINNER

The winner is the SAME member as the old preview-corrected expectation in every
one of the four cells, so nothing flips. The Basel 3.1 MDB share's REASON does
change and is worth stating: the retail member used to win because its preview
75% beat Table 2B's 50%; it now wins because its candidate is classified
``corporate`` unrated at 100% by the Art. 123A granularity limb and prices at
400,000 against the MDB's 200,000. At the retail 75% it would price at 300,000
and still win, so the outcome does not depend on that classification — only the
asserted risk weight does.

Direction: RWA-INCREASING on ``F-ECB-SHARE`` relative to the pre-P1.307 engine
(0 -> 800,000 of RWEA), unchanged relative to the P1.307 fix.

RED until the S3 aggregator resolution lands. Today the hierarchy fan-out emits
both candidates and nothing drops the loser, so there is no
``<facility>_UNDRAWN`` row at all and ``AggregatedResultBundle`` carries no
``facility_share_resolution`` frame.

References:
    - CRR Art. 114(3) / PRA PS1/26 Art. 114(3) — the ECB, 0% unconditional
      (pack: ``ecb_zero_rw``, common pack, deliberately not Feature-gated)
    - CRR Art. 117(1) — non-named MDBs take the institution treatment
      (pack: ``institution_rw_crr``); PS1/26 Art. 117(1)(a)/(b) Table 2B
      (pack: ``mdb_unrated_rw``) is the Basel 3.1 divergence
    - CRR Art. 122 Table 5 / PS1/26 Art. 122(2) Table 6 — corporate CQS 1 20%,
      unrated 100%
    - CRR Art. 123 — the regulatory retail 75% (pack: ``retail_risk_weight``)
    - CRR Art. 111 / PS1/26 Art. 111 Table A1 — the 50% commitment conversion
      factor that turns headroom into EAD
    - docs/plans/facility-share-riskiest-member.md — D1, D2, D5 and Section 6
    - tests/unit/test_hierarchy.py::TestFacilityShareFanOutIsEntityTypeBlind
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig, PermissionMode
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    COUNTERPARTY_SCHEMA,
    FACILITY_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)
from rwa_calc.domain.enums import CQS
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.rulebook.resolve import resolve
from tests.fixtures.raw_bundle import make_raw_bundle

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import RawDataBundle

# ---------------------------------------------------------------------------
# Scenario constants
# ---------------------------------------------------------------------------

_REPORTING_DATE = date(2027, 6, 30)
_MATURITY = date(2032, 6, 30)

_ECB_SHARE = "F-ECB-SHARE"
_MDB_SHARE = "F-MDB-SHARE"

# (counterparty_reference, entity_type, cqs | None)
_COUNTERPARTIES: tuple[tuple[str, str, int | None], ...] = (
    ("CP-ECB", "central_bank_ecb", None),
    ("CP-CORP-A", "corporate", 1),
    ("CP-MDB", "mdb", None),
    ("CP-RETAIL", "retail", None),
)

# Every share carries TWO drawn members. The facility's own counterparty is the
# first of them, so it is both the OWNER and a descendant counterparty — under
# decision D3 the owner is always a member, and here the two halves of the
# member union overlap rather than adding a third candidate.
_SHARES: tuple[tuple[str, tuple[str, str], float, float], ...] = (
    # reference, members, facility limit, drawn per member
    (_ECB_SHARE, ("CP-ECB", "CP-CORP-A"), 10_000_000.0, 1_000_000.0),
    # The MDB share is deliberately small: it keeps CP-RETAIL inside the
    # Art. 123 retail limits under CRR, so its candidate prices at the retail
    # 75% rather than a corporate fallback and the 100% MDB winner is a
    # DISCRIMINATING risk weight rather than a coincidence.
    (_MDB_SHARE, ("CP-MDB", "CP-RETAIL"), 1_000_000.0, 100_000.0),
)

# Undrawn headroom x the MR commitment conversion factor (50%) — regime-invariant
# on this portfolio, and asserted rather than assumed by
# ``test_undrawn_rows_carry_a_priced_exposure``.
_ECB_SHARE_EAD: float = 4_000_000.0
_MDB_SHARE_EAD: float = 400_000.0

# ---------------------------------------------------------------------------
# Expected risk weights — read back from the resolved rulepack, never typed
# ---------------------------------------------------------------------------
#
# Every weight below is looked up from the pack that ``resolve(regime, date)``
# hands the engine, so a pack change moves the test and the engine together and
# neither can drift onto a number the other does not use (LESSONS A4). The CQS
# tables for institutions live only in the CRR pack; ``guarantor_rw`` binds them
# from there for both regimes.

_CRR_PACK = resolve("crr", date(2026, 1, 1))
_B31_PACK = resolve("b31", date(2027, 1, 1))

#: Art. 122 Table 5 / PS1/26 Art. 122(2) Table 6, CQS 1 — 20% in both regimes.
_CORPORATE_CQS1_RW: dict[str, float] = {
    "crr": float(dict(_CRR_PACK.lookup("corporate_risk_weights").entries)[CQS.CQS1]),
    "b31": float(dict(_B31_PACK.lookup("b31_corporate_risk_weights").entries)[1]),
}
#: PS1/26 Art. 122(2) Table 6, unrated — where the Basel 3.1 retail candidate
#: lands once the Art. 123A granularity limb routes it out of retail.
_B31_UNRATED_CORPORATE_RW: float = float(
    dict(_B31_PACK.lookup("b31_corporate_risk_weights").entries)[None]
)
#: Art. 117(1) -> Art. 121: the CRR unrated institution weight a non-named MDB
#: takes, there being no CRR MDB table.
_CRR_UNRATED_INSTITUTION_RW: float = float(
    dict(_CRR_PACK.lookup("institution_rw_crr").entries)[CQS.UNRATED]
)
#: PS1/26 Art. 117(1)(a)/(b) Table 2B, unrated — the Basel 3.1 MDB weight.
_B31_UNRATED_MDB_RW: float = float(_B31_PACK.scalar("mdb_unrated_rw"))
#: Art. 123 regulatory retail, the weight the CRR retail candidate loses at.
_CRR_RETAIL_RW: float = float(_CRR_PACK.scalar("retail_risk_weight"))
#: Art. 114(3), both regimes. Read per regime so a regime-gated pack entry
#: could not make one arm silently non-zero.
_ECB_RW: dict[str, float] = {
    "crr": float(_CRR_PACK.scalar("ecb_zero_rw")),
    "b31": float(_B31_PACK.scalar("ecb_zero_rw")),
}

#: The ranking metric, derived: EAD x own-approach risk weight, per candidate.
#: Stated as a table so the argmax is read off the derivation rather than
#: transcribed from a run.
_OWN_APPROACH_RWA: dict[str, dict[str, dict[str, float]]] = {
    "crr": {
        _ECB_SHARE: {
            "CP-ECB": _ECB_SHARE_EAD * _ECB_RW["crr"],
            "CP-CORP-A": _ECB_SHARE_EAD * _CORPORATE_CQS1_RW["crr"],
        },
        _MDB_SHARE: {
            "CP-MDB": _MDB_SHARE_EAD * _CRR_UNRATED_INSTITUTION_RW,
            "CP-RETAIL": _MDB_SHARE_EAD * _CRR_RETAIL_RW,
        },
    },
    "b31": {
        _ECB_SHARE: {
            "CP-ECB": _ECB_SHARE_EAD * _ECB_RW["b31"],
            "CP-CORP-A": _ECB_SHARE_EAD * _CORPORATE_CQS1_RW["b31"],
        },
        _MDB_SHARE: {
            "CP-MDB": _MDB_SHARE_EAD * _B31_UNRATED_MDB_RW,
            "CP-RETAIL": _MDB_SHARE_EAD * _B31_UNRATED_CORPORATE_RW,
        },
    },
}

_FACILITY_MAPPING_SCHEMA = {
    "parent_facility_reference": pl.String,
    "child_reference": pl.String,
    "child_type": pl.String,
}


def _winner(regime: str, share: str) -> str:
    """The member with the largest own-approach RWA, derived from the pack."""
    candidates = _OWN_APPROACH_RWA[regime][share]
    return max(candidates, key=lambda member: candidates[member])


def _build_bundle() -> RawDataBundle:
    """Two facility shares, each with two drawn loan members and real headroom."""
    counterparties = [
        {
            "counterparty_reference": ref,
            "counterparty_name": f"P1.307 {ref}",
            "entity_type": entity_type,
            "country_code": "GB",
            "default_status": False,
            "is_financial_sector_entity": False,
            "apply_fi_scalar": False,
        }
        for ref, entity_type, _cqs in _COUNTERPARTIES
    ]
    ratings = [
        {
            "rating_reference": f"RTG-{ref}",
            "counterparty_reference": ref,
            "rating_type": "external",
            "rating_agency": "Moody's",
            "cqs": cqs,
            "pd": None,
            "rating_date": _REPORTING_DATE,
        }
        for ref, _entity_type, cqs in _COUNTERPARTIES
        if cqs is not None
    ]

    facilities, loans, mappings = [], [], []
    for facility_reference, members, limit, drawn in _SHARES:
        facilities.append(
            {
                "facility_reference": facility_reference,
                # The facility's own counterparty is the first member, so the
                # owner is inside the member union rather than beside it.
                "counterparty_reference": members[0],
                "currency": "GBP",
                "value_date": _REPORTING_DATE,
                "maturity_date": _MATURITY,
                "limit": limit,
                "committed": True,
                "seniority": "senior",
                "risk_type": "MR",
                "product_type": "RCF",
            }
        )
        for member in members:
            loan_reference = f"L-{facility_reference}-{member}"
            loans.append(
                {
                    "loan_reference": loan_reference,
                    "counterparty_reference": member,
                    "currency": "GBP",
                    "value_date": _REPORTING_DATE,
                    "maturity_date": _MATURITY,
                    "drawn_amount": drawn,
                    "interest": 0.0,
                    "seniority": "senior",
                    "product_type": "TERM_LOAN",
                }
            )
            mappings.append(
                {
                    "parent_facility_reference": facility_reference,
                    "child_reference": loan_reference,
                    "child_type": "loan",
                }
            )

    return make_raw_bundle(
        facilities=pl.DataFrame(facilities, schema=dtypes_of(FACILITY_SCHEMA)),
        loans=pl.DataFrame(loans, schema=dtypes_of(LOAN_SCHEMA)),
        counterparties=pl.DataFrame(counterparties, schema=dtypes_of(COUNTERPARTY_SCHEMA)),
        facility_mappings=pl.DataFrame(mappings, schema=_FACILITY_MAPPING_SCHEMA),
        ratings=pl.DataFrame(ratings, schema=dtypes_of(RATINGS_SCHEMA)),
    )


@dataclass(frozen=True)
class Run:
    """One regime's run, read into plain Python so absence stays visible.

    The fixture that builds this does NOT assert. Every claim about the run is
    made on an assertion line inside a test body, because pytest reports a
    fixture-setup failure as an ERROR — and an error is indistinguishable in a
    summary from an ``ImportError`` or a broken builder, which is exactly the
    signal a red test wave must not send.
    """

    regime: str
    undrawn: dict[str, dict[str, Any]]
    references: tuple[str, ...]
    contract_violations: tuple[str, ...]
    resolution: list[dict[str, Any]] | None
    summary: Any

    def share_row(self, share: str) -> dict[str, Any]:
        """The one surviving undrawn row of ``share``, asserted present first."""
        reference = f"{share}_UNDRAWN"
        assert reference in self.undrawn, (
            f"{reference} is absent from the results under {self.regime}; the "
            f"undrawn rows present are {sorted(self.undrawn)} - a candidate "
            "reference means the losers were never dropped, and no row at all "
            "means the share was dropped outright"
        )
        return self.undrawn[reference]

    def candidates(self, share: str) -> dict[str, dict[str, Any]]:
        """The audit frame's rows for one share, keyed by member."""
        assert self.resolution is not None, (
            "AggregatedResultBundle carries no facility_share_resolution frame, "
            "so nothing here observes which member was chosen or why - RED until "
            "the S3 aggregator resolution lands"
        )
        return {
            row["counterparty_reference"]: row
            for row in self.resolution
            if row["facility_share_group"] == share
        }


def _run(regime: str, config: CalculationConfig) -> Run:
    """Run the shared book and read back the surviving undrawn rows."""
    result = PipelineOrchestrator().run_with_data(_build_bundle(), config)
    rows = result.results.collect().to_dicts()
    resolution_frame = getattr(result, "facility_share_resolution", None)
    return Run(
        regime=regime,
        undrawn={
            row["exposure_reference"]: row
            for row in rows
            if row["exposure_type"] == "facility_undrawn"
        },
        references=tuple(str(row["exposure_reference"]) for row in rows),
        contract_violations=tuple(
            error.message for error in result.errors if "contract violated" in error.message
        ),
        resolution=None if resolution_frame is None else resolution_frame.collect().to_dicts(),
        summary=result.output_floor_summary,
    )


@pytest.fixture(scope="module")
def crr_run() -> Run:
    """CRR run of the shared facility-share book."""
    return _run(
        "crr",
        CalculationConfig.crr(
            reporting_date=_REPORTING_DATE,
            permission_mode=PermissionMode.STANDARDISED,
        ),
    )


@pytest.fixture(scope="module")
def b31_run() -> Run:
    """Basel 3.1 run of the shared facility-share book."""
    return _run(
        "b31",
        CalculationConfig.basel_3_1(
            reporting_date=_REPORTING_DATE,
            permission_mode=PermissionMode.STANDARDISED,
        ),
    )


@pytest.fixture(scope="module")
def runs(crr_run: Run, b31_run: Run) -> dict[str, Run]:
    """Both regimes' runs, keyed by regime label."""
    return {"crr": crr_run, "b31": b31_run}


class TestFacilityShareOwnershipUnderTheOwnApproachMetric:
    """Which member owns the surviving undrawn row, and at what weight."""

    # --- presence, before any value ----------------------------------------

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_exactly_one_undrawn_row_survives_per_share(
        self, runs: dict[str, Run], regime: str
    ) -> None:
        """
        Each share emits ONE undrawn row, under its bare facility reference.

        Arrange: the two-share book under the named regime.
        Act:     read every ``facility_undrawn`` row of the sealed results.
        Assert:  exactly the two bare ``<facility>_UNDRAWN`` references, and no
                 ``@<member>`` reference anywhere in the frame.

        Set equality, not containment. Three different defects land here and the
        message distinguishes them: no row at all means the share was dropped
        outright (this estate's dominant escape class); two rows for one share
        mean the losing candidate was never dropped and the commitment is
        capitalised twice; an ``@`` reference surviving means the winner's
        reference was not collapsed, which silently re-keys the row for COREP,
        Pillar 3 and reconciliation — all of which key on this string, and the
        aggregator-exit invariant is one undrawn row per facility.

        Also checks the edge-contract error channel: a dtype violation on a
        sealed edge reddens the whole acceptance suite and would otherwise be
        misread as a facility-share finding (LESSONS D3).
        """
        # Arrange / Act
        run = runs[regime]

        # Assert — attribution first, then presence, then the reference grammar.
        assert not run.contract_violations, run.contract_violations
        assert set(run.undrawn) == {
            f"{_ECB_SHARE}_UNDRAWN",
            f"{_MDB_SHARE}_UNDRAWN",
        }, sorted(run.undrawn)
        assert not [reference for reference in run.references if "@" in reference], (
            "a candidate reference survived to the sealed exit"
        )

    # --- adequacy: the fixture can express the rule it is used to test ------

    def test_the_output_floor_does_not_bind_on_this_portfolio(self, b31_run: Run) -> None:
        """
        Adequacy: the Basel 3.1 floor is inapplicable here, so P2 collapses to P0.

        Arrange: the Basel 3.1 run.
        Act:     read the output-floor summary.
        Assert:  no floor-eligible exposure, no shortfall, not binding.

        Asserted BEFORE any Basel 3.1 winner is read, because the whole B31 arm's
        derivation rests on it. Every row here runs ``PermissionMode.STANDARDISED``,
        so U-TREA and S-TREA are 0.00 and there is nothing for the floor to bind
        against. Under that state a standardised candidate's floored-branch
        marginal equals its own-approach RWA, assignments A and B pick the same
        member in every group, and the floor-aware default reduces to the
        own-approach rule this module asserts.

        If a later edit gave this book an IRB member, the floor could bind and
        the Basel 3.1 winners would have to be re-derived under the two-assignment
        rule. That is what this assertion exists to force.
        """
        # Arrange / Act
        summary = b31_run.summary

        # Assert
        assert summary is not None, "the Basel 3.1 run produced no output-floor summary"
        assert summary.portfolio_floor_binding is False
        assert summary.shortfall == 0.0
        assert summary.u_trea == 0.0, (
            f"u_trea is {summary.u_trea:,.2f}, so this portfolio HAS a "
            "floor-eligible row and the P2 two-assignment rule is live; the "
            "winners below are derived under P0 and must be re-derived"
        )

    # --- the vacuity guard -------------------------------------------------

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    @pytest.mark.parametrize(
        ("share", "expected_ead"),
        [(_ECB_SHARE, _ECB_SHARE_EAD), (_MDB_SHARE, _MDB_SHARE_EAD)],
    )
    def test_undrawn_rows_carry_a_priced_exposure(
        self,
        runs: dict[str, Run],
        regime: str,
        share: str,
        expected_ead: float,
    ) -> None:
        """
        Every surviving undrawn row carries a non-null, non-zero exposure.

        Arrange: the two-share book under the named regime.
        Act:     read the surviving synthetic undrawn rows.
        Assert:  counterparty, EAD, conversion factor, risk weight and RWEA are
                 all populated, and the EAD is the full headroom at the 50%
                 commitment conversion factor.

        The vacuity guard, and unchanged in intent by the re-pointing. A null
        weight and a legitimate 0% weight are different claims, and a share that
        lost its EAD in the resolution would make every ownership assertion below
        meaningless. The EAD is asserted rather than assumed because the winner
        must carry the WHOLE headroom: each candidate is priced "as if this member
        drew it all", so a resolution that pro-rated the survivor would leave the
        ownership assertions green on a fraction of the commitment.
        """
        # Arrange / Act
        row = runs[regime].share_row(share)

        # Assert
        assert row["counterparty_reference"] is not None
        assert row["risk_weight"] is not None
        assert row["rwa_final"] is not None
        assert row["ccf"] is not None
        assert row["ead_final"] == pytest.approx(expected_ead)
        assert row["facility_share_group"] == share, (
            "the surviving winner must keep its group to reporting, so a reader "
            "of the sealed ledger can tell an allocated undrawn from an ordinary one"
        )
        assert row["is_facility_share_candidate"] is False, (
            "a True flag at the sealed exit means a losing candidate survived the resolution"
        )

    # --- limb B: the ECB, both regimes -------------------------------------

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_ecb_share_undrawn_is_owned_and_priced_by_the_corporate(
        self, runs: dict[str, Run], regime: str
    ) -> None:
        """
        Art. 114(3): the ECB prices at 0% and cannot be the argmax, either regime.

        Arrange: a share between an unrated ECB and a CQS-1 corporate, each
                 candidate carrying the full 4,000,000 of EAD.
        Act:     run the full pipeline under the named regime and read the
                 surviving undrawn row.
        Assert:  it belongs to CP-CORP-A, is classified corporate, and is priced
                 at the Art. 122 CQS-1 20%.

        Derivation, from pack values only:
            CP-ECB      4,000,000 x ``ecb_zero_rw``           = 0.00
            CP-CORP-A   4,000,000 x corporate CQS 1 (20%)     = 800,000.00
        so ``argmax`` is CP-CORP-A by 800,000.00 — the entire book of the loser.

        This is P1.307 limb B's intent, and it is now structural rather than
        corrective: zero cannot be the maximum of a set containing a positive, so
        no pack change, no classification change and no CRM can make the ECB win
        this share. Under the deleted preview the ECB won on a 100% approximation
        and the row was then priced at its true 0%, publishing nothing.

        Run ``-k crr`` and ``-k b31`` separately — one red across a both-regimes
        parametrisation proves one regime, not two.
        """
        # Arrange
        run = runs[regime]
        expected = _winner(regime, _ECB_SHARE)
        assert expected == "CP-CORP-A", "the derivation no longer names the corporate"

        # Act
        row = run.share_row(_ECB_SHARE)

        # Assert — ownership, classification and the priced weight together.
        assert row["counterparty_reference"] == expected
        assert row["original_counterparty_reference"] == "CP-ECB"
        assert row["exposure_class"] == "corporate"
        assert row["risk_weight"] == pytest.approx(_CORPORATE_CQS1_RW[regime])
        assert row["rwa_final"] == pytest.approx(_OWN_APPROACH_RWA[regime][_ECB_SHARE][expected])

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_the_zero_weighted_ecb_candidate_is_ranked_and_rejected(
        self, runs: dict[str, Run], regime: str
    ) -> None:
        """
        The ECB is a candidate that LOSES, not a member that was never offered.

        Arrange: the same share under the named regime.
        Act:     read the per-candidate resolution frame.
        Assert:  both members appear, the ECB's own RWA is exactly 0.00, and it
                 is not the winner.

        Losing on merit and being excluded up front look identical in the results
        frame and are different behaviours. The design admits every member to the
        ranking on purpose — a member silently dropped before it is priced is the
        exact failure the deleted preview had when the counterparty lookup was
        thin — so the audit frame is where that distinction is observable.

        It is also the breakdown-to-parent tie: the frame must name exactly one
        winner per group and that winner must be the member on the surviving row,
        or the audit trail and the ledger disagree about the same allocation.
        """
        # Arrange
        run = runs[regime]

        # Act
        candidates = run.candidates(_ECB_SHARE)

        # Assert — the set, then the loser's number, then the tie to the ledger.
        assert set(candidates) == {"CP-ECB", "CP-CORP-A"}, sorted(candidates)
        assert "rwa_pre_floor" in candidates["CP-ECB"], (
            "the resolution frame does not carry rwa_pre_floor, so the metric "
            "the winner was chosen on is not auditable"
        )
        assert candidates["CP-ECB"]["rwa_pre_floor"] == pytest.approx(0.0)
        assert candidates["CP-ECB"]["is_winner"] is False
        winners = [member for member, row in candidates.items() if row["is_winner"]]
        assert winners == ["CP-CORP-A"], winners
        assert winners[0] == run.share_row(_ECB_SHARE)["counterparty_reference"]

    # --- limb A: non-named MDB, CRR --------------------------------------

    def test_mdb_share_undrawn_is_owned_and_priced_by_the_mdb_under_crr(self, crr_run: Run) -> None:
        """
        Art. 117(1): the unrated non-named MDB outprices retail under CRR.

        Arrange: a share between an unrated ``mdb`` and a ``retail`` obligor,
                 sized to keep the retail leg inside the Art. 123 limits.
        Act:     run the full CRR pipeline.
        Assert:  the surviving undrawn row belongs to CP-MDB, is classified
                 ``mdb``, and is priced at the CRR unrated institution weight.

        Derivation, from pack values only:
            CP-MDB      400,000 x ``institution_rw_crr[UNRATED]`` (100%) = 400,000
            CP-RETAIL   400,000 x ``retail_risk_weight``           (75%) = 300,000
        so ``argmax`` is CP-MDB by 100,000.00, a third of the loser's RWA. The
        margin is wide enough that no tie-break is exercised, which is why the
        share is sized to keep the retail leg regulatory-retail: at a corporate
        fallback both would price at 100% and the winner would ride on the
        reference tie-break instead of on the metric.

        Same member as the P1.307 fix chose, by a different mechanism: the
        preview approximated Art. 117(1) and got CRR wrong; the candidate is now
        priced by the SA branch that would price it if it owned the row.
        """
        # Arrange
        expected = _winner("crr", _MDB_SHARE)
        assert expected == "CP-MDB", "the derivation no longer names the MDB"

        # Act
        row = crr_run.share_row(_MDB_SHARE)

        # Assert
        assert row["counterparty_reference"] == expected
        assert row["exposure_class"] == "mdb"
        assert row["risk_weight"] == pytest.approx(_CRR_UNRATED_INSTITUTION_RW)
        assert row["rwa_final"] == pytest.approx(_OWN_APPROACH_RWA["crr"][_MDB_SHARE][expected])
        # The loser's own RWA is what it lost by, and it must be the retail 75%.
        assert crr_run.candidates(_MDB_SHARE)["CP-RETAIL"]["rwa_pre_floor"] == pytest.approx(
            _MDB_SHARE_EAD * _CRR_RETAIL_RW
        )

    # --- limb A's scope: the same share under Basel 3.1 ---------------------

    def test_mdb_share_undrawn_stays_with_retail_under_basel_3_1(self, b31_run: Run) -> None:
        """
        The Basel 3.1 arm keeps CP-RETAIL — Table 2B holds the MDB at 50%.

        Arrange: the identical share.
        Act:     run the full Basel 3.1 pipeline.
        Assert:  the surviving undrawn row belongs to CP-RETAIL, and the MDB
                 candidate's own RWA is the Table 2B unrated 50%.

        Derivation, from pack values only:
            CP-MDB      400,000 x ``mdb_unrated_rw``             (50%)  = 200,000
            CP-RETAIL   400,000 x unrated corporate Table 6     (100%)  = 400,000
        so ``argmax`` is CP-RETAIL by 200,000.00.

        **The winner is unchanged from the P1.307 expectation; the reason is
        not, and the difference is worth stating.** Under the preview CP-RETAIL
        won because retail's approximated 75% beat Table 2B's 50%. Under the
        applied-approach metric its CANDIDATE is classified ``corporate`` unrated
        at 100% — the Art. 123A(1)(b)(ii) granularity limb, which is Basel 3.1
        only and has nothing to do with facility shares — and wins at 400,000.
        At the retail 75% it would price at 300,000 and still beat the MDB's
        200,000, so ownership does not depend on that classification. Only the
        asserted class and weight do, which is why they are asserted here
        together rather than ownership alone: a change that moved the retail
        candidate's class should redden a test that names it, not pass silently
        under a bare ownership check.

        This also pins limb A's CRR-only scope end to end: the same two members
        give CP-MDB under CRR and CP-RETAIL under Basel 3.1, because
        PS1/26 Art. 117(1)(a)/(b) grants Table 2B where CRR Art. 117(1) sends the
        MDB to the institution treatment.
        """
        # Arrange
        expected = _winner("b31", _MDB_SHARE)
        assert expected == "CP-RETAIL", "the derivation no longer names the retail obligor"

        # Act
        row = b31_run.share_row(_MDB_SHARE)
        candidates = b31_run.candidates(_MDB_SHARE)

        # Assert — ownership, then the class and weight it won at.
        assert row["counterparty_reference"] == expected
        assert row["exposure_class"] == "corporate"
        assert row["risk_weight"] == pytest.approx(_B31_UNRATED_CORPORATE_RW)
        assert row["rwa_final"] == pytest.approx(_OWN_APPROACH_RWA["b31"][_MDB_SHARE][expected])
        # The MDB loses at Table 2B, which is the limb-A divergence itself.
        assert candidates["CP-MDB"]["rwa_pre_floor"] == pytest.approx(
            _MDB_SHARE_EAD * _B31_UNRATED_MDB_RW
        )
        assert candidates["CP-MDB"]["is_winner"] is False
