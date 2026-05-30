"""
Unit tests for P2.30 — Annex I Row 3 vs Row 4 CCF discrimination.

Verifies that ``RiskType.MR_ISSUED`` ("medium_risk_issued") is a distinct
member of the ``RiskType`` enum and that it is registered in
``VALID_RISK_TYPES_INPUT`` and ``RISK_TYPE_SYNONYMS`` so the CCF engine
routes Row 3 issued OBS items separately from Row 4 NIF/RUF commitments.

Regulatory background:
    CRR Annex I / Art. 111 arranges off-balance-sheet items into four risk
    bands.  Row 3 covers "other" issued OBS items (performance bonds, bid
    bonds, shipping guarantees) at 50% CCF under SA.  Row 4 covers
    medium-risk commitments (NIFs, RUFs) — also 50% CCF under SA.

    Both bands carry the same CCF (50%) and produce identical EAD, yet they
    are conceptually distinct:
        Row 3: the bank has *issued* a contingent (is_obs_commitment=False)
        Row 4: the bank has *committed* to extend credit (is_obs_commitment=True)

    P2.30 introduces ``RiskType.MR_ISSUED = "medium_risk_issued"`` so that:
        OBS-ROW3-001  ->  risk_type = "MR_ISSUED"  (Annex I Row 3)
        NIF-ROW4-001  ->  risk_type = "MR"          (Annex I Row 4)

    CCF/EAD invariant (SA):
        ccf_applied = 0.50 for both rows
        ead_from_ccf = 1_000_000 × 0.50 = 500_000.00

Layer-1 assertions (dominant RED signal pre-fix):
    assert "MR_ISSUED" in RiskType.__members__           (AssertionError pre-fix)
    assert "MR_ISSUED" in VALID_RISK_TYPES_INPUT         (AssertionError pre-fix)

Layer-2 assertions (CCF/EAD + separability, guarded to remain AssertionError):
    - Row 3 canonical risk_type resolves to "medium_risk_issued" (distinct)
    - Row 4 canonical risk_type resolves to "medium_risk" (MR)
    - Both yield CCF = 0.50 and EAD = 500_000.00

References:
    - CRR Annex I: OBS risk bands (Rows 1–4)
    - CRR Art. 111(2): SA CCF table
    - P2.30 — IMPLEMENTATION_PLAN.md
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.data.schemas import RISK_TYPE_SYNONYMS, VALID_RISK_TYPES_INPUT
from rwa_calc.domain.enums import RiskType
from rwa_calc.engine.ccf import sa_ccf_expression

# =============================================================================
# Scenario constants (single source of truth shared across all assertions)
# =============================================================================

CONT_REF_ROW3: str = "OBS-ROW3-001"
CONT_REF_ROW4: str = "NIF-ROW4-001"

RISK_TYPE_ROW3: str = "MR_ISSUED"  # Row 3 — NEW (not yet in enum pre-fix)
RISK_TYPE_ROW4: str = "MR"  # Row 4 — existing
CANONICAL_ROW3: str = "medium_risk_issued"  # expected canonical value post-fix
CANONICAL_ROW4: str = "medium_risk"  # expected canonical value

NOMINAL_AMOUNT: float = 1_000_000.00
EXPECTED_CCF: float = 0.50
EXPECTED_EAD: float = NOMINAL_AMOUNT * EXPECTED_CCF  # 500_000.00


# =============================================================================
# Layer 1 — Enum and constraint RED assertions (DOMINANT pre-fix failure)
# =============================================================================


class TestMRIssuedEnumMember:
    """P2.30 Layer 1: RiskType enum must contain MR_ISSUED member."""

    def test_mr_issued_member_exists_in_risk_type_enum(self) -> None:
        """RiskType.MR_ISSUED must be a member of the RiskType StrEnum.

        Fails pre-fix with AssertionError because MR_ISSUED is absent from
        the enum.  Post-fix, RiskType.MR_ISSUED = "medium_risk_issued" is
        added and this assertion passes.
        """
        # Arrange — nothing to arrange; this is a pure enum membership check.

        # Act / Assert
        assert "MR_ISSUED" in RiskType.__members__, (
            "RiskType enum is missing the 'MR_ISSUED' member.  "
            "P2.30 requires RiskType.MR_ISSUED = 'medium_risk_issued' to "
            "distinguish Annex I Row 3 issued OBS items from Row 4 NIF/RUF "
            "commitments (RiskType.MR = 'medium_risk')."
        )

    def test_mr_issued_value_is_medium_risk_issued(self) -> None:
        """RiskType.MR_ISSUED.value must equal 'medium_risk_issued'.

        This test is guarded: if MR_ISSUED is absent (Layer 1 not yet fixed),
        it will raise AttributeError, which pytest converts to an ERROR rather
        than a FAIL.  Layer 1 (test above) is therefore the dominant RED
        signal — this test is the companion correctness check for post-fix.
        """
        # Guard: skip value assertion if MR_ISSUED is not yet in the enum
        # so the overall test suite error is an AssertionError from the
        # preceding test, not an AttributeError here.
        if "MR_ISSUED" not in RiskType.__members__:
            pytest.skip("MR_ISSUED not yet in RiskType — skip value check")

        # Act / Assert
        assert RiskType.MR_ISSUED.value == CANONICAL_ROW3, (  # type: ignore[attr-defined]
            f"RiskType.MR_ISSUED.value should be {CANONICAL_ROW3!r}, "
            f"got {RiskType.MR_ISSUED.value!r}"  # type: ignore[attr-defined]
        )

    def test_mr_issued_distinct_from_mr(self) -> None:
        """RiskType.MR_ISSUED must be a *distinct* member from RiskType.MR.

        The whole point of P2.30 is that Row 3 and Row 4 are separable.
        Guarded like the value test above.
        """
        if "MR_ISSUED" not in RiskType.__members__:
            pytest.skip("MR_ISSUED not yet in RiskType — skip distinctness check")

        # Act / Assert
        assert RiskType.MR_ISSUED != RiskType.MR, (  # type: ignore[attr-defined]
            "RiskType.MR_ISSUED must be distinct from RiskType.MR.  "
            "Both represent 50% CCF but map to different Annex I rows."
        )


class TestMRIssuedInValidRiskTypesInput:
    """P2.30 Layer 1: VALID_RISK_TYPES_INPUT must include 'MR_ISSUED'."""

    def test_mr_issued_in_valid_risk_types_input(self) -> None:
        """'MR_ISSUED' must appear in VALID_RISK_TYPES_INPUT (data/schemas.py).

        Fails pre-fix with AssertionError: the set currently contains
        {'FR', 'FRC', 'MR', 'OC', 'MLR', 'LR', 'CCR_DERIVATIVE', 'CCR_SFT'}.
        Post-fix, 'MR_ISSUED' is added.
        """
        # Arrange
        # (VALID_RISK_TYPES_INPUT is imported at module scope above)

        # Act / Assert
        assert "MR_ISSUED" in VALID_RISK_TYPES_INPUT, (
            f"'MR_ISSUED' is missing from VALID_RISK_TYPES_INPUT.  "
            f"Current members: {sorted(VALID_RISK_TYPES_INPUT)}.  "
            "P2.30 requires MR_ISSUED to be a first-class recognised risk_type "
            "for Annex I Row 3 issued OBS items."
        )

    def test_mr_issued_synonym_resolves_to_canonical(self) -> None:
        """RISK_TYPE_SYNONYMS must map 'mr_issued' and 'medium_risk_issued' to 'MR_ISSUED'.

        Pre-fix: neither key is present so this fails with AssertionError.
        Post-fix: both lowercase spellings resolve to the canonical uppercase form.
        """
        # Arrange — two expected synonym keys
        expected_keys = {"mr_issued", "medium_risk_issued"}

        # Act / Assert — each missing key gives a distinct, actionable failure
        for key in expected_keys:
            assert key in RISK_TYPE_SYNONYMS, (
                f"RISK_TYPE_SYNONYMS is missing the '{key}' synonym.  "
                f"Current keys: {sorted(RISK_TYPE_SYNONYMS)}.  "
                "P2.30 requires RISK_TYPE_SYNONYMS to map 'mr_issued' and "
                "'medium_risk_issued' to 'MR_ISSUED'."
            )


# =============================================================================
# Layer 2 — CCF invariance and separability (guarded AssertionError)
# =============================================================================


class TestMRIssuedCCFInvariance:
    """P2.30 Layer 2: CCF and EAD are invariant (both 0.50 / 500,000).

    These tests exercise ``sa_ccf_expression`` directly — the same
    expression path used by ``CCFCalculator.apply_ccf`` — and are
    structured so that the assertion failure is an AssertionError, not an
    ImportError or AttributeError.

    Pre-fix: ``MR_ISSUED`` is unrecognised so it falls through to the
    ``otherwise`` default (0.50 — same as MR). The CCF invariance tests
    will therefore PASS pre-fix (the fallback gives the right number by
    accident).  The Layer 1 tests are the dominant RED signal.

    Post-fix: ``MR_ISSUED`` canonicalises to ``medium_risk_issued`` and
    is explicitly mapped to 0.50, so the tests continue to pass.
    """

    @pytest.fixture
    def two_row_frame(self) -> pl.DataFrame:
        """Minimal two-row DataFrame mirroring the p2_30 fixture rows."""
        return pl.DataFrame(
            {
                "contingent_reference": [CONT_REF_ROW3, CONT_REF_ROW4],
                "risk_type": [RISK_TYPE_ROW3, RISK_TYPE_ROW4],
                "nominal_amount": [NOMINAL_AMOUNT, NOMINAL_AMOUNT],
                "is_obs_commitment": [False, True],
            }
        )

    def test_row3_mr_issued_sa_ccf_is_50_percent(self, two_row_frame: pl.DataFrame) -> None:
        """Row 3 (MR_ISSUED) must resolve to 50% CCF under SA.

        Hand-calc: CCF = 0.50, EAD = 1_000_000 × 0.50 = 500_000.
        Pre-fix: passes by accident (fallback = 0.50); post-fix: passes via
        explicit MR_ISSUED mapping.  Not the dominant RED signal — see Layer 1.
        """
        # Arrange
        row3 = two_row_frame.filter(pl.col("contingent_reference") == CONT_REF_ROW3)

        # Act
        result = row3.select(sa_ccf_expression().alias("ccf"))
        ccf_row3 = result["ccf"][0]
        ead_row3 = NOMINAL_AMOUNT * ccf_row3

        # Assert
        assert ccf_row3 == pytest.approx(EXPECTED_CCF), (
            f"Row 3 (MR_ISSUED) CCF expected {EXPECTED_CCF}, got {ccf_row3}"
        )
        assert ead_row3 == pytest.approx(EXPECTED_EAD), (
            f"Row 3 (MR_ISSUED) EAD expected {EXPECTED_EAD}, got {ead_row3}"
        )

    def test_row4_mr_sa_ccf_is_50_percent(self, two_row_frame: pl.DataFrame) -> None:
        """Row 4 (MR) must resolve to 50% CCF under SA — regression guard.

        Hand-calc: CCF = 0.50, EAD = 1_000_000 × 0.50 = 500_000.
        """
        # Arrange
        row4 = two_row_frame.filter(pl.col("contingent_reference") == CONT_REF_ROW4)

        # Act
        result = row4.select(sa_ccf_expression().alias("ccf"))
        ccf_row4 = result["ccf"][0]
        ead_row4 = NOMINAL_AMOUNT * ccf_row4

        # Assert
        assert ccf_row4 == pytest.approx(EXPECTED_CCF), (
            f"Row 4 (MR) CCF expected {EXPECTED_CCF}, got {ccf_row4}"
        )
        assert ead_row4 == pytest.approx(EXPECTED_EAD), (
            f"Row 4 (MR) EAD expected {EXPECTED_EAD}, got {ead_row4}"
        )

    def test_aggregate_ead_two_rows_is_one_million(self, two_row_frame: pl.DataFrame) -> None:
        """Total EAD from both rows = 2 × 500_000 = 1_000_000.

        Confirms the 50% CCF applied to both 1M nominals.
        """
        # Arrange / Act
        result = two_row_frame.select(
            (pl.col("nominal_amount") * sa_ccf_expression()).alias("ead_from_ccf")
        )
        total_ead = result["ead_from_ccf"].sum()

        # Assert
        assert total_ead == pytest.approx(EXPECTED_EAD * 2), (
            f"Total EAD for two rows expected {EXPECTED_EAD * 2}, got {total_ead}"
        )


class TestMRIssuedSeparability:
    """P2.30 Layer 2: Risk type values must be *distinct* (separability assertion).

    Post-fix, the RISK_TYPE_SYNONYMS map must route:
        'MR_ISSUED' / 'mr_issued' / 'medium_risk_issued'  ->  'MR_ISSUED' (canonical)
        'MR' / 'mr' / 'medium_risk'                       ->  'MR' (canonical)

    Pre-fix, 'mr_issued' is absent from RISK_TYPE_SYNONYMS so the
    _normalize_risk_type expression passes it through uppercased ('MR_ISSUED')
    which does not match any SA CCF branch and falls to the default (0.50).
    The two rows are CCF-equivalent but the canonical routing is wrong — this
    test asserts the *routing* is correct, not just the CCF scalar.

    The dominant RED signal pre-fix is the Layer 1 enum/constraint tests;
    these separability tests are companion correctness checks that become the
    red signal once Layer 1 is fixed but the synonym map is still incomplete.
    """

    def test_synonyms_map_mr_issued_to_distinct_canonical(self) -> None:
        """RISK_TYPE_SYNONYMS['mr_issued'] must resolve to 'MR_ISSUED', not 'MR'.

        Pre-fix: 'mr_issued' is absent from RISK_TYPE_SYNONYMS -> KeyError /
        absent -> AssertionError on the 'in' membership check (Layer 1 catches
        this first).  Post-fix: resolves to 'MR_ISSUED'.
        """
        # Guard: if the key is absent, Layer 1 already asserts this; skip
        # the resolved-value assertion to keep failure mode clean.
        if "mr_issued" not in RISK_TYPE_SYNONYMS:
            pytest.skip("'mr_issued' not in RISK_TYPE_SYNONYMS — Layer 1 is the RED signal")

        # Act
        resolved = RISK_TYPE_SYNONYMS["mr_issued"]

        # Assert
        assert resolved == "MR_ISSUED", (
            f"RISK_TYPE_SYNONYMS['mr_issued'] should resolve to 'MR_ISSUED', got {resolved!r}"
        )
        assert resolved != RISK_TYPE_SYNONYMS.get("mr", "MR"), (
            "MR_ISSUED and MR must resolve to *distinct* canonical codes"
        )

    def test_synonyms_map_medium_risk_issued_to_mr_issued(self) -> None:
        """RISK_TYPE_SYNONYMS['medium_risk_issued'] must resolve to 'MR_ISSUED'.

        This is the full-name synonym, complementing 'mr_issued' (short code).
        """
        if "medium_risk_issued" not in RISK_TYPE_SYNONYMS:
            pytest.skip(
                "'medium_risk_issued' not in RISK_TYPE_SYNONYMS — Layer 1 is the RED signal"
            )

        # Act
        resolved = RISK_TYPE_SYNONYMS["medium_risk_issued"]

        # Assert
        assert resolved == "MR_ISSUED", (
            f"RISK_TYPE_SYNONYMS['medium_risk_issued'] should be 'MR_ISSUED', got {resolved!r}"
        )

    def test_row3_and_row4_risk_types_are_distinct_strings(self) -> None:
        """The raw risk_type strings for Row 3 and Row 4 must differ.

        This is a fixture-level sanity check that the p2_30 fixture rows
        actually encode different risk_type values (not a test of the engine).
        """
        # Arrange — from scenario constants
        # Act / Assert
        assert RISK_TYPE_ROW3 != RISK_TYPE_ROW4, (
            f"Row 3 risk_type ({RISK_TYPE_ROW3!r}) must differ from "
            f"Row 4 risk_type ({RISK_TYPE_ROW4!r})"
        )
