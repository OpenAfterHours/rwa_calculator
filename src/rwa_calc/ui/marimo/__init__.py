"""Marimo UI applications for RWA Calculator.

Available applications:
    - rwa_app.py: Main calculator for running RWA calculations
    - results_explorer.py: Interactive results analysis and filtering
    - comparison_app.py: CRR vs Basel 3.1 impact analysis (M3.4)
    - framework_reference.py: Regulatory framework documentation

Usage (Multi-App Server - Recommended):
    # Start the server with all apps
    uv run python src/rwa_calc/ui/marimo/server.py

    # Apps available at:
    #   http://localhost:8000/           (Calculator)
    #   http://localhost:8000/calculator (Calculator)
    #   http://localhost:8000/results    (Results Explorer)
    #   http://localhost:8000/comparison (Impact Analysis)
    #   http://localhost:8000/reference  (Framework Reference)

Usage (Single App):
    # Run individual app in edit mode (development)
    uv run marimo edit src/rwa_calc/ui/marimo/rwa_app.py

    # Run individual app in read-only mode
    uv run marimo run src/rwa_calc/ui/marimo/rwa_app.py

    Note: Navigation between apps only works with the multi-app server.

Navigation:
    All apps include a sidebar with navigation links to switch between apps.
    Results from the calculator are cached and shared with the results explorer.
"""
