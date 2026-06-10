from __future__ import annotations

import math
from pathlib import Path
import re
from typing import Callable

from direct.gui.DirectGui import DirectButton, DirectFrame, DirectLabel
from direct.gui.OnscreenText import OnscreenText
from direct.showbase.ShowBase import ShowBase
from direct.showbase.ShowBaseGlobal import globalClock
from panda3d.core import (
    AmbientLight,
    AntialiasAttrib,
    BitMask32,
    DirectionalLight,
    Filename,
    Geom,
    GeomNode,
    GeomTriangles,
    GeomVertexData,
    GeomVertexFormat,
    GeomVertexWriter,
    OrthographicLens,
    LineSegs,
    NodePath,
    Point2,
    Point3,
    TransparencyAttrib,
    Vec3,
    WindowProperties,
    loadPrcFileData,
)

from .audio import ensure_sound_files
from .box_file import BoxFormatError, BoxMap, Cell, DEFAULT_COLOR, MAX_N, MIN_N, RGBA, load_box, save_box
from .geometry import FaceNormal, make_bounds, make_checker_ground, make_cube_outline, make_cuboid
from .gpu import GpuProfile, detect_gpu_profile
from .platform_window import disable_ime_for_window, maximize_window
from .voxel_mesh import (
    CHUNK_SIZE,
    ChunkKey,
    ChunkMesh,
    build_chunk_mesh,
    chunk_key_for_cell,
    neighbor_hides_face,
    visible_faces_for_cell,
)


loadPrcFileData(
    "",
    "\n".join(
        [
            "window-title Box Editor View",
            "sync-video false",
            "show-frame-rate-meter true",
            "textures-power-2 none",
            "framebuffer-multisample true",
            "multisamples 4",
        ]
    ),
)


SHADOW_CAMERA_MASK = BitMask32.bit(30)
FACE_NORMALS: tuple[FaceNormal, ...] = (
    (1, 0, 0),
    (-1, 0, 0),
    (0, 1, 0),
    (0, -1, 0),
    (0, 0, 1),
    (0, 0, -1),
)
MIN_SHADOW_SPAN = 32.0
SHADOW_PADDING = 12.0
PLAYER_WIDTH = 0.96
PLAYER_HEIGHT = 1.8
EYE_HEIGHT = 1.70
CAMERA_NEAR = 0.03
CAMERA_FOV = 82.0
MOVE_SPEED = 5.2
VERTICAL_SPEED = 4.4
MOUSE_SENSITIVITY = 0.055
STANDING_TOLERANCE = 0.10
SOUND_VOLUME = 0.5
CLOSE_REQUEST_EVENT = "box-editor-close-request"
STARTUP_MAXIMIZE_FRAMES = 30


class _NullSound:
    def setVolume(self, _volume: float) -> None:
        pass

    def play(self) -> None:
        pass


class BoxEditorApp(ShowBase):
    def __init__(self, path: Path | None, new_file: bool, new_n: int) -> None:
        super().__init__()
        self.disableMouse()
        self.camLens.setNear(CAMERA_NEAR)
        self.camLens.setFov(CAMERA_FOV)
        self._sync_camera_aspect()

        self.path = path or Path.cwd() / "untitled.box"
        self.box_map = self._load_initial_map(self.path, new_file, new_n)
        self.current_color: RGBA = DEFAULT_COLOR
        self.saved_snapshot = self._current_map_snapshot()
        self.gpu_profile: GpuProfile = detect_gpu_profile(self.win.getGsg() if self.win else None)
        self.window_maximized = maximize_window(self.win)
        self.ime_disabled = disable_ime_for_window(self.win)

        self.world = self.render.attachNewNode("world")
        self.blocks_root = self.world.attachNewNode("blocks")
        self.chunk_meshes: dict[ChunkKey, ChunkMesh] = {}
        self.ground_node: NodePath | None = None
        self.bounds_node: NodePath | None = None
        self.hover_outline = make_cube_outline()
        self.hover_outline.reparentTo(self.world)
        self.hover_shadow_mask = BitMask32.allOff()
        self.hover_outline.hide()
        self.hovered_cell: Cell | None = None

        self.player_pos = Vec3(self.box_map.size * 0.5, 0.5, 1.0)
        self.heading = 0.0
        self.pitch = -12.0
        self.view_mode = "first"
        self.mouse_captured = False
        self.ui_open = False
        self.modal_mode: str | None = None
        self.color_panel: DirectFrame | None = None
        self.help_panel: DirectFrame | None = None
        self.n_panel: DirectFrame | None = None
        self.n_confirm_panel: DirectFrame | None = None
        self.quit_panel: DirectFrame | None = None
        self.n_value_label: DirectLabel | None = None
        self.n_arrow_buttons: list[DirectButton] = []
        self.n_arrow_icons: list[NodePath] = []
        self.color_fields: dict[str, str] = {}
        self.color_field_widgets: dict[str, DirectButton] = {}
        self.active_color_field = "rgba"
        self.color_target: Cell | None = None
        self.pending_n = self.box_map.n
        self.quit_button_frames: dict[str, DirectFrame] = {}
        self.quit_buttons: dict[str, DirectButton] = {}
        self.active_quit_choice = "cancel"
        self.quit_restore_mouse_capture = False
        self.startup_maximize_frames = STARTUP_MAXIMIZE_FRAMES

        self.key_state = {
            "forward": False,
            "back": False,
            "left": False,
            "right": False,
            "up": False,
            "shift": False,
        }

        self._setup_lights()
        self._setup_world()
        self._lift_player_out_of_blocks()
        self._setup_player_model()
        self._setup_hud()
        self._setup_audio()
        self._bind_events()

        self.set_mouse_capture(True)
        self.taskMgr.add(self._update, "box-editor-update")
        self._set_status("Ready")

    def _load_initial_map(self, path: Path, new_file: bool, new_n: int) -> BoxMap:
        if path.exists() and not new_file:
            try:
                return load_box(path)
            except BoxFormatError as exc:
                raise SystemExit(f"Cannot open {path}: {exc}") from exc
        return BoxMap(n=new_n)

    def _sync_camera_aspect(self) -> None:
        if not self.win or not hasattr(self.win, "getXSize") or not hasattr(self.win, "getYSize"):
            return
        width = max(1, self.win.getXSize())
        height = max(1, self.win.getYSize())
        self.camLens.setAspectRatio(width / height)

    def _current_map_snapshot(self) -> str:
        return repr((self.box_map.n, tuple(sorted(self.box_map.boxes.items()))))

    def _has_unsaved_changes(self) -> bool:
        return self.saved_snapshot != self._current_map_snapshot()

    def _setup_lights(self) -> None:
        ambient = AmbientLight("ambient")
        ambient.setColor((0.30, 0.32, 0.36, 1.0))
        self.render.setLight(self.render.attachNewNode(ambient))

        sun = DirectionalLight("sun")
        sun.setColor((1.0, 0.94, 0.82, 1.0))
        if self.gpu_profile.shadow_map_size > 0:
            sun.setShadowCaster(True, self.gpu_profile.shadow_map_size, self.gpu_profile.shadow_map_size)
        sun.setCameraMask(SHADOW_CAMERA_MASK)
        sun_lens = OrthographicLens()
        shadow_span = self._shadow_scene_span()
        sun_lens.setFilmSize(shadow_span, shadow_span)
        sun_lens.setNearFar(-shadow_span, shadow_span)
        sun.setLens(sun_lens)
        sun_path = self.render.attachNewNode(sun)
        center = self.box_map.size * 0.5
        sun_path.setPos(center, center, center)
        sun_path.setHpr(-38, -56, 0)
        self.render.setLight(sun_path)
        self.sun_lens = sun_lens
        self.sun_path = sun_path
        self.hover_shadow_mask = sun.getCameraMask()
        self.hover_outline.hide(self.hover_shadow_mask)

        fill = DirectionalLight("fill")
        fill.setColor((0.18, 0.22, 0.30, 1.0))
        fill_path = self.render.attachNewNode(fill)
        fill_path.setHpr(135, -18, 0)
        self.render.setLight(fill_path)

        if self.gpu_profile.shader_auto_enabled:
            self.render.setShaderAuto()
        if self.gpu_profile.antialias_enabled:
            self.render.setAntialias(AntialiasAttrib.MMultisample)
        self.setBackgroundColor(0.60, 0.72, 0.86, 1.0)

    def _shadow_scene_span(self) -> float:
        return max(MIN_SHADOW_SPAN, math.sqrt(3.0) * self.box_map.size + SHADOW_PADDING)

    def _sync_shadow_lens(self) -> None:
        if not hasattr(self, "sun_lens") or not hasattr(self, "sun_path"):
            return
        shadow_span = self._shadow_scene_span()
        self.sun_lens.setFilmSize(shadow_span, shadow_span)
        self.sun_lens.setNearFar(-shadow_span, shadow_span)
        center = self.box_map.size * 0.5
        self.sun_path.setPos(center, center, center)

    def _setup_world(self) -> None:
        self.ground_node.removeNode() if self.ground_node else None
        self.bounds_node.removeNode() if self.bounds_node else None
        self.blocks_root.removeNode()
        self.blocks_root = self.world.attachNewNode("blocks")
        self.chunk_meshes.clear()

        size = self.box_map.size
        self.ground_node = make_checker_ground(size)
        self.ground_node.reparentTo(self.world)
        self.ground_node.hide(self.hover_shadow_mask)

        self.bounds_node = make_bounds(size)
        self.bounds_node.reparentTo(self.world)
        self.bounds_node.hide(self.hover_shadow_mask)
        self._rebuild_all_chunks()

    def _setup_player_model(self) -> None:
        self.player_model = self.render.attachNewNode("player")
        self._add_player_part("body", (0.52, 0.28, 0.82), (0, 0, 1.08), (0.10, 0.34, 0.88, 1))
        self._add_player_part("head", (0.48, 0.48, 0.48), (0, 0, 1.74), (0.86, 0.70, 0.52, 1))
        self._add_player_part("left-arm", (0.18, 0.22, 0.72), (-0.37, 0, 1.08), (0.10, 0.34, 0.88, 1))
        self._add_player_part("right-arm", (0.18, 0.22, 0.72), (0.37, 0, 1.08), (0.10, 0.34, 0.88, 1))
        self._add_player_part("left-leg", (0.20, 0.24, 0.78), (-0.13, 0, 0.39), (0.12, 0.18, 0.42, 1))
        self._add_player_part("right-leg", (0.20, 0.24, 0.78), (0.13, 0, 0.39), (0.12, 0.18, 0.42, 1))
        self.player_model.setTransparency(TransparencyAttrib.MAlpha)
        self.player_model.hide()

    def _add_player_part(
        self,
        name: str,
        size: tuple[float, float, float],
        pos: tuple[float, float, float],
        color: tuple[float, float, float, float],
    ) -> None:
        part = make_cuboid(name, size)
        part.reparentTo(self.player_model)
        part.setPos(*pos)
        part.setColor(*color)

    def _setup_hud(self) -> None:
        self.status = OnscreenText(
            text="",
            pos=(-1.31, 0.94),
            align=0,
            scale=0.038,
            fg=(1, 1, 1, 1),
            mayChange=True,
            shadow=(0, 0, 0, 0.7),
        )
        self.detail = OnscreenText(
            text="",
            pos=(-1.31, 0.89),
            align=0,
            scale=0.031,
            fg=(1, 1, 1, 0.92),
            mayChange=True,
            shadow=(0, 0, 0, 0.7),
        )
        self.help_hint = OnscreenText(
            text="Press H for help",
            pos=(1.30, 0.94),
            align=1,
            scale=0.033,
            fg=(1, 1, 1, 0.92),
            mayChange=False,
            shadow=(0, 0, 0, 0.7),
        )
        self.center_hint = OnscreenText(
            text="Press C to look at editor center",
            pos=(1.30, 0.90),
            align=1,
            scale=0.030,
            fg=(1, 1, 1, 0.88),
            mayChange=False,
            shadow=(0, 0, 0, 0.7),
        )
        self.crosshair = self._make_crosshair()
        self.crosshair.reparentTo(self.aspect2d)

    def _make_crosshair(self) -> NodePath:
        lines = LineSegs()
        lines.setThickness(2.0)
        lines.setColor(1, 1, 1, 0.92)
        lines.moveTo(-0.018, 0, 0)
        lines.drawTo(0.018, 0, 0)
        lines.moveTo(0, 0, -0.018)
        lines.drawTo(0, 0, 0.018)
        return NodePath(lines.create())

    def _setup_audio(self) -> None:
        sound_paths = ensure_sound_files()
        self.place_sound = self._load_sound(sound_paths["place"])
        self.break_sound = self._load_sound(sound_paths["break"])

    def _load_sound(self, path: Path):
        panda_path = Filename.fromOsSpecific(str(path)).getFullpath()
        sound = self.loader.loadSfx(panda_path)
        sound = sound if sound is not None else _NullSound()
        sound.setVolume(SOUND_VOLUME)
        return sound

    def _bind_events(self) -> None:
        self._setup_close_request_event()
        binds: dict[str, tuple[str, bool]] = {
            "w": ("forward", True),
            "w-up": ("forward", False),
            "s": ("back", True),
            "s-up": ("back", False),
            "a": ("left", True),
            "a-up": ("left", False),
            "d": ("right", True),
            "d-up": ("right", False),
            "space": ("up", True),
            "space-up": ("up", False),
            "shift": ("shift", True),
            "shift-up": ("shift", False),
        }
        for event, (name, value) in binds.items():
            self.accept(event, self._set_key, [name, value])

        self.accept("mouse1", self._delete_clicked_block)
        self.accept("mouse2", self._pick_clicked_block_color)
        self.accept("mouse3", self._right_click)
        self.accept("escape", self._release_mouse_capture)
        self.accept("window-event", self._handle_window_event)
        self.accept("f2", self.save_current)
        self.accept("control-s", self.save_current)
        self.accept("f5", self._toggle_view)
        self.accept("e", self._edit_target_block_color)
        self.accept("h", self._open_help)
        self.accept("c", self._look_at_editor_focus)
        self.accept("n", self._open_n_editor)
        self._bind_color_input_events()

    def _setup_close_request_event(self) -> None:
        if hasattr(self.win, "setCloseRequestEvent"):
            self.win.setCloseRequestEvent(CLOSE_REQUEST_EVENT)
            self.accept(CLOSE_REQUEST_EVENT, self._request_quit)

    def _bind_color_input_events(self) -> None:
        for digit in "0123456789":
            self.accept(digit, self._append_color_input, [digit])
        self.accept(".", self._append_color_input, ["."])
        self.accept("period", self._append_color_input, ["."])
        self.accept(",", self._append_color_input, [","])
        self.accept("comma", self._append_color_input, [","])
        self.accept(";", self._append_color_input, [";"])
        self.accept("semicolon", self._append_color_input, [";"])
        self.accept("backspace", self._backspace_color_input)
        self.accept("delete", self._clear_color_input)
        self.accept("enter", self._submit_color_input)
        self.accept("tab", self._focus_next_color_field, [1])
        self.accept("shift-tab", self._focus_next_color_field, [-1])
        self.accept("shift_tab", self._focus_next_color_field, [-1])
        self.accept("arrow_right", self._focus_next_color_field, [1])
        self.accept("arrow_left", self._focus_next_color_field, [-1])

    def _set_key(self, name: str, value: bool) -> None:
        if self.ui_open:
            if self.modal_mode == "color" and name == "up" and value:
                self._append_color_input(" ")
            self.key_state[name] = False
            return
        self.key_state[name] = value

    def _update(self, task):
        dt = globalClock.getDt()
        self._keep_startup_window_maximized()
        if self.mouse_captured and not self.ui_open:
            self._update_mouse_look()
        if not self.ui_open:
            self._update_player(dt)
        self._update_camera()
        self._update_hover_outline()
        self._update_hud()
        return task.cont

    def _keep_startup_window_maximized(self) -> None:
        if self.startup_maximize_frames <= 0:
            return
        self.window_maximized = maximize_window(self.win) or self.window_maximized
        self.startup_maximize_frames -= 1

    def _update_mouse_look(self) -> None:
        if not self.win or not hasattr(self.win, "getPointer"):
            return
        pointer = self.win.getPointer(0)
        center_x = self.win.getXSize() // 2
        center_y = self.win.getYSize() // 2
        dx = pointer.getX() - center_x
        dy = pointer.getY() - center_y
        if dx or dy:
            self.heading -= dx * MOUSE_SENSITIVITY
            self.pitch = max(-89.0, min(89.0, self.pitch - dy * MOUSE_SENSITIVITY))
            self.win.movePointer(0, center_x, center_y)

    def _update_player(self, dt: float) -> None:
        heading_rad = math.radians(self.heading)
        forward = Vec3(-math.sin(heading_rad), math.cos(heading_rad), 0)
        right = Vec3(math.cos(heading_rad), math.sin(heading_rad), 0)
        desired = Vec3(0, 0, 0)

        if self.key_state["forward"]:
            desired += forward
        if self.key_state["back"]:
            desired -= forward
        if self.key_state["right"]:
            desired += right
        if self.key_state["left"]:
            desired -= right
        if desired.lengthSquared() > 0:
            desired.normalize()
            desired *= MOVE_SPEED * dt
        if self.key_state["up"]:
            desired.z += VERTICAL_SPEED * dt
        if self.key_state["shift"]:
            desired.z -= VERTICAL_SPEED * dt

        self._move_player_with_collision(desired)
        self.player_model.setPos(self.player_pos)
        self.player_model.setH(self.heading)

    def _move_player_with_collision(self, movement: Vec3) -> None:
        for component in (Vec3(movement.x, 0, 0), Vec3(0, movement.y, 0), Vec3(0, 0, movement.z)):
            if component.lengthSquared() == 0:
                continue
            candidate = self._clamp_player_position(self.player_pos + component)
            if not self._player_collides(candidate):
                self.player_pos = candidate
            elif component.z < 0:
                self._snap_player_to_support(abs(component.z) + STANDING_TOLERANCE)

    def _clamp_player_position(self, pos: Vec3) -> Vec3:
        padding = max(5.0, float(self.box_map.size))
        lower_xy = -padding
        upper = self.box_map.size + padding
        return Vec3(
            max(lower_xy, min(upper, pos.x)),
            max(lower_xy, min(upper, pos.y)),
            max(0.0, min(upper, pos.z)),
        )

    def _player_collides(self, pos: Vec3) -> bool:
        min_corner, max_corner = self._player_aabb(pos)
        min_x = math.floor(min_corner.x)
        max_x = math.floor(max_corner.x)
        min_y = math.floor(min_corner.y)
        max_y = math.floor(max_corner.y)
        min_z = math.floor(min_corner.z)
        max_z = math.floor(max_corner.z)

        for x in range(min_x, max_x + 1):
            for y in range(min_y, max_y + 1):
                for z in range(min_z, max_z + 1):
                    if (x, y, z) in self.box_map.boxes and self._aabb_overlap(
                        (min_corner.x, min_corner.y, min_corner.z),
                        (max_corner.x, max_corner.y, max_corner.z),
                        (x, y, z),
                        (x + 1, y + 1, z + 1),
                    ):
                        return True
        return False

    def _lift_player_out_of_blocks(self) -> None:
        position = self._clamp_player_position(self.player_pos)
        upper = self.box_map.size + max(5.0, float(self.box_map.size))
        while position.z <= upper:
            if not self._player_collides(position) and self._player_head_and_feet_clear(position):
                self.player_pos = position
                return
            position = Vec3(position.x, position.y, position.z + 1.0)
        self.player_pos = self._clamp_player_position(position)

    def _player_head_and_feet_clear(self, pos: Vec3) -> bool:
        foot_cell = self._point_cell(Vec3(pos.x, pos.y, pos.z))
        head_cell = self._point_cell(Vec3(pos.x, pos.y, pos.z + PLAYER_HEIGHT))
        return foot_cell not in self.box_map.boxes and head_cell not in self.box_map.boxes

    def _point_cell(self, point: Vec3) -> Cell:
        return (math.floor(point.x), math.floor(point.y), math.floor(point.z))

    def _player_aabb(self, pos: Vec3) -> tuple[Vec3, Vec3]:
        half = PLAYER_WIDTH * 0.5
        return Vec3(pos.x - half, pos.y - half, pos.z), Vec3(pos.x + half, pos.y + half, pos.z + PLAYER_HEIGHT)

    def _update_camera(self) -> None:
        eye = self.player_pos + Vec3(0, 0, EYE_HEIGHT)
        if self.view_mode == "first":
            self.player_model.hide()
            self.camera.setPos(eye)
            self.camera.setHpr(self.heading, self.pitch, 0)
        else:
            self.player_model.show()
            heading_rad = math.radians(self.heading)
            back = Vec3(math.sin(heading_rad), -math.cos(heading_rad), 0) * 4.8
            cam_pos = eye + back + Vec3(0, 0, 1.55)
            self.camera.setPos(cam_pos)
            self.camera.lookAt(eye + Vec3(0, 0, 0.25))

    def _update_hud(self) -> None:
        color = ", ".join(str(round(channel * 255)) for channel in self.current_color)
        gpu_mode = "GPU" if self.gpu_profile.hardware_accelerated else "software"
        self.detail.setText(
            f"{self.path.name}  N={self.box_map.n}  size={self.box_map.size}  "
            f"blocks={len(self.box_map.boxes)}  color=({color})  view={self.view_mode}  {gpu_mode}"
        )

    def _set_status(self, text: str) -> None:
        self.status.setText(text)

    def _right_click(self) -> None:
        if self.ui_open:
            return
        if not self.mouse_captured:
            self.set_mouse_capture(True)
            self._set_status("Mouse captured")
            return
        hit = self._pick()
        if hit is None:
            return
        hit_type, cell, normal, point = hit
        if self.key_state["shift"]:
            return

        target = self._placement_cell(hit_type, cell, normal, point)
        if target is None or target in self.box_map.boxes or self._block_intersects_player(target):
            return
        if self.box_map.set_box(target, self.current_color):
            self._refresh_block_and_neighbors(target)
            self.place_sound.play()
            self._set_status(f"Placed {target}")

    def _delete_clicked_block(self) -> None:
        if self.ui_open:
            return
        if not self.mouse_captured:
            self.set_mouse_capture(True)
            self._set_status("Mouse captured")
            return
        hit = self._pick()
        if hit is None:
            return
        hit_type, cell, _normal, _point = hit
        if hit_type == "block" and cell is not None and self.box_map.remove_box(cell):
            self._refresh_block_and_neighbors(cell)
            self.break_sound.play()
            self._set_status(f"Deleted {cell}")

    def _pick_clicked_block_color(self) -> None:
        if self.ui_open:
            return
        if not self.mouse_captured:
            self.set_mouse_capture(True)
            self._set_status("Mouse captured")
            return
        hit = self._pick()
        if hit is None:
            return
        hit_type, cell, _normal, _point = hit
        if hit_type != "block" or cell is None:
            return

        color = self.box_map.get_box(cell)
        if color is None:
            return
        self.current_color = color
        picked = ", ".join(str(round(channel * 255)) for channel in color)
        self._set_status(f"Picked color ({picked})")

    def _edit_target_block_color(self) -> None:
        if self.ui_open:
            return
        if not self.mouse_captured:
            self.set_mouse_capture(True)
            self._set_status("Mouse captured")
            return

        hit = self._pick()
        if hit is None:
            return
        hit_type, cell, _normal, _point = hit
        if hit_type == "block" and cell is not None:
            self._open_color_editor(cell)

    def _look_at_editor_focus(self) -> None:
        if self.ui_open:
            return

        target = self._editor_focus_target()
        self._look_at_point(target)
        if self.box_map.boxes:
            self._set_status("Looking at block centroid")
        else:
            self._set_status("Looking at editor center")

    def _editor_focus_target(self) -> Point3:
        if not self.box_map.boxes:
            center = self.box_map.size * 0.5
            return Point3(center, center, 0.0)

        total = Vec3(0, 0, 0)
        for x, y, z in self.box_map.boxes:
            total += Vec3(x + 0.5, y + 0.5, z + 0.5)
        count = len(self.box_map.boxes)
        return Point3(total.x / count, total.y / count, total.z / count)

    def _look_at_point(self, target: Point3) -> None:
        eye = self.player_pos + Vec3(0, 0, EYE_HEIGHT)
        direction = Vec3(target.x - eye.x, target.y - eye.y, target.z - eye.z)
        if direction.lengthSquared() == 0:
            return

        horizontal = math.hypot(direction.x, direction.y)
        if horizontal > 0.0001:
            self.heading = math.degrees(math.atan2(-direction.x, direction.y))
        self.pitch = max(-89.0, min(89.0, math.degrees(math.atan2(direction.z, horizontal))))

    def _open_help(self) -> None:
        if self.ui_open:
            return

        self.ui_open = True
        self.modal_mode = "help"
        self._clear_movement_keys()
        self.set_mouse_capture(False)
        self.crosshair.hide()

        self.help_panel = DirectFrame(
            frameColor=(0.05, 0.06, 0.07, 0.97),
            frameSize=(-0.82, 0.82, -0.68, 0.68),
            pos=(0, 0, 0),
        )
        DirectLabel(
            parent=self.help_panel,
            text="Controls",
            text_fg=(1, 1, 1, 1),
            text_scale=0.065,
            frameColor=(0, 0, 0, 0),
            pos=(0, 0, 0.55),
        )
        DirectLabel(
            parent=self.help_panel,
            text="\n".join(
                [
                    "Click window: capture mouse",
                    "Mouse: look around",
                    "WASD: move horizontally",
                    "Space: move upward",
                    "Shift: move downward",
                    "Right click: place cube",
                    "Left click: delete cube",
                    "Middle click: pick cube color",
                    "E: edit cube RGBA",
                    "N: change map size N",
                    "C: look at editor center / cube centroid",
                    "F5: switch first/third person",
                    "F2 or Ctrl+S: save",
                    "Esc: release mouse and show exit choices / close dialogs",
                    "In dialogs: Tab/Shift+Tab or arrows switch focus",
                    "In color editor: type RGBA values",
                ]
            ),
            text_align=0,
            text_fg=(0.92, 0.94, 0.96, 1),
            text_scale=0.038,
            frameColor=(0, 0, 0, 0),
            pos=(-0.65, 0, 0.38),
        )
        self._help_button("OK", (0, 0, -0.55), self._close_help)
        self._set_status("Help")

    def _help_button(self, text: str, pos: tuple[float, float, float], command: Callable[[], None]) -> DirectButton:
        return DirectButton(
            parent=self.help_panel,
            text=text,
            text_scale=0.045,
            frameSize=(-0.14, 0.14, -0.05, 0.06),
            frameColor=(0.24, 0.29, 0.34, 1),
            text_fg=(1, 1, 1, 1),
            pos=pos,
            command=command,
        )

    def _close_help(self) -> None:
        if self.help_panel:
            self.help_panel.destroy()
        self.help_panel = None
        self.ui_open = False
        self.modal_mode = None
        self.crosshair.show()
        self.set_mouse_capture(True)
        self._set_status("Ready")

    def _open_n_editor(self) -> None:
        if self.ui_open:
            return

        self.ui_open = True
        self.modal_mode = "n"
        self.pending_n = self.box_map.n
        self._clear_movement_keys()
        self.set_mouse_capture(False)
        self.crosshair.hide()

        self.n_panel = DirectFrame(
            frameColor=(0.05, 0.06, 0.07, 0.97),
            frameSize=(-0.48, 0.48, -0.38, 0.38),
            pos=(0, 0, 0),
        )
        DirectLabel(
            parent=self.n_panel,
            text="Map Size N",
            text_fg=(1, 1, 1, 1),
            text_scale=0.058,
            frameColor=(0, 0, 0, 0),
            pos=(0, 0, 0.25),
        )
        DirectLabel(
            parent=self.n_panel,
            text=f"Range {MIN_N}..{MAX_N}",
            text_fg=(0.82, 0.86, 0.90, 1),
            text_scale=0.032,
            frameColor=(0, 0, 0, 0),
            pos=(0, 0, 0.17),
        )
        self.n_value_label = DirectLabel(
            parent=self.n_panel,
            text=str(self.pending_n),
            text_fg=(1, 1, 1, 1),
            text_scale=0.088,
            frameColor=(0.12, 0.15, 0.18, 1),
            frameSize=(-0.12, 0.12, -0.075, 0.075),
            pos=(0, 0, 0.02),
        )
        self.n_arrow_buttons = []
        self.n_arrow_icons = []
        self._n_arrow_button(True, (0.20, 0, 0.08), 1)
        self._n_arrow_button(False, (0.20, 0, -0.07), -1)
        self._n_dialog_button("OK", (-0.16, 0, -0.25), self._confirm_n_editor)
        self._n_dialog_button("Cancel", (0.16, 0, -0.25), self._close_n_editor)
        self._set_status("Edit N")

    def _n_arrow_button(self, points_up: bool, pos: tuple[float, float, float], direction: int) -> DirectButton:
        button = DirectButton(
            parent=self.n_panel,
            text="",
            frameSize=(-0.055, 0.055, -0.045, 0.055),
            frameColor=(0.24, 0.29, 0.34, 1),
            pos=pos,
            command=self._change_pending_n,
            extraArgs=[direction],
        )
        icon = self._make_n_arrow_icon(points_up)
        icon.reparentTo(button)
        self.n_arrow_buttons.append(button)
        self.n_arrow_icons.append(icon)
        return button

    def _make_n_arrow_icon(self, points_up: bool) -> NodePath:
        vertex_data = GeomVertexData("n-arrow", GeomVertexFormat.getV3c4(), Geom.UHStatic)
        vertex_writer = GeomVertexWriter(vertex_data, "vertex")
        color_writer = GeomVertexWriter(vertex_data, "color")
        vertices = ((0.0, 0.0, 0.030), (-0.032, 0.0, -0.023), (0.032, 0.0, -0.023))
        if not points_up:
            vertices = tuple((x, y, -z) for x, y, z in vertices)
        for vertex in vertices:
            vertex_writer.addData3f(*vertex)
            color_writer.addData4f(1.0, 1.0, 1.0, 1.0)

        triangles = GeomTriangles(Geom.UHStatic)
        triangles.addVertices(0, 1, 2)
        geom = Geom(vertex_data)
        geom.addPrimitive(triangles)
        node = GeomNode("n-arrow")
        node.addGeom(geom)
        return NodePath(node)

    def _n_dialog_button(self, text: str, pos: tuple[float, float, float], command: Callable[[], None]) -> DirectButton:
        return DirectButton(
            parent=self.n_panel,
            text=text,
            text_scale=0.039,
            frameSize=(-0.12, 0.12, -0.048, 0.055),
            frameColor=(0.24, 0.29, 0.34, 1),
            text_fg=(1, 1, 1, 1),
            pos=pos,
            command=command,
        )

    def _change_pending_n(self, direction: int) -> None:
        if self.modal_mode != "n":
            return
        self.pending_n = max(MIN_N, min(MAX_N, self.pending_n + direction))
        if self.n_value_label is not None:
            self.n_value_label["text"] = str(self.pending_n)

    def _confirm_n_editor(self) -> None:
        if self.modal_mode != "n":
            return
        if self.pending_n == self.box_map.n:
            self._close_n_editor()
            self._set_status("N unchanged")
            return
        if self._cells_outside_n(self.pending_n):
            self._open_n_shrink_confirm()
            return
        self._apply_pending_n()
        self._close_n_editor()

    def _open_n_shrink_confirm(self) -> None:
        if self.n_confirm_panel:
            self.n_confirm_panel.destroy()
        if self.n_panel:
            self.n_panel.hide()
        self.modal_mode = "n-confirm"
        self.n_confirm_panel = DirectFrame(
            frameColor=(0.04, 0.05, 0.06, 0.98),
            frameSize=(-0.78, 0.78, -0.30, 0.30),
            pos=(0, 0, 0),
        )
        DirectLabel(
            parent=self.n_confirm_panel,
            text="Confirm N Change",
            text_fg=(1, 1, 1, 1),
            text_scale=0.054,
            frameColor=(0, 0, 0, 0),
            pos=(0, 0, 0.18),
        )
        DirectLabel(
            parent=self.n_confirm_panel,
            text="Changing N changes the map size.\nShrinking the map may remove some cubes. Confirm?",
            text_fg=(0.92, 0.94, 0.96, 1),
            text_scale=0.032,
            frameColor=(0, 0, 0, 0),
            pos=(0, 0, 0.03),
        )
        self._n_confirm_button("Confirm", (-0.18, 0, -0.17), self._confirm_shrink_n_change)
        self._n_confirm_button("Cancel", (0.18, 0, -0.17), self._cancel_shrink_n_change)
        self._set_status("Confirm N change")

    def _n_confirm_button(self, text: str, pos: tuple[float, float, float], command: Callable[[], None]) -> DirectButton:
        return DirectButton(
            parent=self.n_confirm_panel,
            text=text,
            text_scale=0.038,
            frameSize=(-0.14, 0.14, -0.048, 0.055),
            frameColor=(0.24, 0.29, 0.34, 1),
            text_fg=(1, 1, 1, 1),
            pos=pos,
            command=command,
        )

    def _confirm_shrink_n_change(self) -> None:
        if self.modal_mode != "n-confirm":
            return
        self._apply_pending_n()
        self._close_n_editor()

    def _cancel_shrink_n_change(self) -> None:
        if self.n_confirm_panel:
            self.n_confirm_panel.destroy()
        self.n_confirm_panel = None
        if self.n_panel:
            self.n_panel.show()
        self.modal_mode = "n"
        self._set_status("Edit N")

    def _close_n_editor(self) -> None:
        if self.n_confirm_panel:
            self.n_confirm_panel.destroy()
        if self.n_panel:
            self.n_panel.destroy()
        self.n_confirm_panel = None
        self.n_panel = None
        self.n_value_label = None
        self.n_arrow_buttons = []
        self.n_arrow_icons = []
        self.pending_n = self.box_map.n
        self.ui_open = False
        self.modal_mode = None
        self.crosshair.show()
        self.set_mouse_capture(True)

    def _cells_outside_n(self, n: int) -> list[Cell]:
        size = 2**n
        return [cell for cell in self.box_map.boxes if any(part < 0 or part >= size for part in cell)]

    def _apply_pending_n(self) -> None:
        old_n = self.box_map.n
        self.box_map.n = self.pending_n
        removed = self._remove_out_of_bounds_boxes()
        self._setup_world()
        self.player_pos = self._clamp_player_position(self.player_pos)
        self._lift_player_out_of_blocks()
        self._sync_shadow_lens()
        if removed:
            self._set_status(f"N changed {old_n}->{self.box_map.n}; removed {removed} cubes")
        else:
            self._set_status(f"N changed {old_n}->{self.box_map.n}")

    def _remove_out_of_bounds_boxes(self) -> int:
        outside = self._cells_outside_n(self.box_map.n)
        for cell in outside:
            self.box_map.boxes.pop(cell, None)
        return len(outside)

    def _snap_player_to_support(self, tolerance: float) -> None:
        support_height = self._support_height_below(self.player_pos, tolerance)
        if support_height is None or support_height > self.player_pos.z:
            return
        if self.player_pos.z - support_height > tolerance:
            return

        snapped = Vec3(self.player_pos.x, self.player_pos.y, support_height)
        if not self._player_collides(snapped):
            self.player_pos = snapped

    def _support_height_below(self, pos: Vec3, tolerance: float) -> float | None:
        if pos.z < -tolerance:
            return None

        support: float | None = None
        if self._footprint_overlaps_ground(pos) and 0.0 <= pos.z + tolerance:
            support = 0.0

        min_corner, max_corner = self._player_aabb(pos)
        min_x = math.floor(min_corner.x)
        max_x = math.floor(max_corner.x)
        min_y = math.floor(min_corner.y)
        max_y = math.floor(max_corner.y)
        max_z = math.floor(pos.z + tolerance) - 1

        for x in range(min_x, max_x + 1):
            for y in range(min_y, max_y + 1):
                for z in range(max_z, -1, -1):
                    cell = (x, y, z)
                    if cell not in self.box_map.boxes:
                        continue
                    top = z + 1.0
                    if top > pos.z + tolerance:
                        continue
                    if self._footprint_overlaps_cell(pos, cell):
                        support = top if support is None else max(support, top)
                        break
        return support

    def _footprint_overlaps_ground(self, pos: Vec3) -> bool:
        min_corner, max_corner = self._player_aabb(pos)
        size = self.box_map.size
        return min_corner.x < size and max_corner.x > 0 and min_corner.y < size and max_corner.y > 0

    def _footprint_overlaps_cell(self, pos: Vec3, cell: Cell) -> bool:
        min_corner, max_corner = self._player_aabb(pos)
        return (
            min_corner.x < cell[0] + 1
            and max_corner.x > cell[0]
            and min_corner.y < cell[1] + 1
            and max_corner.y > cell[1]
        )

    def _update_hover_outline(self) -> None:
        if self.ui_open:
            self.hovered_cell = None
            self.hover_outline.hide()
            return

        hit = self._pick()
        if hit is None:
            self.hovered_cell = None
            self.hover_outline.hide()
            return

        hit_type, cell, _normal, _point = hit
        if hit_type == "block" and cell is not None:
            self.hovered_cell = cell
            self.hover_outline.setPos(cell[0] + 0.5, cell[1] + 0.5, cell[2] + 0.5)
            self.hover_outline.show()
            self.hover_outline.hide(self.hover_shadow_mask)
        else:
            self.hovered_cell = None
            self.hover_outline.hide()

    def _pick(self) -> tuple[str, Cell | None, Vec3, Point3] | None:
        ray = self._mouse_ray()
        if ray is None:
            return None
        origin, direction = ray

        hits: list[tuple[float, str, Cell | None, Vec3, Point3]] = []
        block_hit = self._raycast_blocks(origin, direction)
        if block_hit is not None:
            distance, cell, normal, point = block_hit
            hits.append((distance, "block", cell, normal, point))

        ground_hit = self._raycast_ground(origin, direction)
        if ground_hit is not None:
            distance, point = ground_hit
            hits.append((distance, "ground", None, Vec3(0, 0, 1), point))

        if not hits:
            return None
        _distance, hit_type, cell, normal, point = min(hits, key=lambda item: item[0])
        return hit_type, cell, normal, point

    def _mouse_ray(self) -> tuple[Point3, Vec3] | None:
        if self.mouseWatcherNode is None:
            mouse_x, mouse_y = 0.0, 0.0
        elif self.mouse_captured or not self.mouseWatcherNode.hasMouse():
            mouse_x, mouse_y = 0.0, 0.0
        else:
            mouse = self.mouseWatcherNode.getMouse()
            mouse_x, mouse_y = mouse.x, mouse.y

        near_point = Point3()
        far_point = Point3()
        if not self.camLens.extrude(Point2(mouse_x, mouse_y), near_point, far_point):
            return None
        origin = self.render.getRelativePoint(self.camera, near_point)
        far = self.render.getRelativePoint(self.camera, far_point)
        direction = far - origin
        if direction.lengthSquared() == 0:
            return None
        direction.normalize()
        return origin, direction

    def _raycast_ground(self, origin: Point3, direction: Vec3) -> tuple[float, Point3] | None:
        if abs(direction.z) < 1e-8:
            return None
        distance = -origin.z / direction.z
        if distance < 0:
            return None
        point = Point3(origin + direction * distance)
        if 0 <= point.x < self.box_map.size and 0 <= point.y < self.box_map.size:
            return distance, point
        return None

    def _raycast_blocks(self, origin: Point3, direction: Vec3) -> tuple[float, Cell, Vec3, Point3] | None:
        bounds = self._ray_box_intersection(origin, direction, 0.0, float(self.box_map.size))
        if bounds is None:
            return None
        entry_distance, exit_distance, entry_normal = bounds
        distance = max(0.0, entry_distance)
        position = origin + direction * (distance + 1e-6)
        size = self.box_map.size
        cell = [
            max(0, min(size - 1, math.floor(position.x))),
            max(0, min(size - 1, math.floor(position.y))),
            max(0, min(size - 1, math.floor(position.z))),
        ]

        steps: list[int] = []
        next_distances: list[float] = []
        delta_distances: list[float] = []
        for axis in range(3):
            component = direction[axis]
            if component > 0:
                steps.append(1)
                next_boundary = cell[axis] + 1.0
                next_distances.append((next_boundary - origin[axis]) / component)
                delta_distances.append(1.0 / component)
            elif component < 0:
                steps.append(-1)
                next_boundary = float(cell[axis])
                next_distances.append((next_boundary - origin[axis]) / component)
                delta_distances.append(-1.0 / component)
            else:
                steps.append(0)
                next_distances.append(math.inf)
                delta_distances.append(math.inf)

        normal = Vec3(*entry_normal)
        max_steps = size * 3 + 3
        for _ in range(max_steps):
            current = (cell[0], cell[1], cell[2])
            if current in self.box_map.boxes:
                point = Point3(origin + direction * distance)
                return distance, current, normal, point

            axis = min(range(3), key=lambda index: next_distances[index])
            distance = next_distances[axis]
            if distance > exit_distance:
                return None

            cell[axis] += steps[axis]
            if cell[axis] < 0 or cell[axis] >= size:
                return None
            normal = Vec3(0, 0, 0)
            normal[axis] = -steps[axis]
            next_distances[axis] += delta_distances[axis]
        return None

    def _ray_box_intersection(
        self,
        origin: Point3,
        direction: Vec3,
        minimum: float,
        maximum: float,
    ) -> tuple[float, float, tuple[int, int, int]] | None:
        entry = -math.inf
        exit = math.inf
        entry_normal = (0, 0, 0)
        for axis in range(3):
            component = direction[axis]
            origin_value = origin[axis]
            if abs(component) < 1e-8:
                if origin_value < minimum or origin_value > maximum:
                    return None
                continue

            near = (minimum - origin_value) / component
            far = (maximum - origin_value) / component
            near_normal_axis = -1
            if near > far:
                near, far = far, near
                near_normal_axis = 1
            if near > entry:
                normal = [0, 0, 0]
                normal[axis] = near_normal_axis
                entry = near
                entry_normal = (normal[0], normal[1], normal[2])
            exit = min(exit, far)
            if entry > exit:
                return None

        if exit < 0:
            return None
        return entry, exit, entry_normal

    def _placement_cell(
        self,
        hit_type: str,
        cell: Cell | None,
        normal: Vec3,
        point: Point3,
    ) -> Cell | None:
        if hit_type == "ground":
            x = math.floor(point.x)
            y = math.floor(point.y)
            target = (x, y, 0)
            return target if self.box_map.in_bounds(target) else None

        if hit_type != "block" or cell is None:
            return None

        axis = max(range(3), key=lambda index: abs(normal[index]))
        offset = [0, 0, 0]
        offset[axis] = 1 if normal[axis] >= 0 else -1
        target = (cell[0] + offset[0], cell[1] + offset[1], cell[2] + offset[2])
        return target if self.box_map.in_bounds(target) else None

    def _rebuild_all_chunks(self) -> None:
        for mesh in self.chunk_meshes.values():
            self._remove_chunk_mesh(mesh)
        self.chunk_meshes.clear()
        for key in {chunk_key_for_cell(cell) for cell in self.box_map.boxes}:
            self._rebuild_chunk(key)

    def _visible_faces_for_block(self, cell: Cell, color: RGBA) -> set[FaceNormal]:
        return visible_faces_for_cell(cell, color, self.box_map.boxes)

    def _neighbor_hides_face(self, color: RGBA, neighbor_color: RGBA) -> bool:
        return neighbor_hides_face(color, neighbor_color)

    def _refresh_block_node(self, cell: Cell) -> None:
        self._rebuild_chunks_for_cells([cell])

    def _refresh_block_and_neighbors(self, cell: Cell) -> None:
        self._rebuild_chunks_for_cells([cell, *self._neighbor_cells(cell)])

    def _neighbor_cells(self, cell: Cell) -> list[Cell]:
        return [(cell[0] + normal[0], cell[1] + normal[1], cell[2] + normal[2]) for normal in FACE_NORMALS]

    def _rebuild_chunks_for_cells(self, cells: list[Cell]) -> None:
        chunk_keys = {chunk_key_for_cell(cell) for cell in cells if self._cell_can_affect_chunk(cell)}
        for key in chunk_keys:
            self._rebuild_chunk(key)

    def _remove_block_node(self, cell: Cell) -> None:
        self._rebuild_chunks_for_cells([cell])
        if self.hovered_cell == cell:
            self.hovered_cell = None
            self.hover_outline.hide()

    def _cell_can_affect_chunk(self, cell: Cell) -> bool:
        return 0 <= cell[0] < self.box_map.size and 0 <= cell[1] < self.box_map.size and 0 <= cell[2] < self.box_map.size

    def _rebuild_chunk(self, key: ChunkKey) -> None:
        old_mesh = self.chunk_meshes.pop(key, None)
        if old_mesh is not None:
            self._remove_chunk_mesh(old_mesh)

        mesh = build_chunk_mesh(self.box_map.boxes, key, self.box_map.size, CHUNK_SIZE)
        if mesh.stats.source_blocks == 0:
            return
        if mesh.opaque:
            mesh.opaque.reparentTo(self.blocks_root)
            mesh.opaque.show(self.hover_shadow_mask)
        if mesh.transparent:
            mesh.transparent.reparentTo(self.blocks_root)
            mesh.transparent.setTransparency(TransparencyAttrib.MAlpha)
            mesh.transparent.setBin("transparent", 0)
            mesh.transparent.setDepthWrite(False)
            mesh.transparent.hide(self.hover_shadow_mask)
        self.chunk_meshes[key] = mesh

    def _remove_chunk_mesh(self, mesh: ChunkMesh) -> None:
        if mesh.opaque:
            mesh.opaque.removeNode()
        if mesh.transparent:
            mesh.transparent.removeNode()

    def _chunk_stats(self) -> dict[str, int]:
        stats = {
            "chunks": len(self.chunk_meshes),
            "source_blocks": 0,
            "visible_faces": 0,
            "merged_quads": 0,
            "opaque_quads": 0,
            "transparent_quads": 0,
        }
        for mesh in self.chunk_meshes.values():
            stats["source_blocks"] += mesh.stats.source_blocks
            stats["visible_faces"] += mesh.stats.visible_faces
            stats["merged_quads"] += mesh.stats.merged_quads
            stats["opaque_quads"] += mesh.stats.opaque_quads
            stats["transparent_quads"] += mesh.stats.transparent_quads
        return stats

    def _merged_quad_count_for_cell(self, cell: Cell) -> int:
        mesh = self.chunk_meshes.get(chunk_key_for_cell(cell))
        return mesh.stats.merged_quads if mesh else 0

    def _vertex_count_for_cell_chunk(self, cell: Cell) -> int:
        mesh = self.chunk_meshes.get(chunk_key_for_cell(cell))
        if mesh is None:
            return 0
        count = 0
        for node in (mesh.opaque, mesh.transparent):
            if node and node.node().getNumGeoms() > 0:
                count += node.node().getGeom(0).getVertexData().getNumRows()
        return count

    def _open_color_editor(self, cell: Cell) -> None:
        color = self.box_map.get_box(cell)
        if color is None:
            return

        self.color_target = cell
        self.ui_open = True
        self.modal_mode = "color"
        self._clear_movement_keys()
        self.set_mouse_capture(False)
        self.crosshair.hide()

        self.color_panel = DirectFrame(
            frameColor=(0.06, 0.07, 0.08, 0.96),
            frameSize=(-0.68, 0.68, -0.43, 0.43),
            pos=(0, 0, 0),
        )
        DirectLabel(
            parent=self.color_panel,
            text=f"RGBA {cell}",
            text_fg=(1, 1, 1, 1),
            text_scale=0.052,
            frameColor=(0, 0, 0, 0),
            pos=(0, 0, 0.32),
        )
        DirectLabel(
            parent=self.color_panel,
            text="R G B A",
            text_fg=(1, 1, 1, 1),
            text_scale=0.04,
            frameColor=(0, 0, 0, 0),
            pos=(-0.44, 0, 0.18),
        )
        color_values = [str(round(channel * 255)) for channel in color]
        self.color_fields = {
            "rgba": " ".join(color_values),
            "r": color_values[0],
            "g": color_values[1],
            "b": color_values[2],
            "a": color_values[3],
        }
        self.color_field_widgets = {}
        self.active_color_field = "rgba"
        self._make_color_field("rgba", (-0.30, 0, 0.15), (-0.015, 0.86, -0.055, 0.07), 0.052)

        labels = (("r", "R"), ("g", "G"), ("b", "B"), ("a", "A"))
        for index, (field, label) in enumerate(labels):
            x = -0.39 + index * 0.26
            DirectLabel(
                parent=self.color_panel,
                text=label,
                text_fg=(1, 1, 1, 1),
                text_scale=0.043,
                frameColor=(0, 0, 0, 0),
                pos=(x, 0, -0.03),
            )
            self._make_color_field(field, (x - 0.07, 0, -0.15), (-0.015, 0.17, -0.045, 0.055), 0.045)

        self._panel_button("OK", (-0.20, 0, -0.34), self._apply_color_edit)
        self._panel_button("Cancel", (0.20, 0, -0.34), self._close_color_editor)
        self._sync_color_field_widgets()
        self._set_status("Editing color")

    def _make_color_field(
        self,
        field: str,
        pos: tuple[float, float, float],
        frame_size: tuple[float, float, float, float],
        text_scale: float,
    ) -> DirectButton:
        button = DirectButton(
            parent=self.color_panel,
            text=self.color_fields[field],
            text_align=0,
            text_fg=(0.04, 0.05, 0.06, 1),
            text_scale=text_scale,
            frameColor=(0.92, 0.93, 0.95, 1),
            frameSize=frame_size,
            relief=1,
            pos=pos,
            command=self._set_active_color_field,
            extraArgs=[field],
        )
        self.color_field_widgets[field] = button
        return button

    def _panel_button(self, text: str, pos: tuple[float, float, float], command: Callable[[], None]) -> DirectButton:
        return DirectButton(
            parent=self.color_panel,
            text=text,
            text_scale=0.042,
            frameSize=(-0.13, 0.13, -0.045, 0.055),
            frameColor=(0.24, 0.29, 0.34, 1),
            text_fg=(1, 1, 1, 1),
            pos=pos,
            command=command,
        )

    def _apply_color_edit(self) -> None:
        if self.color_target is None:
            self._close_color_editor()
            return
        try:
            rgba = self._read_rgba_inputs()
        except ValueError:
            self._set_status("RGBA needs four numbers from 0 to 255")
            return

        if len(rgba) != 4:
            self._set_status("RGBA needs four values")
            return

        edited = self.color_target
        if rgba[3] <= 0.0:
            if self.box_map.remove_box(edited):
                self._refresh_block_and_neighbors(edited)
                self.break_sound.play()
            self._close_color_editor()
            self._set_status(f"Deleted {edited}")
            return

        self.current_color = rgba  # type: ignore[assignment]
        self.box_map.set_box(self.color_target, self.current_color)
        self._refresh_block_and_neighbors(self.color_target)
        self._close_color_editor()
        self._set_status(f"Updated color {edited}")

    def _read_rgba_inputs(self) -> RGBA:
        parts = [part for part in re.split(r"[\s,;]+", self.color_fields.get("rgba", "").strip()) if part]
        if len(parts) != 4 or any(not part for part in parts):
            raise ValueError("RGBA requires four values")
        return tuple(max(0.0, min(1.0, float(part) / 255.0)) for part in parts)  # type: ignore[return-value]

    def _append_color_input(self, text: str) -> None:
        if self.modal_mode != "color" or not self.color_field_widgets:
            return
        current = self.color_fields.get(self.active_color_field, "")
        if len(current) >= 32:
            return
        self.color_fields[self.active_color_field] = current + text
        self._sync_color_fields_from_active()
        self._sync_color_field_widgets()

    def _backspace_color_input(self) -> None:
        if self.modal_mode != "color" or not self.color_field_widgets:
            return
        self.color_fields[self.active_color_field] = self.color_fields.get(self.active_color_field, "")[:-1]
        self._sync_color_fields_from_active()
        self._sync_color_field_widgets()

    def _clear_color_input(self) -> None:
        if self.modal_mode != "color" or not self.color_field_widgets:
            return
        self.color_fields[self.active_color_field] = ""
        self._sync_color_fields_from_active()
        self._sync_color_field_widgets()

    def _submit_color_input(self) -> None:
        if self.modal_mode == "help":
            self._close_help()
        elif self.modal_mode == "quit":
            self._activate_quit_choice()
        elif self.modal_mode == "n":
            self._confirm_n_editor()
        elif self.modal_mode == "n-confirm":
            self._confirm_shrink_n_change()
        elif self.modal_mode == "color":
            self._apply_color_edit()

    def _set_active_color_field(self, field: str) -> None:
        if self.modal_mode != "color":
            return
        self.active_color_field = field
        self._sync_color_field_widgets()

    def _focus_next_color_field(self, direction: int) -> None:
        if self.modal_mode == "quit":
            self._focus_next_quit_choice(direction)
            return
        if self.modal_mode in {"n", "n-confirm"}:
            return
        if self.modal_mode != "color":
            return
        order = ["rgba", "r", "g", "b", "a"]
        index = order.index(self.active_color_field) if self.active_color_field in order else 0
        self.active_color_field = order[(index + direction) % len(order)]
        self._sync_color_field_widgets()

    def _sync_color_fields_from_active(self) -> None:
        if self.active_color_field == "rgba":
            parts = [part for part in re.split(r"[\s,;]+", self.color_fields.get("rgba", "").strip()) if part]
            if len(parts) == 4:
                for field, value in zip(("r", "g", "b", "a"), parts):
                    self.color_fields[field] = value
            return

        self.color_fields["rgba"] = " ".join(self.color_fields.get(field, "") for field in ("r", "g", "b", "a"))

    def _sync_color_field_widgets(self) -> None:
        for field, widget in self.color_field_widgets.items():
            widget["text"] = self.color_fields.get(field, "")
            widget["frameColor"] = (1.0, 0.88, 0.18, 1.0) if field == self.active_color_field else (0.92, 0.93, 0.95, 1)

    def _clear_movement_keys(self) -> None:
        for key in self.key_state:
            self.key_state[key] = False

    def _close_color_editor(self, recapture_mouse: bool = True) -> None:
        if self.color_panel:
            self.color_panel.destroy()
        self.color_panel = None
        self.color_fields = {}
        self.color_field_widgets = {}
        self.active_color_field = "rgba"
        self.color_target = None
        self.ui_open = False
        self.modal_mode = None
        self.crosshair.show()
        self.set_mouse_capture(recapture_mouse)

    def _release_mouse_capture(self) -> None:
        if self.modal_mode == "quit":
            self._close_quit_confirm()
            return
        if self.modal_mode == "help":
            self._close_help()
            return
        if self.modal_mode == "color":
            self._close_color_editor(recapture_mouse=False)
            self._set_status("Mouse released")
            return
        if self.modal_mode == "n-confirm":
            self._cancel_shrink_n_change()
            return
        if self.modal_mode == "n":
            self._close_n_editor()
            self._set_status("Mouse released")
            return
        self.set_mouse_capture(False)
        self._open_quit_confirm()

    def set_mouse_capture(self, captured: bool) -> None:
        self.mouse_captured = captured
        if captured:
            self.ime_disabled = disable_ime_for_window(self.win) or self.ime_disabled
        props = WindowProperties()
        props.setCursorHidden(captured)
        if hasattr(self.win, "requestProperties"):
            self.win.requestProperties(props)
        if captured:
            self.window_maximized = maximize_window(self.win) or self.window_maximized
        if captured:
            self._center_pointer()
            self.crosshair.show()
        else:
            self.crosshair.hide()

    def _center_pointer(self) -> None:
        if self.win and hasattr(self.win, "movePointer"):
            self.win.movePointer(0, self.win.getXSize() // 2, self.win.getYSize() // 2)

    def _toggle_view(self) -> None:
        if self.ui_open:
            return
        self.view_mode = "third" if self.view_mode == "first" else "first"
        self._set_status(f"View: {self.view_mode}")

    def _handle_window_event(self, window) -> None:
        if window is None:
            return
        if hasattr(window, "isClosed") and window.isClosed():
            self._request_quit()
            return
        if window == self.win:
            self._sync_camera_aspect()
            self.ime_disabled = disable_ime_for_window(self.win) or self.ime_disabled

    def userExit(self) -> None:
        self._request_quit()

    def _request_quit(self) -> None:
        if self.modal_mode == "quit":
            return
        if self.modal_mode == "help":
            self._close_help()
        elif self.modal_mode == "color":
            self._close_color_editor(recapture_mouse=False)
        elif self.modal_mode == "n-confirm":
            self._cancel_shrink_n_change()
            self._close_n_editor()
        elif self.modal_mode == "n":
            self._close_n_editor()

        self._open_quit_confirm()

    def _open_quit_confirm(self) -> None:
        self.ui_open = True
        self.modal_mode = "quit"
        self._clear_movement_keys()
        self.quit_restore_mouse_capture = self.mouse_captured
        self.set_mouse_capture(False)
        self.crosshair.hide()
        self.active_quit_choice = "cancel"
        self.quit_button_frames = {}
        self.quit_buttons = {}

        self.quit_panel = DirectFrame(
            frameColor=(0.05, 0.06, 0.07, 0.97),
            frameSize=(-0.86, 0.86, -0.34, 0.34),
            pos=(0, 0, 0),
        )
        DirectLabel(
            parent=self.quit_panel,
            text="Exit Editor",
            text_fg=(1, 1, 1, 1),
            text_scale=0.058,
            frameColor=(0, 0, 0, 0),
            pos=(0, 0, 0.22),
        )
        DirectLabel(
            parent=self.quit_panel,
            text=self._quit_confirm_message(),
            text_fg=(0.92, 0.94, 0.96, 1),
            text_scale=0.036,
            frameColor=(0, 0, 0, 0),
            pos=(0, 0, 0.08),
        )

        self._quit_button("save", "Save and Quit", (-0.52, 0, -0.17), self._save_and_quit)
        self._quit_button("discard", "Quit without Saving", (0, 0, -0.17), self._quit_now)
        self._quit_button("cancel", "Cancel", (0.52, 0, -0.17), self._close_quit_confirm)
        self._sync_quit_button_highlight()
        self._set_status("Exit editor")

    def _quit_confirm_message(self) -> str:
        if self._has_unsaved_changes():
            return "You have unsaved changes. Do you want to quit?"
        return "Do you want to leave the editor?"

    def _quit_button(
        self,
        choice: str,
        text: str,
        pos: tuple[float, float, float],
        command: Callable[[], None],
    ) -> DirectButton:
        frame = DirectFrame(
            parent=self.quit_panel,
            frameColor=(0.18, 0.21, 0.25, 1),
            frameSize=(-0.205, 0.205, -0.075, 0.075),
            pos=pos,
        )
        button = DirectButton(
            parent=frame,
            text=text,
            text_scale=0.034,
            frameSize=(-0.19, 0.19, -0.058, 0.058),
            frameColor=(0.24, 0.29, 0.34, 1),
            text_fg=(1, 1, 1, 1),
            pos=(0, 0, 0),
            command=command,
        )
        self.quit_button_frames[choice] = frame
        self.quit_buttons[choice] = button
        return button

    def _focus_next_quit_choice(self, direction: int) -> None:
        if self.modal_mode != "quit":
            return
        order = ["save", "discard", "cancel"]
        index = order.index(self.active_quit_choice) if self.active_quit_choice in order else 2
        self.active_quit_choice = order[(index + direction) % len(order)]
        self._sync_quit_button_highlight()

    def _sync_quit_button_highlight(self) -> None:
        for choice, frame in self.quit_button_frames.items():
            frame["frameColor"] = (1.0, 0.88, 0.18, 1.0) if choice == self.active_quit_choice else (0.18, 0.21, 0.25, 1)

    def _activate_quit_choice(self) -> None:
        if self.active_quit_choice == "save":
            self._save_and_quit()
        elif self.active_quit_choice == "discard":
            self._quit_now()
        else:
            self._close_quit_confirm()

    def _save_and_quit(self) -> None:
        save_box(self.path, self.box_map)
        self.saved_snapshot = self._current_map_snapshot()
        self._quit_now()

    def _close_quit_confirm(self) -> None:
        if self.quit_panel:
            self.quit_panel.destroy()
        self.quit_panel = None
        self.quit_button_frames = {}
        self.quit_buttons = {}
        self.active_quit_choice = "cancel"
        self.ui_open = False
        self.modal_mode = None
        self.crosshair.show()
        self.set_mouse_capture(self.quit_restore_mouse_capture)
        self._set_status("Ready")

    def _quit_now(self) -> None:
        raise SystemExit

    def _block_intersects_player(self, cell: Cell) -> bool:
        min_corner, max_corner = self._player_aabb(self.player_pos)
        return self._aabb_overlap(
            (min_corner.x, min_corner.y, min_corner.z),
            (max_corner.x, max_corner.y, max_corner.z),
            cell,
            (cell[0] + 1, cell[1] + 1, cell[2] + 1),
        )

    def _aabb_overlap(
        self,
        min_a: tuple[float, float, float],
        max_a: tuple[float, float, float],
        min_b: tuple[float, float, float],
        max_b: tuple[float, float, float],
    ) -> bool:
        return (
            min_a[0] < max_b[0]
            and max_a[0] > min_b[0]
            and min_a[1] < max_b[1]
            and max_a[1] > min_b[1]
            and min_a[2] < max_b[2]
            and max_a[2] > min_b[2]
        )

    def save_current(self, quiet: bool = False) -> None:
        if self.ui_open:
            return
        save_box(self.path, self.box_map)
        self.saved_snapshot = self._current_map_snapshot()
        if not quiet:
            self._set_status(f"Saved {self.path}")
