"""
Stage adapter modules for the fold orchestrator — the pipeline's wiring layer.

Each module exposes one ``run(ctx, rulepack, run_config) -> PipelineContext``
stage function — the uniform stage shape — wrapping a domain that lives in a
sibling package under ``engine/``. There is one module here per entry in
``engine/registry.py`` and nothing else, so the registry reads as a literal
table of contents for this directory.

**Domains do not live here.** Until the S1 move this package held both kinds
of thing under one name: for seven registry stages a 58-262 line adapter over
a domain at ``engine/<name>/``, and for four the entire 744-3,943 line domain
with no sibling — plus ``fx``, which is not a registry stage at all. Those
five packages now sit beside the other domains at ``engine/{hierarchy,
classify,re_split,scope,fx}/``. A new stage adds one module here and puts its
logic in a peer package under ``engine/``; ``arch_check`` check 16 fails any
package that reappears under this directory without a ``run``.

References:
- docs/plans/architecture-review-2026-08-29.md §2 (the stages/domain split)
- docs/plans/target-architecture-migration.md (Phase 4 — uniform stage model)
"""
