"""
Unit tests for PipelineContext / ArtifactKey (contracts/context.py).

Pins the context mechanics the Phase 4 fold orchestrator relies on:
- typed get/get_or/put/has access
- immutability (put returns a new context; the original is untouched)
- ArtifactKey identity by name
- missing-artifact access is a programming error (KeyError), never a
  silent default

This file is exempt from the builder-conformance lint because its purpose
is pinning raw construction mechanics (mirror of test_edge_contracts.py).

References:
- docs/plans/target-architecture-migration.md (Phase 4 — uniform stage model)
"""

from __future__ import annotations

import pytest

from rwa_calc.contracts.context import ArtifactKey, PipelineContext

A_KEY: ArtifactKey[int] = ArtifactKey("test_a")
B_KEY: ArtifactKey[str] = ArtifactKey("test_b")


class TestArtifactKey:
    """ArtifactKey identity semantics."""

    def test_keys_with_same_name_are_equal(self):
        assert ArtifactKey("x") == ArtifactKey("x")
        assert hash(ArtifactKey("x")) == hash(ArtifactKey("x"))

    def test_keys_with_different_names_differ(self):
        assert ArtifactKey("x") != ArtifactKey("y")


class TestPipelineContext:
    """Context access and immutability semantics."""

    def test_empty_context_has_no_artifacts(self):
        ctx = PipelineContext.empty()
        assert not ctx.has(A_KEY)

    def test_put_then_get_roundtrips(self):
        ctx = PipelineContext.empty().put(A_KEY, 42)
        assert ctx.get(A_KEY) == 42
        assert ctx.has(A_KEY)

    def test_put_returns_new_context_original_untouched(self):
        original = PipelineContext.empty().put(A_KEY, 1)
        updated = original.put(A_KEY, 2)

        assert original.get(A_KEY) == 1
        assert updated.get(A_KEY) == 2
        assert updated is not original

    def test_put_none_is_a_present_artifact(self):
        """A None artifact is present — has() distinguishes None from absent."""
        ctx = PipelineContext.empty().put(B_KEY, None)
        assert ctx.has(B_KEY)
        assert ctx.get_or(B_KEY, "fallback") is None

    def test_get_missing_raises_keyerror_with_name(self):
        ctx = PipelineContext.empty()
        with pytest.raises(KeyError, match="test_a"):
            ctx.get(A_KEY)

    def test_get_or_returns_default_when_absent(self):
        ctx = PipelineContext.empty()
        assert ctx.get_or(A_KEY, 7) == 7

    def test_chained_puts_accumulate(self):
        ctx = PipelineContext.empty().put(A_KEY, 1).put(B_KEY, "two")
        assert ctx.get(A_KEY) == 1
        assert ctx.get(B_KEY) == "two"
