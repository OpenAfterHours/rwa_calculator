"""The CRR supporting-factor shapes in the C 07.00 unit fixtures are ones the engine can produce.

A synthetic reporting frame is a claim about what the sealed ledger carries
(LESSONS C11(c)). The C 07.00 projection of cols 0215/0216/0217/0220 reads
``rwa_pre_factor`` and ``rwa_final`` as given and never re-derives the
multiplier, so a fixture can carry ANY flagged reduction and every projection
test stays green on it — which is how ``test_c07_infra_factor_benefit`` came to
pin a -60.0 from an infrastructure leg reduced at 0.95 (P5.67). Nothing in the
projection tests can see that; this file is what does.

What the engine can produce, row by row:

- ``engine/sa/factors_output.py::calculate_rwa``: ``rwa_pre_factor`` is
  ``ead_final x risk_weight`` (CRR Art. 113(1)-(5)).
- ``engine/supporting_factors.py::apply_factors``: ``rwa_final`` is
  ``rwa_pre_factor x min(sme_factor, infrastructure_factor)``, each factor 1.0
  where it does not apply. CRR Art. 501a(1) multiplies by a flat 0,75 — no
  tiering — so an infrastructure row is reduced at exactly the pack's
  ``infrastructure_factor``, which sits below the SME blend's floor and so
  always wins the minimum.
- CRR Art. 501(1) blends 0,7619 up to the threshold and 0,85 above it, weighted
  by E*, the total owed by the SME's group of connected clients. The SME factor
  is therefore a function of E*, not a free choice in [0,7619, 0,85): it is the
  floor exactly when E* is at or under the threshold, and strictly between floor
  and ceiling above it — it reaches 0,85 only in the limit. So an SME-only row
  is checked for EQUALITY with the blend evaluated at its own E*, which this
  file derives with the engine's own definitions
  (``engine/supporting_factors.py::e_star_contribution_expr`` summed over
  ``obligor_group_key_expr``), over the whole frame as the engine's per-frame
  fallback does. The unit frames are small (E* in the thousands against a
  threshold in the millions), so the floor is the only SME ratio they can
  reach: a blended factor strictly between floor and ceiling, of the kind the
  CRR-F2/F3/F8 acceptance scenarios assert at E* above the threshold, is
  unreachable here and fails.
- A row with neither factor is not reduced at all.

Every bound — the three multipliers and the EUR-based E* threshold, converted
at the CRR config's ``eur_gbp_rate`` through ``engine/thresholds.py`` — is read
from the CRR pack, never typed here, so the test cannot drift with the fixture
it checks (LESSONS B3).

The two fixtures take the two attribution limbs of
``reporting/corep/supporting_factors.py::sf_adjustment_terms``:
``_sa_results_with_phase2_cols`` the dedicated per-factor flags (limb 1,
unreachable in production; this frame is its C 07.00 unit coverage), and
``_sa_results_with_supporting_factors`` the generic ``is_sme`` /
``is_infrastructure`` + ``supporting_factor_applied`` pair (limb 2, the one a
real run takes). The flags are resolved here in the same preference order,
and null-safely: a null flag reads as "not applied", as it does in the engine
and the projection, so it cannot drop its row out of every guard's partition.
Limb 2's ``is_infrastructure`` is the Art. 501a CANDIDATE flag; the engine
applies 0,75 only where the class and default limbs also hold, so a candidate
SME row of another class, reduced at the SME blend, would fail the
infrastructure guard here. That is over-strict — the safe direction — and
neither frame holds such a row.

CRR only, by construction. Basel 3.1 removes both factors — the b31 pack sets
all three multipliers to 1.0 and OF 07.00 has no cols 0215-0217 (PS1/26
Annex II) — so a factor-flagged reduction is unreachable under Basel 3.1 by
definition and there is no second regime to parametrise. The Basel 3.1 tests
that reuse these frames read only column presence, unrated col 0235 or
relative sums.

Scope: the two C 07.00 frames. The C 08.01 / C 08.02 unit frames that carry
``sme_supporting_factor_applied`` are not checked here.

References:
- CRR Art. 113(1)-(5), Art. 501(1), Art. 501a(1)
- COREP Annex II C 07.00 cols 0215/0216/0217/0220
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.engine.supporting_factors import e_star_contribution_expr, obligor_group_key_expr
from rwa_calc.engine.thresholds import regulatory_threshold
from rwa_calc.rulebook.resolve import resolve
from tests.unit.reporting.corep._builders import _sa_results_with_phase2_cols
from tests.unit.reporting.corep.test_c07 import _sa_results_with_supporting_factors

_CRR_DATE = date(2026, 1, 1)
_CRR_PACK = resolve("crr", _CRR_DATE)
_CRR_SF = _CRR_PACK.formula("supporting_factors_values").params
_INFRA_FACTOR = float(_CRR_SF["infrastructure_factor"])
_SME_FLOOR = float(_CRR_SF["sme_factor_under_threshold"])
_SME_CEILING = float(_CRR_SF["sme_factor_above_threshold"])
#: Art. 501(1) E* threshold in GBP: the pack's EUR base at the CRR config's rate.
_SME_THRESHOLD = float(
    regulatory_threshold(
        _CRR_PACK, "sme_exposure_threshold", CalculationConfig.crr(_CRR_DATE).eur_gbp_rate
    )
)

#: Float tolerance on a ratio or a relative money difference.
_TOL = 1e-9

_FIXTURES: dict[str, Callable[[], pl.LazyFrame]] = {
    "dedicated_flags": _sa_results_with_phase2_cols,
    "pipeline_flags": _sa_results_with_supporting_factors,
}

#: The three populations the reduction guards check, over the resolved flags.
#: Every row must land in exactly one, or no guard checks it.
_INFRA = pl.col("_infra")
_SME_ONLY = pl.col("_sme") & ~pl.col("_infra")
_UNFLAGGED = ~pl.col("_sme") & ~pl.col("_infra")
_PARTITIONS = (_SME_ONLY, _INFRA, _UNFLAGGED)

#: Each flag column a fixture resolves a factor state from, and the resolved
#: flag(s) a null in it must leave at "not applied".
_NULLABLE_FLAGS: list[tuple[str, str, tuple[str, ...]]] = [
    ("dedicated_flags", "infrastructure_factor_applied", ("_infra",)),
    ("dedicated_flags", "sme_supporting_factor_applied", ("_sme",)),
    ("pipeline_flags", "is_infrastructure", ("_infra",)),
    ("pipeline_flags", "is_sme", ("_sme",)),
    ("pipeline_flags", "supporting_factor_applied", ("_infra", "_sme")),
]


@pytest.fixture(params=sorted(_FIXTURES))
def legs(request: pytest.FixtureRequest) -> pl.DataFrame:
    """One CRR supporting-factor fixture, with each row's factor state resolved."""
    return _with_factor_states(_FIXTURES[request.param]().collect())


def test_pre_factor_rwea_is_ead_times_risk_weight(legs: pl.DataFrame) -> None:
    """Every row's ``rwa_pre_factor`` is ``ead_final x risk_weight`` (Art. 113)."""
    # Arrange
    expected = pl.col("ead_final") * pl.col("risk_weight")

    # Act
    breaks = legs.filter(_differs(pl.col("rwa_pre_factor"), expected))

    # Assert
    assert breaks.height == 0, (
        "rwa_pre_factor != ead_final x risk_weight, a pre-factor RWEA the engine cannot "
        f"produce: {_rows(breaks, 'ead_final', 'risk_weight', 'rwa_pre_factor')}"
    )


def test_infrastructure_rows_reduce_at_the_flat_art_501a_factor(legs: pl.DataFrame) -> None:
    """An infrastructure row's ``rwa_final`` is ``rwa_pre_factor`` x the pack's flat factor."""
    # Arrange
    infra = legs.filter(_INFRA)
    assert infra.filter(pl.col("rwa_pre_factor") > 0).height > 0, (
        "the fixture holds no infrastructure leg with RWEA - this test would prove nothing"
    )

    # Act
    breaks = infra.filter(_differs(pl.col("rwa_final"), pl.col("rwa_pre_factor") * _INFRA_FACTOR))

    # Assert
    assert breaks.height == 0, (
        f"infrastructure legs not reduced at the flat Art. 501a factor {_INFRA_FACTOR}: "
        f"{_rows(breaks, 'rwa_pre_factor', 'rwa_final', '_ratio')}"
    )


def test_sme_only_rows_reduce_at_the_art_501_blend_of_their_e_star(legs: pl.DataFrame) -> None:
    """An SME-only row's ``rwa_final`` is ``rwa_pre_factor`` x the Art. 501 blend at its E*."""
    # Arrange
    sme_only = legs.filter(_SME_ONLY)
    assert (
        sme_only.filter((pl.col("rwa_pre_factor") > 0) & (pl.col("_e_star") <= _SME_THRESHOLD))
    ).height > 0, (
        "the fixture holds no SME-only leg with RWEA at or under the E* threshold - "
        "the floor case, the only one a unit-scale frame reaches, would go unchecked"
    )
    expected = pl.col("rwa_pre_factor") * _art_501_factor(pl.col("_e_star"))

    # Act
    breaks = sme_only.filter(_differs(pl.col("rwa_final"), expected))

    # Assert
    assert breaks.height == 0, (
        f"SME legs not reduced at the Art. 501 blend of their E* (floor {_SME_FLOOR} at or "
        f"under {_SME_THRESHOLD:,.0f}, ceiling {_SME_CEILING} above): "
        f"{_rows(breaks, '_e_star', 'rwa_pre_factor', 'rwa_final', '_ratio')}"
    )


def test_unflagged_rows_are_not_reduced(legs: pl.DataFrame) -> None:
    """A row with neither factor has ``rwa_final == rwa_pre_factor``."""
    # Arrange
    unflagged = legs.filter(_UNFLAGGED)
    assert unflagged.filter(pl.col("rwa_pre_factor") > 0).height > 0, (
        "the fixture holds no unflagged leg with RWEA - this test would prove nothing"
    )

    # Act
    breaks = unflagged.filter(_differs(pl.col("rwa_final"), pl.col("rwa_pre_factor")))

    # Assert
    assert breaks.height == 0, (
        "unflagged legs whose RWEA moved, a reduction no supporting factor explains: "
        f"{_rows(breaks, 'rwa_pre_factor', 'rwa_final')}"
    )


@pytest.mark.parametrize(
    ("fixture", "column", "gated"),
    _NULLABLE_FLAGS,
    ids=[f"{fixture}-{column}" for fixture, column, _ in _NULLABLE_FLAGS],
)
def test_a_null_flag_resolves_as_not_applied(
    fixture: str, column: str, gated: tuple[str, ...]
) -> None:
    """A null factor flag reads as "not applied", as the engine reads it, so its row stays checked.

    ``is_infrastructure`` is nullable on the sealed ledger
    (``engine/classify/attributes.py`` derives it by a substring match on
    ``product_type``, so it is null wherever that is), and ``apply_factors``
    routes a null ``is_sme`` or ``is_infrastructure`` through ``pl.when`` to
    factor 1.0. Resolved with a null-propagating ``&`` / ``~``, the null reached
    the partition filters above and dropped the row from all three: an SME leg
    with a null ``is_infrastructure`` reduced at 0.70, or at the 0.85 ceiling,
    passed every guard, and so did an SME leg with a null ``is_sme`` reduced at
    0.70 (P5.67 review). The sibling projection reads ``is_infrastructure`` the
    same way (``reporting/corep/supporting_factors.py::sf_infra_flag_exprs``).
    The dedicated flags and ``supporting_factor_applied`` are read alike — the
    strict reading, under which a row whose flag is unknown must be unreduced.
    """
    # Arrange
    frame = _FIXTURES[fixture]().collect()
    assert frame.get_column(column).any(), (
        f"{fixture} has no row with {column} set - nulling it would prove nothing"
    )
    nulled = frame.with_columns(pl.lit(None, dtype=pl.Boolean).alias(column))

    # Act
    resolved = _with_factor_states(nulled)

    # Assert
    in_one = pl.sum_horizontal([p.fill_null(False).cast(pl.Int8) for p in _PARTITIONS]) == 1
    unchecked = resolved.filter(~in_one)
    assert unchecked.height == 0, (
        f"rows no reduction guard checks once {column} is null: "
        f"{_rows(unchecked, '_sme', '_infra')}"
    )
    for flag in gated:
        assert resolved.get_column(flag).to_list() == [False] * resolved.height, (
            f"a null {column} must resolve {flag} to not applied, as the engine does: "
            f"{_rows(resolved, flag)}"
        )


def _with_factor_states(legs: pl.DataFrame) -> pl.DataFrame:
    """Add ``_infra`` / ``_sme`` / ``_e_star`` / ``_ratio``, resolved as the engine does.

    The flags are resolved as the projection does: the dedicated per-factor flag
    wins where the frame carries it; otherwise the generic class flag conjoined
    with ``supporting_factor_applied``. Each is read with ``eq_missing(True)``,
    so a null flag is "not applied" — the engine's reading (``apply_factors``
    sends a null through ``pl.when`` to factor 1.0) and the projection's
    (``sf_infra_flag_exprs``). ``_infra`` and ``_sme`` are therefore never null,
    so every row lands in exactly one of the guards' three partitions; a
    null-propagating ``&`` / ``~`` drops it from all three, unchecked
    (``test_a_null_flag_resolves_as_not_applied``). ``_e_star`` is each row's obligor-group
    E* by the engine's own definitions, summed over the whole frame (the
    engine's per-frame fallback in ``apply_factors``; a frame with no
    ``lending_group_reference`` makes every counterparty a group of one).
    """
    cols = set(legs.columns)

    def applied(dedicated: str, generic: str) -> pl.Expr:
        if dedicated in cols:
            return pl.col(dedicated).eq_missing(True)
        return pl.col(generic).eq_missing(True) & pl.col("supporting_factor_applied").eq_missing(
            True
        )

    if "lending_group_reference" not in cols:
        legs = legs.with_columns(pl.lit(None, dtype=pl.String).alias("lending_group_reference"))
    contribution = e_star_contribution_expr(legs.columns)
    group_key = obligor_group_key_expr()

    return legs.with_columns(
        applied("infrastructure_factor_applied", "is_infrastructure").alias("_infra"),
        applied("sme_supporting_factor_applied", "is_sme").alias("_sme"),
        pl.when(group_key.is_not_null())
        .then(contribution.sum().over(group_key))
        .otherwise(contribution)
        .alias("_e_star"),
        (pl.col("rwa_final") / pl.col("rwa_pre_factor")).alias("_ratio"),
    )


def _art_501_factor(e_star: pl.Expr) -> pl.Expr:
    """CRR Art. 501(1): ``[min(E*, T) x floor + max(E* - T, 0) x ceiling] / E*``.

    Written from the article, not from the engine, with every value read from the
    pack. An E* of zero or less is wholly within the first tier, so it takes the
    floor (as ``apply_factors`` does).
    """
    threshold = pl.lit(_SME_THRESHOLD)
    blend = (
        pl.min_horizontal(e_star, threshold) * _SME_FLOOR
        + (e_star - threshold).clip(lower_bound=0.0) * _SME_CEILING
    ) / e_star
    return pl.when(e_star > 0).then(blend).otherwise(pl.lit(_SME_FLOOR))


def _differs(actual: pl.Expr, expected: pl.Expr) -> pl.Expr:
    """``actual`` and ``expected`` differ beyond a relative float tolerance.

    A null on either side counts as a difference, so a missing input surfaces as
    a break instead of being dropped by the filter.
    """
    gap = (actual - expected).abs() > _TOL * pl.max_horizontal(expected.abs(), pl.lit(1.0))
    return gap.fill_null(True)


def _rows(frame: pl.DataFrame, *columns: str) -> list[tuple[object, ...]]:
    """The offending rows, keyed by exposure reference, for an assertion message."""
    return frame.select("exposure_reference", *columns).rows()
