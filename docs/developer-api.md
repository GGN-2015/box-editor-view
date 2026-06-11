# Developer API

Box-Editor-View exposes a headless Python API for creating, reading, editing, and saving `.box` files without opening the Panda3D visual editor.

The API lives in `box_editor_view.api` and is also re-exported from `box_editor_view` for common use:

```python
from box_editor_view import BoxDocument, open_box, create_box
```

Importing the API does not import `box_editor_view.editor` or Panda3D. It only uses the SQLite-backed `.box` file layer.

## Concepts

`.box` maps are sparse voxel maps:

- `N` controls the map size. The valid range is `0..5`.
- The grid size is `2 ** N` on each axis.
- A cell is an `(x, y, z)` tuple of integers.
- A color is an RGBA tuple. Channels can be `0..1` floats or `0..255` numbers.
- Empty cells are omitted from the file.
- Alpha `0` is still a real saved cube. In the visual editor it renders as an opaque RGB light cube.

Invalid coordinates, invalid colors, bad files, and unsupported schema versions raise `BoxFormatError`.

## Object API

Use `BoxDocument` when you want a small editable document object that remembers its path:

```python
from box_editor_view import BoxDocument

doc = BoxDocument.new(n=3, path="example.box")
doc.set((0, 0, 0), (255, 0, 0, 255))
doc.set((1, 0, 0), (0, 128, 255, 128))
doc.save()
```

Open and edit an existing file:

```python
from box_editor_view import open_box

doc = open_box("example.box")
color = doc.get((0, 0, 0))

doc.fill((2, 2, 0), (5, 5, 1), (255, 255, 255, 255))
doc.erase((3, 3, 0), (4, 4, 1))
doc.remove((1, 0, 0))

doc.save()
```

`fill(start, stop, color)` and `erase(start, stop)` use Python slice-style ranges. `start` is inclusive and `stop` is exclusive.

## Function API

Use the function API when you already have a `BoxMap` and want direct operations:

```python
from box_editor_view import load_box, save_box
from box_editor_view.api import fill_region, resize_map, set_voxel

box_map = load_box("example.box")
set_voxel(box_map, (0, 0, 0), (255, 0, 0, 255))
fill_region(box_map, (1, 1, 0), (4, 4, 1), (0, 255, 0, 255))
resize_map(box_map, 4)
save_box("example.box", box_map)
```

Available function helpers:

- `new_box(n=3, boxes=None) -> BoxMap`
- `open_box(path) -> BoxDocument`
- `create_box(path, n=3, overwrite=False) -> BoxDocument`
- `iter_boxes(box_map) -> Iterator[((x, y, z), rgba)]`
- `get_voxel(box_map, cell) -> rgba | None`
- `set_voxel(box_map, cell, color) -> None`
- `remove_voxel(box_map, cell) -> bool`
- `fill_region(box_map, start, stop, color) -> int`
- `erase_region(box_map, start, stop) -> int`
- `resize_map(box_map, n, discard_out_of_bounds=False) -> int`
- `translate_map(box_map, offset, discard_out_of_bounds=False) -> int`
- `bounding_box(box_map) -> ((min_x, min_y, min_z), (stop_x, stop_y, stop_z)) | None`

## Resizing

Growing a map only changes `N`:

```python
doc = open_box("example.box")
doc.resize(5)
doc.save()
```

Shrinking a map can remove cubes outside the new size. By default this is rejected:

```python
from box_editor_view import BoxFormatError

try:
    doc.resize(2)
except BoxFormatError as exc:
    print(exc)
```

Pass `discard_out_of_bounds=True` to allow the shrink:

```python
removed = doc.resize(2, discard_out_of_bounds=True)
print(f"removed {removed} cubes")
doc.save()
```

## Translating

Move all cubes by an `(x, y, z)` offset:

```python
doc = open_box("example.box")
doc.translate((1, 0, 0))
doc.save()
```

If the move would push cubes outside the map, it raises `BoxFormatError` unless `discard_out_of_bounds=True` is passed.

## Iterating And Inspecting

```python
doc = open_box("example.box")

print(doc.n)
print(doc.size)
print(doc.count)
print(doc.bounding_box())
print(doc.content_hash)

for cell, rgba in doc.iter_boxes():
    print(cell, rgba)
```

The hash matches the command-line `--hash` output. It is based on `N`, cube coordinates, and RGBA values, not palette row IDs.

## Low-Level API

The existing low-level functions are still available:

```python
from box_editor_view import BoxMap, load_box, save_box

box_map = BoxMap(n=1)
box_map.set_box((0, 0, 0), (255, 255, 255, 255))
save_box("single.box", box_map)

loaded = load_box("single.box")
```

Use the high-level API for scripts that need stricter coordinate validation, bulk region helpers, resizing, translation, and path-aware saving.
