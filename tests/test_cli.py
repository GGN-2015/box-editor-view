import sys
import subprocess
from pathlib import Path

import pytest

from box_editor_view.__main__ import main
from box_editor_view.box_file import BoxMap, save_box
from box_editor_view.box_hash import hash_box_file


def test_hash_cli_prints_hash_without_opening_editor(tmp_path, capsys, monkeypatch):
    path = tmp_path / "sample.box"
    save_box(path, BoxMap(n=1, boxes={(0, 0, 0): (1, 0, 0, 1)}))
    previous_editor_module = sys.modules.pop("box_editor_view.editor", None)
    previous_panda_modules = {
        name: module for name, module in list(sys.modules.items()) if name == "panda3d" or name.startswith("panda3d.")
    }
    previous_direct_modules = {
        name: module for name, module in list(sys.modules.items()) if name == "direct" or name.startswith("direct.")
    }
    for name in [*previous_panda_modules, *previous_direct_modules]:
        sys.modules.pop(name, None)

    try:
        assert main(["--hash", str(path)]) == 0
        assert "box_editor_view.editor" not in sys.modules
        assert not any(name == "panda3d" or name.startswith("panda3d.") for name in sys.modules)
        assert not any(name == "direct" or name.startswith("direct.") for name in sys.modules)
    finally:
        if previous_editor_module is not None:
            sys.modules["box_editor_view.editor"] = previous_editor_module
        sys.modules.update(previous_panda_modules)
        sys.modules.update(previous_direct_modules)

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


def test_hash_cli_subprocess_does_not_import_panda3d(tmp_path):
    path = tmp_path / "sample.box"
    save_box(path, BoxMap(n=1, boxes={(0, 0, 0): (1, 0, 0, 1)}))
    script = f"""
import importlib.abc
import runpy
import sys

class BlockPanda(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "panda3d" or fullname.startswith("panda3d.") or fullname == "direct" or fullname.startswith("direct."):
            raise AssertionError(f"unexpected Panda3D import: {{fullname}}")
        return None

sys.meta_path.insert(0, BlockPanda())
sys.argv = ["box_editor_view", "--hash", r"{path}"]
try:
    runpy.run_module("box_editor_view", run_name="__main__", alter_sys=True)
except SystemExit as exc:
    raise SystemExit(exc.code)
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, cwd=Path.cwd())

    assert result.returncode == 0
    assert result.stdout == f"{hash_box_file(path)}\n"
    assert result.stderr == ""
