from __future__ import annotations

from panda3d.core import (
    Geom,
    GeomNode,
    GeomTriangles,
    GeomVertexData,
    GeomVertexFormat,
    GeomVertexWriter,
    LineSegs,
    NodePath,
    Vec3,
)


FaceNormal = tuple[int, int, int]


def make_unit_cube(name: str = "unit-cube", visible_faces: set[FaceNormal] | None = None) -> NodePath:
    return make_cuboid(name, (1.0, 1.0, 1.0), visible_faces=visible_faces)


def make_cuboid(
    name: str,
    size: tuple[float, float, float],
    visible_faces: set[FaceNormal] | None = None,
) -> NodePath:
    sx, sy, sz = size
    hx, hy, hz = sx * 0.5, sy * 0.5, sz * 0.5
    corners = {
        "lbf": (-hx, -hy, -hz),
        "rbf": (hx, -hy, -hz),
        "rtf": (hx, hy, -hz),
        "ltf": (-hx, hy, -hz),
        "lbb": (-hx, -hy, hz),
        "rbb": (hx, -hy, hz),
        "rtb": (hx, hy, hz),
        "ltb": (-hx, hy, hz),
    }
    faces: list[tuple[tuple[str, str, str, str], FaceNormal]] = [
        (("rbf", "rtf", "rtb", "rbb"), (1, 0, 0)),
        (("lbf", "lbb", "ltb", "ltf"), (-1, 0, 0)),
        (("ltf", "ltb", "rtb", "rtf"), (0, 1, 0)),
        (("lbf", "rbf", "rbb", "lbb"), (0, -1, 0)),
        (("lbb", "rbb", "rtb", "ltb"), (0, 0, 1)),
        (("lbf", "ltf", "rtf", "rbf"), (0, 0, -1)),
    ]

    vertex_data = GeomVertexData(name, GeomVertexFormat.getV3n3c4(), Geom.UHStatic)
    vertex_writer = GeomVertexWriter(vertex_data, "vertex")
    normal_writer = GeomVertexWriter(vertex_data, "normal")
    color_writer = GeomVertexWriter(vertex_data, "color")
    triangles = GeomTriangles(Geom.UHStatic)

    vertex_index = 0
    for face, normal in faces:
        if visible_faces is not None and normal not in visible_faces:
            continue
        for corner_name in face:
            vertex_writer.addData3f(*corners[corner_name])
            normal_writer.addData3f(*normal)
            color_writer.addData4f(1, 1, 1, 1)

        triangles.addVertices(vertex_index, vertex_index + 1, vertex_index + 2)
        triangles.addVertices(vertex_index, vertex_index + 2, vertex_index + 3)
        vertex_index += 4

    geom = Geom(vertex_data)
    geom.addPrimitive(triangles)
    node = GeomNode(name)
    node.addGeom(geom)
    return NodePath(node)


def make_checker_ground(size: int, name: str = "checker-ground") -> NodePath:
    vertex_data = GeomVertexData(name, GeomVertexFormat.getV3c4(), Geom.UHStatic)
    vertex_writer = GeomVertexWriter(vertex_data, "vertex")
    color_writer = GeomVertexWriter(vertex_data, "color")
    triangles = GeomTriangles(Geom.UHStatic)

    vertex_index = 0
    for x in range(size):
        for y in range(size):
            color = (0.92, 0.92, 0.92, 1.0) if (x + y) % 2 == 0 else (0.06, 0.06, 0.06, 1.0)
            for vertex in ((x, y, -0.006), (x + 1, y, -0.006), (x + 1, y + 1, -0.006), (x, y + 1, -0.006)):
                vertex_writer.addData3f(*vertex)
                color_writer.addData4f(*color)
            triangles.addVertices(vertex_index, vertex_index + 1, vertex_index + 2)
            triangles.addVertices(vertex_index, vertex_index + 2, vertex_index + 3)
            vertex_index += 4

    geom = Geom(vertex_data)
    geom.addPrimitive(triangles)
    node = GeomNode(name)
    node.addGeom(geom)
    return NodePath(node)


def make_bounds(size: int) -> NodePath:
    lines = LineSegs()
    lines.setThickness(2.0)
    lines.setColor(0.15, 0.55, 1.0, 1.0)
    corners = [
        Vec3(0, 0, 0),
        Vec3(size, 0, 0),
        Vec3(size, size, 0),
        Vec3(0, size, 0),
        Vec3(0, 0, size),
        Vec3(size, 0, size),
        Vec3(size, size, size),
        Vec3(0, size, size),
    ]
    edges = [
        (0, 1),
        (1, 2),
        (2, 3),
        (3, 0),
        (4, 5),
        (5, 6),
        (6, 7),
        (7, 4),
        (0, 4),
        (1, 5),
        (2, 6),
        (3, 7),
    ]
    for start, end in edges:
        lines.moveTo(corners[start])
        lines.drawTo(corners[end])
    path = NodePath(lines.create())
    path.setLightOff()
    return path


def make_cube_outline(name: str = "cube-outline", size: float = 1.01) -> NodePath:
    half = size * 0.5
    lines = LineSegs()
    lines.setThickness(3.0)
    lines.setColor(1.0, 0.95, 0.18, 1.0)
    corners = [
        Vec3(-half, -half, -half),
        Vec3(half, -half, -half),
        Vec3(half, half, -half),
        Vec3(-half, half, -half),
        Vec3(-half, -half, half),
        Vec3(half, -half, half),
        Vec3(half, half, half),
        Vec3(-half, half, half),
    ]
    edges = [
        (0, 1),
        (1, 2),
        (2, 3),
        (3, 0),
        (4, 5),
        (5, 6),
        (6, 7),
        (7, 4),
        (0, 4),
        (1, 5),
        (2, 6),
        (3, 7),
    ]
    for start, end in edges:
        lines.moveTo(corners[start])
        lines.drawTo(corners[end])
    path = NodePath(lines.create())
    path.setLightOff()
    return path
