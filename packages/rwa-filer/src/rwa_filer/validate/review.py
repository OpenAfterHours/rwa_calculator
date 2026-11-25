"""Display preferences for reviewing individual failed evaluations of a filing."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Final

from rwa_filer.boe.catalogue import SEVERITY_ERROR, SEVERITY_WARNING

if TYPE_CHECKING:
    from rwa_filer.boe.engine import Failure, RuleResult


@dataclass(frozen=True)
class ReviewFilter:
    """Hide proven small warning excesses or reported zeroes in must-be-empty checks."""

    money: Decimal | None = None
    basis_points: Decimal | None = None
    hide_zero_null: bool = False

    def __post_init__(self) -> None:
        for value in (self.money, self.basis_points):
            if value is not None and (not value.is_finite() or value < 0):
                raise ValueError("Warning materiality must be a finite, non-negative number.")

    @classmethod
    def from_text(cls, money: str, basis_points: str, hide_zero_null: bool) -> ReviewFilter:
        try:
            return cls(
                Decimal(money) if money.strip() else None,
                Decimal(basis_points) if basis_points.strip() else None,
                hide_zero_null,
            )
        except InvalidOperation as exc:
            raise ValueError("Enter a numeric warning materiality.") from exc

    @property
    def active(self) -> bool:
        return bool(self.money or self.basis_points or self.hide_zero_null)

    def visible(self, result: RuleResult) -> tuple[Failure, ...]:
        """The recorded occurrences to show, in evaluation order, at effective severity."""
        if not self.active:
            return result.failures
        return tuple(f for f in result.failures if not self.hides(result.severity, f))

    def hidden_count(self, result: RuleResult) -> int:
        """Only recorded occurrences can be proven eligible for hiding."""
        if not self.active:
            return 0
        return sum(self.hides(result.severity, f) for f in result.failures)

    def hides(self, severity: str, failure: Failure) -> bool:
        """Whether this occurrence is hidden at the rule's effective severity."""
        if self.hide_zero_null and severity == SEVERITY_ERROR and failure.zero_in_empty_cell:
            return True
        if severity != SEVERITY_WARNING or failure.excess is None:
            return False
        if failure.unit == "monetary" and self.money is not None:
            return failure.excess < self.money
        if failure.unit == "percentage" and self.basis_points is not None:
            return failure.excess * 10_000 < self.basis_points
        return False


SHOW_ALL: Final = ReviewFilter()
