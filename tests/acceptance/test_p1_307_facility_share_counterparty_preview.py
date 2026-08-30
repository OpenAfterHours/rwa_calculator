"""
P1.307 — the entity-RW preview decides who OWNS a facility share's undrawn EAD.

Pipeline position:
    Loader -> HierarchyResolver (facility-share selection) -> Classifier
        -> CRMProcessor -> SACalculator -> OutputAggregator

Why this test exists at the pipeline level rather than only as a unit pin:
    ``engine/sa/guarantor_rw.py::build_entity_rw_expr`` computes a preview risk
    weight whose ONLY consumer is
    ``engine/hierarchy/facility_undrawn.py::
    _derive_facility_share_counterparty``. That helper sorts candidates on the
    preview descending and takes ``.first()`` inside a ``group_by().agg()`` —
    the agg drops the column but consumes its ordering, and the winner becomes
    ``share_counterparty_reference``, coalesced onto the synthetic undrawn
    row's ``counterparty_reference``. So the preview's value never leaves the
    hierarchy stage, but the obligor it selects flows on into classification,
    CRM, the SA/IRB branch and the SA-equivalent RW feeding the Basel 3.1
    output floor. A rank inversion in the preview therefore prices the whole
    undrawn commitment against the wrong obligor at that obligor's TRUE risk
    weight — which is exactly how a 0%-weighted ECB can swallow a facility
    share and publish zero RWEA against it.

The two limbs under test:

    **Limb A — non-named MDB, CRR ARM ONLY.** UK CRR Art. 117(1) (crr.pdf
    p.115) verbatim:
        "Exposures to multilateral development banks that are not referred to
        in paragraph 2 shall be treated in the same manner as exposures to
        institutions."
    CRR has no MDB risk-weight table at all. The preview nevertheless applies
    PS1/26's Table 2B unconditionally, so an unrated non-named MDB previews at
    50% where the CRR institution treatment (Art. 121 unrated) gives 100%.
    Under Basel 3.1, PS1/26 Art. 117(1)(a)/(b) DOES grant Table 2B, so the
    whole B31 arm is correct today and must not move.

    **Limb B — the ECB, BOTH regimes.** Art. 114(3) is regime-invariant; CRR
    (crr.pdf p.111) and PS1/26 (ps126app1.pdf p.35) both read:
        "Exposures to the ECB shall be assigned a 0% risk weight."
    ``central_bank_ecb`` currently falls into the generic CGCB Table 1 bucket
    and previews at its CQS weight — unrated 100%, the top of this portfolio's
    book — while the SA pricing that ultimately applies to the row it wins is
    the true 0% (``engine/sa/central_bank.py::is_ecb_expr``).

Direction: RWA-INCREASING. Selection takes ``argmax(preview)`` and then prices
at the winner's TRUE weight, which is bounded above by ``max(true)``; a preview
corrected downwards can therefore only raise the weight actually applied.

Measured movement on this portfolio (EAD is regime-invariant):
    F-ECB-SHARE_UNDRAWN (EAD 4,000,000, both regimes)
        pre  CP-ECB     central_govt_central_bank  RW 0.00  RWEA         0
        post CP-CORP-A  corporate                  RW 0.20  RWEA   800,000
    F-MDB-SHARE_UNDRAWN (EAD 400,000)
        CRR pre  CP-RETAIL  retail_other  RW 0.75  RWEA 300,000
        CRR post CP-MDB     mdb           RW 1.00  RWEA 400,000
        B31 pre == post: CP-RETAIL (limb A is CRR-only)

References:
    - CRR Art. 114(3) / PRA PS1/26 Art. 114(3) — the ECB, 0% unconditional
      (pack: ``ecb_zero_rw``, common pack, deliberately not Feature-gated)
    - CRR Art. 117(1) — non-named MDBs take the institution treatment
      (pack: ``institution_rw_crr``); PRA PS1/26 Art. 117(1)(a)/(b) Table 2B
      (pack: ``mdb_risk_weights_table_2b``) is the Basel 3.1 divergence
    - CRR Art. 122 Table 5 / PS1/26 Art. 122(2) Table 6 — corporate CQS 1, 20%
      in both regimes
    - tests/unit/test_entity_rw_preview.py — the expression-level pins
    - tests/unit/test_hierarchy.py::TestP1307FacilityShareEntityPreview — the
      share-ownership pins, including the both-limbs half-fix discriminator
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

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

# Every share carries TWO drawn members, so neither is dropped by the
# ``_member_count > 1`` filter — a share whose only interesting member is the
# entity under test collapses to a single candidate and is discarded entirely,
# which would make every ownership assertion below pass for the wrong reason.
_SHARES: tuple[tuple[str, tuple[str, str], float, float], ...] = (
    # reference, members, facility limit, drawn per member
    (_ECB_SHARE, ("CP-ECB", "CP-CORP-A"), 10_000_000.0, 1_000_000.0),
    # The MDB share is deliberately small: it keeps CP-RETAIL inside the
    # Art. 123 retail limits under CRR, so the pre-fix weight is the retail
    # 75% rather than a corporate fallback, and the post-fix 100% is a
    # DISCRIMINATING risk weight rather than a coincidence.
    (_MDB_SHARE, ("CP-MDB", "CP-RETAIL"), 1_000_000.0, 100_000.0),
)

# Undrawn headroom x the MR commitment CCF (50%) — regime-invariant.
_ECB_SHARE_EAD: float = 4_000_000.0
_MDB_SHARE_EAD: float = 400_000.0

# ---------------------------------------------------------------------------
# Expected risk weights — read back from the resolved rulepack, never typed
# ---------------------------------------------------------------------------
#
# The CQS RW tables live only in the CRR pack (``resolve("b31", …)`` has no
# ``institution_rw_crr``), and ``guarantor_rw`` binds them from there for both
# regimes; the Basel 3.1 corporate Table 6 is the one entry with a B31 home.

_CRR_PACK = resolve("crr", date(2026, 1, 1))
_B31_PACK = resolve("b31", date(2027, 1, 1))

# Art. 122 Table 5 / PS1/26 Art. 122(2) Table 6, CQS 1 — 20% in both regimes.
_CORPORATE_CQS1_RW: dict[str, float] = {
    "crr": float(dict(_CRR_PACK.lookup("corporate_risk_weights").entries)[CQS.CQS1]),
    "b31": float(dict(_B31_PACK.lookup("b31_corporate_risk_weights").entries)[1]),
}
# Art. 117(1) -> Art. 121: the CRR unrated institution weight a non-named MDB
# inherits once the preview stops handing it PS1/26's Table 2B.
_CRR_UNRATED_INSTITUTION_RW: float = float(
    dict(_CRR_PACK.lookup("institution_rw_crr").entries)[CQS.UNRATED]
)

_FACILITY_MAPPING_SCHEMA = {
    "parent_facility_reference": pl.String,
    "child_reference": pl.String,
    "child_type": pl.String,
}


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
                # The facility's own counterparty is the first member; the
                # share override must be able to move ownership off it.
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


def _run(config: CalculationConfig) -> dict[str, dict]:
    """Run the shared book and return the two synthetic undrawn rows by reference."""
    result = PipelineOrchestrator().run_with_data(_build_bundle(), config)
    # An edge-contract violation reddens results wholesale and would otherwise
    # be misread as a P1.307 finding.
    assert not [error for error in result.errors if "contract violated" in error.message]
    rows = {
        row["exposure_reference"]: row
        for row in result.results.collect().to_dicts()
        if row["exposure_type"] == "facility_undrawn"
    }
    # Presence: both shares must EMIT an undrawn row. A share dropped by the
    # ``_member_count > 1`` filter produces no row at all, and absence is this
    # project's dominant escape class.
    assert set(rows) == {f"{_ECB_SHARE}_UNDRAWN", f"{_MDB_SHARE}_UNDRAWN"}, sorted(rows)
    return rows


@pytest.fixture(scope="module")
def crr_rows() -> dict[str, dict]:
    """CRR undrawn rows for the shared facility-share book."""
    return _run(
        CalculationConfig.crr(
            reporting_date=_REPORTING_DATE,
            permission_mode=PermissionMode.STANDARDISED,
        )
    )


@pytest.fixture(scope="module")
def b31_rows() -> dict[str, dict]:
    """Basel 3.1 undrawn rows for the shared facility-share book."""
    return _run(
        CalculationConfig.basel_3_1(
            reporting_date=_REPORTING_DATE,
            permission_mode=PermissionMode.STANDARDISED,
        )
    )


@pytest.fixture(scope="module")
def rows_by_regime(crr_rows: dict[str, dict], b31_rows: dict[str, dict]) -> dict[str, dict]:
    """Both regimes' undrawn-row maps, keyed by regime label."""
    return {"crr": crr_rows, "b31": b31_rows}


class TestP1307FacilityShareCounterpartyPreview:
    """The preview's ranking decides which obligor the undrawn EAD is priced against."""

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    @pytest.mark.parametrize(
        ("share", "expected_ead"),
        [(_ECB_SHARE, _ECB_SHARE_EAD), (_MDB_SHARE, _MDB_SHARE_EAD)],
    )
    def test_undrawn_rows_carry_a_priced_exposure(
        self,
        rows_by_regime: dict[str, dict],
        regime: str,
        share: str,
        expected_ead: float,
    ) -> None:
        """
        Every undrawn row carries a non-null, non-zero exposure and a weight.

        Arrange: the two-share book under the named regime.
        Act:     read the synthetic undrawn rows.
        Assert:  counterparty, EAD, risk weight and RWEA are all populated,
                 and the EAD is non-zero.

        Green before and after. This is the vacuity guard: a null weight and a
        legitimate 0% weight are different claims, and a share that lost its
        EAD would make every ownership assertion below meaningless.
        """
        # Arrange / Act
        row = rows_by_regime[regime][f"{share}_UNDRAWN"]

        # Assert
        assert row["counterparty_reference"] is not None
        assert row["risk_weight"] is not None
        assert row["rwa_final"] is not None
        assert row["ead_final"] == pytest.approx(expected_ead)

    # --- limb B: the ECB, both regimes --------------------------------------

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    def test_ecb_share_undrawn_is_owned_and_priced_by_the_corporate(
        self, rows_by_regime: dict[str, dict], regime: str
    ) -> None:
        """
        Art. 114(3): the ECB previews 0% and cannot win a share, in either regime.

        Arrange: a share between an unrated ECB and a CQS-1 corporate.
        Act:     run the full pipeline under the named regime.
        Assert:  the undrawn row belongs to CP-CORP-A, is classified corporate
                 and is priced at the Art. 122 CQS-1 20%.

        Pre-fix the ECB wins on a 100% preview and the row is then priced at
        the ECB's true 0%, publishing zero RWEA against 4,000,000 of EAD.
        Run ``-k crr`` and ``-k b31`` separately — one red across a
        both-regimes parametrisation proves one regime, not two.
        """
        # Arrange / Act
        row = rows_by_regime[regime][f"{_ECB_SHARE}_UNDRAWN"]

        # Assert — ownership, classification and the priced weight all move.
        assert row["counterparty_reference"] == "CP-CORP-A"
        assert row["original_counterparty_reference"] == "CP-ECB"
        assert row["exposure_class"] == "corporate"
        assert row["risk_weight"] == pytest.approx(_CORPORATE_CQS1_RW[regime])
        assert row["rwa_final"] == pytest.approx(_ECB_SHARE_EAD * _CORPORATE_CQS1_RW[regime])

    # --- limb A: non-named MDB, CRR only ------------------------------------

    def test_mdb_share_undrawn_is_owned_and_priced_by_the_mdb_under_crr(
        self, crr_rows: dict[str, dict]
    ) -> None:
        """
        Art. 117(1): an unrated non-named MDB outranks retail under CRR.

        Arrange: a share between an unrated ``mdb`` and a ``retail`` obligor,
                 sized to keep the retail leg inside the Art. 123 limits.
        Act:     run the full CRR pipeline.
        Assert:  the undrawn row belongs to CP-MDB, is classified ``mdb``, and
                 is priced at the CRR unrated institution weight.

        Pre-fix the row belongs to CP-RETAIL and is priced at the Art. 123
        flat 75%; the MDB's preview of 50% (PS1/26 Table 2B) is below it.
        """
        # Arrange / Act
        row = crr_rows[f"{_MDB_SHARE}_UNDRAWN"]

        # Assert — Art. 117(1) institution treatment, Art. 121 unrated.
        assert row["counterparty_reference"] == "CP-MDB"
        assert row["exposure_class"] == "mdb"
        assert row["risk_weight"] == pytest.approx(_CRR_UNRATED_INSTITUTION_RW)
        assert row["rwa_final"] == pytest.approx(_MDB_SHARE_EAD * _CRR_UNRATED_INSTITUTION_RW)

    def test_mdb_share_undrawn_stays_with_retail_under_basel_3_1(
        self, b31_rows: dict[str, dict]
    ) -> None:
        """
        The Basel 3.1 arm is UNCHANGED — PS1/26 Art. 117(1)(a)/(b) keeps Table 2B.

        Arrange: the identical share.
        Act:     run the full Basel 3.1 pipeline.
        Assert:  the undrawn row still belongs to CP-RETAIL.

        Green before and after — limb A's scope pin at the pipeline level.

        Mutation it detects — MEASURED, not assumed: limb A applied in both
        regimes using the **CRR** institution table (the ``is_basel_3_1``
        branch dropped), which takes the B31 MDB preview to 100% and hands
        this row to CP-MDB. It does NOT detect limb A applied with each
        regime's own institution table, because PS1/26 ECRA unrated (40%) is
        BELOW Table 2B's 50% and cannot change the ordering against retail;
        that variant is covered at the expression level by
        ``tests/unit/test_entity_rw_preview.py::…_keeps_table_2b_under_basel_3_1``
        and at the selection level by ``tests/unit/test_hierarchy.py::
        …_keeps_the_mdb_over_an_unrated_institution_under_basel_3_1``.

        Only ownership is asserted — the B31 exposure class of the retail leg
        is governed by the retail-granularity rules (P5.15), which P1.307 does
        not touch.
        """
        # Arrange / Act
        row = b31_rows[f"{_MDB_SHARE}_UNDRAWN"]

        # Assert — Table 2B unrated 50% stays below the retail 75% preview.
        assert row["counterparty_reference"] == "CP-RETAIL"
