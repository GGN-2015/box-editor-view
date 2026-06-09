from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from panda3d.core import Filename, Vec3, loadPrcFileData

loadPrcFileData(
    "",
    "\n".join(
        [
            "window-type offscreen",
            "win-size 1280 720",
            "audio-library-name null",
            "notify-level warning",
            "framebuffer-multisample true",
            "multisamples 4",
        ]
    ),
)

from box_editor_view.box_file import BoxMap, RGBA, save_box
from box_editor_view.editor import BoxEditorApp


PIANO_PATH = ROOT / "piano.box"
IMAGE_DIR = ROOT / "docs" / "images"

BLACK: RGBA = (0.035, 0.032, 0.028, 1.0)
BLACK_SOFT: RGBA = (0.12, 0.105, 0.085, 1.0)
WHITE: RGBA = (0.96, 0.93, 0.86, 1.0)
IVORY: RGBA = (0.82, 0.77, 0.64, 1.0)
WOOD: RGBA = (0.32, 0.16, 0.07, 1.0)
WOOD_LIGHT: RGBA = (0.50, 0.27, 0.11, 1.0)
GOLD: RGBA = (0.95, 0.68, 0.22, 1.0)
RED_FELT: RGBA = (0.50, 0.04, 0.03, 1.0)
SHADOW_GLASS: RGBA = (0.05, 0.04, 0.035, 0.55)
BLUE_GLINT: RGBA = (0.30, 0.52, 0.72, 0.45)


def add_box_range(box_map: BoxMap, start: tuple[int, int, int], end: tuple[int, int, int], color: RGBA) -> None:
    for x in range(start[0], end[0] + 1):
        for y in range(start[1], end[1] + 1):
            for z in range(start[2], end[2] + 1):
                box_map.set_box((x, y, z), color)


def build_piano() -> BoxMap:
    box_map = BoxMap(n=5)

    # Main grand-piano body.
    add_box_range(box_map, (6, 9, 0), (25, 14, 3), WOOD)
    add_box_range(box_map, (7, 10, 4), (24, 13, 8), BLACK)
    add_box_range(box_map, (8, 14, 1), (23, 14, 7), BLACK_SOFT)
    add_box_range(box_map, (7, 8, 3), (24, 8, 4), WOOD_LIGHT)
    add_box_range(box_map, (8, 8, 5), (23, 8, 5), RED_FELT)
    add_box_range(box_map, (8, 7, 4), (23, 7, 4), GOLD)

    # Lid, rim, and music stand.
    add_box_range(box_map, (5, 9, 9), (26, 13, 9), BLACK)
    add_box_range(box_map, (8, 10, 10), (24, 12, 10), BLACK_SOFT)
    add_box_range(box_map, (7, 10, 11), (22, 11, 11), SHADOW_GLASS)
    add_box_range(box_map, (8, 15, 5), (23, 15, 8), SHADOW_GLASS)
    add_box_range(box_map, (10, 16, 6), (21, 16, 7), BLUE_GLINT)
    add_box_range(box_map, (24, 10, 5), (25, 12, 8), WOOD_LIGHT)
    add_box_range(box_map, (6, 10, 5), (7, 12, 8), WOOD_LIGHT)

    # White keys across the front.
    for index in range(18):
        x = 7 + index
        add_box_range(box_map, (x, 5, 4), (x, 7, 4), WHITE if index % 2 == 0 else IVORY)

    # Black keys: skip the gaps in each octave.
    black_key_offsets = {1, 2, 4, 5, 6}
    for index in range(17):
        if index % 7 in black_key_offsets:
            x = 7 + index
            add_box_range(box_map, (x, 6, 5), (x, 7, 5), BLACK)

    # Legs and pedals.
    for x in (7, 24):
        add_box_range(box_map, (x, 9, 0), (x + 1, 10, 5), BLACK)
    for x in (14, 16, 18):
        add_box_range(box_map, (x, 6, 0), (x, 7, 0), GOLD)

    # Bench.
    add_box_range(box_map, (10, 0, 2), (21, 4, 2), BLACK_SOFT)
    for x in (11, 20):
        for y in (1, 3):
            add_box_range(box_map, (x, y, 0), (x, y, 1), WOOD)

    return box_map


def prepare_clean_screenshot(app: BoxEditorApp) -> None:
    app.setFrameRateMeter(False)
    for node in (app.status, app.detail, app.help_hint, app.center_hint, app.crosshair):
        node.hide()
    if app.bounds_node is not None:
        app.bounds_node.hide()


def screenshot(app: BoxEditorApp, name: str, player: Vec3, heading: float, pitch: float) -> None:
    prepare_clean_screenshot(app)
    app.player_pos = player
    app.heading = heading
    app.pitch = pitch
    app.view_mode = "first"
    app._update_camera()
    app.graphicsEngine.renderFrame()
    app.graphicsEngine.renderFrame()
    app.win.saveScreenshot(Filename.fromOsSpecific(str(IMAGE_DIR / name)))


def main() -> None:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    box_map = build_piano()
    save_box(PIANO_PATH, box_map)

    app = BoxEditorApp(PIANO_PATH, new_file=False, new_n=5)
    try:
        screenshot(app, "piano_front.png", Vec3(15.5, -10.0, 5.2), 0.0, -3.5)
        screenshot(app, "piano_keys.png", Vec3(15.5, 1.2, 5.7), 0.0, -15.0)
        screenshot(app, "piano_angle.png", Vec3(1.5, -2.8, 7.8), -38.0, -9.0)
    finally:
        app.destroy()


if __name__ == "__main__":
    main()
