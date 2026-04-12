## Summary
<!-- One-line description of what this PR achieves -->

## Regulatory Context
<!-- Which Basel 3.1 requirement(s) does this relate to? Reference PS9/24 sections, CRR articles, or Basel standards where relevant -->

## Changes

### Calculation Logic
<!-- Any changes to RWA formulas, risk weights, or regulatory treatments -->

### Data Model
<!-- Changes to schemas, Polars DataFrames, or data structures -->

### Other
<!-- Config, tests, documentation, refactoring -->

## Testing
<!-- How was this validated? Include sample calculations if relevant -->
- [ ] Unit tests pass
- [ ] Calculation outputs verified against manual/Excel check
- [ ] Edge cases considered (e.g. missing data, boundary values)
- [ ] Any new regulatory value lives in `src/rwa_calc/data/tables/`; any new input-domain validation enum lives in `src/rwa_calc/data/schemas.py` (not in `engine/**`) — `uv run python scripts/arch_check.py` passes

## Assumptions & Interpretations
<!-- Document any regulatory interpretation decisions made - these are valuable for audit trail -->

## Breaking Changes
<!-- Any changes to inputs, outputs, or behaviour that would affect existing usage -->

## Related
<!-- Link issues, reference PRA/Basel docs consulted -->