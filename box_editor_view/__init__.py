"""Panda3D editor and headless APIs for sparse .box voxel maps."""

from .api import (
    BoxDocument,
    bounding_box,
    create_box,
    erase_region,
    fill_region,
    get_voxel,
    iter_boxes,
    new_box,
    open_box,
    remove_voxel,
    resize_map,
    set_voxel,
    translate_map,
)
from .box_file import BoxFormatError, BoxMap, Cell, RGBA, load_box, save_box
from .box_hash import box_hash, hash_box_file

__author__ = "GGN_2015"
__version__ = "0.1.0"

__all__ = [
    "BoxDocument",
    "BoxFormatError",
    "BoxMap",
    "Cell",
    "RGBA",
    "bounding_box",
    "box_hash",
    "create_box",
    "erase_region",
    "fill_region",
    "get_voxel",
    "hash_box_file",
    "iter_boxes",
    "load_box",
    "new_box",
    "open_box",
    "remove_voxel",
    "resize_map",
    "save_box",
    "set_voxel",
    "translate_map",
]
