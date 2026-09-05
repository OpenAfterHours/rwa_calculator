"""
Output aggregation components.

Pipeline position:
    SA/IRB/Slotting/Equity Calculators -> OutputAggregator -> AggregatedResultBundle

Provides:
- OutputAggregator: Main aggregator implementing OutputAggregatorProtocol
- rekey_candidate_errors: the facility-share error pass, public to the pipeline
  facade — it is the ONLY part of the resolver a caller outside this package
  needs, and it has to run at the facade's single error-merge point rather than
  inside ``aggregate`` (that is where the loader, stage and crash channels join
  the aggregator's own).
"""

from rwa_calc.engine.aggregator._facility_share import rekey_candidate_errors
from rwa_calc.engine.aggregator.aggregator import OutputAggregator

__all__ = ["OutputAggregator", "rekey_candidate_errors"]
