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
        self.assertEqual(query["imp_paths"], "1")
        self.assertNotIn("imp_move", query)
        self.assertNotIn("imp_rename", query)
        self.assertNotIn("imp_metadata", query)

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


class CollapseTests(unittest.TestCase):
    def test_collapse_sets_dynamic_name_to_comic_id(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE importresults (Status TEXT, ComicID TEXT, DynamicName TEXT, Volume TEXT)"
        )
        conn.executemany(
            "INSERT INTO importresults VALUES (?,?,?,?)",
            [
                ("Not Imported", "42563", "actioncomics", "2011"),
                ("Not Imported", None, "loose", None),
                ("Imported", "42563", "actioncomics", "2011"),
            ],
        )
        self.assertEqual(mi.collapse_stamped_groups(conn), 1)
        rows = list(conn.execute("SELECT DynamicName, Volume FROM importresults ORDER BY rowid"))
        self.assertEqual(rows[0], ("42563", None))
        self.assertEqual(rows[1], ("loose", None))
        self.assertEqual(rows[2], ("actioncomics", "2011"))


class RemainingPlanTests(unittest.TestCase):
    def test_skips_dumps_foreign_trees_and_short_names(self) -> None:
        self.assertTrue(mi.skip_folder("/comics/Amazing spiderman/The Amazing Spiderman Complete English Comic Collection (1-700)-/part1"))
        self.assertTrue(mi.skip_folder("/comics/ECC Ediciones/Batman"))
        self.assertTrue(mi.skip_folder("/comics/DC Comics/Absolute Superman (2025)/absolute batman"))
        self.assertTrue(mi.skip_folder("/comics/Marvel/All-New Marvel NOW! Previews (2013)"))
        self.assertFalse(mi.skip_folder("/comics/DC New 52/Grayson"))

    def test_seeds_leftover_english_folder_and_skips_claimed_duplicate(self) -> None:
        folders = [
            "/comics/DC New 52/Grayson",
            "/comics/DC New 52/All-Star Western",
            "/comics/DC New 52/Teen Titans (2026)",
            "/comics/DC Comics/Absolute Superman (2025)/absolute batman",
            "/comics/ECC Ediciones/Batman",
        ]
        volumes = [
            {"comicvine_id": 42563, "folder": "/comics/DC New 52/Action Comics (2011)"},
            {"comicvine_id": 77777, "folder": "/comics/DC New 52/Teen Titans (2026)"},
        ]
        claimed = {"/comics/dc comics/all star western (2011)"}
        used = {"42563"}
        plan = mi.remaining_plan(folders, volumes, claimed, used)
        by_folder = {item["folder"]: item for item in plan}
        self.assertIn("/comics/DC New 52/Grayson", by_folder)
        self.assertIsNone(by_folder["/comics/DC New 52/Grayson"]["comicvine_id"])
        self.assertEqual(by_folder["/comics/DC New 52/Grayson"]["comic_year"], "2011")
        self.assertEqual(by_folder["/comics/DC New 52/Teen Titans (2026)"]["comicvine_id"], "77777")
        self.assertNotIn("/comics/DC New 52/All-Star Western", by_folder)
        self.assertNotIn("/comics/DC Comics/Absolute Superman (2025)/absolute batman", by_folder)
        self.assertNotIn("/comics/ECC Ediciones/Batman", by_folder)

    def test_matches_kapowarr_id_when_folder_punctuation_differs(self) -> None:
        folders = ["/comics/DC New 52/frankenstein, agent of s.h.a.d.e."]
        volumes = [
            {"comicvine_id": 42411, "folder": "/comics/DC New 52/frankenstein, agent of s.h.a.d.e"},
        ]
        plan = mi.remaining_plan(folders, volumes, set(), set())
        self.assertEqual(plan[0]["comicvine_id"], "42411")

    def test_seed_rows_group_one_folder(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute(
            """
            CREATE TABLE importresults (
                impID TEXT, ComicName TEXT, ComicYear TEXT, Status TEXT, ImportDate TEXT,
                ComicFilename TEXT, ComicLocation TEXT, WatchMatch TEXT, DisplayName TEXT,
                SRID TEXT, ComicID TEXT, IssueID TEXT, Volume TEXT, IssueNumber TEXT,
                DynamicName TEXT, IssueCount TEXT, implog TEXT
            )
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "Grayson"
            folder.mkdir()
            one = folder / "Grayson 001.cbz"
            two = folder / "Grayson 002.cbz"
            one.write_bytes(b"a")
            two.write_bytes(b"b")
            changed = mi.seed_folder_rows(
                conn,
                "/comics/DC New 52/Grayson",
                [one, two],
                comic_id=None,
                comic_name="Grayson",
                comic_year="2011",
            )
        self.assertEqual(changed, 2)
        dyn = {row[0] for row in conn.execute("SELECT DynamicName FROM importresults")}
        self.assertEqual(dyn, {"folder:/comics/dc new 52/grayson"})


class InstallScriptTests(unittest.TestCase):
    def test_import_script_does_not_rename_or_touch_manga(self) -> None:
        text = (Path(__file__).resolve().parents[1] / "mylar3-import.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("Do not send imp_move=0", text)
        self.assertIn("imp_paths=1", text)
        self.assertIn("imp_move is on. Refusing to import.", text)
        self.assertIn("DELETE FROM importresults WHERE ComicID IS NULL", text)
        self.assertIn("Does not touch manga", text)
        self.assertIn("resume", text)
        self.assertIn("remaining", text)
        self.assertNotIn("docker start comicarr", text)
        self.assertNotIn("/manga", text)

    def test_watch_script_only_resumes_in_place(self) -> None:
        text = (Path(__file__).resolve().parents[1] / "mylar3-import-watch.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("action=massimport", text)
        self.assertIn("Does not send imp_move", text)
        self.assertIn("Does not touch manga", text)
        self.assertIn("slow down cowboy", text)
        self.assertNotIn("|420|", text)
        self.assertNotIn("imp_move=0", text)
        self.assertNotIn("comicScan", text)
        self.assertNotIn("docker start comicarr", text)


if __name__ == "__main__":
    unittest.main()
