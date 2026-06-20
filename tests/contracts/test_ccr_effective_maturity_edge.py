"""
Contract tests for the ``ccr_effective_maturity`` carrier column and its
supporting SFT / SA-CCR input flags (CCR/SFT IRB effective-maturity fix,
Phase 2).

Pins the schema + edge-contract surface that Phases 3-4 build on:
- ``ccr_effective_maturity`` (Float64, optional) is declared on
  ``CCR_EXIT_EDGE`` and PROPAGATES via the CCR-only spread comprehensions to
  ``CLASSIFIER_EXIT_CCR_EDGE`` / ``CRM_EXIT_CCR_EDGE`` / ``RE_SPLIT_EXIT_CCR_EDGE``.
- It is ABSENT from ``HIERARCHY_EXIT_EDGE`` — a hierarchy-base column would be
  silently filtered out of the CCR-flavoured exits by the
  ``c not in HIERARCHY_EXIT_EDGE.columns`` comprehension (the placement trap).
- The three Art. 162 input flags exist on ``SFT_TRADE_SCHEMA`` and the SA-CCR
  derivative ``TRADE_SCHEMA``, each Boolean with conservative default ``False``.

References:
- CRR Art. 162(1)/(2)(c)(d)/(3) — IRB effective maturity, MNA & one-day floors
- PS1/26 Art. 162(2)/(2A)/(3) — Basel 3.1 maturity divergence
- .claude/state/ccr-irb-maturity-fix-plan.md (Phase 2)
"""

from __future__ import annotations

import polars as pl
import pytest

from rwa_calc.contracts.edges import (
    CCR_EXIT_EDGE,
    CLASSIFIER_EXIT_CCR_EDGE,
    CRM_EXIT_CCR_EDGE,
    HIERARCHY_EXIT_EDGE,
    RE_SPLIT_EXIT_CCR_EDGE,
)
from rwa_calc.data.schemas import SFT_TRADE_SCHEMA, TRADE_SCHEMA

CARRIER = "ccr_effective_maturity"

CCR_FLAVOURED_EDGES = [
    CCR_EXIT_EDGE,
    CLASSIFIER_EXIT_CCR_EDGE,
    CRM_EXIT_CCR_EDGE,
    RE_SPLIT_EXIT_CCR_EDGE,
]

ART_162_FLAGS = (
    "under_master_netting_agreement",
    "qualifies_one_day_maturity_floor",
    "qualifies_mna_intermediate_floor",
)


class TestCcrEffectiveMaturityCarrier:
    """The ``ccr_effective_maturity`` carrier lives on the CCR-flavoured edges."""

    @pytest.mark.parametrize("edge", CCR_FLAVOURED_EDGES, ids=lambda e: e.name)
    def test_carrier_present_on_ccr_edge(self, edge):
        # Arrange / Act / Assert
        assert CARRIER in edge.columns, (
            f"'{CARRIER}' must be declared on edge '{edge.name}' "
            "(CCR-only spread should propagate it)"
        )

    @pytest.mark.parametrize("edge", CCR_FLAVOURED_EDGES, ids=lambda e: e.name)
    def test_carrier_is_float64(self, edge):
        # Arrange / Act / Assert
        assert edge.columns[CARRIER].dtype == pl.Float64, (
            f"'{CARRIER}' must be pl.Float64 on edge '{edge.name}', "
            f"got {edge.columns[CARRIER].dtype}"
        )

    @pytest.mark.parametrize("edge", CCR_FLAVOURED_EDGES, ids=lambda e: e.name)
    def test_carrier_is_optional(self, edge):
        # Arrange / Act / Assert
        assert edge.columns[CARRIER].required is False, (
            f"'{CARRIER}' must be required=False on edge '{edge.name}' "
            "(absent on lending rows; conform injects a typed null)"
        )

    def test_carrier_absent_from_hierarchy_exit_edge(self):
        # The placement-trap guard: a hierarchy-base column is filtered out of
        # the CCR exits by 'c not in HIERARCHY_EXIT_EDGE.columns'.
        assert CARRIER not in HIERARCHY_EXIT_EDGE.columns, (
            f"'{CARRIER}' must NOT be on HIERARCHY_EXIT_EDGE — placing it there "
            "would silently strip it from the CCR classifier/crm exits"
        )

    def test_carrier_never_auto_fills_to_zero(self):
        # Locks 'null = off-carve-out, NOT 0': the optional Float carrier must
        # inject a TYPED NULL when absent (default None) and never fill present
        # nulls. A future edit adding default=0.0 / fill_null_default=True would
        # be anti-conservative (a 0-year M is not the same as 'date-derived M').
        col = CCR_EXIT_EDGE.columns[CARRIER]
        assert col.default is None, "carrier must inject a typed null, not a value"
        assert col.fill_null_default is False, "carrier must never fill present nulls"
        assert col.inject is True, "absent carrier must be injected as a typed null"


class TestArt162SftInputFlags:
    """The three Art. 162 input flags exist on SFT_TRADE_SCHEMA (default False)."""

    @pytest.mark.parametrize("flag", ART_162_FLAGS)
    def test_flag_present(self, flag):
        assert flag in SFT_TRADE_SCHEMA, f"SFT_TRADE_SCHEMA must declare '{flag}'"

    @pytest.mark.parametrize("flag", ART_162_FLAGS)
    def test_flag_is_boolean(self, flag):
        assert SFT_TRADE_SCHEMA[flag].dtype == pl.Boolean, (
            f"SFT_TRADE_SCHEMA['{flag}'] must be pl.Boolean, got {SFT_TRADE_SCHEMA[flag].dtype}"
        )

    @pytest.mark.parametrize("flag", ART_162_FLAGS)
    def test_flag_default_false(self, flag):
        assert SFT_TRADE_SCHEMA[flag].default is False, (
            f"SFT_TRADE_SCHEMA['{flag}'] must default to False (conservative; "
            f"absent is never qualifying), got {SFT_TRADE_SCHEMA[flag].default!r}"
        )

    @pytest.mark.parametrize("flag", ART_162_FLAGS)
    def test_flag_optional(self, flag):
        assert SFT_TRADE_SCHEMA[flag].required is False, (
            f"SFT_TRADE_SCHEMA['{flag}'] must be required=False"
        )


class TestArt162DerivativeInputFlags:
    """The same three Art. 162 flags exist on the SA-CCR TRADE_SCHEMA."""

    @pytest.mark.parametrize("flag", ART_162_FLAGS)
    def test_flag_present(self, flag):
        assert flag in TRADE_SCHEMA, f"TRADE_SCHEMA must declare '{flag}'"

    @pytest.mark.parametrize("flag", ART_162_FLAGS)
    def test_flag_is_boolean(self, flag):
        assert TRADE_SCHEMA[flag].dtype == pl.Boolean, (
            f"TRADE_SCHEMA['{flag}'] must be pl.Boolean, got {TRADE_SCHEMA[flag].dtype}"
        )

    @pytest.mark.parametrize("flag", ART_162_FLAGS)
    def test_flag_default_false(self, flag):
        assert TRADE_SCHEMA[flag].default is False, (
            f"TRADE_SCHEMA['{flag}'] must default to False (conservative), "
            f"got {TRADE_SCHEMA[flag].default!r}"
        )

    @pytest.mark.parametrize("flag", ART_162_FLAGS)
    def test_flag_optional(self, flag):
        assert TRADE_SCHEMA[flag].required is False, (
            f"TRADE_SCHEMA['{flag}'] must be required=False"
        )
