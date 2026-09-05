"""
P1.311 — a regime-divergent entity-class override must actually take effect.

Pipeline position:
    rulebook.resolve -> engine/entity_class_maps -> Classifier
    (``engine/classify/attributes.py::derive_independent_flags``)

What this pins:
    ``engine/entity_class_maps`` used to resolve ``entity_type_to_sa_class`` /
    ``entity_type_to_irb_class`` against a hard-coded ``resolve("crr", ...)``
    once at module import and rebind them into plain dicts. Both maps live in
    the common pack, so a regime-divergent override placed in ``packs/b31.py``
    would be merged by ``resolve("b31", ...)`` — and never seen, because this
    module never asked for the b31 regime. The failure mode was silent: the
    Basel 3.1 engine quietly keeping the CRR class.

    That trap has been hit twice. P1.276 (2026-07-24) and P1.286 (batch
    20260724b) each proposed a pack-map edit at that exact site and were dead
    on arrival, and P1.303 records routing around it explicitly.

Why the test is BEHAVIOURAL and not an equality assertion:
    The obvious guard — assert the two resolved maps are identical — **passes
    today and proves nothing**, because the packs currently agree exactly (31
    entries each, zero differences). Worse, it is the wrong guard: P1.303 D4
    records a pending Basel 3.1 divergence under PS1/26 Art. 147(3) that these
    maps are the natural home for, so a "the maps must match" invariant would
    fire on the *correct* change and have to be deleted to proceed. A ratchet
    that blocks the right change while permitting nothing is worse than none.

    So this test injects a divergent override and asserts the classifier
    HONOURS it. It fails on the pre-fix module with the CRR value, and it stays
    meaningful once a real divergence is written.

References:
    - CRR Art. 112 Table A2 / Art. 147 — the two maps' subject matter
    - PS1/26 Art. 147(3) — the pending divergence P1.303 D4 records
"""

from __future__ import annotations

from datetime import date

import pytest

from rwa_calc.engine.entity_class_maps import (
    entity_type_to_irb_class,
    entity_type_to_sa_class,
    entity_types_by_sa_class,
)
from rwa_calc.rulebook.model import CategoryMap, Citation
from rwa_calc.rulebook.resolve import resolve

_REPORTING_DATE = date(2027, 6, 30)

#: The entity type P1.303 D4 names as belonging to the central-government class
#: under PS1/26 Art. 147(3) where CRR puts it in institutions. Used here only as
#: a realistic divergence to inject — this test does not decide that question.
_DIVERGENT_ENTITY = "pse_institution"


def _b31_pack_with_irb_override(entity: str, target_class: str):
    """A resolved b31 pack whose IRB entity map diverges from CRR by one entry."""
    pack = resolve("b31", _REPORTING_DATE)
    entries = dict(pack.category_map("entity_type_to_irb_class").entries)
    entries[entity] = target_class
    return pack.with_overrides(
        entity_type_to_irb_class=CategoryMap(
            name="entity_type_to_irb_class",
            entries=entries,
            key="entity_type",
            citation=Citation("PS1/26", "147", "(3)"),
        )
    )


def test_p1_311_a_b31_override_reaches_the_irb_map() -> None:
    """A divergent b31 override is honoured, not silently replaced by CRR's value.

    Arrange: a resolved Basel 3.1 pack whose IRB entity map sends
    ``pse_institution`` to the central-government class.
    Act: bind the map through the accessor for that pack.
    Assert: the override is what comes back.

    This is the assertion that fails before the fix. The module resolved
    ``"crr"`` at import and returned a module-level dict, so any pack passed by
    a caller was ignored and this returned the CRR value.
    """
    pack = _b31_pack_with_irb_override(_DIVERGENT_ENTITY, "central_govt_central_bank")

    assert entity_type_to_irb_class(pack)[_DIVERGENT_ENTITY] == "central_govt_central_bank", (
        "P1.311: a regime-divergent override in the b31 pack must reach the engine. "
        "Binding the map from a hard-coded resolve('crr', ...) at import made such an "
        "override silently unreachable."
    )


def test_p1_311_the_crr_pack_is_unaffected_by_the_b31_override() -> None:
    """The CRR map keeps its own value — the regime-leak guard.

    The point of the change is that the two regimes can differ. A fix that made
    the accessor return whichever map was resolved *last*, or that mutated
    shared state, would satisfy the assertion above and break this one.
    """
    _ = _b31_pack_with_irb_override(_DIVERGENT_ENTITY, "central_govt_central_bank")
    crr = entity_type_to_irb_class(resolve("crr", _REPORTING_DATE))

    assert crr[_DIVERGENT_ENTITY] != "central_govt_central_bank", (
        "P1.311: overriding the b31 pack must not disturb the CRR binding."
    )


def test_p1_311_the_default_binding_still_works_without_a_pack() -> None:
    """Callers that hold no pack still get a populated map.

    Several consumers (the CRM guarantee branches) have no pack in scope and
    read the module-level dicts. Those must keep working, so the accessors take
    an optional pack rather than a required one.
    """
    sa_map = entity_type_to_sa_class()
    irb_map = entity_type_to_irb_class()

    assert sa_map and irb_map, "the default binding must not be empty"
    assert "corporate" in sa_map
    assert "corporate" in irb_map


def test_p1_311_the_inverse_index_follows_the_pack_it_is_given() -> None:
    """``entity_types_by_sa_class`` is derived from the same pack, not the default.

    The inverse index feeds the CRR Art. 140(1) / CRE21.16 short-term ECAI
    obligor-class gate in ``engine/hierarchy/enrich.py``, which expands the
    ``institution`` and ``corporate`` SA classes into the set of ``entity_type``
    strings a short-term assessment may be used for. If the index kept binding
    the default pack while the forward map followed the caller's, the two would
    disagree for exactly the rows a divergence affects — a subtler version of
    the defect being fixed.

    **Scope, stated honestly: this is a forward guard, not a pin on a live
    path.** The docstring used to name "the entity-level SA RW preview" as the
    consumer; that preview
    (``engine/sa/guarantor_rw.py::build_entity_rw_expr``) is deleted, and the
    Art. 140(1) gate named above is the only remaining one. But the gate reads
    the module-level ``ENTITY_TYPES_BY_SA_CLASS`` constant, which
    ``entity_class_maps.py`` binds by calling this accessor with **no pack** at
    import. So no production caller passes a pack to
    ``entity_types_by_sa_class`` today, and this test is currently its only
    pack-aware caller. That is the difference from the forward maps, which
    ``engine/classify/attributes.py`` does call with the run's pack.

    Keep the test rather than delete it: a regime-divergent SA class map is the
    change P1.303 D4 anticipates, and the day the gate starts resolving through
    the run's pack this is the assertion that says the two sides agree. Written
    down because an unexercised parameter that looks exercised is how a
    divergence lands silently on one of the two maps.
    """
    pack = resolve("b31", _REPORTING_DATE)
    entries = dict(pack.category_map("entity_type_to_sa_class").entries)
    entries["corporate"] = "institution"
    diverged = pack.with_overrides(
        entity_type_to_sa_class=CategoryMap(
            name="entity_type_to_sa_class",
            entries=entries,
            key="entity_type",
            citation=Citation("PS1/26", "112"),
        )
    )

    by_class = entity_types_by_sa_class(diverged)

    assert "corporate" in by_class.get("institution", ()), (
        "P1.311: the inverse index must be derived from the caller's pack, not the "
        "module default, or it disagrees with the forward map under a divergence."
    )


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_p1_311_both_regimes_bind_a_complete_map(regime: str) -> None:
    """Neither regime resolves to a partial map.

    Anti-vacuity: the assertions above would all pass against an empty dict for
    one regime, since they only inspect single keys.
    """
    sa_map = entity_type_to_sa_class(resolve(regime, _REPORTING_DATE))
    irb_map = entity_type_to_irb_class(resolve(regime, _REPORTING_DATE))

    assert len(sa_map) > 20, f"{regime} SA map looks truncated: {len(sa_map)} entries"
    assert len(irb_map) > 20, f"{regime} IRB map looks truncated: {len(irb_map)} entries"
