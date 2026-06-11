import sys

import pytest

from box_editor_view import BoxDocument, BoxFormatError, create_box, open_box
from box_editor_view.api import bounding_box, new_box, resize_map, set_voxel, translate_map
from box_editor_view.box_file import load_box


def test_box_document_script_flow_round_trips_without_gui(tmp_path):
    path = tmp_path / "scripted.box"

    document = BoxDocument.new(n=2, path=path)
    assert document.size == 4
    assert document.count == 0

    assert document.fill((0, 0, 0), (2, 2, 1), (255, 0, 0, 255)) == 4
    document.set((3, 3, 3), (0, 128, 255, 64))
    assert document.bounding_box() == ((0, 0, 0), (4, 4, 4))
    assert document.save() == path

    reopened = open_box(path)
    assert reopened.n == 2
    assert reopened.count == 5
    assert reopened.get((3, 3, 3)) == pytest.approx((0, 128 / 255, 1, 64 / 255))
    assert len(reopened.content_hash) == 64

    assert reopened.erase((0, 0, 0), (2, 2, 1)) == 4
    assert reopened.remove((3, 3, 3)) is True
    assert reopened.remove((3, 3, 3)) is False
    reopened.save()
    assert load_box(path).boxes == {}


def test_create_box_refuses_existing_file_without_overwrite(tmp_path):
    path = tmp_path / "existing.box"
    create_box(path, n=1)

    with pytest.raises(FileExistsError):
        create_box(path, n=2)

    create_box(path, n=2, overwrite=True)
    assert load_box(path).n == 2


def test_function_api_resizes_and_reports_discarded_cells():
    box_map = new_box(n=2)
    set_voxel(box_map, (0, 0, 0), (1, 0, 0, 1))
    set_voxel(box_map, (3, 3, 3), (0, 1, 0, 1))

    with pytest.raises(BoxFormatError, match="would discard 1 cube"):
        resize_map(box_map, 1)

    assert resize_map(box_map, 1, discard_out_of_bounds=True) == 1
    assert box_map.n == 1
    assert box_map.boxes == {(0, 0, 0): (1.0, 0.0, 0.0, 1.0)}


def test_translate_can_discard_or_reject_out_of_bounds_cells():
    box_map = new_box(n=1, boxes={(0, 0, 0): (1, 0, 0, 1), (1, 1, 1): (0, 1, 0, 1)})

    with pytest.raises(BoxFormatError, match="translation"):
        translate_map(box_map, (1, 0, 0))

    assert translate_map(box_map, (1, 0, 0), discard_out_of_bounds=True) == 1
    assert box_map.boxes == {(1, 0, 0): (1.0, 0.0, 0.0, 1.0)}


def test_document_boxes_and_to_box_map_are_copies():
    document = BoxDocument.new(n=1, boxes={(0, 0, 0): (1, 0, 0, 1)})

    external_boxes = document.boxes
    external_boxes.clear()
    assert document.count == 1

    copied_map = document.to_box_map()
    copied_map.clear()
    assert document.count == 1


def test_bounding_box_empty_map_returns_none():
    assert bounding_box(new_box(n=1)) is None


def test_api_import_does_not_import_editor_or_panda_modules(monkeypatch):
    for name in list(sys.modules):
        if name == "box_editor_view.editor" or name == "panda3d" or name.startswith("panda3d."):
            monkeypatch.delitem(sys.modules, name, raising=False)

    __import__("box_editor_view.api")

    assert "box_editor_view.editor" not in sys.modules
    assert not any(name == "panda3d" or name.startswith("panda3d.") for name in sys.modules)
