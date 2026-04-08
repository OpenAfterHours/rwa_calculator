# Documentation Review & Regulatory Completeness Prompt

## Ultimate Goal

Ensure `docs/` is a **complete, accurate regulatory reference** for developers and auditors — covering both CRR and Basel 3.1 rules the calculator implements, with clear documentation of the differences between them.

## Important Constraints

- **Plan only.** Do NOT implement anything within `src/`.
- Do NOT assume functionality is missing; confirm with code search first.
- Treat `src/rwa_calc/contracts/` and `src/rwa_calc/domain/` as the project's shared protocols, bundles, and enums. Prefer consolidated, idiomatic implementations there over ad-hoc copies.
- Primary output artifact: `DOCS_IMPLEMENTATION_PLAN.md` — a prioritised bullet-point list of documentation gaps and fixes.

---

## Phase 0: Orientation

Study existing state before comparing anything.

0a. Study `docs/` structure with up to 3 parallel Explore subagents:
   - Agent 1: `docs/specifications/` — catalogue every spec file, note which have scenario IDs and acceptance criteria
   - Agent 2: `docs/framework-comparison/` + `docs/user-guide/regulatory/` — catalogue CRR↔B31 comparison content
   - Agent 3: `docs/user-guide/methodology/` + `docs/user-guide/exposure-classes/` — catalogue rule explanations

0b. Study `DOCS_IMPLEMENTATION_PLAN.md` (if present) to understand progress so far.

0c. Study `src/rwa_calc/` with up to 3 parallel Explore subagents to understand what the calculator actually implements:
   - Agent 1: `src/rwa_calc/engine/` — SA, IRB, slotting, equity calculators
   - Agent 2: `src/rwa_calc/pipeline/` + `src/rwa_calc/domain/` — pipeline stages, enums, regulatory tables
   - Agent 3: `src/rwa_calc/contracts/` — protocols, bundles, schemas

---

## Phase A: Regulatory Completeness (docs vs PDFs)

**Question:** Do the docs accurately and completely capture the rules from the regulatory PDFs?

### PDF-to-Docs Mapping

Use pymupdf to extract text from PDFs in `docs/assets/`. Assign agents by topic area, not arbitrary count.

| PDF | Maps to | Agent scope |
|-----|---------|-------------|
| `ps126app1.pdf` | `specifications/`, `framework-comparison/` | Basel 3.1 SA risk weights, IRB parameters, CRM, CCFs, output floor |
| `crr.pdf` | `specifications/crr/` | CRR SA risk weights, IRB, CRM, CCFs, supporting factors |
| `comparison-of-the-final-rules.pdf` | `framework-comparison/` | CRR↔B31 deltas |
| COREP instruction PDFs (×4) | `features/corep-reporting.md` | Reporting template accuracy |
| Pillar 3 instruction PDFs (×3) | `features/pillar3-disclosures.md` | Disclosure template accuracy |

### What to Check

Use up to 3 Sonnet subagents per topic area (run multiple rounds if needed). Each agent should check:

1. **Missing risk weight tables** — Does Basel 3.1 SA real estate loan-splitting have full documentation? Are ECRA/SCRA tables for institutions complete?
2. **Incorrect article references** — CRR article numbers that changed or don't exist in PS1/26
3. **Missing regulatory formulas** — IRB K formula, maturity adjustment, correlation parameters, PD/LGD floor values
4. **Undocumented CRR→B31 parameter changes** — PD floors, LGD floors, CCF changes, output floor mechanics, removal of 1.06 scaling, removal of supporting factors
5. **Missing exposure class treatments** — Basel 3.1 adds real estate as standalone class, corporate sub-categories (investment grade, project finance), retail qualifying criteria changes
6. **Completeness of `docs/specifications/`** — CRR has 8 spec files; Basel 3.1 has **zero** dedicated spec files (only a link to framework-comparison). Every CRR spec should have a B31 equivalent or explicit "unchanged" note.

### Analysis

Use up to 3 Opus subagents to:
- Synthesise findings from the Sonnet agents
- Prioritise gaps by regulatory importance (e.g., missing risk weight tables > minor article reference typos)
- Update files in `docs/` where gaps are found

---

## Phase B: Code-Docs Alignment (docs vs source code)

**Question:** Does the source code implement what the docs describe, and vice versa?

Study `IMPLEMENTATION_PLAN.md` (at project root) for current implementation status.

Use up to 3 Sonnet subagents to compare `src/rwa_calc/` against `docs/specifications/` and `docs/user-guide/methodology/`:

1. **Documented but not implemented** — Rules described in docs that have no corresponding code (check for TODOs, stubs, placeholder implementations)
2. **Implemented but not documented** — Code logic with no corresponding docs entry (search for regulatory comments in code that aren't reflected in docs)
3. **Inconsistencies** — Risk weights, formulas, or parameters that differ between docs and code
4. **Missing scenario IDs** — Specs without traceability to acceptance tests

Also search for: `TODO`, `FIXME`, `HACK`, `PLACEHOLDER`, `NotImplementedError`, skipped/flaky tests, and `pytest.mark.skip`.

### Analysis

Use up to 3 Opus subagents to:
- Analyse findings from Phase B
- Cross-reference with Phase A findings
- Create/update `DOCS_IMPLEMENTATION_PLAN.md` as a prioritised bullet-point list

---

## Output: DOCS_IMPLEMENTATION_PLAN.md

The final artifact should be structured as:

```markdown
# Documentation Implementation Plan

Last updated: YYYY-MM-DD

## Priority 1: Critical Gaps (missing or incorrect regulatory content)
- [ ] Item...

## Priority 2: Basel 3.1 Specification Parity (B31 specs matching CRR depth)
- [ ] Item...

## Priority 3: Code-Docs Alignment (mismatches between docs and source)
- [ ] Item...

## Priority 4: Minor Fixes (article references, formatting, broken links)
- [ ] Item...

## Completed
- [x] Item...
```

## Success Criteria

- Every CRR article referenced in code has a corresponding docs entry
- Every Basel 3.1 PS1/26 section implemented has a specification with scenario IDs
- Every CRR↔B31 difference is documented in `framework-comparison/`
- Risk weight tables in docs are complete and match the regulatory PDFs
- `docs/specifications/` has equivalent depth for both CRR and Basel 3.1
