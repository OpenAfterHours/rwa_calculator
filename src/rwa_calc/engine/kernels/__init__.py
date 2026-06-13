"""
Shared engine kernels — algorithms written once, parameterised per consumer.

Currently hosts the multi-level beneficiary allocation kernel
(:mod:`rwa_calc.engine.kernels.allocation`), extracted from the five
drifting CRM / hierarchy allocator copies in migration Phase 4 Slice 6.
"""

from __future__ import annotations

from rwa_calc.engine.kernels.allocation import (
    NO_DEFAULT,
    LevelSpec,
    allocate_multi_level,
    ancestor_membership_expr,
    beneficiary_level_expr,
    coalesce_attribute_levels,
    direct_level_lookup,
    expand_items_pro_rata,
    explode_facility_membership,
    grouped_level_lookup,
    join_items_to_level_lookups,
    level_attribute_lookup,
    switch_by_beneficiary_level,
)

__all__ = [
    "NO_DEFAULT",
    "LevelSpec",
    "allocate_multi_level",
    "ancestor_membership_expr",
    "beneficiary_level_expr",
    "coalesce_attribute_levels",
    "direct_level_lookup",
    "expand_items_pro_rata",
    "explode_facility_membership",
    "grouped_level_lookup",
    "join_items_to_level_lookups",
    "level_attribute_lookup",
    "switch_by_beneficiary_level",
]
