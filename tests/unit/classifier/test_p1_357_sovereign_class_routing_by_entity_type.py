"""
Unit pins — P1.357: the sovereign-class approach gate keys on entity type alone.

Pipeline position:
    HierarchyResolver -> ExposureClassifier (approach.assign_approach)
        -> CRMProcessor

Key assertion:
    PS1/26 Art. 147A(1)(a) (ps126app1.pdf p.92, verbatim): "An institution shall
    ... use the following specified approaches: (a) for point (a) of Article
    147(2) (central governments, central banks or quasi-sovereigns), the
    Standardised Approach". PS1/26 Art. 147(3) assigns central governments,
    central banks, regional governments, local authorities, public sector
    entities and multilateral development banks to that class with no
    condition. The rule has no currency, country, funding or permission limb.

    The classifier implements it in ``_apply_b31_approach_restrictions`` by
    stripping both IRB approaches from every ``cp_entity_type`` in
    ``B31_SOVEREIGN_LIKE_ENTITY_TYPES``. P1.357 deleted a second, narrower
    gate — ``is_eu_domestic_sovereign`` — that forced SA only for a
    central-government-class row denominated in its domestic currency. It was
    dead in both regimes: ANDed with a pack Feature that is False under CRR,
    and a strict subset of the entity-type gate under Basel 3.1. So these tests
    are green on both sides of P1.357, deliberately: they pin the outcome the
    deleted branch was credited with, and they turn red if the entity-type gate
    is ever narrowed (Basel 3.1) or if a currency-keyed forced-SA override is
    ever re-attached without the regime gate (CRR).

    Under CRR the approach is NOT forced: CRR Art. 114(4)/(7) set an SA risk
    weight only, and Art. 150(1) permanent partial use is an election ("may
    apply the Standardised Approach"), so a firm holding a central-government
    IRB permission routes a domestic-currency sovereign to IRB.

Fixture adequacy (asserted at the top of each test, because a sweep that never
reaches IRB, or never holds a domestic-currency row, proves nothing):
    - full IRB model permissions for every exposure class, plus an internal PD
      and a modelled LGD on every row, so a corporate row does reach A-IRB;
    - ``original_currency`` populated as the FX converter populates it in
      production, so the domestic-currency shapes are domestic on the carrier
      the deleted branch read.

References:
    - PRA PS1/26 Art. 147A(1)(a), Art. 147(2)(a), Art. 147(3)(a)-(f)
    - CRR Art. 114(4)/(7) (SA risk weight), CRR Art. 150(1) (PPU election)
    - src/rwa_calc/engine/classify/approach.py::_apply_b31_approach_restrictions
    - src/rwa_calc/data/schemas.py::B31_SOVEREIGN_LIKE_ENTITY_TYPES
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType, ExposureClass, PermissionMode
from rwa_calc.engine.classify import ExposureClassifier
from rwa_calc.engine.entity_class_maps import entity_type_to_sa_class
from rwa_calc.rulebook import RulepackV0
from tests.fixtures.resolved_bundle import make_counterparty_lookup, make_resolved_bundle

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CRR_DATE = date(2026, 6, 30)
_B31_DATE = date(2027, 6, 30)
_MODEL_ID = "P1357-MODEL"

# (country, denomination) shapes. Domestic: the currency is the counterparty
# country's own (GB/GBP is the CRR Art. 114(4) case, DE/EUR and PL/PLN the
# Art. 114(7) EU case, US/USD a third-country sovereign in its own currency).
# Foreign: the same countries in a currency that is not their own (EUR is not
# Poland's domestic currency). The third-country shapes catch a narrowing keyed
# on non-EU / non-UK sovereigns, which the EU and UK shapes alone would miss.
_DOMESTIC_SHAPES: tuple[tuple[str, str], ...] = (
    ("GB", "GBP"),
    ("DE", "EUR"),
    ("PL", "PLN"),
    ("US", "USD"),
)
_FOREIGN_SHAPES: tuple[tuple[str, str], ...] = (("DE", "USD"), ("PL", "EUR"), ("US", "EUR"))
_ALL_SHAPES = _DOMESTIC_SHAPES + _FOREIGN_SHAPES

_CGCB = ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value

# The SA classes of PS1/26 Art. 147(3)(a)-(f): every entity type mapped to one
# of these sits in the Art. 147(2)(a) class unconditionally. International
# organisations are left out on purpose — Art. 147(3)(g) takes in only those
# with a 0% Art. 118 risk weight, so the class is conditional there.
_ART_147_3_A_TO_F_SA_CLASSES: frozenset[str] = frozenset(
    {
        _CGCB,
        ExposureClass.RGLA.value,
        ExposureClass.PSE.value,
        ExposureClass.MDB.value,
    }
)

_IRB_APPROACHES: frozenset[str] = frozenset({ApproachType.AIRB.value, ApproachType.FIRB.value})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def classifier() -> ExposureClassifier:
    return ExposureClassifier()


def _config(regime: str) -> CalculationConfig:
    """The regime's config, with IRB permissions resolved from model_permissions."""
    if regime == "b31":
        return CalculationConfig.basel_3_1(
            reporting_date=_B31_DATE, permission_mode=PermissionMode.IRB
        )
    return CalculationConfig.crr(reporting_date=_CRR_DATE, permission_mode=PermissionMode.IRB)


def _sa_map(config: CalculationConfig) -> dict[str, str]:
    """The regime's entity_type -> SA exposure class map, read from its rulepack."""
    return entity_type_to_sa_class(RulepackV0.from_config(config).pack)


def _sweep_bundle(entity_types: list[str]) -> object:
    """One IRB-eligible loan per (entity type, currency shape).

    Every row carries an internal PD, a modelled LGD and a model id that the
    attached permission table grants A-IRB, F-IRB and slotting for every
    exposure class — so nothing but an approach restriction keeps a row on SA.
    """
    cp_refs: list[str] = []
    cp_types: list[str] = []
    cp_countries: list[str] = []
    exp_refs: list[str] = []
    currencies: list[str] = []
    for entity_type in entity_types:
        for country, currency in _ALL_SHAPES:
            ref = f"{entity_type}|{country}|{currency}"
            cp_refs.append(f"CP-{ref}")
            cp_types.append(entity_type)
            cp_countries.append(country)
            exp_refs.append(ref)
            currencies.append(currency)

    n = len(exp_refs)
    exposures = pl.LazyFrame(
        {
            "exposure_reference": exp_refs,
            "counterparty_reference": cp_refs,
            "exposure_type": ["loan"] * n,
            "product_type": ["TERM_LOAN"] * n,
            "book_code": ["BANKING"] * n,
            "currency": currencies,
            # The FX converter keeps the pre-conversion denomination here; the
            # deleted branch read this carrier, so it is populated as in
            # production rather than left as the seal's typed null.
            "original_currency": currencies,
            "drawn_amount": [1_000_000.0] * n,
            "nominal_amount": [0.0] * n,
            "internal_pd": [0.01] * n,
            "lgd": [0.45] * n,
            "model_id": [_MODEL_ID] * n,
        }
    )
    counterparties = pl.LazyFrame(
        {
            "counterparty_reference": cp_refs,
            "counterparty_name": cp_refs,
            "entity_type": cp_types,
            "country_code": cp_countries,
        }
    )
    permissions = pl.LazyFrame(
        [
            {"model_id": _MODEL_ID, "exposure_class": ec.value, "approach": approach}
            for ec in ExposureClass
            for approach in (
                ApproachType.AIRB.value,
                ApproachType.FIRB.value,
                ApproachType.SLOTTING.value,
            )
        ]
    )
    return make_resolved_bundle(
        exposures=exposures,
        counterparty_lookup=make_counterparty_lookup(counterparties=counterparties),
        lending_group_totals=pl.LazyFrame(
            schema={"lending_group_reference": pl.String, "total_exposure": pl.Float64}
        ),
        hierarchy_errors=[],
        model_permissions=permissions,
    )


def _classify(
    classifier: ExposureClassifier, config: CalculationConfig, entity_types: list[str]
) -> pl.DataFrame:
    """Classify the sweep and return one row per exposure, with its shape split out."""
    result = classifier.classify(_sweep_bundle(entity_types), config)  # type: ignore[arg-type]
    return (
        result.all_exposures.select(
            "exposure_reference",
            "cp_entity_type",
            "exposure_class_sa",
            "exposure_class",
            "approach",
        )
        .collect()
        .with_columns(
            pl.col("exposure_reference")
            .str.split("|")
            .list.slice(1, 2)
            .list.join("/")
            .alias("shape")
        )
    )


def _shape_label(shapes: tuple[tuple[str, str], ...]) -> set[str]:
    return {f"{country}/{currency}" for country, currency in shapes}


# ---------------------------------------------------------------------------
# Central-government class: both regimes
# ---------------------------------------------------------------------------


class TestCentralGovernmentClassRoutingIgnoresCurrency:
    """A CGCB-class row's approach does not depend on its denomination currency."""

    @pytest.mark.parametrize(
        ("regime", "expected_approach"),
        [
            pytest.param("b31", ApproachType.SA.value, id="b31-art147A1a-sa-only"),
            pytest.param("crr", ApproachType.AIRB.value, id="crr-art150-ppu-election"),
        ],
    )
    def test_cgcb_class_routing_is_the_same_in_domestic_and_foreign_currency(
        self, classifier: ExposureClassifier, regime: str, expected_approach: str
    ) -> None:
        """Every CGCB-mapped entity type routes the same way in every currency.

        Arrange: one IRB-eligible loan per (CGCB-mapped entity type, currency
                 shape) — domestic GB/GBP, DE/EUR, PL/PLN, US/USD and foreign
                 DE/USD, PL/EUR, US/EUR — with full IRB model permissions.
        Act:     ExposureClassifier.classify.
        Assert:  Basel 3.1 — every row is SA (PS1/26 Art. 147A(1)(a), no
                 currency limb). CRR — every row is A-IRB: Art. 114(4)/(7)
                 sets an SA risk weight only and Art. 150(1) PPU is an
                 election, so the permission decides.

        Can fail in each regime separately: Basel 3.1 goes red if the
        entity-type gate (``B31_SOVEREIGN_LIKE_ENTITY_TYPES``) stops covering a
        CGCB-mapped type; CRR goes red if a currency-keyed forced-SA override is
        attached without the regime gate (the P1.192 defect).
        """
        # Arrange
        config = _config(regime)
        cgcb_types = sorted(t for t, cls in _sa_map(config).items() if cls == _CGCB)
        assert cgcb_types, "the SA map sends no entity type to CGCB - nothing to test"

        # Act
        df = _classify(classifier, config, cgcb_types)

        # Assert — adequacy first: every CGCB type in every shape reached the ladder.
        assert set(df["exposure_class_sa"].unique()) == {_CGCB}, (
            "a CGCB-mapped entity type left the CGCB SA class before the ladder - "
            "the sweep no longer exercises the central-government gate"
        )
        assert set(df["shape"].unique()) == _shape_label(_ALL_SHAPES)
        assert df.height == len(cgcb_types) * len(_ALL_SHAPES)

        wrong = df.filter(pl.col("approach") != expected_approach)
        assert wrong.is_empty(), (
            f"{regime}: every CGCB-class row must route to {expected_approach!r} "
            f"whatever its currency; got\n{wrong}"
        )


# ---------------------------------------------------------------------------
# Whole Art. 147(2)(a) class: Basel 3.1 only
# ---------------------------------------------------------------------------


class TestB31SovereignClassIsStandardisedOnly:
    """PS1/26 Art. 147A(1)(a): no Art. 147(3)(a)-(f) row exits the classifier on IRB."""

    def test_b31_no_sovereign_class_row_routes_to_irb_whatever_the_currency(
        self, classifier: ExposureClassifier
    ) -> None:
        """Sweep every entity type; none of the Art. 147(3)(a)-(f) rows is IRB.

        Arrange: one IRB-eligible loan per (entity type in the SA map, currency
                 shape), full IRB model permissions, Basel 3.1.
        Act:     ExposureClassifier.classify.
        Assert:  every row whose SA class is CGCB / RGLA / PSE / MDB — read
                 both from the pack map (input side) and from
                 ``exposure_class_sa`` (output side, so a new classify path
                 that emits one of these classes for another entity type is
                 caught too) — has approach SA.

        Red under a narrowed ``B31_SOVEREIGN_LIKE_ENTITY_TYPES`` (measured: an
        emptied tuple sends these rows to advanced_irb).
        """
        # Arrange
        config = _config("b31")
        sa_map = _sa_map(config)
        family_types = {t for t, cls in sa_map.items() if cls in _ART_147_3_A_TO_F_SA_CLASSES}

        # Act
        df = _classify(classifier, config, sorted(sa_map))

        # Assert — adequacy: permissions are live (something reaches IRB), and the
        # sovereign-class population holds every family type in both currency kinds.
        assert not df.filter(pl.col("approach").is_in(list(_IRB_APPROACHES))).is_empty(), (
            "no row reached IRB - the permissions are not live and an SA-only "
            "outcome below would prove nothing"
        )
        in_family = pl.col("cp_entity_type").is_in(list(family_types)) | pl.col(
            "exposure_class_sa"
        ).is_in(list(_ART_147_3_A_TO_F_SA_CLASSES))
        family = df.filter(in_family)
        assert set(family["cp_entity_type"].unique()) >= family_types
        assert set(family["shape"].unique()) >= _shape_label(_DOMESTIC_SHAPES)
        assert set(family["shape"].unique()) >= _shape_label(_FOREIGN_SHAPES)

        escaped = family.filter(pl.col("approach") != ApproachType.SA.value)
        assert escaped.is_empty(), (
            "PS1/26 Art. 147A(1)(a): central governments, central banks and the "
            "Art. 147(3)(c)-(f) quasi-sovereigns are Standardised-Approach only, in "
            f"any currency. These rows escaped to another approach:\n{escaped}"
        )
