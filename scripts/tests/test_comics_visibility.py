#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import comics_visibility as cv

FIXTURE = Path(__file__).parent / "fixtures" / "leroux-comics.json"


class ComicsVisibilityTests(unittest.TestCase):
    def test_last_unraid_snapshot_explains_empty_kapowarr(self) -> None:
        snapshot = cv.snapshot_from_dict(json.loads(FIXTURE.read_text()))
        report = cv.diagnose(snapshot)
        codes = {item.code for item in report.findings}

        self.assertIn("kapowarr_not_running", codes)
        self.assertIn("empty_placeholder_share", codes)
        self.assertIn("omnibus_data_wrong_share", codes)
        self.assertIn("stale_bleach_mount", codes)
        self.assertIn("real_library_at_books", codes)
        self.assertIn("collection_is_split", codes)
        self.assertIn("manga_dwarfs_comics", codes)
        self.assertIn("kapowarr_import_rules", codes)
        self.assertTrue(report.errors())

        text = cv.render(report)
        self.assertIn("Kapowarr is not running", text)
        self.assertIn("/mnt/user/media/book", text)
        self.assertIn("/data is an empty placeholder", text)

    def test_kapowarr_on_empty_omnibus_share(self) -> None:
        snapshot = cv.snapshot_from_dict(json.loads(FIXTURE.read_text()))
        snapshot.containers.append("kapowarr")
        snapshot.mounts.append(
            cv.Mount(container="kapowarr", destination="/comics", source="/mnt/user/omnibus-data/comics")
        )
        report = cv.diagnose(snapshot)
        self.assertTrue(report.has("kapowarr_points_at_empty_share"))
        self.assertFalse(report.has("kapowarr_not_running"))

    def test_kapowarr_comics_root_misses_manga(self) -> None:
        snapshot = cv.snapshot_from_dict(json.loads(FIXTURE.read_text()))
        snapshot.containers.append("kapowarr")
        snapshot.mounts.append(
            cv.Mount(container="kapowarr", destination="/comics", source="/mnt/user/media/book/comics")
        )
        report = cv.diagnose(snapshot)
        self.assertTrue(report.has("kapowarr_comics_only"))
        self.assertFalse(report.has("kapowarr_empty_root"))

    def test_host_path_used_as_container_destination(self) -> None:
        snapshot = cv.Snapshot(
            containers=["kapowarr"],
            mounts=[
                cv.Mount(
                    container="kapowarr",
                    destination="/mnt/user/media/book/comics",
                    source="/mnt/user/media/book/comics",
                )
            ],
            trees=[
                cv.TreeCount(path="/mnt/user/media/book/comics", files=80, exists=True),
                cv.TreeCount(path="/mnt/user/media/book/manga", files=306, exists=True),
            ],
        )
        report = cv.diagnose(snapshot)
        self.assertTrue(report.has("kapowarr_host_path_in_container"))

    def test_count_comic_files_ignores_other_extensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Series" / "Issue").mkdir(parents=True)
            (root / "Series" / "Issue" / "01.cbz").write_bytes(b"x")
            (root / "Series" / "cover.jpg").write_bytes(b"x")
            (root / "readme.txt").write_text("no")
            self.assertEqual(cv.count_comic_files(root), 1)


if __name__ == "__main__":
    unittest.main()
