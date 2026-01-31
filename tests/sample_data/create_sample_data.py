import marimo

__generated_with = "0.19.6"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import polars as pl
    return (pl,)


@app.cell
def _(pl):
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
        df = pl.read_excel(r"C:\Users\philm\PycharmProjects\rwa_calculator\tests\sample_data\sample_data_3.xlsx", sheet_name=file_name)
        df.write_parquet(rf"C:\Users\philm\PycharmProjects\rwa_calculator\tests\sample_data\{folder}\{file_name}.parquet")
    return


if __name__ == "__main__":
    app.run()
