"""CLI boundary for the walking skeleton.

Composition root: wires CodeGenerator + SqliteLinkRepository into ShortenService
and exposes the "shorten" command. This is the thin top of the vertical slice
(CLI -> service -> persistence).
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from url_shortener.codegen import RandomBase62Generator
from url_shortener.repository import SqliteLinkRepository
from url_shortener.services import InvalidURLError, ShortenService

_DEFAULT_DB = "links.db"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="url-shortener")
    sub = parser.add_subparsers(dest="command", required=True)

    shorten = sub.add_parser("shorten", help="Shorten a long URL")
    shorten.add_argument("url", help="The long URL to shorten")
    shorten.add_argument("--db", default=_DEFAULT_DB, help="Path to the SQLite store")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "shorten":
        service = ShortenService(SqliteLinkRepository(args.db), RandomBase62Generator())
        try:
            link = service.shorten(args.url)
        except InvalidURLError:
            print(f"error: invalid URL: {args.url}")
            return 2
        print(link.code)
        return 0

    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
