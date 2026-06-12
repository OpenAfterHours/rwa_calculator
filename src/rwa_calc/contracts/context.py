"""
PipelineContext and typed artifact keys for the fold orchestrator.

Pipeline position:
    Carried through every registered stage:
    Stage(ctx: PipelineContext, rulepack, run_config) -> PipelineContext

Key responsibilities:
- ``ArtifactKey[T]``: a typed, hashable handle naming one artifact a stage
  reads or writes (frames, bundles, error channels, side lookups).
- ``PipelineContext``: an immutable artifact map. Stages never mutate the
  context; they return a new one via ``put``. This replaces the orchestrator
  ``self._*`` scratch attributes (migration Phase 4) so cross-stage state is
  explicit, typed, and inspectable.

Design notes:
- Keys compare by ``name`` — declare each key exactly once, as a module-level
  constant next to the stage family that owns it (engine-typed keys live in
  ``engine/orchestrator.py``; this module stays free of engine imports per
  the import-direction rule, arch_check check 12).
- Frame artifacts keep their Phase 3 producer seal: the context stores the
  exact sealed object, and bundle ``__post_init__`` re-validates brands
  whenever an adapter regathers a bundle from context artifacts.

References:
- docs/plans/target-architecture-migration.md (Phase 4 — uniform stage model)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast


@dataclass(frozen=True)
class ArtifactKey[T]:
    """Typed handle for one artifact in :class:`PipelineContext`.

    The type parameter documents (and lets ``ty`` check) what a stage gets
    back from ``ctx.get(KEY)``. Equality and hashing are by ``name`` — two
    keys with the same name address the same artifact slot.
    """

    name: str


@dataclass(frozen=True)
class PipelineContext:
    """Immutable artifact map threaded through the stage fold.

    Stages receive a context and return a new one; the orchestrator never
    mutates state in place. Artifact writes copy the underlying map — the
    map holds a handful of bundle/frame references per run, so copies are
    O(stage count), not O(data).
    """

    artifacts: dict[ArtifactKey[Any], Any] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> PipelineContext:
        """Create a context with no artifacts."""
        return cls(artifacts={})

    def has(self, key: ArtifactKey[Any]) -> bool:
        """Return True when ``key`` holds an artifact (even ``None``)."""
        return key in self.artifacts

    def get[T](self, key: ArtifactKey[T]) -> T:
        """Return the artifact for ``key``.

        Raises:
            KeyError: when the artifact was never written — a programming
                error (stage ordering bug), not a data-quality issue.
        """
        if key not in self.artifacts:
            msg = f"artifact {key.name!r} not in PipelineContext"
            raise KeyError(msg)
        return cast("T", self.artifacts[key])

    def get_or[T](self, key: ArtifactKey[T], default: T) -> T:
        """Return the artifact for ``key``, or ``default`` when absent."""
        if key not in self.artifacts:
            return default
        return cast("T", self.artifacts[key])

    def put[T](self, key: ArtifactKey[T], value: T) -> PipelineContext:
        """Return a new context with ``key`` set to ``value``."""
        new_artifacts: dict[ArtifactKey[Any], Any] = dict(self.artifacts)
        new_artifacts[key] = value
        return PipelineContext(artifacts=new_artifacts)
