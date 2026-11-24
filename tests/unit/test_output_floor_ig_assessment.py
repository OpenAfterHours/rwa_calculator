"""
Basel 3.1 Art. 122(6) / Art. 122(8) — two independent investment-grade elections.

PRA PS1/26 Art. 122 holds two elections that the engine used to drive from
one flag (P1.475):

- Art. 122(6) is a PRA *permission* for the Standardised Approach: with it,
  an unrated non-SME corporate the firm assesses as investment grade takes
  65% and one assessed as not investment grade 135%; without it, Art. 122(5)
  gives 100%. ``CalculationConfig.sa_investment_grade_permission``.
- Art. 122(8) is an output-floor-only choice for the corporates a firm
  weights under the IRB Approach: (a) 100%, or (b) the paragraph 6 weights,
  on *notice* to the PRA — no permission. Art. 92(3A)(b)(ii) routes S-TREA to
  it. ``CalculationConfig.output_floor_investment_grade_election``.

Neither implies the other, so the tests below run every combination and show
each election moving only its own population: SA-branch rows (approach
``standardised`` — including an SA-CCR leg, which keeps that approach though
the floor counts it) follow the permission; F-IRB / A-IRB rows' SA-equivalent
``sa_rwa`` follows the election. Para 11 (SME, 85%) overrides both. The
deprecated ``use_investment_grade_assessment`` stands in for each election left
unstated — through the factory, the constructor and ``dataclasses.replace``
alike — so every existing configuration keeps its numbers, and its
DeprecationWarning lands on the caller's own line. CRR has no investment-grade
approach and no output floor: both elections are inert there.

Why this matters:
    For a floor-binding IRB firm the election alone moves S-TREA: an IG
    unrated IRB corporate falls from 100% to 65% and a non-IG one rises to
    135%. Driving it from the SA permission misstated either the SA RWEA or
    the S-TREA of any firm that holds one election and not the other.

References:
- PRA PS1/26 Art. 122(5), (6), (8), (9), (11): unrated corporate weights
- PRA PS1/26 Art. 92(3A)(b)(ii): S-TREA uses Art. 122(8)(a) or (b)
- PRA PS1/26 Art. 92(2A): output floor formula
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from dataclasses import replace
from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType, PermissionMode, RiskType
from rwa_calc.engine.aggregator.aggregator import OutputAggregator
from rwa_calc.engine.sa.calculator import SACalculator
from tests.fixtures.contract_columns import pad_irb_branch, pad_sa_branch, pad_slotting_branch

# --- Helpers ---

# Padded zero-row branch frames mirroring the orchestrator's sealed branch
# collect — empty branches still carry the full edge schema in production.
EMPTY = pl.LazyFrame({"exposure_reference": pl.Series([], dtype=pl.String)})
EMPTY_SA = pad_sa_branch(EMPTY)
EMPTY_SLOTTING = pad_slotting_branch(EMPTY)

_EAD = 1_000_000.0


def _irb_corporate_frame(
    *,
    ead: float = 1_000_000.0,
    rwa: float = 500_000.0,
    sa_rwa: float = 1_000_000.0,
    exposure_class: str = "corporate",
    ref: str = "EXP1",
) -> pl.LazyFrame:
    """Build a minimal IRB corporate exposure with pre-baked sa_rwa."""
    return pad_irb_branch(
        pl.LazyFrame(
            {
                "exposure_reference": [ref],
                "exposure_class": [exposure_class],
                "approach_applied": ["FIRB"],
                "ead_final": [ead],
                "risk_weight": [rwa / ead if ead > 0 else 0.0],
                "rwa_final": [rwa],
                "sa_rwa": [sa_rwa],
            }
        )
    )


def _b31_config(
    *,
    use_ig: bool = False,
    reporting_date: date = date(2032, 1, 1),
) -> CalculationConfig:
    """B31 IRB config holding both investment-grade elections, or neither."""
    return CalculationConfig.basel_3_1(
        reporting_date=reporting_date,
        permission_mode=PermissionMode.IRB,
        sa_investment_grade_permission=use_ig,
        output_floor_investment_grade_election=use_ig,
    )


def _b31_elections(*, permission: bool, election: bool) -> CalculationConfig:
    """B31 IRB config with each investment-grade election set independently."""
    return CalculationConfig.basel_3_1(
        reporting_date=date(2032, 1, 1),
        permission_mode=PermissionMode.IRB,
        sa_investment_grade_permission=permission,
        output_floor_investment_grade_election=election,
    )


#: One row per population the two elections must keep apart. Every row is an
#: unrated corporate (no ECAI assessment, ``cqs`` null) with EAD 1,000,000.
#: ``approach`` uses the real ``ApproachType`` values: an invented ``"firb"``
#: is not an IRB approach to ``engine/branch_split.py`` and would put the row on
#: the SA branch (LESSONS B3).
_ELECTION_ROWS: dict[str, tuple[str, str, bool, str | None]] = {
    # ref: (approach, exposure_class, cp_is_investment_grade, risk_type)
    "SA_IG": (ApproachType.SA.value, "corporate", True, None),
    "SA_NIG": (ApproachType.SA.value, "corporate", False, None),
    "FIRB_IG": (ApproachType.FIRB.value, "corporate", True, None),
    "FIRB_NIG": (ApproachType.FIRB.value, "corporate", False, None),
    "AIRB_IG": (ApproachType.AIRB.value, "corporate", True, None),
    # SA-CCR derivative leg: weighted by the SA (approach stays "standardised")
    # although the floor counts it — so it is a 122(6) row, never a 122(8) one.
    "CCR_IG": (ApproachType.SA.value, "corporate", True, RiskType.CCR_DERIVATIVE.value),
    # Para 11: a non-retail SME takes 85% whatever either election says.
    "FIRB_SME_IG": (ApproachType.FIRB.value, "corporate_sme", True, None),
}


def _election_frame() -> pl.LazyFrame:
    """The unified (pre-split) frame ``calculate_unified`` sees: SA + IRB rows."""
    refs = list(_ELECTION_ROWS)
    return pl.LazyFrame(
        {
            "exposure_reference": refs,
            "approach": [_ELECTION_ROWS[r][0] for r in refs],
            "exposure_class": [_ELECTION_ROWS[r][1] for r in refs],
            "ead_final": [_EAD] * len(refs),
            "cqs": pl.Series([None] * len(refs), dtype=pl.Int8),
            "cp_is_investment_grade": [_ELECTION_ROWS[r][2] for r in refs],
            "risk_type": pl.Series([_ELECTION_ROWS[r][3] for r in refs], dtype=pl.String),
        }
    )


def _risk_weights(config: CalculationConfig) -> dict[str, float]:
    """Run the unified SA pass and return each row's SA(-equivalent) risk weight."""
    result = SACalculator().calculate_unified(_election_frame(), config).collect()
    return dict(zip(result["exposure_reference"], result["risk_weight"], strict=True))


def _sa_rwa(config: CalculationConfig) -> dict[str, float]:
    """Run the unified SA pass and return each row's ``sa_rwa`` (S-TREA input)."""
    result = SACalculator().calculate_unified(_election_frame(), config).collect()
    return dict(zip(result["exposure_reference"], result["sa_rwa"], strict=True))


# --- The two elections are independent (P1.475) ---


class TestInvestmentGradeElectionsAreIndependent:
    """Art. 122(6) governs SA-branch rows; Art. 122(8)(b) governs IRB rows' sa_rwa.

    Absolute values per row (EAD 1,000,000): 65% -> 650,000, 100% -> 1,000,000,
    135% -> 1,350,000, SME 85% -> 850,000. Each case is red under one shared
    flag, because no single setting gives SA and IRB rows different weights.
    """

    @pytest.mark.parametrize(
        ("permission", "election", "expected"),
        [
            pytest.param(
                False,
                True,
                {
                    "SA_IG": 1_000_000.0,
                    "SA_NIG": 1_000_000.0,
                    "FIRB_IG": 650_000.0,
                    "FIRB_NIG": 1_350_000.0,
                    "AIRB_IG": 650_000.0,
                    "CCR_IG": 1_000_000.0,
                    "FIRB_SME_IG": 850_000.0,
                },
                id="122(8)(b)-notice-without-122(6)-permission",
            ),
            pytest.param(
                True,
                False,
                {
                    "SA_IG": 650_000.0,
                    "SA_NIG": 1_350_000.0,
                    "FIRB_IG": 1_000_000.0,
                    "FIRB_NIG": 1_000_000.0,
                    "AIRB_IG": 1_000_000.0,
                    "CCR_IG": 650_000.0,
                    "FIRB_SME_IG": 850_000.0,
                },
                id="122(6)-permission-with-122(8)(a)-floor",
            ),
            pytest.param(
                True,
                True,
                {
                    "SA_IG": 650_000.0,
                    "SA_NIG": 1_350_000.0,
                    "FIRB_IG": 650_000.0,
                    "FIRB_NIG": 1_350_000.0,
                    "AIRB_IG": 650_000.0,
                    "CCR_IG": 650_000.0,
                    "FIRB_SME_IG": 850_000.0,
                },
                id="both",
            ),
            pytest.param(
                False,
                False,
                {
                    "SA_IG": 1_000_000.0,
                    "SA_NIG": 1_000_000.0,
                    "FIRB_IG": 1_000_000.0,
                    "FIRB_NIG": 1_000_000.0,
                    "AIRB_IG": 1_000_000.0,
                    "CCR_IG": 1_000_000.0,
                    "FIRB_SME_IG": 850_000.0,
                },
                id="neither",
            ),
        ],
    )
    def test_each_election_moves_only_its_own_population(
        self, permission: bool, election: bool, expected: dict[str, float]
    ) -> None:
        """sa_rwa per row equals EAD x the weight its own election selects."""
        # Arrange
        config = _b31_elections(permission=permission, election=election)

        # Act
        sa_rwa = _sa_rwa(config)

        # Assert
        assert sa_rwa == pytest.approx(expected)

    def test_deprecated_alias_sets_both_elections(self) -> None:
        """use_investment_grade_assessment=True still gives 65/135 on every row."""
        # Arrange
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            config = CalculationConfig.basel_3_1(
                reporting_date=date(2032, 1, 1),
                permission_mode=PermissionMode.IRB,
                use_investment_grade_assessment=True,
            )

        # Act
        sa_rwa = _sa_rwa(config)

        # Assert
        assert sa_rwa == pytest.approx(
            {
                "SA_IG": 650_000.0,
                "SA_NIG": 1_350_000.0,
                "FIRB_IG": 650_000.0,
                "FIRB_NIG": 1_350_000.0,
                "AIRB_IG": 650_000.0,
                "CCR_IG": 650_000.0,
                "FIRB_SME_IG": 850_000.0,
            }
        )

    @pytest.mark.parametrize(
        ("alias", "expected"),
        [
            pytest.param(
                True,
                {
                    "SA_IG": 650_000.0,
                    "SA_NIG": 1_350_000.0,
                    "FIRB_IG": 650_000.0,
                    "FIRB_NIG": 1_350_000.0,
                    "AIRB_IG": 650_000.0,
                    "CCR_IG": 650_000.0,
                    "FIRB_SME_IG": 850_000.0,
                },
                id="replace-alias-on-a-default-config",
            ),
            pytest.param(
                False,
                {
                    "SA_IG": 1_000_000.0,
                    "SA_NIG": 1_000_000.0,
                    "FIRB_IG": 1_000_000.0,
                    "FIRB_NIG": 1_000_000.0,
                    "AIRB_IG": 1_000_000.0,
                    "CCR_IG": 1_000_000.0,
                    "FIRB_SME_IG": 850_000.0,
                },
                id="replace-alias-off-an-alias-config",
            ),
        ],
    )
    def test_deprecated_alias_applied_by_dataclasses_replace(
        self, alias: bool, expected: dict[str, float]
    ) -> None:
        """``replace(config, use_investment_grade_assessment=...)`` keeps its old numbers.

        Before the split, ``replace`` of the single flag moved every row both ways.
        The alias must too: a config that resolved its elections at construction
        would carry them through ``replace`` unchanged (SA non-IG RWEA and the
        non-IG S-TREA leg 135% -> 100% on the way on, the reverse on the way off).
        """
        # Arrange
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            base = CalculationConfig.basel_3_1(
                reporting_date=date(2032, 1, 1),
                permission_mode=PermissionMode.IRB,
                use_investment_grade_assessment=not alias,
            )
            config = replace(base, use_investment_grade_assessment=alias)

        # Act
        sa_rwa = _sa_rwa(config)

        # Assert
        assert sa_rwa == pytest.approx(expected)

    def test_both_elections_inert_under_crr(self) -> None:
        """CRR Art. 122 has no investment-grade approach: every unrated row is 100%."""
        # Arrange
        config = replace(
            CalculationConfig.crr(
                reporting_date=date(2026, 6, 30), permission_mode=PermissionMode.IRB
            ),
            sa_investment_grade_permission=True,
            output_floor_investment_grade_election=True,
        )

        # Act
        weights = _risk_weights(config)

        # Assert
        non_sme = {ref: rw for ref, rw in weights.items() if ref != "FIRB_SME_IG"}
        assert non_sme == pytest.approx(dict.fromkeys(non_sme, 1.0))


class TestInvestmentGradeAssessmentCarrier:
    """``sa_investment_grade_assessed`` records the weight paragraph 6 set under the row's election.

    True (65%) / False (135%) where the row's own election is held, the row is an
    unrated non-SME corporate, and that paragraph 6 weight is its exposure-class
    weight; null otherwise — election off, a para 11 SME (85%), and alike every
    row on which another rule sets the weight (Art. 133(5) subordinated debt,
    Art. 127 default). OF 08.01 row 0200 reads it, so it must follow the election
    and the weight, never the raw ``cp_is_investment_grade`` input.
    """

    @pytest.mark.parametrize(
        ("permission", "election", "expected"),
        [
            pytest.param(
                False,
                True,
                {
                    "SA_IG": None,
                    "SA_NIG": None,
                    "FIRB_IG": True,
                    "FIRB_NIG": False,
                    "AIRB_IG": True,
                    "CCR_IG": None,
                    "FIRB_SME_IG": None,
                },
                id="election-only",
            ),
            pytest.param(
                True,
                False,
                {
                    "SA_IG": True,
                    "SA_NIG": False,
                    "FIRB_IG": None,
                    "FIRB_NIG": None,
                    "AIRB_IG": None,
                    "CCR_IG": True,
                    "FIRB_SME_IG": None,
                },
                id="permission-only",
            ),
        ],
    )
    def test_carrier_follows_the_row_s_own_election(
        self, permission: bool, election: bool, expected: dict[str, bool | None]
    ) -> None:
        """The carrier is set by the election that governs the row, and only that one."""
        # Arrange
        config = _b31_elections(permission=permission, election=election)

        # Act
        result = SACalculator().calculate_unified(_election_frame(), config).collect()
        carrier = dict(
            zip(result["exposure_reference"], result["sa_investment_grade_assessed"], strict=True)
        )

        # Assert
        assert carrier == expected

    @pytest.mark.parametrize(
        ("permission", "election", "approach"),
        [
            pytest.param(False, True, ApproachType.FIRB.value, id="122(8)(b)-on-f-irb"),
            pytest.param(True, False, ApproachType.SA.value, id="122(6)-on-sa"),
        ],
    )
    def test_carrier_is_null_where_another_rule_sets_the_weight(
        self, permission: bool, election: bool, approach: str
    ) -> None:
        """An IG-assessed subordinated or defaulted leg is outside paragraph 6: null.

        Art. 122(8) reaches only "the exposure class set out in point (g) of
        Article 112(1)"; Table A2 puts a subordinated instrument in point (p)
        (Art. 133(5) 150%) and an exposure in default in point (j) (Art. 127:
        150% here, specific provisions under 20%). The control leg keeps 65% and
        True, so a carrier nulled everywhere cannot pass.
        """
        # Arrange
        config = _b31_elections(permission=permission, election=election)
        frame = pl.LazyFrame(
            {
                "exposure_reference": ["IG", "SUB_IG", "DEF_IG"],
                "approach": [approach] * 3,
                "exposure_class": ["corporate"] * 3,
                "ead_final": [_EAD] * 3,
                "ead_gross": [_EAD] * 3,
                "provision_deducted": [0.0] * 3,
                "provision_specific_allocated": [0.0] * 3,
                "cqs": pl.Series([None] * 3, dtype=pl.Int8),
                "cp_is_investment_grade": [True] * 3,
                "seniority": ["senior", "subordinated", "senior"],
                "is_defaulted": [False, False, True],
            }
        )

        # Act
        result = SACalculator().calculate_unified(frame, config).collect()
        legs = {
            row["exposure_reference"]: (row["risk_weight"], row["sa_investment_grade_assessed"])
            for row in result.iter_rows(named=True)
        }

        # Assert
        assert legs == {
            "IG": (pytest.approx(0.65), True),
            "SUB_IG": (pytest.approx(1.50), None),
            "DEF_IG": (pytest.approx(1.50), None),
        }


class TestInvestmentGradeElectionConfig:
    """The two elections and the deprecated alias resolve on ``CalculationConfig``.

    The fields hold what the caller stated (``None`` = not stated); the
    ``resolved_*`` properties are what the engine reads. Keeping "not stated"
    unresolved is what lets ``dataclasses.replace`` of the alias still reach them.
    """

    def test_factory_sets_each_election_independently(self) -> None:
        """basel_3_1() carries the permission and the election as given."""
        # Arrange / Act
        config = _b31_elections(permission=False, election=True)

        # Assert
        assert (
            config.resolved_sa_investment_grade_permission,
            config.resolved_output_floor_investment_grade_election,
        ) == (False, True)

    def test_defaults_hold_neither_election(self) -> None:
        """Both resolve False: Art. 122(5) 100% on SA rows, Art. 122(8)(a) in S-TREA."""
        # Arrange / Act
        b31 = CalculationConfig.basel_3_1(reporting_date=date(2032, 1, 1))
        crr = CalculationConfig.crr(reporting_date=date(2024, 12, 31))

        # Assert
        assert (
            b31.resolved_sa_investment_grade_permission,
            b31.resolved_output_floor_investment_grade_election,
            crr.resolved_sa_investment_grade_permission,
            crr.resolved_output_floor_investment_grade_election,
        ) == (False, False, False, False)

    def test_unstated_elections_stay_unstated(self) -> None:
        """An election the caller did not state is stored as ``None``, not resolved."""
        # Arrange / Act
        config = CalculationConfig.basel_3_1(reporting_date=date(2032, 1, 1))

        # Assert
        assert (
            config.sa_investment_grade_permission,
            config.output_floor_investment_grade_election,
        ) == (None, None)

    def test_alias_sets_both_and_warns(self) -> None:
        """use_investment_grade_assessment=True resolves to both, with a DeprecationWarning."""
        # Arrange / Act
        with pytest.warns(DeprecationWarning, match="use_investment_grade_assessment"):
            config = CalculationConfig.basel_3_1(
                reporting_date=date(2032, 1, 1), use_investment_grade_assessment=True
            )

        # Assert
        assert (
            config.resolved_sa_investment_grade_permission,
            config.resolved_output_floor_investment_grade_election,
        ) == (True, True)

    def test_explicit_election_overrides_the_alias(self) -> None:
        """An election stated explicitly wins over the alias; the alias fills the other."""
        # Arrange / Act
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            config = CalculationConfig.basel_3_1(
                reporting_date=date(2032, 1, 1),
                use_investment_grade_assessment=True,
                output_floor_investment_grade_election=False,
            )

        # Assert
        assert (
            config.resolved_sa_investment_grade_permission,
            config.resolved_output_floor_investment_grade_election,
        ) == (True, False)

    @pytest.mark.parametrize(
        ("base_alias", "replaced_alias", "expected"),
        [
            pytest.param(False, True, (True, True), id="on"),
            pytest.param(True, False, (False, False), id="off"),
        ],
    )
    def test_replace_of_the_alias_resolves_both_ways(
        self, base_alias: bool, replaced_alias: bool, expected: tuple[bool, bool]
    ) -> None:
        """Unstated elections stay unstated through ``replace``, so the alias reaches them."""
        # Arrange
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            base = CalculationConfig.basel_3_1(
                reporting_date=date(2032, 1, 1), use_investment_grade_assessment=base_alias
            )

            # Act
            config = replace(base, use_investment_grade_assessment=replaced_alias)

        # Assert
        assert (
            config.resolved_sa_investment_grade_permission,
            config.resolved_output_floor_investment_grade_election,
        ) == expected

    def test_replace_of_one_election_keeps_the_other_on_the_alias(self) -> None:
        """Replacing one election leaves the unstated one resolved from the alias."""
        # Arrange
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            base = CalculationConfig.basel_3_1(
                reporting_date=date(2032, 1, 1), use_investment_grade_assessment=True
            )

            # Act
            config = replace(base, sa_investment_grade_permission=False)

        # Assert
        assert (
            config.resolved_sa_investment_grade_permission,
            config.resolved_output_floor_investment_grade_election,
        ) == (False, True)


class TestDeprecatedAliasWarning:
    """The DeprecationWarning points at the caller's line and says what the alias did.

    ``pytest.warns`` only sees that a warning fired. These tests read where it was
    attributed: Python's default filters show a ``DeprecationWarning`` only when it
    is attributed to ``__main__``, so one attributed to a line inside
    ``contracts/config.py`` never reaches a script that uses the alias.
    """

    @staticmethod
    def _record(build: Callable[[], object]) -> list[warnings.WarningMessage]:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            build()
        return [w for w in caught if issubclass(w.category, DeprecationWarning)]

    @pytest.mark.parametrize("path", ["factory", "direct", "replace"])
    def test_warning_is_attributed_to_the_caller(self, path: str) -> None:
        """From the factory, direct construction and ``dataclasses.replace`` alike."""
        # Arrange
        base = CalculationConfig.basel_3_1(reporting_date=date(2032, 1, 1))
        builds: dict[str, Callable[[], object]] = {
            "factory": lambda: CalculationConfig.basel_3_1(
                reporting_date=date(2032, 1, 1), use_investment_grade_assessment=True
            ),
            "direct": lambda: CalculationConfig(
                reporting_date=date(2032, 1, 1),
                regime_id="b31",
                use_investment_grade_assessment=True,
            ),
            "replace": lambda: replace(base, use_investment_grade_assessment=True),
        }

        # Act
        caught = self._record(builds[path])

        # Assert
        assert [w.filename for w in caught] == [__file__]

    def test_warning_names_only_the_election_the_alias_set(self) -> None:
        """With the permission stated, the alias sets only the floor election — and says so."""
        # Arrange / Act
        caught = self._record(
            lambda: CalculationConfig.basel_3_1(
                reporting_date=date(2032, 1, 1),
                use_investment_grade_assessment=True,
                sa_investment_grade_permission=False,
            )
        )

        # Assert
        message = str(caught[0].message)
        assert "sets output_floor_investment_grade_election to True" in message
        assert "sa_investment_grade_permission to True" not in message

    def test_warning_says_the_alias_had_no_effect_when_both_are_stated(self) -> None:
        """With both elections stated, the alias sets neither — and says so."""
        # Arrange / Act
        caught = self._record(
            lambda: CalculationConfig.basel_3_1(
                reporting_date=date(2032, 1, 1),
                use_investment_grade_assessment=True,
                sa_investment_grade_permission=False,
                output_floor_investment_grade_election=False,
            )
        )

        # Assert
        assert "has no effect" in str(caught[0].message)


# --- SA Calculator: sa_rwa reflects IG flag ---


class TestSACalculatorIGForFloor:
    """SA calculator unified path produces sa_rwa reflecting the Art. 122(8) choice.

    Why: The unified path computes SA-equivalent RWA for ALL exposures,
    including IRB exposures. The sa_rwa column feeds directly into S-TREA, so
    the Art. 122(8)(b) election must flow through to sa_rwa on F-IRB rows.
    ``_b31_config(use_ig=...)`` sets both elections together; their
    independence is pinned by ``TestInvestmentGradeElectionsAreIndependent``.
    """

    @pytest.fixture
    def sa_calculator(self) -> SACalculator:
        return SACalculator()

    def _unrated_corporate_frame(
        self,
        *,
        is_ig: bool = False,
        approach: str = "standardised",
        ead: float = 1_000_000.0,
    ) -> pl.LazyFrame:
        """Build a minimal unrated corporate frame for unified path."""
        return pl.LazyFrame(
            {
                "exposure_reference": ["CORP1"],
                "exposure_class": ["CORPORATE"],
                "approach": [approach],
                "ead_final": [ead],
                "cqs": [None],
                "cp_is_investment_grade": [is_ig],
            }
        )

    def test_sa_rwa_100pct_without_ig_flag(
        self,
        sa_calculator: SACalculator,
    ) -> None:
        """Default (no IG election): unrated corporate sa_rwa = EAD × 100%."""
        config = _b31_config(use_ig=False)
        frame = self._unrated_corporate_frame(approach=ApproachType.FIRB.value)
        result = sa_calculator.calculate_unified(frame, config).collect()
        assert float(result["sa_rwa"][0]) == pytest.approx(1_000_000.0)

    def test_sa_rwa_65pct_with_ig_flag(
        self,
        sa_calculator: SACalculator,
    ) -> None:
        """IG election + IG counterparty: unrated corporate sa_rwa = EAD × 65%."""
        config = _b31_config(use_ig=True)
        frame = self._unrated_corporate_frame(approach=ApproachType.FIRB.value, is_ig=True)
        result = sa_calculator.calculate_unified(frame, config).collect()
        assert float(result["sa_rwa"][0]) == pytest.approx(650_000.0)

    def test_sa_rwa_135pct_non_ig(
        self,
        sa_calculator: SACalculator,
    ) -> None:
        """IG election + non-IG counterparty: sa_rwa = EAD × 135%."""
        config = _b31_config(use_ig=True)
        frame = self._unrated_corporate_frame(approach=ApproachType.FIRB.value, is_ig=False)
        result = sa_calculator.calculate_unified(frame, config).collect()
        assert float(result["sa_rwa"][0]) == pytest.approx(1_350_000.0)

    def test_rated_corporate_unaffected_by_ig_flag(
        self,
        sa_calculator: SACalculator,
    ) -> None:
        """Rated corporates (CQS present) use CQS table regardless of IG flag."""
        config = _b31_config(use_ig=True)
        frame = pl.LazyFrame(
            {
                "exposure_reference": ["CORP_RATED"],
                "exposure_class": ["CORPORATE"],
                "approach": [ApproachType.FIRB.value],
                "ead_final": [1_000_000.0],
                "cqs": [3],
                "cp_is_investment_grade": [True],
            }
        )
        result = sa_calculator.calculate_unified(frame, config).collect()
        # CQS 3 corporate → 75% (B31 Table 6) regardless of IG flag
        assert float(result["sa_rwa"][0]) == pytest.approx(750_000.0)

    def test_sme_unaffected_by_ig_flag(
        self,
        sa_calculator: SACalculator,
    ) -> None:
        """Corporate SME exposures get 85% regardless of IG flag (SME gate in when-chain)."""
        config = _b31_config(use_ig=True)
        frame = pl.LazyFrame(
            {
                "exposure_reference": ["CORP_SME"],
                "exposure_class": ["CORPORATE_SME"],
                "approach": [ApproachType.FIRB.value],
                "ead_final": [500_000.0],
                "cqs": [None],
                "cp_is_investment_grade": [True],
            }
        )
        result = sa_calculator.calculate_unified(frame, config).collect()
        # Corporate SME → 85% always (Art. 122A), not affected by IG
        assert float(result["sa_rwa"][0]) == pytest.approx(425_000.0)

    def test_institution_unaffected_by_ig_flag(
        self,
        sa_calculator: SACalculator,
    ) -> None:
        """Institution exposures use SCRA/ECRA regardless of IG flag."""
        config = _b31_config(use_ig=True)
        frame = pl.LazyFrame(
            {
                "exposure_reference": ["INST1"],
                "exposure_class": ["INSTITUTION"],
                "approach": [ApproachType.FIRB.value],
                "ead_final": [1_000_000.0],
                "cqs": [None],
                "cp_is_investment_grade": [False],
                "cp_scra_grade": ["B"],
            }
        )
        result = sa_calculator.calculate_unified(frame, config).collect()
        # SCRA grade B → 75%, not affected by corporate IG assessment
        assert float(result["sa_rwa"][0]) == pytest.approx(750_000.0)


# --- Aggregator: S-TREA changes with IG flag ---


class TestOutputFloorSTeaIG:
    """Output floor arithmetic on an S-TREA the Art. 122(8) choice has already set.

    Why: S-TREA = sum(sa_rwa) for floor-eligible exposures. The aggregator
    never reads either election: these frames PRE-BAKE ``sa_rwa`` at the value
    each branch of Art. 122(8) produces and pin the floor arithmetic on it.
    That the election actually produces those values is pinned upstream, on the
    SA calculator, by ``TestInvestmentGradeElectionsAreIndependent``.
    """

    @pytest.fixture
    def aggregator(self) -> OutputAggregator:
        return OutputAggregator()

    def test_s_trea_100pct_without_ig(self, aggregator: OutputAggregator) -> None:
        """Without IG election: S-TREA = EAD × 100% for unrated corporate."""
        config = _b31_config(use_ig=False)
        # sa_rwa = 1M (100% of EAD) — simulating no IG assessment
        irb = _irb_corporate_frame(ead=1_000_000, rwa=500_000, sa_rwa=1_000_000)
        result = aggregator.aggregate(EMPTY_SA, irb, EMPTY_SLOTTING, None, config)
        summary = result.output_floor_summary
        assert summary is not None
        assert summary.s_trea == pytest.approx(1_000_000.0)

    def test_s_trea_65pct_with_ig(self, aggregator: OutputAggregator) -> None:
        """With IG election: S-TREA = EAD × 65% for IG corporate."""
        config = _b31_config(use_ig=True)
        # sa_rwa = 650k (65% of EAD) — simulating IG assessment
        irb = _irb_corporate_frame(ead=1_000_000, rwa=500_000, sa_rwa=650_000)
        result = aggregator.aggregate(EMPTY_SA, irb, EMPTY_SLOTTING, None, config)
        summary = result.output_floor_summary
        assert summary is not None
        assert summary.s_trea == pytest.approx(650_000.0)

    def test_s_trea_135pct_non_ig(self, aggregator: OutputAggregator) -> None:
        """With IG election: S-TREA = EAD × 135% for non-IG corporate."""
        config = _b31_config(use_ig=True)
        # sa_rwa = 1.35M (135% of EAD) — simulating non-IG assessment
        irb = _irb_corporate_frame(ead=1_000_000, rwa=500_000, sa_rwa=1_350_000)
        result = aggregator.aggregate(EMPTY_SA, irb, EMPTY_SLOTTING, None, config)
        summary = result.output_floor_summary
        assert summary is not None
        assert summary.s_trea == pytest.approx(1_350_000.0)

    def test_ig_reduces_floor_threshold(self, aggregator: OutputAggregator) -> None:
        """IG assessment reduces floor threshold: 72.5% × 650k < 72.5% × 1M.

        Why: The floor threshold = floor_pct × S-TREA. When IG assessment
        reduces S-TREA (65% vs 100%), the floor threshold drops proportionally.
        """
        config = _b31_config(use_ig=True)
        # IG corporate: sa_rwa = 650k
        irb = _irb_corporate_frame(ead=1_000_000, rwa=500_000, sa_rwa=650_000)
        result = aggregator.aggregate(EMPTY_SA, irb, EMPTY_SLOTTING, None, config)
        summary = result.output_floor_summary
        assert summary is not None
        # Floor threshold = 72.5% × 650k = 471,250
        assert summary.floor_threshold == pytest.approx(471_250.0)

    def test_ig_changes_floor_binding(self, aggregator: OutputAggregator) -> None:
        """IG assessment can flip floor from binding to non-binding.

        Why: With IRB RWA = 500k:
        - Without IG: floor = 72.5% × 1M = 725k > 500k → binds
        - With IG: floor = 72.5% × 650k = 471.25k < 500k → does NOT bind
        This demonstrates the material capital impact of Art. 122(8).
        """
        # Without IG: floor binds (725k > 500k)
        config_no_ig = _b31_config(use_ig=False)
        irb_no_ig = _irb_corporate_frame(ead=1_000_000, rwa=500_000, sa_rwa=1_000_000)
        result_no_ig = aggregator.aggregate(EMPTY_SA, irb_no_ig, EMPTY_SLOTTING, None, config_no_ig)
        assert result_no_ig.output_floor_summary is not None
        assert result_no_ig.output_floor_summary.portfolio_floor_binding is True
        assert result_no_ig.output_floor_summary.shortfall == pytest.approx(225_000.0)

        # With IG: floor does NOT bind (471.25k < 500k)
        config_ig = _b31_config(use_ig=True)
        irb_ig = _irb_corporate_frame(ead=1_000_000, rwa=500_000, sa_rwa=650_000)
        result_ig = aggregator.aggregate(EMPTY_SA, irb_ig, EMPTY_SLOTTING, None, config_ig)
        assert result_ig.output_floor_summary is not None
        assert result_ig.output_floor_summary.portfolio_floor_binding is False
        assert result_ig.output_floor_summary.shortfall == pytest.approx(0.0)

    def test_non_ig_increases_floor_threshold(self, aggregator: OutputAggregator) -> None:
        """Non-IG 135% increases floor threshold vs default 100%.

        Why: Non-IG corporates INCREASE S-TREA and make the floor more likely
        to bind. This is the capital penalty for choosing IG assessment without
        actually having IG counterparties.
        """
        config = _b31_config(use_ig=True)
        # Non-IG corporate: sa_rwa = 1.35M
        irb = _irb_corporate_frame(ead=1_000_000, rwa=500_000, sa_rwa=1_350_000)
        result = aggregator.aggregate(EMPTY_SA, irb, EMPTY_SLOTTING, None, config)
        summary = result.output_floor_summary
        assert summary is not None
        # Floor threshold = 72.5% × 1.35M = 978,750
        assert summary.floor_threshold == pytest.approx(978_750.0)
        assert summary.shortfall == pytest.approx(478_750.0)

    def test_mixed_ig_and_non_ig(self, aggregator: OutputAggregator) -> None:
        """Mixed portfolio: IG and non-IG corporates affect S-TREA additively.

        Why: In practice, IRB institutions will have a mix of IG and non-IG
        corporate counterparties. S-TREA is the sum of all sa_rwa values.
        """
        config = _b31_config(use_ig=True)
        irb = pad_irb_branch(
            pl.LazyFrame(
                {
                    "exposure_reference": ["IG_CORP", "NON_IG_CORP"],
                    "exposure_class": ["CORPORATE", "CORPORATE"],
                    "approach_applied": ["FIRB", "FIRB"],
                    "ead_final": [1_000_000.0, 1_000_000.0],
                    "risk_weight": [0.5, 0.5],
                    "rwa_final": [500_000.0, 500_000.0],
                    "sa_rwa": [650_000.0, 1_350_000.0],  # IG=65%, non-IG=135%
                }
            )
        )
        result = aggregator.aggregate(EMPTY_SA, irb, EMPTY_SLOTTING, None, config)
        summary = result.output_floor_summary
        assert summary is not None
        # S-TREA = 650k + 1.35M = 2M (average 100%, same as no-IG in aggregate)
        assert summary.s_trea == pytest.approx(2_000_000.0)
        assert summary.u_trea == pytest.approx(1_000_000.0)

    def test_rwa_post_floor_with_ig(self, aggregator: OutputAggregator) -> None:
        """Post-floor RWA reflects the IG-adjusted S-TREA.

        Why: When the floor does not bind (IG assessment reduces S-TREA below
        U-TREA), the final RWA equals the pre-floor IRB RWA — no add-on.
        """
        config = _b31_config(use_ig=True)
        irb = _irb_corporate_frame(ead=1_000_000, rwa=500_000, sa_rwa=650_000)
        result = aggregator.aggregate(EMPTY_SA, irb, EMPTY_SLOTTING, None, config)
        df = result.results.collect()
        # Floor does not bind → rwa_final = pre-floor IRB RWA
        assert float(df["rwa_final"][0]) == pytest.approx(500_000.0)

    def test_rwa_post_floor_without_ig(self, aggregator: OutputAggregator) -> None:
        """Without IG: floor binds and increases RWA.

        Why: When floor binds, rwa_final = pre-floor + shortfall.
        """
        config = _b31_config(use_ig=False)
        irb = _irb_corporate_frame(ead=1_000_000, rwa=500_000, sa_rwa=1_000_000)
        result = aggregator.aggregate(EMPTY_SA, irb, EMPTY_SLOTTING, None, config)
        df = result.results.collect()
        # Floor binds: rwa_final = 500k + 225k shortfall = 725k
        assert float(df["rwa_final"][0]) == pytest.approx(725_000.0)

    def test_config_flag_propagates_to_factory(self) -> None:
        """CalculationConfig.basel_3_1() still accepts the deprecated alias.

        Why: existing callers pass ``use_investment_grade_assessment``; it must
        keep resolving to both elections so their numbers do not move.
        """
        config_no_ig = CalculationConfig.basel_3_1(
            reporting_date=date(2032, 1, 1),
            use_investment_grade_assessment=False,
        )
        assert config_no_ig.use_investment_grade_assessment is False

        with pytest.warns(DeprecationWarning):
            config_ig = CalculationConfig.basel_3_1(
                reporting_date=date(2032, 1, 1),
                use_investment_grade_assessment=True,
            )
        assert config_ig.use_investment_grade_assessment is True

    def test_crr_ig_flag_locked_false(self) -> None:
        """CRR configs hold neither investment-grade election.

        Why: CRR Art. 122 has no investment-grade approach and no output
        floor. The CRR factory takes none of the three keywords.
        """
        config = CalculationConfig.crr(reporting_date=date(2024, 12, 31))
        assert config.use_investment_grade_assessment is False
        assert config.resolved_sa_investment_grade_permission is False
        assert config.resolved_output_floor_investment_grade_election is False
