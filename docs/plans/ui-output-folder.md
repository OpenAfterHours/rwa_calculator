# UI Output Folder — Write Calculation Results to a Chosen Local Folder

**Status:** In progress · **Owner:** UI surface (`src/rwa_calc/ui/app/`) + `api/` export layer
**Goal:** Let a UI user choose where calculation outputs are written on disk, instead of
the results living only in an in-memory registry reachable through a hand-typed REST URL.

## Problem

Today the `/calculator` form collects only `data_path`, reporting date, framework,
permission mode and the **input** `data_format` — there is no output destination. A run
registers its `CalculationResponse` in an in-memory registry (`_RUNS`, keyed by `run_id`)
and the only way to get files out is `GET /api/export/{fmt}?run_id=…`, which streams a
browser **download** from a server temp dir. `results.html` surfaces this only as inert
text, not even a button. In most real use the operator wants the outputs written to a
folder they choose.

## Enabling fact

The write primitive already exists. `CalculationResponse.to_parquet(dir)` / `to_csv(dir)` /
`to_excel(path)` / `to_corep(path)` (`api/models.py`) already `mkdir(parents=True)` and
return a frozen `ExportResult(format, files, row_count)`. Because the app is a loopback
single-user uvicorn process (`127.0.0.1`, no sandbox — `ui/app/main.py`), **a server-side
write is a write to the user's own disk.** So this is wiring, a validator, and a guard —
not new low-level writer code.

## Recommendation

Adopt **server-side write driven by a plain text "Output folder" field** (mirroring the
existing `data_path` field), reusing the `to_*` wrappers. Two write entry points share one
helper so they can never drift:

1. **`POST /results/{run_id}/save`** (primary) — write an already-computed run's selected
   formats on demand, gated on the unguessable `run_id` from `_RUNS`.
2. **Calc-time write** — an optional "Output folder" + "Output format(s)" on the calculator
   form so one submit runs *and* writes; folder/formats remembered for next time.

Plus real **Download buttons** on the results page (the safe half of the browser approach —
the existing endpoint, zero new server code).

### Why not the alternatives

| Approach | Verdict | Reason |
|---|---|---|
| **A. Text field + server write** | **Adopt** | Reuses existing writers; server == disk so no round-trip; fully testable via `TestClient`; can echo the absolute path written. |
| B. Browser File System Access API | Reject (keep only download buttons) | Chromium-only; the load-bearing JS write path is untestable in the pytest stack (violates TDD); buffers the whole export in browser memory; can only show the folder leaf name; multi-file parquet/csv arrive as a ZIP. Round-trips bytes through the browser to reach a folder Python can write directly. |
| C. Server-side `/api/browse` directory picker | Reject | Adds a filesystem-**enumeration oracle** — the largest net-new attack surface — for a marginal "don't type a path" gain a text field already satisfies. A server-side `tkinter.filedialog.askdirectory()` is a safer fallback if that UX is ever required. |

## Two non-obvious findings that gate this work

### 1. The server has zero network protection today
`create_app()` (and `create_api_app()`) mount the router with **no TrustedHost / CORS /
Origin middleware**, and there is no DNS-rebinding defence. Adding any user-driven write
endpoint turns the app into a **remotely-triggerable arbitrary-file-write gadget**: a form
POST is a CORS "simple request" (no preflight), so a malicious page the user visits can
submit it cross-origin (CORS blocks reading the response, not the side effect); DNS
rebinding (`evil.com → 127.0.0.1`) defeats even that barrier. **The network guard
(`TrustedHostMiddleware(['localhost','127.0.0.1'])` + an `Origin`/`Sec-Fetch-Site`
same-origin check on state-changing routes) must land before any write endpoint ships.**
This is the dominant risk — not path traversal (the path is *intended* to be arbitrary).

### 2. Fixed filenames + 4 workers = silent data loss
All writers use fixed names (`results.parquet`, `summary_by_class.parquet`, …) with
`exist_ok=True`. Re-exporting into a folder silently clobbers the user's existing
same-named files, and two concurrent runs targeting one folder race on the same names.
**Fix both at once by writing into a run-stamped subfolder** `<chosen>/rwa_export_<run_id>/`
and echoing the resolved absolute path back.

## Phased plan (smallest shippable slice first)

Each phase is TDD (failing test first) and ends with the gate:
`uv run python scripts/arch_check.py`, `uv run ruff check`/`format`, `uv run ty`, contract
tests, then `uv run pytest tests/`.

### Phase 1 — Download buttons (no new write surface)
- `ui/app/main.py` `_results_context`: add `export_parquet_url`/`export_csv_url`/
  `export_excel_url`/`export_corep_url` = `/api/export/{fmt}?run_id={run_id}`; add
  `xlsx_available = importlib.util.find_spec("xlsxwriter") is not None`.
- `templates/results.html`: replace the inert REST text with `.btn .btn-ghost` anchors
  (copy `reconciliation.html` CSV/Excel pattern); grey/disable excel+corep when
  `not xlsx_available`.
- **Failing test:** `tests/integration/test_ui_app.py` — `/results/{run_id}` body contains
  the four `/api/export/{fmt}?run_id=` anchors.

### Phase 2 — Network guard (prerequisite for any write)
- `ui/app/main.py` `create_app()`: add `TrustedHostMiddleware(allowed_hosts=
  ["localhost","127.0.0.1"])`; keep the `127.0.0.1` bind.
- `ui/app/main.py`: add a `require_same_origin(request)` dependency that rejects
  state-changing requests whose `Origin`/`Sec-Fetch-Site` is cross-site; attach it to
  `POST /calculate` and `POST /results/{run_id}/save`.
- **Test trap:** `TestClient` sends `Host: testserver` → rejected by `TrustedHostMiddleware`.
  Build fixtures with `TestClient(create_app(), base_url="http://localhost")` rather than
  widening the allowlist.
- **Failing tests:** `Host: evil.com` → rejected; cross-site `Origin` on a POST → rejected;
  `localhost` still 200.

### Phase 3 — Shared write helper + output-path validator (pure, unit-tested)
- `ui/app/output_writer.py` (NEW): `@dataclass(frozen=True, slots=True)
  OutputWriteResult(folder, files, errors)` and `write_selected_formats(response, folder,
  formats, *, run_id) -> OutputWriteResult`. Builds `subdir = folder / f"rwa_export_{run_id}"`;
  `parquet→to_parquet(subdir)`, `csv→to_csv(subdir)`, `excel→to_excel(subdir/"rwa_results.xlsx")`,
  `corep→to_corep(subdir/"rwa_corep.xlsx")`; collect each `ExportResult.files`; **catch**
  `ModuleNotFoundError` (xlsxwriter) and `OSError` → append a user-facing string to `errors`,
  never raise. Atomic-ish: write to a temp sibling and `os.replace` on full success.
- `api/validation.py`: add `validate_output_path(output_path) -> ValidationResponse`
  (sibling to `validate_data_path`; reuse `APIError`/`ValidationResponse`/`create_validation_error`
  VAL001; **do not** reuse the required-files machinery). Checks: resolvable + **absolute**
  (reject relative — cwd is ephemeral in the packaged `.pyz`); reject Windows reserved device
  names (`CON`, `NUL`, `COM1`, `LPT1`, …); if it exists it must be a directory; else its
  nearest existing ancestor must exist and be writable; `os.access(W_OK)` treated as advisory.
- **Failing tests:** `tests/unit/api/test_export.py` (writer: files land under
  `tmp/rwa_export_<run_id>/`; a monkeypatched `to_excel` raising `ModuleNotFoundError` is
  captured in `.errors`, not raised) and `tests/unit/api/test_api_validation.py`
  (`validate_output_path` matrix).

### Phase 4 — `POST /results/{run_id}/save` (primary feature)
- `ui/app/main.py`: module-level `ExportFormatArg = Literal["parquet","csv","excel","corep"]`
  alongside `FrameworkArg`/`PermissionArg`/`FormatArg` (module-level so ruff's fix hook
  doesn't strip the quotes under `from __future__ import annotations`).
- New `@app.post("/results/{run_id}/save")` with `require_same_origin`: `get_run(run_id)` →
  friendly **404 "this result has expired — re-run"** if `None` (mirror
  `_RECON_NOT_FOUND_MESSAGE`, never 500); `validate_output_path` → 400 re-render on failure;
  else `write_selected_formats(...)` and re-render `results.html` with the written-files /
  per-format-error callout echoing the **resolved absolute** subfolder.
- `_results_context`: add `default_output_folder` + `export_formats` for the save form.
- `templates/results.html`: add a `<form method="post" action="/results/{{ run_id }}/save">`
  block (folder input + format checkboxes + submit) near "Run another"; render the callout.
- **Failing tests:** save writes files under `<tmp>/rwa_export_<run_id>/`; unknown id → 404;
  unwritable/relative folder → 400; cross-site `Origin` → rejected.

### Phase 5 — Calc-time write + form fields + remembered last-run
- `POST /calculate`: add `output_folder: Annotated[str, Form()] = ""` and
  `output_formats: Annotated[list[str], Form()] = []`; `require_same_origin`; if folder
  non-empty `validate_output_path` → 400 re-render preserving **all selects + folder +
  formats**; thread both into `_calculation_worker`.
- `_calculation_worker`: after `register_run_with_id`, if folder set call
  `write_selected_formats(...)` and stash the `OutputWriteResult` in a module-level
  `_EXPORT_OUTCOMES: dict[str, OutputWriteResult]`; then `save_calculator_state(...)`. Write
  happens **after** `calculate()` and **outside `STAGE_SEQUENCE`**, so the live stepper stays
  responsive and the existing `total_stages == 10` assertion holds.
- `ui/app/calculator_state.py` (NEW): `@dataclass(frozen=True, slots=True)
  CalculatorFormState(...)` — all `str`; `output_formats` **comma-encoded** to satisfy the
  recon_state all-strings invariant. `save/load/clear_calculator_state` (distinct names —
  `recon_state.save_last_run` is already imported), JSON at `$RWA_STATE_DIR/
  calculator_last_run.json` else `~/.rwa_calc/...`; both swallow IO/parse errors.
- `GET /calculator`: pre-fill from `load_calculator_state` (override > saved > fallback); add
  `selected_framework`/`selected_permission`/`selected_format` + `default_output_folder` +
  `selected_output_formats`. Default folder computed at **submit time** from the posted
  `data_path` (`Path(data_path).parent/"rwa_output"`, fallback `Path.home()/"Downloads"` then
  `Path.home()`) — never `__file__`/cwd.
- `templates/calculator.html`: full-width optional `output_folder` text input under
  `data_path` (no `required`); an "Output format(s)" checkbox group `name=output_formats`
  (labelled distinctly from the existing input-format "Data format" select); retrofit
  `{% if selected_* %}selected{% endif %}` on the framework/permission/data_format selects so
  a validation bounce is non-destructive.
- **Failing tests:** `tests/unit/ui/test_calculator_state.py` (round-trip incl. comma-encoded
  formats); integration POST `/calculate` with folder+formats → files on disk under
  `<tmp>/rwa_export_<run_id>/`; `total_stages == 10` still holds; invalid folder → 400 with
  selects preserved.

## Decided defaults

- **Scope:** full (Phases 1–5).
- **Formats:** pre-tick `parquet` + `csv`; offer `excel`/`corep` but grey them out with a
  friendly message when `xlsxwriter` is absent (it stays an optional dependency).
- **Overwrite policy:** run-stamped subfolder `rwa_export_<run_id>` (no clobber, no race).
- **Default folder:** derived at submit-time from `data_path`, with `~/Downloads` then
  `~` fallback.
- **Remember last folder/formats:** yes (`calculator_state.py`, mirroring `recon_state`).
- **Pillar3:** out of scope (no `CalculationResponse` wrapper, not in the export `Literal`).

## Must-have guardrails → where enforced

| Guardrail | Enforced in |
|---|---|
| Network guard first — `TrustedHostMiddleware` + `require_same_origin`; bind stays `127.0.0.1` | Phase 2; applied on `POST /calculate` (P5) and `POST /results/{run_id}/save` (P4) |
| Save is POST, gated on unguessable uuid4 `run_id`; `output_folder` is the only user string reaching the FS; `run_id` never a path component | Phase 4 route |
| Run-stamped subfolder kills silent clobber **and** the `max_workers=4` race; echo resolved absolute dest | Phase 3 `write_selected_formats` |
| Non-raising output-path validation (absolute, reject relative + reserved names, dir-or-creatable-ancestor, advisory `os.access`) | Phase 3 `validate_output_path`; wired P4 + P5 |
| Atomic-ish honest writes — temp + `os.replace`; per-format `try/except`; never raise mid-write; report exactly what was written vs failed; no "success" on partial failure | Phase 3 `output_writer` |
| Clean expiry — `run_id` absent from `_RUNS` (no TTL, restart-only) or a cleaned `rwa_cache_*` → friendly 404, never 500 | Phase 4 route; Phase 1 downloads |
| xlsxwriter capability probe — grey out excel/corep with a friendly message; writer catches the raised `ModuleNotFoundError` | Phase 1 `_results_context`; Phase 3 writer |
| Cross-platform path discipline — `pathlib` throughout, `expanduser().resolve()`, validate UNC share roots, MAX_PATH note, default from posted `data_path` not `__file__`/cwd | Phase 3 validator; Phase 5 default computation |
| TDD seams + `total_stages == 10` invariant (write after `calculate()`, outside `STAGE_SEQUENCE`) | Failing test per phase; Phase 5 worker hook |
| Document the conscious reversal of the "no user input in FS paths" posture (`rest.py` temp-dir + literal names), acceptable only under loopback single-user | Phase 4/5 spec + changelog |

## Key files

- `src/rwa_calc/ui/app/main.py`
- `src/rwa_calc/ui/app/output_writer.py` (new)
- `src/rwa_calc/ui/app/calculator_state.py` (new)
- `src/rwa_calc/ui/app/templates/calculator.html`, `templates/results.html`
- `src/rwa_calc/api/validation.py`, `api/export.py`, `api/models.py`, `api/rest.py`
- `src/rwa_calc/contracts/results.py`
- `tests/unit/api/test_export.py`, `tests/unit/api/test_api_validation.py`
- `tests/unit/ui/test_calculator_state.py` (new), `tests/integration/test_ui_app.py`
- `docs/specifications/interfaces.md`, `docs/specifications/output-reporting.md`,
  `docs/user-guide/interactive-ui.md`, `docs/appendix/changelog.md`
