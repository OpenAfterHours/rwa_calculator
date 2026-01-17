"""
Counterparty test fixtures module.

This module provides functions to create and save counterparty test data
for all exposure classes required by the RWA calculator acceptance tests.
"""

from .sovereign import create_sovereign_counterparties, save_sovereign_counterparties
from .institution import create_institution_counterparties, save_institution_counterparties
from .corporate import create_corporate_counterparties, save_corporate_counterparties
from .retail import create_retail_counterparties, save_retail_counterparties
from .specialised_lending import (
    create_specialised_lending_counterparties,
    save_specialised_lending_counterparties,
)

__all__ = [
    "create_sovereign_counterparties",
    "save_sovereign_counterparties",
    "create_institution_counterparties",
    "save_institution_counterparties",
    "create_corporate_counterparties",
    "save_corporate_counterparties",
    "create_retail_counterparties",
    "save_retail_counterparties",
    "create_specialised_lending_counterparties",
    "save_specialised_lending_counterparties",
    "generate_all_counterparties",
]


def generate_all_counterparties() -> dict[str, int]:
    """
    Generate all counterparty parquet files.

    Returns:
        dict[str, int]: Dictionary mapping counterparty type to record count
    """
    from .sovereign import create_sovereign_counterparties, save_sovereign_counterparties
    from .institution import create_institution_counterparties, save_institution_counterparties
    from .corporate import create_corporate_counterparties, save_corporate_counterparties
    from .retail import create_retail_counterparties, save_retail_counterparties
    from .specialised_lending import (
        create_specialised_lending_counterparties,
        save_specialised_lending_counterparties,
    )

    results = {}

    save_sovereign_counterparties()
    results["sovereign"] = len(create_sovereign_counterparties())

    save_institution_counterparties()
    results["institution"] = len(create_institution_counterparties())

    save_corporate_counterparties()
    results["corporate"] = len(create_corporate_counterparties())

    save_retail_counterparties()
    results["retail"] = len(create_retail_counterparties())

    save_specialised_lending_counterparties()
    results["specialised_lending"] = len(create_specialised_lending_counterparties())

    return results
