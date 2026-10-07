"""Run one or both visual artifact verification suites."""

from __future__ import annotations

import argparse

from verify_epub import main as verify_epub
from verify_html import main as verify_html


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "target",
        choices=("all", "html", "epub"),
        default="all",
        nargs="?",
        help="Artifact type to verify (default: all).",
    )
    args = parser.parse_args()

    if args.target in {"all", "html"}:
        verify_html()
    if args.target in {"all", "epub"}:
        verify_epub()


if __name__ == "__main__":
    main()
