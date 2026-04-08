"""
Fixture referential integrity tests.

Validates that all cross-references between fixture parquet files are consistent:
- Collateral beneficiary references → loans or facilities
- Guarantee beneficiary references → loans or facilities
- Guarantee guarantor references → counterparties
- Provision beneficiary references → loans
- Loan/facility/contingent counterparty references → counterparties
- Rating counterparty references → counterparties
- Rating model_id references → model_permissions
- Facility mapping parent → facilities, child → facilities or loans
- Org/lending mapping references → counterparties

These tests prevent regression of P5.2 fixture referential integrity issues.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def _load_parquet(subdir: str, filename: str) -> pl.DataFrame:
    """Load a parquet file from the fixtures directory."""
    path = FIXTURES_DIR / subdir / filename
    if not path.exists():
        pytest.skip(f"Fixture file not found: {path} (run generate_all.py first)")
    return pl.read_parquet(path)


@pytest.fixture(scope="module")
def counterparties() -> pl.DataFrame:
    return _load_parquet("counterparty", "counterparties.parquet")


@pytest.fixture(scope="module")
def loans() -> pl.DataFrame:
    return _load_parquet("exposures", "loans.parquet")


@pytest.fixture(scope="module")
def facilities() -> pl.DataFrame:
    return _load_parquet("exposures", "facilities.parquet")


@pytest.fixture(scope="module")
def contingents() -> pl.DataFrame:
    return _load_parquet("exposures", "contingents.parquet")


@pytest.fixture(scope="module")
def collateral() -> pl.DataFrame:
    return _load_parquet("collateral", "collateral.parquet")


@pytest.fixture(scope="module")
def guarantees() -> pl.DataFrame:
    return _load_parquet("guarantee", "guarantee.parquet")


@pytest.fixture(scope="module")
def provisions() -> pl.DataFrame:
    return _load_parquet("provision", "provision.parquet")


@pytest.fixture(scope="module")
def ratings() -> pl.DataFrame:
    return _load_parquet("ratings", "ratings.parquet")


@pytest.fixture(scope="module")
def facility_mappings() -> pl.DataFrame:
    return _load_parquet("exposures", "facility_mapping.parquet")


@pytest.fixture(scope="module")
def org_mappings() -> pl.DataFrame:
    return _load_parquet("mapping", "org_mapping.parquet")


@pytest.fixture(scope="module")
def lending_mappings() -> pl.DataFrame:
    return _load_parquet("mapping", "lending_mapping.parquet")


@pytest.fixture(scope="module")
def cpty_refs(counterparties: pl.DataFrame) -> set[str]:
    return set(counterparties["counterparty_reference"].to_list())


@pytest.fixture(scope="module")
def loan_refs(loans: pl.DataFrame) -> set[str]:
    return set(loans["loan_reference"].to_list())


@pytest.fixture(scope="module")
def fac_refs(facilities: pl.DataFrame) -> set[str]:
    return set(facilities["facility_reference"].to_list())


# --- Counterparty reference checks ---


class TestCounterpartyReferences:
    """All exposure/rating counterparty references must exist in counterparties."""

    def test_loan_counterparty_references(self, loans: pl.DataFrame, cpty_refs: set[str]) -> None:
        loan_cptys = set(loans["counterparty_reference"].to_list())
        missing = loan_cptys - cpty_refs
        assert not missing, f"Loans reference missing counterparties: {missing}"

    def test_facility_counterparty_references(
        self, facilities: pl.DataFrame, cpty_refs: set[str]
    ) -> None:
        fac_cptys = set(facilities["counterparty_reference"].to_list())
        missing = fac_cptys - cpty_refs
        assert not missing, f"Facilities reference missing counterparties: {missing}"

    def test_contingent_counterparty_references(
        self, contingents: pl.DataFrame, cpty_refs: set[str]
    ) -> None:
        cont_cptys = set(contingents["counterparty_reference"].to_list())
        missing = cont_cptys - cpty_refs
        assert not missing, f"Contingents reference missing counterparties: {missing}"

    def test_rating_counterparty_references(
        self, ratings: pl.DataFrame, cpty_refs: set[str]
    ) -> None:
        rating_cptys = set(ratings["counterparty_reference"].to_list())
        missing = rating_cptys - cpty_refs
        assert not missing, f"Ratings reference missing counterparties: {missing}"


# --- CRM beneficiary reference checks ---


class TestCRMBeneficiaryReferences:
    """CRM records must reference existing loans or facilities."""

    def test_collateral_loan_references(
        self, collateral: pl.DataFrame, loan_refs: set[str]
    ) -> None:
        coll_loan_refs = set(
            collateral.filter(pl.col("beneficiary_type") == "loan")[
                "beneficiary_reference"
            ].to_list()
        )
        missing = coll_loan_refs - loan_refs
        assert not missing, f"Collateral references missing loans: {missing}"

    def test_collateral_facility_references(
        self, collateral: pl.DataFrame, fac_refs: set[str]
    ) -> None:
        coll_fac_refs = set(
            collateral.filter(pl.col("beneficiary_type") == "facility")[
                "beneficiary_reference"
            ].to_list()
        )
        missing = coll_fac_refs - fac_refs
        assert not missing, f"Collateral references missing facilities: {missing}"

    def test_guarantee_loan_references(self, guarantees: pl.DataFrame, loan_refs: set[str]) -> None:
        guar_loan_refs = set(
            guarantees.filter(pl.col("beneficiary_type") == "loan")[
                "beneficiary_reference"
            ].to_list()
        )
        missing = guar_loan_refs - loan_refs
        assert not missing, f"Guarantees reference missing loans: {missing}"

    def test_guarantee_facility_references(
        self, guarantees: pl.DataFrame, fac_refs: set[str]
    ) -> None:
        guar_fac_refs = set(
            guarantees.filter(pl.col("beneficiary_type") == "facility")[
                "beneficiary_reference"
            ].to_list()
        )
        missing = guar_fac_refs - fac_refs
        assert not missing, f"Guarantees reference missing facilities: {missing}"

    def test_guarantee_guarantor_references(
        self, guarantees: pl.DataFrame, cpty_refs: set[str]
    ) -> None:
        guarantor_refs = set(guarantees["guarantor"].to_list())
        missing = guarantor_refs - cpty_refs
        assert not missing, f"Guarantees reference missing guarantors: {missing}"

    def test_provision_loan_references(self, provisions: pl.DataFrame, loan_refs: set[str]) -> None:
        prov_loan_refs = set(
            provisions.filter(pl.col("beneficiary_type") == "loan")[
                "beneficiary_reference"
            ].to_list()
        )
        missing = prov_loan_refs - loan_refs
        assert not missing, f"Provisions reference missing loans: {missing}"


# --- Mapping reference checks ---


class TestMappingReferences:
    """All mapping parent/child references must exist in their respective tables."""

    def test_facility_mapping_parent_references(
        self, facility_mappings: pl.DataFrame, fac_refs: set[str]
    ) -> None:
        parent_refs = set(facility_mappings["parent_facility_reference"].to_list())
        missing = parent_refs - fac_refs
        assert not missing, f"Facility mappings reference missing parent facilities: {missing}"

    def test_facility_mapping_child_references(
        self,
        facility_mappings: pl.DataFrame,
        fac_refs: set[str],
        loan_refs: set[str],
    ) -> None:
        child_refs = set(facility_mappings["child_reference"].to_list())
        valid = fac_refs | loan_refs
        missing = child_refs - valid
        assert not missing, f"Facility mappings reference unknown children: {missing}"

    def test_org_mapping_references(self, org_mappings: pl.DataFrame, cpty_refs: set[str]) -> None:
        parents = set(org_mappings["parent_counterparty_reference"].to_list())
        children = set(org_mappings["child_counterparty_reference"].to_list())
        missing = (parents | children) - cpty_refs
        assert not missing, f"Org mappings reference missing counterparties: {missing}"

    def test_lending_mapping_references(
        self, lending_mappings: pl.DataFrame, cpty_refs: set[str]
    ) -> None:
        parents = set(lending_mappings["parent_counterparty_reference"].to_list())
        children = set(lending_mappings["child_counterparty_reference"].to_list())
        missing = (parents | children) - cpty_refs
        assert not missing, f"Lending mappings reference missing counterparties: {missing}"


# --- Model ID reference checks ---


class TestModelIDReferences:
    """Rating model_ids must reference valid model_permissions."""

    def test_rating_model_id_references(self, ratings: pl.DataFrame) -> None:
        perms_path = FIXTURES_DIR / "model_permissions" / "model_permissions.parquet"
        if not perms_path.exists():
            pytest.skip("model_permissions.parquet not found")

        model_perms = pl.read_parquet(perms_path)
        valid_ids = set(model_perms["model_id"].to_list())

        if "model_id" not in ratings.columns:
            return

        non_null = ratings.filter(pl.col("model_id").is_not_null())
        rating_ids = set(non_null["model_id"].to_list())
        missing = rating_ids - valid_ids
        assert not missing, f"Ratings reference missing model_ids: {missing}"


# --- Data quality checks ---


class TestFixtureDataQuality:
    """Basic data quality checks on fixture data."""

    def test_no_duplicate_loan_references(self, loans: pl.DataFrame) -> None:
        refs = loans["loan_reference"].to_list()
        dupes = [r for r in refs if refs.count(r) > 1]
        assert not dupes, f"Duplicate loan references: {set(dupes)}"

    def test_no_duplicate_facility_references(self, facilities: pl.DataFrame) -> None:
        refs = facilities["facility_reference"].to_list()
        dupes = [r for r in refs if refs.count(r) > 1]
        assert not dupes, f"Duplicate facility references: {set(dupes)}"

    def test_no_duplicate_collateral_references(self, collateral: pl.DataFrame) -> None:
        refs = collateral["collateral_reference"].to_list()
        dupes = [r for r in refs if refs.count(r) > 1]
        assert not dupes, f"Duplicate collateral references: {set(dupes)}"

    def test_no_duplicate_guarantee_references(self, guarantees: pl.DataFrame) -> None:
        refs = guarantees["guarantee_reference"].to_list()
        dupes = [r for r in refs if refs.count(r) > 1]
        assert not dupes, f"Duplicate guarantee references: {set(dupes)}"

    def test_no_duplicate_provision_references(self, provisions: pl.DataFrame) -> None:
        refs = provisions["provision_reference"].to_list()
        dupes = [r for r in refs if refs.count(r) > 1]
        assert not dupes, f"Duplicate provision references: {set(dupes)}"
