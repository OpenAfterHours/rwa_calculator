# Project Plans

This section contains project planning documents and phase tracking for the RWA Calculator.

## Overview

The project follows a **phased, test-first approach** prioritising CRR (Basel 3.0) implementation before extending to Basel 3.1.

## Documents

- [**Implementation Plan**](implementation-plan.md) - Detailed acceptance test scenarios, contract definitions, and regulatory parameters
- [**Target Architecture & Migration Plan**](target-architecture-migration.md) - Architecture review findings, the rulepack target architecture, and the phased (0-8) strangler migration plan
- [**Engine Defensiveness — Boundary Hardening**](engine-defensiveness-boundary-hardening.md) - Producer-enforced stage-contract investigation; folded into migration Phase 3 (includes the binding KEEP-guard triage)
- [**Single-Lazy-Plan Refactor**](single-lazy-plan-refactor.md) - SUPERSEDED by migration Phase 1; preserves the Polars plan-depth SIGSEGV evidence and the irreducible-barrier finding
- [**UI Output Folder**](ui-output-folder.md) - Let a UI user write calculation outputs to a chosen local folder (server-side write, run-stamped subfolder, network guard); phased TDD plan
- [**Return Reconciliation**](return-reconciliation.md) - Proposed: compare a generated template (e.g. C 08.03) against the firm's current return cell by cell, and decompose each delta into population / row placement / sheet placement / measurement
- [**Independent Validation System**](independent-validation-system.md) - Why a green suite keeps shipping template defects, and the six-component plan (impact report, property suite, shadow calculator, cell re-derivation, coverage ratchets, defect-injection scorecard) to fix it
- [**Architecture Review — structure, efficiency, parallelism (2026-08-29)**](architecture-review-2026-08-29.md) - Measured review of `engine/stages/` layout, reporting-vs-calculation cost, and thread scaling; a sequenced proposal (proposal only, nothing implemented)
- [**Facility Share — Riskiest Member by Applied Approach**](facility-share-riskiest-member.md) - Proposal: allocate a shared facility's undrawn to the member with the highest RWA under its *own* approach (candidate fan-out, resolved before the output floor), and the two-assignment rule that makes "riskiest" well-defined under the Basel 3.1 floor (approved and implemented 2026-09-05; methodology in Specifications → Facility Share Allocation)
- [**Test-Suite Runtime (proposed)**](test-suite-runtime-proposal.md) - Measured: the dev loop's 6m47s is ~1,300 tests that each run a pipeline or a COREP generation, not per-test overhead; five ranked levers (memoise repeat runs, cut the per-run fixed cost, compile COREP cells once, tail, collection) to ~4m15s with identical tests (proposal only, nothing implemented)
- [**rwa-filer Evidence Export (implemented)**](rwa-filer-evidence-export.md) - Measured against rwa-filer 0.1.2: what the validation JSON left out (passing rules, all but five failures per rule, interval semantics and allowances, fingerprints), an Error-severity rule on which `validate` and `build` disagreed, a missing rule book reported as clean; the phased design for a complete, versioned evidence export with an explicit completeness status, and what landed (implemented 2026-11-15 in rwa-filer; rwa-calc integration follows the 0.2.0 release)
- [**Taxonomy Release Selection (implemented)**](taxonomy-release-selection.md) - rwa-filer: let the user choose the taxonomy release per run by version (`--taxonomy <version>`; by default the release live for the return's module), take the pack and rule book from the same release, say on every run which release was used, ship as many named releases as are needed, and package the next one with a single build script (implemented 2026-11-15; verified byte for byte on the Bank's 4.1.1 files)

## Development Philosophy

The project adheres to these core principles:

1. **Test-Driven Development (TDD)** - Tests are written before implementation
2. **Phased Delivery** - Features are delivered incrementally with clear milestones
3. **Regulatory Accuracy** - All calculations are validated against regulatory specifications
4. **Performance First** - LazyFrame operations and vectorized calculations throughout

