# Observability

The RWA Calculator emits operational telemetry through stdlib `logging`,
wrapped by `rwa_calc.observability`. This page is the contract for what the
logging layer records, how to configure it, and what authors of new code must
do to stay inside it.

> **Contract**: logging is for **operational observability only**. Data-quality
> and regulatory issues remain the responsibility of `CalculationError`, which
> is accumulated in bundles and surfaced via `AggregatedResultBundle.errors`.
> A log record must never duplicate a `CalculationError.message` — this is
> enforced by `tests/integration/test_logging_pipeline.py`.

## Public API

`rwa_calc.observability` exposes:

| Symbol | Purpose |
|---|---|
| `configure_logging(level, fmt, stream=None)` | Idempotent setup. Attaches a single `StreamHandler` to the `rwa_calc` namespace logger; sets noisy third-party loggers (`polars`, `uvicorn.access`, `fastapi`, `asyncio`) to `WARNING`. |
| `get_logger(name)` | Thin wrapper around `logging.getLogger`. |
| `new_run_id()` | Generate a fresh 12-hex-char `run_id`, bind it to the current context, and return `(run_id, token)`. |
| `bind_run_id(run_id)` | Bind an existing id (returns reset token). |
| `clear_run_id(token)` | Release the binding using the token from `new_run_id` / `bind_run_id`. |
| `current_run_id()` | Read the active id (or `None`). |
| `stage_timer(logger, stage, **extra)` | Context manager emitting a DEBUG entry record and an INFO exit record carrying `elapsed_ms`. Emits WARNING on exception so timing is always recorded. |
| `RunIdFilter` | `logging.Filter` that injects `record.run_id` on every record. |
| `TextFormatter` / `JsonFormatter` | The two supported output formats. |

## Record schema

**Text format** (default):

```
2026-04-19T18:42:01 INFO    [a3f0c1b24e1c] rwa_calc.engine.pipeline: classifier completed in 12.3 ms
```

The stage name and elapsed time are embedded in the message string so the
default `%(message)s` formatter surfaces them without per-stage configuration.
A companion DEBUG record (`"classifier started"`) bookends each stage and is
suppressed at default `INFO` level.

**JSON format** (audit ingestion), single line per record:

```json
{
  "timestamp": "2026-04-19T18:42:01.123456+00:00",
  "level": "INFO",
  "logger": "rwa_calc.engine.pipeline",
  "run_id": "a3f0c1b24e1c",
  "message": "classifier completed in 12.3 ms",
  "module": "pipeline",
  "line": 399,
  "stage": "classifier",
  "elapsed_ms": 12.34
}
```

Only a whitelisted set of `extra` keys is propagated to JSON: `stage`,
`elapsed_ms`, `row_count`, `framework`, `permission_mode`, `log_level`,
`log_format`, `run_id`. Exceptions include `exc_type`, `exc_message`,
`traceback`.

## Levels

| Level | When |
|---|---|
| DEBUG | Stage entry records (via `stage_timer`); branch decisions (IRB-vs-SA routing, CRM method selection, RE-splitter no-op skip). Guard expensive formatting with `logger.isEnabledFor(logging.DEBUG)`. |
| INFO | Stage exit lines with embedded `elapsed_ms` (via `stage_timer`); pipeline start/finish (with total elapsed + error count); stage-level row/row-count summaries (e.g. `"calculators materialised N rows"`); config echo (framework, permission_mode — never regulatory scalars); a single `"collected N calculation errors"` line when errors are appended. |
| WARNING | Missing optional inputs (e.g., IRB selected without `model_permissions`); fallback risk weights; stage failures (emitted by `stage_timer` on exception). |
| ERROR | Reserved for truly unexpected exceptions. Regulatory issues remain `CalculationError`. |

## Configuration

Fields on `CalculationConfig`:

- `log_level: str = "INFO"` — any of `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL`.
- `log_format: Literal["text", "json"] = "text"`.

Both factory methods (`.crr()` and `.basel_3_1()`) accept these as keyword
arguments. The API service (`CreditRiskCalc`) also accepts them and calls
`configure_logging(config.log_level, config.log_format)` before each run.

`configure_logging` is idempotent: repeated calls with identical arguments are
no-ops; calls with different arguments swap the existing handler's
formatter/level in place rather than stacking handlers. This keeps notebooks
and marimo sessions clean across repeated `CreditRiskCalc(...)` constructions.

## Correlation IDs

`PipelineOrchestrator.run_with_data` is the canonical place where a `run_id`
is bound:

```python
run_id, token = new_run_id()
try:
    ...
finally:
    cleanup_spill_files()
    clear_run_id(token)
```

`RunIdFilter` (installed by `configure_logging`) reads the active id from a
`contextvars.ContextVar` and writes it onto every LogRecord as `record.run_id`.
The `TextFormatter` renders it between square brackets; the `JsonFormatter`
emits it as a top-level key.

Implications:

- Concurrent pipelines running in separate asyncio tasks / threads each see
  their own `run_id` (the variable is isolated per context).
- Back-to-back runs always get distinct ids, so log aggregators can partition
  cleanly.
- Worker processes / `multiprocessing` do not inherit the id; future worker
  code must call `new_run_id()` on entry.

## Reference stage skeleton

New stage modules under `engine/` must follow this pattern:

```python
"""
<Stage> for RWA Calculator.

Pipeline position:
    <previous-stage> -> <this-stage> -> <next-stage>

Key responsibilities:
- ...

References:
- ...
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.contracts.bundles import ...

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig

logger = logging.getLogger(__name__)


class MyStage:
    def run(self, data, config: CalculationConfig):
        # INFO entry/exit + elapsed_ms come from the orchestrator wrap; use
        # DEBUG here for branch decisions that are cheap to compute.
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("routing %d rows via fast path", row_count)
        ...
```

The orchestrator wraps the stage's main call with `stage_timer`:

```python
with stage_timer(logger, "my_stage"):
    result = self._my_stage.run(data, config)
```

## Enforcement

The contract is enforced by four mutually-reinforcing mechanisms:

1. **ruff rules** (`pyproject.toml` `[tool.ruff.lint]`): `G`
   (flake8-logging-format — no f-strings in log calls), `LOG`
   (flake8-logging — no deprecated APIs), `T20` (flake8-print — no
   `print()` outside `tests/` and marimo workbooks).
2. **Architecture check** (`scripts/arch_check.py` check 8): every non-exempt
   engine module declares a module logger; `print(` and `logging.basicConfig(`
   are forbidden in `engine/**`. Helper modules are listed in
   `LOGGER_REQUIRED_EXEMPT`.
3. **Contract test** (`tests/contracts/test_logging_contract.py`): iterates
   every stage module and asserts it exports a `logger` attribute of the
   correct `logging.Logger` name.
4. **Integration test** (`tests/integration/test_logging_pipeline.py`): runs
   the full pipeline and asserts entry/exit record pairs, shared `run_id`,
   no handler stacking across runs, and no duplication of
   `CalculationError.message` in log output.

## Anti-patterns

- `f"got {n} rows"` — use lazy formatting (`"got %d rows", n`). Ruff `G004`.
- `logging.basicConfig(level=...)` — use `configure_logging`. Ruff `LOG` +
  arch_check.
- `print(...)` for debugging — ruff `T20` catches this.
- `lf.collect().height` just to log a count — forbidden; defer to the
  aggregator which materialises once. Caught in code review.
- Logging a `CalculationError.message` verbatim — caught by the integration
  test.
