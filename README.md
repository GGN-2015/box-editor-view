# box-editor-view

Box-Editor-View is a Panda3D visual editor for sparse `.box` voxel maps. At its core, it is a box editor: every editable element is a `1x1x1` cube with RGBA color.

This software is part of the future `NekoMouseCraft` project. `NekoMouseCraft` is planned as a Minecraft-like creative-mode game, and Box-Editor-View is the tool for building the reusable cube structures that will live inside it. Each `.box` file can become a small model, prop, landmark, or scene fragment, and those pieces can later be used to construct larger game worlds.

## Showcase

This repository includes `piano.box`, a hand-built voxel piano scene created with the editor.

![Voxel piano front view](https://raw.githubusercontent.com/GGN-2015/box-editor-view/refs/heads/main/docs/images/piano_front.png)

![Voxel piano keyboard close-up](https://raw.githubusercontent.com/GGN-2015/box-editor-view/refs/heads/main/docs/images/piano_keys.png)

![Voxel piano angled view](https://raw.githubusercontent.com/GGN-2015/box-editor-view/refs/heads/main/docs/images/piano_angle.png)

Open the demo scene:

```bash
source venv/bin/activate
python -m box_editor_view piano.box
```

There is also `pikachu.box`, a cute voxel creature model with ears, cheeks, tail, and stubby feet:

```bash
source venv/bin/activate
python -m box_editor_view pikachu.box
```

## File Format

`.box` files are SQLite databases. The editor stores sparse voxels with a compact palette schema:

```sql
CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE palette (
    color_id INTEGER PRIMARY KEY,
    r INTEGER NOT NULL CHECK (r BETWEEN 0 AND 255),
    g INTEGER NOT NULL CHECK (g BETWEEN 0 AND 255),
    b INTEGER NOT NULL CHECK (b BETWEEN 0 AND 255),
    a INTEGER NOT NULL CHECK (a BETWEEN 0 AND 255),
    UNIQUE (r, g, b, a)
) WITHOUT ROWID;

CREATE TABLE boxes (
    x INTEGER NOT NULL,
    y INTEGER NOT NULL,
    z INTEGER NOT NULL,
    color_id INTEGER NOT NULL REFERENCES palette(color_id),
    PRIMARY KEY (x, y, z)
) WITHOUT ROWID;
```

`metadata` contains `schema_version` and `N`. `N` must be from `0` to `5`, and the editable map size is `(2^N)^3`. Empty cells are not written to the `boxes` table. Each cube references a `palette.color_id`; RGBA values are stored once per distinct color, and unused palette colors are removed on save.

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

Print a stable content hash without opening the editor:

```bash
source venv/bin/activate
python -m box_editor_view --hash my_map.box
```

The hash is based on `N` plus each cube coordinate and RGBA value. Palette IDs and unused palette entries do not affect it. Invalid `.box` files print `FormatError` to stderr.

## Render PNG

Render a transparent PNG preview without opening the editor:

```bash
source venv/bin/activate
python -m box_editor_view --render-png pikachu.box
```

By default this writes `pikachu.png`. You can also choose the output path and image size:

```bash
source venv/bin/activate
python -m box_editor_view pikachu.box --render-png docs/images/pikachu_render_png.png --render-size 1024
```

The preview is rendered from the right-front-upper direction, uses a transparent background outside the model, and does not render the checkerboard ground or editor boundary.

![Pikachu rendered with render-png](https://raw.githubusercontent.com/GGN-2015/box-editor-view/refs/heads/main/docs/images/pikachu_render_png.png)

## Developer API

Use the headless Python API when you need to create, inspect, or edit `.box` files from scripts without opening the visual editor:

```python
from box_editor_view import BoxDocument, open_box

doc = BoxDocument.new(n=3, path="example.box")
doc.fill((0, 0, 0), (4, 1, 1), (255, 0, 0, 255))
doc.save()

doc = open_box("example.box")
doc.translate((0, 1, 0))
doc.save()
```

See [`docs/developer-api.md`](docs/developer-api.md) for the full API reference and examples.

## Scripts

The `scripts/` directory contains repository maintenance and demo-generation tools. These scripts are not packaged into the installable Python project.

- `scripts/make_piano_demo.py`: rebuilds `piano.box` and refreshes the showcase screenshots in `docs/images/`.
- `scripts/make_pikachu_demo.py`: rebuilds `pikachu.box`, a compact character model useful for testing colorful organic shapes.
- `scripts/measure_fps.py`: runs an offscreen render benchmark and reports FPS plus chunk mesh statistics.

Run it from the repository root:

```bash
source venv/bin/activate
python scripts/make_piano_demo.py
```

Measure the piano demo performance:

```bash
source venv/bin/activate
python scripts/measure_fps.py piano.box --frames 600 --warmup 120
```

## Performance

The editor batches cubes into chunk meshes, renders only visible faces, greedily merges same-color coplanar faces, and uses a voxel raycast for mouse picking instead of one collision object per cube. It also detects the active Panda3D renderer and enables conservative GPU settings when hardware acceleration is available. Opaque chunk meshes cast shadows; transparent chunk meshes keep real alpha blending and do not cast shadows. Cubes with alpha `0` are rendered as opaque RGB cubes and act as RGB-colored light sources.

## Lighting

The alpha channel has one special lighting rule: a cube with alpha `0` is still a real saved cube, not an empty cell. It is rendered as an opaque cube using its RGB color, and the editor places a small point light at the cube center. The light color is exactly the cube RGB value, so `255 0 0 0` creates a solid red light cube, `0 255 0 0` creates a solid green light cube, and `0 0 0 0` is an opaque black cube with no visible light contribution.

Cubes with alpha from `1` to `254` are ordinary transparent cubes. They use alpha blending, do not cast shadows, and do not emit light. Cubes with alpha `255` are ordinary opaque cubes. Use left click to delete a cube; setting alpha to `0` no longer deletes it.

## Controls

- Click the window: capture the mouse.
- Mouse look: look around after the mouse is captured.
- `WASD`: move horizontally.
- `Space`: move upward.
- `Shift`: move downward.
- Right click: place a cube on the ground or on the clicked cube face.
- Left click: delete the clicked cube.
- Middle click: pick the clicked cube RGBA as the current placement color.
- `E`: edit the RGBA values of the cube under the crosshair.
- Set alpha to `0`: keep the cube opaque and make it emit RGB-colored light.
- `N`: change the map size exponent. Shrinking the map asks for confirmation if cubes would be removed.
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
