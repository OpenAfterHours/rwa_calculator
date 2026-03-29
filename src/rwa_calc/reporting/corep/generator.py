"""
COREP template generator for credit risk reporting.

Pipeline position:
    CalculationResponse -> COREPGenerator -> COREPTemplateBundle -> Excel

Key responsibilities:
- Transform exposure-level results into COREP-formatted DataFrames
- Generate C 07.00 (SA), C 08.01 (IRB totals), C 08.02 (IRB PD grades)
- Aggregate by exposure class with correct CRM split logic
- Compute exposure-weighted averages for IRB parameters

Why: COREP templates are the regulatory reporting format mandated by
the PRA for quarterly capital adequacy returns. The calculator has
all the data; this module reshapes it into the fixed template layout.

References:
- Regulation (EU) 2021/451, Annex I/II
- CRR Art. 111-134 (SA), Art. 142-191 (IRB)
- PRA PS1/26 (Basel 3.1 reporting amendments)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.reporting.corep.templates import (
    IRB_EXPOSURE_CLASS_ROWS,
    PD_BANDS,
    SA_EXPOSURE_CLASS_ROWS,
    SA_RISK_WEIGHT_BANDS,
)

if TYPE_CHECKING:
    from rwa_calc.api.export import ExportResult
    from rwa_calc.api.models import CalculationResponse

logger = logging.getLogger(__name__)


# =============================================================================
# COREP TEMPLATE BUNDLE
# =============================================================================


@dataclass(frozen=True)
class COREPTemplateBundle:
    """
    Bundle of generated COREP template DataFrames.

    Each attribute is an eager DataFrame representing one filled-in
    COREP template, ready for Excel rendering.

    Attributes:
        c07_00: C 07.00 — CR SA (one row per SA exposure class)
        c08_01: C 08.01 — CR IRB totals (one row per IRB exposure class)
        c08_02: C 08.02 — CR IRB by PD grade (rows = class x PD band)
        c07_rw_breakdown: C 07.00 risk weight breakdown (exposure by RW band)
        framework: Regulatory framework used ("CRR" or "BASEL_3_1")
        errors: Any issues encountered during generation
    """

    c07_00: pl.DataFrame
    c08_01: pl.DataFrame
    c08_02: pl.DataFrame
    c07_rw_breakdown: pl.DataFrame
    framework: str = "CRR"
    errors: list[str] = field(default_factory=list)


# =============================================================================
# COREP GENERATOR
# =============================================================================


class COREPGenerator:
    """
    Generates COREP credit risk templates from RWA calculation results.

    Reads from the CalculationResponse's cached parquet files and produces
    COREP-formatted DataFrames for C 07.00 (SA), C 08.01 (IRB totals),
    and C 08.02 (IRB PD grade breakdown).

    Usage:
        generator = COREPGenerator()
        bundle = generator.generate(response)
        bundle = generator.generate_from_lazyframe(results_lf, framework="CRR")
    """

    def generate(self, response: CalculationResponse) -> COREPTemplateBundle:
        """
        Generate all COREP templates from a CalculationResponse.

        Args:
            response: CalculationResponse with cached parquet results

        Returns:
            COREPTemplateBundle with all three templates
        """
        results_lf = response.scan_results()
        return self.generate_from_lazyframe(results_lf, framework=response.framework)

    def generate_from_lazyframe(
        self,
        results: pl.LazyFrame,
        *,
        framework: str = "CRR",
    ) -> COREPTemplateBundle:
        """
        Generate all COREP templates from a results LazyFrame.

        This is the primary entry point for direct pipeline integration
        (bypassing CalculationResponse). Useful for testing.

        Args:
            results: Combined results LazyFrame with all approaches
            framework: Regulatory framework ("CRR" or "BASEL_3_1")

        Returns:
            COREPTemplateBundle with all three templates
        """
        errors: list[str] = []

        c07 = self._generate_c07(results, errors)
        c07_rw = self._generate_c07_rw_breakdown(results, errors)
        c08_01 = self._generate_c08_01(results, errors)
        c08_02 = self._generate_c08_02(results, errors)

        return COREPTemplateBundle(
            c07_00=c07,
            c08_01=c08_01,
            c08_02=c08_02,
            c07_rw_breakdown=c07_rw,
            framework=framework,
            errors=errors,
        )

    def export_to_excel(
        self,
        bundle: COREPTemplateBundle,
        output_path: Path,
    ) -> ExportResult:
        """
        Write COREP templates to a multi-sheet Excel workbook.

        Creates sheets: "C 07.00", "C 07.00 RW Breakdown",
        "C 08.01", "C 08.02".

        Args:
            bundle: COREPTemplateBundle with generated templates
            output_path: Path for the .xlsx output file

        Returns:
            ExportResult with written file path and row count

        Raises:
            ModuleNotFoundError: If xlsxwriter is not installed
        """
        from rwa_calc.api.export import ExportResult

        try:
            import xlsxwriter  # noqa: F401
        except ModuleNotFoundError:
            msg = "COREP Excel export requires 'xlsxwriter'. Install with: uv add xlsxwriter"
            raise ModuleNotFoundError(msg) from None

        output_path.parent.mkdir(parents=True, exist_ok=True)
        total_rows = 0

        import xlsxwriter as xw

        workbook = xw.Workbook(str(output_path))
        try:
            # C 07.00 — SA credit risk
            if len(bundle.c07_00) > 0:
                bundle.c07_00.write_excel(
                    workbook=workbook,
                    worksheet="C 07.00",
                    autofit=True,
                )
                total_rows += len(bundle.c07_00)

            # C 07.00 RW Breakdown
            if len(bundle.c07_rw_breakdown) > 0:
                bundle.c07_rw_breakdown.write_excel(
                    workbook=workbook,
                    worksheet="C 07.00 RW Breakdown",
                    autofit=True,
                )
                total_rows += len(bundle.c07_rw_breakdown)

            # C 08.01 — IRB totals
            if len(bundle.c08_01) > 0:
                bundle.c08_01.write_excel(
                    workbook=workbook,
                    worksheet="C 08.01",
                    autofit=True,
                )
                total_rows += len(bundle.c08_01)

            # C 08.02 — IRB PD grade breakdown
            if len(bundle.c08_02) > 0:
                bundle.c08_02.write_excel(
                    workbook=workbook,
                    worksheet="C 08.02",
                    autofit=True,
                )
                total_rows += len(bundle.c08_02)
        finally:
            workbook.close()

        logger.info("COREP templates written to %s (%d rows)", output_path, total_rows)

        return ExportResult(
            format="corep_excel",
            files=[output_path],
            row_count=total_rows,
        )

    # =========================================================================
    # C 07.00 — CR SA
    # =========================================================================

    def _generate_c07(
        self,
        results: pl.LazyFrame,
        errors: list[str],
    ) -> pl.DataFrame:
        """
        Generate C 07.00 SA credit risk template.

        One row per SA exposure class with key aggregate measures:
        original exposure, provisions, net exposure, CRM adjustments,
        adjusted exposure, and RWA.
        """
        cols = _available_columns(results)

        # Filter to SA approach only
        sa = _filter_by_approach(results, "standardised", cols)

        # Resolve column names with fallbacks
        ead_col = _pick(cols, "ead_final", "final_ead", "ead")
        rwa_col = _pick(cols, "rwa_final", "final_rwa", "rwa_post_factor", "rwa")

        if ead_col is None or rwa_col is None:
            errors.append("C07: Missing EAD or RWA columns in results")
            return _empty_c07()

        # Build aggregation expressions
        agg_exprs: list[pl.Expr] = [
            # 010: Original exposure pre conversion factors
            _sum_cols_agg(cols, "drawn_amount", "undrawn_amount").alias("original_exposure_010"),
            # 020: Value adjustments and provisions
            _sum_cols_agg(cols, "scra_provision_amount", "gcra_provision_amount").alias(
                "provisions_020"
            ),
            # 070: Exposure value post CCF (EAD)
            pl.col(ead_col).sum().alias("exposure_value_070"),
            # 080: Risk weighted exposure amount
            pl.col(rwa_col).sum().alias("rwea_080"),
            # Exposure count
            pl.len().alias("exposure_count"),
        ]

        # 040: Funded CRM (collateral)
        if "collateral_adjusted_value" in cols:
            agg_exprs.append(pl.col("collateral_adjusted_value").sum().alias("funded_crm_040"))

        # 050: Unfunded CRM (guarantees)
        if "guaranteed_portion" in cols:
            agg_exprs.append(pl.col("guaranteed_portion").sum().alias("unfunded_crm_050"))

        # 090: With ECAI credit assessment
        if "sa_cqs" in cols:
            agg_exprs.append(
                pl.col(rwa_col)
                .filter(pl.col("sa_cqs").is_not_null() & (pl.col("sa_cqs") > 0))
                .sum()
                .alias("rwea_ecai_090")
            )

        # Group by exposure class
        ec_col = _pick(cols, "exposure_class")
        if ec_col is None:
            errors.append("C07: Missing exposure_class column")
            return _empty_c07()

        agg_df = sa.group_by(ec_col).agg(agg_exprs).collect()

        if len(agg_df) == 0:
            return _empty_c07()

        # Compute derived columns, handling optional CRM columns
        agg_cols = set(agg_df.columns)
        funded = (
            pl.col("funded_crm_040").fill_null(0.0) if "funded_crm_040" in agg_cols else pl.lit(0.0)
        )
        unfunded = (
            pl.col("unfunded_crm_050").fill_null(0.0)
            if "unfunded_crm_050" in agg_cols
            else pl.lit(0.0)
        )

        agg_df = agg_df.with_columns(
            # 030: Net exposure = original - provisions
            (pl.col("original_exposure_010") - pl.col("provisions_020").fill_null(0.0)).alias(
                "net_exposure_030"
            ),
            # 060: Net exposure after CRM
            (
                pl.col("original_exposure_010")
                - pl.col("provisions_020").fill_null(0.0)
                - funded
                - unfunded
            ).alias("net_after_crm_060"),
        )

        # Map to COREP row structure
        return _map_to_corep_rows(agg_df, ec_col, SA_EXPOSURE_CLASS_ROWS, template="C 07.00")

    # =========================================================================
    # C 07.00 — Risk Weight Breakdown
    # =========================================================================

    def _generate_c07_rw_breakdown(
        self,
        results: pl.LazyFrame,
        errors: list[str],
    ) -> pl.DataFrame:
        """
        Generate C 07.00 risk weight band breakdown.

        Pivots SA exposure value by risk weight into the standard
        regulatory bands (0%, 20%, 35%, 50%, 75%, 100%, 150%, 250%).
        """
        cols = _available_columns(results)
        sa = _filter_by_approach(results, "standardised", cols)

        ead_col = _pick(cols, "ead_final", "final_ead", "ead")
        rw_col = _pick(cols, "risk_weight", "sa_final_risk_weight")
        ec_col = _pick(cols, "exposure_class")

        if ead_col is None or rw_col is None or ec_col is None:
            errors.append("C07 RW: Missing EAD, risk_weight, or exposure_class columns")
            return pl.DataFrame()

        # Assign each exposure to a risk weight band
        band_expr = pl.lit("Other")
        for rw_value, label in reversed(SA_RISK_WEIGHT_BANDS):
            band_expr = (
                pl.when(pl.col(rw_col).round(4) == round(rw_value, 4))
                .then(pl.lit(label))
                .otherwise(band_expr)
            )

        sa_banded = sa.with_columns(band_expr.alias("rw_band"))

        # Pivot: rows = exposure class, columns = risk weight bands
        pivot_df = (
            sa_banded.group_by([ec_col, "rw_band"])
            .agg(pl.col(ead_col).sum().alias("exposure_value"))
            .collect()
            .pivot(on="rw_band", index=ec_col, values="exposure_value")
            .fill_null(0.0)
        )

        # Ensure all standard RW band columns exist
        all_band_labels = [label for _, label in SA_RISK_WEIGHT_BANDS] + ["Other"]
        for label in all_band_labels:
            if label not in pivot_df.columns:
                pivot_df = pivot_df.with_columns(pl.lit(0.0).alias(label))

        # Reorder columns: exposure_class first, then bands in order
        ordered_cols = [ec_col] + [label for _, label in SA_RISK_WEIGHT_BANDS] + ["Other"]
        existing_ordered = [c for c in ordered_cols if c in pivot_df.columns]
        pivot_df = pivot_df.select(existing_ordered)

        # Map to COREP rows
        return _map_to_corep_rows(pivot_df, ec_col, SA_EXPOSURE_CLASS_ROWS, template="C 07.00 RW")

    # =========================================================================
    # C 08.01 — CR IRB Totals
    # =========================================================================

    def _generate_c08_01(
        self,
        results: pl.LazyFrame,
        errors: list[str],
    ) -> pl.DataFrame:
        """
        Generate C 08.01 IRB totals template.

        One row per IRB exposure class with exposure-weighted averages
        for PD, LGD, maturity, plus totals for EAD, RWA, and EL.
        """
        cols = _available_columns(results)

        # Filter to IRB approaches (F-IRB and A-IRB)
        irb = _filter_by_irb_approach(results, cols)

        ead_col = _pick(cols, "ead_final", "final_ead", "ead")
        rwa_col = _pick(cols, "rwa_final", "final_rwa", "rwa_post_factor", "rwa")
        ec_col = _pick(cols, "exposure_class")

        if ead_col is None or rwa_col is None or ec_col is None:
            errors.append("C08.01: Missing EAD, RWA, or exposure_class columns")
            return _empty_c08_01()

        # Build aggregation expressions
        agg_exprs: list[pl.Expr] = [
            # 020: Original exposure
            _sum_cols_agg(cols, "drawn_amount", "undrawn_amount").alias("original_exposure_020"),
            # 030: Provisions
            _sum_cols_agg(cols, "scra_provision_amount", "gcra_provision_amount").alias(
                "provisions_030"
            ),
            # 040: EAD
            pl.col(ead_col).sum().alias("ead_040"),
            # 070: RWEA
            pl.col(rwa_col).sum().alias("rwea_070"),
            # 100: Number of obligors
            pl.len().alias("exposure_count"),
        ]

        # 010: Exposure-weighted average PD
        if "irb_pd_floored" in cols:
            agg_exprs.extend(
                [
                    (pl.col("irb_pd_floored") * pl.col(ead_col)).sum().alias("_pd_x_ead"),
                ]
            )

        # 050: Exposure-weighted average LGD
        lgd_col = _pick(cols, "irb_lgd_floored", "irb_lgd_original")
        if lgd_col is not None:
            agg_exprs.append(
                (pl.col(lgd_col) * pl.col(ead_col)).sum().alias("_lgd_x_ead"),
            )

        # 060: Exposure-weighted average maturity
        if "irb_maturity_m" in cols:
            agg_exprs.append(
                (pl.col("irb_maturity_m") * pl.col(ead_col)).sum().alias("_m_x_ead"),
            )

        # 080: Expected loss
        if "irb_expected_loss" in cols:
            agg_exprs.append(pl.col("irb_expected_loss").sum().alias("el_080"))

        # 090: Provisions allocated
        if "provision_held" in cols:
            agg_exprs.append(pl.col("provision_held").sum().alias("provisions_allocated_090"))

        # 110: EL shortfall / excess
        if "el_shortfall" in cols:
            agg_exprs.append(pl.col("el_shortfall").sum().alias("_el_shortfall"))
        if "el_excess" in cols:
            agg_exprs.append(pl.col("el_excess").sum().alias("_el_excess"))

        # Obligor count (distinct counterparties)
        if "counterparty_reference" in cols:
            agg_exprs.append(pl.col("counterparty_reference").n_unique().alias("obligor_count_100"))

        # Group by exposure class
        agg_df = irb.group_by(ec_col).agg(agg_exprs).collect()

        # Compute weighted averages
        derived_cols: list[pl.Expr] = []
        total_ead = pl.col("ead_040")

        if "_pd_x_ead" in agg_df.columns:
            derived_cols.append(
                pl.when(total_ead > 0)
                .then(pl.col("_pd_x_ead") / total_ead)
                .otherwise(0.0)
                .alias("weighted_pd_010")
            )

        if "_lgd_x_ead" in agg_df.columns:
            derived_cols.append(
                pl.when(total_ead > 0)
                .then(pl.col("_lgd_x_ead") / total_ead)
                .otherwise(0.0)
                .alias("weighted_lgd_050")
            )

        if "_m_x_ead" in agg_df.columns:
            derived_cols.append(
                pl.when(total_ead > 0)
                .then(pl.col("_m_x_ead") / total_ead)
                .otherwise(0.0)
                .alias("weighted_maturity_060")
            )

        if "_el_shortfall" in agg_df.columns and "_el_excess" in agg_df.columns:
            derived_cols.append(
                (pl.col("_el_excess") - pl.col("_el_shortfall")).alias("el_net_110")
            )
        elif "_el_shortfall" in agg_df.columns:
            derived_cols.append((-pl.col("_el_shortfall")).alias("el_net_110"))
        elif "_el_excess" in agg_df.columns:
            derived_cols.append(pl.col("_el_excess").alias("el_net_110"))

        if derived_cols:
            agg_df = agg_df.with_columns(derived_cols)

        # Drop intermediate columns
        drop_cols = [c for c in agg_df.columns if c.startswith("_")]
        if drop_cols:
            agg_df = agg_df.drop(drop_cols)

        # Map to COREP rows
        return _map_to_corep_rows(agg_df, ec_col, IRB_EXPOSURE_CLASS_ROWS, template="C 08.01")

    # =========================================================================
    # C 08.02 — CR IRB by PD Grade
    # =========================================================================

    def _generate_c08_02(
        self,
        results: pl.LazyFrame,
        errors: list[str],
    ) -> pl.DataFrame:
        """
        Generate C 08.02 IRB PD grade breakdown template.

        Rows = exposure class x PD band. Same columns as C 08.01
        but disaggregated by obligor PD grade for granular reporting.
        """
        cols = _available_columns(results)

        irb = _filter_by_irb_approach(results, cols)

        ead_col = _pick(cols, "ead_final", "final_ead", "ead")
        rwa_col = _pick(cols, "rwa_final", "final_rwa", "rwa_post_factor", "rwa")
        ec_col = _pick(cols, "exposure_class")
        pd_col = _pick(cols, "irb_pd_floored", "irb_pd_original")

        if ead_col is None or rwa_col is None or ec_col is None:
            errors.append("C08.02: Missing required columns")
            return pl.DataFrame()

        if pd_col is None:
            errors.append("C08.02: No PD column available — skipping PD grade breakdown")
            return pl.DataFrame()

        # Assign PD bands
        band_expr = pl.lit("Unassigned")
        for lower, upper, label in reversed(PD_BANDS):
            band_expr = (
                pl.when((pl.col(pd_col) >= lower) & (pl.col(pd_col) < upper))
                .then(pl.lit(label))
                .otherwise(band_expr)
            )

        irb_banded = irb.with_columns(band_expr.alias("pd_band"))

        # Build aggregation expressions (same as C 08.01)
        agg_exprs: list[pl.Expr] = [
            _sum_cols_agg(cols, "drawn_amount", "undrawn_amount").alias("original_exposure_020"),
            pl.col(ead_col).sum().alias("ead_040"),
            pl.col(rwa_col).sum().alias("rwea_070"),
            pl.len().alias("exposure_count"),
        ]

        # Weighted PD
        agg_exprs.append(
            (pl.col(pd_col) * pl.col(ead_col)).sum().alias("_pd_x_ead"),
        )

        # Weighted LGD
        lgd_col = _pick(cols, "irb_lgd_floored", "irb_lgd_original")
        if lgd_col is not None:
            agg_exprs.append(
                (pl.col(lgd_col) * pl.col(ead_col)).sum().alias("_lgd_x_ead"),
            )

        # Weighted maturity
        if "irb_maturity_m" in cols:
            agg_exprs.append(
                (pl.col("irb_maturity_m") * pl.col(ead_col)).sum().alias("_m_x_ead"),
            )

        # Expected loss
        if "irb_expected_loss" in cols:
            agg_exprs.append(pl.col("irb_expected_loss").sum().alias("el_080"))

        # Obligor count
        if "counterparty_reference" in cols:
            agg_exprs.append(pl.col("counterparty_reference").n_unique().alias("obligor_count_100"))

        # Group by exposure class AND PD band
        agg_df = irb_banded.group_by([ec_col, "pd_band"]).agg(agg_exprs).collect()

        # Compute weighted averages
        derived_cols: list[pl.Expr] = []
        total_ead = pl.col("ead_040")

        derived_cols.append(
            pl.when(total_ead > 0)
            .then(pl.col("_pd_x_ead") / total_ead)
            .otherwise(0.0)
            .alias("weighted_pd_010")
        )

        if "_lgd_x_ead" in agg_df.columns:
            derived_cols.append(
                pl.when(total_ead > 0)
                .then(pl.col("_lgd_x_ead") / total_ead)
                .otherwise(0.0)
                .alias("weighted_lgd_050")
            )

        if "_m_x_ead" in agg_df.columns:
            derived_cols.append(
                pl.when(total_ead > 0)
                .then(pl.col("_m_x_ead") / total_ead)
                .otherwise(0.0)
                .alias("weighted_maturity_060")
            )

        if derived_cols:
            agg_df = agg_df.with_columns(derived_cols)

        # Drop intermediate columns
        drop_cols = [c for c in agg_df.columns if c.startswith("_")]
        if drop_cols:
            agg_df = agg_df.drop(drop_cols)

        # Sort by exposure class then PD band order
        band_labels = [label for _, _, label in PD_BANDS] + ["Unassigned"]
        band_order = {label: i for i, label in enumerate(band_labels)}

        agg_df = agg_df.with_columns(
            pl.col("pd_band")
            .replace_strict(band_order, default=len(band_labels))
            .alias("_sort_order")
        )
        agg_df = agg_df.sort([ec_col, "_sort_order"]).drop("_sort_order")

        # Map exposure class to COREP row references
        row_map = {v: ref for v, (ref, _) in IRB_EXPOSURE_CLASS_ROWS.items()}
        name_map = {v: name for v, (_, name) in IRB_EXPOSURE_CLASS_ROWS.items()}

        agg_df = agg_df.with_columns(
            [
                pl.col(ec_col).replace_strict(row_map, default="9999").alias("row_ref"),
                pl.col(ec_col)
                .replace_strict(name_map, default=pl.col(ec_col))
                .alias("exposure_class_name"),
            ]
        )

        return agg_df


# =============================================================================
# PRIVATE HELPERS
# =============================================================================


def _available_columns(lf: pl.LazyFrame) -> set[str]:
    """Get the set of column names in a LazyFrame without collecting."""
    return set(lf.collect_schema().names())


def _pick(cols: set[str], *candidates: str) -> str | None:
    """Return the first column name from candidates that exists in cols."""
    for c in candidates:
        if c in cols:
            return c
    return None


def _sum_cols_agg(cols: set[str], *col_names: str) -> pl.Expr:
    """
    Sum multiple columns and aggregate for group_by context.

    Computes (col_a + col_b + ...).sum() for use inside .agg().
    Missing columns are skipped; returns pl.lit(0.0) if none exist.
    """
    present = [c for c in col_names if c in cols]
    if not present:
        return pl.lit(0.0)
    if len(present) == 1:
        return pl.col(present[0]).fill_null(0.0).sum()
    # Sum multiple columns per-row then aggregate
    row_sum = pl.col(present[0]).fill_null(0.0)
    for c in present[1:]:
        row_sum = row_sum + pl.col(c).fill_null(0.0)
    return row_sum.sum()


def _filter_by_approach(
    results: pl.LazyFrame,
    approach_value: str,
    cols: set[str],
) -> pl.LazyFrame:
    """Filter results to a specific approach_applied value."""
    approach_col = _pick(cols, "approach_applied")
    if approach_col is None:
        return results.filter(pl.lit(False))
    return results.filter(pl.col(approach_col) == approach_value)


def _filter_by_irb_approach(
    results: pl.LazyFrame,
    cols: set[str],
) -> pl.LazyFrame:
    """Filter results to IRB approaches (F-IRB, A-IRB, slotting)."""
    approach_col = _pick(cols, "approach_applied")
    if approach_col is None:
        return results.filter(pl.lit(False))
    return results.filter(
        pl.col(approach_col).is_in(["foundation_irb", "advanced_irb", "slotting"])
    )


def _map_to_corep_rows(
    df: pl.DataFrame,
    ec_col: str,
    row_mapping: dict[str, tuple[str, str]],
    *,
    template: str,
) -> pl.DataFrame:
    """
    Map exposure class values to COREP row references and names.

    Adds row_ref and exposure_class_name columns, computes a total row,
    and sorts by row reference.
    """
    if len(df) == 0:
        return df

    # Map to COREP references
    row_ref_map = {v: ref for v, (ref, _) in row_mapping.items()}
    name_map = {v: name for v, (_, name) in row_mapping.items()}

    df = df.with_columns(
        [
            pl.col(ec_col).replace_strict(row_ref_map, default="9999").alias("row_ref"),
            pl.col(ec_col)
            .replace_strict(name_map, default=pl.col(ec_col))
            .alias("exposure_class_name"),
        ]
    )

    # Compute total row
    numeric_cols = [
        c
        for c in df.columns
        if c not in {ec_col, "row_ref", "exposure_class_name"}
        and df[c].dtype in (pl.Float64, pl.Int64, pl.UInt32, pl.Int32, pl.Float32)
    ]

    if numeric_cols:
        total_values: dict[str, object] = {
            ec_col: "TOTAL",
            "row_ref": "0000",
            "exposure_class_name": "Total",
        }
        for col_name in numeric_cols:
            # For weighted averages (PD, LGD, maturity), the total row
            # should be re-computed from the EAD-weighted components, not
            # summed. But since we dropped the intermediates, we sum the
            # absolute measures and leave weighted averages as None.
            if col_name.startswith("weighted_"):
                total_values[col_name] = None
            else:
                total_values[col_name] = df[col_name].sum()

        total_row = pl.DataFrame(
            [total_values],
            schema={c: df[c].dtype for c in df.columns},
        )
        df = pl.concat([total_row, df], how="diagonal_relaxed")

    # Sort by row reference
    df = df.sort("row_ref")

    # Reorder: row_ref, exposure_class_name first, then rest
    ordered = ["row_ref", "exposure_class_name"] + [
        c for c in df.columns if c not in {"row_ref", "exposure_class_name"}
    ]
    return df.select(ordered)


def _empty_c07() -> pl.DataFrame:
    """Return an empty C 07.00 DataFrame with correct schema."""
    return pl.DataFrame(
        schema={
            "row_ref": pl.String,
            "exposure_class_name": pl.String,
            "exposure_class": pl.String,
            "original_exposure_010": pl.Float64,
            "provisions_020": pl.Float64,
            "net_exposure_030": pl.Float64,
            "funded_crm_040": pl.Float64,
            "unfunded_crm_050": pl.Float64,
            "net_after_crm_060": pl.Float64,
            "exposure_value_070": pl.Float64,
            "rwea_080": pl.Float64,
        }
    )


def _empty_c08_01() -> pl.DataFrame:
    """Return an empty C 08.01 DataFrame with correct schema."""
    return pl.DataFrame(
        schema={
            "row_ref": pl.String,
            "exposure_class_name": pl.String,
            "exposure_class": pl.String,
            "weighted_pd_010": pl.Float64,
            "original_exposure_020": pl.Float64,
            "provisions_030": pl.Float64,
            "ead_040": pl.Float64,
            "weighted_lgd_050": pl.Float64,
            "weighted_maturity_060": pl.Float64,
            "rwea_070": pl.Float64,
            "el_080": pl.Float64,
        }
    )
