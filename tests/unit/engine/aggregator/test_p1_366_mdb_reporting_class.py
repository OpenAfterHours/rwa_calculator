"""
Unit pins — P1.366: a CRR IRB non-named MDB reports in the Art. 147 INSTITUTIONS class.

Pipeline position:
    ... -> OutputAggregator (``_add_reporting_projection``) -> COREP / Pillar 3

Key assertion:
    CRR Art. 147(4) (legislation.gov.uk, verbatim): "The following exposures shall
    be assigned to the class laid down in point (b) of paragraph 2 [institutions]:
    ... (c) exposures to multilateral development banks which are not assigned a
    0 % risk weight under Article 117". Art. 147(3)(b) sends only "exposures to
    multilateral development banks referred to in Article 117(2)" (the named MDBs)
    to central governments.

    The CRR IRB templates are laid out on those Art. 147(2) classes (COREP Annex II
    §3.3.2: CR IRB sheets "Institutions (point (b) of Article 147(2) CRR)"; C 09.02
    row 0020 "Institutions — Point (b) of Article 147(2) CRR"). The engine keeps a
    CRR non-named MDB's ``exposure_class`` at the Art. 112(1)(d) SA label ``mdb``
    on its IRB leg (``engine/classify/approach.py::_align_irb_exposure_class``
    deliberately does not align it — capital-neutral), so before P1.366 the
    projection published ``mdb`` on ``reporting_class_origin`` / ``reporting_class``
    for an IRB leg — a class no IRB template has a sheet or row for.

What the projection must do, per twin and on the twin's OWN approach:
    - ``reporting_class_origin`` -> ``institution`` where ``exposure_class_applied``
      is ``mdb``, ``exposure_class_irb`` is ``institution`` (the Art. 147(4)(c)
      class the classifier derived for a NON-named MDB) and
      ``reporting_approach_origin`` is F-IRB / A-IRB.
    - ``reporting_class`` -> ``institution`` under the same test on the post
      twins, only while the leg's post class is still the obligor's own (it was
      not substituted) and ``reporting_approach`` is F-IRB / A-IRB. A leg
      beneficially substituted to a guarantor carries the GUARANTOR's class and
      is untouched — including when that guarantor is itself an IRB-treated MDB,
      whose class the obligor's ``exposure_class_irb`` cannot decide.

Left alone, each pinned below:
    - an SA leg (``mdb`` is the correct Art. 112(1)(d) class on C 07.00 / C 09.01);
    - a NAMED MDB (``exposure_class_irb`` stays ``mdb``; Art. 147(3)(b) would put
      it in central governments — a separate engine gap, not relabelled here);
    - a Basel 3.1 MDB row: PS1/26 Art. 147(3)(f) + 147A(1)(a) route every MDB to
      SA with ``exposure_class_irb`` ``mdb``, so the relabel cannot fire;
    - a frame that seals no ``exposure_class_irb`` (the projection is exercised on
      minimal frames, so the read is absence-tolerant).

References:
    - CRR Art. 147(3)(b), 147(4)(c); CRR Art. 117(2)
    - PS1/26 Art. 147(3)(f), 147A(1)(a)
    - COREP Annex II §3.3.2 and C 09.02 row 0020
    - src/rwa_calc/engine/aggregator/aggregator.py::_add_reporting_projection
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.domain.enums import ApproachType, ExposureClass
from rwa_calc.engine.aggregator.aggregator import _add_reporting_projection

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MDB = ExposureClass.MDB.value
_INSTITUTION = ExposureClass.INSTITUTION.value
_CORPORATE = ExposureClass.CORPORATE.value
_FIRB = ApproachType.FIRB.value
_AIRB = ApproachType.AIRB.value
_SA = ApproachType.SA.value

#: The minimal column set ``_add_reporting_projection`` reads, with explicit dtypes
#: so a None keeps its column's real type (the pattern
#: ``tests/contracts/test_r1_gross_carrier_edge.py`` established).
_DTYPES: dict[str, pl.DataType] = {
    "exposure_reference": pl.String(),
    "exposure_type": pl.String(),
    "drawn_amount": pl.Float64(),
    "interest": pl.Float64(),
    "nominal_amount": pl.Float64(),
    "undrawn_amount": pl.Float64(),
    "ead_final": pl.Float64(),
    "risk_weight": pl.Float64(),
    "cp_entity_type": pl.String(),
    "exposure_class": pl.String(),
    "exposure_class_irb": pl.String(),
    "exposure_class_applied": pl.String(),
    "exposure_class_post_crm": pl.String(),
    "exposure_subclass": pl.String(),
    "approach_applied": pl.String(),
    "approach_post_crm": pl.String(),
    "is_guaranteed": pl.Boolean(),
    "is_guarantee_beneficial": pl.Boolean(),
    "post_crm_exposure_class_guaranteed": pl.String(),
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("approach", [_FIRB, _AIRB])
def test_crr_irb_non_named_mdb_reports_in_the_institutions_class(approach: str) -> None:
    """Both twins of an unguaranteed F-IRB / A-IRB non-named MDB leg read
    ``institution`` — Art. 147(4)(c)."""
    # Arrange
    frame = _frame(
        _leg("MDB", entity="mdb", irb_class=_INSTITUTION, approach=approach),
    )

    # Act
    projected = _add_reporting_projection(frame).collect()

    # Assert
    assert projected["reporting_class_origin"].to_list() == [_INSTITUTION]
    assert projected["reporting_class"].to_list() == [_INSTITUTION]


def test_crr_irb_mdb_retained_leg_relabels_and_irb_guaranteed_leg_keeps_guarantor_class() -> None:
    """A guarantee split of a non-named MDB F-IRB loan by an IRB corporate guarantor
    (Art. 161 / 236 parameter substitution keeps the leg on IRB).

    Origin basis: both legs are the OBLIGOR's exposure -> ``institution``. Post
    basis: the retained leg stays the obligor's -> ``institution``; the guaranteed
    leg carries the GUARANTOR's class (``corporate``) with an IRB approach twin and
    must not be relabelled — the measured shape of ``LN000__G_GCP000`` in the
    premise verification.
    """
    # Arrange
    frame = _frame(
        _leg(
            "MDB__G_GTOR",
            entity="mdb",
            irb_class=_INSTITUTION,
            approach=_FIRB,
            post_class=_CORPORATE,
            is_guaranteed=True,
        ),
        _leg("MDB__REM", entity="mdb", irb_class=_INSTITUTION, approach=_FIRB),
    )

    # Act
    projected = _add_reporting_projection(frame).collect()

    # Assert
    by_ref = _by_reference(projected)
    assert by_ref["MDB__G_GTOR"] == (_INSTITUTION, _CORPORATE)
    assert by_ref["MDB__REM"] == (_INSTITUTION, _INSTITUTION)


def test_crr_irb_mdb_leg_substituted_to_sa_guarantor_keeps_its_post_class() -> None:
    """A guaranteed slice that moved to an SA guarantor is a direct SA exposure to
    the guarantor (Art. 235): its post twin keeps the guarantor's SA class even when
    that class is ``mdb``, while the origin twin (obligor, IRB) still relabels."""
    # Arrange
    frame = _frame(
        _leg(
            "MDB__G_SAGTOR",
            entity="mdb",
            irb_class=_INSTITUTION,
            approach=_FIRB,
            post_class=_MDB,
            post_approach=_SA,
            is_guaranteed=True,
        ),
    )

    # Act
    projected = _add_reporting_projection(frame).collect()

    # Assert
    assert _by_reference(projected)["MDB__G_SAGTOR"] == (_INSTITUTION, _MDB)


@pytest.mark.parametrize("obligor_class", [_INSTITUTION, _MDB])
def test_slice_substituted_to_an_irb_mdb_guarantor_keeps_the_guarantor_class(
    obligor_class: str,
) -> None:
    """A slice beneficially substituted to an MDB guarantor treated as IRB reads the
    guarantor's ``mdb`` on the post basis with an IRB approach twin, and its
    ``exposure_class_irb`` is the OBLIGOR's. Whether that guarantor is named
    (Art. 147(3)(b), central governments) or not (Art. 147(4)(c), institutions)
    is not something the obligor's IRB class can tell, so the post twin keeps the
    guarantor's class. The origin twin is the obligor's: an institution stays
    ``institution``; a non-named MDB obligor relabels."""
    # Arrange
    frame = _frame(
        _leg(
            "OBL__G_MDBGTOR",
            entity=obligor_class,
            applied_class=obligor_class,
            irb_class=_INSTITUTION,
            approach=_FIRB,
            post_class=_MDB,
            is_guaranteed=True,
        ),
    )

    # Act
    projected = _add_reporting_projection(frame).collect()

    # Assert
    assert _by_reference(projected)["OBL__G_MDBGTOR"] == (_INSTITUTION, _MDB)


def test_non_beneficial_guarantee_leaves_the_mdb_slice_in_its_own_class() -> None:
    """A guarantee the engine declines (not beneficial) moves nothing: the slice
    stays the obligor's on the post basis, so it relabels like the obligor."""
    # Arrange
    frame = _frame(
        _leg(
            "MDB__G_DECLINED",
            entity="mdb",
            irb_class=_INSTITUTION,
            approach=_FIRB,
            is_guaranteed=True,
            beneficial=False,
            guarantor_class=_CORPORATE,
        ),
    )

    # Act
    projected = _add_reporting_projection(frame).collect()

    # Assert
    assert _by_reference(projected)["MDB__G_DECLINED"] == (_INSTITUTION, _INSTITUTION)


def test_sa_mdb_keeps_the_art_112_mdb_class() -> None:
    """On SA, ``mdb`` is the correct Art. 112(1)(d) class (C 07.00 / C 09.01 row
    0040) — the relabel is gated on an IRB approach."""
    # Arrange
    frame = _frame(_leg("MDB-SA", entity="mdb", irb_class=_INSTITUTION, approach=_SA))

    # Act
    projected = _add_reporting_projection(frame).collect()

    # Assert
    assert _by_reference(projected)["MDB-SA"] == (_MDB, _MDB)


def test_named_mdb_on_irb_is_not_put_in_the_institutions_class() -> None:
    """A named (Art. 117(2)) MDB reached IRB through an ``mdb``-class permission keeps
    ``exposure_class_irb`` ``mdb`` (``test_p1_276...::
    test_crr_named_mdb_permission_key_is_unchanged``). Art. 147(3)(b) puts it in
    CENTRAL GOVERNMENTS, never institutions, so it must not be swept up by the
    non-named relabel."""
    # Arrange
    frame = _frame(_leg("MDB-NAMED", entity="mdb_named", irb_class=_MDB, approach=_FIRB))

    # Act
    projected = _add_reporting_projection(frame).collect()

    # Assert
    assert _by_reference(projected)["MDB-NAMED"] != (_INSTITUTION, _INSTITUTION)
    assert _by_reference(projected)["MDB-NAMED"] == (_MDB, _MDB)


def test_basel_3_1_mdb_row_is_untouched() -> None:
    """PS1/26 Art. 147(3)(f) + 147A(1)(a): every MDB is SA under Basel 3.1 and the
    classifier keeps ``exposure_class_irb`` ``mdb``, so the projection is a no-op."""
    # Arrange
    frame = _frame(_leg("MDB-B31", entity="mdb", irb_class=_MDB, approach=_SA))

    # Act
    projected = _add_reporting_projection(frame).collect()

    # Assert
    assert _by_reference(projected)["MDB-B31"] == (_MDB, _MDB)


def test_frame_without_irb_class_projects_the_applied_class() -> None:
    """A minimal frame that seals no ``exposure_class_irb`` keeps the plain aliases —
    the read is absence-tolerant rather than a widened input contract."""
    # Arrange
    frame = _frame(_leg("MDB", entity="mdb", irb_class=_INSTITUTION, approach=_FIRB)).drop(
        "exposure_class_irb"
    )

    # Act
    projected = _add_reporting_projection(frame).collect()

    # Assert
    assert _by_reference(projected)["MDB"] == (_MDB, _MDB)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _leg(
    reference: str,
    *,
    entity: str,
    irb_class: str,
    approach: str,
    applied_class: str = _MDB,
    post_class: str | None = None,
    post_approach: str | None = None,
    is_guaranteed: bool = False,
    beneficial: bool = True,
    guarantor_class: str | None = None,
) -> dict[str, object]:
    """One drawn leg in the sealed shape.

    The SA-side classes default to ``mdb`` (the engine keeps the Art. 112 label on
    the IRB leg) and the post twins to the origin ones, as
    ``_add_post_crm_reporting_class`` / ``_approach`` resolve them for an
    unguaranteed or retained leg. A guaranteed leg carries the guarantee's
    benefit flag and the guarantor's class (``post_class`` unless
    ``guarantor_class`` says otherwise), so the substitution columns agree with
    the post class the way the aggregator derives it: a beneficial guarantee
    moves the post class to the guarantor's, a declined one leaves it alone.
    """
    gtor_class = guarantor_class if guarantor_class is not None else post_class
    return {
        "exposure_reference": reference,
        "exposure_type": "loan",
        "drawn_amount": 1_000.0,
        "interest": 0.0,
        "nominal_amount": 0.0,
        "undrawn_amount": 0.0,
        "ead_final": 1_000.0,
        "risk_weight": 1.0,
        "cp_entity_type": entity,
        "exposure_class": applied_class,
        "exposure_class_irb": irb_class,
        "exposure_class_applied": applied_class,
        "exposure_class_post_crm": post_class if post_class is not None else applied_class,
        "exposure_subclass": None,
        "approach_applied": approach,
        "approach_post_crm": post_approach if post_approach is not None else approach,
        "is_guaranteed": is_guaranteed,
        "is_guarantee_beneficial": beneficial if is_guaranteed else None,
        "post_crm_exposure_class_guaranteed": gtor_class if is_guaranteed else None,
    }


def _frame(*legs: dict[str, object]) -> pl.LazyFrame:
    """The legs as a LazyFrame with the projection's input dtypes."""
    return pl.LazyFrame(
        {name: [leg[name] for leg in legs] for name in _DTYPES},
        schema=_DTYPES,
    )


def _by_reference(projected: pl.DataFrame) -> dict[str, tuple[str, str]]:
    """``exposure_reference -> (reporting_class_origin, reporting_class)``."""
    return {
        row["exposure_reference"]: (row["reporting_class_origin"], row["reporting_class"])
        for row in projected.iter_rows(named=True)
    }
