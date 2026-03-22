"""
Ratings test fixtures module.

This module provides functions to create and save credit rating test data
for counterparties, supporting both external (agency) and internal (bank) ratings.
"""

from .ratings import create_ratings, save_ratings
from .specialised_lending import create_specialised_lending_data, save_specialised_lending_data

__all__ = [
    "create_ratings",
    "save_ratings",
    "create_specialised_lending_data",
    "save_specialised_lending_data",
]
