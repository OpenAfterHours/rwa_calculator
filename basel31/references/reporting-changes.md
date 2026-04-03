# Basel 3.1 Reporting Changes

Summary of COREP and Pillar 3 template changes from CRR to Basel 3.1.

---

## Template Renames

### COREP (Supervisory Reporting)

| CRR (C prefix) | Basel 3.1 (OF prefix) | Purpose |
|----------------|----------------------|---------|
| C 02.00 | OF 02.00 | Own funds requirements |
| — | OF 02.01 | Output floor comparison (**new**) |
| C 07.00 | OF 07.00 | SA credit risk |
| C 08.01 | OF 08.01 | IRB totals |
| C 08.02 | OF 08.02 | IRB by obligor grade |
| C 08.03 | OF 08.03 | IRB by PD ranges |
| C 08.04 | OF 08.04 | IRB RWEA flow |
| C 08.06 | OF 08.06 | Specialised lending slotting |
| C 08.07 | OF 08.07 | Scope of IRB/SA use |
| C 09.01 | OF 09.01 | Geographical breakdown SA |
| C 09.02 | OF 09.02 | Geographical breakdown IRB |

### Pillar 3 (Public Disclosure)

| CRR (UK prefix) | Basel 3.1 (UKB prefix) | Purpose |
|-----------------|----------------------|---------|
| UK OV1 | UKB OV1 | Overview of RWEAs |
| UK CR4 | UKB CR4 | SA exposure & CRM effects |
| UK CR5 | UKB CR5 | SA risk weight allocation |
| UK CR6 | UKB CR6 | IRB by PD range |
| UK CR6-A | UKB CR6-A | Scope of IRB/SA use |
| UK CR10 | UKB CR10 | Slotting exposures |

## Five Key Themes

1. **Removal of capital relief** — supporting factor columns removed across all templates;
   double default column removed
2. **Output floor infrastructure** — new columns (0275-0276) in IRB templates for
   SA-equivalent values; new OF 02.01 template for U-TREA vs S-TREA comparison
3. **Greater granularity** — SA risk weight bands 15 -> 29; detailed RE breakdowns;
   SL sub-categories; corporate sub-rows
4. **Post-model oversight** — new columns (0251-0254, 0281-0282) for model overlays
   and regulatory floors
5. **Scope-of-use transparency** — OF 08.07 expands 5 -> 18 columns with RWEA
   breakdown by SA reason

## Key Structural Changes

| Area | CRR | Basel 3.1 |
|------|-----|-----------|
| SA risk weight rows | 15 (0%-1250%) | 29 (adds 15%, 25%, 30%, 40%, 45%, 60%, etc.) |
| SA CCF buckets | 0%, 20%, 50%, 100% | 10%, 20%, 40%, 50%, 100% |
| IRB approach filter | Foundation / Advanced | Foundation / Advanced / **Slotting** |
| SL types in slotting | 4 (IPRE+HVCRE combined) | 5 (HVCRE separated) |
| CR10 sub-templates | PF, IPRE+HVCRE, OF, CF, **Equity** | PF, IPRE, OF, CF, **HVCRE** |

---

> **Full detail:** `docs/framework-comparison/reporting-differences.md` and `docs/framework-comparison/disclosure-differences.md`
