from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Iterable


RGBA = tuple[float, float, float, float]
Cell = tuple[int, int, int]

MIN_N = 1
MAX_N = 5
DEFAULT_N = 3
DEFAULT_COLOR: RGBA = (140 / 255, 140 / 255, 140 / 255, 1.0)


class BoxFormatError(ValueError):
    """Raised when a .box file is not valid for this editor."""


@dataclass
class BoxMap:
    """Sparse voxel map stored as JSON."""

    n: int = DEFAULT_N
    boxes: dict[Cell, RGBA] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.n = validate_n(self.n)
        normalized_boxes: dict[Cell, RGBA] = {}
        for cell, color in self.boxes.items():
            normalized_color = normalize_rgba(color)
            if normalized_color[3] > 0.0:
                normalized_boxes[validate_cell(cell, self.size)] = normalized_color
        self.boxes = normalized_boxes

    @property
    def size(self) -> int:
        return 2**self.n

    def in_bounds(self, cell: Cell) -> bool:
        x, y, z = cell
        return 0 <= x < self.size and 0 <= y < self.size and 0 <= z < self.size

    def set_box(self, cell: Cell, color: Iterable[float]) -> bool:
        if not self.in_bounds(cell):
            return False
        normalized_cell = tuple(map(int, cell))
        normalized_color = normalize_rgba(color)
        if normalized_color[3] <= 0.0:
            return self.remove_box(normalized_cell)
        self.boxes[normalized_cell] = normalized_color
        return True

    def remove_box(self, cell: Cell) -> bool:
        return self.boxes.pop(tuple(map(int, cell)), None) is not None

    def get_box(self, cell: Cell) -> RGBA | None:
        return self.boxes.get(tuple(map(int, cell)))

    def clear(self) -> None:
        self.boxes.clear()

    def to_json_dict(self) -> dict[str, object]:
        return {
            "N": self.n,
            "boxes": {
                format_cell(cell): rgba_to_255(color)
                for cell, color in sorted(self.boxes.items())
            },
        }

    @classmethod
    def from_json_dict(cls, data: object) -> "BoxMap":
        if not isinstance(data, dict):
            raise BoxFormatError(".box root must be a JSON object")

        if "N" not in data:
            raise BoxFormatError(".box file must contain an N value")
        n = validate_n(data["N"])
        size = 2**n

        raw_boxes = data.get("boxes", data.get("blocks", {}))
        if raw_boxes is None:
            raw_boxes = {}

        boxes: dict[Cell, RGBA] = {}
        if isinstance(raw_boxes, dict):
            for raw_cell, raw_color in raw_boxes.items():
                cell = parse_cell_key(raw_cell)
                boxes[validate_cell(cell, size)] = normalize_rgba(raw_color)
        elif isinstance(raw_boxes, list):
            for item in raw_boxes:
                cell, color = parse_box_item(item)
                boxes[validate_cell(cell, size)] = normalize_rgba(color)
        else:
            raise BoxFormatError("boxes must be an object or list")

        return cls(n=n, boxes=boxes)


def validate_n(value: object) -> int:
    if isinstance(value, bool):
        raise BoxFormatError("N must be an integer from 1 to 5")
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise BoxFormatError("N must be an integer from 1 to 5") from exc
    if n < MIN_N or n > MAX_N:
        raise BoxFormatError("N must be an integer from 1 to 5")
    return n


def validate_cell(cell: Cell, size: int) -> Cell:
    if len(cell) != 3:
        raise BoxFormatError("cell coordinates must have three values")
    normalized = tuple(int(part) for part in cell)
    if any(part < 0 or part >= size for part in normalized):
        raise BoxFormatError(f"cell {format_cell(normalized)} is outside 0..{size - 1}")
    return normalized


def normalize_rgba(color: Iterable[float]) -> RGBA:
    channels = list(color)
    if len(channels) != 4:
        raise BoxFormatError("RGBA colors must contain four channels")

    normalized: list[float] = []
    scale = 255.0 if any(float(channel) > 1.0 for channel in channels) else 1.0
    for channel in channels:
        value = float(channel) / scale
        normalized.append(max(0.0, min(1.0, value)))
    return tuple(normalized)  # type: ignore[return-value]


def rgba_to_255(color: RGBA) -> list[int]:
    return [round(max(0.0, min(1.0, channel)) * 255) for channel in color]


def parse_cell_key(value: object) -> Cell:
    if isinstance(value, str):
        pieces = value.replace(";", ",").split(",")
    elif isinstance(value, (list, tuple)):
        pieces = list(value)
    else:
        raise BoxFormatError("box cell keys must be strings like 'x,y,z'")

    if len(pieces) != 3:
        raise BoxFormatError("box cell keys must have three coordinates")
    try:
        return tuple(int(piece) for piece in pieces)  # type: ignore[return-value]
    except ValueError as exc:
        raise BoxFormatError("box cell coordinates must be integers") from exc


def parse_box_item(item: object) -> tuple[Cell, RGBA]:
    if not isinstance(item, dict):
        raise BoxFormatError("box list entries must be objects")
    if "pos" in item:
        cell = parse_cell_key(item["pos"])
    elif all(axis in item for axis in ("x", "y", "z")):
        cell = parse_cell_key([item["x"], item["y"], item["z"]])
    else:
        raise BoxFormatError("box list entries must contain pos or x/y/z")

    color = item.get("rgba", item.get("color", DEFAULT_COLOR))
    return cell, normalize_rgba(color)


def format_cell(cell: Cell) -> str:
    x, y, z = cell
    return f"{x},{y},{z}"


def load_box(path: str | Path) -> BoxMap:
    file_path = Path(path)
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BoxFormatError(f"{file_path} is not valid JSON") from exc
    return BoxMap.from_json_dict(data)


def save_box(path: str | Path, box_map: BoxMap) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(box_map.to_json_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
