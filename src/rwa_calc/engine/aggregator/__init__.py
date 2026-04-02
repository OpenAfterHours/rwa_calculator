"""
Output aggregation components.

Pipeline position:
    SA/IRB/Slotting/Equity Calculators -> OutputAggregator -> AggregatedResultBundle

Provides:
- OutputAggregator: Main aggregator implementing OutputAggregatorProtocol
"""

from rwa_calc.engine.aggregator.aggregator import OutputAggregator

__all__ = ["OutputAggregator"]
