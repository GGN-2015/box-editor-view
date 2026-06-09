from __future__ import annotations

from pathlib import Path
import math
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from box_editor_view.box_file import BoxMap, RGBA, save_box


PIKACHU_PATH = ROOT / "pikachu.box"

YELLOW: RGBA = (1.0, 0.82, 0.08, 1.0)
YELLOW_DARK: RGBA = (0.86, 0.58, 0.05, 1.0)
BLACK: RGBA = (0.025, 0.02, 0.018, 1.0)
BROWN: RGBA = (0.36, 0.16, 0.05, 1.0)
RED: RGBA = (0.95, 0.06, 0.04, 1.0)
WHITE: RGBA = (1.0, 0.98, 0.88, 1.0)


def add_cell(box_map: BoxMap, cell: tuple[int, int, int], color: RGBA) -> None:
    box_map.set_box(cell, color)


def add_box_range(box_map: BoxMap, start: tuple[int, int, int], end: tuple[int, int, int], color: RGBA) -> None:
    for x in range(start[0], end[0] + 1):
        for y in range(start[1], end[1] + 1):
            for z in range(start[2], end[2] + 1):
                add_cell(box_map, (x, y, z), color)


def add_ellipsoid(
    box_map: BoxMap,
    center: tuple[float, float, float],
    radius: tuple[float, float, float],
    color: RGBA,
) -> None:
    cx, cy, cz = center
    rx, ry, rz = radius
    min_x, max_x = math.floor(cx - rx), math.ceil(cx + rx)
    min_y, max_y = math.floor(cy - ry), math.ceil(cy + ry)
    min_z, max_z = math.floor(cz - rz), math.ceil(cz + rz)
    for x in range(min_x, max_x + 1):
        for y in range(min_y, max_y + 1):
            for z in range(min_z, max_z + 1):
                nx = (x + 0.5 - cx) / rx
                ny = (y + 0.5 - cy) / ry
                nz = (z + 0.5 - cz) / rz
                if nx * nx + ny * ny + nz * nz <= 1.0:
                    add_cell(box_map, (x, y, z), color)


def add_tail(box_map: BoxMap) -> None:
    # A blocky lightning-bolt tail rising behind Pikachu.
    add_box_range(box_map, (21, 19, 8), (23, 21, 10), BROWN)
    add_box_range(box_map, (23, 20, 10), (25, 22, 12), YELLOW_DARK)
    add_box_range(box_map, (25, 21, 12), (27, 23, 14), YELLOW)
    add_box_range(box_map, (23, 22, 14), (26, 24, 16), YELLOW)
    add_box_range(box_map, (21, 23, 16), (24, 25, 18), YELLOW)
    add_box_range(box_map, (20, 24, 18), (22, 26, 20), YELLOW)


def build_pikachu() -> BoxMap:
    box_map = BoxMap(n=5)

    # Body and head.
    add_ellipsoid(box_map, (15.5, 14.5, 8.0), (5.8, 4.5, 6.8), YELLOW)
    add_ellipsoid(box_map, (15.5, 14.0, 17.0), (6.2, 5.2, 5.2), YELLOW)

    # Ears with black tips.
    add_box_range(box_map, (10, 12, 21), (12, 14, 26), YELLOW)
    add_box_range(box_map, (9, 12, 24), (11, 14, 28), BLACK)
    add_box_range(box_map, (19, 12, 21), (21, 14, 26), YELLOW)
    add_box_range(box_map, (20, 12, 24), (22, 14, 28), BLACK)

    # Face.
    add_box_range(box_map, (12, 9, 18), (13, 9, 19), BLACK)
    add_box_range(box_map, (18, 9, 18), (19, 9, 19), BLACK)
    add_cell(box_map, (13, 8, 20), WHITE)
    add_cell(box_map, (19, 8, 20), WHITE)
    add_box_range(box_map, (10, 8, 15), (12, 9, 16), RED)
    add_box_range(box_map, (19, 8, 15), (21, 9, 16), RED)
    add_box_range(box_map, (15, 8, 16), (16, 8, 16), BLACK)
    add_cell(box_map, (14, 8, 14), BLACK)
    add_cell(box_map, (17, 8, 14), BLACK)
    add_box_range(box_map, (15, 8, 13), (16, 8, 13), BLACK)

    # Arms, feet, and belly highlight.
    add_box_range(box_map, (8, 12, 9), (10, 14, 13), YELLOW_DARK)
    add_box_range(box_map, (21, 12, 9), (23, 14, 13), YELLOW_DARK)
    add_box_range(box_map, (11, 10, 0), (14, 14, 2), YELLOW_DARK)
    add_box_range(box_map, (17, 10, 0), (20, 14, 2), YELLOW_DARK)
    add_ellipsoid(box_map, (15.5, 10.0, 8.0), (3.2, 1.2, 3.8), (1.0, 0.88, 0.28, 1.0))

    add_tail(box_map)
    return box_map


def main() -> None:
    save_box(PIKACHU_PATH, build_pikachu())
    print(f"Wrote {PIKACHU_PATH}")


if __name__ == "__main__":
    main()
