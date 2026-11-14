# rwa-filer

Validate regulatory returns against the published supervisory rules and write
them in the format the regulator accepts.

It carries the Bank of England's validation rules for banking taxonomy v4.1.1
and evaluates them as the Bank's gateway does, for 14 reporting modules
(`PRA001`, `PRA116`, Capital+, leverage, MREL and financial statements).

**Documentation:** <https://openafterhours.github.io/rwa_calculator/rwa-filer/>

`rwa-filer` is a standalone package. It lives in the
[rwa_calculator](https://github.com/OpenAfterHours/rwa_calculator) repository as a
uv workspace member and is released separately from `rwa-calc`: it depends on
Polars and, for its dashboard, a small web stack (Starlette, uvicorn, Jinja2), and
never imports `rwa_calc`. `rwa-calc` uses it to validate the
returns it generates; any other system that can produce template-level figures
can use it the same way.

```bash
pip install rwa-filer
```

```bash
# The dashboard: open a return in the browser and walk from the verdict to the
# broken rules to the cells on the template grid that broke them
uvx rwa-filer dash return.xbrl
```

```bash
# Check a return: structure against the taxonomy, then the published rules
rwa-filer validate return.parquet \
    --entity 5493001KJTIIGC8Y1R12 --reference-date 2027-03-31 --module PRA001

# Validate it and write the XBRL submission file, with a manifest
rwa-filer build return.parquet --out filing/ \
    --entity 5493001KJTIIGC8Y1R12 --reference-date 2027-03-31 --module PRA001

# Record an approval against the file's checksum, and check it before upload
rwa-filer signoff filing/<name>.manifest.json --approver "C. Approver" --role "Head of Reporting"
rwa-filer verify filing/<name>.manifest.json

# What changed since the version already filed
rwa-filer diff filed.xbrl resubmission.xbrl

# A second opinion: have the Arelle XBRL processor check the written file
# against the Bank's taxonomy package, and compare its verdict on every rule
# with this package's own (needs rwa-filer[arelle] and the Bank's package)
rwa-filer referee filing/<name>.xbrl --taxonomy-package boe-banking-v411.zip

# A blank workbook in the template layout, to fill in and validate
rwa-filer template --module PRA001 --reference-date 2027-03-31 --out return.xlsx

rwa-filer --help
```

A return is a table with one row per reported cell (`table`, `sheet`,
`open_key`, `row`, `column`, `value`), read from Parquet or CSV, or an Excel
workbook in the template layout (needs `rwa-filer[excel]`), or an XBRL instance
written by any system.

> The regulator's own validation on upload is authoritative. A clean result
> from `rwa-filer` is evidence a return is well-formed, not a guarantee that it
> will be accepted.

See [CHANGELOG.md](CHANGELOG.md) for release notes.
