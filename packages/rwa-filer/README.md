# rwa-filer

Validate regulatory returns against the published supervisory rules and write
them in the format the regulator accepts.

`rwa-filer` is a standalone package. It lives in the
[rwa_calculator](https://github.com/OpenAfterHours/rwa_calculator) repository as a
uv workspace member and is released separately from `rwa-calc`: it depends on
Polars alone and never imports `rwa_calc`. `rwa-calc` uses it to validate the
returns it generates; any other system that can produce template-level figures
can use it the same way.

```bash
pip install rwa-filer
```

```bash
# Check a return: structure against the taxonomy, then the published rules
rwa-filer validate return.parquet \
    --entity 5493001KJTIIGC8Y1R12 --reference-date 2027-03-31 --module PRA001

# Validate it and write the XBRL submission file, with a manifest
rwa-filer build return.parquet --out filing/ \
    --entity 5493001KJTIIGC8Y1R12 --reference-date 2027-03-31 --module PRA001

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
