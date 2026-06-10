from __future__ import annotations

from pathlib import Path

from panda3d.core import (
    AmbientLight,
    DirectionalLight,
    Filename,
    OrthographicLens,
    Point3,
    PointLight,
    TransparencyAttrib,
    Vec3,
    loadPrcFileData,
)

from .box_file import BoxMap, Cell, RGBA, load_box
from .voxel_mesh import CHUNK_SIZE, ChunkKey, build_chunk_mesh, chunk_key_for_cell, is_light_color


DEFAULT_PREVIEW_SIZE = 1024
MIN_PREVIEW_SIZE = 16
VIEW_DIRECTION = Vec3(1.0, -1.0, 0.78)


def render_box_png(box_path: str | Path, png_path: str | Path, image_size: int = DEFAULT_PREVIEW_SIZE) -> None:
    box_map = load_box(box_path)
    image_size = _validate_image_size(image_size)
    output_path = Path(png_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    _configure_offscreen_window(image_size)

    from direct.showbase.ShowBase import ShowBase

    app = ShowBase(windowType="offscreen")
    try:
        app.setFrameRateMeter(False)
        app.disableMouse()
        app.setBackgroundColor(0.0, 0.0, 0.0, 0.0)
        app.win.setClearColorActive(True)
        app.win.setClearColor((0.0, 0.0, 0.0, 0.0))

        root = app.render.attachNewNode("box-preview")
        _setup_lights(app, box_map)
        _attach_chunk_meshes(root, box_map)
        _attach_block_lights(app, box_map)
        _setup_camera(app, box_map)

        app.graphicsEngine.renderFrame()
        app.graphicsEngine.renderFrame()
        app.win.saveScreenshot(Filename.fromOsSpecific(str(output_path)))
    finally:
        app.destroy()


def default_png_path(box_path: str | Path) -> Path:
    return Path(box_path).with_suffix(".png")


def _validate_image_size(image_size: int) -> int:
    try:
        value = int(image_size)
    except (TypeError, ValueError) as exc:
        raise ValueError("PNG render size must be an integer") from exc
    if value < MIN_PREVIEW_SIZE:
        raise ValueError(f"PNG render size must be at least {MIN_PREVIEW_SIZE}")
    return value


def _configure_offscreen_window(image_size: int) -> None:
    loadPrcFileData(
        "",
        "\n".join(
            [
                "window-type offscreen",
                f"win-size {image_size} {image_size}",
                "framebuffer-alpha true",
                "textures-power-2 none",
                "audio-library-name null",
                "sync-video false",
                "show-frame-rate-meter false",
                "print-pipe-types false",
                "notify-level error",
                "default-directnotify-level error",
            ]
        ),
    )


def _setup_lights(app, box_map: BoxMap) -> None:
    ambient = AmbientLight("preview-ambient")
    ambient.setColor((0.36, 0.38, 0.42, 1.0))
    app.render.setLight(app.render.attachNewNode(ambient))

    key = DirectionalLight("preview-key")
    key.setColor((0.95, 0.92, 0.84, 1.0))
    key_path = app.render.attachNewNode(key)
    key_path.setHpr(-38.0, -48.0, 0.0)
    app.render.setLight(key_path)

    fill = DirectionalLight("preview-fill")
    fill.setColor((0.20, 0.24, 0.32, 1.0))
    fill_path = app.render.attachNewNode(fill)
    fill_path.setHpr(135.0, -20.0, 0.0)
    app.render.setLight(fill_path)

    if any(is_light_color(color) for color in box_map.boxes.values()):
        app.render.setShaderAuto()


def _attach_chunk_meshes(root, box_map: BoxMap) -> None:
    for key in _chunk_keys(box_map):
        mesh = build_chunk_mesh(box_map.boxes, key, box_map.size, CHUNK_SIZE)
        if mesh.opaque:
            mesh.opaque.reparentTo(root)
        if mesh.transparent:
            mesh.transparent.reparentTo(root)
            mesh.transparent.setTransparency(TransparencyAttrib.MAlpha)
            mesh.transparent.setBin("transparent", 0)
            mesh.transparent.setDepthWrite(False)


def _chunk_keys(box_map: BoxMap) -> list[ChunkKey]:
    return sorted({chunk_key_for_cell(cell) for cell in box_map.boxes})


def _attach_block_lights(app, box_map: BoxMap) -> None:
    for cell, color in box_map.boxes.items():
        if not is_light_color(color):
            continue
        light = PointLight(f"preview-block-light-{cell[0]}-{cell[1]}-{cell[2]}")
        light.setColor((color[0], color[1], color[2], 1.0))
        light.setAttenuation((1.0, 0.12, 0.035))
        light_path = app.render.attachNewNode(light)
        light_path.setPos(cell[0] + 0.5, cell[1] + 0.5, cell[2] + 0.5)
        app.render.setLight(light_path)


def _setup_camera(app, box_map: BoxMap) -> None:
    minimum, maximum = _model_bounds(box_map)
    target = Point3(
        (minimum.x + maximum.x) * 0.5,
        (minimum.y + maximum.y) * 0.5,
        (minimum.z + maximum.z) * 0.5,
    )
    view_direction = Vec3(VIEW_DIRECTION)
    view_direction.normalize()
    radius = max((maximum - minimum).length() * 0.5, 1.0)
    distance = max(12.0, radius * 4.0)

    camera_pos = target + view_direction * distance
    app.camera.setPos(camera_pos)
    app.camera.lookAt(target)

    lens = OrthographicLens()
    film_size = _projected_film_size(minimum, maximum, target, camera_pos) * 1.16
    lens.setFilmSize(max(1.0, film_size), max(1.0, film_size))
    lens.setNearFar(0.1, distance + radius * 4.0 + box_map.size + 8.0)
    app.cam.node().setLens(lens)


def _model_bounds(box_map: BoxMap) -> tuple[Point3, Point3]:
    if not box_map.boxes:
        center = box_map.size * 0.5
        return Point3(center - 0.5, center - 0.5, center - 0.5), Point3(center + 0.5, center + 0.5, center + 0.5)

    cells = list(box_map.boxes)
    min_x = min(cell[0] for cell in cells)
    min_y = min(cell[1] for cell in cells)
    min_z = min(cell[2] for cell in cells)
    max_x = max(cell[0] for cell in cells) + 1
    max_y = max(cell[1] for cell in cells) + 1
    max_z = max(cell[2] for cell in cells) + 1
    return Point3(min_x, min_y, min_z), Point3(max_x, max_y, max_z)


def _projected_film_size(minimum: Point3, maximum: Point3, target: Point3, camera_pos: Point3) -> float:
    forward = Vec3(target - camera_pos)
    forward.normalize()
    right = forward.cross(Vec3(0.0, 0.0, 1.0))
    if right.lengthSquared() < 0.0001:
        right = Vec3(1.0, 0.0, 0.0)
    right.normalize()
    up = right.cross(forward)
    up.normalize()

    projected_x: list[float] = []
    projected_y: list[float] = []
    for corner in _bounds_corners(minimum, maximum):
        offset = corner - target
        projected_x.append(offset.dot(right))
        projected_y.append(offset.dot(up))
    width = max(projected_x) - min(projected_x)
    height = max(projected_y) - min(projected_y)
    return max(width, height)


def _bounds_corners(minimum: Point3, maximum: Point3) -> list[Point3]:
    return [
        Point3(x, y, z)
        for x in (minimum.x, maximum.x)
        for y in (minimum.y, maximum.y)
        for z in (minimum.z, maximum.z)
    ]
