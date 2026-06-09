# box-editor-view

Author: GGN_2015

A Panda3D visual editor for sparse `.box` voxel maps. A `.box` file is JSON text:

```json
{
  "N": 3,
  "boxes": {
    "1,2,0": [140, 140, 140, 255]
  }
}
```

`N` must be from `1` to `5`, and the editable map size is `(2^N)^3`. Empty cells are not written to the file.

## Setup

Use the project `venv`:

```bash
source venv/bin/activate
python -m pip install -r requirements.txt
```

Run tests:

```bash
source venv/bin/activate
python -m pytest
```

## Run

Create or open a file:

```bash
source venv/bin/activate
python -m box_editor_view my_map.box
```

Create a new empty file with a chosen `N`:

```bash
source venv/bin/activate
python -m box_editor_view my_map.box --new -n 5
```

If no path is given, the editor uses `untitled.box` in the current directory.

## Controls

- Click the window: capture the mouse.
- Mouse look: look around after the mouse is captured.
- `WASD`: move horizontally.
- `Space`: move upward.
- `Shift`: move downward.
- Right click: place a cube on the ground or on the clicked cube face.
- Left click: delete the clicked cube.
- `E`: edit the RGBA values of the cube under the crosshair.
- Set alpha to `0`: delete that cube instead of saving it.
- `C`: look at the editor center, or the centroid of all cubes when cubes exist.
- `F5`: switch first-person and third-person view.
- `F2` or `Ctrl+S`: save.
- `H`: show the help page.
- `Esc`: release the mouse and show exit choices.

The hovered cube is outlined. The player has an approximately `1x1x1.8` body, with the camera near eye height. RGBA values are entered as `0..255`; the color editor accepts either `R G B A` or `R,G,B,A`. The default placement color is gray with alpha `255`. After editing a cube color, newly placed cubes use that last edited RGBA color.

While the color editor is open, movement keys are disabled and keyboard input is reserved for color fields. The combined `RGBA` field is focused by default; click `R`, `G`, `B`, or `A` to edit one channel, or use `Tab`, `Shift+Tab`, or the left/right arrow keys to switch fields. The active field is highlighted yellow.

Block placement and deletion sounds are generated automatically as MP3 files under `%USERPROFILE%\.box_editor_view\sounds`.

The help page disables editing and movement until you click OK or press Enter.

When you leave the editor, it asks whether to Save and Quit, Quit without Saving, or Cancel. Use `Tab`, `Shift+Tab`, or the left/right arrow keys to switch the highlighted button.
