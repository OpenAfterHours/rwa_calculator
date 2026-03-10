"""
Generate model permissions test fixtures for IRB approach testing.

The output will be saved as `model_permissions.parquet` ready to get picked up
within the wider testing process.

Model permissions define per-model IRB approvals, replacing the org-wide
IRBPermissions config with granular, data-driven approach gating. Each row
grants a specific IRB model permission for an exposure class, optionally
scoped by geography and with book code exclusions.

Why model permissions exist:
    Banks operate multiple IRB models, each approved by the regulator for
    specific exposure classes and geographies. A UK corporate PD model may
    have FIRB approval, while a separate retail model has AIRB approval.
    The classifier joins exposures to these permissions via model_id to
    determine the correct approach per-exposure.

Permission types for testing:
    - FIRB corporate model (UK-wide)
    - AIRB corporate model (UK-wide, with book code exclusion)
    - FIRB institution model (all geographies)
    - AIRB retail model (UK-wide)
    - Geography-restricted model (DE only)

Usage:
    uv run python tests/fixtures/model_permissions/model_permissions.py
"""

from dataclasses import dataclass
from pathlib import Path

import polars as pl

from rwa_calc.data.schemas import MODEL_PERMISSIONS_SCHEMA


def main() -> None:
    """Entry point for model permissions generation."""
    output_path = save_model_permissions()
    print_summary(output_path)


@dataclass(frozen=True)
class ModelPermission:
    """A model-level IRB permission."""

    model_id: str
    exposure_class: str
    approach: str
    country_codes: str | None = None
    excluded_book_codes: str | None = None

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "exposure_class": self.exposure_class,
            "approach": self.approach,
            "country_codes": self.country_codes,
            "excluded_book_codes": self.excluded_book_codes,
        }


def create_model_permissions() -> pl.DataFrame:
    """
    Create model permissions test data.

    Returns:
        pl.DataFrame: Model permissions matching MODEL_PERMISSIONS_SCHEMA
    """
    permissions = [
        *_corporate_permissions(),
        *_institution_permissions(),
        *_retail_permissions(),
        *_geography_restricted_permissions(),
    ]

    return pl.DataFrame([p.to_dict() for p in permissions], schema=MODEL_PERMISSIONS_SCHEMA)


def _corporate_permissions() -> list[ModelPermission]:
    """
    Corporate IRB model permissions.

    Covers:
        - UK_CORP_PD_01: FIRB for corporates (UK, all books)
        - UK_CORP_AIRB_01: AIRB for corporates (UK, excludes TRADE_FINANCE book)
    """
    return [
        # FIRB corporate model — approved for all UK corporate exposures
        ModelPermission(
            model_id="UK_CORP_PD_01",
            exposure_class="corporate",
            approach="foundation_irb",
            country_codes="GB",
        ),
        # AIRB corporate model — approved for UK corporates except trade finance book
        # When an exposure has this model_id + lgd, it qualifies for AIRB;
        # without lgd, it falls back to SA (unless FIRB permission also exists)
        ModelPermission(
            model_id="UK_CORP_AIRB_01",
            exposure_class="corporate",
            approach="advanced_irb",
            country_codes="GB",
            excluded_book_codes="TRADE_FINANCE",
        ),
    ]


def _institution_permissions() -> list[ModelPermission]:
    """
    Institution IRB model permissions.

    Covers:
        - INST_FIRB_01: FIRB for institutions (all geographies)
    """
    return [
        # FIRB institution model — all geographies, no exclusions
        ModelPermission(
            model_id="INST_FIRB_01",
            exposure_class="institution",
            approach="foundation_irb",
        ),
    ]


def _retail_permissions() -> list[ModelPermission]:
    """
    Retail IRB model permissions.

    Covers:
        - UK_RTL_AIRB_01: AIRB for retail mortgages (UK)
        - UK_RTL_AIRB_02: AIRB for qualifying revolving retail (UK)
        - UK_RTL_AIRB_03: AIRB for other retail (UK)
    """
    return [
        # AIRB retail mortgage model
        ModelPermission(
            model_id="UK_RTL_AIRB_01",
            exposure_class="retail_mortgage",
            approach="advanced_irb",
            country_codes="GB",
        ),
        # AIRB qualifying revolving retail model
        ModelPermission(
            model_id="UK_RTL_AIRB_02",
            exposure_class="retail_qrre",
            approach="advanced_irb",
            country_codes="GB",
        ),
        # AIRB other retail model
        ModelPermission(
            model_id="UK_RTL_AIRB_03",
            exposure_class="retail_other",
            approach="advanced_irb",
            country_codes="GB",
        ),
    ]


def _geography_restricted_permissions() -> list[ModelPermission]:
    """
    Geography-restricted model permissions for testing geography gating.

    Covers:
        - DE_CORP_PD_01: FIRB for German corporates only
    """
    return [
        # German corporate FIRB model — only applies to DE exposures
        # Exercises the geography filter: exposures with cp_country_code != DE
        # won't match this permission and fall back to SA
        ModelPermission(
            model_id="DE_CORP_PD_01",
            exposure_class="corporate",
            approach="foundation_irb",
            country_codes="DE",
        ),
    ]


def save_model_permissions(output_dir: Path | None = None) -> Path:
    """
    Create and save model permissions to parquet format.

    Args:
        output_dir: Directory to save the parquet file.
                    Defaults to fixtures/model_permissions directory.

    Returns:
        Path: Path to the saved parquet file.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent

    df = create_model_permissions()
    output_path = output_dir / "model_permissions.parquet"
    df.write_parquet(output_path)

    return output_path


def print_summary(output_path: Path) -> None:
    """Print generation summary."""
    df = pl.read_parquet(output_path)

    print(f"Saved model permissions to: {output_path}")
    print(f"\nCreated {len(df)} model permissions:")

    print("\nBy exposure class:")
    class_counts = df.group_by("exposure_class").len().sort("exposure_class")
    for row in class_counts.iter_rows(named=True):
        print(f"  {row['exposure_class']}: {row['len']}")

    print("\nBy approach:")
    approach_counts = df.group_by("approach").len().sort("approach")
    for row in approach_counts.iter_rows(named=True):
        print(f"  {row['approach']}: {row['len']}")

    print("\nModel details:")
    for row in df.iter_rows(named=True):
        geo = row["country_codes"] or "all"
        excl = row["excluded_book_codes"] or "none"
        print(
            f"  {row['model_id']}: {row['approach']} for {row['exposure_class']} "
            f"(geo={geo}, excl={excl})"
        )


if __name__ == "__main__":
    main()
