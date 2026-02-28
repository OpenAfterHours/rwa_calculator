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
        from corporate import create_corporate_counterparties, save_corporate_counterparties
        from institution import create_institution_counterparties, save_institution_counterparties
        from retail import create_retail_counterparties, save_retail_counterparties
        from sovereign import create_sovereign_counterparties, save_sovereign_counterparties
        from specialised_lending import (
            create_specialised_lending_counterparties,
            save_specialised_lending_counterparties,
        )

        files = []
        for name, create_fn, save_fn in [
            ("sovereign.parquet", create_sovereign_counterparties, save_sovereign_counterparties),
            (
                "institution.parquet",
                create_institution_counterparties,
                save_institution_counterparties,
            ),
            ("corporate.parquet", create_corporate_counterparties, save_corporate_counterparties),
            ("retail.parquet", create_retail_counterparties, save_retail_counterparties),
            (
                "specialised_lending.parquet",
                create_specialised_lending_counterparties,
                save_specialised_lending_counterparties,
            ),
        ]:
            df = create_fn()
            save_fn(output_dir)
            files.append((name, len(df)))
        return files
    finally:
        sys.path.remove(str(output_dir))


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

        df = create_ratings()
        save_ratings(output_dir)
        return [("ratings.parquet", len(df))]
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
        counterparties = pl.concat(
            [
                pl.read_parquet(fixtures_dir / "counterparty" / "sovereign.parquet"),
                pl.read_parquet(fixtures_dir / "counterparty" / "institution.parquet"),
                pl.read_parquet(fixtures_dir / "counterparty" / "corporate.parquet"),
                pl.read_parquet(fixtures_dir / "counterparty" / "retail.parquet"),
                pl.read_parquet(fixtures_dir / "counterparty" / "specialised_lending.parquet"),
            ]
        )
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
