from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .box_file import BoxFormatError, DEFAULT_N, MAX_N, MIN_N
from .box_hash import hash_box_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Panda3D .box voxel editor")
    parser.add_argument("path", nargs="?", help="existing or new .box file")
    parser.add_argument(
        "-n",
        "--n",
        type=int,
        default=DEFAULT_N,
        choices=range(MIN_N, MAX_N + 1),
        metavar="0..5",
        help="N value for a new file; map size is (2^N)^3",
    )
    parser.add_argument(
        "--new",
        action="store_true",
        help="start with an empty map even if the path already exists",
    )
    parser.add_argument(
        "--hash",
        action="store_true",
        help="print a content hash for the .box file and exit without opening the editor",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.hash:
        if not args.path:
            parser.error("--hash requires a .box file path")
        try:
            print(hash_box_file(Path(args.path)))
        except BoxFormatError as exc:
            print(f"FormatError: {exc}", file=sys.stderr)
            return 1
        return 0

    from .editor import BoxEditorApp

    path = Path(args.path).resolve() if args.path else None
    app = BoxEditorApp(path=path, new_file=args.new, new_n=args.n)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
