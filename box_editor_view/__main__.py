from __future__ import annotations

import argparse
from pathlib import Path

from .box_file import DEFAULT_N, MAX_N, MIN_N


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Panda3D .box voxel editor")
    parser.add_argument("path", nargs="?", help="existing or new .box file")
    parser.add_argument(
        "-n",
        "--n",
        type=int,
        default=DEFAULT_N,
        choices=range(MIN_N, MAX_N + 1),
        metavar="1..5",
        help="N value for a new file; map size is (2^N)^3",
    )
    parser.add_argument(
        "--new",
        action="store_true",
        help="start with an empty map even if the path already exists",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    from .editor import BoxEditorApp

    path = Path(args.path).resolve() if args.path else None
    app = BoxEditorApp(path=path, new_file=args.new, new_n=args.n)
    app.run()


if __name__ == "__main__":
    main()
