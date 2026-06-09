import json

import pytest

from box_editor_view.box_file import BoxFormatError, BoxMap, load_box, save_box


def test_sparse_round_trip_omits_empty_cells(tmp_path):
    box_map = BoxMap(n=2)
    assert box_map.set_box((1, 2, 3), (0.1, 0.2, 0.3, 0.4))
    assert not box_map.set_box((4, 0, 0), (1, 1, 1, 1))

    path = tmp_path / "sample.box"
    save_box(path, box_map)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"N": 2, "boxes": {"1,2,3": [26, 51, 76, 102]}}
    assert load_box(path).boxes[(1, 2, 3)] == pytest.approx((26 / 255, 51 / 255, 76 / 255, 102 / 255))


def test_n_must_be_between_zero_and_five():
    assert BoxMap(n=0).size == 1
    with pytest.raises(BoxFormatError):
        BoxMap(n=-1)
    assert BoxMap(n=5).size == 32
    with pytest.raises(BoxFormatError):
        BoxMap(n=6)


def test_loader_accepts_255_rgba_and_list_entries():
    box_map = BoxMap.from_json_dict(
        {
            "N": 1,
            "boxes": [
                {"pos": [0, 0, 0], "rgba": [128, 64, 32, 255]},
                {"x": 1, "y": 1, "z": 1, "color": [0.25, 0.5, 0.75, 1]},
            ],
        }
    )

    assert box_map.boxes[(0, 0, 0)] == pytest.approx((128 / 255, 64 / 255, 32 / 255, 1))
    assert box_map.boxes[(1, 1, 1)] == (0.25, 0.5, 0.75, 1.0)


def test_loader_rejects_out_of_bounds_boxes():
    with pytest.raises(BoxFormatError):
        BoxMap.from_json_dict({"N": 1, "boxes": {"2,0,0": [1, 1, 1, 1]}})


def test_alpha_zero_removes_and_is_not_saved(tmp_path):
    box_map = BoxMap(n=1, boxes={(0, 0, 0): (1, 0, 0, 0), (1, 1, 1): (0, 1, 0, 1)})
    assert box_map.boxes == {(1, 1, 1): (0.0, 1.0, 0.0, 1.0)}

    assert box_map.set_box((1, 1, 1), (0, 1, 0, 0))
    assert box_map.boxes == {}

    path = tmp_path / "alpha.box"
    save_box(path, box_map)
    assert json.loads(path.read_text(encoding="utf-8")) == {"N": 1, "boxes": {}}


def test_default_color_uses_255_alpha():
    box_map = BoxMap(n=1)
    assert box_map.set_box((0, 0, 0), (140, 140, 140, 255))
    assert box_map.to_json_dict()["boxes"] == {"0,0,0": [140, 140, 140, 255]}
