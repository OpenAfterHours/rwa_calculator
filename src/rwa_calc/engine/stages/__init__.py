"""
Stage adapter modules for the fold orchestrator (migration Phase 4).

Each module exposes one ``run(ctx, rulepack, run_config) -> PipelineContext``
stage function — the uniform stage shape — wrapping today's class-shaped
component behind the bundle-to-context adapter. As each stage migrates to
the mandatory anatomy (thin ``stage.py`` + focused sub-modules + exit
contract), its adapter here grows into a package and the component class
dissolves.

References:
- docs/plans/target-architecture-migration.md (Phase 4 — uniform stage model)
"""
