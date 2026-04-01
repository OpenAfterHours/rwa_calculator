"""
Asset correlation calculations for IRB approach.

Redirects to the shared correlation module in workbooks/shared/correlation.py.
The asset correlation formula is the same for CRR and Basel 3.1.
"""

# Re-export from shared module
from workbooks.shared.correlation import (
    CORRELATION_PARAMS,
    calculate_correlation,
    get_correlation_for_class,
)

__all__ = [
    "calculate_correlation",
    "get_correlation_for_class",
    "CORRELATION_PARAMS",
]
