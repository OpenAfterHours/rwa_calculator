"""
Unit pins — P1.276: CRR assigns non-named MDBs to the INSTITUTIONS IRB class.

Pipeline position:
    HierarchyResolver -> ExposureClassifier (attributes.derive_independent_flags)
        -> approach selection / model-permission matching

Key assertion:
    CRR Art. 147(3) (crr.pdf p.141, verbatim): "The following exposures shall be
    assigned to the class laid down in point (a) of paragraph 2: ... (b) exposures
    to multilateral development banks referred to in **Article 117(2)**".
    CRR Art. 147(4): "The following exposures shall be assigned to the class laid
    down in point (b) of paragraph 2 [institutions]: ... (c) exposures to
    multilateral development banks which are **not** assigned a 0 % risk weight
    under Article 117".

    So under CRR only the Art. 117(2) named MDBs (``mdb_named``) join the
    central-government IRB class; the generic, CQS-rated ``mdb`` belongs to the
    institutions class.

    PS1/26 Art. 147(3) (ps126app1.pdf p.89, verbatim) drops that split: "(f)
    multilateral development banks" is listed unconditionally among the entities
    assigned to the central-government class — the 0%-risk-weight qualifier binds
    only the "(g) international organisations" limb — and PS1/26 Art. 147(4) has
    no MDB limb at all. The reroute is therefore CRR-ONLY, gated on the cited
    ``crr_non_named_mdb_institution_irb_class`` pack Feature, and the B31 arms
    below are the regression guard for that.

Scope (what this change does and does not touch):
    - ``exposure_class_irb`` is the ONLY class column that moves. The SA columns
      (``exposure_class_sa`` / ``exposure_class``) keep MDB, so SA risk weights,
      ``exposure_class_applied`` and every COREP / Pillar 3 class row are
      untouched (they read the SA-side class, never ``exposure_class_irb``).
    - The behavioural consequence is IRB model-permission matching, which keys on
      ``exposure_class_irb`` (``stages/classify/permissions.py``): under CRR a
      non-named MDB now needs an INSTITUTION-class IRB permission, not a
      central-government one. That is the Art. 147(4)(c) outcome.
    - Capital is unmoved by the class itself: the IRB correlation parameters are
      identical across MDB / INSTITUTION / CGCB, and the CRR institution PD floor
      equals the corporate default floor an MDB-classed row would otherwise take.

References:
    - CRR Art. 147(3)(b), 147(4)(c); PRA PS1/26 Art. 147(3)(f)
    - CRR Art. 117(2): the named 0%-risk-weight MDB list
    - src/rwa_calc/engine/stages/classify/attributes.py::derive_independent_flags
    - src/rwa_calc/rulebook/packs/{crr,b31}.py:
      ``crr_non_named_mdb_institution_irb_class``
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import ApproachType, ExposureClass
from rwa_calc.engine.classifier import ExposureClassifier
from rwa_calc.engine.irb.formulas import get_correlation_params
from rwa_calc.rulebook import RulepackV0
from tests.fixtures.resolved_bundle import make_counterparty_lookup, make_resolved_bundle

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CRR_DATE = date(2026, 6, 30)
_B31_DATE = date(2027, 6, 30)

MDB_REF = "P1276-MDB"
MDB_NAMED_REF = "P1276-MDB-NAMED"

_CGCB = ExposureClass.CENTRAL_GOVT_CENTRAL_BANK.value
_INSTITUTION = ExposureClass.INSTITUTION.value
_MDB = ExposureClass.MDB.value


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def classifier() -> ExposureClassifier:
    return ExposureClassifier()


@pytest.fixture
def crr_config() -> CalculationConfig:
    return CalculationConfig.crr(reporting_date=_CRR_DATE)


@pytest.fixture
def b31_config() -> CalculationConfig:
    return CalculationConfig.basel_3_1(reporting_date=_B31_DATE)


def _bundle(
    *,
    model_id: str | None = None,
    permission_class: str | None = None,
) -> object:
    """Two loans: one to a generic MDB, one to an Art. 117(2) named MDB.

    When ``model_id`` and ``permission_class`` are supplied, a single F-IRB
    model-permission row is attached so the approach ladder can be observed.
    """
    exposures = pl.LazyFrame(
        {
            "exposure_reference": [MDB_REF, MDB_NAMED_REF],
            "counterparty_reference": ["CP-MDB", "CP-MDB-NAMED"],
            "exposure_type": ["loan", "loan"],
            "product_type": ["TERM_LOAN", "TERM_LOAN"],
            "book_code": ["BANKING", "BANKING"],
            "currency": ["GBP", "GBP"],
            "drawn_amount": [1_000_000.0, 1_000_000.0],
            "nominal_amount": [0.0, 0.0],
            "internal_pd": [0.01, 0.01],
            "lgd": [0.45, 0.45],
            "model_id": [model_id, model_id],
        },
        schema_overrides={"model_id": pl.String},
    )
    counterparties = pl.LazyFrame(
        {
            "counterparty_reference": ["CP-MDB", "CP-MDB-NAMED"],
            "counterparty_name": ["Generic MDB", "Named MDB"],
            "entity_type": ["mdb", "mdb_named"],
            "country_code": ["US", "US"],
            "institution_cqs": [2, 1],
        },
        schema_overrides={"institution_cqs": pl.Int8},
    )
    kwargs: dict = {
        "counterparty_lookup": make_counterparty_lookup(counterparties=counterparties),
        "lending_group_totals": pl.LazyFrame(
            schema={"lending_group_reference": pl.String, "total_exposure": pl.Float64}
        ),
        "hierarchy_errors": [],
    }
    if model_id is not None and permission_class is not None:
        kwargs["model_permissions"] = pl.LazyFrame(
            {
                "model_id": [model_id],
                "exposure_class": [permission_class],
                "approach": [ApproachType.FIRB.value],
            }
        )
    return make_resolved_bundle(exposures=exposures, **kwargs)


def _row(
    classifier: ExposureClassifier,
    config: CalculationConfig,
    bundle: object,
    reference: str,
) -> dict:
    """Classify and return the single row for ``reference``."""
    result = classifier.classify(bundle, config)  # type: ignore[arg-type]
    df = result.all_exposures.filter(pl.col("exposure_reference") == reference).collect()
    assert len(df) == 1, f"expected 1 row for {reference!r}, got {len(df)}"
    return df.to_dicts()[0]


# ---------------------------------------------------------------------------
# CRR — the P1.276 defect
# ---------------------------------------------------------------------------


class TestCRRNonNamedMDBIRBClass:
    """CRR Art. 147(4)(c): the generic MDB belongs to the institutions IRB class."""

    def test_crr_generic_mdb_irb_class_is_institution(
        self, classifier: ExposureClassifier, crr_config: CalculationConfig
    ) -> None:
        """CRR ``mdb`` -> exposure_class_irb == institution.

        Arrange: a GBP 1m loan to a generic (CQS-rated, non-0%) MDB, CRR config.
        Act:     ExposureClassifier.classify.
        Assert:  exposure_class_irb == "institution".

        Pre-fix failure: "central_govt_central_bank" — the Art. 147(3)(b) named-MDB
        treatment applied to every MDB.
        """
        # Arrange / Act
        row = _row(classifier, crr_config, _bundle(), MDB_REF)

        # Assert
        assert row["exposure_class_irb"] == _INSTITUTION, (
            "CRR Art. 147(4)(c) assigns MDBs not carrying a 0% Art. 117 risk weight "
            f"to the institutions class; got {row['exposure_class_irb']!r}."
        )

    def test_crr_named_mdb_irb_class_is_not_rerouted(
        self, classifier: ExposureClassifier, crr_config: CalculationConfig
    ) -> None:
        """CRR ``mdb_named`` is NOT caught by the Art. 147(4)(c) reroute.

        Art. 147(4)(c) is limited to MDBs "not assigned a 0 % risk weight under
        Article 117", so the Art. 117(2) named MDBs must keep whatever class they
        had. Today that is the SA-derived ``mdb``: ``sync_irb_exposure_class``
        overwrites ``exposure_class_irb`` with the SA class for every entity type
        outside its exclusion list, so the map's CGCB entry for ``mdb_named``
        never survives the classifier.

        The value pinned here is therefore CURRENT BEHAVIOUR, not a regulatory
        endorsement — Art. 147(3)(b) would put a named MDB in the
        central-government IRB class, a separate pre-existing gap outside P1.276
        (which is the Art. 147(4)(c) limb only). The load-bearing assertion is
        the first one: the reroute did not capture the named MDB.
        """
        # Arrange / Act
        row = _row(classifier, crr_config, _bundle(), MDB_NAMED_REF)

        # Assert
        assert row["exposure_class_irb"] != _INSTITUTION
        assert row["exposure_class_irb"] == _MDB

    def test_crr_generic_mdb_sa_class_untouched(
        self, classifier: ExposureClassifier, crr_config: CalculationConfig
    ) -> None:
        """CRR ``mdb`` keeps the MDB class on the SA-side columns.

        ``exposure_class_sa`` / ``exposure_class`` drive SA risk weights,
        ``exposure_class_applied`` and every COREP / Pillar 3 class row. The
        reroute must not touch them — Art. 112 keeps a dedicated SA MDB class.
        """
        # Arrange / Act
        row = _row(classifier, crr_config, _bundle(), MDB_REF)

        # Assert
        assert row["exposure_class_sa"] == _MDB
        assert row["exposure_class"] == _MDB


# ---------------------------------------------------------------------------
# Basel 3.1 — regression guard for the regime scoping
# ---------------------------------------------------------------------------


class TestBasel31MDBsAreNotRerouted:
    """PS1/26 Art. 147(3)(f): no Art. 147(4)(c) MDB split exists under Basel 3.1."""

    @pytest.mark.parametrize("reference", [MDB_REF, MDB_NAMED_REF])
    def test_b31_no_mdb_type_is_rerouted_to_institution(
        self,
        classifier: ExposureClassifier,
        b31_config: CalculationConfig,
        reference: str,
    ) -> None:
        """B31 ``mdb`` and ``mdb_named`` are both left out of the reroute.

        PS1/26 Art. 147(3)(f) lists multilateral development banks unconditionally
        among the entities assigned to the central-government class — the
        0%-risk-weight qualifier binds only the "(g) international organisations"
        limb — and PS1/26 Art. 147(4) has no MDB limb at all. The CRR
        Art. 147(4)(c) split must therefore NOT leak into Basel 3.1: this is the
        guard against a framework-invariant edit of ``entity_type_to_irb_class``.

        The second assertion records current B31 behaviour (the SA-derived
        ``mdb``, via the ``sync_irb_exposure_class`` overwrite) and is NOT a
        regulatory endorsement — PS1/26 Art. 147(3)(f) would say CGCB. That
        pre-existing gap is outside P1.276.
        """
        # Arrange / Act
        row = _row(classifier, b31_config, _bundle(), reference)

        # Assert
        assert row["exposure_class_irb"] != _INSTITUTION
        assert row["exposure_class_irb"] == _MDB


# ---------------------------------------------------------------------------
# Behavioural consequence: IRB model-permission matching
# ---------------------------------------------------------------------------


class TestCRRMDBPermissionMatching:
    """The IRB permission key follows the Art. 147(4)(c) class under CRR."""

    def test_crr_mdb_matches_institution_class_firb_permission(
        self, classifier: ExposureClassifier, crr_config: CalculationConfig
    ) -> None:
        """CRR ``mdb`` + INSTITUTION-class F-IRB permission -> foundation_irb.

        ``permissions.py`` matches ``exposure_class_irb`` against the permission
        row's class, so an institution-class permission is the one that now governs
        a non-named MDB.
        """
        # Arrange
        bundle = _bundle(model_id="MP-INST", permission_class=_INSTITUTION)

        # Act
        row = _row(classifier, crr_config, bundle, MDB_REF)

        # Assert
        assert row["approach"] == ApproachType.FIRB.value

    def test_crr_mdb_does_not_match_cgcb_class_firb_permission(
        self, classifier: ExposureClassifier, crr_config: CalculationConfig
    ) -> None:
        """CRR ``mdb`` + CGCB-class F-IRB permission -> falls back to SA.

        The mirror of the test above: a central-government permission no longer
        covers a non-named MDB under CRR. Pre-fix this row matched and routed to
        F-IRB on a permission the exposure class does not actually carry.
        """
        # Arrange
        bundle = _bundle(model_id="MP-CGCB", permission_class=_CGCB)

        # Act
        row = _row(classifier, crr_config, bundle, MDB_REF)

        # Assert
        assert row["approach"] == ApproachType.SA.value

    def test_crr_named_mdb_permission_key_is_unchanged(
        self, classifier: ExposureClassifier, crr_config: CalculationConfig
    ) -> None:
        """Control: CRR ``mdb_named`` still keys on its own (unchanged) class.

        A named MDB keeps ``exposure_class_irb == "mdb"``, so an ``mdb``-class
        permission still grants F-IRB. The reroute moved the non-named MDB's
        permission key only.
        """
        # Arrange
        bundle = _bundle(model_id="MP-MDB", permission_class=_MDB)

        # Act
        row = _row(classifier, crr_config, bundle, MDB_NAMED_REF)

        # Assert
        assert row["approach"] == ApproachType.FIRB.value


# ---------------------------------------------------------------------------
# Nil-capital-effect invariants
# ---------------------------------------------------------------------------


class TestClassFlipIsCapitalNeutral:
    """The two IRB parameters that could have keyed off the class do not."""

    @pytest.mark.parametrize("exposure_class", [_MDB, _INSTITUTION, _CGCB])
    def test_correlation_params_identical_across_the_flip(self, exposure_class: str) -> None:
        """CRR Art. 153(1): MDB / INSTITUTION / CGCB share one correlation ladder.

        0.12 / 0.24 with a 50 k-factor in every case, so moving an MDB row between
        these classes cannot change ``correlation``, ``k`` or ``rwa``.
        """
        # Arrange / Act
        params = get_correlation_params(exposure_class)

        # Assert
        assert (
            params.correlation_type,
            params.r_min,
            params.r_max,
            params.decay_factor,
        ) == ("pd_dependent", 0.12, 0.24, 50.0)

    def test_crr_institution_pd_floor_equals_the_default_floor(
        self, crr_config: CalculationConfig
    ) -> None:
        """CRR Art. 160(1): the institution floor equals the floor an MDB row took.

        ``_pd_floor_expression`` sends an INSTITUTION row to ``floors["institution"]``
        and an unrecognised class (MDB) to ``floors["corporate"]``. While those two
        are equal the class flip cannot move a floored PD. This is the invariant the
        "nil capital effect" claim rests on — it is NOT the all-values-equal
        shortcut, which a future CRR sovereign-floor change would remove.
        """
        # Arrange
        floors = RulepackV0.from_config(crr_config).pack.formula("pd_floors").params

        # Assert
        assert floors["institution"] == floors["corporate"]
