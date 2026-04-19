"""
Contract tests for the RWA Calculator observability contract.

Enforces the invariants documented in docs/specifications/observability.md
across every stage module and binds the contract to the ``arch_check.py``
logger check. These tests fail loudly if a new stage is added without a
module logger, or if someone accidentally reintroduces ``print()`` /
``logging.basicConfig()`` into engine/**.
"""

from __future__ import annotations

import importlib
import logging

import pytest

STAGE_MODULES: tuple[str, ...] = (
    "rwa_calc.engine.loader",
    "rwa_calc.engine.hierarchy",
    "rwa_calc.engine.classifier",
    "rwa_calc.engine.crm.processor",
    "rwa_calc.engine.re_splitter",
    "rwa_calc.engine.sa.calculator",
    "rwa_calc.engine.irb.calculator",
    "rwa_calc.engine.slotting.calculator",
    "rwa_calc.engine.equity.calculator",
    "rwa_calc.engine.aggregator.aggregator",
    "rwa_calc.engine.pipeline",
)


@pytest.mark.parametrize("module_name", STAGE_MODULES)
def test_stage_module_declares_logger(module_name: str) -> None:
    module = importlib.import_module(module_name)
    logger = getattr(module, "logger", None)

    assert isinstance(logger, logging.Logger), (
        f"{module_name} must declare `logger = logging.getLogger(__name__)`"
    )
    assert logger.name == module_name, (
        f"{module_name}.logger has name {logger.name!r}; should use `logging.getLogger(__name__)`"
    )


def test_arch_check_engine_logger_contract_has_no_violations() -> None:
    """The architecture check for the observability contract must pass."""
    from pathlib import Path

    from scripts.arch_check import check_engine_logger_contract

    violations = check_engine_logger_contract(Path("src/rwa_calc"))

    assert not violations, "arch_check engine-logger violations:\n" + "\n".join(violations)


def test_observability_public_api_is_stable() -> None:
    """The observability package exposes the documented public API surface."""
    from rwa_calc import observability

    expected = {
        "configure_logging",
        "get_logger",
        "new_run_id",
        "bind_run_id",
        "clear_run_id",
        "current_run_id",
        "stage_timer",
        "RunIdFilter",
        "TextFormatter",
        "JsonFormatter",
    }
    exported = set(observability.__all__)

    missing = expected - exported
    assert not missing, f"observability.__all__ missing entries: {sorted(missing)}"
