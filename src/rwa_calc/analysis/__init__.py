"""Cross-run analysis layer (above the engine).

Houses the runners that consume finished pipeline output rather than producing
it: dual-/labelled-run comparison, parallel-run reconciliation, and (Phase 6)
transition modelling. Per the target architecture, ``analysis/`` sits ABOVE
``engine/`` — it may import ``engine``/``contracts``/``rulebook``/``data``/
``domain`` downward, but nothing below it may import ``rwa_calc.analysis``
(enforced by ``scripts/arch_check.py`` import-direction rules).
"""
