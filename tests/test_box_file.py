import sqlite3

import pytest

from box_editor_view.box_file import BOX_SCHEMA_VERSION, BoxFormatError, BoxMap, load_box, save_box
from box_editor_view.box_hash import box_hash, hash_box_file


def test_sparse_round_trip_uses_sqlite_and_omits_empty_cells(tmp_path):
    box_map = BoxMap(n=2)
    assert box_map.set_box((1, 2, 3), (0.1, 0.2, 0.3, 0.4))
    assert box_map.set_box((2, 2, 3), (0.1, 0.2, 0.3, 0.4))
    assert not box_map.set_box((4, 0, 0), (1, 1, 1, 1))

    path = tmp_path / "sample.box"
    save_box(path, box_map)

    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT value FROM metadata WHERE key = 'schema_version'").fetchone()[0] == str(
            BOX_SCHEMA_VERSION
        )
        assert connection.execute("SELECT value FROM metadata WHERE key = 'N'").fetchone()[0] == "2"
        assert connection.execute("SELECT color_id, r, g, b, a FROM palette").fetchall() == [(1, 26, 51, 76, 102)]
        assert connection.execute("SELECT x, y, z, color_id FROM boxes ORDER BY x, y, z").fetchall() == [
            (1, 2, 3, 1),
            (2, 2, 3, 1),
        ]
    assert load_box(path).boxes[(1, 2, 3)] == pytest.approx((26 / 255, 51 / 255, 76 / 255, 102 / 255))
    assert load_box(path).boxes[(2, 2, 3)] == pytest.approx((26 / 255, 51 / 255, 76 / 255, 102 / 255))


def test_n_must_be_between_zero_and_five():
    assert BoxMap(n=0).size == 1
    with pytest.raises(BoxFormatError):
        BoxMap(n=-1)
    assert BoxMap(n=5).size == 32
    with pytest.raises(BoxFormatError):
        BoxMap(n=6)


def test_loader_rejects_legacy_sqlite_rows_without_palette(tmp_path):
    path = tmp_path / "rows.box"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
            CREATE TABLE boxes (
                x INTEGER NOT NULL,
                y INTEGER NOT NULL,
                z INTEGER NOT NULL,
                r INTEGER NOT NULL CHECK (r BETWEEN 0 AND 255),
                g INTEGER NOT NULL CHECK (g BETWEEN 0 AND 255),
                b INTEGER NOT NULL CHECK (b BETWEEN 0 AND 255),
                a INTEGER NOT NULL CHECK (a BETWEEN 1 AND 255),
                PRIMARY KEY (x, y, z)
            ) WITHOUT ROWID;
            INSERT INTO metadata (key, value) VALUES ('schema_version', '1'), ('N', '1');
            INSERT INTO boxes (x, y, z, r, g, b, a) VALUES
                (0, 0, 0, 128, 64, 32, 255),
                (1, 1, 1, 64, 128, 191, 255);
            """
        )

    with pytest.raises(BoxFormatError, match="unsupported .box schema version 1"):
        load_box(path)


def test_loader_accepts_palette_rows(tmp_path):
    path = tmp_path / "palette.box"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            f"""
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
            CREATE TABLE palette (
                color_id INTEGER PRIMARY KEY,
                r INTEGER NOT NULL,
                g INTEGER NOT NULL,
                b INTEGER NOT NULL,
                a INTEGER NOT NULL,
                UNIQUE (r, g, b, a)
            ) WITHOUT ROWID;
            CREATE TABLE boxes (
                x INTEGER NOT NULL,
                y INTEGER NOT NULL,
                z INTEGER NOT NULL,
                color_id INTEGER NOT NULL REFERENCES palette(color_id),
                PRIMARY KEY (x, y, z)
            ) WITHOUT ROWID;
            INSERT INTO metadata (key, value) VALUES ('schema_version', '{BOX_SCHEMA_VERSION}'), ('N', '1');
            INSERT INTO palette (color_id, r, g, b, a) VALUES (1, 0, 0, 0, 1), (2, 255, 255, 255, 128);
            INSERT INTO boxes (x, y, z, color_id) VALUES (0, 0, 0, 1), (1, 1, 1, 2);
            """
        )

    box_map = load_box(path)

    assert box_map.boxes[(0, 0, 0)] == pytest.approx((0, 0, 0, 1 / 255))
    assert box_map.boxes[(1, 1, 1)] == pytest.approx((1, 1, 1, 128 / 255))


def test_loader_rejects_missing_palette_color(tmp_path):
    path = tmp_path / "missing-color.box"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            f"""
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
            CREATE TABLE palette (
                color_id INTEGER PRIMARY KEY,
                r INTEGER NOT NULL,
                g INTEGER NOT NULL,
                b INTEGER NOT NULL,
                a INTEGER NOT NULL,
                UNIQUE (r, g, b, a)
            ) WITHOUT ROWID;
            CREATE TABLE boxes (
                x INTEGER NOT NULL,
                y INTEGER NOT NULL,
                z INTEGER NOT NULL,
                color_id INTEGER NOT NULL,
                PRIMARY KEY (x, y, z)
            ) WITHOUT ROWID;
            INSERT INTO metadata (key, value) VALUES ('schema_version', '{BOX_SCHEMA_VERSION}'), ('N', '1');
            INSERT INTO boxes (x, y, z, color_id) VALUES (0, 0, 0, 7);
            """
        )

    with pytest.raises(BoxFormatError, match="missing palette color_id"):
        load_box(path)


def test_unused_palette_colors_are_not_saved(tmp_path):
    box_map = BoxMap(
        n=1,
        boxes={
            (0, 0, 0): (1, 0, 0, 1),
            (1, 1, 1): (0, 1, 0, 1),
        },
    )
    path = tmp_path / "compact.box"
    save_box(path, box_map)

    box_map.remove_box((1, 1, 1))
    save_box(path, box_map)

    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT r, g, b, a FROM palette").fetchall() == [(255, 0, 0, 255)]
        assert connection.execute("SELECT x, y, z, color_id FROM boxes").fetchall() == [(0, 0, 0, 1)]


def test_hash_uses_box_content_not_palette_ids_or_unused_colors(tmp_path):
    first = tmp_path / "first.box"
    second = tmp_path / "second.box"
    box_map = BoxMap(n=2, boxes={(1, 2, 3): (255, 0, 0, 255), (0, 0, 0): (0, 128, 255, 64)})
    save_box(first, box_map)

    with sqlite3.connect(second) as connection:
        connection.executescript(
            f"""
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
            CREATE TABLE palette (
                color_id INTEGER PRIMARY KEY,
                r INTEGER NOT NULL,
                g INTEGER NOT NULL,
                b INTEGER NOT NULL,
                a INTEGER NOT NULL,
                UNIQUE (r, g, b, a)
            ) WITHOUT ROWID;
            CREATE TABLE boxes (
                x INTEGER NOT NULL,
                y INTEGER NOT NULL,
                z INTEGER NOT NULL,
                color_id INTEGER NOT NULL,
                PRIMARY KEY (x, y, z)
            ) WITHOUT ROWID;
            INSERT INTO metadata (key, value) VALUES ('schema_version', '{BOX_SCHEMA_VERSION}'), ('N', '2');
            INSERT INTO palette (color_id, r, g, b, a) VALUES
                (10, 255, 0, 0, 255),
                (20, 0, 128, 255, 64),
                (30, 1, 2, 3, 4);
            INSERT INTO boxes (x, y, z, color_id) VALUES
                (1, 2, 3, 10),
                (0, 0, 0, 20);
            """
        )

    assert hash_box_file(first) == hash_box_file(second)
    assert hash_box_file(first) == box_hash(box_map)
    assert len(hash_box_file(first)) == 64


def test_hash_changes_when_box_content_changes():
    base = BoxMap(n=1, boxes={(0, 0, 0): (1, 0, 0, 1)})
    changed_color = BoxMap(n=1, boxes={(0, 0, 0): (0, 1, 0, 1)})
    changed_position = BoxMap(n=1, boxes={(1, 0, 0): (1, 0, 0, 1)})
    changed_n = BoxMap(n=2, boxes={(0, 0, 0): (1, 0, 0, 1)})

    assert box_hash(base) != box_hash(changed_color)
    assert box_hash(base) != box_hash(changed_position)
    assert box_hash(base) != box_hash(changed_n)


def test_loader_rejects_out_of_bounds_boxes(tmp_path):
    path = tmp_path / "bad.box"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
            CREATE TABLE palette (
                color_id INTEGER PRIMARY KEY,
                r INTEGER NOT NULL,
                g INTEGER NOT NULL,
                b INTEGER NOT NULL,
                a INTEGER NOT NULL,
                UNIQUE (r, g, b, a)
            ) WITHOUT ROWID;
            CREATE TABLE boxes (
                x INTEGER NOT NULL,
                y INTEGER NOT NULL,
                z INTEGER NOT NULL,
                color_id INTEGER NOT NULL,
                PRIMARY KEY (x, y, z)
            ) WITHOUT ROWID;
            INSERT INTO metadata (key, value) VALUES ('schema_version', '2'), ('N', '1');
            INSERT INTO palette (color_id, r, g, b, a) VALUES (1, 1, 1, 1, 255);
            INSERT INTO boxes (x, y, z, color_id) VALUES (2, 0, 0, 1);
            """
        )

    with pytest.raises(BoxFormatError):
        load_box(path)


def test_alpha_zero_is_saved_as_a_real_box(tmp_path):
    box_map = BoxMap(n=1, boxes={(0, 0, 0): (1, 0, 0, 0), (1, 1, 1): (0, 1, 0, 1)})
    assert box_map.boxes == {
        (0, 0, 0): (1.0, 0.0, 0.0, 0.0),
        (1, 1, 1): (0.0, 1.0, 0.0, 1.0),
    }

    assert box_map.set_box((1, 1, 1), (0, 1, 0, 0))
    assert box_map.boxes == {
        (0, 0, 0): (1.0, 0.0, 0.0, 0.0),
        (1, 1, 1): (0.0, 1.0, 0.0, 0.0),
    }

    path = tmp_path / "alpha.box"
    save_box(path, box_map)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT r, g, b, a FROM palette ORDER BY r, g, b, a").fetchall() == [
            (0, 255, 0, 0),
            (255, 0, 0, 0),
        ]
        assert connection.execute("SELECT COUNT(*) FROM boxes").fetchone()[0] == 2

    loaded = load_box(path)
    assert loaded.boxes[(0, 0, 0)] == pytest.approx((1.0, 0.0, 0.0, 0.0))
    assert loaded.boxes[(1, 1, 1)] == pytest.approx((0.0, 1.0, 0.0, 0.0))


def test_default_color_uses_255_alpha(tmp_path):
    box_map = BoxMap(n=1)
    assert box_map.set_box((0, 0, 0), (140, 140, 140, 255))

    path = tmp_path / "default.box"
    save_box(path, box_map)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT r, g, b, a FROM palette").fetchone() == (140, 140, 140, 255)
        assert connection.execute("SELECT color_id FROM boxes").fetchone() == (1,)


def test_loader_rejects_json_text_files(tmp_path):
    path = tmp_path / "old-json.box"
    path.write_text('{"N": 1, "boxes": {}}', encoding="utf-8")

    with pytest.raises(BoxFormatError):
        load_box(path)


def test_loader_rejects_non_numeric_schema_version(tmp_path):
    path = tmp_path / "bad-version.box"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
            CREATE TABLE palette (
                color_id INTEGER PRIMARY KEY,
                r INTEGER NOT NULL,
                g INTEGER NOT NULL,
                b INTEGER NOT NULL,
                a INTEGER NOT NULL,
                UNIQUE (r, g, b, a)
            ) WITHOUT ROWID;
            CREATE TABLE boxes (
                x INTEGER NOT NULL,
                y INTEGER NOT NULL,
                z INTEGER NOT NULL,
                color_id INTEGER NOT NULL,
                PRIMARY KEY (x, y, z)
            ) WITHOUT ROWID;
            INSERT INTO metadata (key, value) VALUES ('schema_version', 'dev'), ('N', '1');
            """
        )

    with pytest.raises(BoxFormatError, match="invalid .box schema version"):
        load_box(path)


def test_loader_rejects_unsupported_schema_version(tmp_path):
    path = tmp_path / "unsupported.box"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
            CREATE TABLE palette (
                color_id INTEGER PRIMARY KEY,
                r INTEGER NOT NULL,
                g INTEGER NOT NULL,
                b INTEGER NOT NULL,
                a INTEGER NOT NULL,
                UNIQUE (r, g, b, a)
            ) WITHOUT ROWID;
            CREATE TABLE boxes (
                x INTEGER NOT NULL,
                y INTEGER NOT NULL,
                z INTEGER NOT NULL,
                color_id INTEGER NOT NULL,
                PRIMARY KEY (x, y, z)
            ) WITHOUT ROWID;
            INSERT INTO metadata (key, value) VALUES ('schema_version', '1'), ('N', '1');
            """
        )

    with pytest.raises(BoxFormatError, match="unsupported .box schema version 1"):
        load_box(path)
