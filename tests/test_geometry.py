from panda3d.core import GeomVertexReader, Vec3

from box_editor_view.geometry import make_unit_cube
from box_editor_view.voxel_mesh import build_chunk_mesh


def test_cube_face_winding_matches_normals():
    cube = make_unit_cube()
    geom = cube.node().getGeom(0)
    vertex_data = geom.getVertexData()
    vertex_reader = GeomVertexReader(vertex_data, "vertex")
    normal_reader = GeomVertexReader(vertex_data, "normal")

    vertices = []
    normals = []
    while not vertex_reader.isAtEnd():
        vertices.append(Vec3(vertex_reader.getData3f()))
        normals.append(Vec3(normal_reader.getData3f()))

    for face_start in range(0, len(vertices), 4):
        face = vertices[face_start : face_start + 4]
        normal = normals[face_start]
        winding_normal = (face[1] - face[0]).cross(face[2] - face[1])
        winding_normal.normalize()
        assert winding_normal.dot(normal) > 0.99


def test_unit_cube_can_omit_selected_faces():
    cube = make_unit_cube(visible_faces={(1, 0, 0), (0, 1, 0)})
    geom = cube.node().getGeom(0)
    assert geom.getVertexData().getNumRows() == 8


def test_chunk_mesh_greedily_merges_same_color_faces():
    mesh = build_chunk_mesh(
        {
            (0, 0, 0): (1, 0, 0, 1),
            (1, 0, 0): (1, 0, 0, 1),
        },
        (0, 0, 0),
        2,
    )

    assert mesh.stats.source_blocks == 2
    assert mesh.stats.visible_faces == 10
    assert mesh.stats.merged_quads == 6
    assert mesh.opaque is not None
    assert mesh.opaque.node().getGeom(0).getVertexData().getNumRows() == 24


def test_chunk_mesh_keeps_different_transparent_faces_separate():
    mesh = build_chunk_mesh(
        {
            (0, 0, 0): (1, 0, 0, 0.5),
            (1, 0, 0): (1, 0, 0, 0.75),
        },
        (0, 0, 0),
        2,
    )

    assert mesh.stats.visible_faces == 12
    assert mesh.stats.merged_quads == 12
    assert mesh.stats.transparent_quads == 12
    assert mesh.transparent is not None
