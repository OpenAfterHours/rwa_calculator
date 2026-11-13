"""
The ``rwa-filer`` command line.

Pipeline position:
    shell  ->  rwa_filer.cli.main  ->  the package's public API

Key responsibilities:
- Parse the command line and dispatch to a subcommand.
- Write results to stdout and diagnostics to stderr, and return a process exit
  code. This module holds no validation or filing logic of its own.

Exit codes:
    0  success
    2  usage error (argparse's own convention)
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from rwa_filer import __version__

EXIT_OK = 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``rwa-filer`` command and return its exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help(sys.stdout)
        return EXIT_OK
    return handler(args)


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="rwa-filer",
        description=(
            "Validate regulatory returns against the published supervisory rules "
            "and write them for submission."
        ),
    )
    parser.add_argument("--version", action="version", version=f"rwa-filer {__version__}")
    parser.add_subparsers(dest="command", metavar="<command>")
    return parser


if __name__ == "__main__":
    sys.exit(main())
