"""
Column discovery helpers shared by the COREP and Pillar 3 generators.

Pipeline position:
    OutputAggregator -> {COREPGenerator, Pillar3Generator}
    (called at generator entry to resolve which result columns are present)

Key responsibilities:
- Materialise the set of available column names from a LazyFrame schema
  without collecting the frame
- Resolve the first present column name from an ordered candidate list
  (pipeline results expose the same quantity under historical aliases,
  e.g. ``ead_final`` / ``final_ead`` / ``ead``)
- Resolve the own-approach (un-floored) RWEA carrier every COREP RWEA figure
  reads (``own_rwea``), and alias it across frames (``with_own_rwea_as``)

References:
- Regulation (EU) 2021/451, Annex I/II (COREP templates)
- CRR Part 8 (Pillar 3 disclosure templates)
- PRA PS1/26 Appendix 1, Art. 92(2A) / 92(3) (output floor; U-TREA)
"""

from __future__ import annotations

import polars as pl
from watchfire import cites

from rwa_calc.engine.materialise import materialise_frame

#: The un-floored own-approach RWEA the output floor seals beside ``rwa_final``
#: (``engine/aggregator/_floor.py``); absent wherever the floor never ran.
OWN_RWEA_CARRIER = "rwa_pre_floor"

#: exposure_type values inside the on/off-balance-sheet credit-risk gross scope
#: (CRR Art. 111 SA / Art. 166 IRB). CCR / settlement legs sit outside it.
_CREDIT_BS_TYPES: tuple[str, ...] = ("loan", "contingent", "facility_undrawn")


def available_columns(lf: pl.LazyFrame) -> set[str]:
    """Get the set of column names in a LazyFrame without collecting."""
    return set(lf.collect_schema().names())


def materialise_results(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Read the results frame once, returning an in-memory LazyFrame over it.

    The generators issue ~30 ``.collect()`` calls between them — one per
    template population — and each one re-executes the whole source plan. When
    that source is the production ``pl.scan_parquet`` handle
    (``ResultsSource.scan_results``), those are ~30 re-reads of the results
    parquet plus ~30 re-runs of the overlapping filter work. Collecting once at
    the generator boundary turns every one of them into an in-memory scan.

    Number-neutral by construction: an in-memory ``LazyFrame`` carries the same
    schema, dtypes and values as the scan it replaces, so every template asks
    the same questions of the same data and gets the same answers.

    Idempotent in cost, not just in value: a full materialise of the results
    parquet costs 69-84 ms, while re-materialising an already-eager frame costs
    0.099-0.129 ms. So a caller that has already materialised — ``api/rest.py``
    shares one collect between the COREP and Pillar 3 generators — pays
    essentially nothing for the generator's own call.

    What it is worth, at the two scales measured. These are different
    denominators, not a trend — quote the one that matches what you are timing:

    - **Generator time, 37,443 rows, live IRB populations:** SA 1.35x, IRB
      1.44x (interleaved A/B).
    - **Whole reporting pass, 373,928 rows, SA-only portfolio:** 15,633 ->
      6,802 ms, **2.3x — an upper bound, never quote it bare.** That book has
      no ``model_permissions``, so ~20 IRB templates each pay a full source
      scan and then aggregate an EMPTY population. That maximises the
      scan-to-work ratio, and the scan is exactly what this function removes.
      The 2.3x is portfolio SHAPE, not scale; a book with live IRB populations
      does more work per template and shows a smaller ratio.
    - **Whole ``validate_submission``, 37,443 rows:** 1.17x — it adds ~808
      rules of evaluation that this function does not touch.

    Small-n on a loaded box: same-state wall times varied 6.2-13.8 s and peak
    RSS 97-764 MB across six reps, so single-rep figures carry a wide band.

    Two costs to weigh before reusing this anywhere else:

    - It defeats projection pushdown, so it PAYS only where many consumers read
      the frame. It is applied to the current results frame (~30 template
      populations) and deliberately NOT to ``previous_period_results``, which
      only C 08.04 and CR8 read — there the full collect measured 3-5x slower
      than leaving the scan lazy.
    - **Memory: no measurable cost at 100k.** Peak RSS 4,168 MB before vs
      4,283 MB after — +115 MB, inside the noise, since the two arms differed
      by ~1 GB in pre-reporting RSS from GC timing alone. Headroom on the
      7.8 GB reference box: 3.63 GB vs 3.52 GB. At 37k the delta measured
      +122-184 MB on a 71.5 MB frame; treat that as a **measured observation
      that does NOT scale**, not a per-byte multiplier. Extrapolating it
      linearly to 100k predicts +1.2-1.8 GB, which the direct measurement
      above refutes by an order of magnitude — that extrapolation was made
      twice here and was wrong both times.
    """
    return materialise_frame(lf)


def pick(cols: set[str], *candidates: str) -> str | None:
    """Return the first column name from *candidates* that exists in *cols*."""
    for c in candidates:
        if c in cols:
            return c
    return None


@cites("PS1/26, paragraph 92")
def own_rwea(cols: set[str], *fallbacks: str) -> str | None:
    """Resolve the column carrying the own-approach RWEA a COREP template reports.

    The output floor is an entity-level maximum — PS1/26 Art. 92(2A)(a): "TREA =
    max {U-TREA; x . S-TREA + OF-ADJ}" — and Art. 92(3)(a) makes the credit-risk
    part of U-TREA the risk-weighted exposure amounts "calculated in accordance
    with Title II of Part Three", i.e. what each exposure's own approach produces.
    Nothing allocates the floor to an exposure, a class or a template row: Annex
    II reports it once, in OF 02.00 row 0010 column 0030, and defines OF 08.01
    col 0260 as col 0251 adjusted for the three Art. 153(5A) / 154(4A) amounts
    (cols 0252-0254) only.

    The engine, however, spreads a binding floor's shortfall pro rata over
    ``rwa_final`` on every floor-eligible leg (``engine/aggregator/_floor.py``)
    and keeps the un-floored figure on ``rwa_pre_floor``. So this returns
    ``rwa_pre_floor`` wherever the ledger seals it (the floor ran), and otherwise
    the first of *fallbacks* present — ``rwa_final`` and its historical aliases —
    because a ledger with no ``rwa_pre_floor`` (CRR, or a Basel 3.1 entity outside
    the floor's scope) had no floor applied, and there ``rwa_final`` IS the
    own-approach figure. Each call site keeps its own fallback ladder.

    The resolution is by PRESENCE, so it rests on ``rwa_pre_floor`` staying a
    conditional column of ``AGGREGATOR_EXIT_EDGE`` (``contracts/edges.py``:
    ``required=False, inject=False`` — sealed only where the floor ran). Were the
    edge ever to inject it as a typed null, every ledger would carry it and every
    COREP RWEA would sum nulls.

    Every COREP RWEA read goes through here; ``tests/contracts/
    test_corep_rwea_carrier.py`` fails a template that binds ``rwa_final``
    directly.
    """
    return pick(cols, OWN_RWEA_CARRIER, *fallbacks)


def with_own_rwea_as(
    frame: pl.LazyFrame, cols: set[str], target: str | None, *fallbacks: str
) -> pl.LazyFrame:
    """Write *frame*'s own-approach RWEA (:func:`own_rwea`) under the name *target*.

    For a template that binds a carrier name resolved from ONE frame and reads it
    from ANOTHER — C 08.04 resolves its RWEA column from the current period and
    reads the opening from the prior period's frame. The two periods need not
    seal the same carriers: a prior the floor never ran on (a CRR prior at the
    1 January 2027 transition, an entity outside the floor's scope) has no
    ``rwa_pre_floor``, and a prior the floor did run on carries the add-on in
    ``rwa_final``. Either way the opening must be the prior's OWN own-approach
    figure, written under whatever column the current spec binds. The frame is
    returned unchanged when *target* is None, when *frame* carries none of the
    candidates, or when its own carrier already is *target*.
    """
    source = own_rwea(cols, *fallbacks)
    if target is None or source is None or source == target:
        return frame
    return frame.with_columns(pl.col(source).alias(target))


#: Raw gross-exposure carrier -> its floored ``reporting_gross_*`` twin. The
#: aggregator seals the floored twins (raw amount clipped at 0) so a negative
#: on-balance netting deposit (CRR Art. 195/219) never makes a gross-exposure
#: template cell report a negative figure (CRR Art. 111 SA / Art. 166 IRB).
_GROSS_CARRIER_MAP: dict[str, str] = {
    "drawn_amount": "reporting_gross_drawn",
    "interest": "reporting_gross_interest",
    "nominal_amount": "reporting_gross_nominal",
    "undrawn_amount": "reporting_gross_undrawn",
}


def gross_carrier(cols: set[str], raw_name: str) -> str:
    """Resolve a raw gross carrier to its floored ``reporting_gross_*`` twin.

    Prefers the sealed floored twin when present in *cols*, else falls back to
    the raw column name (older synthetic unit frames that predate the seal).
    A name with no floored twin is returned unchanged.
    """
    floored = _GROSS_CARRIER_MAP.get(raw_name)
    return floored if floored is not None and floored in cols else raw_name


def gross_carriers(cols: set[str], *raw_names: str) -> tuple[str, ...]:
    """Resolve a group of raw gross carriers to their floored twins.

    Order-preserving convenience over :func:`gross_carrier` for the
    ``SafeSum`` gross-exposure cells (COREP C 07/C 08).
    """
    return tuple(gross_carrier(cols, name) for name in raw_names)


def ensure_gross_side_carriers(frame: pl.LazyFrame, cols: set[str]) -> pl.LazyFrame:
    """Derive ``reporting_gross_on_bs`` / ``reporting_gross_off_bs`` when absent.

    The sealed aggregator exit carries the two per-side gross carriers; a
    synthetic / legacy frame (a unit fixture, or any pre-seal input a generator
    is handed directly) gets the SAME mirror derivation here so the on/off-BS
    gross template cells can reference the columns unconditionally. The rule is
    the aggregator's row rule verbatim (``_add_reporting_projection``) and must
    stay identical to ``tests/fixtures/recon_ledger.with_reporting_ledger``:

    - with ``exposure_type`` -> the sealed rule: an on-balance credit type
      (loan/contingent/facility_undrawn) whose drawn AND interest are both null
      stays null (unknown stays unknown), else its on-side is the floored drawn +
      interest (a null component counts as 0); the off-side is a contingent's
      floored nominal, a facility_undrawn's floored undrawn (once), a loan's true
      0.0, else null (CCR / settlement legs — outside the gross scope).
    - without ``exposure_type`` (a legacy synthetic frame) -> the on-side sum
      applies unconditionally, and the off-side is
      ``max_horizontal(clip0(nominal), clip0(undrawn))``: legacy frames can carry
      the off-BS gross in either raw column (the retired C 08.03 fallback read
      nominal; the retired C 07/C 08.01 formula read undrawn) and pipeline
      facility_undrawn rows alias the two, so ``max_horizontal`` counts an aliased
      pair exactly once and reproduces both retired behaviours; all-null -> null.

    A null component inside a known side counts as 0 (never fill Float nulls to
    0.0 beyond that — anti-conservative). Called at each generator's LazyFrame
    entry, before the templates collect.
    """
    exprs: list[pl.Expr] = []

    def _col_or_null(name: str) -> pl.Expr:
        return pl.col(name) if name in cols else pl.lit(None, dtype=pl.Float64)

    drawn = _col_or_null("drawn_amount")
    interest = _col_or_null("interest")
    nominal = _col_or_null("nominal_amount")
    undrawn = _col_or_null("undrawn_amount")
    on_bs_sum = (
        pl.when(drawn.is_null() & interest.is_null())
        .then(pl.lit(None, dtype=pl.Float64))
        .otherwise(
            drawn.clip(lower_bound=0.0).fill_null(0.0)
            + interest.clip(lower_bound=0.0).fill_null(0.0)
        )
    )
    if "reporting_gross_on_bs" not in cols:
        if "exposure_type" in cols:
            exprs.append(
                # "facility" is a legacy off-BS alias the discriminators still
                # recognise (Wave 3 amendment); it joins the credit types here.
                pl.when(pl.col("exposure_type").is_in([*_CREDIT_BS_TYPES, "facility"]))
                .then(on_bs_sum)
                .otherwise(pl.lit(None, dtype=pl.Float64))
                .alias("reporting_gross_on_bs")
            )
        else:
            exprs.append(on_bs_sum.alias("reporting_gross_on_bs"))
    if "reporting_gross_off_bs" not in cols:
        if "exposure_type" in cols:
            exprs.append(
                pl.when(pl.col("exposure_type") == "contingent")
                .then(nominal.clip(lower_bound=0.0))
                .when(pl.col("exposure_type") == "facility_undrawn")
                .then(undrawn.clip(lower_bound=0.0))
                .when(pl.col("exposure_type") == "loan")
                .then(pl.lit(0.0))
                # Legacy "facility" alias: its off-BS carrier home is ambiguous
                # (nominal or undrawn), so max_horizontal counts the aliased
                # pair exactly once. All-null -> null.
                .when(pl.col("exposure_type") == "facility")
                .then(
                    pl.max_horizontal(nominal.clip(lower_bound=0.0), undrawn.clip(lower_bound=0.0))
                )
                .otherwise(pl.lit(None, dtype=pl.Float64))
                .alias("reporting_gross_off_bs")
            )
        else:
            exprs.append(
                pl.max_horizontal(
                    nominal.clip(lower_bound=0.0), undrawn.clip(lower_bound=0.0)
                ).alias("reporting_gross_off_bs")
            )
    return frame.with_columns(exprs) if exprs else frame
