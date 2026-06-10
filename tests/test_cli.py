import sys

import pytest

from box_editor_view.__main__ import main
from box_editor_view.box_file import BoxMap, hash_box_file, save_box


def test_hash_cli_prints_hash_without_opening_editor(tmp_path, capsys, monkeypatch):
    path = tmp_path / "sample.box"
    save_box(path, BoxMap(n=1, boxes={(0, 0, 0): (1, 0, 0, 1)}))
    previous_editor_module = sys.modules.pop("box_editor_view.editor", None)

    try:
        assert main(["--hash", str(path)]) == 0
        assert "box_editor_view.editor" not in sys.modules
    finally:
        if previous_editor_module is not None:
            sys.modules["box_editor_view.editor"] = previous_editor_module

    captured = capsys.readouterr()
    assert captured.out == f"{hash_box_file(path)}\n"
    assert captured.err == ""


def test_hash_cli_reports_format_error(tmp_path, capsys):
    path = tmp_path / "bad.box"
    path.write_text("not sqlite", encoding="utf-8")

    assert main(["--hash", str(path)]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("FormatError:")


def test_hash_cli_requires_path(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--hash"])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "--hash requires a .box file path" in captured.err
