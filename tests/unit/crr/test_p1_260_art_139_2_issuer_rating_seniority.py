"""
P1.260 — CRR Art. 139(2): a junior exposure keeps an issuer rating only if it
produces the HIGHER risk weight.

CRR Art. 139 (legislation.gov.uk/eur/2013/575/article/139; ``docs/assets/crr.pdf``
is a 0-byte file in this tree, so the text is the watchfire snapshot of the same
page, which matches the legislation.gov.uk XML the Wave 0 audit fetched):

    (1) "Where a credit assessment exists for a specific issuing programme or
        facility to which the item constituting the exposure belongs, this
        credit assessment shall be used to determine the risk weight to be
        assigned to that item."
    (2) "Where no directly applicable credit assessment exists for a certain
        item, but a credit assessment exists for a specific issuing programme or
        facility to which the item constituting the exposure does not belong or
        a general credit assessment exists for the issuer, then that credit
        assessment shall be used in either of the following cases:
        (a) it produces a higher risk weight than would otherwise be the case
            and the exposure in question ranks pari passu or junior in all
            respects to the specific issuing program or facility or to senior
            unsecured exposures of that issuer, as relevant;
        (b) it produces a lower risk weight and the exposure in question ranks
            pari passu or senior in all respects to the specific issuing
            programme or facility or to senior unsecured exposures of that
            issuer, as relevant.
        In all other cases, the exposure shall be treated as unrated."

PS1/26 Art. 139(2) (``ps126app1.pdf`` page 71) keeps both limbs with the same
operative words and closes on "[Note: This rule corresponds to Article 139 of
CRR ...]" — the provision survives, it is not left blank.

A subordinated exposure ranks junior, so limb (b) can never apply to it: it
takes the issuer rating where that rating gives the higher weight (limb (a)),
and is otherwise treated as unrated — ``max(rated RW, unrated RW)``. The CRR SA
chain never read ``seniority``, so a subordinated corporate carrying its
issuer's CQS 2 took 50% where the unrated Art. 122(2) treatment gives 100%.

Which ratings are Art. 139(2) ratings: the engine attaches every long-term
rating counterparty-wide (``engine/hierarchy/ratings.py``) and cannot attach
one to an item, so a long-term rating is never "directly applicable" to a
subordinated item — whatever the defaulted ``rating_is_issue_specific`` flag
says. The one rating that IS the item's own is an exposure-scoped short-term
issue rating (``has_own_short_term_ecai``), which is Art. 139(1) and keeps its
weight. The moving legs therefore leave the flag at its default, and a
flag=False twin shows the outcome does not depend on it.

Basel 3.1: PS1/26 Art. 133(5) assigns 150% to a subordinated institution,
corporate or specialised-lending exposure whatever its rating, so the rated and
the unrated weight are both 150% and nothing moves — pinned by the B31 legs.

The institution survivor is the leak detector the audit asked for: a gate that
compared against the TABLE's unrated institution weight (100%) instead of the
Art. 121(1) sovereign-derived weight would treat a CQS 2 (50%) row in a CQS 1
sovereign as unrated and drop it to 20%, a 30pp capital cut.

References:
    - CRR Art. 139(1)/(2); PS1/26 Art. 139(1)/(2); PS1/26 Art. 133(5).
    - CRR Art. 122(1)/(2) (corporate rated / unrated), Art. 120(1) Table 3,
      Art. 121(1) Table 5 / 121(3) (institution rated / unrated),
      Art. 131 Table 7 (short-term ECAI).
    - src/rwa_calc/engine/sa/issuer_rating_seniority.py.
    - IMPLEMENTATION_PLAN.md: P1.260.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.sa import SACalculator

_EAD = 1_000_000.0


@pytest.fixture
def crr_config() -> CalculationConfig:
    """CRR configuration."""
    return CalculationConfig.crr(reporting_date=date(2025, 12, 31))


@pytest.fixture
def b31_config() -> CalculationConfig:
    """Basel 3.1 configuration."""
    return CalculationConfig.basel_3_1(reporting_date=date(2027, 6, 30))


def _risk_weight(
    config: CalculationConfig,
    *,
    exposure_class: str,
    cqs: int | None,
    seniority: str,
    sovereign_cqs: int | None = None,
    maturity_years: float = 5.0,
    residual_maturity_years: float | None = None,
    issue_specific: bool | None = None,
    short_term_ecai: str = "none",
    obligor_st_facility: str = "none",
    managed_as_retail: bool = False,
    risk_type: str | None = None,
    sl_type: str | None = None,
) -> float:
    """Run one SA row through ``SACalculator.calculate_branch`` and return its RW.

    ``issue_specific=None`` leaves ``external_rating_is_issue_specific`` out of
    the frame, so the SA input contract supplies its default (True) — the shape
    every long-term rating in the standard fixture arrives with.

    ``maturity_years`` sets both maturities; ``residual_maturity_years``
    overrides the residual one (a long-dated loan near its maturity date).

    ``short_term_ecai`` marks a short-term assessment the way
    ``engine/hierarchy/enrich.py`` does: ``"own"`` is an exposure-scoped issue
    rating (``has_short_term_ecai`` and ``has_own_short_term_ecai`` True);
    ``"spilled"`` is one handed over from another of the obligor's facilities
    by the Art. 120(3)(c) spillover (``has_short_term_ecai`` only).

    ``obligor_st_facility`` sets the Art. 140(2) obligor flags the hierarchy
    broadcasts: ``"150"`` where the obligor carries a 150%-weighted short-term
    rated facility (limb (a)), ``"50"`` where it carries a 50%-weighted one
    (limb (b)).
    """
    data: dict[str, list[object]] = {
        "exposure_reference": ["P1_260"],
        "ead_final": [_EAD],
        "ead_gross": [_EAD],
        "exposure_class": [exposure_class],
        "cqs": [cqs],
        "seniority": [seniority],
        "cp_sovereign_cqs": [sovereign_cqs],
        "cp_country_code": ["GB"],
        "currency": ["GBP"],
        "residual_maturity_years": [
            maturity_years if residual_maturity_years is None else residual_maturity_years
        ],
        "original_maturity_years": [maturity_years],
        "has_short_term_ecai": [short_term_ecai in ("own", "spilled")],
        "has_own_short_term_ecai": [short_term_ecai == "own"],
        "obligor_st_150_contamination": [obligor_st_facility == "150"],
        "obligor_st_50_floor": [obligor_st_facility == "50"],
        "cp_is_managed_as_retail": [managed_as_retail],
        "qualifies_as_retail": [managed_as_retail],
        "risk_type": [risk_type],
        "sl_type": [sl_type],
        "is_defaulted": [False],
        "provision_allocated": [0.0],
        "provision_deducted": [0.0],
    }
    schema: dict[str, pl.PolarsDataType] = {
        "cqs": pl.Int8,
        "cp_sovereign_cqs": pl.Int32,
        "risk_type": pl.String,
        "sl_type": pl.String,
    }
    if issue_specific is not None:
        data["external_rating_is_issue_specific"] = [issue_specific]
    frame = pl.DataFrame(data, schema_overrides=schema).lazy()
    row = SACalculator().calculate_branch(frame, config).collect().row(0, named=True)
    return float(row["risk_weight"])


class TestCrrSubordinatedIssuerRatingTreatedAsUnrated:
    """Art. 139(2): the rating gives a LOWER weight, the row ranks junior -> unrated."""

    @pytest.mark.parametrize(
        ("exposure_class", "cqs", "sovereign_cqs", "expected"),
        [
            # Art. 122(2): unrated corporate = max(100%, sovereign weight).
            pytest.param("corporate", 2, 1, 1.00, id="corporate-cqs2-50pct-to-100pct"),
            pytest.param("corporate", 1, 1, 1.00, id="corporate-cqs1-20pct-to-100pct"),
            pytest.param("corporate_sme", 2, 1, 1.00, id="corporate-sme-cqs2-50pct-to-100pct"),
            # Art. 122(2) "whichever is the higher": a CQS 6 sovereign (150%)
            # binds, so a CQS 3 (100%) rating is below the unrated weight too.
            pytest.param("corporate", 3, 6, 1.50, id="corporate-cqs3-in-cqs6-sovereign-to-150pct"),
            # Art. 121(1) Table 5: unrated institution in a CQS 2 sovereign = 50%.
            pytest.param(
                "institution", 1, 2, 0.50, id="institution-cqs1-in-cqs2-sovereign-to-50pct"
            ),
        ],
    )
    def test_subordinated_row_takes_the_unrated_weight(
        self,
        crr_config: CalculationConfig,
        exposure_class: str,
        cqs: int,
        sovereign_cqs: int,
        expected: float,
    ) -> None:
        """A subordinated row whose issuer rating gives the lower RW is risk-weighted as unrated."""
        # Arrange / Act
        rw = _risk_weight(
            crr_config,
            exposure_class=exposure_class,
            cqs=cqs,
            seniority="subordinated",
            sovereign_cqs=sovereign_cqs,
        )

        # Assert
        assert rw == pytest.approx(expected)

    def test_subordinated_specialised_lending_takes_the_unrated_weight(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """CRR SA specialised lending is a corporate: CQS 2 (50%) junior -> unrated 100%."""
        # Arrange / Act
        rw = _risk_weight(
            crr_config,
            exposure_class="specialised_lending",
            cqs=2,
            seniority="subordinated",
            sovereign_cqs=1,
            sl_type="object_finance",
        )

        # Assert
        assert rw == pytest.approx(1.00)

    def test_outcome_does_not_depend_on_the_issue_specific_flag(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """A long-term rating is counterparty-wide whatever the flag says: True and False agree."""
        # Arrange / Act
        flagged_issuer_level = _risk_weight(
            crr_config,
            exposure_class="corporate",
            cqs=2,
            seniority="subordinated",
            sovereign_cqs=1,
            issue_specific=False,
        )
        flagged_issue_specific = _risk_weight(
            crr_config,
            exposure_class="corporate",
            cqs=2,
            seniority="subordinated",
            sovereign_cqs=1,
            issue_specific=True,
        )

        # Assert
        assert (flagged_issuer_level, flagged_issue_specific) == pytest.approx((1.00, 1.00))


class TestCrrIssuerRatingKept:
    """Rows Art. 139 leaves on their rated weight — each guards one wrong widening."""

    def test_limb_a_higher_rated_weight_is_kept(self, crr_config: CalculationConfig) -> None:
        """Limb (a): CQS 5 gives 150%, above the 100% unrated weight, and the row is junior."""
        # Arrange / Act
        rw = _risk_weight(
            crr_config, exposure_class="corporate", cqs=5, seniority="subordinated", sovereign_cqs=1
        )

        # Assert
        assert rw == pytest.approx(1.50)

    def test_equal_weights_stay_at_that_weight(self, crr_config: CalculationConfig) -> None:
        """CQS 3 gives 100%, equal to the unrated weight: the row stays at 100%.

        An invariance pin, not a detector: rated and unrated weights agree, so
        no decision the seniority test can take moves this row's weight.
        """
        # Arrange / Act
        rw = _risk_weight(
            crr_config, exposure_class="corporate", cqs=3, seniority="subordinated", sovereign_cqs=1
        )

        # Assert
        assert rw == pytest.approx(1.00)

    def test_institution_compared_with_its_sovereign_derived_unrated_weight(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """Leak detector: CQS 2 (50%) beats the Art. 121(1) unrated 20% in a CQS 1 sovereign.

        A gate that read the table's unrated institution weight (100%) would
        treat this row as unrated and cut it to 20%.
        """
        # Arrange / Act
        rw = _risk_weight(
            crr_config,
            exposure_class="institution",
            cqs=2,
            seniority="subordinated",
            sovereign_cqs=1,
        )

        # Assert
        assert rw == pytest.approx(0.50)

    @pytest.mark.parametrize(
        ("exposure_class", "cqs", "sovereign_cqs", "expected"),
        [
            pytest.param("corporate", 2, 1, 0.50, id="senior-corporate-cqs2"),
            pytest.param("institution", 1, 2, 0.20, id="senior-institution-cqs1"),
        ],
    )
    def test_senior_row_keeps_its_rating(
        self,
        crr_config: CalculationConfig,
        exposure_class: str,
        cqs: int,
        sovereign_cqs: int,
        expected: float,
    ) -> None:
        """Limb (b): a senior row keeps a lower issuer-rated weight — no seniority spill."""
        # Arrange / Act
        rw = _risk_weight(
            crr_config,
            exposure_class=exposure_class,
            cqs=cqs,
            seniority="senior",
            sovereign_cqs=sovereign_cqs,
        )

        # Assert
        assert rw == pytest.approx(expected)

    def test_own_short_term_issue_rating_is_directly_applicable(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """Art. 139(1): the item's own short-term issue rating keeps its Table 7 weight (20%)."""
        # Arrange / Act
        rw = _risk_weight(
            crr_config,
            exposure_class="corporate",
            cqs=1,
            seniority="subordinated",
            sovereign_cqs=1,
            maturity_years=0.2,
            short_term_ecai="own",
        )

        # Assert
        assert rw == pytest.approx(0.20)


class TestCrrUnratedWeightIncludesArt140Contamination:
    """Art. 139(2) compares against the weight the row takes AS UNRATED — Art. 140(2) included.

    CRR Art. 140(2) (watchfire snapshot of legislation.gov.uk/eur/2013/575/
    article/140; PS1/26 Art. 140(2), ``ps126app1.pdf`` page 72, same words):
    "(a) if a short-term rated facility is assigned a 150 % risk weight, then
    all unrated unsecured exposures on that obligor whether short-term or
    long-term shall also be assigned a 150 % risk weight; (b) if a short-term
    rated facility is assigned a 50 % risk-weight, no unrated short-term
    exposure shall be assigned a risk weight lower than 100 %."

    A row Art. 139(2) treats as unrated IS an unrated unsecured exposure on
    that obligor, so "the risk weight ... than would otherwise be the case" is
    the Art. 140(2) weight. Comparing against the ladder's unrated weight alone
    left a subordinated CQS 3 corporate of a contaminated obligor at 100% while
    a CQS 2 one went to 150%.
    """

    @pytest.mark.parametrize(
        ("exposure_class", "cqs", "expected"),
        [
            # Rated 100% (CQS 3) vs unrated 150% (Art. 140(2)(a)) -> unrated.
            pytest.param("corporate", 3, 1.50, id="corporate-cqs3-100pct-to-150pct"),
            # Rated 50% (Table 3 CQS 2) vs unrated 150% -> unrated. The ladder's
            # own unrated weight is 20% (Table 5, sovereign CQS 1), which hid it.
            pytest.param("institution", 2, 1.50, id="institution-cqs2-50pct-to-150pct"),
            pytest.param("corporate", 2, 1.50, id="corporate-cqs2-50pct-to-150pct"),
        ],
    )
    def test_subordinated_row_of_a_150pct_obligor_takes_150pct(
        self,
        crr_config: CalculationConfig,
        exposure_class: str,
        cqs: int,
        expected: float,
    ) -> None:
        """Limb (a) obligor: a junior row whose rating gives less than 150% is unrated -> 150%."""
        # Arrange / Act
        rw = _risk_weight(
            crr_config,
            exposure_class=exposure_class,
            cqs=cqs,
            seniority="subordinated",
            sovereign_cqs=1,
            obligor_st_facility="150",
        )

        # Assert
        assert rw == pytest.approx(expected)

    def test_weights_of_a_150pct_obligor_are_monotone_in_cqs(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """Every subordinated corporate CQS of a limb (a) obligor ends at 150%.

        The regression this pins: with the ladder-only basis CQS 1/2 moved to
        150% while CQS 3/4 kept 100% — a better rating gave a higher weight.
        """
        # Arrange / Act
        weights = [
            _risk_weight(
                crr_config,
                exposure_class="corporate",
                cqs=cqs,
                seniority="subordinated",
                sovereign_cqs=1,
                obligor_st_facility="150",
            )
            for cqs in range(1, 7)
        ]

        # Assert
        assert weights == pytest.approx([1.50] * 6)

    def test_short_term_row_of_a_50pct_obligor_takes_the_100pct_floor(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """Limb (b) obligor: Table 4 CQS 2 (20%) vs unrated max(Art. 121(3) 20%, 100%) -> 100%."""
        # Arrange / Act
        rw = _risk_weight(
            crr_config,
            exposure_class="institution",
            cqs=2,
            seniority="subordinated",
            sovereign_cqs=1,
            maturity_years=0.2,
            obligor_st_facility="50",
        )

        # Assert
        assert rw == pytest.approx(1.00)

    def test_sme_managed_as_retail_of_a_150pct_obligor_takes_150pct(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """An SME weighted as retail (75%) whatever its CQS 5 rating; unrated, Art. 140(2) -> 150%.

        The ladder's Art. 123 branch ignores ``cqs``, so the rated weight is the
        retail 75%, not the corporate table's CQS 5 150%; reading the table
        kept the rating and left the row at 75%. The 150% is the weight the
        engine already gives this row's unrated twin.
        """
        # Arrange / Act
        rw = _risk_weight(
            crr_config,
            exposure_class="corporate_sme",
            cqs=5,
            seniority="subordinated",
            sovereign_cqs=1,
            managed_as_retail=True,
            obligor_st_facility="150",
        )

        # Assert
        assert rw == pytest.approx(1.50)

    def test_senior_row_of_a_150pct_obligor_keeps_its_rating(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """Limb (b) of Art. 139(2): a senior rated row keeps 50% — it is not an unrated exposure."""
        # Arrange / Act
        rw = _risk_weight(
            crr_config,
            exposure_class="corporate",
            cqs=2,
            seniority="senior",
            sovereign_cqs=1,
            obligor_st_facility="150",
        )

        # Assert
        assert rw == pytest.approx(0.50)


class TestCrrRatedWeightMirrorsTheLadder:
    """The rated side of the comparison takes the ladder's branch: Table 4 / Table 7 / Table 3."""

    def test_short_dated_institution_compares_its_table_4_weight(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """Art. 120(2) Table 4: CQS 2 at 0.2y residual is 20%, below the unrated Table 5 50%.

        Original maturity 5y, so Art. 121(3)'s 20% (original <= 3m) does not
        apply to the unrated weight. Comparing the Table 3 weight (50%) instead
        would keep the rating and leave the row at 20%.
        """
        # Arrange / Act
        rw = _risk_weight(
            crr_config,
            exposure_class="institution",
            cqs=2,
            seniority="subordinated",
            sovereign_cqs=2,
            maturity_years=5.0,
            residual_maturity_years=0.2,
        )

        # Assert
        assert rw == pytest.approx(0.50)

    def test_spilled_short_term_rating_compares_its_table_7_weight(
        self,
        crr_config: CalculationConfig,
    ) -> None:
        """Art. 131 Table 7: a spilled short-term CQS 3 is 100%, above the unrated 50% -> kept.

        Comparing the Table 4 weight (20%) instead would treat the row as
        unrated and cut it to 50%.
        """
        # Arrange / Act
        rw = _risk_weight(
            crr_config,
            exposure_class="institution",
            cqs=3,
            seniority="subordinated",
            sovereign_cqs=2,
            maturity_years=5.0,
            residual_maturity_years=0.2,
            short_term_ecai="spilled",
        )

        # Assert
        assert rw == pytest.approx(1.00)


class TestCrrRowsWithoutAChapter2Assessment:
    """Rows the ladder weights without a credit assessment are outside the test."""

    def test_own_funds_line_keeps_its_1250pct(self, crr_config: CalculationConfig) -> None:
        """A settlement-risk own-funds line stays at 12.5 even for a subordinated 150% obligor.

        Treating it as unrated would make it an Art. 140(2) target, and that
        override would replace the Art. 92(3)(ca) 12.5 factor with 150%.
        """
        # Arrange / Act
        rw = _risk_weight(
            crr_config,
            exposure_class="institution",
            cqs=1,
            seniority="subordinated",
            sovereign_cqs=1,
            obligor_st_facility="150",
            risk_type="SETTLEMENT_FAILED_TRADE",
        )

        # Assert
        assert rw == pytest.approx(12.5)


class TestBasel31SubordinatedDebtUnmoved:
    """PS1/26 Art. 133(5) already gives 150% at every CQS; Art. 139(2) moves nothing.

    The Basel 3.1 weight cannot be reddened through the seniority test: running
    it on the PS1/26 ladder too (dropping its Feature check) still gives 150%,
    because Art. 133(5) outranks the CQS table. These legs pin the measured
    neutrality; they do not detect that mutation.
    """

    @pytest.mark.parametrize(
        ("exposure_class", "cqs", "sovereign_cqs"),
        [
            pytest.param("corporate", 2, 1, id="corporate-cqs2"),
            pytest.param("institution", 1, 2, id="institution-cqs1-in-cqs2-sovereign"),
            pytest.param("institution", 2, 1, id="institution-cqs2-in-cqs1-sovereign"),
        ],
    )
    def test_subordinated_row_stays_at_150pct(
        self,
        b31_config: CalculationConfig,
        exposure_class: str,
        cqs: int,
        sovereign_cqs: int,
    ) -> None:
        """Every subordinated institution / corporate row is 150% before and after."""
        # Arrange / Act
        rw = _risk_weight(
            b31_config,
            exposure_class=exposure_class,
            cqs=cqs,
            seniority="subordinated",
            sovereign_cqs=sovereign_cqs,
        )

        # Assert
        assert rw == pytest.approx(1.50)

    def test_art_139_2b_sl_disapplication_still_reads_the_flag(
        self,
        b31_config: CalculationConfig,
    ) -> None:
        """Art. 139(2B) is untouched: a flag=False senior SL row is unrated, flag=True keeps CQS 1."""
        # Arrange / Act
        issuer_level = _risk_weight(
            b31_config,
            exposure_class="specialised_lending",
            cqs=1,
            seniority="senior",
            sovereign_cqs=1,
            issue_specific=False,
            sl_type="object_finance",
        )
        issue_specific = _risk_weight(
            b31_config,
            exposure_class="specialised_lending",
            cqs=1,
            seniority="senior",
            sovereign_cqs=1,
            issue_specific=True,
            sl_type="object_finance",
        )

        # Assert: Art. 122B(2)(b) object finance 100% vs Table 6 CQS 1 20%.
        assert (issuer_level, issue_specific) == pytest.approx((1.00, 0.20))
