"""
Unit pins — entity-level SA-RW preview expression (``build_entity_rw_expr``).

Pipeline position:
    engine/sa/guarantor_rw.py::build_entity_rw_expr — compiled by the
    hierarchy facility-share selection
    (engine/hierarchy/facility_undrawn.py::
    _derive_facility_share_counterparty) to rank candidate counterparties
    by SA-equivalent risk weight.

Key assertion:
    The shared builder closes the branches the old hierarchy preview
    (``_preview_sa_rw_expr``, deleted in this slice) lacked — PSE Table 2A,
    RGLA Table 1B with the GB→20%/else→100% unrated approximation,
    international organisation 0%, named MDB 0% — while keeping the
    pre-existing branches (corporate et al.) value-identical and the
    conservative 1.0 default for unmatched entity types.

    All expected values are read back from the **rulepack** — never from
    running the engine, and never typed into this file as literals where a
    pack entry exists. (The historic ``data/tables/`` home named in earlier
    revisions of this docstring no longer exists; the pack is the value home.)

P1.307 — the preview mis-prices two entity types relative to the SA pricing
it is meant to approximate, and the error is a RANKING error, not a display
one: ``_derive_facility_share_counterparty`` sorts on this expression to
decide which obligor owns a facility share's whole undrawn EAD.

    Limb A (CRR ONLY) — CRR Art. 117(1): a non-named MDB "shall be treated in
    the same manner as exposures to institutions". CRR has no MDB table, so
    the preview must price a non-named MDB off ``institution_rw_crr``
    (CQS 2 → 50%, unrated → 100%), not off PS1/26's Table 2B (30% / 50%).
    Under Basel 3.1, PS1/26 Art. 117(1)(a)/(b) DOES give MDBs Table 2B, so
    the whole B31 arm is unchanged.

    Limb B (BOTH regimes) — Art. 114(3) is regime-invariant in CRR and
    PS1/26 alike: "Exposures to the ECB shall be assigned a 0% risk weight."
    ``central_bank_ecb`` currently falls into the generic CGCB Table 1
    bucket and so previews at its CQS weight (unrated → 100%, CQS 2 → 20%).

References:
    - CRR Art. 114(3) / PS1/26 Art. 114(3) (``ecb_zero_rw``): the ECB — 0%,
      unconditional and regime-invariant
    - CRR Art. 117(1) (``institution_rw_crr``): non-named MDBs take the
      institution treatment; PS1/26 Art. 117(1)(a)/(b)
      (``mdb_risk_weights_table_2b``) is the Basel 3.1 divergence
    - CRR Art. 116(2) Table 2A (``pse_risk_weights_own_rating``): PSE CQS 2 = 50%
    - CRR Art. 115(5) (``rgla_domestic_currency_rw``): unrated GB RGLA → 20%
      (the documented SA-side GB-vs-other approximation)
    - CRR Art. 118 (``io_zero_rw``): international organisations — 0%
    - CRR Art. 117(2) (``mdb_named_zero_rw``): named MDBs — 0% unconditional
    - CRR Art. 122 Table 5 (``corporate_risk_weights``): corporate CQS 2 = 50%
      (unchanged-branch regression pin)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.domain.enums import CQS
from rwa_calc.engine.sa.crr_risk_weight_tables import CORPORATE_RISK_WEIGHTS
from rwa_calc.engine.sa.guarantor_rw import build_entity_rw_expr
from rwa_calc.rulebook.resolve import resolve

# ---------------------------------------------------------------------------
# Hand-pinned expectations (from the data tables, NOT from the engine)
# ---------------------------------------------------------------------------

EXPECTED_PSE_CQS2_RW: float = 0.50  # PSE_RISK_WEIGHTS_OWN_RATING[CQS2] — Art. 116(2) Table 2A
EXPECTED_RGLA_UNRATED_GB_RW: float = 0.20  # RGLA_DOMESTIC_CURRENCY_RW — Art. 115(5)
EXPECTED_IO_RW: float = 0.0  # IO_ZERO_RW — Art. 118 unconditional
EXPECTED_NAMED_MDB_RW: float = 0.0  # MDB_NAMED_ZERO_RW — Art. 117(2) unconditional
EXPECTED_UNMATCHED_RW: float = 1.0  # conservative preview default (otherwise-branch)
EXPECTED_UNRATED_NO_COUNTRY_RW: float = 1.0  # PSE_UNRATED_DEFAULT_RW when country unknown
EXPECTED_CORPORATE_CQS2_RW: float = float(CORPORATE_RISK_WEIGHTS[CQS.CQS2])  # 0.50 — Art. 122

# ---------------------------------------------------------------------------
# P1.307 expectations — read back from the resolved rulepack
# ---------------------------------------------------------------------------
#
# Anchoring to the pack rather than to a literal (or to the engine's own
# private ``_MDB_RW`` / ``_CGCB_RW`` bindings) keeps these assertions on a
# source of truth that cannot drift with the code under test.
#
# Note the CQS risk-weight TABLES live only in the CRR pack — ``resolve("b31",
# …)`` carries no ``cgcb_risk_weights`` / ``institution_rw_crr`` /
# ``mdb_risk_weights_table_2b`` entry, and ``guarantor_rw`` binds all three
# from the CRR pack for both regimes. ``ecb_zero_rw`` is the exception: it is a
# common-pack scalar present under both regimes and deliberately NOT Feature-
# gated, so it is read per regime below.

_CRR_PACK = resolve("crr", date(2026, 1, 1))
_B31_PACK = resolve("b31", date(2027, 1, 1))
_PACK_BY_REGIME = {"crr": _CRR_PACK, "b31": _B31_PACK}

_CGCB_RW = dict(_CRR_PACK.lookup("cgcb_risk_weights").entries)
_MDB_TABLE_2B = dict(_CRR_PACK.lookup("mdb_risk_weights_table_2b").entries)
_INSTITUTION_RW_CRR = dict(_CRR_PACK.lookup("institution_rw_crr").entries)

# Every CQS the preview can see, unrated included (null CQS -> CQS.UNRATED).
_ALL_CQS: list[int | None] = [1, 2, 3, 4, 5, 6, None]


def _cqs_key(cqs: int | None) -> CQS:
    """Map a raw preview CQS input (``None`` == unrated) onto the table key."""
    return CQS.UNRATED if cqs is None else CQS(cqs)


def _evaluate_entity_rw(
    entity_type: str,
    cqs: int | None,
    *,
    is_basel_3_1: bool = False,
    country_code: str | None = None,
    pass_country_col: bool = True,
) -> float:
    """Evaluate ``build_entity_rw_expr`` against a single-row frame."""
    frame = pl.LazyFrame(
        {
            "entity_type": [entity_type],
            "cqs": [cqs],
            "country_code": [country_code],
        },
        schema_overrides={"cqs": pl.Int8, "country_code": pl.String},
    )
    expr = build_entity_rw_expr(
        entity_type_col="entity_type",
        cqs_col="cqs",
        is_basel_3_1=is_basel_3_1,
        country_code_col="country_code" if pass_country_col else None,
    )
    return frame.select(expr.alias("preview_rw")).collect()["preview_rw"][0]


class TestEntityRwPreviewNewBranches:
    """Branches the old hierarchy preview lacked (fell to the flat-1.0 default)."""

    def test_pse_cqs2_routes_to_table_2a(self) -> None:
        # Arrange / Act
        rw = _evaluate_entity_rw("pse_institution", 2)

        # Assert — Art. 116(2) Table 2A own-rating, not the old flat 1.0.
        assert rw == pytest.approx(EXPECTED_PSE_CQS2_RW)

    def test_rgla_unrated_gb_gets_domestic_currency_treatment(self) -> None:
        # Arrange / Act — unrated (null CQS) GB RGLA with a country column.
        rw = _evaluate_entity_rw("rgla_institution", None, country_code="GB")

        # Assert — GB → 20% domestic-currency treatment (Art. 115(5) approximation).
        assert rw == pytest.approx(EXPECTED_RGLA_UNRATED_GB_RW)

    def test_rgla_unrated_non_gb_gets_conservative_default(self) -> None:
        # Arrange / Act — unrated non-GB RGLA with a country column.
        rw = _evaluate_entity_rw("rgla_institution", None, country_code="DE")

        # Assert — other-country side of the GB-vs-other approximation: 100%.
        assert rw == pytest.approx(EXPECTED_UNRATED_NO_COUNTRY_RW)

    def test_rgla_unrated_without_country_column_falls_back_to_default(self) -> None:
        # Arrange / Act — country_code_col=None (minimal lookups without the column).
        rw = _evaluate_entity_rw("rgla_institution", None, pass_country_col=False)

        # Assert — conservative 100% unrated default applies unconditionally.
        assert rw == pytest.approx(EXPECTED_UNRATED_NO_COUNTRY_RW)

    def test_international_org_zero(self) -> None:
        # Arrange / Act
        rw = _evaluate_entity_rw("international_org", None)

        # Assert — Art. 118: 0% unconditional.
        assert rw == pytest.approx(EXPECTED_IO_RW)

    def test_named_mdb_zero(self) -> None:
        # Arrange / Act
        rw = _evaluate_entity_rw("mdb_named", None)

        # Assert — Art. 117(2): 0% unconditional (old preview gave Table 2B 50%).
        assert rw == pytest.approx(EXPECTED_NAMED_MDB_RW)

    def test_unmatched_entity_type_keeps_conservative_default(self) -> None:
        # Arrange / Act — an entity type with no SA-class bucket.
        rw = _evaluate_entity_rw("unknown_entity_type", None)

        # Assert — the final otherwise stays the conservative preview 1.0.
        assert rw == pytest.approx(EXPECTED_UNMATCHED_RW)


class TestEntityRwPreviewUnchangedBranches:
    """Regression pin — pre-existing preview branches stay value-identical."""

    def test_corporate_cqs2_crr_matches_corporate_table(self) -> None:
        # Arrange / Act
        rw = _evaluate_entity_rw("corporate", 2, is_basel_3_1=False)

        # Assert — Art. 122 Table 5 CQS 2 (read from CORPORATE_RISK_WEIGHTS).
        assert rw == pytest.approx(EXPECTED_CORPORATE_CQS2_RW)


# =============================================================================
# P1.307 limb A — CRR Art. 117(1): non-named MDBs take the institution
# treatment. CRR ARM ONLY; the Basel 3.1 arm keeps PS1/26 Table 2B.
# =============================================================================


class TestP1307NonNamedMdbCrrInstitutionTreatment:
    """CRR Art. 117(1): "treated in the same manner as exposures to institutions"."""

    @pytest.mark.parametrize("cqs", _ALL_CQS)
    def test_p1_307_non_named_mdb_previews_institution_rw_under_crr(self, cqs: int | None) -> None:
        """
        A non-named MDB previews off ``institution_rw_crr``, not Table 2B.

        Arrange: entity_type ``mdb`` at each CQS the preview can see.
        Act:     evaluate the preview expression on the CRR arm.
        Assert:  the CRR institution weight applies.

        Two members of this parametrisation are DISCRIMINATING — the two CQS
        at which Table 2B and the institution table disagree:
            CQS 2   Table 2B 30%  ->  institution 50%
            unrated Table 2B 50%  ->  institution 100%
        The other five (CQS 1/3/4/5/6) are value-identical between the two
        tables and are carried here as unchanged-branch pins, not as evidence.
        """
        # Arrange / Act
        rw = _evaluate_entity_rw("mdb", cqs, is_basel_3_1=False)

        # Assert — Art. 117(1) routes to Art. 120 Table 3 / Art. 121 unrated.
        assert rw == pytest.approx(float(_INSTITUTION_RW_CRR[_cqs_key(cqs)]))

    @pytest.mark.parametrize("cqs", _ALL_CQS)
    def test_p1_307_non_named_mdb_keeps_table_2b_under_basel_3_1(self, cqs: int | None) -> None:
        """
        The Basel 3.1 arm is UNCHANGED — PS1/26 Art. 117(1)(a)/(b) Table 2B stands.

        Arrange: entity_type ``mdb`` at each CQS, Basel 3.1 arm.
        Act:     evaluate the preview expression.
        Assert:  the PS1/26 Table 2B weight applies.

        Green before the fix and green after it — this is the scope pin for
        limb A, and it detects the specific mutation "apply the institution
        treatment in both regimes". Only the **unrated** member is
        discriminating against that mutation: Table 2B unrated is 50% where
        ``institution_rw_b31_ecra`` unrated is 40%. Every rated CQS carries the
        same value in both B31 tables, so CQS 1-6 here cannot see the leak.
        """
        # Arrange / Act
        rw = _evaluate_entity_rw("mdb", cqs, is_basel_3_1=True)

        # Assert — PS1/26 Art. 117(1)(a)/(b).
        assert rw == pytest.approx(float(_MDB_TABLE_2B[_cqs_key(cqs)]))

    @pytest.mark.parametrize("is_basel_3_1", [False, True], ids=["crr", "b31"])
    @pytest.mark.parametrize("cqs", _ALL_CQS)
    def test_p1_307_named_mdb_keeps_zero_in_both_regimes(
        self, cqs: int | None, is_basel_3_1: bool
    ) -> None:
        """
        Art. 117(2) named MDBs stay at 0% regardless of CQS or regime.

        Arrange: entity_type ``mdb_named`` at each CQS, both arms.
        Act:     evaluate the preview expression.
        Assert:  ``mdb_named_zero_rw``.

        Green both before and after — the carve-out sits ahead of the MDB
        branch and must keep doing so. It detects the mutation "key limb A on
        the whole ``mdb`` SA-class bucket instead of the exact ``mdb``
        entity_type", which would price a named MDB at the CRR institution
        weight (unrated 100%) instead of 0%. Discriminating at every CQS.
        """
        # Arrange / Act
        rw = _evaluate_entity_rw("mdb_named", cqs, is_basel_3_1=is_basel_3_1)

        # Assert — Art. 117(2), unconditional.
        assert rw == pytest.approx(EXPECTED_NAMED_MDB_RW)


# =============================================================================
# P1.307 limb B — Art. 114(3): the ECB is 0%, in BOTH regimes.
# =============================================================================


class TestP1307EcbZeroRiskWeight:
    """Art. 114(3) — regime-invariant, unconditional 0% for the ECB."""

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    @pytest.mark.parametrize("cqs", _ALL_CQS)
    def test_p1_307_ecb_previews_zero_in_both_regimes(self, cqs: int | None, regime: str) -> None:
        """
        ``central_bank_ecb`` previews at 0% at every CQS, under both regimes.

        Arrange: entity_type ``central_bank_ecb`` at each CQS.
        Act:     evaluate the preview expression on the named regime's arm.
        Assert:  ``ecb_zero_rw``, read from that regime's own resolved pack.

        Six of the seven members are DISCRIMINATING: today the ECB falls into
        the generic CGCB Table 1 bucket, so it previews 20% / 50% / 100% /
        100% / 150% / 100% at CQS 2/3/4/5/6/unrated. CQS 1 is already 0%
        (Table 1 CQS 1 == 0%) and is carried as an unchanged pin.
        """
        # Arrange / Act
        rw = _evaluate_entity_rw("central_bank_ecb", cqs, is_basel_3_1=regime == "b31")

        # Assert — CRR Art. 114(3) / PS1/26 Art. 114(3).
        assert rw == pytest.approx(float(_PACK_BY_REGIME[regime].scalar_param("ecb_zero_rw").value))

    @pytest.mark.parametrize("regime", ["crr", "b31"])
    @pytest.mark.parametrize("entity_type", ["sovereign", "central_bank"])
    @pytest.mark.parametrize("cqs", _ALL_CQS)
    def test_p1_307_non_ecb_sovereigns_keep_the_cgcb_table(
        self, cqs: int | None, entity_type: str, regime: str
    ) -> None:
        """
        Every OTHER central-govt/central-bank entity type keeps Table 1.

        Arrange: ``sovereign`` / ``central_bank`` at each CQS, both arms.
        Act:     evaluate the preview expression.
        Assert:  ``cgcb_risk_weights`` at that CQS.

        Green before and after. It detects two mutations: zeroing the whole
        CGCB bucket, and keying the ECB branch on ``central_bank`` (or on the
        SA exposure class) rather than on the ``central_bank_ecb`` entity_type
        — either would drag a plain central bank to 0%. Discriminating at
        every CQS except 1, where Table 1 is already 0%.
        """
        # Arrange / Act
        rw = _evaluate_entity_rw(entity_type, cqs, is_basel_3_1=regime == "b31")

        # Assert — Art. 114 Table 1 (unchanged by limb B).
        assert rw == pytest.approx(float(_CGCB_RW[_cqs_key(cqs)]))
