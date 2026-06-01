"""Unit tests for DataSourceRegistry collateral_links entry.

Asserts that the registry contains a DataSourceFile for collateral links and that
DataSourceConfig.from_registry() populates the collateral_links_file field, so the
M:N collateral-to-beneficiary mapping is auto-discovered from the standard data
layout like every other optional input.

References:
- CRR Art. 230-231: collateral substitution / sequential allocation
"""

from __future__ import annotations

from pathlib import Path

from rwa_calc.config.data_sources import DataSourceFile, DataSourceRegistry, RequirementLevel
from rwa_calc.engine.loader import DataSourceConfig


class TestDataSourceRegistryCollateralLinks:
    """Tests for collateral_links entry in DataSourceRegistry."""

    def test_registry_contains_collateral_links_entry(self) -> None:
        """DataSourceRegistry should contain an entry with id 'collateral_links'."""
        # Arrange
        registry = DataSourceRegistry()

        # Act
        source = registry.get_by_id("collateral_links")

        # Assert
        assert source is not None, (
            "Expected 'collateral_links' entry in DataSourceRegistry, got None"
        )
        assert isinstance(source, DataSourceFile)

    def test_collateral_links_relative_path(self) -> None:
        """collateral_links entry should have relative_path of 'collateral/collateral_links'."""
        # Arrange
        registry = DataSourceRegistry()

        # Act
        source = registry.get_by_id("collateral_links")

        # Assert
        assert source is not None
        assert source.relative_path == Path("collateral/collateral_links"), (
            f"Expected relative_path=Path('collateral/collateral_links'), "
            f"got {source.relative_path!r}"
        )

    def test_collateral_links_requirement_is_optional(self) -> None:
        """collateral_links entry should have requirement level OPTIONAL."""
        # Arrange
        registry = DataSourceRegistry()

        # Act
        source = registry.get_by_id("collateral_links")

        # Assert
        assert source is not None
        assert source.requirement is RequirementLevel.OPTIONAL, (
            f"Expected RequirementLevel.OPTIONAL, got {source.requirement!r}"
        )

    def test_collateral_links_parquet_path_in_optional_list(self) -> None:
        """collateral/collateral_links.parquet should appear in get_optional('parquet')."""
        # Arrange
        registry = DataSourceRegistry()

        # Act
        optional_paths = registry.get_optional("parquet")

        # Assert
        assert Path("collateral/collateral_links.parquet") in optional_paths, (
            f"Expected Path('collateral/collateral_links.parquet') in optional parquet paths, "
            f"got: {optional_paths}"
        )

    def test_from_registry_parquet_populates_collateral_links_file(self) -> None:
        """from_registry() should set collateral_links_file to collateral/collateral_links.parquet."""
        # Arrange / Act
        config = DataSourceConfig.from_registry()

        # Assert
        assert config.collateral_links_file == Path("collateral/collateral_links.parquet"), (
            f"Expected collateral_links_file=Path('collateral/collateral_links.parquet'), "
            f"got {config.collateral_links_file!r}"
        )

    def test_from_registry_csv_populates_collateral_links_file(self) -> None:
        """from_registry(extension='csv') should set collateral_links_file to the .csv path."""
        # Arrange / Act
        config = DataSourceConfig.from_registry(extension="csv")

        # Assert
        assert config.collateral_links_file == Path("collateral/collateral_links.csv"), (
            f"Expected collateral_links_file=Path('collateral/collateral_links.csv'), "
            f"got {config.collateral_links_file!r}"
        )

    def test_collateral_links_description_mentions_collateral(self) -> None:
        """collateral_links entry should have a non-None description mentioning 'collateral'."""
        # Arrange
        registry = DataSourceRegistry()

        # Act
        source = registry.get_by_id("collateral_links")

        # Assert
        assert source is not None
        assert source.description is not None, (
            "Expected a non-None description for collateral_links"
        )
        assert "collateral" in source.description.lower(), (
            f"Expected 'collateral' in description (case-insensitive), got {source.description!r}"
        )
