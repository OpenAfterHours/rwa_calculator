"""
Ratings test fixtures module.

This module provides functions to create and save credit rating test data
for counterparties, supporting both external (agency) and internal (bank) ratings.
"""

from .ratings import create_ratings, save_ratings

__all__ = [
    "create_ratings",
    "save_ratings",
]
