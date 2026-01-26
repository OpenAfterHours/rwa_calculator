"""
BDD test configuration.

Feature files are located in docs/specifications/ to serve as living documentation
for both risk users and developers. Step definitions in this package implement
the executable tests against those specifications.
"""

from pathlib import Path

import pytest

# Path to feature specifications in docs
SPECIFICATIONS_DIR = Path(__file__).parent.parent.parent / "docs" / "specifications"


@pytest.fixture
def specifications_path() -> Path:
    """Return the path to the feature specifications directory."""
    return SPECIFICATIONS_DIR


@pytest.fixture
def context():
    """Shared context for passing data between steps."""

    class Context:
        """Simple namespace for step data."""

        pass

    return Context()
