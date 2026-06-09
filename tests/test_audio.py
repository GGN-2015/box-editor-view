from pathlib import Path

from panda3d.core import Filename

from box_editor_view.audio import ensure_sound_files


def test_sound_files_are_mp3_when_ffmpeg_is_available():
    sounds = ensure_sound_files()
    assert sounds["place"].exists()
    assert sounds["break"].exists()
    assert sounds["place"].suffix == ".mp3"
    assert sounds["break"].suffix == ".mp3"


def test_panda3d_sound_paths_are_unix_style():
    path = Path.home() / ".box_editor_view" / "sounds" / "place.mp3"
    panda_path = Filename.fromOsSpecific(str(path)).getFullpath()
    assert "\\" not in panda_path
    assert panda_path.endswith("/place.mp3")
