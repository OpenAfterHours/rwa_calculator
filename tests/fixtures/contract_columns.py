"""
Pad hand-rolled calculator-branch frames with crm_exit contract columns.

Phase 3 sealed the calculators' branch input: every REQUIRED crm_exit
column is guaranteed present in production, so the SA / IRB / slotting
namespaces read contract columns directly (no presence guards). Tests
that hand-roll minimal LazyFrames and call namespace methods or
``calculate_branch`` directly must therefore carry those columns.

``pad_crm_exit_defaults`` adds the commonly-read contract columns with
production-realistic neutral values (only when missing) WITHOUT
stripping extra non-contract columns — unlike
``tests.fixtures.resolved_bundle.seal_crm_exit``, which conforms to the
full edge shape and drops calculator-internal inputs such as
``maturity`` / ``turnover_m``.

Derived pads mirror upstream stage outputs:
- ``ead_final`` falls back to a legacy ``ead`` column when present
- ``ead_gross`` mirrors ``ead_final`` (no CRM reduction)
- ``ead_for_crm`` mirrors ``ead_gross`` (pure on-balance-sheet row: the
  Art. 223(4) CCF=100% basis and the post-CCF EAD coincide)
- ``lgd_post_crm`` mirrors ``lgd`` (no collateral adjustment)

``exposure_class`` is never invented (P5.69). It is engine-derived: the
classifier writes ``ExposureClass.<X>.value`` on every row, lowercase and never
null, so no neutral default exists. Both ways of not supplying it reach a
branch production never takes, silently:

- a typed NULL takes the null branch of every exact-``.value`` gate;
- an ABSENT column takes the silent fallback of every reader that guards on
  the column's presence — at least six under ``engine/`` (measured
  2026-11-24): ``engine/supporting_factors.py`` (the Art. 501a(1)(a) class
  limb becomes ``pl.lit(True)``, so an unclassed infrastructure row collects
  the 0.75 factor a null or an ``institution`` class is denied),
  ``engine/crm/processor.py`` (the guarantor ranking drops its SA risk-weight
  density), ``engine/aggregator/_securitisation.py`` (the pool breakdown drops
  the parent class), ``engine/aggregator/_equity_prep.py`` (stamps a class of
  its own) and ``engine/aggregator/_floor.py`` /
  ``engine/aggregator/_supporting_factors.py`` (``col_or_default``: a typed
  null).

So ``pad_crm_exit_defaults`` and the branch-exit pads all REFUSE a non-empty
frame that carries no class, or a null one, rather than padding it either way;
a zero-row frame carries no class to get wrong and pads as before. The refusal
is ``require_class_on_every_row``, which the stage-output seals of
``tests/fixtures/resolved_bundle.py`` run too. ``require_exposure_class_values``
is the stronger membership check the single-exposure builders run on the frame
they hand to ``calculate_branch``; ``tests/contracts/test_harness_exposure_class_domain.py``
gates all of them.
"""

from __future__ import annotations

import polars as pl

from rwa_calc.contracts.edges import CALC_BRANCH_EDGES, seal_lenient
from rwa_calc.domain.enums import ExposureClass

#: The values the classifier can write to ``exposure_class`` — the harness domain.
EXPOSURE_CLASS_VALUES: frozenset[str] = frozenset(member.value for member in ExposureClass)

_SIMPLE_DEFAULTS: dict[str, pl.Expr] = {
    "seniority": pl.lit("senior"),
    "purchased_receivables_subtype": pl.lit(None, dtype=pl.String),
    "cp_is_financial_sector_entity": pl.lit(False),
    "is_qrre_transactor": pl.lit(False),
    "requires_fi_scalar": pl.lit(False),
    "has_one_day_maturity_floor": pl.lit(False),
    "is_defaulted": pl.lit(False),
    "beel": pl.lit(0.0),
    "is_sme": pl.lit(False),
    "is_infrastructure": pl.lit(False),
    # Null lending group preserves the counterparty fallback in the SME
    # group-key resolution; counterparty_reference is deliberately NOT
    # padded (its absence drives the SF001 warning path).
    "lending_group_reference": pl.lit(None, dtype=pl.String),
    "sme_size_metric_gbp": pl.lit(None, dtype=pl.Float64),
    "maturity_date": pl.lit(None, dtype=pl.Date),
    "effective_maturity": pl.lit(None, dtype=pl.Float64),
    "facility_termination_date": pl.lit(None, dtype=pl.Date),
    "is_revolving": pl.lit(False),
    "is_sft": pl.lit(False),
    "is_short_term_trade_lc": pl.lit(False),
    "lgd": pl.lit(None, dtype=pl.Float64),
    # Internal derived column normally produced by ``prepare_columns``; the
    # neutral null matches the no-SME derivation result (is_sme=False).
    "turnover_m": pl.lit(None, dtype=pl.Float64),
    "total_collateral_for_lgd": pl.lit(0.0),
    # CRR Art. 223(5) exposure-side volatility haircut: non-zero only on SFT
    # rows lending out a debt security, so 0.0 is the production-realistic
    # neutral for a hand-rolled lending frame (E' = E × (1 + HE) = E).
    "exposure_volatility_haircut": pl.lit(0.0),
    "crm_alloc_financial": pl.lit(0.0),
    "crm_alloc_covered_bond": pl.lit(0.0),
    "crm_alloc_receivables": pl.lit(0.0),
    "crm_alloc_real_estate": pl.lit(0.0),
    "crm_alloc_other_physical": pl.lit(0.0),
    "crm_alloc_life_insurance": pl.lit(0.0),
    "provision_allocated": pl.lit(0.0),
    "ava_amount": pl.lit(0.0),
    "other_own_funds_reductions": pl.lit(0.0),
}


def require_exposure_class_values(lf: pl.LazyFrame, where: str) -> None:
    """Refuse a hand frame any of whose rows lacks an ``ExposureClass`` value.

    The single-exposure builders run this on the frame they hand to
    ``calculate_branch`` — the frame itself, not the argument it was built
    from — so a builder that drops the column (motivating instance 1 of P5.69:
    ``calculate_single_slotting_exposure`` once did), nulls it, or carries an
    upper-case spelling (``"CORPORATE"``) or an invented class (``"RETAIL"``,
    ``"COMMERCIAL_RE"``) is refused before a calculator's exact-match gate can
    take a branch production never takes. A test that means to exercise the
    engine's case tolerance builds its frame directly with
    ``member.value.upper()`` instead.

    Stronger than ``require_class_on_every_row`` (absent or null only), which
    the pads and seals run because their callers still hand them the banked
    non-member frame literals; a builder's caller names one class, so the
    builder can require membership outright.

    Collects at most two scalars and one short column, for the same reason as
    ``require_class_on_every_row``: the refusal has to happen before the frame
    reaches the calculator.

    Raises:
        ValueError: ``lf`` has rows and either no ``exposure_class`` column, a
            null in it, or a value that is not an ``ExposureClass`` value. A
            harness defect, so it raises rather than accumulating a
            CalculationError.
    """
    require_class_on_every_row(lf, where)
    if "exposure_class" not in lf.collect_schema().names():
        return
    outside = (
        lf.filter(~pl.col("exposure_class").is_in(sorted(EXPOSURE_CLASS_VALUES)))
        .select(pl.col("exposure_class").unique().sort())
        .collect()["exposure_class"]
        .to_list()
    )
    if outside:
        msg = (
            f"{where}: exposure_class {outside!r} is not an ExposureClass value; production "
            f"writes one of {sorted(EXPOSURE_CLASS_VALUES)} — use ExposureClass.<X>.value"
        )
        raise ValueError(msg)


def require_class_on_every_row(lf: pl.LazyFrame, edge: str) -> None:
    """Refuse a non-empty hand frame whose rows carry no class.

    The guard every harness helper that lenient-seals or pads a classed edge
    runs first: the four pads here and the stage-output seals of
    ``tests/fixtures/resolved_bundle.py`` (``seal_classifier_exit``,
    ``seal_crm_exit``, ``seal_aggregator_exit`` and the summary-frame seal).
    ``exposure_class`` is required and injected on each of those edges, so the
    lenient seal would otherwise turn an unsupplied class into a typed null on
    every row. A zero-row frame carries no class to get wrong and is accepted.
    A frame is refused if ANY row is null, not only when every row is.
    ``tests/contracts/test_harness_exposure_class_domain.py`` reads every
    lenient seal under ``tests/`` and fails one on a classed edge that does not
    run this guard on the same frame first.

    Collects one scalar: a hand frame is a handful of rows, and the refusal
    has to happen before a pad or seal can null the column or leave it absent.

    Raises:
        ValueError: ``lf`` has rows and either no ``exposure_class`` column or
            a null in it. A harness defect, so it raises rather than
            accumulating a CalculationError.
    """
    if "exposure_class" in lf.collect_schema().names():
        nulls = lf.select(pl.col("exposure_class").null_count()).collect().item()
        if nulls:
            msg = f"{edge} hand frame has {nulls} row(s) with a null exposure_class"
            raise ValueError(msg)
        return
    if lf.select(pl.len()).collect().item():
        msg = f"{edge} hand frame has rows but no exposure_class column"
        raise ValueError(msg)


def pad_crm_exit_defaults(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Add missing crm_exit contract columns with neutral defaults.

    Only columns absent from the frame are added; existing columns and
    extra non-contract columns are untouched. ``approach`` is
    deliberately NOT padded — ``classify_approach`` owns its default —
    and neither is ``exposure_class``, which has no neutral value: a
    non-empty frame must say which class each row is (see the module
    docstring for why neither a null nor an absent column is safe).

    Raises:
        ValueError: a non-empty frame has no ``exposure_class`` or a null one.
    """
    require_class_on_every_row(lf, "crm_exit")
    names = set(lf.collect_schema().names())

    additions = [expr.alias(name) for name, expr in _SIMPLE_DEFAULTS.items() if name not in names]
    if additions:
        lf = lf.with_columns(additions)
    names |= {name for name in _SIMPLE_DEFAULTS if name not in names}

    derived: list[pl.Expr] = []
    if "ead_final" in names:  # noqa: SIM108 — three-way source resolution
        ead_final_src = pl.col("ead_final")
    elif "ead" in names:
        # with_columns evaluates in parallel — reference the source column,
        # not the alias created in the same pass.
        ead_final_src = pl.col("ead")
        derived.append(ead_final_src.alias("ead_final"))
    else:
        ead_final_src = pl.lit(0.0)
    if "ead_gross" in names:
        ead_for_crm_src = pl.col("ead_gross")
    else:
        derived.append(ead_final_src.alias("ead_gross"))
        ead_for_crm_src = ead_final_src
    # CRR Art. 223(4) CCF=100% CRM basis. Mirrors ead_gross: the two are equal
    # by construction on the pure on-balance-sheet rows hand frames model.
    if "ead_for_crm" not in names:
        derived.append(ead_for_crm_src.alias("ead_for_crm"))
    if "lgd_post_crm" not in names:
        derived.append(pl.col("lgd").alias("lgd_post_crm"))
    if derived:
        lf = lf.with_columns(derived)
    return lf


def pad_slotting_branch_defaults(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Pad a hand-rolled slotting ``calculate_branch`` frame.

    Adds ``approach="slotting"`` and ``exposure_class="specialised_lending"``
    on top of the generic crm_exit defaults, BEFORE delegating to
    ``pad_crm_exit_defaults`` — which pads neither and refuses a row with no
    class (it injected a typed NULL ``exposure_class`` until P5.69). Both are
    always populated in production:

    - ``approach`` — the pipeline routes pre-filtered slotting rows.
    - ``exposure_class`` — ``engine/classify/approach.py`` gates the slotting
      branch on ``exposure_class == ExposureClass.SPECIALISED_LENDING.value``,
      so a slotting row can only EXIST with that class. Verified on a real
      ``PipelineOrchestrator`` run: the golden reporting portfolio's slotting
      leg carries ``exposure_class='specialised_lending'`` alongside
      ``approach_applied='slotting'``.

    The null was silent until the CRR Art. 501a(1)(a) class gate landed
    (``engine/supporting_factors.py``), which reads ``exposure_class`` and
    correctly denies the infrastructure factor on a null. Three slotting tests
    then failed against an input shape production cannot produce — a fixture
    that cannot express the condition under test (LESSONS C11).
    """
    names = set(lf.collect_schema().names())
    additions = []
    if "approach" not in names:
        additions.append(pl.lit("slotting").alias("approach"))
    if "exposure_class" not in names:
        additions.append(pl.lit(ExposureClass.SPECIALISED_LENDING.value).alias("exposure_class"))
    if additions:
        lf = lf.with_columns(additions)
    return pad_crm_exit_defaults(lf)


def _pad_calc_branch(frame: pl.LazyFrame | pl.DataFrame, branch: str) -> pl.LazyFrame:
    """Leniently conform a hand-rolled calculator-branch frame to its edge.

    Mirrors the orchestrator's branch-exit seal shape: missing REQUIRED
    columns become typed nulls, required-with-inject optionals get their
    defaults, CONDITIONAL (inject=False) columns are preserved only when
    supplied, undeclared scratch columns are stripped.

    ``equity_type`` is appended after the seal: it is required at the
    aggregator exit but owned by the equity path — production's combined
    frame always carries it because the equity calculator returns a
    (possibly empty) results frame with the column even when the portfolio
    holds no equity. Aggregate-calling tests that pass
    ``equity_bundle=None`` need the column to come from the branch inputs.

    ``exposure_class`` is REQUIRED on every branch edge, so the seal would turn
    an unsupplied class into a typed null on every row — a state production
    never produces (P5.69). A non-empty frame must therefore carry a non-null
    class; a zero-row frame (the ``EMPTY_*`` branch stand-ins) carries no class
    to get wrong and seals as before.

    Raises:
        ValueError: a non-empty frame has no ``exposure_class`` or a null one.
    """
    lf = frame.lazy() if isinstance(frame, pl.DataFrame) else frame
    require_class_on_every_row(lf, branch)
    sealed, _missing, _lossy = seal_lenient(lf, CALC_BRANCH_EDGES[branch])
    return sealed.with_columns(pl.lit(None, dtype=pl.String).alias("equity_type"))


def pad_sa_branch(frame: pl.LazyFrame | pl.DataFrame) -> pl.LazyFrame:
    """Pad a hand-rolled SA results frame to the sa_branch edge shape."""
    return _pad_calc_branch(frame, "sa_branch")


def pad_irb_branch(frame: pl.LazyFrame | pl.DataFrame) -> pl.LazyFrame:
    """Pad a hand-rolled IRB results frame to the irb_branch edge shape."""
    return _pad_calc_branch(frame, "irb_branch")


def pad_slotting_branch(frame: pl.LazyFrame | pl.DataFrame) -> pl.LazyFrame:
    """Pad a hand-rolled slotting results frame to the slotting_branch edge shape."""
    return _pad_calc_branch(frame, "slotting_branch")
