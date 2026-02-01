import marimo

__generated_with = "0.19.6"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import polars as pl
    from pathlib import Path
    return Path, pl


@app.cell
def _(Path, pl):
    files = [
        ('counterparty', 'corporate'), 
        ('exposures', 'loans'), 
        ('exposures', 'facilities'),
        ('exposures', 'facility_mapping'),
        ('mapping', 'lending_mapping'),
        ('ratings', 'ratings'),
        ('collateral', 'collateral'),
    ]

    for folder, file_name in files:
        output_path = Path(rf"C:\Users\philm\PycharmProjects\rwa_calculator\tests\sample_data\{folder}\{file_name}.parquet")
        try:
            df = pl.read_excel(r"C:\Users\philm\PycharmProjects\rwa_calculator\tests\sample_data\sample_data_5.xlsx", sheet_name=file_name)
            df.write_parquet(output_path)
        except Exception as e:
            print(f"Error processing {file_name}: {e}")
            if output_path.exists():
                output_path.unlink()
                print(f"Deleted {output_path}")
    return


if __name__ == "__main__":
    app.run()
