"""
P1.342: QCCP trade exposures are carved out of the Art. 121(6) FX sovereign floor.

Pipeline position:
    Loader -> HierarchyResolver -> Classifier -> CRMProcessor -> CCRAdapter
    -> SACalculator (``engine/sa/sovereign_floor.py``) -> OutputAggregator

Key responsibilities:
- Pin that an unrated QCCP's *trade* exposure keeps its Art. 306 2% / 4% weight
  and is NOT floored to the jurisdiction's sovereign risk weight.
- Pin that the exemption is *deliberate* — named by
  ``sa_risk_weight_branch_reason`` — rather than an accident of a null.
- Pin that an ordinary unrated institution in the same FR/USD shape stays
  inside the floor.

The item has TWO legs, and this test requires both
-------------------------------------------------
**Leg 1 — the Art. 306 carve-out.** ``apply_sovereign_floor_for_institutions``
has no QCCP limb. A QCCP classifies as an institution, so an unrated QCCP with a
foreign-currency netting set sits squarely inside ``_floor_applies`` and the
floor overwrites the Art. 306 weight with the sovereign residual.

The carve-out's predicate must be keyed on the exposure being a **CCR trade
exposure**, not merely on the counterparty being a QCCP. CRR Art. 107(2), read
verbatim from ``docs/assets/crr.pdf`` p.106:

    "For trade exposures and for default fund contributions to a central
    counterparty, institutions shall apply the treatment set out in Chapter 6,
    Section 9 ... For all other types of exposures to a central counterparty,
    institutions shall treat those exposures as follows: (a) as exposures to an
    institution for other types of exposures to a qualifying CCP".

So an ordinary loan to a QCCP is an exposure to an *institution* and IS inside
Art. 121(6). Only trade exposures (and default fund contributions) reach the
Art. 306 lex specialis. A carve-out written over ``is_qccp`` alone would exempt
the loan too.

**Leg 2 — the null-safe denomination currency.** ``denomination_currency_expr``
returns ``pl.col("original_currency")`` whenever that column is in the schema.
The FX converter stamps it on the *lending* frame; the synthetic ``ccr__`` rows
are minted afterwards and pick it up as a null fill. So ``"EUR".eq(NULL)`` is
NULL, ``is_domestic_currency`` is NULL, ``~_is_fx`` is NULL, and every limb of
the floor's ``decide`` goes indeterminate — the row lands on
``UNKNOWN_FALLBACK`` and the floor never runs. Measured on this fixture:
``original_currency`` is null and ``currency`` is ``"USD"`` on all three rows.

Do not re-shape the fixture to GB — FR/USD is the only shape that arms the floor
-------------------------------------------------------------------------------
A UK-focused reader will reach for a GB counterparty. It would make this whole
file vacuous. ``is_domestic_currency`` is ``is_uk_domestic | is_eu_domestic``,
and ``is_eu_domestic`` is built with ``replace_strict(..., default=None)``, so a
country outside the EU map yields NULL rather than False. The UK limb is NOT the
null source: for GB/USD, ``(country == "GB") & (ccy == "GBP")`` is a determinate
``True & False``. It is the EU limb that goes null, and ``False | NULL`` is NULL:

    GB + USD  -> False | NULL = NULL -> ``~NULL`` is NULL -> floor never arms
    US + GBP  -> same shape, same vacuity
    FR + USD  -> False | False = False -> ``~False`` is True -> ARMED

Measured by the fixture author with the country flipped and nothing else changed:
GB/USD stays ``UNKNOWN_FALLBACK`` at 2% **even after leg 2 lands**, because that
residual null is the separate item P1.333. So a GB fixture would sit green before
and after this fix, for the wrong reason, and pin nothing
(`.claude/LESSONS.md` B5 — a row that never lights the branch makes coverage
worse, not better).

Why ``risk_weight == 0.02`` is NOT the fail-first assertion
----------------------------------------------------------
It holds TODAY. The QCCP rows already read 2% / 4% — correct **by accident**,
because leg 2's null disarms the floor before leg 1's absence can bite. A test
asserting only the risk weight is green before the fix and green after, and
pins nothing.

The assertions that can only go green once BOTH legs land are on
``sa_risk_weight_branch_reason`` (today ``UNKNOWN_FALLBACK`` on all three rows)
and on the absence of the accompanying ``BR001`` warnings in ``result.errors``.

**The value pins alongside them are load-bearing — do not delete them as
redundant.** They are what stops a "fix" that arms the floor without carving
Art. 306 out. Measured by patching leg 2 alone with the carve-out absent, both
QCCP legs go to ``risk_weight`` 1.00 / ``floor_bound``:

    proprietary    109,933.82 -> 5,496,691.10 (CRR)   50x
    client-cleared 219,867.64 -> 5,496,691.10 (CRR)   25x
    proprietary     97,518.54 -> 4,875,927.25 (B31)   50x
    client-cleared 195,037.09 -> 4,875,927.25 (B31)   25x

That is the exact failure this item exists to prevent, so it is pinned
explicitly in ``test_p1_342_qccp_legs_are_not_floored_to_the_sovereign_residual``
rather than left implicit.

Both regimes are exercised. `.claude/LESSONS.md` C7: one regime green is not
evidence about the other, and the floor's value source is regime-sensitive.

References:
- CRR Art. 306(1)(a) / (c), Art. 307 — QCCP trade-exposure risk weights.
  Note: Arts. 300-311 are *omitted* from the onshored consolidation at
  legislation.gov.uk (S.I. 2021/1078 reg. 6(3)(f)(ii)(ee), 1.1.2022) — the
  substance sits in the PRA Rulebook Counterparty Credit Risk Part. The values
  are taken from the rulepack (``qccp_proprietary_rw`` / ``qccp_client_cleared_rw``,
  ``Citation("CRR", "306", ...)``) via ``tests/fixtures/ccr/qccp_builder.py``,
  never retyped here.
- CRR Art. 107(2) — only trade exposures and default fund contributions reach
  Chapter 6 Section 9; all other CCP exposures are institution exposures.
- PRA PS1/26 Art. 121(6) — the FX sovereign floor for unrated institutions.
- PRA PS1/26 Art. 114(1)-(2) — the floor's value source; the unrated-sovereign
  residual is what the QCCP legs would be floored to.
- BCBS CRE54.14 / CRE54.15 — the 2% / 4% supervisory factors.
- BCBS CRE20.22 + footnote 13 — the SCRA sovereign floor and its only carve-out.
- src/rwa_calc/engine/sa/sovereign_floor.py — the rule under test.
- src/rwa_calc/engine/eu_sovereign.py::denomination_currency_expr — leg 2.
- tests/fixtures/ccr/p1342_qccp_fx_floor_builder.py — the FR/USD book.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.branch_reasons import (
    SA_RISK_WEIGHT_BRANCH_REASON,
    UNKNOWN_FALLBACK,
    SovereignFloorReason,
)
from rwa_calc.domain.enums import CQS, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.engine.sa.crr_risk_weight_tables import CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS
from tests.fixtures.ccr.p1342_qccp_fx_floor_builder import (
    P1342_EAD_B31,
    P1342_EAD_CRR,
    P1342_EXPOSURE_INST,
    P1342_EXPOSURE_QCCP_CLIENT,
    P1342_EXPOSURE_QCCP_PROP,
    P1342_RW_QCCP_CLIENT_CLEARED,
    P1342_RW_QCCP_PROPRIETARY,
    P1342_RWA_QCCP_CLIENT_B31,
    P1342_RWA_QCCP_CLIENT_CRR,
    P1342_RWA_QCCP_FLOORED_B31,
    P1342_RWA_QCCP_FLOORED_CRR,
    P1342_RWA_QCCP_PROP_B31,
    P1342_RWA_QCCP_PROP_CRR,
    build_p1342_bundle,
)

if TYPE_CHECKING:
    from rwa_calc.contracts.bundles import AggregatedResultBundle

# ---------------------------------------------------------------------------
# Regimes. Both are run: the floor's value source and the institution ladder
# are regime-sensitive, and `.claude/LESSONS.md` C7 is explicit that a
# both-regimes parametrisation seen red once proves one regime, not two.
# ---------------------------------------------------------------------------

_CRR = "crr"
_B31 = "basel_3_1"
_REGIMES = (_CRR, _B31)

#: The reporting dates the fixture's measured EADs are keyed to. The SA-CCR
#: add-on integrates remaining maturity from the reporting date, so a different
#: date silently moves every expected number here.
_CONFIGS = {
    _CRR: lambda: CalculationConfig.crr(
        reporting_date=date(2025, 12, 31),
        permission_mode=PermissionMode.STANDARDISED,
    ),
    _B31: lambda: CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 1),
        permission_mode=PermissionMode.STANDARDISED,
    ),
}

# ---------------------------------------------------------------------------
# The branch-reason vocabulary AS IT STANDS BEFORE THIS ITEM.
#
# Deliberately a snapshot of the PRE-CHANGE population, and deliberately used
# only as a "must differ from" set — never as a "must equal" list. That is what
# makes it fail-first without dictating the implementer's spelling: the Art. 306
# carve-out has to arrive as a NEW named limb, and any of the six existing
# members (or UNKNOWN_FALLBACK) on a QCCP trade row is a failure.
#
# Written as enum attribute references rather than string literals so that a
# RENAME of an existing member breaks collection loudly instead of silently
# turning this set into a stale collection of orphan strings
# (`.claude/LESSONS.md` B3).
# ---------------------------------------------------------------------------

_PRE_FIX_SOVEREIGN_FLOOR_REASONS: frozenset[str] = frozenset(
    {
        SovereignFloorReason.NOT_INSTITUTION.value,
        SovereignFloorReason.RATED.value,
        SovereignFloorReason.TRADE_EXEMPT.value,
        SovereignFloorReason.DOMESTIC_CURRENCY.value,
        SovereignFloorReason.FLOOR_BOUND.value,
        SovereignFloorReason.FLOOR_NOT_BINDING.value,
        UNKNOWN_FALLBACK,
    }
)

#: Every row the fixture's three netting sets must produce.
_ALL_REFS = (P1342_EXPOSURE_QCCP_PROP, P1342_EXPOSURE_QCCP_CLIENT, P1342_EXPOSURE_INST)

#: The two Art. 306 legs, and the weight each must keep.
_QCCP_RW: dict[str, float] = {
    P1342_EXPOSURE_QCCP_PROP: P1342_RW_QCCP_PROPRIETARY,
    P1342_EXPOSURE_QCCP_CLIENT: P1342_RW_QCCP_CLIENT_CLEARED,
}

#: Correct RWA per regime per Art. 306 leg (EAD x the Art. 306 weight).
_QCCP_RWA: dict[str, dict[str, float]] = {
    _CRR: {
        P1342_EXPOSURE_QCCP_PROP: P1342_RWA_QCCP_PROP_CRR,
        P1342_EXPOSURE_QCCP_CLIENT: P1342_RWA_QCCP_CLIENT_CRR,
    },
    _B31: {
        P1342_EXPOSURE_QCCP_PROP: P1342_RWA_QCCP_PROP_B31,
        P1342_EXPOSURE_QCCP_CLIENT: P1342_RWA_QCCP_CLIENT_B31,
    },
}

#: The RWA a QCCP leg takes when the floor arms and nothing carves it out.
_FLOORED_RWA: dict[str, float] = {
    _CRR: P1342_RWA_QCCP_FLOORED_CRR,
    _B31: P1342_RWA_QCCP_FLOORED_B31,
}

#: The risk weight the floor would impose — the Art. 114(1) unrated-sovereign
#: residual, read from the SAME pack-bound table ``sovereign_floor.py`` reads
#: (`.claude/LESSONS.md` A4: the pack is the value home, never a typed literal).
#: Used only as a forbidden value, so sharing production's source strengthens
#: the guard rather than weakening it — if the pack moves, so does the guard.
_FLOORED_RW: float = float(CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS[CQS.UNRATED])

#: SA-CCR EAD per regime. Identical across all three netting sets — the trades
#: share the canonical CCR-A1 economics.
_EAD: dict[str, float] = {_CRR: P1342_EAD_CRR, _B31: P1342_EAD_B31}

# ---------------------------------------------------------------------------
# The ordinary-institution SCOPE CONTROL row.
#
# These two weights are MEASURED anchors, not a claim this item owns. The CRR
# figure is the unrated-institution weight the engine assigns a counterparty
# with a null ``institution_cqs``; the Basel 3.1 figure is the
# ``b31_scra_risk_weights`` table DEFAULT (SCRA Grade C, PS1/26 Art. 120 /
# CRE20.18-21), taken because the fixture supplies no ``cp_scra_grade``.
#
# What matters here is only that neither equals an Art. 306 weight: this row is
# an ordinary institution exposure and must keep the number it has.
# ---------------------------------------------------------------------------

_INST_RW: dict[str, float] = {_CRR: 1.00, _B31: 1.50}

# ---------------------------------------------------------------------------
# Module-scoped pipeline runs — one per regime, reused by every test.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def p1342_results() -> dict[str, AggregatedResultBundle]:
    """Run the P1.342 FR/USD QCCP book through both regimes.

    Arrange:
        Three unmargined FR netting sets denominated in USD — an unrated QCCP's
        proprietary trade, the same QCCP's client-cleared trade, and an unrated
        ordinary institution. All three carry the CCR-A1 10y IR swap economics.
    Act:
        Full pipeline via ``PipelineOrchestrator().run_with_data``.
    """
    return {
        regime: PipelineOrchestrator().run_with_data(build_p1342_bundle(), make_config())
        for regime, make_config in _CONFIGS.items()
    }


@pytest.fixture(scope="module")
def p1342_rows(
    p1342_results: dict[str, AggregatedResultBundle],
) -> dict[str, dict[str, dict]]:
    """Index every regime's result rows by ``exposure_reference``."""
    return {
        regime: {row["exposure_reference"]: row for row in bundle.results.collect().to_dicts()}
        for regime, bundle in p1342_results.items()
    }


# ---------------------------------------------------------------------------
# Negative space — absence is this project's dominant escape class
# (`.claude/LESSONS.md` B4). Assert the rows exist and carry figures at all
# before asserting anything about the figures.
# ---------------------------------------------------------------------------


class TestP1342RowsAreEmitted:
    """The three CCR rows exist, are priced, and the vocabulary still declares its limbs."""

    @pytest.mark.parametrize("regime", _REGIMES)
    def test_p1_342_all_three_ccr_rows_are_emitted(
        self, p1342_rows: dict[str, dict[str, dict]], regime: str
    ) -> None:
        """Each of the three netting sets produces exactly one ``ccr__`` row.

        A carve-out implemented as a filter rather than a predicate would drop
        rows instead of re-weighting them, and every value assertion below
        would then fail with a KeyError rather than a number. Assert presence
        first so that failure mode is named.

        Assert:
            The result frame carries exactly the three expected
            ``exposure_reference`` values and no other ``ccr__`` row.
        """
        # Arrange
        rows = p1342_rows[regime]

        # Act
        emitted = {ref for ref in rows if ref.startswith("ccr__")}

        # Assert
        assert emitted == set(_ALL_REFS), (
            f"P1.342/{regime}: expected exactly the three CCR rows {sorted(_ALL_REFS)!r}, "
            f"got {sorted(emitted)!r}. The CCR stage emits one synthetic row per netting "
            "set; a missing row means the netting set was dropped rather than re-weighted."
        )

    @pytest.mark.parametrize("regime", _REGIMES)
    @pytest.mark.parametrize("ref", _ALL_REFS)
    def test_p1_342_priced_columns_are_non_null(
        self, p1342_rows: dict[str, dict[str, dict]], regime: str, ref: str
    ) -> None:
        """Every row carries a non-null EAD, risk weight, RWA and branch reason.

        A null and a legitimate zero are different claims. All three netting
        sets have real exposure, so a null in any of these four columns is a
        row that published nothing, not a row that published zero.

        Assert:
            ``ead_final``, ``risk_weight``, ``rwa_final`` and
            ``sa_risk_weight_branch_reason`` are all non-null.
        """
        # Arrange
        row = p1342_rows[regime][ref]
        priced = ("ead_final", "risk_weight", "rwa_final", SA_RISK_WEIGHT_BRANCH_REASON)

        # Act
        nulls = [column for column in priced if row[column] is None]

        # Assert
        assert not nulls, (
            f"P1.342/{regime}/{ref}: {nulls!r} is null on a row with real exposure. "
            "The netting set carries a live SA-CCR EAD, so every priced column must "
            "hold a figure — a null here is absence, not a zero."
        )

    def test_p1_342_sovereign_floor_vocabulary_keeps_every_existing_limb(self) -> None:
        """The carve-out is ADDED to ``SovereignFloorReason``, never repurposed from a limb.

        The fix must introduce a new named limb. Re-labelling ``TRADE_EXEMPT``
        (the Art. 121(6)(b) self-liquidating goods-movement exemption) or
        ``FLOOR_NOT_BINDING`` (which asserts the floor ran and did not move the
        row — false for a carved-out exposure) would satisfy a naive reason
        assertion while destroying an existing limb's meaning.

        Assert:
            Every pre-existing member is still declared by the vocabulary.
        """
        # Act
        declared = {member.value for member in SovereignFloorReason}

        # Assert
        missing = _PRE_FIX_SOVEREIGN_FLOOR_REASONS - declared
        assert not missing, (
            f"P1.342: SovereignFloorReason no longer declares {sorted(missing)!r}. "
            "The Art. 306 carve-out must be a NEW member — repurposing TRADE_EXEMPT "
            "(Art. 121(6)(b) goods-movement items) or FLOOR_NOT_BINDING (the floor ran "
            "and did not bind) would make the branch census report a limb that no "
            "longer means what it says."
        )


# ---------------------------------------------------------------------------
# Leg 1 + leg 2 — the fail-first core.
# ---------------------------------------------------------------------------


class TestP1342Art306CarveOutIsNamed:
    """The Art. 306 legs are exempted deliberately, not by a null accident."""

    @pytest.mark.parametrize("regime", _REGIMES)
    @pytest.mark.parametrize(
        "ref",
        (P1342_EXPOSURE_QCCP_PROP, P1342_EXPOSURE_QCCP_CLIENT),
        ids=("proprietary", "client_cleared"),
    )
    def test_p1_342_qccp_trade_leg_names_the_art_306_carve_out(
        self, p1342_rows: dict[str, dict[str, dict]], regime: str, ref: str
    ) -> None:
        """A QCCP trade exposure's branch reason names the Art. 306 carve-out.

        THIS IS THE FAIL-FIRST ASSERTION. Today the reason reads
        ``UNKNOWN_FALLBACK`` on both legs: leg 2's null makes the whole
        domesticity test indeterminate, so the floor's ``decide`` cannot reach
        any limb. The 2% / 4% the rows currently show is what survives that
        accident, not a decision.

        After the fix the reason must be a NEW member of
        ``SovereignFloorReason`` naming the Art. 306 exemption. It must not be
        ``UNKNOWN_FALLBACK`` (leg 2 unfixed), not ``FLOOR_BOUND`` (leg 2 fixed,
        leg 1 missing — the 50x defect), and not ``DOMESTIC_CURRENCY`` (a
        USD-denominated exposure to an FR counterparty is not domestic).

        Both legs are asserted separately: a carve-out keyed on the proprietary
        branch alone leaves the client-cleared leg floored.

        Assert:
            The reason is outside the pre-change vocabulary — i.e. a limb this
            item introduced.

        References:
            CRR Art. 306(1)(a) / (c), Art. 307 — the lex specialis weights.
            CRR Art. 107(2) — only trade exposures reach Chapter 6 Section 9.
        """
        # Arrange
        row = p1342_rows[regime][ref]

        # Act
        reason = row[SA_RISK_WEIGHT_BRANCH_REASON]

        # Assert
        assert reason not in _PRE_FIX_SOVEREIGN_FLOOR_REASONS, (
            f"P1.342/{regime}/{ref}: sa_risk_weight_branch_reason is {reason!r}, which is "
            "a pre-existing limb — the Art. 306 carve-out has not been named.\n"
            f"  {UNKNOWN_FALLBACK!r} means leg 2 is unfixed: denomination_currency_expr "
            "still returns a null original_currency on synthetic ccr__ rows, so the "
            "domesticity test is indeterminate and the floor silently never runs.\n"
            f"  {SovereignFloorReason.FLOOR_BOUND.value!r} means leg 2 landed WITHOUT "
            "leg 1: the floor now arms and overwrites the Art. 306 weight with the "
            "unrated-sovereign residual — a 50x (proprietary) / 25x (client-cleared) "
            "overstatement.\n"
            f"  {SovereignFloorReason.DOMESTIC_CURRENCY.value!r} means leg 2 was fixed "
            "wrongly: a USD exposure to an FR counterparty is not domestic.\n"
            "Add a new SovereignFloorReason member for the Art. 306 exemption and gate "
            "it on risk_type in {CCR_DERIVATIVE, CCR_SFT} AND is_qccp — CRR Art. 107(2) "
            "sends only trade exposures and default fund contributions to Chapter 6 "
            "Section 9, so an ordinary loan to a QCCP stays inside Art. 121(6)."
        )

    @pytest.mark.parametrize("regime", _REGIMES)
    def test_p1_342_no_ccr_row_is_left_on_unknown_fallback(
        self,
        p1342_results: dict[str, AggregatedResultBundle],
        p1342_rows: dict[str, dict[str, dict]],
        regime: str,
    ) -> None:
        """Leg 2: no row's domesticity test is indeterminate, and no BR001 is raised.

        This is the leg-2 assertion stated on the production-reachable channel
        rather than only on the frame. ``validate_branch_reasons`` raises a
        BR001 WARNING for every row whose branch reason reads
        ``UNKNOWN_FALLBACK``; today all three rows do, so all three BR001s are
        present in ``result.errors``.

        Asserting it over ALL THREE rows — not just the QCCP pair — is what
        stops leg 2 being "fixed" by exempting CCR rows from the floor
        wholesale. The scope-control row must come out of the null too, and
        land on a real limb.

        Assert:
            No row reads ``UNKNOWN_FALLBACK``, and no BR001 in ``result.errors``
            names one of the fixture's three exposure references.

        References:
            src/rwa_calc/contracts/validation.py::validate_branch_reasons.
        """
        # Arrange
        rows = p1342_rows[regime]
        errors = p1342_results[regime].errors

        # Act
        unjustified = {
            ref for ref in _ALL_REFS if rows[ref][SA_RISK_WEIGHT_BRANCH_REASON] == UNKNOWN_FALLBACK
        }
        br001 = sorted(
            error.exposure_reference
            for error in errors
            if error.code == "BR001" and error.exposure_reference in _ALL_REFS
        )

        # Assert
        assert not unjustified and not br001, (
            f"P1.342/{regime}: rows on {UNKNOWN_FALLBACK}: {sorted(unjustified)!r}; "
            f"BR001 warnings: {br001!r}. Every one of these rows is an unrated FR "
            "institution exposure denominated in USD — the domesticity test is fully "
            "determined by the data. It reads null only because "
            "denomination_currency_expr returns original_currency, which the FX "
            "converter never stamps on synthetic ccr__ rows. Make it null-safe "
            "(fall back to `currency`) so the floor decides rather than abstains."
        )


# ---------------------------------------------------------------------------
# Value pins. These do NOT fail first — they hold today. They are what stops a
# fix that arms the floor and takes the QCCP legs to the sovereign residual.
# Do not delete them as redundant; see the module docstring.
# ---------------------------------------------------------------------------


class TestP1342Art306WeightsSurvive:
    """The Art. 306 weights and RWAs are unchanged by the carve-out."""

    @pytest.mark.parametrize("regime", _REGIMES)
    @pytest.mark.parametrize(
        "ref",
        (P1342_EXPOSURE_QCCP_PROP, P1342_EXPOSURE_QCCP_CLIENT),
        ids=("proprietary", "client_cleared"),
    )
    def test_p1_342_qccp_trade_leg_keeps_its_art_306_weight(
        self, p1342_rows: dict[str, dict[str, dict]], regime: str, ref: str
    ) -> None:
        """The proprietary leg keeps 2% and the client-cleared leg keeps 4%.

        PASSES TODAY — deliberately. The QCCP rows already read their Art. 306
        weights because the floor is disarmed by a null, so this pin cannot go
        red before the fix. Its job is the other direction: it must still hold
        AFTER the floor is armed, which is precisely what leg 1 delivers.

        The expected weights come from ``qccp_builder``, which carries them from
        the rulepack entries ``qccp_proprietary_rw`` / ``qccp_client_cleared_rw``
        — never retyped here (`.claude/LESSONS.md` A4).

        Assert:
            ``risk_weight`` equals the Art. 306 weight exactly.

        References:
            CRR Art. 306(1)(a) — 2%, clearing member's own trade exposures.
            CRR Art. 306(1)(c) / Art. 307 — 4%, client-cleared exposures.
        """
        # Arrange
        expected_rw = _QCCP_RW[ref]

        # Act
        actual_rw = p1342_rows[regime][ref]["risk_weight"]

        # Assert
        assert actual_rw == expected_rw, (
            f"P1.342/{regime}/{ref}: expected risk_weight={expected_rw} "
            f"(CRR Art. 306 trade-exposure weight), got {actual_rw!r}. "
            "Art. 306 is lex specialis for QCCP trade exposures and admits no "
            "Art. 121(6) sovereign floor."
        )

    @pytest.mark.parametrize("regime", _REGIMES)
    @pytest.mark.parametrize(
        "ref",
        (P1342_EXPOSURE_QCCP_PROP, P1342_EXPOSURE_QCCP_CLIENT),
        ids=("proprietary", "client_cleared"),
    )
    def test_p1_342_qccp_trade_leg_rwa_is_ead_times_the_art_306_weight(
        self, p1342_rows: dict[str, dict[str, dict]], regime: str, ref: str
    ) -> None:
        """``rwa_final`` is the measured EAD times the Art. 306 weight.

        An absolute pin, not a comparison against a baseline
        (`.claude/LESSONS.md` C1): two tests once let a 48% RWA movement
        through because they only asserted a direction.

        Assert:
            ``rwa_final`` equals the fixture's measured constant.
        """
        # Arrange
        expected_rwa = _QCCP_RWA[regime][ref]

        # Act
        actual_rwa = p1342_rows[regime][ref]["rwa_final"]

        # Assert
        assert actual_rwa == pytest.approx(expected_rwa, rel=1e-12), (
            f"P1.342/{regime}/{ref}: expected rwa_final={expected_rwa:,.6f} "
            f"(EAD x the Art. 306 weight), got {actual_rwa:,.6f}."
        )

    @pytest.mark.parametrize("regime", _REGIMES)
    @pytest.mark.parametrize("ref", _ALL_REFS)
    def test_p1_342_ead_is_carve_out_invariant(
        self, p1342_rows: dict[str, dict[str, dict]], regime: str, ref: str
    ) -> None:
        """All three netting sets share one SA-CCR EAD, and the carve-out must not move it.

        The three trades are the same CCR-A1 10y IR swap redenominated into USD,
        so SA-CCR (Art. 274(2)) prices them identically. Pinning EAD separately
        keeps the RWA assertions honest: a carve-out that changed EAD instead of
        the risk weight would still land the right RWA on one leg.

        Assert:
            ``ead_final`` equals the regime's measured EAD.
        """
        # Arrange
        expected_ead = _EAD[regime]

        # Act
        actual_ead = p1342_rows[regime][ref]["ead_final"]

        # Assert
        assert actual_ead == pytest.approx(expected_ead, rel=1e-9), (
            f"P1.342/{regime}/{ref}: expected ead_final={expected_ead:,.6f}, "
            f"got {actual_ead:,.6f}. The Art. 306 carve-out changes a RISK WEIGHT; "
            "SA-CCR EAD is not in its path."
        )


# ---------------------------------------------------------------------------
# The 50x anti-confound and the scope control.
# ---------------------------------------------------------------------------


class TestP1342FloorIsNeitherOverAppliedNorOverExempted:
    """The floor must not reach the Art. 306 legs, and must still reach the loan-shaped one."""

    @pytest.mark.parametrize("regime", _REGIMES)
    @pytest.mark.parametrize(
        "ref",
        (P1342_EXPOSURE_QCCP_PROP, P1342_EXPOSURE_QCCP_CLIENT),
        ids=("proprietary", "client_cleared"),
    )
    def test_p1_342_qccp_legs_are_not_floored_to_the_sovereign_residual(
        self, p1342_rows: dict[str, dict[str, dict]], regime: str, ref: str
    ) -> None:
        """Neither Art. 306 leg carries the unrated-sovereign residual.

        THE ANTI-CONFOUND. Measured by patching leg 2 alone with the carve-out
        absent: both QCCP legs go to ``risk_weight`` 1.00 and ``rwa_final``
        equal to the EAD, in both regimes — 50x on the proprietary leg, 25x on
        the client-cleared one. That is the exact failure this item exists to
        prevent, so it is pinned rather than left implicit behind the value
        assertions.

        Assert:
            ``risk_weight`` is not the Art. 114(1) unrated-sovereign residual,
            and ``rwa_final`` is not the floored figure.

        References:
            PRA PS1/26 Art. 114(1) — the residual the floor would impose.
        """
        # Arrange
        floored_rwa = _FLOORED_RWA[regime]
        row = p1342_rows[regime][ref]

        # Act
        actual_rw = row["risk_weight"]
        actual_rwa = row["rwa_final"]

        # Assert
        assert actual_rw != _FLOORED_RW, (
            f"P1.342/{regime}/{ref}: risk_weight is {actual_rw!r} — the Art. 114(1) "
            "unrated-sovereign residual. The Art. 121(6) floor has been applied to a "
            "QCCP TRADE exposure, overwriting the Art. 306 weight."
        )
        assert actual_rwa != pytest.approx(floored_rwa, rel=1e-9), (
            f"P1.342/{regime}/{ref}: rwa_final is {actual_rwa:,.2f}, the floored figure. "
            f"Correct is {_QCCP_RWA[regime][ref]:,.2f} — a "
            f"{floored_rwa / _QCCP_RWA[regime][ref]:.0f}x overstatement."
        )

    @pytest.mark.parametrize("regime", _REGIMES)
    def test_p1_342_ordinary_institution_stays_inside_the_floor(
        self, p1342_rows: dict[str, dict[str, dict]], regime: str
    ) -> None:
        """SCOPE CONTROL: the non-QCCP institution keeps its weight and its floor limb.

        ``NS-P1342-INST`` is an unrated ordinary institution in the same FR/USD
        shape, differing only by ``is_qccp=False``. A carve-out keyed on "is a
        CCR row" rather than "is a QCCP trade exposure" would hand this row 2%
        and understate it 50x (CRR) / 75x (B31).

        The reason pin is ``FLOOR_NOT_BINDING`` and it is load-bearing in a way
        the weight pin is not. Measured under leg 2 alone: this row reads
        ``floor_not_binding`` in both regimes — the floor arms, resolves to the
        Art. 114(1) 100% residual, and does not exceed the row's own weight. So
        ``FLOOR_NOT_BINDING`` is the only limb consistent with a correctly
        null-safe domesticity test. ``DOMESTIC_CURRENCY`` would leave the same
        NUMBER while meaning the engine decided a USD exposure to an FR
        counterparty is domestic — a wrong leg 2 that no value assertion here
        could see.

        Assert:
            The weight and RWA are unchanged, and the reason is
            ``FLOOR_NOT_BINDING`` — inside the floor, not carved out of it.

        References:
            CRR Art. 107(2) — an ordinary exposure to a QCCP, and a fortiori to
            a non-CCP institution, is an institution exposure under Art. 120-121.
        """
        # Arrange
        expected_rw = _INST_RW[regime]
        expected_rwa = _EAD[regime] * expected_rw
        row = p1342_rows[regime][P1342_EXPOSURE_INST]

        # Act
        actual_rw = row["risk_weight"]
        actual_rwa = row["rwa_final"]
        reason = row[SA_RISK_WEIGHT_BRANCH_REASON]

        # Assert
        assert actual_rw == expected_rw, (
            f"P1.342/{regime}/{P1342_EXPOSURE_INST}: expected risk_weight={expected_rw}, "
            f"got {actual_rw!r}. This counterparty has is_qccp=False — the Art. 306 "
            "carve-out must not reach it. Gate the carve-out on the QCCP flag AND the "
            "CCR trade risk_type, not on the row being synthetic."
        )
        assert actual_rwa == pytest.approx(expected_rwa, rel=1e-12), (
            f"P1.342/{regime}/{P1342_EXPOSURE_INST}: expected rwa_final="
            f"{expected_rwa:,.6f}, got {actual_rwa:,.6f}."
        )
        assert reason == SovereignFloorReason.FLOOR_NOT_BINDING.value, (
            f"P1.342/{regime}/{P1342_EXPOSURE_INST}: expected "
            f"{SovereignFloorReason.FLOOR_NOT_BINDING.value!r}, got {reason!r}. "
            "This row must stay INSIDE Art. 121(6): the floor arms, resolves to the "
            "Art. 114(1) unrated-sovereign residual, and does not exceed the row's own "
            f"weight ({expected_rw}). "
            f"{SovereignFloorReason.DOMESTIC_CURRENCY.value!r} would mean a USD exposure "
            "to an FR counterparty was read as domestic; a carve-out reason would mean "
            "the exemption leaked past the QCCP trade-exposure gate; "
            f"{UNKNOWN_FALLBACK!r} would mean leg 2 was fixed only for QCCP rows."
        )
