from __future__ import annotations

import hashlib
from pathlib import Path
import struct

from .box_file import BoxMap, load_box, rgba_to_255


BOX_HASH_VERSION = 1


def box_hash(box_map: BoxMap) -> str:
    normalized = BoxMap(n=box_map.n, boxes=box_map.boxes)
    digest = hashlib.sha256()
    digest.update(b"BOX_EDITOR_VIEW_CONTENT_HASH\0")
    digest.update(struct.pack(">BBI", BOX_HASH_VERSION, normalized.n, len(normalized.boxes)))
    for cell, color in sorted(normalized.boxes.items()):
        digest.update(struct.pack(">HHHBBBB", cell[0], cell[1], cell[2], *rgba_to_255(color)))
    return digest.hexdigest()


def hash_box_file(path: str | Path) -> str:
    return box_hash(load_box(path))
