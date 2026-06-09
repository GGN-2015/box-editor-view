from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from panda3d.core import Geom, GeomNode, GeomTriangles, GeomVertexData, GeomVertexFormat, GeomVertexWriter, NodePath

from .box_file import Cell, RGBA
from .geometry import FaceNormal


CHUNK_SIZE = 8
FACE_NORMALS: tuple[FaceNormal, ...] = (
    (1, 0, 0),
    (-1, 0, 0),
    (0, 1, 0),
    (0, -1, 0),
    (0, 0, 1),
    (0, 0, -1),
)


ChunkKey = tuple[int, int, int]


@dataclass(frozen=True)
class ChunkMeshStats:
    source_blocks: int = 0
    visible_faces: int = 0
    merged_quads: int = 0
    opaque_quads: int = 0
    transparent_quads: int = 0


@dataclass
class ChunkMesh:
    opaque: NodePath | None
    transparent: NodePath | None
    stats: ChunkMeshStats


class _MeshBuilder:
    def __init__(self, name: str) -> None:
        self.name = name
        self.vertex_data = GeomVertexData(name, GeomVertexFormat.getV3n3c4(), Geom.UHStatic)
        self.vertex_writer = GeomVertexWriter(self.vertex_data, "vertex")
        self.normal_writer = GeomVertexWriter(self.vertex_data, "normal")
        self.color_writer = GeomVertexWriter(self.vertex_data, "color")
        self.triangles = GeomTriangles(Geom.UHStatic)
        self.vertex_index = 0
        self.quads = 0

    def add_quad(self, vertices: tuple[tuple[float, float, float], ...], normal: FaceNormal, color: RGBA) -> None:
        for vertex in vertices:
            self.vertex_writer.addData3f(*vertex)
            self.normal_writer.addData3f(*normal)
            self.color_writer.addData4f(*color)

        self.triangles.addVertices(self.vertex_index, self.vertex_index + 1, self.vertex_index + 2)
        self.triangles.addVertices(self.vertex_index, self.vertex_index + 2, self.vertex_index + 3)
        self.vertex_index += 4
        self.quads += 1

    def to_node(self) -> NodePath | None:
        if self.vertex_index == 0:
            return None
        geom = Geom(self.vertex_data)
        geom.addPrimitive(self.triangles)
        node = GeomNode(self.name)
        node.addGeom(geom)
        return NodePath(node)


def chunk_key_for_cell(cell: Cell, chunk_size: int = CHUNK_SIZE) -> ChunkKey:
    return (cell[0] // chunk_size, cell[1] // chunk_size, cell[2] // chunk_size)


def chunk_bounds(chunk_key: ChunkKey, map_size: int, chunk_size: int = CHUNK_SIZE) -> tuple[Cell, Cell]:
    start = (chunk_key[0] * chunk_size, chunk_key[1] * chunk_size, chunk_key[2] * chunk_size)
    end = (
        min(start[0] + chunk_size, map_size),
        min(start[1] + chunk_size, map_size),
        min(start[2] + chunk_size, map_size),
    )
    return start, end


def neighbor_hides_face(color: RGBA, neighbor_color: RGBA) -> bool:
    if color[3] >= 1.0 and neighbor_color[3] >= 1.0:
        return True
    return color[3] < 1.0 and neighbor_color[3] < 1.0 and neighbor_color == color


def visible_faces_for_cell(cell: Cell, color: RGBA, boxes: Mapping[Cell, RGBA]) -> set[FaceNormal]:
    visible_faces = set(FACE_NORMALS)
    for normal in FACE_NORMALS:
        neighbor = (cell[0] + normal[0], cell[1] + normal[1], cell[2] + normal[2])
        neighbor_color = boxes.get(neighbor)
        if neighbor_color is not None and neighbor_hides_face(color, neighbor_color):
            visible_faces.discard(normal)
    return visible_faces


def build_chunk_mesh(
    boxes: Mapping[Cell, RGBA],
    chunk_key: ChunkKey,
    map_size: int,
    chunk_size: int = CHUNK_SIZE,
) -> ChunkMesh:
    start, end = chunk_bounds(chunk_key, map_size, chunk_size)
    groups: dict[tuple[bool, FaceNormal, int, RGBA], set[tuple[int, int]]] = {}
    source_blocks = 0
    visible_faces = 0

    for cell, color in boxes.items():
        if not _cell_in_bounds(cell, start, end):
            continue
        source_blocks += 1
        for normal in visible_faces_for_cell(cell, color, boxes):
            plane, u, v = _face_plane_uv(cell, normal)
            transparent = color[3] < 1.0
            groups.setdefault((transparent, normal, plane, color), set()).add((u, v))
            visible_faces += 1

    opaque_builder = _MeshBuilder(f"chunk-{chunk_key[0]}-{chunk_key[1]}-{chunk_key[2]}-opaque")
    transparent_builder = _MeshBuilder(f"chunk-{chunk_key[0]}-{chunk_key[1]}-{chunk_key[2]}-transparent")

    for (transparent, normal, plane, color), positions in groups.items():
        builder = transparent_builder if transparent else opaque_builder
        for u0, v0, u1, v1 in _greedy_rectangles(positions):
            builder.add_quad(_quad_vertices(normal, plane, u0, v0, u1, v1), normal, color)

    stats = ChunkMeshStats(
        source_blocks=source_blocks,
        visible_faces=visible_faces,
        merged_quads=opaque_builder.quads + transparent_builder.quads,
        opaque_quads=opaque_builder.quads,
        transparent_quads=transparent_builder.quads,
    )
    return ChunkMesh(opaque=opaque_builder.to_node(), transparent=transparent_builder.to_node(), stats=stats)


def _cell_in_bounds(cell: Cell, start: Cell, end: Cell) -> bool:
    return start[0] <= cell[0] < end[0] and start[1] <= cell[1] < end[1] and start[2] <= cell[2] < end[2]


def _face_plane_uv(cell: Cell, normal: FaceNormal) -> tuple[int, int, int]:
    x, y, z = cell
    if normal == (1, 0, 0):
        return x + 1, y, z
    if normal == (-1, 0, 0):
        return x, y, z
    if normal == (0, 1, 0):
        return y + 1, x, z
    if normal == (0, -1, 0):
        return y, x, z
    if normal == (0, 0, 1):
        return z + 1, x, y
    return z, x, y


def _greedy_rectangles(positions: set[tuple[int, int]]) -> list[tuple[int, int, int, int]]:
    remaining = set(positions)
    rectangles: list[tuple[int, int, int, int]] = []
    while remaining:
        u0, v0 = min(remaining, key=lambda item: (item[1], item[0]))
        width = 1
        while (u0 + width, v0) in remaining:
            width += 1

        height = 1
        while all((u, v0 + height) in remaining for u in range(u0, u0 + width)):
            height += 1

        for u in range(u0, u0 + width):
            for v in range(v0, v0 + height):
                remaining.remove((u, v))
        rectangles.append((u0, v0, u0 + width, v0 + height))
    return rectangles


def _quad_vertices(
    normal: FaceNormal,
    plane: int,
    u0: int,
    v0: int,
    u1: int,
    v1: int,
) -> tuple[tuple[float, float, float], ...]:
    p = float(plane)
    a = float(u0)
    b = float(v0)
    c = float(u1)
    d = float(v1)

    if normal == (1, 0, 0):
        return ((p, a, b), (p, c, b), (p, c, d), (p, a, d))
    if normal == (-1, 0, 0):
        return ((p, a, b), (p, a, d), (p, c, d), (p, c, b))
    if normal == (0, 1, 0):
        return ((a, p, b), (a, p, d), (c, p, d), (c, p, b))
    if normal == (0, -1, 0):
        return ((a, p, b), (c, p, b), (c, p, d), (a, p, d))
    if normal == (0, 0, 1):
        return ((a, b, p), (c, b, p), (c, d, p), (a, d, p))
    return ((a, b, p), (a, d, p), (c, d, p), (c, b, p))
