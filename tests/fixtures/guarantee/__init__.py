"""
Guarantee test fixtures module.

This module provides functions to create and save guarantee test data
for credit risk mitigation (CRM) testing.
"""

from .guarantee import create_guarantees, save_guarantees

__all__ = [
    "create_guarantees",
    "save_guarantees",
]
