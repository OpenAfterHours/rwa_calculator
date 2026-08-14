"""
P1.354 — DQ006 must not fire on a documented ``risk_type`` spelling.

Pipeline position:
    RawDataBundle -> validate_column_values (pipeline-entry gate)

What this pins:
    ``RISK_TYPE_SYNONYMS`` documents 14 accepted spellings for the
    ``risk_type`` column — both the short codes (``"fr"``) and the long forms
    (``"full_risk"``) — and the CCF builders resolve every one of them
    correctly. The validation constraint, however, was
    ``VALID_RISK_TYPES_INPUT``: the 9 canonical codes only.

    ``validate_column_values`` lower-cases both sides, so the short codes
    happened to pass. The seven long forms did not, and a preparer writing the
    documented ``"full_risk"`` received a **DQ006 while the engine computed the
    correct 100% CCF**.

    That is worse than a missing error. DQ006 is the same code that carries the
    genuinely unrecognised case, so a false positive on documented input trains
    a reader to dismiss the true ones — and the true one here is the silent
    fallback the same column feeds (see P1.267).

    The fix widens the *constraint* set to the accepted domain while leaving
    ``VALID_RISK_TYPES_INPUT`` as the canonical output vocabulary. Both halves
    are pinned below: documented spellings must be accepted, and genuinely
    unknown values must still be rejected — a fix that simply dropped the
    constraint would satisfy the first and destroy the second.
"""

from __future__ import annotations

import pytest

from rwa_calc.data.schemas import (
    RISK_TYPE_SYNONYMS,
    VALID_RISK_TYPES_ACCEPTED,
    VALID_RISK_TYPES_INPUT,
)

#: The long-form spellings the constraint set previously rejected.
_LONG_FORMS = sorted(
    name
    for name in RISK_TYPE_SYNONYMS
    if name not in VALID_RISK_TYPES_INPUT and name.upper() not in VALID_RISK_TYPES_INPUT
)


def test_p1_354_every_documented_synonym_is_accepted() -> None:
    """Every spelling in ``RISK_TYPE_SYNONYMS`` passes validation.

    Arrange: the documented synonym map.
    Act: compare it against the constraint set.
    Assert: the constraint set is a superset.

    Stated over the whole map rather than a hard-coded list, so a synonym added
    later cannot reintroduce the defect by being documented and unvalidated.
    """
    missing = sorted(set(RISK_TYPE_SYNONYMS) - VALID_RISK_TYPES_ACCEPTED)

    assert not missing, (
        "P1.354: these spellings are documented in RISK_TYPE_SYNONYMS and resolve "
        f"correctly in the CCF builders, but the validator rejects them: {missing}. "
        "DQ006 would fire on input the engine handles perfectly."
    )


def test_p1_354_the_long_forms_are_the_ones_that_were_broken() -> None:
    """The seven long-form spellings are accepted.

    Anti-vacuity guard. The short codes always passed because the validator
    lower-cases both sides, so a test asserting only "the synonyms are accepted"
    could be satisfied by a constraint set that still rejects every long form.
    This names them explicitly.
    """
    assert _LONG_FORMS, "expected long-form synonyms to exist; the map has changed shape"

    rejected = [name for name in _LONG_FORMS if name not in VALID_RISK_TYPES_ACCEPTED]

    assert not rejected, f"P1.354: long-form spellings still rejected: {rejected}"


def test_p1_354_canonical_codes_remain_accepted() -> None:
    """The canonical vocabulary is still valid input.

    The survives-the-change half: widening the constraint must not have
    replaced the canonical set rather than extended it.
    """
    missing = sorted(VALID_RISK_TYPES_INPUT - VALID_RISK_TYPES_ACCEPTED)

    assert not missing, f"P1.354: canonical codes dropped from the constraint: {missing}"


def test_p1_354_unknown_values_are_still_rejected() -> None:
    """A genuinely unrecognised value is not accepted.

    The load-bearing negative. The whole point of the constraint is to catch
    input the engine cannot resolve; a fix that widened it to everything — or
    removed it — would pass every assertion above while destroying the check
    this item exists to protect.
    """
    for unknown in ("XYZ", "direct_credit_substitute", "medium", "full", ""):
        assert unknown not in VALID_RISK_TYPES_ACCEPTED, (
            f"P1.354: {unknown!r} is not a documented spelling and must still raise DQ006."
        )


def test_p1_354_canonical_set_is_unchanged_in_size() -> None:
    """``VALID_RISK_TYPES_INPUT`` stays the canonical output vocabulary.

    The two sets have different jobs: one is what the engine may *emit*, the
    other is what a preparer may *write*. Keeping them distinct is why the fix
    added a set rather than editing the existing one — collapsing them would
    make the canonical vocabulary include ``"full_risk"``, which no downstream
    consumer should ever see.
    """
    assert len(VALID_RISK_TYPES_INPUT) == 9
    assert VALID_RISK_TYPES_ACCEPTED > VALID_RISK_TYPES_INPUT
    assert len(VALID_RISK_TYPES_ACCEPTED) == pytest.approx(
        len(VALID_RISK_TYPES_INPUT | set(RISK_TYPE_SYNONYMS))
    )
