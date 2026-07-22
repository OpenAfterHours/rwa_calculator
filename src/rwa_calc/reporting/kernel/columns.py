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

References:
- Regulation (EU) 2021/451, Annex I/II (COREP templates)
- CRR Part 8 (Pillar 3 disclosure templates)
"""

from __future__ import annotations

import polars as pl

#: exposure_type values inside the on/off-balance-sheet credit-risk gross scope
#: (CRR Art. 111 SA / Art. 166 IRB). CCR / settlement legs sit outside it.
_CREDIT_BS_TYPES: tuple[str, ...] = ("loan", "contingent", "facility_undrawn")


def available_columns(lf: pl.LazyFrame) -> set[str]:
    """Get the set of column names in a LazyFrame without collecting."""
    return set(lf.collect_schema().names())


def pick(cols: set[str], *candidates: str) -> str | None:
    """Return the first column name from *candidates* that exists in *cols*."""
    for c in candidates:
        if c in cols:
            return c
    return None


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
