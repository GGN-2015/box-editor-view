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
    parser.add_argument(
        "--render-png",
        nargs="?",
        const=True,
        metavar="PNG",
        help="render the .box model to a transparent PNG without opening the editor",
    )
    parser.add_argument(
        "--render-size",
        type=int,
        default=1024,
        metavar="PX",
        help="square PNG size for --render-png; default is 1024",
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

    if args.render_png is not None:
        box_path = args.path
        png_argument = args.render_png
        if not box_path and png_argument is not True:
            box_path = png_argument
            png_argument = True
        if not box_path:
            parser.error("--render-png requires a .box file path")
        from .render_png import default_png_path, render_box_png

        box_path = Path(box_path)
        png_path = default_png_path(box_path) if png_argument is True else Path(png_argument)
        try:
            render_box_png(box_path, png_path, image_size=args.render_size)
        except BoxFormatError as exc:
            print(f"FormatError: {exc}", file=sys.stderr)
            return 1
        except ValueError as exc:
            print(f"RenderError: {exc}", file=sys.stderr)
            return 1
        print(png_path)
        return 0

    from .editor import BoxEditorApp

    path = Path(args.path).resolve() if args.path else None
    app = BoxEditorApp(path=path, new_file=args.new, new_n=args.n)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
