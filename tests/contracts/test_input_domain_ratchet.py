"""
Contract: the declared input-domain population may only grow, and never dies unread.

Pipeline position:
    (not a pipeline stage) — a gate over ``src/rwa_calc/data/schemas.py``.

Key responsibilities:
- Run ``scripts/check_input_domains.py --check`` for real, on every dev-loop
  pytest run, so the ratchet cannot rot unwired.
- Demonstrate BOTH directions of the ratchet and the reachability limb against
  synthetic populations, in milliseconds, so each failure mode is shown rather
  than argued from code.
- Pin the invariants a baseline diff alone cannot express: every declaration
  states a basis, and the highest-value domains are actually declared.

Why the wiring test is in-suite rather than a CI job:
    ``docs/development/escape-log.md`` 2026-08-09 entry 1 is the whole
    argument. A ratchet wired only into ``.github/workflows/ci.yml`` was
    defeated six ways while its invocation guard stayed green (``run:``
    commented out, ``if: false``, ``continue-on-error: true``, the step
    deleted with the command left in a comment, the workflow's ``on:``
    triggers removed, and the guard asserting that CI *invokes* the script
    rather than that the script *works*). This census is a module import and a
    dict walk, so it belongs where nobody has to remember to run it.

References:
- ``docs/plans/test-space-correctness-proposal.md`` — Phase 1
- `.claude/LESSONS.md` B8 (ratchet the accumulator, not a ratio)
- ``scripts/check_input_domains.py``
"""

from __future__ import annotations

import pytest
from scripts.check_input_domains import census, unreachable_declarations
from scripts.tolerated_findings import diff

from rwa_calc.data.column_spec import EnumDomain, NumericDomain

# ---------------------------------------------------------------------------
# The gate itself, against the real declarations
# ---------------------------------------------------------------------------


def test_declared_domains_match_the_committed_baseline() -> None:
    """The two-way ratchet: nothing added unbanked, nothing removed at all.

    Arrange: the real census and the committed baseline.
    Act:     set-diff them.
    Assert:  they are the same set.
    """
    # Arrange
    from scripts.check_input_domains import _load_baseline

    # Act
    moved = diff(sorted(census()), _load_baseline())

    # Assert
    assert not moved.removed, (
        "A declared input domain was REMOVED — coverage going backwards:\n  "
        + "\n  ".join(moved.removed)
        + "\nFix the data or the bound; do not delete the declaration to clear a red gate."
    )
    assert not moved.added, (
        "New declared input domain(s) are unbanked:\n  "
        + "\n  ".join(moved.added)
        + "\nBank them: uv run python scripts/check_input_domains.py --update-baseline"
    )


def test_no_declared_domain_is_unreachable_from_the_input_gate() -> None:
    """A domain on a table nothing validates is guard-shaped data.

    The declaration-level analogue of ``arch_check`` check 20: check 20 stops a
    guard FUNCTION going unreachable, this stops a guard DECLARATION doing it.
    """
    # Arrange / Act
    dead = unreachable_declarations()

    # Assert
    assert not dead, (
        "These columns declare a domain no input-gate table reads:\n  "
        + "\n  ".join(dead)
        + "\nWire the table into contracts/validation.py::bundle_frames, or drop it."
    )


# ---------------------------------------------------------------------------
# Invariants a baseline diff cannot express
# ---------------------------------------------------------------------------


def test_every_declared_domain_states_its_basis() -> None:
    """A bound with no stated reason is how a WRONG bound survives review."""
    # Arrange / Act
    thin = {
        declared_id: domain.reason
        for declared_id, domain in census().items()
        if len(domain.reason.strip()) < 40
    }

    # Assert
    assert not thin, f"Declared domains whose reason is too thin to review: {thin}"


@pytest.mark.parametrize(
    "declared_id",
    [
        # The measured silent-wrong-number cases from the proposal's evidence
        # table. Each one returned a plausible number with no signal at all
        # before Phase 1, so each must stay declared by name — a baseline diff
        # would not notice one being swapped for an easier column.
        "RATINGS_SCHEMA::pd",
        "RATINGS_SCHEMA::cqs",
        "COUNTERPARTY_SCHEMA::sovereign_cqs",
        "COUNTERPARTY_SCHEMA::institution_cqs",
        "FACILITY_SCHEMA::lgd",
        "LOAN_SCHEMA::lgd",
        "CONTINGENTS_SCHEMA::lgd",
        "FACILITY_SCHEMA::effective_maturity",
        "LOAN_SCHEMA::effective_maturity",
        "FACILITY_SCHEMA::ccf_modelled",
        "FX_RATES_SCHEMA::rate",
    ],
)
def test_the_measured_defect_columns_stay_declared(declared_id: str) -> None:
    """Named, not counted — B8's argument applied to the population's membership."""
    assert declared_id in census(), f"{declared_id} lost its declared domain"


def test_cqs_domain_is_the_six_step_scale_in_every_schema_that_carries_it() -> None:
    """A corporate at CQS 0/7/99 took the unrated 100% branch in silence.

    Anchored to the CQS enum rather than to a hand-written 1-6, so the test and
    the declaration cannot drift together (`.claude/LESSONS.md` B3).

    ``CQS.UNRATED = 0`` is EXCLUDED, and that exclusion is the substantive
    claim of this test rather than a convenience. It is an engine-internal
    LOOKUP KEY — the "unrated" row of the pack risk-weight tables
    (``rulebook/packs/crr.py``, ``b31.py``) — not an input value. The input
    contract for the column is nullable and documented as "Credit Quality Step
    (1-6)" (``docs/data-model/input-schemas.md``), so NULL is how a feed says
    unrated. Admitting 0 as well would give "unrated" two spellings on the
    input side and make the declared domain unable to catch a truncated or
    zero-filled CQS field.
    """
    # Arrange
    from rwa_calc.domain.enums import CQS

    steps = [int(member) for member in CQS if member is not CQS.UNRATED]

    # Act
    cqs_domains = {
        declared_id: domain
        for declared_id, domain in census().items()
        if declared_id.endswith(("::cqs", "_cqs"))
    }

    # Assert
    assert cqs_domains, "no CQS domain is declared at all"
    for declared_id, domain in cqs_domains.items():
        assert isinstance(domain, NumericDomain)
        assert (domain.lower, domain.upper) == (min(steps), max(steps)), (
            f"{declared_id} declares {domain.describe()}, not the CQS scale "
            f"[{min(steps)}, {max(steps)}]"
        )


# ---------------------------------------------------------------------------
# The mechanism, driven through synthetic populations
# ---------------------------------------------------------------------------


def test_a_removed_declaration_is_a_regression_whatever_else_was_added() -> None:
    """B8: the accumulator, not the count. A count ratchet passes this case."""
    # Arrange — one domain lost, one gained: the count is unchanged.
    baseline = ["A_SCHEMA::pd", "A_SCHEMA::lgd"]
    register = ["A_SCHEMA::lgd", "A_SCHEMA::trivial_new_column"]

    # Act
    moved = diff(register, baseline)

    # Assert
    assert moved.removed == ("A_SCHEMA::pd",)
    assert moved.added == ("A_SCHEMA::trivial_new_column",)


def test_both_domain_shapes_reject_a_reason_free_declaration() -> None:
    """The mandatory ``reason`` is enforced by the type, not by convention."""
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="reason is mandatory"):
        NumericDomain(reason="  ", lower=0.0)
    with pytest.raises(ValueError, match="reason is mandatory"):
        EnumDomain(reason="", values={"a"})


def test_a_numeric_domain_must_bound_at_least_one_side() -> None:
    """An unbounded 'domain' would be a declaration that validates nothing."""
    with pytest.raises(ValueError, match="bound at least one side"):
        NumericDomain(reason="a reason long enough to pass review")
