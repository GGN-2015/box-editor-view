from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import sqlite3
import time
from typing import Iterable


RGBA = tuple[float, float, float, float]
Cell = tuple[int, int, int]

MIN_N = 0
MAX_N = 5
DEFAULT_N = 3
DEFAULT_COLOR: RGBA = (140 / 255, 140 / 255, 140 / 255, 1.0)
BOX_SCHEMA_VERSION = 2


class BoxFormatError(ValueError):
    """Raised when a .box SQLite database is not valid for this editor."""


@dataclass
class BoxMap:
    """Sparse voxel map stored in memory and serialized as SQLite."""

    n: int = DEFAULT_N
    boxes: dict[Cell, RGBA] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.n = validate_n(self.n)
        normalized_boxes: dict[Cell, RGBA] = {}
        for cell, color in self.boxes.items():
            normalized_color = normalize_rgba(color)
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
        self.boxes[normalized_cell] = normalized_color
        return True

    def remove_box(self, cell: Cell) -> bool:
        return self.boxes.pop(tuple(map(int, cell)), None) is not None

    def get_box(self, cell: Cell) -> RGBA | None:
        return self.boxes.get(tuple(map(int, cell)))

    def clear(self) -> None:
        self.boxes.clear()


def validate_n(value: object) -> int:
    if isinstance(value, bool):
        raise BoxFormatError("N must be an integer from 0 to 5")
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise BoxFormatError("N must be an integer from 0 to 5") from exc
    if n < MIN_N or n > MAX_N:
        raise BoxFormatError("N must be an integer from 0 to 5")
    return n


def validate_cell(cell: Cell, size: int) -> Cell:
    if len(cell) != 3:
        raise BoxFormatError("cell coordinates must have three values")
    try:
        normalized = tuple(int(part) for part in cell)
    except (TypeError, ValueError) as exc:
        raise BoxFormatError("cell coordinates must be integers") from exc
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


def rgba_to_255(color: RGBA) -> tuple[int, int, int, int]:
    return tuple(round(max(0.0, min(1.0, channel)) * 255) for channel in color)  # type: ignore[return-value]


def rgba_from_255(channels: Iterable[int]) -> RGBA:
    values = [int(channel) for channel in channels]
    if len(values) != 4:
        raise BoxFormatError("RGBA colors must contain four channels")
    return tuple(max(0.0, min(1.0, value / 255.0)) for value in values)  # type: ignore[return-value]


def format_cell(cell: Cell) -> str:
    x, y, z = cell
    return f"{x},{y},{z}"


def load_box(path: str | Path) -> BoxMap:
    file_path = Path(path)
    if not file_path.exists():
        raise BoxFormatError(f"{file_path} does not exist")

    try:
        connection = sqlite3.connect(file_path)
        try:
            connection.row_factory = sqlite3.Row
            return _load_box_from_connection(connection, file_path)
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        raise BoxFormatError(f"{file_path} is not a valid SQLite .box file") from exc


def save_box(path: str | Path, box_map: BoxMap) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = file_path.with_name(f"{file_path.name}.tmp")
    if temp_path.exists():
        temp_path.unlink()

    try:
        connection = sqlite3.connect(temp_path)
        try:
            _configure_connection(connection)
            _create_schema(connection)
            _write_box_map(connection, box_map)
            connection.commit()
        finally:
            connection.close()
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise
    _replace_file(temp_path, file_path)


def _load_box_from_connection(connection: sqlite3.Connection, path: Path) -> BoxMap:
    tables = _table_names(connection)
    _require_tables(tables, {"metadata"}, path)
    schema_version = _read_schema_version(connection, path)
    if schema_version != BOX_SCHEMA_VERSION:
        raise BoxFormatError(f"{path} uses unsupported .box schema version {schema_version}")
    _require_tables(tables, {"palette", "boxes"}, path)
    n_value = _read_metadata(connection, "N", path)
    n = validate_n(n_value)
    size = 2**n
    boxes = _load_palette_boxes(connection, path, size)
    return BoxMap(n=n, boxes=boxes)


def _load_palette_boxes(connection: sqlite3.Connection, path: Path, size: int) -> dict[Cell, RGBA]:
    palette: dict[int, RGBA] = {}
    palette_rows = connection.execute("SELECT color_id, r, g, b, a FROM palette ORDER BY color_id").fetchall()
    for row in palette_rows:
        color_id = _positive_int(row["color_id"], "palette color_id", path)
        color = _rgba_from_storage((row["r"], row["g"], row["b"], row["a"]), path)
        palette[color_id] = color

    boxes: dict[Cell, RGBA] = {}
    rows = connection.execute("SELECT x, y, z, color_id FROM boxes ORDER BY x, y, z").fetchall()
    for row in rows:
        cell = validate_cell((row["x"], row["y"], row["z"]), size)
        color_id = _positive_int(row["color_id"], "box color_id", path)
        try:
            boxes[cell] = palette[color_id]
        except KeyError as exc:
            raise BoxFormatError(f"{path} references missing palette color_id {color_id}") from exc
    return boxes


def _configure_connection(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA journal_mode=OFF")
    connection.execute("PRAGMA synchronous=OFF")
    connection.execute("PRAGMA foreign_keys=ON")


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        ) WITHOUT ROWID;

        CREATE TABLE palette (
            color_id INTEGER PRIMARY KEY,
            r INTEGER NOT NULL CHECK (r BETWEEN 0 AND 255),
            g INTEGER NOT NULL CHECK (g BETWEEN 0 AND 255),
            b INTEGER NOT NULL CHECK (b BETWEEN 0 AND 255),
            a INTEGER NOT NULL CHECK (a BETWEEN 0 AND 255),
            UNIQUE (r, g, b, a)
        ) WITHOUT ROWID;

        CREATE TABLE boxes (
            x INTEGER NOT NULL,
            y INTEGER NOT NULL,
            z INTEGER NOT NULL,
            color_id INTEGER NOT NULL REFERENCES palette(color_id),
            PRIMARY KEY (x, y, z)
        ) WITHOUT ROWID;
        """
    )


def _write_box_map(connection: sqlite3.Connection, box_map: BoxMap) -> None:
    box_map = BoxMap(n=box_map.n, boxes=box_map.boxes)
    connection.executemany(
        "INSERT INTO metadata (key, value) VALUES (?, ?)",
        (("schema_version", str(BOX_SCHEMA_VERSION)), ("N", str(box_map.n))),
    )
    palette_colors = sorted({_rgba_to_storage(color) for color in box_map.boxes.values()})
    palette = {color: color_id for color_id, color in enumerate(palette_colors, start=1)}
    connection.executemany(
        "INSERT INTO palette (color_id, r, g, b, a) VALUES (?, ?, ?, ?, ?)",
        ((color_id, *color) for color, color_id in palette.items()),
    )
    rows = []
    for cell, color in sorted(box_map.boxes.items()):
        storage_color = _rgba_to_storage(color)
        rows.append((cell[0], cell[1], cell[2], palette[storage_color]))
    connection.executemany(
        "INSERT INTO boxes (x, y, z, color_id) VALUES (?, ?, ?, ?)",
        rows,
    )


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _require_tables(tables: set[str], required: set[str], path: Path) -> None:
    missing = required - tables
    if missing:
        raise BoxFormatError(f"{path} is missing SQLite .box tables: {', '.join(sorted(missing))}")


def _read_schema_version(connection: sqlite3.Connection, path: Path) -> int:
    version = _read_metadata(connection, "schema_version", path)
    try:
        return int(version)
    except ValueError as exc:
        raise BoxFormatError(f"{path} has invalid .box schema version {version}") from exc


def _read_metadata(connection: sqlite3.Connection, key: str, path: Path) -> str:
    row = connection.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
    if row is None:
        raise BoxFormatError(f"{path} is missing metadata key {key}")
    return str(row[0])


def _rgba_to_storage(color: RGBA) -> tuple[int, int, int, int]:
    return rgba_to_255(color)


def _rgba_from_storage(channels: Iterable[object], path: Path) -> RGBA:
    values = list(channels)
    if len(values) != 4:
        raise BoxFormatError("RGBA colors must contain four channels")
    rgba: list[int] = []
    for label, channel in zip(("r", "g", "b", "a"), values, strict=True):
        try:
            value = int(channel)
        except (TypeError, ValueError) as exc:
            raise BoxFormatError(f"{path} has invalid {label} channel {channel}") from exc
        if value < 0 or value > 255:
            raise BoxFormatError(f"{path} has invalid {label} channel {value}")
        rgba.append(value)
    return rgba_from_255(rgba)


def _positive_int(value: object, label: str, path: Path) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise BoxFormatError(f"{path} has invalid {label} {value}") from exc
    if number < 1:
        raise BoxFormatError(f"{path} has invalid {label} {number}")
    return number


def _replace_file(source: Path, target: Path) -> None:
    last_error: PermissionError | None = None
    for _ in range(10):
        try:
            os.replace(source, target)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.05)
    if last_error is not None:
        raise last_error
