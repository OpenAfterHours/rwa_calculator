"""
Hypothesis configuration for the property suite.

Key responsibilities:
- Register a deterministic profile. ``derandomize=True`` means the same command
  explores the same portfolios on every machine, so a failure reported here is a
  failure anyone can reproduce without a seed hand-off.
- Remove the per-example deadline. A pipeline run is ~0.35s and a template
  generation ~1.5s; a deadline would convert scheduling noise into failures that
  say nothing about correctness.
- Keep ``max_examples`` small enough for the dev loop, with a thorough setting
  behind ``RWA_PROPERTY_PROFILE=thorough`` for a deliberate deeper sweep.

The database is disabled on purpose: a replayed example from a previous run
would make the suite's runtime and its explored set depend on local state, and
this suite's value rests on both being stated honestly.
"""

from __future__ import annotations

import os

from hypothesis import HealthCheck, settings

#: Suppressed because both are expected here rather than symptomatic: a single
#: example runs a whole pipeline, and the portfolio strategies filter on
#: regulatory admissibility (a retail obligor above the Art. 123 limit is not a
#: retail obligor).
_SUPPRESSED = (HealthCheck.too_slow, HealthCheck.filter_too_much, HealthCheck.data_too_large)

settings.register_profile(
    "dev",
    max_examples=int(os.environ.get("RWA_PROPERTY_MAX_EXAMPLES", "12")),
    deadline=None,
    derandomize=True,
    database=None,
    suppress_health_check=_SUPPRESSED,
)

settings.register_profile(
    "thorough",
    max_examples=int(os.environ.get("RWA_PROPERTY_MAX_EXAMPLES", "200")),
    deadline=None,
    derandomize=True,
    database=None,
    suppress_health_check=_SUPPRESSED,
)

settings.load_profile(os.environ.get("RWA_PROPERTY_PROFILE", "dev"))
