from __future__ import annotations

import argparse
from pathlib import Path
import sys
from time import perf_counter

from panda3d.core import loadPrcFileData

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WINDOW_MODE = "--window" in sys.argv
loadPrcFileData(
    "",
    "\n".join(
        [
            "window-type onscreen" if WINDOW_MODE else "window-type offscreen",
            "audio-library-name null",
            "sync-video false",
            "show-frame-rate-meter false",
            "notify-level warning",
        ]
    ),
)

from box_editor_view.editor import BoxEditorApp


def measure(path: Path, frames: int, warmup: int) -> None:
    app = BoxEditorApp(path=path.resolve(), new_file=False, new_n=3)
    try:
        app.set_mouse_capture(False)
        app.player_pos.setX(app.box_map.size * 0.5)
        app.player_pos.setY(-max(8.0, app.box_map.size * 0.45))
        app.player_pos.setZ(max(4.0, app.box_map.size * 0.35))
        app._look_at_editor_focus()
        app._update_camera()

        for _ in range(warmup):
            app.taskMgr.step()

        start = perf_counter()
        for _ in range(frames):
            app.taskMgr.step()
        elapsed = max(1e-9, perf_counter() - start)
        stats = app._chunk_stats()

        print(f"path={path}")
        print(f"frames={frames}")
        print(f"elapsed={elapsed:.4f}s")
        print(f"fps={frames / elapsed:.2f}")
        print(
            "mesh="
            f"chunks:{stats['chunks']} "
            f"blocks:{stats['source_blocks']} "
            f"visible_faces:{stats['visible_faces']} "
            f"merged_quads:{stats['merged_quads']} "
            f"opaque_quads:{stats['opaque_quads']} "
            f"transparent_quads:{stats['transparent_quads']}"
        )
    finally:
        app.destroy()


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure Box Editor View render FPS for a .box file.")
    parser.add_argument("path", type=Path)
    parser.add_argument("--frames", type=int, default=300)
    parser.add_argument("--warmup", type=int, default=60)
    parser.add_argument(
        "--window",
        action="store_true",
        help="use a visible onscreen window instead of the default offscreen buffer",
    )
    args = parser.parse_args()
    measure(args.path, args.frames, args.warmup)


if __name__ == "__main__":
    main()
