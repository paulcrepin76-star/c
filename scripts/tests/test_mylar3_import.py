#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mylar3_import as mi


class ScanQueryTests(unittest.TestCase):
    def test_scan_stays_in_place(self) -> None:
        query = mi.scan_query("/comics/DC New 52/Action Comics (2011)")
        self.assertEqual(query["path"], "/comics/DC New 52/Action Comics (2011)")
        self.assertEqual(query["imp_move"], "0")
        self.assertEqual(query["imp_rename"], "0")
        self.assertEqual(query["imp_paths"], "1")
        self.assertEqual(query["imp_metadata"], "0")
        self.assertEqual(query["autoadd"], "0")

    def test_refuses_manga_and_paths_outside_comics(self) -> None:
        with self.assertRaises(ValueError):
            mi.scan_query("/manga/MPD Psycho")
        with self.assertRaises(ValueError):
            mi.scan_query("/series/Bleach")
        with self.assertRaises(ValueError):
            mi.scan_query("/books/comics")


class StampTests(unittest.TestCase):
    def test_stamps_only_unique_non_imprint_folders(self) -> None:
        volumes = [
            {"comicvine_id": 42563, "folder": "/comics/DC New 52/Action Comics (2011)"},
            {"comicvine_id": 111, "folder": "/comics/DC New 52"},
            {"comicvine_id": 222, "folder": "/comics/shared"},
            {"comicvine_id": 223, "folder": "/comics/shared"},
            {"comicvine_id": 999, "folder": "/manga/MPD Psycho"},
        ]
        updates = dict(mi.stamp_updates(volumes))
        self.assertEqual(updates["42563"], "/comics/DC New 52/Action Comics (2011)/")
        self.assertNotIn("111", updates)
        self.assertNotIn("222", updates)
        self.assertNotIn("223", updates)
        self.assertNotIn("999", updates)

    def test_apply_stamps_only_touches_unstamped_rows(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE importresults (Status TEXT, ComicLocation TEXT, ComicID TEXT)"
        )
        conn.executemany(
            "INSERT INTO importresults VALUES (?,?,?)",
            [
                ("Not Imported", "/comics/DC New 52/Action Comics (2011)/Action Comics (2011) #1.cbz", None),
                ("Not Imported", "/comics/DC New 52/Action Comics (2011)/Action Comics (2011) #2.cbz", "None"),
                ("Imported", "/comics/DC New 52/Action Comics (2011)/old.cbz", None),
                ("Not Imported", "/comics/other/file.cbz", None),
            ],
        )
        changed = mi.apply_stamps(
            conn, [("42563", "/comics/DC New 52/Action Comics (2011)/")]
        )
        self.assertEqual(changed, 2)
        ids = [row[0] for row in conn.execute("SELECT ComicID FROM importresults ORDER BY ComicLocation")]
        self.assertEqual(ids, ["42563", "42563", None, None])


class SnapshotTests(unittest.TestCase):
    def test_detects_moved_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Action Comics (2011)").mkdir()
            keep = root / "Action Comics (2011)" / "Action Comics (2011) #1.cbz"
            keep.write_bytes(b"cbz")
            before = mi.snapshot_paths(root)
            keep.rename(root / "moved.cbz")
            after = mi.snapshot_paths(root)
            diff = mi.snapshot_changed(before, after)
            self.assertFalse(diff["unchanged"])
            self.assertEqual(diff["before"], 1)
            self.assertEqual(diff["after"], 1)


class InstallScriptTests(unittest.TestCase):
    def test_import_script_does_not_rename_or_touch_manga(self) -> None:
        text = (Path(__file__).resolve().parents[1] / "mylar3-import.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("imp_rename=0", text)
        self.assertIn("imp_move=0", text)
        self.assertIn("imp_paths=1", text)
        self.assertIn("DELETE FROM importresults WHERE ComicID IS NULL", text)
        self.assertIn("Does not touch manga", text)
        self.assertNotIn("docker start comicarr", text)
        self.assertNotIn("/manga", text)


if __name__ == "__main__":
    unittest.main()
