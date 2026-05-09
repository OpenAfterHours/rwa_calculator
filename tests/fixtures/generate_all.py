"""
Master script to generate all test fixture parquet files.

This script runs all fixture generators in the correct order to produce
a complete set of test data for RWA calculator acceptance testing.

Usage:
    uv run python tests/fixtures/generate_all.py
"""

import sys
from dataclasses import dataclass
from pathlib import Path

import polars as pl


def main() -> None:
    """Entry point for master fixture generation."""
    fixtures_dir = Path(__file__).parent
    results = generate_all_fixtures(fixtures_dir)
    print_master_report(results, fixtures_dir)
    print_data_integrity_check(fixtures_dir)


@dataclass
class FixtureGroupResult:
    """Result of a fixture group generation."""

    group_name: str
    output_dir: Path
    file_count: int
    total_records: int
    files: list[tuple[str, int]]  # (filename, record_count)


def generate_all_fixtures(fixtures_dir: Path) -> list[FixtureGroupResult]:
    """
    Generate all fixture parquet files.

    Args:
        fixtures_dir: Root fixtures directory.

    Returns:
        List of generation results for each fixture group.
    """
    results = []

    # Import and run each generator
    generators = [
        ("Counterparties", "counterparty", _generate_counterparties),
        ("Mappings", "mapping", _generate_mappings),
        ("Ratings", "ratings", _generate_ratings),
        ("Exposures", "exposures", _generate_exposures),
        ("Collateral", "collateral", _generate_collateral),
        ("Guarantees", "guarantee", _generate_guarantees),
        ("Provisions", "provision", _generate_provisions),
        ("FX Rates", "fx_rates", _generate_fx_rates),
        ("Model Permissions", "model_permissions", _generate_model_permissions),
        ("P1.114 (null book_code / null country_code)", "p1_114", _generate_p1114),
        ("P1.112 (non-UK unrated PSE sovereign-derived RW)", "p1_112", _generate_p1112),
        ("P1.98 (subordinated corporate A-IRB LGD floor fallback)", "p1_98", _generate_p198),
        (
            "P1.99 (CRR Art. 120(2) Table 4 short-term rated institution RW)",
            "p1_99",
            _generate_p199,
        ),
        ("P1.117 (B31 HVCRE slotting short-maturity subgrades)", "p1_117", _generate_p1117),
        ("P1.125 (classifier FSE-column-missing warning CLS007)", "p1_125", _generate_p1125),
        (
            "P1.121 (CRR Art. 121(3) unrated institution short-term 20% RW)",
            "p1_121",
            _generate_p1121,
        ),
        ("P1.124 (CRR Art. 237(2)(a) guarantee maturity ineligibility)", "p1_124", _generate_p1124),
        (
            "P1.126 (classifier null-revenue conservative-large default CLS008)",
            "p1_126",
            _generate_p1126,
        ),
        ("P1.156 (PSM guarantor LGD seniority/FSE-aware Art. 236/161)", "p1_156", _generate_p1156),
        (
            "P1.157 (PSM 'no better than direct' PD floor Art. 160(4))",
            "p1_157",
            _generate_p1157,
        ),
        (
            "P1.182 (long-established PE/VC 250% vs 400% business-age split)",
            "p1_182",
            _generate_p1182,
        ),
        (
            "P1.100 (CRR Art. 137 ECA MEIP score 2 → 20% sovereign RW)",
            "p1_100",
            _generate_p1100,
        ),
        (
            "P1.101 (CRR Art. 226(1) non-daily revaluation haircut adjustment)",
            "p1_101",
            _generate_p1101,
        ),
        (
            "P1.104 (CRR Art. 239(1) FCSM binary maturity-mismatch eligibility)",
            "p1_104_art_239_1_fcsm_maturity",
            _generate_p1104,
        ),
        (
            "P1.181 (CRR Art. 126(2)(d) commercial RE proportion split)",
            "p1_181",
            _generate_p1181,
        ),
        (
            "P1.105 (B31 Art. 120(2B) Table 4A short-term institution ECAI RW)",
            "p1_105",
            _generate_p1105,
        ),
        (
            "P1.103 (B31 Art. 122(3) Table 6A short-term corporate ECAI RW)",
            "p1_103",
            _generate_p1103,
        ),
        (
            "P1.128 (B31 Art. 121(4) SCRA short-term trade finance exception)",
            "p1_128",
            _generate_p1128,
        ),
        (
            "P1.186 (CRR Art. 224(2)(a) FX haircut H_fx default liquidation scaling)",
            "p1_186",
            _generate_p1186,
        ),
        (
            "P1.96 (CRR Art. 197/207(2) covered-bond collateral haircut routing)",
            "p1_96",
            _generate_p196,
        ),
    ]

    for group_name, subdir, generator_func in generators:
        output_dir = fixtures_dir / subdir
        try:
            files = generator_func(output_dir)
            total_records = sum(count for _, count in files)
            results.append(
                FixtureGroupResult(
                    group_name=group_name,
                    output_dir=output_dir,
                    file_count=len(files),
                    total_records=total_records,
                    files=files,
                )
            )
        except Exception as e:
            print(f"ERROR generating {group_name}: {e}")
            raise

    return results


def _generate_counterparties(output_dir: Path) -> list[tuple[str, int]]:
    """Generate counterparty fixtures."""
    sys.path.insert(0, str(output_dir))
    try:
        from corporate import create_corporate_counterparties
        from institution import create_institution_counterparties
        from retail import create_retail_counterparties
        from sovereign import create_sovereign_counterparties
        from specialised_lending import create_specialised_lending_counterparties

        frames = [
            create_sovereign_counterparties(),
            create_institution_counterparties(),
            create_corporate_counterparties(),
            create_retail_counterparties(),
            create_specialised_lending_counterparties(),
        ]

        combined = pl.concat(frames)
        combined.write_parquet(output_dir / "counterparties.parquet")
        return [("counterparties.parquet", len(combined))]
    finally:
        sys.path.remove(str(output_dir))
        # Clear cached module to avoid collision with ratings/specialised_lending.py
        sys.modules.pop("specialised_lending", None)


def _generate_mappings(output_dir: Path) -> list[tuple[str, int]]:
    """Generate mapping fixtures."""
    sys.path.insert(0, str(output_dir))
    try:
        from lending_mapping import create_lending_mappings, save_lending_mappings
        from org_mapping import create_org_mappings, save_org_mappings

        files = []
        for name, create_fn, save_fn in [
            ("org_mapping.parquet", create_org_mappings, save_org_mappings),
            ("lending_mapping.parquet", create_lending_mappings, save_lending_mappings),
        ]:
            df = create_fn()
            save_fn(output_dir)
            files.append((name, len(df)))
        return files
    finally:
        sys.path.remove(str(output_dir))


def _generate_ratings(output_dir: Path) -> list[tuple[str, int]]:
    """Generate ratings fixtures."""
    sys.path.insert(0, str(output_dir))
    try:
        from ratings import create_ratings, save_ratings
        from specialised_lending import (
            create_specialised_lending_data,
            save_specialised_lending_data,
        )

        files = []
        for name, create_fn, save_fn in [
            ("ratings.parquet", create_ratings, save_ratings),
            (
                "specialised_lending.parquet",
                create_specialised_lending_data,
                save_specialised_lending_data,
            ),
        ]:
            df = create_fn()
            save_fn(output_dir)
            files.append((name, len(df)))
        return files
    finally:
        sys.path.remove(str(output_dir))


def _generate_exposures(output_dir: Path) -> list[tuple[str, int]]:
    """Generate exposure fixtures."""
    sys.path.insert(0, str(output_dir))
    try:
        from contingents import create_contingents, save_contingents
        from facilities import create_facilities, save_facilities
        from facility_mapping import create_facility_mappings, save_facility_mappings
        from loans import create_loans, save_loans

        files = []
        for name, create_fn, save_fn in [
            ("facilities.parquet", create_facilities, save_facilities),
            ("loans.parquet", create_loans, save_loans),
            ("contingents.parquet", create_contingents, save_contingents),
            ("facility_mapping.parquet", create_facility_mappings, save_facility_mappings),
        ]:
            df = create_fn()
            save_fn(output_dir)
            files.append((name, len(df)))
        return files
    finally:
        sys.path.remove(str(output_dir))


def _generate_collateral(output_dir: Path) -> list[tuple[str, int]]:
    """Generate collateral fixtures."""
    sys.path.insert(0, str(output_dir))
    try:
        from collateral import create_collateral, save_collateral

        df = create_collateral()
        save_collateral(output_dir)
        return [("collateral.parquet", len(df))]
    finally:
        sys.path.remove(str(output_dir))


def _generate_guarantees(output_dir: Path) -> list[tuple[str, int]]:
    """Generate guarantee fixtures."""
    sys.path.insert(0, str(output_dir))
    try:
        from guarantee import create_guarantees, save_guarantees

        df = create_guarantees()
        save_guarantees(output_dir)
        return [("guarantee.parquet", len(df))]
    finally:
        sys.path.remove(str(output_dir))


def _generate_provisions(output_dir: Path) -> list[tuple[str, int]]:
    """Generate provision fixtures."""
    sys.path.insert(0, str(output_dir))
    try:
        from provision import create_provisions, save_provisions

        df = create_provisions()
        save_provisions(output_dir)
        return [("provision.parquet", len(df))]
    finally:
        sys.path.remove(str(output_dir))


def _generate_fx_rates(output_dir: Path) -> list[tuple[str, int]]:
    """Generate FX rates fixtures."""
    sys.path.insert(0, str(output_dir))
    try:
        from fx_rates import create_fx_rates, save_fx_rates

        df = create_fx_rates()
        save_fx_rates(output_dir)
        return [("fx_rates.parquet", len(df))]
    finally:
        sys.path.remove(str(output_dir))


def _generate_model_permissions(output_dir: Path) -> list[tuple[str, int]]:
    """Generate model permissions fixtures."""
    sys.path.insert(0, str(output_dir))
    try:
        from model_permissions import create_model_permissions, save_model_permissions

        df = create_model_permissions()
        save_model_permissions(output_dir)
        return [("model_permissions.parquet", len(df))]
    finally:
        sys.path.remove(str(output_dir))


def _generate_p1114(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.114 fixtures (null-propagation defect in model permissions filter)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_114 import save_p1114_fixtures

        saved = save_p1114_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_114", None)


def _generate_p1112(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.112 fixtures (non-UK unrated PSE sovereign-derived risk weight)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_112 import save_p1112_fixtures

        saved = save_p1112_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_112", None)


def _generate_p198(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.98 fixtures (subordinated corporate A-IRB LGD floor fallback path)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_98 import save_p198_fixtures

        saved = save_p198_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_98", None)


def _generate_p199(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.99 fixtures (CRR Art. 120(2) Table 4 short-term rated institution RW)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_99 import save_p199_fixtures

        saved = save_p199_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_99", None)


def _generate_p1117(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.117 fixtures (B31 HVCRE slotting short-maturity subgrades)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_117 import save_p1117_fixtures

        saved = save_p1117_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_117", None)


def _generate_p1126(output_dir: Path) -> list[tuple[str, int]]:
    """
    Validate P1.126 builder imports (no parquet output — Python-only builder).

    P1.126 tests null vs. non-null annual_revenue values in the counterparty
    LazyFrame to exercise the CLS008 conservative-large-corp warning under
    Basel 3.1.  Like P1.125, this is a Python-only builder: parquet round-trips
    preserve column presence but may alter null handling semantics in edge cases.
    The fixture is exercised by constructing all three named scenario bundles and
    checking schema invariants that matter to the CLS008 logic.
    """
    sys.path.insert(0, str(output_dir))
    try:
        from p1_126 import (  # noqa: F401
            make_scenario_a_bundle,
            make_scenario_b_bundle,
            make_scenario_c_bundle,
        )

        # Smoke-check: all three bundles must construct without raising.
        bundle_a = make_scenario_a_bundle()
        bundle_b = make_scenario_b_bundle()
        bundle_c = make_scenario_c_bundle()

        # Invariant 1: annual_revenue column is present in all three scenarios
        # (it is always present — null in A/C, non-null in B).
        for label, bundle in [("A", bundle_a), ("B", bundle_b), ("C", bundle_c)]:
            cp_cols = bundle.counterparty_lookup.counterparties.collect_schema().names()
            if "annual_revenue" not in cp_cols:
                raise AssertionError(f"Scenario {label}: annual_revenue column must be present")

        # Invariant 2: Scenario A counterparty has null annual_revenue.
        cp_a = bundle_a.counterparty_lookup.counterparties.collect()
        if cp_a["annual_revenue"][0] is not None:
            raise AssertionError("Scenario A: annual_revenue must be null")

        # Invariant 3: Scenario B counterparty has non-null annual_revenue > 440m threshold.
        cp_b = bundle_b.counterparty_lookup.counterparties.collect()
        rev_b = cp_b["annual_revenue"][0]
        if rev_b is None or rev_b <= 440_000_000.0:
            raise AssertionError(f"Scenario B: annual_revenue must be > GBP 440m (got {rev_b})")

        # Invariant 4: Scenario C counterparty has null annual_revenue (same data as A).
        cp_c = bundle_c.counterparty_lookup.counterparties.collect()
        if cp_c["annual_revenue"][0] is not None:
            raise AssertionError("Scenario C: annual_revenue must be null")

        # Invariant 5: is_financial_sector_entity is present and False in all scenarios
        # (so FSE restriction does not interfere with the CLS008 path).
        for label, cp_df in [("A", cp_a), ("B", cp_b), ("C", cp_c)]:
            if "is_financial_sector_entity" not in cp_df.columns:
                raise AssertionError(
                    f"Scenario {label}: is_financial_sector_entity must be present"
                )
            if cp_df["is_financial_sector_entity"][0] is not False:
                raise AssertionError(f"Scenario {label}: is_financial_sector_entity must be False")

        # Invariant 6: model_id is present on the exposure and matches M_CORP_AIRB.
        from p1_126 import MODEL_ID  # noqa: PLC0415

        for label, bundle in [("A", bundle_a), ("B", bundle_b), ("C", bundle_c)]:
            exp_cols = bundle.exposures.collect_schema().names()
            if "model_id" not in exp_cols:
                raise AssertionError(f"Scenario {label}: model_id must be present on exposures")
            exp_df = bundle.exposures.collect()
            if exp_df["model_id"][0] != MODEL_ID:
                raise AssertionError(
                    f"Scenario {label}: model_id must be {MODEL_ID!r} "
                    f"(got {exp_df['model_id'][0]!r})"
                )

        # No parquet files written — report zero files, zero records.
        return [("(python-only builder — no parquet)", 0)]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_126", None)


def _generate_p1125(output_dir: Path) -> list[tuple[str, int]]:
    """
    Validate P1.125 builder imports (no parquet output — Python-only builder).

    P1.125 tests column-schema existence, which cannot be preserved through a
    parquet round-trip (parquet writes include all declared columns regardless of
    whether they appear in the input dict).  The fixture is a Python builder that
    constructs in-memory LazyFrames with controlled schemas.  This function
    exercises the import path and checks the three named scenario bundles can be
    constructed without error.
    """
    sys.path.insert(0, str(output_dir))
    try:
        from p1_125 import (  # noqa: F401
            make_scenario_a_bundle,
            make_scenario_b_bundle,
            make_scenario_c_bundle,
        )

        # Smoke-check: all three bundles must construct without raising.
        bundle_a = make_scenario_a_bundle()
        bundle_b = make_scenario_b_bundle()
        bundle_c = make_scenario_c_bundle()

        # Confirm the critical schema invariants.
        cp_cols_a = bundle_a.counterparty_lookup.counterparties.collect_schema().names()
        cp_cols_b = bundle_b.counterparty_lookup.counterparties.collect_schema().names()
        cp_cols_c = bundle_c.counterparty_lookup.counterparties.collect_schema().names()

        if "is_financial_sector_entity" in cp_cols_a:
            raise AssertionError("Scenario A: is_financial_sector_entity must be absent")
        if "is_financial_sector_entity" not in cp_cols_b:
            raise AssertionError("Scenario B: is_financial_sector_entity must be present")
        if "is_financial_sector_entity" in cp_cols_c:
            raise AssertionError("Scenario C: is_financial_sector_entity must be absent")

        # No parquet files written — report zero files, zero records.
        return [("(python-only builder — no parquet)", 0)]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_125", None)


def _generate_p1121(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.121 fixtures (CRR Art. 121(3) unrated institution short-term 20% RW)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_121 import save_p1121_fixtures

        saved = save_p1121_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_121", None)


def _generate_p1124(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.124 fixtures (CRR Art. 237(2)(a) guarantee maturity ineligibility)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_124 import save_p1124_fixtures

        saved = save_p1124_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_124", None)


def _generate_p1156(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.156 fixtures (PSM guarantor LGD seniority/FSE-aware Art. 236/161)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_156 import save_p1156_fixtures

        saved = save_p1156_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_156", None)


def _generate_p1157(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.157 fixtures (PSM 'no better than direct' PD floor Art. 160(4))."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_157 import save_p1157_fixtures

        saved = save_p1157_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_157", None)


def _generate_p1182(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.182 fixtures (long-established PE/VC 250% vs 400% business-age split)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_182 import save_p1182_fixtures

        saved = save_p1182_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_182", None)


def _generate_p1100(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.100 fixtures (CRR Art. 137 ECA MEIP score 2 → 20% sovereign RW)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_100 import save_p1100_fixtures

        saved = save_p1100_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_100", None)


def _generate_p1101(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.101 fixtures (CRR Art. 226(1) non-daily revaluation haircut adjustment)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_101 import save_p1101_fixtures

        saved = save_p1101_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_101", None)


def _generate_p1104(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.104 fixtures (CRR Art. 239(1) FCSM binary maturity-mismatch eligibility)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_104 import save_p1104_fixtures

        saved = save_p1104_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_104", None)


def _generate_p1181(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.181 fixtures (CRR Art. 126(2)(d) commercial RE proportion split)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_181 import save_p1181_fixtures

        saved = save_p1181_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_181", None)


def _generate_p1105(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.105 fixtures (B31 Art. 120(2B) Table 4A short-term ECAI institution RW)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_105 import save_p1105_fixtures

        saved = save_p1105_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_105", None)


def _generate_p1103(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.103 fixtures (B31 Art. 122(3) Table 6A short-term ECAI corporate RW)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_103 import save_p1103_fixtures

        saved = save_p1103_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_103", None)


def _generate_p1128(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.128 fixtures (B31 Art. 121(4) SCRA short-term trade finance exception)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_128 import save_p1128_fixtures

        saved = save_p1128_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_128", None)


def _generate_p1186(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.186 fixtures (CRR Art. 224(2)(a) FX haircut H_fx default liquidation scaling)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_186 import save_p1186_fixtures

        saved = save_p1186_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_186", None)


def _generate_p196(output_dir: Path) -> list[tuple[str, int]]:
    """Generate P1.96 fixtures (CRR Art. 197/207(2) covered-bond collateral haircut routing)."""
    sys.path.insert(0, str(output_dir))
    try:
        from p1_96 import save_p196_fixtures

        saved = save_p196_fixtures(output_dir)
        return [(f"{name}.parquet", pl.read_parquet(path).height) for name, path in saved.items()]
    finally:
        sys.path.remove(str(output_dir))
        sys.modules.pop("p1_96", None)


def print_master_report(results: list[FixtureGroupResult], fixtures_dir: Path) -> None:
    """Print master generation report."""
    print("=" * 80)
    print("RWA CALCULATOR - MASTER FIXTURE GENERATOR")
    print("=" * 80)
    print(f"Output directory: {fixtures_dir}\n")

    total_files = 0
    total_records = 0

    for result in results:
        print(f"[OK] {result.group_name}")
        for filename, count in result.files:
            print(f"     - {filename}: {count} records")
        total_files += result.file_count
        total_records += result.total_records

    print("\n" + "-" * 80)
    print("SUMMARY BY GROUP")
    print("-" * 80)

    for result in results:
        print(
            f"  {result.group_name:<20} {result.file_count:>3} files  {result.total_records:>6} records"
        )

    print("-" * 80)
    print(f"  {'TOTAL':<20} {total_files:>3} files  {total_records:>6} records")
    print("=" * 80)


def print_data_integrity_check(fixtures_dir: Path) -> None:
    """Print data integrity validation results."""
    print("\n" + "=" * 80)
    print("DATA INTEGRITY CHECK")
    print("=" * 80)

    errors = []
    warnings = []

    # Load all parquet files
    try:
        counterparties = pl.read_parquet(fixtures_dir / "counterparty" / "counterparties.parquet")
        loans = pl.read_parquet(fixtures_dir / "exposures" / "loans.parquet")
        facilities = pl.read_parquet(fixtures_dir / "exposures" / "facilities.parquet")
        contingents = pl.read_parquet(fixtures_dir / "exposures" / "contingents.parquet")
        collateral = pl.read_parquet(fixtures_dir / "collateral" / "collateral.parquet")
        guarantees = pl.read_parquet(fixtures_dir / "guarantee" / "guarantee.parquet")
        provisions = pl.read_parquet(fixtures_dir / "provision" / "provision.parquet")
        ratings = pl.read_parquet(fixtures_dir / "ratings" / "ratings.parquet")
        facility_mappings = pl.read_parquet(fixtures_dir / "exposures" / "facility_mapping.parquet")
        org_mappings = pl.read_parquet(fixtures_dir / "mapping" / "org_mapping.parquet")
        lending_mappings = pl.read_parquet(fixtures_dir / "mapping" / "lending_mapping.parquet")

        cpty_refs = set(counterparties["counterparty_reference"].to_list())

        # Check 1: All loan counterparty references exist
        loan_cpty_refs = set(loans["counterparty_reference"].to_list())
        missing_loan_cpty = loan_cpty_refs - cpty_refs
        if missing_loan_cpty:
            errors.append(f"Loans reference missing counterparties: {missing_loan_cpty}")
        else:
            print("[OK] All loan counterparty references valid")

        # Check 2: All facility counterparty references exist
        fac_cpty_refs = set(facilities["counterparty_reference"].to_list())
        missing_fac_cpty = fac_cpty_refs - cpty_refs
        if missing_fac_cpty:
            errors.append(f"Facilities reference missing counterparties: {missing_fac_cpty}")
        else:
            print("[OK] All facility counterparty references valid")

        # Check 3: All contingent counterparty references exist
        cont_cpty_refs = set(contingents["counterparty_reference"].to_list())
        missing_cont_cpty = cont_cpty_refs - cpty_refs
        if missing_cont_cpty:
            errors.append(f"Contingents reference missing counterparties: {missing_cont_cpty}")
        else:
            print("[OK] All contingent counterparty references valid")

        # Check 4: All rating counterparty references exist
        rating_cpty_refs = set(ratings["counterparty_reference"].to_list())
        missing_rating_cpty = rating_cpty_refs - cpty_refs
        if missing_rating_cpty:
            errors.append(f"Ratings reference missing counterparties: {missing_rating_cpty}")
        else:
            print("[OK] All rating counterparty references valid")

        # Check 5: Facility mappings reference valid facilities and loans
        fac_refs = set(facilities["facility_reference"].to_list())
        loan_refs = set(loans["loan_reference"].to_list())

        parent_fac_refs = set(facility_mappings["parent_facility_reference"].to_list())
        missing_parent_facs = parent_fac_refs - fac_refs
        if missing_parent_facs:
            errors.append(f"Facility mappings reference missing facilities: {missing_parent_facs}")
        else:
            print("[OK] All facility mapping parent references valid")

        # Check child references (can be facility or loan)
        child_refs = set(facility_mappings["child_reference"].to_list())
        valid_children = fac_refs | loan_refs
        missing_children = child_refs - valid_children
        if missing_children:
            warnings.append(f"Facility mappings reference unknown children: {missing_children}")
        else:
            print("[OK] All facility mapping child references valid")

        # Check 6: Org mappings reference valid counterparties
        org_parents = set(org_mappings["parent_counterparty_reference"].to_list())
        org_children = set(org_mappings["child_counterparty_reference"].to_list())
        missing_org = (org_parents | org_children) - cpty_refs
        if missing_org:
            errors.append(f"Org mappings reference missing counterparties: {missing_org}")
        else:
            print("[OK] All org mapping counterparty references valid")

        # Check 7: Lending mappings reference valid counterparties
        lending_parents = set(lending_mappings["parent_counterparty_reference"].to_list())
        lending_children = set(lending_mappings["child_counterparty_reference"].to_list())
        missing_lending = (lending_parents | lending_children) - cpty_refs
        if missing_lending:
            errors.append(f"Lending mappings reference missing counterparties: {missing_lending}")
        else:
            print("[OK] All lending mapping counterparty references valid")

        # Check 8: Collateral beneficiary references
        coll_loan_refs = set(
            collateral.filter(pl.col("beneficiary_type") == "loan")[
                "beneficiary_reference"
            ].to_list()
        )
        coll_fac_refs = set(
            collateral.filter(pl.col("beneficiary_type") == "facility")[
                "beneficiary_reference"
            ].to_list()
        )
        missing_coll_loans = coll_loan_refs - loan_refs
        missing_coll_facs = coll_fac_refs - fac_refs
        if missing_coll_loans:
            errors.append(f"Collateral references missing loans: {missing_coll_loans}")
        if missing_coll_facs:
            errors.append(f"Collateral references missing facilities: {missing_coll_facs}")
        if not missing_coll_loans and not missing_coll_facs:
            print("[OK] All collateral beneficiary references valid")

        # Check 9: Guarantee beneficiary references
        guar_loan_refs = set(
            guarantees.filter(pl.col("beneficiary_type") == "loan")[
                "beneficiary_reference"
            ].to_list()
        )
        guar_fac_refs = set(
            guarantees.filter(pl.col("beneficiary_type") == "facility")[
                "beneficiary_reference"
            ].to_list()
        )
        missing_guar_loans = guar_loan_refs - loan_refs
        missing_guar_facs = guar_fac_refs - fac_refs
        if missing_guar_loans:
            errors.append(f"Guarantees reference missing loans: {missing_guar_loans}")
        if missing_guar_facs:
            errors.append(f"Guarantees reference missing facilities: {missing_guar_facs}")
        if not missing_guar_loans and not missing_guar_facs:
            print("[OK] All guarantee beneficiary references valid")

        # Check 10: Guarantee guarantor references (should be counterparties)
        guarantor_refs = set(guarantees["guarantor"].to_list())
        missing_guarantors = guarantor_refs - cpty_refs
        if missing_guarantors:
            errors.append(f"Guarantees reference missing guarantors: {missing_guarantors}")
        else:
            print("[OK] All guarantee guarantor references valid")

        # Check 11: Provision beneficiary references
        prov_loan_refs = set(
            provisions.filter(pl.col("beneficiary_type") == "loan")[
                "beneficiary_reference"
            ].to_list()
        )
        missing_prov_loans = prov_loan_refs - loan_refs
        if missing_prov_loans:
            errors.append(f"Provisions reference missing loans: {missing_prov_loans}")
        else:
            print("[OK] All provision loan references valid")

        # Check 12: Model ID references (ratings → model_permissions)
        model_perms_path = fixtures_dir / "model_permissions" / "model_permissions.parquet"
        if model_perms_path.exists():
            model_perms = pl.read_parquet(model_perms_path)
            valid_model_ids = set(model_perms["model_id"].to_list())

            # Collect non-null model_ids from ratings
            rating_model_ids: set[str] = set()
            if "model_id" in ratings.columns:
                non_null = ratings.filter(pl.col("model_id").is_not_null())["model_id"].to_list()
                rating_model_ids.update(non_null)

            missing_model_ids = rating_model_ids - valid_model_ids
            if missing_model_ids:
                errors.append(f"Ratings reference missing model_ids: {missing_model_ids}")
            else:
                print(
                    f"[OK] All rating model_id references valid "
                    f"({len(rating_model_ids)} unique model_ids)"
                )
        else:
            print("[--] Model permissions file not found, skipping model_id check")

    except Exception as e:
        errors.append(f"Error during integrity check: {e}")

    # Print summary
    print("\n" + "-" * 80)
    if errors:
        print(f"ERRORS: {len(errors)}")
        for error in errors:
            print(f"  [X] {error}")
    if warnings:
        print(f"WARNINGS: {len(warnings)}")
        for warning in warnings:
            print(f"  [!] {warning}")
    if not errors and not warnings:
        print("All integrity checks passed!")
    print("=" * 80)


if __name__ == "__main__":
    main()
