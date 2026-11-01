"""``percival`` command line. Only ``import`` for now."""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from typing import Any

from percival.naming import NAME


def load_app(spec: str) -> Any:
    """``proj.celery:app``, or just ``proj.celery`` if the app is called app/celery."""
    # same as celery -A: make the current directory importable
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())

    module_name, _, attr = spec.partition(":")
    module = importlib.import_module(module_name)
    if attr:
        return getattr(module, attr)
    for candidate in ("app", "celery"):
        if hasattr(module, candidate):
            return getattr(module, candidate)
    raise SystemExit(f"couldn't find a celery app in {module_name}, try {module_name}:app")


def cmd_import(args: argparse.Namespace) -> int:
    from percival import importer

    app = load_app(args.app)
    importer.configure_redbeat(app, args.redis_url, args.key_prefix)
    planned = importer.plan(app, require_version=args.require_version, only=args.only or None)
    print(importer.render(planned))

    if not args.apply:
        if any(p.action in (importer.CREATE, importer.UPDATE) for p in planned):
            print("\ndry run, nothing written. run again with --apply to write these.")
        return 0

    written = importer.apply(app, planned)
    print(f"\nwrote {written} entries to redbeat.")
    if written:
        print(
            "note: beat re-syncs beat_schedule from config on every start, so remove the\n"
            "imported entries from your config or they will overwrite changes made in the panel."
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=NAME)
    sub = parser.add_subparsers(dest="command", required=True)

    imp = sub.add_parser("import", help="copy beat_schedule from your app into redbeat")
    imp.add_argument("--app", required=True, help="celery app, e.g. proj.celery:app")
    imp.add_argument("--redis-url", help="redis used by redbeat (default: redbeat_redis_url)")
    imp.add_argument("--key-prefix", help="redbeat_key_prefix if you changed it")
    imp.add_argument(
        "--require-version",
        help="set the required code version on every imported entry",
    )
    imp.add_argument("--only", nargs="+", metavar="NAME", help="import just these entries")
    imp.add_argument("--apply", action="store_true", help="actually write (default is dry run)")
    imp.set_defaults(func=cmd_import)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
