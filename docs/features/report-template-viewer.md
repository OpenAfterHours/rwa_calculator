# Report Template Viewer

View the COREP and Pillar III templates a run produced **on screen**, sheet by sheet — the same
figures the regulatory workbooks export, without downloading a workbook to read one number.

The viewer is the foundation for report-cell drill-down: every cell it renders is addressable, so a
later slice can attach lineage ("which exposures and rules produced this number?") to a cell you can
actually see and click.

## Using it

From a completed run's results page, follow **View report templates** (or go straight to
`/results/{run_id}/templates`).

- **Template picker** — every template the run produced, grouped COREP / Pillar III. A template that
  did not apply to the portfolio or the regime is *absent*, not empty: a CRR run offers no output-floor
  templates, and a portfolio with no IRB book offers no C 08 family.
- **Sheet picker** — per-sheet templates (C 07.00 and C 08.x by exposure class, C 09.0x by country,
  C 34.02 by netting set, CR6/CR9 by class) select one sheet at a time.
- **The grid** — regulatory row refs and names down the side, 4-digit column refs across the top under
  their logical group band (Exposure / CRM Substitution / RWEA …). Hover a column ref for its full name.

Templates are generated once per run and cached, so switching template or sheet is a re-render, not a
recalculation.

## Reading a cell correctly

!!! warning "A blank cell is not a zero"

    The grid shows **`—`** for a null cell and **`0`** for a reported zero. These mean different things
    and the viewer deliberately does not flatten them:

    - **`0`** — the cell was computed and the answer is zero.
    - **`—`** — the cell is not reported: an inert or empty row, or a value whose source the engine does
      not produce (for example C 07.00 columns 0230/0235 need an ECAI credit-quality step, which the
      calculation ledger does not carry).

    Distinguishing the two is what a later drill-down makes explicit; today the viewer marks them apart
    but cannot yet tell you *why* a given cell is blank.

Cells are shown **exactly as the generator produced them**, including the COREP Annex II §1.3 sign
convention — deduction columns labelled "(-)" (0030, 0035, 0050–0090, 0130, 0140) are reported as
negative figures. Nothing in the viewer recomputes, re-signs or re-fills a value.

## The API

Two additive read endpoints back the page; both take a `run_id` from a completed run.

| Endpoint | Returns |
|---|---|
| `GET /api/templates?run_id=…` | The templates this run produced: `id`, `title`, `family`, `sheets`, `sheet_label` |
| `GET /api/templates/{template_id}?run_id=…&sheet=…` | One sheet: `columns` (ref, name, group) and `rows` |

`sheet` is optional — omitted, it takes the template's first sheet. An unknown run, template or sheet
is a `404`.

```bash
curl "http://localhost:8000/api/templates/c07_00?run_id=$RUN&sheet=corporate"
```

```json
{
  "template": {"id": "c07_00", "title": "C 07.00 — SA credit risk", "family": "corep"},
  "sheet": "corporate",
  "columns": [{"ref": "0220", "name": "Risk weighted exposure amount post SF", "group": "RWEA"}],
  "rows": [{"row_ref": "0010", "row_name": "Total exposures", "0220": 1000000.0}]
}
```

Template ids are the bundle field names (`c07_00`, `c08_01`, `cr5`, `ov1`, …) — the same ids the
rulepack's `ReportingTemplateSet` carries. Together with a sheet, a row ref and a column ref they form
the **cell key** `(template_id, sheet, row_ref, col_ref)` that addresses one reported figure. The
viewer stamps that key on every rendered cell.

## Scope

- Covers every template the two generators produce — the full COREP credit-risk estate (C 02.00,
  C 07.00, C 08.01–07, C 09.01/02, OF 02.01, C 34.x) and the Pillar III suite (OV1, CR4–CR10,
  CMS1/2, CCR1–8).
- Read-only. The workbook exports (COREP / Pillar III) remain the submission artefacts; the viewer is
  for inspection.
- **Click a cell to see which exposures and rules produced it** — see
  [Report Cell Lineage](report-cell-lineage.md). Cells are only clickable on templates that have
  lineage (C 07.00 today).

## References

- Regulation (EU) 2021/451, Annex I/II — COREP template layouts
- CRR Part 8 — Pillar III disclosure templates
- [COREP Reporting](corep-reporting.md) · [Pillar III Disclosures](pillar3-disclosures.md)
