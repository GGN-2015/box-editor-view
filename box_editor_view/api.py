from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from .box_file import (
    BoxFormatError,
    BoxMap,
    Cell,
    DEFAULT_N,
    RGBA,
    load_box,
    normalize_rgba,
    save_box,
    validate_cell,
    validate_n,
)
from .box_hash import box_hash


CellInput = Iterable[int]
ColorInput = Iterable[float]


@dataclass
class BoxDocument:
    """High-level, headless editor for a .box map."""

    box_map: BoxMap
    path: Path | None = None

    def __post_init__(self) -> None:
        self.box_map = BoxMap(n=self.box_map.n, boxes=self.box_map.boxes)
        if self.path is not None:
            self.path = Path(self.path)

    @classmethod
    def open(cls, path: str | Path) -> BoxDocument:
        file_path = Path(path)
        return cls(load_box(file_path), file_path)

    @classmethod
    def new(
        cls,
        *,
        n: int = DEFAULT_N,
        path: str | Path | None = None,
        boxes: Mapping[Cell, ColorInput] | None = None,
    ) -> BoxDocument:
        file_path = Path(path) if path is not None else None
        return cls(new_box(n=n, boxes=boxes), file_path)

    @property
    def n(self) -> int:
        return self.box_map.n

    @property
    def size(self) -> int:
        return self.box_map.size

    @property
    def count(self) -> int:
        return len(self.box_map.boxes)

    @property
    def boxes(self) -> dict[Cell, RGBA]:
        return dict(self.box_map.boxes)

    @property
    def content_hash(self) -> str:
        return box_hash(self.box_map)

    def iter_boxes(self) -> Iterator[tuple[Cell, RGBA]]:
        return iter_boxes(self.box_map)

    def get(self, cell: CellInput) -> RGBA | None:
        return get_voxel(self.box_map, cell)

    def set(self, cell: CellInput, color: ColorInput) -> BoxDocument:
        set_voxel(self.box_map, cell, color)
        return self

    def remove(self, cell: CellInput) -> bool:
        return remove_voxel(self.box_map, cell)

    def fill(self, start: CellInput, stop: CellInput, color: ColorInput) -> int:
        return fill_region(self.box_map, start, stop, color)

    def erase(self, start: CellInput, stop: CellInput) -> int:
        return erase_region(self.box_map, start, stop)

    def resize(self, n: int, *, discard_out_of_bounds: bool = False) -> int:
        return resize_map(self.box_map, n, discard_out_of_bounds=discard_out_of_bounds)

    def translate(self, offset: CellInput, *, discard_out_of_bounds: bool = False) -> int:
        return translate_map(self.box_map, offset, discard_out_of_bounds=discard_out_of_bounds)

    def clear(self) -> BoxDocument:
        self.box_map.clear()
        return self

    def bounding_box(self) -> tuple[Cell, Cell] | None:
        return bounding_box(self.box_map)

    def to_box_map(self) -> BoxMap:
        return BoxMap(n=self.box_map.n, boxes=self.box_map.boxes)

    def save(self, path: str | Path | None = None) -> Path:
        if path is not None:
            self.path = Path(path)
        if self.path is None:
            raise ValueError("save() needs a path for this BoxDocument")
        save_box(self.path, self.box_map)
        return self.path

    def save_as(self, path: str | Path) -> Path:
        return self.save(path)


def new_box(*, n: int = DEFAULT_N, boxes: Mapping[Cell, ColorInput] | None = None) -> BoxMap:
    return BoxMap(n=n, boxes=dict(boxes or {}))


def open_box(path: str | Path) -> BoxDocument:
    return BoxDocument.open(path)


def create_box(path: str | Path, *, n: int = DEFAULT_N, overwrite: bool = False) -> BoxDocument:
    file_path = Path(path)
    if file_path.exists() and not overwrite:
        raise FileExistsError(f"{file_path} already exists")
    document = BoxDocument.new(n=n, path=file_path)
    document.save()
    return document


def iter_boxes(box_map: BoxMap) -> Iterator[tuple[Cell, RGBA]]:
    normalized = BoxMap(n=box_map.n, boxes=box_map.boxes)
    yield from sorted(normalized.boxes.items())


def get_voxel(box_map: BoxMap, cell: CellInput) -> RGBA | None:
    return box_map.boxes.get(_validate_map_cell(box_map, cell))


def set_voxel(box_map: BoxMap, cell: CellInput, color: ColorInput) -> None:
    box_map.boxes[_validate_map_cell(box_map, cell)] = normalize_rgba(color)


def remove_voxel(box_map: BoxMap, cell: CellInput) -> bool:
    return box_map.boxes.pop(_validate_map_cell(box_map, cell), None) is not None


def fill_region(box_map: BoxMap, start: CellInput, stop: CellInput, color: ColorInput) -> int:
    start_cell, stop_cell = _validate_region(box_map, start, stop)
    normalized_color = normalize_rgba(color)
    count = 0
    for x in range(start_cell[0], stop_cell[0]):
        for y in range(start_cell[1], stop_cell[1]):
            for z in range(start_cell[2], stop_cell[2]):
                box_map.boxes[(x, y, z)] = normalized_color
                count += 1
    return count


def erase_region(box_map: BoxMap, start: CellInput, stop: CellInput) -> int:
    start_cell, stop_cell = _validate_region(box_map, start, stop)
    removed = 0
    for x in range(start_cell[0], stop_cell[0]):
        for y in range(start_cell[1], stop_cell[1]):
            for z in range(start_cell[2], stop_cell[2]):
                if box_map.boxes.pop((x, y, z), None) is not None:
                    removed += 1
    return removed


def resize_map(box_map: BoxMap, n: int, *, discard_out_of_bounds: bool = False) -> int:
    new_n = validate_n(n)
    new_size = 2**new_n
    outside = [cell for cell in box_map.boxes if not _cell_inside_size(cell, new_size)]
    if outside and not discard_out_of_bounds:
        raise BoxFormatError(
            f"resize to N={new_n} would discard {_cube_count_message(len(outside))}; "
            "pass discard_out_of_bounds=True to continue"
        )
    for cell in outside:
        box_map.boxes.pop(cell, None)
    box_map.n = new_n
    return len(outside)


def translate_map(box_map: BoxMap, offset: CellInput, *, discard_out_of_bounds: bool = False) -> int:
    dx, dy, dz = _coerce_cell(offset, "offset")
    moved: dict[Cell, RGBA] = {}
    discarded = 0
    for cell, color in box_map.boxes.items():
        target = (cell[0] + dx, cell[1] + dy, cell[2] + dz)
        if _cell_inside_size(target, box_map.size):
            moved[target] = color
            continue
        if not discard_out_of_bounds:
            raise BoxFormatError(
                f"translation by {dx},{dy},{dz} would move {_cube_count_message(1)} outside the map; "
                "pass discard_out_of_bounds=True to continue"
            )
        discarded += 1
    box_map.boxes = moved
    return discarded


def bounding_box(box_map: BoxMap) -> tuple[Cell, Cell] | None:
    if not box_map.boxes:
        return None
    cells = list(box_map.boxes)
    minimum = (
        min(cell[0] for cell in cells),
        min(cell[1] for cell in cells),
        min(cell[2] for cell in cells),
    )
    stop = (
        max(cell[0] for cell in cells) + 1,
        max(cell[1] for cell in cells) + 1,
        max(cell[2] for cell in cells) + 1,
    )
    return minimum, stop


def _validate_map_cell(box_map: BoxMap, cell: CellInput) -> Cell:
    return validate_cell(_coerce_cell(cell, "cell"), box_map.size)


def _validate_region(box_map: BoxMap, start: CellInput, stop: CellInput) -> tuple[Cell, Cell]:
    start_cell = _validate_region_corner(start, box_map.size, "start")
    stop_cell = _validate_region_corner(stop, box_map.size, "stop")
    if any(stop_cell[index] < start_cell[index] for index in range(3)):
        raise BoxFormatError("region stop must be greater than or equal to start on every axis")
    return start_cell, stop_cell


def _validate_region_corner(corner: CellInput, size: int, label: str) -> Cell:
    cell = _coerce_cell(corner, label)
    if any(part < 0 or part > size for part in cell):
        raise BoxFormatError(f"region {label} coordinates must be inside 0..{size}")
    return cell


def _coerce_cell(cell: CellInput, label: str) -> Cell:
    try:
        values = tuple(cell)
    except TypeError as exc:
        raise BoxFormatError(f"{label} coordinates must contain three integer values") from exc
    if len(values) != 3:
        raise BoxFormatError(f"{label} coordinates must contain three integer values")
    try:
        return tuple(int(part) for part in values)  # type: ignore[return-value]
    except (TypeError, ValueError) as exc:
        raise BoxFormatError(f"{label} coordinates must be integers") from exc


def _cell_inside_size(cell: Cell, size: int) -> bool:
    return 0 <= cell[0] < size and 0 <= cell[1] < size and 0 <= cell[2] < size


def _cube_count_message(count: int) -> str:
    suffix = "" if count == 1 else "s"
    return f"{count} cube{suffix}"


__all__ = [
    "BoxDocument",
    "CellInput",
    "ColorInput",
    "bounding_box",
    "create_box",
    "erase_region",
    "fill_region",
    "get_voxel",
    "iter_boxes",
    "new_box",
    "open_box",
    "remove_voxel",
    "resize_map",
    "set_voxel",
    "translate_map",
]
