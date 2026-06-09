from __future__ import annotations

import json
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
    CollisionBox,
    CollisionHandlerQueue,
    CollisionNode,
    CollisionPlane,
    CollisionRay,
    CollisionTraverser,
    DirectionalLight,
    Filename,
    OrthographicLens,
    LineSegs,
    NodePath,
    Plane,
    Point3,
    TransparencyAttrib,
    Vec3,
    WindowProperties,
    loadPrcFileData,
)

from .audio import ensure_sound_files
from .box_file import BoxFormatError, BoxMap, Cell, DEFAULT_COLOR, RGBA, load_box, save_box
from .geometry import FaceNormal, make_bounds, make_checker_ground, make_cube_outline, make_cuboid, make_unit_cube


loadPrcFileData(
    "",
    "\n".join(
        [
            "window-title Box Editor View",
            "sync-video true",
            "show-frame-rate-meter true",
            "textures-power-2 none",
            "framebuffer-multisample true",
            "multisamples 4",
        ]
    ),
)


PICK_MASK = BitMask32.bit(1)
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

        self.world = self.render.attachNewNode("world")
        self.blocks_root = self.world.attachNewNode("blocks")
        self.block_template = make_unit_cube("box-template")
        self.block_nodes: dict[Cell, NodePath] = {}
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
        self.quit_panel: DirectFrame | None = None
        self.color_fields: dict[str, str] = {}
        self.color_field_widgets: dict[str, DirectButton] = {}
        self.active_color_field = "rgba"
        self.color_target: Cell | None = None
        self.quit_button_frames: dict[str, DirectFrame] = {}
        self.quit_buttons: dict[str, DirectButton] = {}
        self.active_quit_choice = "cancel"
        self.quit_restore_mouse_capture = False

        self.key_state = {
            "forward": False,
            "back": False,
            "left": False,
            "right": False,
            "up": False,
            "shift": False,
        }

        self._setup_lights()
        self._setup_collision_picker()
        self._setup_world()
        self._lift_player_out_of_blocks()
        self._setup_player_model()
        self._setup_hud()
        self._setup_audio()
        self._bind_events()

        self.set_mouse_capture(False)
        self.taskMgr.add(self._update, "box-editor-update")
        self._set_status("Click to capture mouse")

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
        return json.dumps(self.box_map.to_json_dict(), sort_keys=True, separators=(",", ":"))

    def _has_unsaved_changes(self) -> bool:
        return self.saved_snapshot != self._current_map_snapshot()

    def _setup_lights(self) -> None:
        ambient = AmbientLight("ambient")
        ambient.setColor((0.30, 0.32, 0.36, 1.0))
        self.render.setLight(self.render.attachNewNode(ambient))

        sun = DirectionalLight("sun")
        sun.setColor((1.0, 0.94, 0.82, 1.0))
        sun.setShadowCaster(True, 4096, 4096)
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

        self.render.setShaderAuto()
        self.render.setAntialias(AntialiasAttrib.MMultisample)
        self.setBackgroundColor(0.60, 0.72, 0.86, 1.0)

    def _shadow_scene_span(self) -> float:
        return max(MIN_SHADOW_SPAN, math.sqrt(3.0) * self.box_map.size + SHADOW_PADDING)

    def _setup_collision_picker(self) -> None:
        self.picker = CollisionTraverser("picker")
        self.pick_queue = CollisionHandlerQueue()
        picker_node = CollisionNode("mouse-ray")
        picker_node.setFromCollideMask(PICK_MASK)
        picker_node.setIntoCollideMask(BitMask32.allOff())
        self.pick_ray = CollisionRay()
        picker_node.addSolid(self.pick_ray)
        picker_path = self.camera.attachNewNode(picker_node)
        self.picker.addCollider(picker_path, self.pick_queue)

    def _setup_world(self) -> None:
        self.ground_node.removeNode() if self.ground_node else None
        self.bounds_node.removeNode() if self.bounds_node else None
        self.blocks_root.removeNode()
        self.blocks_root = self.world.attachNewNode("blocks")
        self.block_nodes.clear()

        size = self.box_map.size
        self.ground_node = make_checker_ground(size)
        self.ground_node.reparentTo(self.world)
        ground_collision = CollisionNode("ground-collision")
        ground_collision.addSolid(CollisionPlane(Plane(Vec3(0, 0, 1), Point3(0, 0, 0))))
        ground_collision.setIntoCollideMask(PICK_MASK)
        ground_collision_path = self.ground_node.attachNewNode(ground_collision)
        ground_collision_path.setPythonTag("hit_type", "ground")

        self.bounds_node = make_bounds(size)
        self.bounds_node.reparentTo(self.world)
        self.bounds_node.hide(self.hover_shadow_mask)
        for cell, color in self.box_map.boxes.items():
            self._add_block_node(cell, color)

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
        self.accept("mouse3", self._right_click)
        self.accept("escape", self._release_mouse_capture)
        self.accept("window-event", self._handle_window_event)
        self.accept("f2", self.save_current)
        self.accept("control-s", self.save_current)
        self.accept("f5", self._toggle_view)
        self.accept("e", self._edit_target_block_color)
        self.accept("h", self._open_help)
        self.accept("c", self._look_at_editor_focus)
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
        if self.mouse_captured and not self.ui_open:
            self._update_mouse_look()
        if not self.ui_open:
            self._update_player(dt)
        self._update_camera()
        self._update_hover_outline()
        self._update_hud()
        return task.cont

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
        self.detail.setText(
            f"{self.path.name}  N={self.box_map.n}  size={self.box_map.size}  "
            f"blocks={len(self.box_map.boxes)}  color=({color})  view={self.view_mode}"
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
            neighbors = self._neighbor_cells(cell)
            self._remove_block_node(cell)
            for neighbor in neighbors:
                if neighbor in self.box_map.boxes:
                    self._refresh_block_node(neighbor)
            self.break_sound.play()
            self._set_status(f"Deleted {cell}")

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
                    "E: edit cube RGBA",
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

        for cell in self.box_map.boxes:
            top = cell[2] + 1.0
            if top > pos.z + tolerance:
                continue
            if self._footprint_overlaps_cell(pos, cell):
                support = top if support is None else max(support, top)
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
        if self.mouseWatcherNode is None:
            mouse_x, mouse_y = 0.0, 0.0
        elif self.mouse_captured or not self.mouseWatcherNode.hasMouse():
            mouse_x, mouse_y = 0.0, 0.0
        else:
            mouse = self.mouseWatcherNode.getMouse()
            mouse_x, mouse_y = mouse.x, mouse.y

        self.pick_ray.setFromLens(self.camNode, mouse_x, mouse_y)
        self.pick_queue.clearEntries()
        self.picker.traverse(self.render)
        if self.pick_queue.getNumEntries() == 0:
            return None
        self.pick_queue.sortEntries()

        for index in range(self.pick_queue.getNumEntries()):
            collision_entry = self.pick_queue.getEntry(index)
            into = collision_entry.getIntoNodePath()
            hit_type = self._find_python_tag(into, "hit_type")
            if not hit_type:
                continue
            cell = self._find_python_tag(into, "cell")
            point = collision_entry.getSurfacePoint(self.render)
            normal = collision_entry.getSurfaceNormal(self.render)
            return str(hit_type), cell, normal, point
        return None

    def _find_python_tag(self, path: NodePath, tag: str):
        current = path
        while not current.isEmpty():
            if current.hasPythonTag(tag):
                return current.getPythonTag(tag)
            current = current.getParent()
        return None

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

    def _add_block_node(self, cell: Cell, color: RGBA) -> None:
        block = self._make_block_visual(cell, color)
        block.setPos(cell[0] + 0.5, cell[1] + 0.5, cell[2] + 0.5)
        self._apply_block_render_state(block, color)
        block.setPythonTag("hit_type", "block")
        block.setPythonTag("cell", cell)

        collision_node = CollisionNode(f"block-collision-{cell[0]}-{cell[1]}-{cell[2]}")
        collision_node.addSolid(CollisionBox(Point3(0, 0, 0), 0.5, 0.5, 0.5))
        collision_node.setIntoCollideMask(PICK_MASK)
        collision_path = block.attachNewNode(collision_node)
        collision_path.setPythonTag("hit_type", "block")
        collision_path.setPythonTag("cell", cell)
        self.block_nodes[cell] = block

    def _make_block_visual(self, cell: Cell, color: RGBA) -> NodePath:
        visible_faces = self._visible_faces_for_block(cell, color)
        if visible_faces == set(FACE_NORMALS):
            return self.block_template.copyTo(self.blocks_root)
        block = make_unit_cube(f"box-{cell[0]}-{cell[1]}-{cell[2]}", visible_faces=visible_faces)
        block.reparentTo(self.blocks_root)
        return block

    def _visible_faces_for_block(self, cell: Cell, color: RGBA) -> set[FaceNormal]:
        visible_faces = set(FACE_NORMALS)

        for normal in FACE_NORMALS:
            neighbor = (cell[0] + normal[0], cell[1] + normal[1], cell[2] + normal[2])
            neighbor_color = self.box_map.get_box(neighbor)
            if neighbor_color is not None and self._neighbor_hides_face(color, neighbor_color):
                visible_faces.discard(normal)
        return visible_faces

    def _neighbor_hides_face(self, color: RGBA, neighbor_color: RGBA) -> bool:
        if color[3] >= 1.0 and neighbor_color[3] >= 1.0:
            return True
        return color[3] < 1.0 and neighbor_color[3] < 1.0 and neighbor_color == color

    def _refresh_block_node(self, cell: Cell) -> None:
        color = self.box_map.get_box(cell)
        if color is None:
            return
        was_hovered = self.hovered_cell == cell
        self._remove_block_node(cell)
        self._add_block_node(cell, color)
        if was_hovered:
            self.hovered_cell = cell

    def _refresh_block_and_neighbors(self, cell: Cell) -> None:
        self._refresh_block_node(cell)
        for neighbor in self._neighbor_cells(cell):
            if neighbor in self.box_map.boxes:
                self._refresh_block_node(neighbor)

    def _neighbor_cells(self, cell: Cell) -> list[Cell]:
        return [(cell[0] + normal[0], cell[1] + normal[1], cell[2] + normal[2]) for normal in FACE_NORMALS]

    def _apply_block_render_state(self, block: NodePath, color: RGBA) -> None:
        block.setColor(*color)
        if color[3] < 1.0:
            block.setTransparency(TransparencyAttrib.MAlpha)
            block.setBin("transparent", 0)
            block.setDepthWrite(False)
            block.hide(self.hover_shadow_mask)
            return

        block.clearTransparency()
        block.clearBin()
        block.clearDepthWrite()
        block.show(self.hover_shadow_mask)

    def _remove_block_node(self, cell: Cell) -> None:
        node = self.block_nodes.pop(cell, None)
        if node:
            node.removeNode()
        if self.hovered_cell == cell:
            self.hovered_cell = None
            self.hover_outline.hide()

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
                neighbors = self._neighbor_cells(edited)
                self._remove_block_node(edited)
                for neighbor in neighbors:
                    if neighbor in self.box_map.boxes:
                        self._refresh_block_node(neighbor)
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
        self.set_mouse_capture(False)
        self._open_quit_confirm()

    def set_mouse_capture(self, captured: bool) -> None:
        self.mouse_captured = captured
        props = WindowProperties()
        props.setCursorHidden(captured)
        if hasattr(self.win, "requestProperties"):
            self.win.requestProperties(props)
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

    def userExit(self) -> None:
        self._request_quit()

    def _request_quit(self) -> None:
        if self.modal_mode == "quit":
            return
        if self.modal_mode == "help":
            self._close_help()
        elif self.modal_mode == "color":
            self._close_color_editor(recapture_mouse=False)

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
