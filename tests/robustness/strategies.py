"""
Pathological input strategies — the second axis of the test estate.

Pipeline position:
    (not a pipeline stage) — Hypothesis strategies and declaration readers
    consumed by every module under ``tests/robustness/``.

Key responsibilities:
- Name the known-good portfolios this suite corrupts, by reusing
  ``tests/properties/corpus.py`` rather than inventing a second corpus.
- Read the DECLARED input domain off ``ColumnSpec.domain`` so a new bounded
  column is fuzzed by being declared, not by someone remembering.
- Generate values that are outside those domains, on both sides.

Extend, do not fork
-------------------
``tests/properties/strategies.py`` generates only WELL-FORMED portfolios — PD in
``[0.0003, 0.20]``, amounts at or above GBP 10k, no NaN, no wrong types — and its
docstring is explicit that those ranges "are the coverage this suite actually
has". That is correct for what it answers (*does Art. 123 work?*) and must not be
widened: loosening it would make the conservation and monotonicity properties
noisy rather than making them stronger. This module therefore reuses
``ExposureSpec``, ``build_bundle`` and the ``CORPUS`` portfolios for the KNOWN-GOOD
side and writes new strategies for the pathological side only.

Where the domain comes from
---------------------------
Phase 1 (``src/rwa_calc/data/column_spec.py``) landed ``NumericDomain`` /
``EnumDomain`` on ``ColumnSpec``, so generator 2 is driven off the DECLARATION —
:func:`declared_numeric_domains` and :func:`declared_enum_domains` walk the input
schemas and yield every column that carries one. There is no local restatement of
a bound anywhere in this suite, deliberately: a test that restated the domain
would share the declaration's mistakes (`.claude/LESSONS.md` B3) and would go
stale the first time a bound moved.

:func:`declared_numeric_domains` RAISES when a canary column has lost its
declaration, rather than returning a shorter list. A generator that silently
fuzzes nothing is indistinguishable from a generator that finds nothing.

References:
- docs/plans/test-space-correctness-proposal.md — Phase 1 (declare) / Phase 2 (fuzz)
- .claude/LESSONS.md B1, B3
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from hypothesis import HealthCheck, settings
from hypothesis import strategies as st

from rwa_calc.data import schemas
from rwa_calc.data.column_spec import EnumDomain, NumericDomain
from tests.properties.corpus import CORPUS
from tests.properties.strategies import portfolios

if TYPE_CHECKING:
    from rwa_calc.data.column_spec import ColumnSpec
    from tests.properties.portfolios import Portfolio

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Suppressed for the same reasons ``tests/properties/`` suppresses them: a
#: single example runs a whole pipeline (``too_slow``), the pathological
#: strategies filter on shapes that are actually reachable (``filter_too_much``),
#: and a generated portfolio is a large value by construction
#: (``data_too_large``).
_SUPPRESSED = (HealthCheck.too_slow, HealthCheck.filter_too_much, HealthCheck.data_too_large)

#: How hard every property in this suite searches. Applied as an EXPLICIT
#: decorator on each ``@given`` rather than through a registered Hypothesis
#: profile, because profiles are process-global and a ``conftest.py`` is imported
#: during collection whether or not its tests are selected — registering
#: ``"dev"`` / ``"thorough"`` here would rebind the property suite's profiles of
#: the same names and silently change ITS coverage in the dev loop. See
#: ``tests/robustness/conftest.py``.
#:
#: ``RWA_ROBUSTNESS_PROFILE=thorough`` raises the budget from 10 to 250; the
#: nightly workflow sets it. The determinism settings are the property suite's,
#: for the reasons it documents and which are load-bearing in both places:
#: ``derandomize=True`` so the same command explores the same pathologies on
#: every machine (a nightly failure reproduces from the command alone, with no
#: seed hand-off), and ``database=None`` so neither the runtime nor the explored
#: set depends on local state — this suite's value rests on both being stated
#: honestly.
SEARCH_EXAMPLES: int = int(
    os.environ.get(
        "RWA_ROBUSTNESS_MAX_EXAMPLES",
        "250" if os.environ.get("RWA_ROBUSTNESS_PROFILE") == "thorough" else "10",
    )
)

SEARCH_SETTINGS = settings(
    max_examples=SEARCH_EXAMPLES,
    deadline=None,
    derandomize=True,
    database=None,
    suppress_health_check=_SUPPRESSED,
)

#: ``RawDataBundle`` frame field -> its input schema. Mirrors the mapping in
#: ``contracts/edges.py::_raw_table_edges``, restricted to the tables a credit-risk
#: portfolio built through ``tests/properties/portfolios.py`` actually populates.
#: CCR / SFT / securitisation tables have their own bundles and their own
#: fixtures, and corrupting a table the base portfolio does not carry would
#: generate examples that inject nothing.
TABLE_SCHEMAS: dict[str, dict[str, ColumnSpec]] = {
    "facilities": schemas.FACILITY_SCHEMA,
    "loans": schemas.LOAN_SCHEMA,
    "contingents": schemas.CONTINGENTS_SCHEMA,
    "counterparties": schemas.COUNTERPARTY_SCHEMA,
    "collateral": schemas.COLLATERAL_SCHEMA,
    "guarantees": schemas.GUARANTEE_SCHEMA,
    "provisions": schemas.PROVISION_SCHEMA,
    "ratings": schemas.RATINGS_SCHEMA,
    "specialised_lending": schemas.SPECIALISED_LENDING_SCHEMA,
}

#: Which source :func:`declared_enum_domains` last read — ``"ColumnSpec.domain"``
#: once Phase 1's categorical half lands, ``"COLUMN_VALUE_CONSTRAINTS"`` until
#: then. Reported by ``test_null_and_enum.py`` so a run states its own provenance
#: rather than leaving a reader to infer it.
ENUM_DOMAIN_SOURCE: str = "<not yet read>"

#: Columns whose declaration MUST still carry a domain. Not a restatement of the
#: bounds — only of the fact that a bound exists. These four are the columns the
#: measured evidence table in the proposal is built on, so a run in which they
#: are undeclared is a run that cannot reproduce the finding this suite exists
#: for. Anchored to the declaration, never to a hand-written value.
_DOMAIN_CANARIES: frozenset[tuple[str, str]] = frozenset(
    {("ratings", "pd"), ("loans", "lgd"), ("facilities", "ccf_modelled"), ("ratings", "cqs")}
)

#: How a ratio column is recognised from its declared domain: bounded on BOTH
#: sides, inside [-1, 2]. That covers ``pd`` [0, 1], ``lgd`` [0, 1.25],
#: ``ccf_modelled`` [0, 1.5] and ``delta`` [-1, 1], and excludes ``cqs`` (1-6),
#: the maturity columns and every money amount — the columns where multiplying
#: by 100 is a scale error rather than a unit error.
_RATIO_LOWER_FLOOR = -1.0
_RATIO_UPPER_CEILING = 2.0

#: Ratio columns whose declared domain is deliberately UNBOUNDED above, so the
#: rule cannot see them. ``ltv`` and its siblings are banded upward by CRR
#: Art. 125/126 and PS1/26 Art. 124C without being capped — negative equity puts
#: real exposures above 100% — so the declaration states only a lower bound.
#: They are still ratios and a x100 feed error still reaches them.
_UNBOUNDED_RATIO_COLUMNS: frozenset[tuple[str, str]] = frozenset(
    {
        ("loans", "ltv"),
        ("collateral", "property_ltv"),
        ("collateral", "prior_charge_ltv"),
        ("collateral", "rental_to_interest_ratio"),
    }
)

#: The scale errors a real feed makes: percent supplied where a fraction is
#: wanted, and a fraction supplied where a percent is wanted. Both directions,
#: because they fail in OPPOSITE ways — see ``test_unit_scale.py``.
UNIT_SCALE_FACTORS: tuple[float, ...] = (100.0, 0.01)

#: Garbage strings a categorical column receives from a real feed. Case and
#: whitespace variants are included because a feed that round-trips through
#: Excel or a CSV export produces exactly these, and because a validator that
#: lower-cases but does not strip accepts one and rejects the other.
ENUM_GARBAGE: tuple[str, ...] = (
    "",
    " ",
    "UNKNOWN",
    "n/a",
    "NULL",
    "-",
    "0",
    "corporate ",
    " corporate",
    "Corporate",
    "CORPORATE",
    "corp orate",
)


# ---------------------------------------------------------------------------
# Declaration readers
# ---------------------------------------------------------------------------


def declared_numeric_domains() -> tuple[tuple[str, str, NumericDomain], ...]:
    """Every ``(table, column, domain)`` in the input schemas with a numeric domain.

    Raises:
        AssertionError: when a canary column has lost its declaration. A
            generator that quietly fuzzes fewer columns than it did yesterday
            reports "no defects found" for the wrong reason.
    """
    found = tuple(
        (table, column, spec.domain)
        for table, schema in TABLE_SCHEMAS.items()
        for column, spec in schema.items()
        if isinstance(spec.domain, NumericDomain)
    )
    declared = {(table, column) for table, column, _ in found}
    missing = sorted(_DOMAIN_CANARIES - declared)
    if missing:
        raise AssertionError(
            f"columns {missing} no longer declare a NumericDomain in data/schemas.py. "
            "The out-of-domain generator is driven off the declaration, so this is "
            "not a smaller test run — it is a silently disarmed one."
        )
    return found


def declared_enum_domains() -> tuple[tuple[str, str, EnumDomain], ...]:
    """Every ``(table, column, domain)`` in the input schemas with an enum domain.

    Prefers ``ColumnSpec.domain``; falls back to the free-standing
    ``COLUMN_VALUE_CONSTRAINTS`` registry when no column declares one yet.

    The fallback is not a local restatement — it is the registry the categorical
    half of the input gate reads today. Phase 1's ``EnumDomain`` is documented as
    subsuming it, and only the NUMERIC half of that migration has landed on this
    branch; when the categorical half lands, this function returns the
    declarations and the fallback goes cold on its own. Which source was used is
    recorded on :data:`ENUM_DOMAIN_SOURCE` so a test run can say so out loud.
    """
    global ENUM_DOMAIN_SOURCE  # noqa: PLW0603 — one observable fact about this run
    found = tuple(
        (table, column, spec.domain)
        for table, schema in TABLE_SCHEMAS.items()
        for column, spec in schema.items()
        if isinstance(spec.domain, EnumDomain)
    )
    if found:
        ENUM_DOMAIN_SOURCE = "ColumnSpec.domain"
        return found

    from rwa_calc.data.schemas import COLUMN_VALUE_CONSTRAINTS

    fallback = tuple(
        (
            table,
            column,
            EnumDomain(reason="derived from COLUMN_VALUE_CONSTRAINTS", values=values),
        )
        for table, columns in COLUMN_VALUE_CONSTRAINTS.items()
        if table in TABLE_SCHEMAS
        for column, values in columns.items()
        if column in TABLE_SCHEMAS[table]
    )
    if not fallback:
        raise AssertionError(
            "no EnumDomain is declared on any input schema AND "
            "COLUMN_VALUE_CONSTRAINTS is empty for every table this suite "
            "corrupts; the unknown-enum generator would fuzz nothing"
        )
    ENUM_DOMAIN_SOURCE = "COLUMN_VALUE_CONSTRAINTS"
    return fallback


def ratio_columns() -> tuple[tuple[str, str], ...]:
    """The ``(table, column)`` pairs a x100 / /100 unit error can reach.

    Derived from the declared domain (see :data:`_RATIO_UPPER_CEILING`) plus the
    deliberately-unbounded ratios in :data:`_UNBOUNDED_RATIO_COLUMNS`.
    """
    derived = {
        (table, column)
        for table, column, domain in declared_numeric_domains()
        if domain.lower is not None
        and domain.upper is not None
        and domain.lower >= _RATIO_LOWER_FLOOR
        and domain.upper <= _RATIO_UPPER_CEILING
    }
    present = {
        (table, column)
        for table, column in _UNBOUNDED_RATIO_COLUMNS
        if column in TABLE_SCHEMAS[table]
    }
    return tuple(sorted(derived | present))


def out_of_domain_values(domain: NumericDomain) -> tuple[float, ...]:
    """Values just outside ``domain``, one per bounded side.

    Chosen adjacent to the bound rather than absurdly far from it. A validator
    that rejects ``1e30`` but accepts ``1.0000001`` on a ``[0, 1]`` domain is
    the shape a real feed produces — a rounding or units slip, not a corrupt
    file — and an absurd probe would report it as covered.
    """
    values: list[float] = []
    if domain.lower is not None:
        values.append(domain.lower - 1.0 if domain.lower_closed else domain.lower)
    if domain.upper is not None:
        values.append(domain.upper + 1.0 if domain.upper_closed else domain.upper)
    return tuple(values)


# ---------------------------------------------------------------------------
# Portfolio strategies
# ---------------------------------------------------------------------------


def corpus_portfolios() -> st.SearchStrategy[Portfolio]:
    """A known-good portfolio drawn from the property suite's own corpus.

    Reused rather than rebuilt: these portfolios are the shapes the estate has
    already agreed are well-formed, so a failure under corruption is
    unambiguously about the corruption.
    """
    return st.sampled_from(sorted(CORPUS)).map(lambda name: CORPUS[name])


def base_portfolios(max_size: int = 4) -> st.SearchStrategy[Portfolio]:
    """A known-good portfolio: a corpus member, or a freshly generated one."""
    return st.one_of(corpus_portfolios(), portfolios(min_size=1, max_size=max_size))


def injectable_tables() -> st.SearchStrategy[str]:
    """One of the input tables this suite knows how to corrupt."""
    return st.sampled_from(sorted(TABLE_SCHEMAS))


def enum_garbage() -> st.SearchStrategy[str]:
    """One of the garbage strings a categorical column receives from a real feed."""
    return st.sampled_from(ENUM_GARBAGE)
