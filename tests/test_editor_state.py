import math
from pathlib import Path

import pytest
from panda3d.core import CullBinAttrib, DepthWriteAttrib, PNMImage, Point3, TransparencyAttrib, Vec3, loadPrcFileData

loadPrcFileData("", "window-type offscreen\naudio-library-name null\nnotify-level warning")

from box_editor_view.box_file import BoxMap, save_box
from box_editor_view import editor
from box_editor_view.editor import BoxEditorApp


def make_app(tmp_path, box_map):
    path = tmp_path / "state.box"
    save_box(path, box_map)
    return BoxEditorApp(Path(path), new_file=False, new_n=1)


def test_support_state_tracks_ground_and_blocks(tmp_path):
    app = make_app(tmp_path, BoxMap(n=1, boxes={(0, 0, 0): (1, 0, 0, 1)}))
    try:
        app.player_pos = Vec3(0.5, 0.5, 0.0)
        assert app._support_height_below(app.player_pos, editor.STANDING_TOLERANCE) == 0.0

        app.player_pos = Vec3(0.5, 0.5, 3.0)
        assert app._support_height_below(app.player_pos, editor.STANDING_TOLERANCE) == 1.0

        app.player_pos = Vec3(0.5, 0.5, 1.0)
        assert app._support_height_below(app.player_pos, editor.STANDING_TOLERANCE) == 1.0
    finally:
        app.destroy()


def test_color_editor_can_open_without_standing(tmp_path):
    app = make_app(tmp_path, BoxMap(n=1, boxes={(0, 0, 0): (1, 0, 0, 1)}))
    try:
        app.player_pos = Vec3(0.5, 0.5, 3.0)
        app._open_color_editor((0, 0, 0))
        assert app.ui_open
        assert app.color_target == (0, 0, 0)
    finally:
        app.destroy()


def test_shift_left_click_no_longer_opens_color_editor(tmp_path):
    app = make_app(tmp_path, BoxMap(n=1, boxes={(0, 0, 0): (1, 0, 0, 1)}))
    try:
        app.key_state["shift"] = True
        app.mouse_captured = True
        app._pick = lambda: ("block", (0, 0, 0), Vec3(0, 0, 1), Vec3(0, 0, 0))

        app._delete_clicked_block()

        assert app.ui_open is False
        assert app.box_map.get_box((0, 0, 0)) is None
    finally:
        app.destroy()


def test_player_camera_and_collision_dimensions_are_not_tiny():
    assert 0.9 <= editor.PLAYER_WIDTH <= 1.0
    assert editor.PLAYER_HEIGHT <= 2.0
    assert editor.EYE_HEIGHT >= 1.68
    assert editor.CAMERA_NEAR <= 0.05
    assert editor.CAMERA_FOV >= 80
    assert editor.SOUND_VOLUME == 0.5


def test_player_position_is_limited_to_size_scaled_bounds(tmp_path):
    app = make_app(tmp_path, BoxMap(n=2))
    try:
        padding = max(5, app.box_map.size)
        lower = -padding
        upper = app.box_map.size + padding

        assert app.player_pos.z >= 0
        assert app._clamp_player_position(Vec3(-99, -99, -99)) == Vec3(lower, lower, 0)
        assert app._clamp_player_position(Vec3(99, 99, 99)) == Vec3(upper, upper, upper)
        assert app._clamp_player_position(Vec3(2, 3, 4)) == Vec3(2, 3, 4)
    finally:
        app.destroy()


def test_player_movement_cannot_leave_size_scaled_bounds(tmp_path):
    app = make_app(tmp_path, BoxMap(n=1))
    try:
        padding = max(5, app.box_map.size)
        lower = -padding
        upper = app.box_map.size + padding

        app.player_pos = Vec3(upper - 0.1, lower + 0.1, 0.1)
        app._move_player_with_collision(Vec3(10, -10, 10))

        assert app.player_pos == Vec3(upper, lower, upper)
    finally:
        app.destroy()


def test_player_bounds_use_size_when_size_exceeds_minimum(tmp_path):
    app = make_app(tmp_path, BoxMap(n=5))
    try:
        size = app.box_map.size
        assert app._clamp_player_position(Vec3(-99, -99, -99)) == Vec3(-size, -size, 0)
        assert app._clamp_player_position(Vec3(99, 99, 99)) == Vec3(size * 2, size * 2, size * 2)
    finally:
        app.destroy()


def test_player_spawn_lifts_out_of_blocks(tmp_path):
    boxes = {
        (2, 0, 1): (1, 0, 0, 1),
        (2, 0, 2): (1, 0, 0, 1),
        (2, 0, 3): (1, 0, 0, 1),
    }
    app = make_app(tmp_path, BoxMap(n=2, boxes=boxes))
    try:
        assert app.player_pos.x == pytest.approx(2.0)
        assert app.player_pos.y == pytest.approx(0.5)
        assert app.player_pos.z > 1.0
        assert not app._player_collides(app.player_pos)
        assert app._player_head_and_feet_clear(app.player_pos)
    finally:
        app.destroy()


def test_player_spawn_stays_when_clear(tmp_path):
    app = make_app(tmp_path, BoxMap(n=1))
    try:
        assert app.player_pos == Vec3(1.0, 0.5, 1.0)
    finally:
        app.destroy()


def test_camera_aspect_tracks_window_size(tmp_path):
    app = make_app(tmp_path, BoxMap(n=1))
    original_window = app.win
    try:
        class FakeWindow:
            def __init__(self, width, height):
                self.width = width
                self.height = height

            def getXSize(self):
                return self.width

            def getYSize(self):
                return self.height

            def isClosed(self):
                return False

        fake_window = FakeWindow(1600, 900)
        app.win = fake_window
        app._handle_window_event(fake_window)
        assert app.camLens.getAspectRatio() == pytest.approx(16 / 9)

        fake_window.width = 900
        fake_window.height = 1600
        app._handle_window_event(fake_window)
        assert app.camLens.getAspectRatio() == pytest.approx(9 / 16)
    finally:
        app.win = original_window
        app.destroy()


def test_editor_sound_volume_is_half(tmp_path):
    app = make_app(tmp_path, BoxMap(n=1))
    try:
        class FakeSound:
            volume = None

            def setVolume(self, volume):
                self.volume = volume

        class FakeLoader:
            sound = FakeSound()

            def loadSfx(self, _path):
                return self.sound

        original_loader = app.loader
        app.loader = FakeLoader()
        sound = app._load_sound(tmp_path / "fake.mp3")
        assert sound.volume == 0.5
        app.loader = original_loader
    finally:
        if not hasattr(app.loader, "destroy"):
            app.loader = original_loader
        app.destroy()


def test_rgba_input_accepts_single_line_values(tmp_path):
    app = make_app(tmp_path, BoxMap(n=1, boxes={(0, 0, 0): (1, 0, 0, 1)}))
    try:
        app._open_color_editor((0, 0, 0))
        app._clear_color_input()
        for char in "10, 20, 30, 255":
            app._append_color_input(char)
        assert app._read_rgba_inputs() == (10 / 255, 20 / 255, 30 / 255, 1.0)
    finally:
        app.destroy()


def test_color_editor_clears_and_blocks_movement_keys(tmp_path):
    app = make_app(tmp_path, BoxMap(n=1, boxes={(0, 0, 0): (1, 0, 0, 1)}))
    try:
        app.key_state["forward"] = True
        app._open_color_editor((0, 0, 0))
        assert not any(app.key_state.values())

        app._set_key("forward", True)
        assert app.key_state["forward"] is False

        app._set_key("up", True)
        assert app.key_state["up"] is False
        assert app.color_fields["rgba"].endswith(" ")
    finally:
        app.destroy()


def test_help_modal_blocks_actions_and_closes_with_enter(tmp_path):
    app = make_app(tmp_path, BoxMap(n=1, boxes={(0, 0, 0): (1, 0, 0, 1)}))
    try:
        app.key_state["forward"] = True
        app._open_help()

        assert app.ui_open
        assert app.modal_mode == "help"
        assert not any(app.key_state.values())

        app._set_key("forward", True)
        assert app.key_state["forward"] is False

        app._append_color_input("1")
        assert app.color_fields == {}

        app._submit_color_input()
        assert app.ui_open is False
        assert app.modal_mode is None
    finally:
        app.destroy()


def test_editor_focus_target_uses_ground_center_or_cube_centroid(tmp_path):
    empty_app = make_app(tmp_path, BoxMap(n=2))
    try:
        assert empty_app._editor_focus_target() == Point3(2, 2, 0)
    finally:
        empty_app.destroy()

    app = make_app(
        tmp_path,
        BoxMap(
            n=2,
            boxes={
                (0, 0, 0): (1, 0, 0, 1),
                (2, 2, 2): (0, 1, 0, 1),
            },
        ),
    )
    try:
        assert app._editor_focus_target() == Point3(1.5, 1.5, 1.5)
    finally:
        app.destroy()


def test_look_at_editor_focus_points_camera_at_target(tmp_path):
    app = make_app(tmp_path, BoxMap(n=2, boxes={(2, 1, 1): (1, 0, 0, 1)}))
    try:
        app.player_pos = Vec3(0, 0, 0)
        target = app._editor_focus_target()
        eye = app.player_pos + Vec3(0, 0, editor.EYE_HEIGHT)

        app._look_at_editor_focus()

        heading = math.radians(app.heading)
        pitch = math.radians(app.pitch)
        forward = Vec3(
            -math.sin(heading) * math.cos(pitch),
            math.cos(heading) * math.cos(pitch),
            math.sin(pitch),
        )
        expected = Vec3(target.x - eye.x, target.y - eye.y, target.z - eye.z)
        expected.normalize()
        assert forward.dot(expected) > 0.999
    finally:
        app.destroy()


def test_voxel_raycast_hits_block_face_for_placement(tmp_path):
    app = make_app(tmp_path, BoxMap(n=1, boxes={(0, 0, 0): (1, 0, 0, 1)}))
    try:
        hit = app._raycast_blocks(Point3(0.5, 2.5, 0.5), Vec3(0, -1, 0))

        assert hit is not None
        _distance, cell, normal, point = hit
        assert cell == (0, 0, 0)
        assert normal == Vec3(0, 1, 0)
        assert point.y == pytest.approx(1.0)
        assert app._placement_cell("block", cell, normal, point) == (0, 1, 0)
    finally:
        app.destroy()


def test_voxel_raycast_hits_ground_for_placement(tmp_path):
    app = make_app(tmp_path, BoxMap(n=1))
    try:
        hit = app._raycast_ground(Point3(1.5, 0.5, 3.0), Vec3(0, 0, -1))

        assert hit is not None
        _distance, point = hit
        assert point == Point3(1.5, 0.5, 0.0)
        assert app._placement_cell("ground", None, Vec3(0, 0, 1), point) == (1, 0, 0)
    finally:
        app.destroy()


def test_color_editor_focuses_rgba_by_default_and_tabs_between_fields(tmp_path):
    app = make_app(tmp_path, BoxMap(n=1, boxes={(0, 0, 0): (1, 0, 0, 1)}))
    try:
        app._open_color_editor((0, 0, 0))
        assert app.active_color_field == "rgba"
        assert app.color_field_widgets["rgba"]["frameColor"] == (1.0, 0.88, 0.18, 1.0)

        app._focus_next_color_field(1)
        assert app.active_color_field == "r"
        assert app.color_field_widgets["r"]["frameColor"] == (1.0, 0.88, 0.18, 1.0)

        app._focus_next_color_field(-1)
        assert app.active_color_field == "rgba"
    finally:
        app.destroy()


def test_arrow_keys_use_modal_focus_navigation(tmp_path):
    app = make_app(tmp_path, BoxMap(n=1, boxes={(0, 0, 0): (1, 0, 0, 1)}))
    try:
        app._open_color_editor((0, 0, 0))

        app.messenger.send("arrow_right")
        assert app.active_color_field == "r"

        app.messenger.send("arrow_left")
        assert app.active_color_field == "rgba"

        app._close_color_editor()
        app.box_map.set_box((1, 1, 1), (1, 0, 0, 1))
        app._request_quit()

        app.messenger.send("arrow_right")
        assert app.active_quit_choice == "save"

        app.messenger.send("arrow_left")
        assert app.active_quit_choice == "cancel"
    finally:
        app.destroy()


def test_color_editor_component_field_input_syncs_rgba(tmp_path):
    app = make_app(tmp_path, BoxMap(n=1, boxes={(0, 0, 0): (1, 0, 0, 1)}))
    try:
        app._open_color_editor((0, 0, 0))
        app._set_active_color_field("g")
        app._clear_color_input()
        app._append_color_input("1")
        app._append_color_input("2")

        assert app.color_fields["g"] == "12"
        assert app.color_fields["rgba"].split()[1] == "12"
        assert app._read_rgba_inputs()[1] == 12 / 255
    finally:
        app.destroy()


def test_editor_lines_are_hidden_from_shadow_camera(tmp_path):
    app = make_app(tmp_path, BoxMap(n=1, boxes={(0, 0, 0): (1, 0, 0, 1)}))
    try:
        assert app.bounds_node is not None
        assert app.hover_outline.isHidden(app.hover_shadow_mask)
        assert app.bounds_node.isHidden(app.hover_shadow_mask)
    finally:
        app.destroy()


def test_shadow_camera_covers_large_maps(tmp_path):
    app = make_app(tmp_path, BoxMap(n=5, boxes={(31, 31, 31): (1, 0, 0, 1)}))
    try:
        expected_span = math.sqrt(3.0) * app.box_map.size + editor.SHADOW_PADDING
        assert app.sun_lens.getFilmSize().x == pytest.approx(expected_span)
        assert app.sun_lens.getFilmSize().y == pytest.approx(expected_span)
        assert app.sun_lens.getNear() == pytest.approx(-expected_span)
        assert app.sun_lens.getFar() == pytest.approx(expected_span)
        assert app.sun_path.getPos() == Vec3(16, 16, 16)
    finally:
        app.destroy()


def test_transparent_blocks_use_alpha_rendering_and_no_shadow(tmp_path):
    app = make_app(tmp_path, BoxMap(n=1, boxes={(0, 0, 0): (1, 0, 0, 0.5)}))
    try:
        mesh = next(iter(app.chunk_meshes.values()))
        node = mesh.transparent
        assert node is not None
        state = node.getState()

        assert node.getTransparency() == TransparencyAttrib.MAlpha
        assert state.getAttrib(CullBinAttrib).getBinName() == "transparent"
        assert state.getAttrib(DepthWriteAttrib).getMode() == DepthWriteAttrib.MOff
        assert node.isHidden(app.hover_shadow_mask)
        assert not node.isHidden(app.camNode.getCameraMask())

        app.box_map.set_box((0, 0, 0), (1, 1, 1, 1))
        app._refresh_block_and_neighbors((0, 0, 0))
        mesh = next(iter(app.chunk_meshes.values()))
        assert mesh.transparent is None
        assert mesh.opaque is not None
        assert mesh.opaque.getTransparency() == TransparencyAttrib.MNone
        assert mesh.opaque.getState().getAttrib(CullBinAttrib) is None
        assert mesh.opaque.getState().getAttrib(DepthWriteAttrib) is None
        assert not mesh.opaque.isHidden(app.hover_shadow_mask)
    finally:
        app.destroy()


def test_block_alpha_changes_rendered_opacity(tmp_path):
    app = make_app(tmp_path, BoxMap(n=1, boxes={(0, 0, 0): (1, 0, 0, 0.25)}))
    try:
        app.player_pos = Vec3(0.5, -3, -1.2)
        app.heading = 0
        app.pitch = 0

        def center_red_for_alpha(alpha):
            app.box_map.set_box((0, 0, 0), (1, 0, 0, alpha))
            app._refresh_block_and_neighbors((0, 0, 0))
            app._update_camera()
            app.graphicsEngine.renderFrame()
            app.graphicsEngine.renderFrame()
            image = PNMImage()
            app.win.getScreenshot(image)
            return image.getXelA(image.getXSize() // 2, image.getYSize() // 2).x

        red_25 = center_red_for_alpha(0.25)
        red_50 = center_red_for_alpha(0.5)
        red_75 = center_red_for_alpha(0.75)
        red_100 = center_red_for_alpha(1.0)

        assert red_25 < red_50 < red_75 < red_100
    finally:
        app.destroy()


def test_identical_adjacent_transparent_blocks_omit_shared_faces(tmp_path):
    color = (1, 0, 0, 0.5)
    app = make_app(tmp_path, BoxMap(n=1, boxes={(0, 0, 0): color, (1, 0, 0): color}))
    try:
        stats = app._chunk_stats()

        assert stats["visible_faces"] == 10
        assert stats["merged_quads"] == 6
        assert stats["transparent_quads"] == 6
    finally:
        app.destroy()


def test_different_adjacent_transparent_blocks_keep_shared_faces(tmp_path):
    app = make_app(
        tmp_path,
        BoxMap(
            n=1,
            boxes={
                (0, 0, 0): (1, 0, 0, 0.5),
                (1, 0, 0): (1, 0, 0, 0.75),
            },
        ),
    )
    try:
        stats = app._chunk_stats()

        assert stats["visible_faces"] == 12
        assert stats["merged_quads"] == 12
        assert stats["transparent_quads"] == 12
    finally:
        app.destroy()


def test_opaque_adjacent_blocks_omit_shared_faces(tmp_path):
    app = make_app(
        tmp_path,
        BoxMap(
            n=1,
            boxes={
                (0, 0, 0): (1, 0, 0, 1),
                (1, 0, 0): (0, 1, 0, 1),
            },
        ),
    )
    try:
        stats = app._chunk_stats()

        assert stats["visible_faces"] == 10
        assert stats["merged_quads"] == 10
        assert stats["opaque_quads"] == 10
    finally:
        app.destroy()


def test_greedy_mesh_merges_same_color_opaque_faces(tmp_path):
    color = (1, 0, 0, 1)
    app = make_app(tmp_path, BoxMap(n=1, boxes={(0, 0, 0): color, (1, 0, 0): color}))
    try:
        stats = app._chunk_stats()

        assert stats["visible_faces"] == 10
        assert stats["merged_quads"] == 6
        assert stats["opaque_quads"] == 6
    finally:
        app.destroy()


def test_opaque_shared_faces_refresh_when_neighbor_is_deleted(tmp_path):
    app = make_app(
        tmp_path,
        BoxMap(
            n=1,
            boxes={
                (0, 0, 0): (1, 0, 0, 1),
                (1, 0, 0): (0, 1, 0, 1),
            },
        ),
    )
    try:
        assert app._chunk_stats()["visible_faces"] == 10

        app.box_map.remove_box((1, 0, 0))
        app._refresh_block_and_neighbors((1, 0, 0))

        assert app._chunk_stats()["visible_faces"] == 6
        assert app._chunk_stats()["merged_quads"] == 6
    finally:
        app.destroy()


def test_transparent_shared_faces_refresh_when_color_changes(tmp_path):
    color = (1, 0, 0, 0.5)
    app = make_app(tmp_path, BoxMap(n=1, boxes={(0, 0, 0): color, (1, 0, 0): color}))
    try:
        assert app._chunk_stats()["visible_faces"] == 10

        app.box_map.set_box((1, 0, 0), (0, 1, 0, 0.5))
        app._refresh_block_and_neighbors((1, 0, 0))

        assert app._chunk_stats()["visible_faces"] == 12
        assert app._chunk_stats()["merged_quads"] == 12
    finally:
        app.destroy()


def test_unsaved_changes_snapshot_updates_only_on_save(tmp_path):
    app = make_app(tmp_path, BoxMap(n=1))
    try:
        assert app._has_unsaved_changes() is False

        app.box_map.set_box((0, 0, 0), (1, 0, 0, 1))
        assert app._has_unsaved_changes() is True

        app.save_current()
        assert app._has_unsaved_changes() is False
    finally:
        app.destroy()


def test_quit_confirm_defaults_to_cancel_and_tabs_between_buttons(tmp_path):
    app = make_app(tmp_path, BoxMap(n=1))
    try:
        app.box_map.set_box((0, 0, 0), (1, 0, 0, 1))
        app._request_quit()

        assert app.ui_open
        assert app.modal_mode == "quit"
        assert app.active_quit_choice == "cancel"
        assert app.quit_button_frames["cancel"]["frameColor"] == (1.0, 0.88, 0.18, 1.0)

        app._focus_next_quit_choice(1)
        assert app.active_quit_choice == "save"

        app._focus_next_quit_choice(-1)
        assert app.active_quit_choice == "cancel"

        app._submit_color_input()
        assert app.ui_open is False
        assert app.modal_mode is None
    finally:
        app.destroy()


def test_escape_opens_exit_choices_even_without_unsaved_changes(tmp_path):
    app = make_app(tmp_path, BoxMap(n=1))
    try:
        assert app._has_unsaved_changes() is False
        app.mouse_captured = True

        app._release_mouse_capture()

        assert app.mouse_captured is False
        assert app.ui_open
        assert app.modal_mode == "quit"
        assert app.active_quit_choice == "cancel"
    finally:
        app.destroy()


def test_request_quit_opens_exit_choices_even_without_unsaved_changes(tmp_path):
    app = make_app(tmp_path, BoxMap(n=1))
    try:
        assert app._has_unsaved_changes() is False

        app._request_quit()

        assert app.ui_open
        assert app.modal_mode == "quit"
    finally:
        app.destroy()


def test_quit_confirm_enter_activates_highlighted_save_and_quit(tmp_path):
    app = make_app(tmp_path, BoxMap(n=1))
    try:
        app.box_map.set_box((0, 0, 0), (1, 0, 0, 1))
        app._open_quit_confirm()
        app.active_quit_choice = "save"
        app._sync_quit_button_highlight()

        try:
            app._submit_color_input()
        except SystemExit:
            pass
        else:
            raise AssertionError("Save and Quit should exit")

        assert app._has_unsaved_changes() is False
    finally:
        app.destroy()


def test_close_request_event_opens_unsaved_quit_confirm(tmp_path):
    app = make_app(tmp_path, BoxMap(n=1))
    original_window = app.win
    try:
        class FakeWindow:
            close_request_event = None

            def setCloseRequestEvent(self, event):
                self.close_request_event = event

        fake_window = FakeWindow()
        app.win = fake_window
        app._setup_close_request_event()
        assert fake_window.close_request_event == editor.CLOSE_REQUEST_EVENT

        app.box_map.set_box((0, 0, 0), (1, 0, 0, 1))
        app.messenger.send(editor.CLOSE_REQUEST_EVENT)

        assert app.ui_open
        assert app.modal_mode == "quit"
        assert app.active_quit_choice == "cancel"
    finally:
        app.win = original_window
        app.destroy()
